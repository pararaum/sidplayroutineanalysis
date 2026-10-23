# ntedit

> The project lives in the `ntedit/` subdirectory of this repository; all paths below are
> relative to it (`cd ntedit`). The package itself is `ntedit/ntedit/`.

A small Tkinter editor for **NinjaTracker V2** style C64 music (Cadaver /
Covert Bitops), with real-time playback and PSID export.

* `ntedit/model.py`  – song model (patterns, commands, wave/pulse/filter tables, tracks)
* `ntedit/packed.py` – bit-exact reader/writer of NinjaTracker's packed "gamemusic" data
* `ntedit/nt2file.py` – reader/writer of NinjaTracker's own song files (`*.nt2`)
* `ntedit/psid.py`   – PSID export (play routine + packed data)
* `ntedit/emu.py`    – runs the real 6502 play routine in py65 and renders the SID writes with reSID (pyresidfp)
* `ntedit/audio.py`  – real-time playback through sounddevice
* `ntedit/gui.py`    – the editor
* `player/`          – NinjaTracker's play routine ported to ca65 (`make -C player` rebuilds
                       `ntedit/player.bin`/`player.lbl`, which are committed)

## Running

    cd ntedit
    python3 -m venv --system-site-packages .venv      # needs python3-tk
    .venv/bin/pip install numpy py65 pyresidfp sounddevice pytest
    .venv/bin/python -m ntedit [file.nt2 | file.nt2.json | file.bin | file.sid]

Keys: F9 play song, F10 play current pattern, F12 stop, F1-F7 octave, Ctrl+Z/Y undo/redo,
Ctrl+S save.  Each tab shows its own key help at the bottom.
Piano keys in the pattern note column: `z s x d c v g b h n j m` (lower octave), `q 2 w 3 e r 5 t 6 y 7 u` (upper).

Projects are JSON (`*.nt2.json`).  *File > Export SID* writes a PSID v2 (PAL, 6581)
whose player is at $1000 and data at $14D3.  SIDs written by this editor can be
re-imported. Songs saved by the original C64 NinjaTracker (`*.nt2`) can be imported (*File > Import NinjaTracker song*,
or pass the file on the command line) and exported again (*File > Export NinjaTracker song*), including command
names; original NinjaTracker "gamemusic" `.bin` files (address stripped, base $1000) can be imported too.

## Tests

    cd ntedit
    .venv/bin/python -m pytest tests
    PYTHONPATH=. xvfb-run -a .venv/bin/python tests/gui_smoke.py    # headless GUI check

`tests/test_emu.py` checks that the register stream of this player matches the original
dasm-built player (running the original data) frame for frame.

## Format notes (see `ntedit/packed.py` for the layout; full analysis in `docs/ANALYSIS.md`)

* Row length in frames = 258 - duration byte (3..65); a hard restart happens in the two
  frames before a note.
* Transpose byte = `$80 | ((semitones - 1) & $7F)`, so `$FF` is neutral.
* Pulse table speeds and wave vibrato speeds are stored converted for the play routine
  (nibble swap / xor $1F); the model keeps the editor representation.
