"""Project (JSON) persistence and import of packed data / our own SID files."""
from __future__ import annotations

import json
import struct
from pathlib import Path

from .model import (Command, Pattern, Row, Song, Subtune, Track, TrackItem)
from .packed import unpack

FORMAT = "ntedit-project-1"


def song_to_dict(s: Song) -> dict:
    return {
        "format": FORMAT,
        "title": s.title, "author": s.author, "released": s.released,
        "hr_param": s.hr_param, "first_wave": s.first_wave,
        "wave": [list(r) for r in s.wave],
        "pulse": [list(r) for r in s.pulse],
        "filt": [list(r) for r in s.filt],
        "commands": [[c.ad, c.sr, c.wave, c.pulse, c.filt, c.name] for c in s.commands],
        "patterns": [[[r.note, r.gate, r.cmd, r.legato, r.dur] for r in p.rows]
                     for p in s.patterns],
        "subtunes": [[{"loop": t.loop, "items": [[i.kind, i.value] for i in t.items]}
                      for t in st.tracks] for st in s.subtunes],
    }


def song_from_dict(d: dict) -> Song:
    if d.get("format") != FORMAT:
        raise ValueError("not an ntedit project file")
    s = Song(title=d["title"], author=d["author"], released=d["released"],
             hr_param=d["hr_param"], first_wave=d["first_wave"])
    s.wave = [tuple(r) for r in d["wave"]]
    s.pulse = [tuple(r) for r in d["pulse"]]
    s.filt = [tuple(r) for r in d["filt"]]
    s.commands = [Command(*c) for c in d["commands"]]
    s.patterns = [Pattern([Row(*r) for r in p]) for p in d["patterns"]]
    s.subtunes = [Subtune([Track([TrackItem(k, v) for k, v in t["items"]], t["loop"])
                           for t in st]) for st in d["subtunes"]]
    return s


def save_project(song: Song, path) -> None:
    Path(path).write_text(json.dumps(song_to_dict(song), indent=1))


def load_project(path) -> Song:
    return song_from_dict(json.loads(Path(path).read_text()))


def load_packed(path, base: int = 0x1000) -> Song:
    """Load a NinjaTracker 'gamemusic' data block (load address stripped)."""
    return unpack(Path(path).read_bytes(), base)


def load_sid(path) -> Song:
    """Load a SID written by ntedit (player + packed data)."""
    from .psid import DATA_ADDR, LOAD_ADDR, INIT_ADDR
    raw = Path(path).read_bytes()
    if raw[:4] != b"PSID":
        raise ValueError("not a PSID file")
    off = struct.unpack(">H", raw[6:8])[0]
    load, init = struct.unpack(">HH", raw[8:12])
    body = raw[off:]
    if load == 0:
        load = struct.unpack("<H", body[:2])[0]
        body = body[2:]
    if load != LOAD_ADDR or init != INIT_ADDR:
        raise ValueError("SID was not produced by this editor (different player)")
    song = unpack(body[DATA_ADDR - load:], DATA_ADDR)
    song.title = raw[0x16:0x36].split(b"\0")[0].decode("latin-1")
    song.author = raw[0x36:0x56].split(b"\0")[0].decode("latin-1")
    song.released = raw[0x56:0x76].split(b"\0")[0].decode("latin-1")
    return song


def load_any(path) -> Song:
    """Load a song by file extension (.nt2, .json project, .bin, .sid)."""
    from .nt2file import load_nt2
    low = str(path).lower()
    if low.endswith(".nt2"):
        return load_nt2(path)
    if low.endswith(".sid"):
        return load_sid(path)
    if low.endswith(".bin"):
        return load_packed(path)
    return load_project(path)
