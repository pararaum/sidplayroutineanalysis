# Analysis: C64 SID players, NinjaTracker V2 and Blackbird

Background research behind `ntedit`. Sources analysed: the
`c64_6581_sid_players/` repository (22 ACME sources of original and
reverse-engineered players), `ninjatr204.zip` (NinjaTracker V2.04, Cadaver /
Covert Bitops) and `blackbird-1.2.zip` (Blackbird tracker with Birdcruncher
exporter). Statements marked *(verified)* were checked by decoding data or by
running code; the rest come from reading source and comments.

## 1. What all the players have in common

Every player is a routine called once per video frame (50 Hz PAL) from a raster
or CIA interrupt. Each call:

1. Ticks a tempo or duration counter. The song only advances every N frames; on the
   frames in between, per-frame effects run (vibrato, slides, arpeggio, pulse-width
   modulation, ADSR or waveform sequencing).
2. Steps through the song data of three voices: a track or order list per voice that
   points to patterns, which are byte streams of note, duration and
   instrument/command bytes.
3. Converts notes to SID registers: a 16-bit frequency table to `$D400-$D414`,
   waveform plus gate to the control register, ADSR, pulse width.
4. Handles filter and volume (`$D415-$D418`).

State is kept in per-voice arrays indexed by X (0, 7, 14 = SID voice offsets);
zero page and self-modifying code are used for speed.

## 2. The players in `c64_6581_sid_players/`

| Author / file | Notable design |
|---|---|
| Rob Hubbard (Commando, Monty on the Run) | Track per voice points to patterns; note byte carries a length plus a legato bit; instruments have effect flags (pulse sweep, vibrato, drum, arpeggio); pitch-bend byte; status byte for init/stop/mute. `$FF` = restart, `$FE` = stop in track data. |
| Charles Deenen / M.O.N. / Scoop (Cybernoid II, Armada, Dutch Breeze, test tunes, SFX player) | "MUSICFILE V01-07-1988": separate routines for tone/wave/pulse arpeggio, vibrato, glide, tone sweep, filter. The SFX player is a step-table engine with start/repeat/end statements. |
| Jeroen Kimmel, Johannes Bjerregaard (Myth) | Same Dutch M.O.N. / TurboAssembler family. `Bjerregaard_J_James_Bond_3.asm` is an empty file. |
| Adam Bulka / FAME (Sound Routine f 4.1.0) | German comments; voices have roles (bass drum, filtered snare, main); mode bits select table mode (`$80`) or arpeggio mode (`$C0`); high nibble selects filter position. |
| Matt Gray (Dominator, Driller), Fred Gray (Mutants) | MGEdit "Player V4.2" with a drum table; Mutants is a work in progress. |
| David Whittaker (Panther) | Per-voice handlers; command byte covers notes, effects, arpeggio flag, duration, ADSR. |
| Jonathan Dunn / Paul Hughes (D. Thompson '88, Ocean Loader 5) | Ocean/Imagine engine: `TUNE` with X = tune number, `REFRESH` every frame. |
| Martin Galway (Arkanoid, Rambo loader) | Per-voice stack of return addresses with repeat counts (patterns can call subroutines); 4-bit digitised sample channel through `$D418`. |
| Audial Arts / Francois Prijt ("zong player" v1, v2) | Disk-demo era track/pattern/instrument players. |

The files carry PSID headers, so ACME builds `.sid` files directly.

## 3. NinjaTracker V2 in detail

Cadaver, 2013. Editor (`src/`, DASM) plus a standalone "gamemusic" play routine
(`nt2play.s`, about 400 bytes of code).

### 3.1 Data model

- Up to 16 subtunes x 3 voices. Each subtune's tracks total at most 256 bytes.
- Shared by all subtunes: 127 patterns (max 192 bytes each incl. terminator), 127
  commands, one wave, one pulse and one filter table (max 255 rows each).
- Track bytes: `00 pos` = loop to absolute position; `01-7F` = play pattern;
  `80-FF` = set transpose. A transpose must be followed by a pattern (never by the loop).
- Command = ADSR + wave/pulse/filter table pointers (1-based; 0 = leave unchanged).
  Acts as an instrument when used with a note, or as a general command without one.
  Legato use (cmd `81-FF`) skips hard restart, first-frame waveform and ADSR.
- Tables have two columns (left selects the function, right is the parameter):
  - Wave: `00-8F` set waveform with arpeggio in the right column (`00-7F`
    relative, `8C-DF` absolute note); `90-BF` delay the arpeggio; `C0-DF` vibrato;
    `E0-FE` slide to target pitch (then jumps to the last "set waveform" step); `FF` jump.
  - Pulse: `01-7F` modulate for n frames by signed speed; `80-FE` set pulse; `FF` jump.
  - Filter: same shape; `80-FE` sets passband/resonance (left, shared nibble),
    voices (low bits) and cutoff (right). One filter, global to all voices.

### 3.2 Pattern bytes *(verified against the example tune)*

Row = first byte, optional command byte, optional duration byte; `00` ends the pattern.

- First byte: bit 0 = command byte follows; note code = `byte >> 1`, real notes are
  codes 12-95 (C-1..B-7, first byte `>= $18`).
- Gate bytes (`< $18`): bit 1 = no command follows, bit 2 = key-on. The editor
  emits `$06` (+++, also the empty row), `$0A` (---), `$04`/`$08` with command;
  `$01` = command-only row. `$00` cannot be used (terminator).
- Command byte: `1-7F`, or `|$80` for legato.
- Duration byte `>= $C0`: frames = `258 - byte` (3..65). Optional; the last duration persists.

### 3.3 Timing *(verified by emulation)*

Each voice has a counter incremented every frame. On wrap to 0 the next row is read
and the hard restart (gate off, SR = HR param) is done. At counter = 2 the new
note and command are initialised and the counter is reloaded from the duration
byte. A row therefore lasts exactly `258 - durbyte` frames and the hard restart
falls in the first two frames of the row.

### 3.4 Wave/pulse execution

Wave table is stepped once per frame per voice; the right column adds to the
voice's note (relative) or replaces it (absolute); the result indexes a 84-entry
frequency table (`$022D` = C-1 up to B-7). Pulse writes the same byte to
`$D402` and `$D403`, which is why the editor stores values nibble-swapped
(`pulse_to_play`); negative modulation speeds are decremented by one. Vibrato speed
is stored xor `$1F`. Both conversions are in `ntedit/packed.py`.

### 3.5 Transpose *(player semantics verified; editor readme differs)*

Effective offset = `(byte + 1)` as a signed 7-bit value; `$FF` is neutral. The
example tune uses `$FD`, `$FB`, `$84` meaning -2, -4, +5 semitones. The
readme says "`C0` = zero", which does not match the player code.

### 3.6 Packed "gamemusic" layout *(verified: byte-exact round trip)*

```
6 bytes   header: wave len, pulse len, filter len, #commands, #commands incl.
          legato-only, #patterns
wave L | wave R | pulse time | pulse speed | filter time | filter speed
          (1-based tables; entry 0 not stored)
cmd AD | cmd SR                       (non-legato commands only)
cmd wave | pulse | filter pointers    (all commands)
pattern address low bytes, then high bytes  (absolute addresses)
song table, 5 bytes per subtune: track addr lo/hi, 00, len(v1), len(v1)+len(v2)
pattern data, then track data
```

The player is relocated by `nt_newmusic`, which patches 21 operand addresses in
its own code from the header lengths, so the block works at any address as
long as the absolute addresses inside it match. Empty patterns take 0 bytes. `nt_doinit`
falls through into `nt_playsong` (A = `$FF` afterwards disables re-init).
`NT_PLAYSFX` plays one-shot effects (format: SR, AD, pulse, then note/wave pairs, `00`) with a priority
rule based on the data address; `ins2nt2.exe` converts GoatTracker instruments to this.

### 3.7 Song files (`*.nt2`) *(verified on two real songs)*

`N2` tag, then the editor's song memory (`savesongstart..savesongend` in `nt2songdata.s`,
31975 bytes) with an RLE: `$BF value count` for every run of 2+ equal bytes (count up to
255), literal `$BF` as `$BF $BF $01`. Memory order: six 256-byte table columns in editor
representation, 127 x 192 patterns (same encoding as the packed data), 16 x 256 tracks,
five 127-byte command arrays, 127 x 10 command names, 48 track lengths, 3 table lengths,
command count, hard-restart SR, first-frame waveform. Implemented in `ntedit/nt2file.py`.

## 4. Blackbird 1.2 and how it differs

Modern tracker with a cross-platform exporter (`birdcruncher`, C source in the zip)
that writes SID, runnable PRG, or "distributed" file sets.

| | NinjaTracker V2 | Blackbird 1.2 |
|---|---|---|
| Song structure | Variable-length patterns, track list per voice | One-bar tracks per voice referenced from a song grid, with transposition |
| Time | Per-row duration in frames | Rows plus global tempo and groove (swing), delay codes |
| Pitch | Semitones, wave-table arpeggio/vibrato/slide | Quarter-tone units; per-note "effect" table (arpeggios are effects) |
| Instrument | Command + wave/pulse/filter pointers | ADSR + hard-restart mode (0/1/2), wavetable (also does pulse width), optional 3-byte-per-row filter table |
| Limits | 255 rows per table | 48 instruments, 48 effects, 255-byte wave table, 252-byte filter table |
| Data in player | Raw, relocated by address patching | Compressed (literal/copy-with-transpose stream), unpacked a few bytes per frame |
| CPU | Not bounded | At most 18 raster lines per frame, work split over prepare1-3/execute |

Shared ideas: per-voice state, hard restart two frames before a note,
table-driven per-frame sequencing. Blackbird shares one pitch value between track
note and effect, so the note cannot change without restarting the effect.
Not examined: `cruncher.c` and the Blackbird song-file format.

## 5. Why NinjaTracker was chosen as the basis for `ntedit`

Small, fully documented source for both editor and player; flat data layout that
is easy to generate from Python; relocation by patching rather than a stream
compressor. The editor reproduces the packer so that exported SIDs run the
unmodified original player.
