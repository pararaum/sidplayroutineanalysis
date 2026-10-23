"""Song model for NinjaTracker V2 style music.

Values are kept in the *editor* representation of NinjaTracker 2 (the packer
in packed.py converts to / from the play routine's representation).

Table positions and pattern/command numbers are 1-based exactly like in the
original editor: position 0 means "none / stop".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

MAX_SUBTUNES = 16
MAX_PATTERNS = 127
MAX_COMMANDS = 127
MAX_PATTERN_BYTES = 192          # including the 00 terminator
MAX_TRACK_BYTES = 256            # all three voices of a subtune together
MAX_TABLE_ROWS = 255

FIRST_NOTE = 12                  # note code of C-1; code 95 = B-7
LAST_NOTE = 95
MIN_DURATION = 3                 # frames
MAX_DURATION = 65

NOTE_NAMES = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "B-"]


def note_name(code: int) -> str:
    n = code - FIRST_NOTE
    return f"{NOTE_NAMES[n % 12]}{n // 12 + 1}"


def parse_note(text: str) -> Optional[int]:
    """'C-4' / 'C#4' / 'c4' -> note code, None if it does not parse."""
    t = text.strip().upper()
    if len(t) < 2:
        return None
    name, octave = t[:-1], t[-1]
    if not octave.isdigit():
        return None
    if len(name) == 1:
        name += "-"
    if name not in NOTE_NAMES:
        return None
    code = NOTE_NAMES.index(name) + (int(octave) - 1) * 12 + FIRST_NOTE
    return code if FIRST_NOTE <= code <= LAST_NOTE else None


@dataclass
class Row:
    """One pattern row.

    note   : note code FIRST_NOTE..LAST_NOTE, or None
    gate   : only when note is None.  'on' (+++, also used for empty rows),
             'off' (---) or None for a command-only row.
    cmd    : command number 1..127 or None (None = keep the last command)
    legato : use the command in legato mode (no hard restart / ADSR)
    dur    : new row duration in frames (3..65) or None to keep the last one
    """
    note: Optional[int] = None
    gate: Optional[str] = "on"
    cmd: Optional[int] = None
    legato: bool = False
    dur: Optional[int] = None

    def __post_init__(self):
        if self.note is not None:
            self.gate = None
        elif self.gate is None and self.cmd is None:
            self.gate = "on"

    def validate(self):
        if self.note is not None and not FIRST_NOTE <= self.note <= LAST_NOTE:
            raise ValueError(f"note {self.note} out of range")
        if self.note is None and self.gate not in ("on", "off", None):
            raise ValueError("bad gate")
        if self.cmd is not None and not 1 <= self.cmd <= MAX_COMMANDS:
            raise ValueError(f"command {self.cmd} out of range")
        if self.legato and self.cmd is None:
            raise ValueError("legato needs a command")
        if self.dur is not None and not MIN_DURATION <= self.dur <= MAX_DURATION:
            raise ValueError(f"duration {self.dur} out of range")

    def encode(self) -> bytes:
        self.validate()
        has_cmd = 1 if self.cmd is not None else 0
        if self.note is not None:
            out = [(self.note << 1) | has_cmd]
        elif self.gate is None:
            out = [0x01]
        elif self.gate == "off":
            out = [0x08 if has_cmd else 0x0A]
        else:
            out = [0x04 if has_cmd else 0x06]
        if has_cmd:
            out.append(self.cmd | (0x80 if self.legato else 0))
        if self.dur is not None:
            out.append(258 - self.dur)
        return bytes(out)


@dataclass
class Pattern:
    rows: List[Row] = field(default_factory=list)

    def encode(self) -> bytes:
        if not self.rows:
            return b""
        data = b"".join(r.encode() for r in self.rows) + b"\x00"
        if len(data) > MAX_PATTERN_BYTES:
            raise ValueError(f"pattern too long ({len(data)} bytes, max {MAX_PATTERN_BYTES})")
        return data

    @staticmethod
    def decode(data: bytes) -> "Pattern":
        rows: List[Row] = []
        i = 0
        while i < len(data) and data[i] != 0:
            b = data[i]
            i += 1
            has_cmd = b & 1
            note = gate = None
            if b >= 0x18:
                note = b >> 1
                gate = None
            elif b == 0x01:
                gate = None
            else:
                # gate byte: bit 1 = no command follows, bit 2 = key-on
                gate = "on" if b & 0x04 else "off"
                has_cmd = 0 if b & 0x02 else 1
            cmd, legato, dur = None, False, None
            if has_cmd:
                c = data[i]
                i += 1
                legato = bool(c & 0x80)
                cmd = c & 0x7F
            if i < len(data) and data[i] >= 0xC0:
                dur = 258 - data[i]
                i += 1
            rows.append(Row(note, gate, cmd, legato, dur))
        return Pattern(rows)

    def byte_size(self) -> int:
        return len(self.encode())


@dataclass
class Command:
    """Instrument / command: ADSR plus wave, pulse and filter table pointers."""
    ad: int = 0x09
    sr: int = 0x00
    wave: int = 0
    pulse: int = 0
    filt: int = 0
    name: str = ""


@dataclass
class TrackItem:
    """kind 'pat' (value = pattern 1..127) or 'trans' (value = semitones)."""
    kind: str
    value: int

    def encode(self) -> int:
        if self.kind == "pat":
            if not 1 <= self.value <= MAX_PATTERNS:
                raise ValueError(f"pattern {self.value} out of range")
            return self.value
        if not -63 <= self.value <= 64:
            raise ValueError(f"transpose {self.value} out of range")
        return 0x80 | ((self.value - 1) & 0x7F)

    @staticmethod
    def decode(byte: int) -> "TrackItem":
        if byte < 0x80:
            return TrackItem("pat", byte)
        v = (byte & 0x7F) + 1
        return TrackItem("trans", v - 128 if v > 64 else v)


@dataclass
class Track:
    items: List[TrackItem] = field(default_factory=list)
    loop: int = 0                # index into items the track loops to

    def validate(self):
        if not self.items:
            return
        if not 0 <= self.loop < len(self.items):
            raise ValueError("loop position out of range")
        if self.items[-1].kind == "trans":
            raise ValueError("a track cannot end with a transpose (loop must follow a pattern)")


@dataclass
class Subtune:
    tracks: List[Track] = field(default_factory=lambda: [Track(), Track(), Track()])

    def is_empty(self) -> bool:
        return all(not t.items for t in self.tracks)


@dataclass
class Song:
    title: str = "Untitled"
    author: str = ""
    released: str = ""
    # table rows are (left, right) pairs, list index i is table position i+1
    wave: List[Tuple[int, int]] = field(default_factory=list)
    pulse: List[Tuple[int, int]] = field(default_factory=list)
    filt: List[Tuple[int, int]] = field(default_factory=list)
    commands: List[Command] = field(default_factory=list)   # index i is command i+1
    patterns: List[Pattern] = field(default_factory=list)   # index i is pattern i+1
    subtunes: List[Subtune] = field(default_factory=lambda: [Subtune()])
    hr_param: int = 0x00         # SR value written during hard restart
    first_wave: int = 0x09       # waveform written on the first frame of a note

    # -- helpers -------------------------------------------------------------
    def command(self, n: int) -> Command:
        while len(self.commands) < n:
            self.commands.append(Command())
        return self.commands[n - 1]

    def pattern(self, n: int) -> Pattern:
        while len(self.patterns) < n:
            self.patterns.append(Pattern())
        return self.patterns[n - 1]

    @staticmethod
    def new() -> "Song":
        """A small starting point: one audible instrument and one pattern."""
        s = Song()
        s.wave = [(0x41, 0x00), (0xFF, 0x01)]          # pulse wave, loop to itself
        s.pulse = [(0x80, 0x08), (0xFF, 0x01)]                # fixed width, loop
        s.commands = [Command(ad=0x08, sr=0xA9, wave=1, pulse=1, name="Pulse")]
        s.patterns = [Pattern([
            Row(note=48, cmd=1, dur=12), Row(), Row(note=55), Row(),
            Row(note=51), Row(), Row(gate="off"), Row(),
        ])]
        s.subtunes = [Subtune([
            Track([TrackItem("trans", 0), TrackItem("pat", 1)], loop=0),
            Track(), Track(),
        ])]
        return s
