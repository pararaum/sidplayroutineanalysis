"""Assemble the exported .s with cc65 and check it against the binary export."""
import shutil
import subprocess
from pathlib import Path

import pytest

from ntedit.asmexport import export_asm
from ntedit.emu import Player6502, song_player
from ntedit.model import Song
from ntedit.nt2file import load_nt2
from ntedit.packed import pack

DATA = Path(__file__).parent / "data"
pytestmark = pytest.mark.skipif(not (shutil.which("ca65") and shutil.which("ld65")),
                                reason="cc65 not installed")

CFG = """MEMORY { ZP: start = $0080, size = $20, type = rw; RAM: start = $1000, size = $8000, file = %O; }
SEGMENTS { ZEROPAGE: load = ZP, type = zp; CODE: load = RAM, type = rw; RODATA: load = RAM, type = ro; }
"""


def build(tmp_path, song, **kw):
    src = tmp_path / "song.s"
    src.write_text(export_asm(song, **kw))
    (tmp_path / "t.cfg").write_text(CFG)
    run = lambda *a: subprocess.run(a, check=True, capture_output=True, text=True, cwd=tmp_path)
    run("ca65", "-o", "song.o", "song.s")
    run("ld65", "-C", "t.cfg", "-o", "song.bin", "-Ln", "song.lbl", "song.o")
    labels = {}
    for line in (tmp_path / "song.lbl").read_text().splitlines():
        _, addr, name = line.split()
        labels[name.lstrip(".")] = int(addr, 16)
    return (tmp_path / "song.bin").read_bytes(), labels


@pytest.mark.parametrize("name", ["mw4title.nt2", "trueoldskool.nt2"])
def test_data_matches_binary_export(tmp_path, name):
    song = load_nt2(DATA / name)
    image, lab = build(tmp_path, song)
    for sym in ("nt_init", "nt_play", "nt_music", "nt_playsong", "nt_newmusic", "nt_playsfx", "nt_data"):
        assert sym in lab, sym
    base = lab["nt_data"]
    want = pack(song, base)
    assert image[base - 0x1000: base - 0x1000 + len(want)] == want


def test_plays_like_the_psid_export(tmp_path):
    song = load_nt2(DATA / "mw4title.nt2")
    image, lab = build(tmp_path, song)
    ref = song_player(song)
    mine = Player6502(0x1000, image, init=lab["nt_init"], play=lab["nt_play"])
    assert mine.init(0) == ref.init(0)
    for _ in range(1500):
        assert mine.frame() == ref.frame()


def test_settings_and_linker_allocated_zero_page(tmp_path):
    song = Song.new()
    song.hr_param, song.first_wave = 0x0F, 0x01
    text = export_asm(song)
    assert "NT_HRPARAM         = $0F" in text and "NT_FIRSTWAVE       = $01" in text
    assert "nt_zpbase" not in text and '.segment "ZEROPAGE"' in text
    song = load_nt2(DATA / "mw4title.nt2")
    image, lab = build(tmp_path, song)
    p = Player6502(0x1000, image, init=lab["nt_init"], play=lab["nt_play"])
    p.init(0)
    seen = set()
    for _ in range(100):
        p.frame()
        seen |= {a for a in range(0x80, 0xA0) if p.mem[a]} | {a for a in (0xFC, 0xFD) if p.mem[a]}
    # the test linker config puts ZEROPAGE at $80; nothing may touch the old fixed $FC
    assert seen and seen <= {0x80, 0x81}


def test_data_only_links_with_player(tmp_path):
    real = load_nt2(DATA / "trueoldskool.nt2")
    song = Song.new()
    song.hr_param, song.first_wave = real.hr_param, real.first_wave   # settings live in the player
    player_src = export_asm(song, prefix="a")
    data_src = export_asm(real, prefix="b", player=False)
    assert "NT_FIRSTWAVE = $01" in data_src
    (tmp_path / "a.s").write_text(player_src)
    (tmp_path / "b.s").write_text(data_src)
    (tmp_path / "t.cfg").write_text(CFG)
    for f in ("a", "b"):
        subprocess.run(["ca65", "-o", f"{f}.o", f"{f}.s"], check=True, cwd=tmp_path)
    subprocess.run(["ld65", "-C", "t.cfg", "-o", "x.bin", "-Ln", "x.lbl", "a.o", "b.o"],
                   check=True, cwd=tmp_path)
    labels = {l.split()[2].lstrip("."): int(l.split()[1], 16)
              for l in (tmp_path / "x.lbl").read_text().splitlines()}
    assert {"a_init", "b_init", "b_data", "b_numsongs"} <= set(labels)
    image = (tmp_path / "x.bin").read_bytes()
    p = Player6502(0x1000, image, init=labels["b_init"], play=labels["nt_play"])
    ref = song_player(load_nt2(DATA / "trueoldskool.nt2"))
    assert p.init(0) == ref.init(0)
    for _ in range(500):
        assert p.frame() == ref.frame()


def test_bad_arguments():
    with pytest.raises(ValueError):
        export_asm(Song.new(), prefix="1bad")
