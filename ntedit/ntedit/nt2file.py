"""Reader and writer for NinjaTracker V2 song files (*.nt2).

A file is the ASCII tag "N2" followed by an RLE-coded dump of the editor's song
memory ("savesongstart".."savesongend" in nt2songdata.s), 31975 bytes:

    6 x 256   wave left, wave right (note), pulse time, pulse speed,
              filter time, filter speed        (editor representation)
    127 x 192 patterns (same byte encoding as in the packed data)
    16 x 256  tracks, three voices back to back per subtune
    5 x 127   command AD, SR, wave, pulse, filter pointer
    127 x 10  command names (9 characters, space padded, 00 terminated)
    48        track lengths, 3 per subtune
    3         table lengths: wave, pulse, filter
    1         number of commands
    1         hard restart SR parameter
    1         first frame waveform

RLE: `BF value count` repeats value (used for every run of 2 or more equal
bytes, count 1-255); a literal BF is stored as `BF BF 01`.
"""
from __future__ import annotations

from pathlib import Path

from .model import (MAX_COMMANDS, MAX_PATTERN_BYTES, MAX_PATTERNS, MAX_SUBTUNES, MAX_TABLE_ROWS,
                    Command, Pattern, Song, Subtune)
from .packed import PackError, _decode_track, _prepare, encode_tracks

ESC = 0xBF
TBL = 256
PATT = MAX_PATTERN_BYTES
TRK = 256
NAME_LEN = 9
MEM_SIZE = 6 * TBL + MAX_PATTERNS * PATT + MAX_SUBTUNES * TRK + 5 * MAX_COMMANDS \
    + MAX_COMMANDS * (NAME_LEN + 1) + 3 * MAX_SUBTUNES + 3 + 3

O_TABLES = 0
O_PATT = 6 * TBL
O_TRACKS = O_PATT + MAX_PATTERNS * PATT
O_CMD = O_TRACKS + MAX_SUBTUNES * TRK
O_NAMES = O_CMD + 5 * MAX_COMMANDS
O_SONGLEN = O_NAMES + MAX_COMMANDS * (NAME_LEN + 1)
O_TBLLEN = O_SONGLEN + 3 * MAX_SUBTUNES


def rle_decode(data: bytes) -> bytes:
    if data[:2] != b"N2":
        raise ValueError("not a NinjaTracker 2 song (missing 'N2' tag)")
    out = bytearray()
    i = 2
    while i < len(data):
        if data[i] == ESC:
            if i + 2 >= len(data):
                raise ValueError("truncated RLE block")
            out += bytes([data[i + 1]]) * (data[i + 2] or 256)
            i += 3
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def rle_encode(mem: bytes) -> bytes:
    """The editor's own algorithm (runs capped at 255)."""
    out = bytearray(b"N2")
    i, n = 0, len(mem)
    while i < n:
        b = mem[i]
        if i + 1 < n and mem[i + 1] == b:
            run = 1
            while run < 255 and i + run < n and mem[i + run] == b:
                run += 1
            out += bytes([ESC, b, run])
            i += run
        elif b == ESC:
            out += bytes([ESC, ESC, 1])
            i += 1
        else:
            out.append(b)
            i += 1
    return bytes(out)


def parse(data: bytes) -> Song:
    mem = rle_decode(data)
    if len(mem) != MEM_SIZE:
        raise ValueError(f"unexpected song size {len(mem)} (expected {MEM_SIZE})")
    col = [mem[O_TABLES + i * TBL: O_TABLES + (i + 1) * TBL] for i in range(6)]
    nwave, npulse, nfilt = mem[O_TBLLEN: O_TBLLEN + 3]
    ncmd, hr, first = mem[O_TBLLEN + 3: O_TBLLEN + 6]
    s = Song(hr_param=hr, first_wave=first)
    s.wave = [(col[0][i], col[1][i]) for i in range(nwave)]
    s.pulse = [(col[2][i], col[3][i]) for i in range(npulse)]
    s.filt = [(col[4][i], col[5][i]) for i in range(nfilt)]

    s.commands = []
    for i in range(min(ncmd, MAX_COMMANDS)):
        f = [mem[O_CMD + k * MAX_COMMANDS + i] for k in range(5)]
        nm = mem[O_NAMES + i * (NAME_LEN + 1): O_NAMES + i * (NAME_LEN + 1) + NAME_LEN]
        s.commands.append(Command(*f, name=nm.decode("latin-1").rstrip()))

    pats = []
    for i in range(MAX_PATTERNS):
        pats.append(Pattern.decode(mem[O_PATT + i * PATT: O_PATT + (i + 1) * PATT]))
    while pats and not pats[-1].rows:
        pats.pop()
    s.patterns = pats

    s.subtunes = []
    for i in range(MAX_SUBTUNES):
        l1, l2, l3 = mem[O_SONGLEN + 3 * i: O_SONGLEN + 3 * i + 3]
        base = O_TRACKS + i * TRK
        bounds = [0, l1, l1 + l2, l1 + l2 + l3]
        st = Subtune([_decode_track(mem[base + bounds[v]: base + bounds[v + 1]], bounds[v])
                      for v in range(3)])
        s.subtunes.append(st)
    while len(s.subtunes) > 1 and s.subtunes[-1].is_empty():
        s.subtunes.pop()
    return s


def build(song: Song) -> bytes:
    """Editor memory image (not RLE coded) of song."""
    s = _prepare(song)
    if len(s.subtunes) > MAX_SUBTUNES:
        raise PackError("too many subtunes")
    if len(s.patterns) > MAX_PATTERNS:
        raise PackError("too many patterns")
    if len(s.commands) > MAX_COMMANDS:
        raise PackError("too many commands")
    mem = bytearray(MEM_SIZE)
    tables = [([l for l, _ in s.wave], [r for _, r in s.wave]),
              ([l for l, _ in s.pulse], [r for _, r in s.pulse]),
              ([l for l, _ in s.filt], [r for _, r in s.filt])]
    for t, (left, right) in enumerate(tables):
        if len(left) > MAX_TABLE_ROWS:
            raise PackError("table too long")
        mem[O_TABLES + 2 * t * TBL: O_TABLES + 2 * t * TBL + len(left)] = bytes(left)
        mem[O_TABLES + (2 * t + 1) * TBL: O_TABLES + (2 * t + 1) * TBL + len(right)] = bytes(right)
        mem[O_TBLLEN + t] = len(left)
    for i, p in enumerate(s.patterns):
        enc = p.encode()
        mem[O_PATT + i * PATT: O_PATT + i * PATT + len(enc)] = enc
    for i, st in enumerate(s.subtunes):
        if st.is_empty():
            continue
        blob, lens = encode_tracks(st)
        if len(blob) > TRK:
            raise PackError(f"subtune {i + 1} tracks are {len(blob)} bytes (max {TRK})")
        mem[O_TRACKS + i * TRK: O_TRACKS + i * TRK + len(blob)] = blob
        mem[O_SONGLEN + 3 * i: O_SONGLEN + 3 * i + 3] = bytes(lens)
    for i in range(MAX_COMMANDS):
        c = s.commands[i] if i < len(s.commands) else None
        vals = (c.ad, c.sr, c.wave, c.pulse, c.filt) if c else (0,) * 5
        for k, v in enumerate(vals):
            mem[O_CMD + k * MAX_COMMANDS + i] = v & 0xFF
        name = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in (c.name if c else ""))
        mem[O_NAMES + i * (NAME_LEN + 1): O_NAMES + (i + 1) * (NAME_LEN + 1)] = \
            name[:NAME_LEN].ljust(NAME_LEN).encode("latin-1") + b"\0"
    mem[O_TBLLEN + 3] = len(s.commands)
    mem[O_TBLLEN + 4] = s.hr_param & 0xFF
    mem[O_TBLLEN + 5] = s.first_wave & 0xFF
    return bytes(mem)


def load_nt2(path) -> Song:
    return parse(Path(path).read_bytes())


def save_nt2(song: Song, path) -> None:
    Path(path).write_bytes(rle_encode(build(song)))
