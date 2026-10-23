"""PSID export: wraps the cc65-built play routine and a packed song."""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Dict, List, Tuple

from .model import Song
from .packed import pack

PKG = Path(__file__).parent
LOAD_ADDR = 0x1000


def _labels() -> Dict[str, int]:
    out = {}
    for line in (PKG / "player.lbl").read_text().splitlines():
        _, addr, name = line.split()
        out[name.lstrip(".")] = int(addr, 16)
    return out


LABELS = _labels()
INIT_ADDR = LABELS["init_entry"]
PLAY_ADDR = LABELS["play_entry"]
DATA_ADDR = LABELS["nt_end"]


def build_image(song: Song) -> Tuple[int, bytes]:
    """Return (load address, memory image) with player and packed song."""
    code = bytearray((PKG / "player.bin").read_bytes())
    code[LABELS["nt_hrparam"] - LOAD_ADDR + 1] = song.hr_param & 0xFF
    code[LABELS["nt_firstwave"] - LOAD_ADDR + 1] = song.first_wave & 0xFF
    assert LOAD_ADDR + len(code) == DATA_ADDR
    data = pack(song, DATA_ADDR)
    if DATA_ADDR + len(data) > 0xD000:
        raise ValueError("song too large for the C64 memory map")
    return LOAD_ADDR, bytes(code) + data


def _field(text: str) -> bytes:
    return text.encode("latin-1", "replace")[:31].ljust(32, b"\0")


def build_psid(song: Song, *, pal: bool = True, model_6581: bool = True) -> bytes:
    load, image = build_image(song)
    nsongs = max(1, max((i + 1 for i, st in enumerate(song.subtunes) if not st.is_empty()), default=1))
    flags = (1 if pal else 2) << 2 | (1 if model_6581 else 2) << 4
    header = b"PSID" + struct.pack(">HHHHHHHI", 2, 0x7C, 0, INIT_ADDR, PLAY_ADDR, nsongs, 1, 0)
    header += _field(song.title) + _field(song.author) + _field(song.released)
    header += struct.pack(">HBBBB", flags, 0, 0, 0, 0)
    assert len(header) == 0x7C
    # load address 0 in the header means "first two bytes of data"
    return header + struct.pack("<H", load) + image


def write_psid(song: Song, path) -> None:
    Path(path).write_bytes(build_psid(song))
