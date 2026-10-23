import pytest
from ntedit.model import Row, Pattern, TrackItem, parse_note, note_name, Song, Track, Subtune
from ntedit.packed import pack, unpack, PackError


def test_note_names():
    assert note_name(12) == "C-1" and note_name(95) == "B-7"
    assert parse_note("c-4") == 48 and parse_note("F#2") == 12 + 12 + 6
    assert parse_note("H-1") is None


@pytest.mark.parametrize("row", [
    Row(note=50), Row(note=50, cmd=3, dur=9), Row(note=20, cmd=127, legato=True),
    Row(), Row(gate="off"), Row(gate="off", cmd=2), Row(gate="on", cmd=5, dur=65),
    Row(gate=None, cmd=4, dur=3),
])
def test_row_roundtrip(row):
    got = Pattern.decode(row.encode() + b"\x00").rows
    assert got == [row]


@pytest.mark.parametrize("v", [-63, -2, 0, 1, 5, 64])
def test_transpose_codes(v):
    it = TrackItem("trans", v)
    assert it.encode() >= 0x80 and TrackItem.decode(it.encode()) == it


def test_neutral_transpose_is_ff():
    assert TrackItem("trans", 0).encode() == 0xFF


def test_empty_voices_become_silent_and_pack():
    s = Song.new()
    data = pack(s, 0x1800)
    again = unpack(data, 0x1800)
    assert all(t.items for t in again.subtunes[0].tracks)


def test_limits():
    s = Song.new()
    s.patterns[0].rows = [Row(note=50) for _ in range(200)]      # over 192 bytes
    with pytest.raises(ValueError):
        pack(s)
    with pytest.raises(ValueError):
        Row(dur=2).encode()


def test_track_must_not_end_with_transpose():
    s = Song.new()
    s.subtunes[0].tracks[0] = Track([TrackItem("pat", 1), TrackItem("trans", 3)], 0)
    with pytest.raises(ValueError):
        pack(s)
