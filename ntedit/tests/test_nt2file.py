from pathlib import Path
import pytest
from ntedit.nt2file import MEM_SIZE, build, parse, rle_decode, rle_encode, save_nt2, load_nt2
from ntedit.packed import pack
from ntedit.model import Song

DATA = Path(__file__).parent / "data"
SONGS = ["mw4title.nt2", "trueoldskool.nt2"]


@pytest.mark.parametrize("name", SONGS)
def test_rle_is_exact(name):
    raw = (DATA / name).read_bytes()
    mem = rle_decode(raw)
    assert len(mem) == MEM_SIZE
    assert rle_encode(mem) == raw


@pytest.mark.parametrize("name", SONGS)
def test_roundtrip_is_functionally_exact(name):
    """Only stale bytes behind pattern terminators differ in the memory image."""
    raw = (DATA / name).read_bytes()
    song = parse(raw)
    again = parse(rle_encode(build(song)))
    assert pack(again) == pack(song)
    mem, mem2 = rle_decode(raw), build(song)
    from ntedit.nt2file import O_PATT, O_TRACKS
    diff = [i for i in range(MEM_SIZE) if mem[i] != mem2[i]]
    assert all(O_PATT <= i < O_TRACKS for i in diff)
    assert all(mem2[i] == 0 for i in diff)


@pytest.mark.parametrize("name", SONGS)
def test_contents(name):
    s = parse((DATA / name).read_bytes())
    assert len(s.commands) > 20 and all(c.name for c in s.commands[:5])
    assert all(t.items for t in s.subtunes[0].tracks)
    assert s.first_wave == 1


def test_new_song_and_names(tmp_path):
    s = Song.new()
    s.commands[0].name = "bass+kick"
    save_nt2(s, tmp_path / "a.nt2")
    back = load_nt2(tmp_path / "a.nt2")
    assert back.commands[0].name == "bass+kick"
    assert pack(back) == pack(s)
    # an NT2 song also plays through the whole pipeline
    from ntedit.emu import frames
    assert any(w for w in frames(back, 0, 50))
