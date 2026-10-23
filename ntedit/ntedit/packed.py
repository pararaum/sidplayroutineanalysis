"""Reading and writing NinjaTracker V2 "gamemusic" data blocks.

Layout (all multi-byte addresses are absolute, little endian):

    6 bytes   header: wave, pulse, filter table lengths, number of commands,
              number of commands incl. legato-only ones, number of patterns
    wave left | wave right (note) | pulse time | pulse speed |
    filter time | filter speed                 (tables are 1-based, entry 0 is
                                                not stored)
    command AD | SR      (non-legato commands only)
    command wave | pulse | filter pointers   (all commands)
    pattern address table (low bytes, then high bytes)
    song table, 5 bytes per subtune: track address lo/hi, 00, len(track 1),
                                     len(track 1) + len(track 2)
    pattern data, track data
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .model import (MAX_TABLE_ROWS, MAX_TRACK_BYTES, Command, Pattern, Row, Song,
                    Subtune, Track, TrackItem)


class PackError(ValueError):
    pass


def _swap_nibbles(v: int) -> int:
    return ((v << 4) | (v >> 4)) & 0xFF


# -- table value conversion (editor <-> play routine) --------------------------

def pulse_to_play(left: int, right: int) -> int:
    if left == 0xFF:
        return right
    if left < 0x80:                       # modulation: negative speeds are decremented
        if right & 0x80:
            right -= 1
            if not right & 0x80:
                right = 0x80
    return _swap_nibbles(right)


def pulse_from_play(left: int, play: int) -> int:
    if left == 0xFF:
        return play
    v = _swap_nibbles(play)
    if left < 0x80 and v & 0x80 and v != 0xFF:
        v += 1
    return v


def wave_to_play(left: int) -> int:
    return left ^ 0x1F if 0xC0 <= left < 0xE0 else left


wave_from_play = wave_to_play           # xor is an involution


# -- helpers -------------------------------------------------------------------

def silent_pattern() -> Pattern:
    return Pattern([Row(gate="off", dur=65)])


def _prepare(song: Song) -> Song:
    """Return a copy of song where empty tracks are made silent and loop
    to themselves (an empty track would otherwise run into the next voice)."""
    import copy
    s = copy.deepcopy(song)
    silent_no = None
    for st in s.subtunes:
        if st.is_empty():
            continue
        for tr in st.tracks:
            if tr.items:
                continue
            if silent_no is None:
                for i, p in enumerate(s.patterns):
                    if p.rows == silent_pattern().rows:
                        silent_no = i + 1
                        break
                else:
                    s.patterns.append(silent_pattern())
                    silent_no = len(s.patterns)
            tr.items = [TrackItem("pat", silent_no)]
            tr.loop = 0
    return s


def encode_tracks(st: Subtune) -> Tuple[bytes, Tuple[int, int, int]]:
    """Bytes of a subtune's three tracks (each ending in `00 loop`, loop
    positions absolute within the subtune) and the three track lengths."""
    pos = 0
    blob = bytearray()
    ls = []
    for tr in st.tracks:
        tr.validate()
        offs = []
        seg = bytearray()
        for it in tr.items:
            offs.append(len(seg))
            seg.append(it.encode())
        if not seg:
            raise PackError("empty track")
        if tr.items[-1].kind == "trans":
            raise PackError("track ends with a transpose")
        seg += bytes([0, pos + offs[tr.loop]])
        ls.append(len(seg))
        blob += seg
        pos += len(seg)
    return bytes(blob), (ls[0], ls[1], ls[2])


def command_counts(song: Song) -> Tuple[int, int]:
    """(last command used normally, last command used at all)."""
    last = leg = 0
    for p in song.patterns:
        for r in p.rows:
            if r.cmd is not None:
                if r.legato:
                    leg = max(leg, r.cmd)
                else:
                    last = max(last, r.cmd)
    return last, max(last, leg)


@dataclass
class Layout:
    """The parts of a packed song, before addresses are assigned."""
    song: Song                                  # prepared copy (empty voices filled)
    header: bytes
    tables: List[Tuple[str, bytes]]             # in file order
    patterns: List[bytes]                       # pattern i+1 at index i
    tracks: List[bytes]                         # one blob per subtune
    lens: List[Tuple[int, int, int]]            # track lengths per subtune

    def fixed_size(self) -> int:
        return (len(self.header) + sum(len(b) for _, b in self.tables)
                + 2 * len(self.patterns) + 5 * len(self.tracks))


def layout(song: Song) -> Layout:
    s = _prepare(song)
    for name, t in (("wave", s.wave), ("pulse", s.pulse), ("filter", s.filt)):
        if len(t) > MAX_TABLE_ROWS:
            raise PackError(f"{name} table has {len(t)} rows (max {MAX_TABLE_ROWS})")
    ncmd, nleg = command_counts(s)
    npat = 0
    for i, p in enumerate(s.patterns):
        if p.rows:
            npat = i + 1
    nsongs = 0
    for i, st in enumerate(s.subtunes):
        if not st.is_empty():
            nsongs = i + 1

    pats = [s.patterns[i].encode() for i in range(npat)]
    track_blobs: List[bytes] = []
    lens: List[Tuple[int, int, int]] = []
    for st in s.subtunes[:nsongs]:
        if st.is_empty():
            track_blobs.append(b"")
            lens.append((0, 0, 0))
            continue
        blob, ls = encode_tracks(st)
        if len(blob) > MAX_TRACK_BYTES:
            raise PackError(f"subtune tracks are {len(blob)} bytes (max {MAX_TRACK_BYTES})")
        track_blobs.append(blob)
        lens.append(ls)

    cmds = [s.commands[i] if i < len(s.commands) else Command() for i in range(nleg)]
    tables = [
        ("wave table, waveform / delay / vibrato / slide / jump", bytes(wave_to_play(l) for l, _ in s.wave)),
        ("wave table, note / arpeggio / depth / target", bytes(r for _, r in s.wave)),
        ("pulse table, time / set / jump", bytes(l for l, _ in s.pulse)),
        ("pulse table, speed / value / target", bytes(pulse_to_play(l, r) for l, r in s.pulse)),
        ("filter table, time / set / jump", bytes(l for l, _ in s.filt)),
        ("filter table, speed / cutoff / target", bytes(r for _, r in s.filt)),
        ("command AD", bytes(c.ad for c in cmds[:ncmd])),
        ("command SR", bytes(c.sr for c in cmds[:ncmd])),
        ("command wave table position", bytes(c.wave for c in cmds)),
        ("command pulse table position", bytes(c.pulse for c in cmds)),
        ("command filter table position", bytes(c.filt for c in cmds)),
    ]
    header = bytes([len(s.wave), len(s.pulse), len(s.filt), ncmd, nleg, npat])
    return Layout(s, header, tables, pats, track_blobs, lens)


def pack(song: Song, base: int = 0x1000) -> bytes:
    """Serialise song to a data block that will live at address `base`."""
    lay = layout(song)
    pat_addr = base + lay.fixed_size()
    trk_addr = pat_addr + sum(len(p) for p in lay.patterns)
    out = bytearray(lay.header)
    for _, blk in lay.tables:
        out += blk
    addrs = []
    a = pat_addr
    for p in lay.patterns:
        addrs.append(a)
        a += len(p)
    out += bytes(x & 0xFF for x in addrs)
    out += bytes(x >> 8 for x in addrs)
    a = trk_addr
    for blob, (l1, l2, _l3) in zip(lay.tracks, lay.lens):
        out += bytes([a & 0xFF, a >> 8, 0, l1, l1 + l2])
        a += len(blob)
    for p in lay.patterns:
        out += p
    for blob in lay.tracks:
        out += blob
    return bytes(out)


def unpack(data: bytes, base: int = 0x1000) -> Song:
    """Parse a data block that was packed for address `base`."""
    if len(data) < 6:
        raise PackError("data too short")
    nw, npl, nf, ncmd, nleg, npat = data[:6]
    p = 6

    def take(n):
        nonlocal p
        r = data[p:p + n]
        if len(r) != n:
            raise PackError("data truncated")
        p += n
        return r

    wave_l, wave_r = take(nw), take(nw)
    pul_l, pul_r = take(npl), take(npl)
    fil_l, fil_r = take(nf), take(nf)
    cmd_ad, cmd_sr = take(ncmd), take(ncmd)
    cmd_w, cmd_p, cmd_f = take(nleg), take(nleg), take(nleg)
    plo, phi = take(npat), take(npat)
    paddr = [plo[i] | phi[i] << 8 for i in range(npat)]
    song_tbl_off = p

    # number of subtunes: song table ends where the first pattern/track starts
    if npat:
        content = paddr[0] - base
    else:
        content = (data[p] | data[p + 1] << 8) - base if len(data) > p + 1 else p
    nsongs = (content - song_tbl_off) // 5
    if nsongs < 0 or nsongs > 16:
        raise PackError("cannot determine number of subtunes (wrong base address?)")
    ents = [data[song_tbl_off + 5 * i: song_tbl_off + 5 * i + 5] for i in range(nsongs)]
    taddr = [e[0] | e[1] << 8 for e in ents]
    trk_start = taddr[0] - base if nsongs else len(data)

    s = Song()
    s.wave = [(wave_from_play(wave_l[i]), wave_r[i]) for i in range(nw)]
    s.pulse = [(pul_l[i], pulse_from_play(pul_l[i], pul_r[i])) for i in range(npl)]
    s.filt = [(fil_l[i], fil_r[i]) for i in range(nf)]
    s.commands = [Command(ad=cmd_ad[i] if i < ncmd else 0, sr=cmd_sr[i] if i < ncmd else 0,
                          wave=cmd_w[i], pulse=cmd_p[i], filt=cmd_f[i]) for i in range(nleg)]
    s.patterns = []
    for i in range(npat):
        a = paddr[i] - base
        e = paddr[i + 1] - base if i + 1 < npat else trk_start
        s.patterns.append(Pattern.decode(data[a:e]))
    s.subtunes = []
    for i, e in enumerate(ents):
        a = taddr[i] - base
        end = taddr[i + 1] - base if i + 1 < nsongs else len(data)
        l1, l12 = e[3], e[4]
        bounds = [0, l1, l12, end - a]
        st = Subtune([])
        for v in range(3):
            seg = data[a + bounds[v]: a + bounds[v + 1]]
            st.tracks.append(_decode_track(seg, bounds[v]))
        s.subtunes.append(st)
    return s


def _decode_track(seg: bytes, start: int) -> Track:
    items: List[TrackItem] = []
    offs: List[int] = []
    i = 0
    loop_byte = None
    while i < len(seg):
        b = seg[i]
        if b == 0:
            if i + 1 >= len(seg):
                raise PackError("track ends after loop marker")
            loop_byte = seg[i + 1]
            break
        offs.append(i)
        items.append(TrackItem.decode(b))
        i += 1
    if loop_byte is None:
        return Track(items, 0)
    rel = loop_byte - start
    if rel not in offs:
        raise PackError(f"loop target {loop_byte} is not an item boundary")
    return Track(items, offs.index(rel))
