from pathlib import Path
from ntedit.packed import pack, unpack

DATA = Path(__file__).parent / "data" / "gamemusic.bin"


def test_roundtrip_original_tune():
    raw = DATA.read_bytes()
    song = unpack(raw, 0x1000)
    assert len(song.subtunes) == 2
    assert pack(song, 0x1000) == raw


def test_relocation():
    raw = DATA.read_bytes()
    song = unpack(raw, 0x1000)
    again = unpack(pack(song, 0x2345), 0x2345)
    assert pack(again, 0x1000) == raw


def test_project_and_sid_roundtrip(tmp_path):
    from ntedit.project import save_project, load_project, load_sid
    from ntedit.psid import write_psid
    song = unpack(DATA.read_bytes(), 0x1000)
    song.title, song.author = "T", "A"
    save_project(song, tmp_path / "p.json")
    assert pack(load_project(tmp_path / "p.json")) == pack(song)
    write_psid(song, tmp_path / "s.sid")
    back = load_sid(tmp_path / "s.sid")
    assert pack(back) == pack(song) and back.title == "T"


def test_new_song_packs_and_decodes():
    from ntedit.model import Song
    s = Song.new()
    again = unpack(pack(s, 0x3000), 0x3000)
    assert again.patterns[0].rows == s.patterns[0].rows
