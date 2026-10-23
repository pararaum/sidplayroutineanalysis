from pathlib import Path
import numpy as np
from ntedit.packed import unpack
from ntedit.emu import render, frames
from ntedit.psid import build_psid

DATA = Path(__file__).parent / "data" / "gamemusic.bin"


def test_original_tune_makes_sound():
    song = unpack(DATA.read_bytes(), 0x1000)
    pcm = render(song, 0, 4.0)
    assert len(pcm) > 4 * 44100 * 0.95
    assert np.abs(pcm).max() > 2000


def test_psid_header():
    song = unpack(DATA.read_bytes(), 0x1000)
    sid = build_psid(song)
    assert sid[:4] == b"PSID" and sid[0x0E:0x10] == b"\x00\x02"


def test_register_stream_matches_original_player():
    """SHA-256 of the SID register writes of the ORIGINAL dasm-built
    NinjaTracker player running the original data (2000 frames per subtune).
    Our cc65 build with the data repacked at a different address must match."""
    import hashlib
    golden = {0: "42f60e1aab9c37ef3c968bf4fb58b35a5948dd047643cab1388c2d634e47a876",
              1: "160f2e85212126f6e48dbe7b9f5ec03d0126936ad44d00a43e64040cc5196b32"}
    from ntedit.emu import song_player
    song = unpack(DATA.read_bytes(), 0x1000)
    for sub, want in golden.items():
        p = song_player(song)
        h = hashlib.sha256(repr(p.init(sub)).encode())
        for _ in range(2000):
            h.update(repr(p.frame()).encode())
        assert h.hexdigest() == want


def test_new_song_pitch_and_timing():
    """C-4 (=$1168) first, then G-4 ($1A15) exactly two rows of 12 frames later."""
    from ntedit.model import Song
    seq = []
    for i, w in enumerate(frames(Song.new(), 0, 60)):
        d = dict(w)
        if 0 in d and 1 in d and (not seq or seq[-1][1] != d[1] << 8 | d[0]):
            seq.append((i, d[1] << 8 | d[0]))
    assert seq[0][1] == 0x1168 and seq[1][1] == 0x1A15
    assert seq[1][0] - seq[0][0] == 24
