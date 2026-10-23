"""Tkinter front end for the NinjaTracker-style song editor."""
from __future__ import annotations

import copy
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional

from . import project
from .audio import AudioError, LivePlayer
from .model import (FIRST_NOTE, LAST_NOTE, MAX_COMMANDS, MAX_DURATION, MAX_PATTERN_BYTES,
                    MAX_PATTERNS, MAX_TABLE_ROWS, MIN_DURATION, Command, Pattern, Row, Song,
                    Subtune, Track, TrackItem, note_name)
from .packed import PackError, command_counts, pack
from .psid import DATA_ADDR, write_psid

FONT = ("DejaVu Sans Mono", 11)
HEX = "0123456789abcdef"

# piano keys: lower row starts at C of the current octave, upper row one octave up
LOWER = "zsxdcvgbhnjm,l.;/"
UPPER = "q2w3er5t6y7ui9o0p"


# ---------------------------------------------------------------------------
# generic grid widget
# ---------------------------------------------------------------------------

class Col:
    def __init__(self, title: str, width: int, editable: bool = True):
        self.title, self.width, self.editable = title, width, editable


class Grid(tk.Canvas):
    """Keyboard driven cell grid.  Subclasses supply rows and key handling."""

    ROW_H = 20
    CH_W = 9

    def __init__(self, master, columns: List[Col], app: "App", height=420):
        super().__init__(master, background="#101418", highlightthickness=1,
                         highlightbackground="#444", takefocus=True, height=height)
        self.cols = columns
        self.app = app
        self.cur_row = 0
        self.cur_col = 0
        self.xs = []
        x = 6
        for c in columns:
            self.xs.append(x)
            x += (c.width + 1) * self.CH_W
        self.total_w = x
        self.configure(width=self.total_w + 4)
        self.bind("<Key>", self._key)
        self.bind("<Button-1>", self._click)
        self._focused = False        # focus_get() raises KeyError while a menu is open
        self.bind("<FocusIn>", lambda e: self._set_focus(True))
        self.bind("<FocusOut>", lambda e: self._set_focus(False))
        self.bind("<MouseWheel>", lambda e: self.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.bind("<Button-4>", lambda e: self.yview_scroll(-3, "units"))
        self.bind("<Button-5>", lambda e: self.yview_scroll(3, "units"))

    def _set_focus(self, focused: bool):
        self._focused = focused
        self.redraw()

    # -- to override -------------------------------------------------------
    def nrows(self) -> int:
        return 0

    def text(self, r: int, c: int) -> str:
        return ""

    def style(self, r: int, c: int) -> str:
        """Extra tag: '' normal, 'dim', 'hl'."""
        return ""

    def key(self, ev, r: int, c: int) -> bool:
        return False

    # -- drawing -----------------------------------------------------------
    def redraw(self):
        self.delete("all")
        n = self.nrows()
        has_focus = self._focused
        for r in range(max(n, 1)):
            y = r * self.ROW_H
            if r == self.cur_row and n:
                self.create_rectangle(0, y, self.total_w + 2, y + self.ROW_H,
                                      fill="#1d2630", outline="")
            if n == 0:
                continue
            for c, col in enumerate(self.cols):
                s = self.style(r, c)
                color = {"dim": "#6b7785", "hl": "#ffd166", "err": "#ff6b6b"}.get(s, "#d8dee9")
                if r == self.cur_row and c == self.cur_col:
                    self.create_rectangle(self.xs[c] - 2, y + 1,
                                          self.xs[c] + col.width * self.CH_W + 2, y + self.ROW_H - 1,
                                          fill="#3b6ea5" if has_focus else "#2b3a4a", outline="")
                    color = "#ffffff"
                self.create_text(self.xs[c], y + self.ROW_H // 2, anchor="w",
                                 text=self.text(r, c), fill=color, font=FONT)
        self.configure(scrollregion=(0, 0, self.total_w, max(n, 1) * self.ROW_H + 4))
        self._see()

    def _see(self):
        n = max(self.nrows(), 1)
        top = self.canvasy(0)
        bot = top + self.winfo_height()
        y0 = self.cur_row * self.ROW_H
        y1 = y0 + self.ROW_H
        total = n * self.ROW_H + 4
        if y0 < top:
            self.yview_moveto(y0 / total)
        elif y1 > bot and self.winfo_height() > 1:
            self.yview_moveto((y1 - self.winfo_height()) / total)

    def move(self, dr: int = 0, dc: int = 0):
        n = self.nrows()
        if n:
            self.cur_row = min(max(self.cur_row + dr, 0), n - 1)
        self.cur_col = min(max(self.cur_col + dc, 0), len(self.cols) - 1)
        self.redraw()

    def clamp(self):
        n = self.nrows()
        self.cur_row = min(self.cur_row, max(n - 1, 0))

    def _click(self, ev):
        self.focus_set()
        r = int(self.canvasy(ev.y) // self.ROW_H)
        if 0 <= r < self.nrows():
            self.cur_row = r
        for c in range(len(self.cols)):
            if ev.x >= self.xs[c] - 3:
                self.cur_col = c
        self.redraw()

    def _key(self, ev):
        if ev.state & 0x4 and ev.keysym.lower() in ("z", "y", "s", "o", "n", "q", "e"):
            return None                      # global shortcuts handled by the app
        r, c = self.cur_row, self.cur_col
        if self.nrows() and self.key(ev, r, c):
            self.app.after_edit()
            self.redraw()
            return "break"
        k = ev.keysym
        if k == "Up": self.move(-1)
        elif k == "Down": self.move(1)
        elif k == "Left": self.move(0, -1)
        elif k == "Right": self.move(0, 1)
        elif k == "Prior": self.move(-16)
        elif k == "Next": self.move(16)
        elif k == "Home": self.cur_row = 0; self.redraw()
        elif k == "End": self.cur_row = max(self.nrows() - 1, 0); self.redraw()
        elif k == "Tab": self.move(0, 1 if self.cur_col < len(self.cols) - 1 else 0)
        else:
            return None
        return "break"

    # -- helpers for subclasses ---------------------------------------------
    @staticmethod
    def hexdigit(ev) -> Optional[int]:
        ch = ev.char.lower() if ev.char else ""
        return HEX.index(ch) if ch and ch in HEX else None


# ---------------------------------------------------------------------------
# table / command editors
# ---------------------------------------------------------------------------

def _arp_text(r: int) -> str:
    if r == 0:
        return ""
    if r >= 0x80:
        code = r - 0x80
        return f"abs {note_name(code)}" if FIRST_NOTE <= code <= LAST_NOTE else "abs ??"
    return f"+{r}"


def wave_desc(l: int, r: int) -> str:
    if l == 0xFF:
        return f"jump -> {r:02X}" if r else "stop"
    if l >= 0xE0:
        return f"slide {(l - 0xE0) << 8 | r:04X}"
    if l >= 0xC0:
        return f"vibrato spd {l - 0xC0} depth {r}"
    if l >= 0x90:
        return f"delay {l - 0x90}fr {_arp_text(r)}"
    return f"wave {l:02X} {_arp_text(r)}"


def pulse_desc(l: int, r: int) -> str:
    if l == 0xFF:
        return f"jump -> {r:02X}" if r else "stop"
    if l >= 0x80:
        lo = ((r << 4) | (r >> 4)) & 0xFF
        return f"set pw {lo | (lo & 15) << 8:03X}"
    if l == 0:
        return ""
    return f"mod {l}fr by {r - 256 if r >= 128 else r}"


def filt_desc(l: int, r: int) -> str:
    if l == 0xFF:
        return f"jump -> {r:02X}" if r else "stop"
    if l >= 0x80:
        mode = "".join(n for b, n in ((0x10, "LP"), (0x20, "BP"), (0x40, "HP")) if l & b)
        voices = "".join(str(i + 1) for i in range(3) if l & (1 << i))
        return f"{mode or '--'} res {l >> 4:X} voices {voices or '-'} cut {r:02X}"
    if l == 0:
        return ""
    return f"cutoff mod {l}fr by {r - 256 if r >= 128 else r}"


class TableGrid(Grid):
    def __init__(self, master, app, which: str, describe: Callable[[int, int], str]):
        super().__init__(master, [Col("Pos", 3, False), Col("L", 2), Col("R", 2),
                                  Col("Meaning", 34, False)], app)
        self.which, self.describe = which, describe
        self.cur_col = 1

    @property
    def rows(self):
        return getattr(self.app.song, self.which)

    def nrows(self):
        return len(self.rows) + 1            # one spare row at the end

    def text(self, r, c):
        rows = self.rows
        if r >= len(rows):
            return f"{r + 1:02X}" if c == 0 else ("" if c < 3 else "(new row)")
        l, rr = rows[r]
        return [f"{r + 1:02X}", f"{l:02X}", f"{rr:02X}", self.describe(l, rr)][c]

    def style(self, r, c):
        return "dim" if c == 0 or r >= len(self.rows) or c == 3 else ""

    def key(self, ev, r, c):
        rows = self.rows
        k = ev.keysym
        if k == "Insert":
            self.app.push_undo()
            rows.insert(min(r, len(rows)), (0, 0))
            return True
        if k == "Delete" and r < len(rows):
            self.app.push_undo()
            del rows[r]
            self.clamp()
            return True
        if c not in (1, 2):
            return False
        d = self.hexdigit(ev)
        if d is not None:
            self.app.push_undo()
            if r >= len(rows):
                if len(rows) >= MAX_TABLE_ROWS:
                    return True
                rows.append((0, 0))
            l, rr = rows[r]
            if c == 1:
                l = ((l << 4) | d) & 0xFF
            else:
                rr = ((rr << 4) | d) & 0xFF
            rows[r] = (l, rr)
            return True
        if k == "BackSpace" and r < len(rows):
            self.app.push_undo()
            l, rr = rows[r]
            rows[r] = (0, rr) if c == 1 else (l, 0)
            return True
        return False


class CommandGrid(Grid):
    def __init__(self, master, app):
        super().__init__(master, [Col("#", 2, False), Col("Name", 12), Col("AD", 2), Col("SR", 2),
                                  Col("Wv", 2), Col("Pu", 2), Col("Fl", 2)], app)
        self.cur_col = 2

    def nrows(self):
        return MAX_COMMANDS

    def cmd(self, r) -> Command:
        cs = self.app.song.commands
        return cs[r] if r < len(cs) else Command(ad=0, sr=0)

    def text(self, r, c):
        k = self.cmd(r)
        used = r < len(self.app.song.commands)
        return [f"{r + 1:02X}", k.name, f"{k.ad:02X}" if used else "..", f"{k.sr:02X}" if used else "..",
                f"{k.wave:02X}" if used else "..", f"{k.pulse:02X}" if used else "..",
                f"{k.filt:02X}" if used else ".."][c]

    def style(self, r, c):
        if c == 0 or r >= len(self.app.song.commands):
            return "dim"
        return ""

    def key(self, ev, r, c):
        s = self.app.song
        if c == 1:
            if ev.keysym == "BackSpace":
                self.app.push_undo()
                s.command(r + 1).name = s.command(r + 1).name[:-1]
                return True
            if ev.char and ev.char.isprintable() and len(self.cmd(r).name) < 12:
                self.app.push_undo()
                k = s.command(r + 1)
                k.name += ev.char
                return True
            return False
        d = self.hexdigit(ev)
        if d is None or c < 2:
            return False
        self.app.push_undo()
        k = s.command(r + 1)
        attr = ["ad", "sr", "wave", "pulse", "filt"][c - 2]
        setattr(k, attr, ((getattr(k, attr) << 4) | d) & 0xFF)
        return True


# ---------------------------------------------------------------------------
# pattern editor
# ---------------------------------------------------------------------------

class PatternGrid(Grid):
    def __init__(self, master, app):
        super().__init__(master, [Col("Row", 3, False), Col("Note", 3), Col("Cmd", 2),
                                  Col("Dur", 2), Col("Name", 12, False)], app)
        self.cur_col = 1

    @property
    def pattern(self) -> Pattern:
        return self.app.song.pattern(self.app.cur_pattern)

    def nrows(self):
        return len(self.pattern.rows) + 1

    def text(self, r, c):
        rows = self.pattern.rows
        if r >= len(rows):
            return f"{r:02d}" if c == 0 else ("" if c != 1 else "")
        row = rows[r]
        if c == 0:
            return f"{r:02d}"
        if c == 1:
            if row.note is not None:
                return note_name(row.note)
            return {"on": "+++", "off": "---", None: "..."}[row.gate]
        if c == 2:
            return "--" if row.cmd is None else f"{row.cmd | (0x80 if row.legato else 0):02X}"
        if c == 3:
            return "--" if row.dur is None else f"{row.dur:02d}"
        if row.cmd is not None:
            cs = self.app.song.commands
            return cs[row.cmd - 1].name if row.cmd <= len(cs) else ""
        return ""

    def style(self, r, c):
        rows = self.pattern.rows
        if r >= len(rows):
            return "dim"
        row = rows[r]
        if c == 0 or c == 4:
            return "dim"
        if c == 1 and row.note is None and row.gate == "on":
            return "dim"
        if c == 2 and row.cmd is None or c == 3 and row.dur is None:
            return "dim"
        return ""

    def _ensure(self, r) -> Row:
        rows = self.pattern.rows
        while len(rows) <= r:
            rows.append(Row())
        return rows[r]

    def key(self, ev, r, c):
        a = self.app
        rows = self.pattern.rows
        k = ev.keysym
        if k == "Insert":
            a.push_undo()
            rows.insert(min(r, len(rows)), Row())
            return True
        if k == "Delete" and r < len(rows):
            a.push_undo()
            del rows[r]
            self.clamp()
            return True
        if c == 1:
            ch = ev.char.lower() if ev.char else ""
            if k == "space" and not ev.state & 0x1 or k == "Return":
                a.push_undo()
                row = self._ensure(r)
                row.note, row.gate = None, "off"
                self.move_down_after()
                return True
            if k == "space" or ch == "=":
                a.push_undo()
                row = self._ensure(r)
                row.note, row.gate = None, "on"
                self.move_down_after()
                return True
            if k == "BackSpace" and r < len(rows):
                a.push_undo()
                rows[r] = Row(dur=rows[r].dur, cmd=rows[r].cmd, legato=rows[r].legato, gate="on")
                return True
            idx = LOWER.find(ch) if ch else -1
            idx2 = UPPER.find(ch) if ch else -1
            semis = idx if idx >= 0 else (idx2 + 12 if idx2 >= 0 else -1)
            if semis >= 0:
                code = FIRST_NOTE + (a.octave - 1) * 12 + semis
                if FIRST_NOTE <= code <= LAST_NOTE:
                    a.push_undo()
                    row = self._ensure(r)
                    row.note, row.gate = code, None
                    prev = self._last_cmd(r)
                    if row.cmd is None and prev != a.cur_cmd:
                        row.cmd, row.legato = a.cur_cmd, False
                    self.move_down_after()
                    return True
            return False
        if c == 2:
            d = self.hexdigit(ev)
            if d is not None:
                a.push_undo()
                row = self._ensure(r)
                cur = 0 if row.cmd is None else (row.cmd | (0x80 if row.legato else 0))
                cur = ((cur << 4) | d) & 0xFF
                row.legato = bool(cur & 0x80)
                row.cmd = (cur & 0x7F) or None
                if row.cmd is None:
                    row.legato = False
                else:
                    a.cur_cmd = row.cmd
                if row.note is None and row.gate is None and row.cmd is None:
                    row.gate = "on"
                return True
            if k == "BackSpace" and r < len(rows):
                a.push_undo()
                rows[r].cmd, rows[r].legato = None, False
                if rows[r].note is None and rows[r].gate is None:
                    rows[r].gate = "on"
                return True
        if c == 3:
            ch = ev.char
            if ch and ch.isdigit():
                a.push_undo()
                row = self._ensure(r)
                cur = row.dur or 0
                cur = (cur * 10 + int(ch)) % 100
                row.dur = min(max(cur, MIN_DURATION), MAX_DURATION) if cur >= 10 else cur or None
                if row.dur is not None and row.dur < MIN_DURATION:
                    row.dur = MIN_DURATION if cur else None
                return True
            if k == "BackSpace" and r < len(rows):
                a.push_undo()
                rows[r].dur = None
                return True
            if ch in ("+", "-") and r < len(rows) and rows[r].dur is not None:
                a.push_undo()
                rows[r].dur = min(max(rows[r].dur + (1 if ch == "+" else -1), MIN_DURATION), MAX_DURATION)
                return True
        return False

    def move_down_after(self):
        self.cur_row = self.cur_row + 1

    def _last_cmd(self, r) -> Optional[int]:
        for row in reversed(self.pattern.rows[:r]):
            if row.cmd is not None:
                return row.cmd
        return None


# ---------------------------------------------------------------------------
# track (song order) editor
# ---------------------------------------------------------------------------

class TrackGrid(Grid):
    def __init__(self, master, app, voice: int):
        super().__init__(master, [Col("Pos", 2, False), Col("Item", 4), Col("", 2, False)], app)
        self.voice = voice
        self.cur_col = 1

    @property
    def track(self) -> Track:
        return self.app.subtune().tracks[self.voice]

    def nrows(self):
        return len(self.track.items) + 1

    def text(self, r, c):
        items = self.track.items
        if r >= len(items):
            return f"{r:02X}" if c == 0 else ("" if c == 1 else "")
        it = items[r]
        if c == 0:
            return f"{r:02X}"
        if c == 1:
            return f"{it.value:02X}" if it.kind == "pat" else f"{it.value:+d}"
        return "<-L" if self.track.loop == r else ""

    def style(self, r, c):
        items = self.track.items
        if r >= len(items) or c != 1:
            return "dim" if c != 1 or r >= len(items) else ""
        return "hl" if items[r].kind == "trans" else ""

    def key(self, ev, r, c):
        a = self.app
        t = self.track
        k, ch = ev.keysym, (ev.char or "")
        if k == "Insert":
            a.push_undo()
            t.items.insert(min(r, len(t.items)), TrackItem("pat", a.cur_pattern))
            if t.loop >= r and len(t.items) > 1:
                t.loop += 1
            return True
        if k == "Delete" and r < len(t.items):
            a.push_undo()
            del t.items[r]
            if t.loop > r or t.loop >= len(t.items):
                t.loop = max(0, min(t.loop - (1 if t.loop > r else 0), len(t.items) - 1))
            self.clamp()
            return True
        if k == "Return" and r < len(t.items) and t.items[r].kind == "pat":
            a.goto_pattern(t.items[r].value)
            return True
        if ch.lower() == "l" and r < len(t.items):
            a.push_undo()
            t.loop = r
            return True
        if ch.lower() == "t":
            a.push_undo()
            self._ensure(r)
            t.items[r] = TrackItem("trans", 0)
            return True
        if ch.lower() == "p":
            a.push_undo()
            self._ensure(r)
            t.items[r] = TrackItem("pat", a.cur_pattern)
            return True
        if ch in ("+", "-") and r < len(t.items):
            a.push_undo()
            it = t.items[r]
            step = 1 if ch == "+" else -1
            if it.kind == "trans":
                it.value = min(max(it.value + step, -63), 64)
            else:
                it.value = min(max(it.value + step, 1), MAX_PATTERNS)
            return True
        d = self.hexdigit(ev)
        if d is not None:
            a.push_undo()
            self._ensure(r)
            it = t.items[r]
            if it.kind == "pat":
                it.value = ((it.value << 4) | d) & 0xFF
                if it.value > MAX_PATTERNS or it.value == 0:
                    it.value = d or 1
                a.cur_pattern = it.value
            return True
        return False

    def _ensure(self, r):
        t = self.track
        while len(t.items) <= r:
            t.items.append(TrackItem("pat", self.app.cur_pattern))


# ---------------------------------------------------------------------------
# main application
# ---------------------------------------------------------------------------

HELP = {
    "song": "Hex digits: pattern no.   t: transpose   p: pattern   +/-: change value   l: loop point   "
            "Enter: open pattern   Ins/Del: insert/delete",
    "pattern": "Note column: piano keys (z s x d c v ... / q 2 w 3 e ...), Space: key-off, Shift+Space or =: key-on, "
               "BackSpace: clear   Cmd: hex (80+ = legato)   Dur: decimal frames   Ins/Del: rows   "
               "F1-F8: octave",
    "commands": "Hex digits edit AD SR and the wave/pulse/filter table positions (1-based, 00 = unchanged)",
    "wave": "L/R hex.  L 00-8F waveform (R = arpeggio), 90-BF delay, C0-DF vibrato, E0-FE slide, FF jump.  Ins/Del rows",
    "pulse": "L 01-7F modulate for n frames (R signed speed), 80-FE set pulse (R, nibble-swapped), FF jump",
    "filt": "L 01-7F modulate cutoff, 80-FE set mode/res/voices (R = cutoff), FF jump",
    "info": "",
}


class App(tk.Tk):
    def __init__(self, path: Optional[str] = None):
        super().__init__()
        self.title("NinjaTracker editor")
        self.geometry("920x640")
        self.song = Song.new()
        self.path: Optional[str] = None
        self.dirty = False
        self.undo: List[Song] = []
        self.redo: List[Song] = []
        self.cur_pattern = 1
        self.cur_cmd = 1
        self.cur_subtune = 0
        self.octave = 4
        self.player = LivePlayer()
        self.sid_6581 = tk.BooleanVar(value=True)

        self._menu()
        self._layout()
        self.bind("<Control-z>", lambda e: self.do_undo())
        self.bind("<Control-y>", lambda e: self.do_redo())
        self.bind("<Control-s>", lambda e: self.save())
        self.bind("<Control-o>", lambda e: self.open_project())
        self.bind("<Control-n>", lambda e: self.new())
        self.bind("<F9>", lambda e: self.play_song())
        self.bind("<F10>", lambda e: self.play_pattern())
        self.bind("<F12>", lambda e: self.stop())
        for i in range(1, 8):
            self.bind(f"<F{i}>", lambda e, i=i: self.set_octave(i))
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        if path:
            self._open(path)
        self.refresh_all()

    # -- layout ---------------------------------------------------------------
    def _boxed(self, parent, grid: "Grid", title: str = ""):
        """Pack grid with a column header line, a scrollbar and optional title."""
        box = ttk.Frame(parent)
        box.pack(side="left", fill="y", padx=6, pady=6)
        if title:
            ttk.Label(box, text=title).pack()
        hdr = " ".join(c.title.ljust(c.width) for c in grid.cols)
        ttk.Label(box, text=hdr, font=FONT, foreground="#666").pack(anchor="w", padx=(10, 0))
        row = ttk.Frame(box)
        row.pack(fill="both", expand=True)
        grid.pack(in_=row, side="left", fill="y")
        tk.Misc.lift(grid)                      # created before `row`, would be hidden behind it
        sb = ttk.Scrollbar(row, command=grid.yview)
        sb.pack(side="left", fill="y")
        grid.configure(yscrollcommand=sb.set)
        return grid

    def _menu(self):
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="New", accelerator="Ctrl+N", command=self.new)
        f.add_command(label="Open project...", accelerator="Ctrl+O", command=self.open_project)
        f.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        f.add_command(label="Save as...", command=self.save_as)
        f.add_separator()
        f.add_command(label="Import packed data (.bin)...", command=self.import_bin)
        f.add_command(label="Import SID made by this editor...", command=self.import_sid)
        f.add_separator()
        f.add_command(label="Export SID...", command=self.export_sid)
        f.add_command(label="Export WAV...", command=self.export_wav)
        f.add_separator()
        f.add_command(label="Quit", command=self.quit_app)
        m.add_cascade(label="File", menu=f)
        e = tk.Menu(m, tearoff=0)
        e.add_command(label="Undo", accelerator="Ctrl+Z", command=self.do_undo)
        e.add_command(label="Redo", accelerator="Ctrl+Y", command=self.do_redo)
        m.add_cascade(label="Edit", menu=e)
        p = tk.Menu(m, tearoff=0)
        p.add_command(label="Play song", accelerator="F9", command=self.play_song)
        p.add_command(label="Play current pattern", accelerator="F10", command=self.play_pattern)
        p.add_command(label="Stop", accelerator="F12", command=self.stop)
        p.add_separator()
        p.add_checkbutton(label="SID model 6581 (off = 8580)", variable=self.sid_6581)
        m.add_cascade(label="Play", menu=p)
        self.config(menu=m)

    def _layout(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text="Subtune").pack(side="left")
        self.sub_var = tk.IntVar(value=1)
        ttk.Spinbox(top, from_=1, to=16, width=3, textvariable=self.sub_var,
                    command=self._subtune_changed).pack(side="left", padx=4)
        ttk.Label(top, text="Pattern").pack(side="left", padx=(12, 0))
        self.pat_var = tk.IntVar(value=1)
        ttk.Spinbox(top, from_=1, to=MAX_PATTERNS, width=4, textvariable=self.pat_var,
                    command=self._pattern_changed).pack(side="left", padx=4)
        ttk.Label(top, text="Command").pack(side="left", padx=(12, 0))
        self.cmd_var = tk.IntVar(value=1)
        ttk.Spinbox(top, from_=1, to=MAX_COMMANDS, width=4, textvariable=self.cmd_var,
                    command=self._cmd_changed).pack(side="left", padx=4)
        self.oct_label = ttk.Label(top, text="Octave 4")
        self.oct_label.pack(side="left", padx=12)
        ttk.Button(top, text="Play song (F9)", command=self.play_song).pack(side="right")
        ttk.Button(top, text="Pattern (F10)", command=self.play_pattern).pack(side="right", padx=4)
        ttk.Button(top, text="Stop (F12)", command=self.stop).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6)
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._tab_changed())

        self.tab_song = ttk.Frame(self.nb)
        self.track_grids = []
        for v in range(3):
            self.track_grids.append(self._boxed(self.tab_song, TrackGrid(self.tab_song, self, v),
                                                f"Voice {v + 1}"))
        self.nb.add(self.tab_song, text="Song")

        self.tab_pat = ttk.Frame(self.nb)
        self.pat_grid = self._boxed(self.tab_pat, PatternGrid(self.tab_pat, self))
        self.pat_info = ttk.Label(self.tab_pat, justify="left", anchor="nw")
        self.pat_info.pack(side="left", fill="both", padx=12, pady=6)
        self.nb.add(self.tab_pat, text="Patterns")

        self.tab_cmd = ttk.Frame(self.nb)
        self.cmd_grid = self._boxed(self.tab_cmd, CommandGrid(self.tab_cmd, self))
        self.nb.add(self.tab_cmd, text="Commands")

        self.table_grids = {}
        for which, label, desc in (("wave", "Wave", wave_desc), ("pulse", "Pulse", pulse_desc),
                                   ("filt", "Filter", filt_desc)):
            fr = ttk.Frame(self.nb)
            g = self._boxed(fr, TableGrid(fr, self, which, desc))
            self.table_grids[which] = g
            self.nb.add(fr, text=label)

        self.tab_info = ttk.Frame(self.nb)
        self._info_tab()
        self.nb.add(self.tab_info, text="Info")

        self.help = ttk.Label(self, anchor="w", wraplength=900)
        self.help.pack(fill="x", padx=8, pady=(4, 0))
        self.status = ttk.Label(self, anchor="w", relief="sunken")
        self.status.pack(fill="x", padx=6, pady=4)

    def _info_tab(self):
        f = self.tab_info
        self.info_vars = {}
        for i, (key, label) in enumerate((("title", "Title"), ("author", "Author"),
                                          ("released", "Released"))):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="e", padx=6, pady=4)
            v = tk.StringVar()
            e = ttk.Entry(f, textvariable=v, width=40)
            e.grid(row=i, column=1, sticky="w")
            v.trace_add("write", lambda *a, k=key, v=v: self._info_edit(k, v))
            self.info_vars[key] = v
        for i, (key, label) in enumerate((("hr_param", "Hard-restart SR (hex)"),
                                          ("first_wave", "First-frame waveform (hex)")), start=3):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="e", padx=6, pady=4)
            v = tk.StringVar()
            ttk.Entry(f, textvariable=v, width=6).grid(row=i, column=1, sticky="w")
            v.trace_add("write", lambda *a, k=key, v=v: self._info_edit(k, v, True))
            self.info_vars[key] = v
        self.report = tk.Text(f, height=14, width=80, font=FONT, state="disabled")
        self.report.grid(row=6, column=0, columnspan=2, padx=6, pady=8, sticky="w")
        self._info_lock = False

    # -- state helpers ---------------------------------------------------------
    def subtune(self) -> Subtune:
        while len(self.song.subtunes) <= self.cur_subtune:
            self.song.subtunes.append(Subtune())
        return self.song.subtunes[self.cur_subtune]

    def push_undo(self):
        self.undo.append(copy.deepcopy(self.song))
        del self.undo[:-100]
        self.redo.clear()
        self.dirty = True

    def after_edit(self):
        self.dirty = True
        self.pat_var.set(self.cur_pattern)
        self.cmd_var.set(self.cur_cmd)
        self.update_status()

    def do_undo(self):
        if self.undo:
            self.redo.append(self.song)
            self.song = self.undo.pop()
            self.refresh_all()

    def do_redo(self):
        if self.redo:
            self.undo.append(self.song)
            self.song = self.redo.pop()
            self.refresh_all()

    def set_octave(self, o):
        self.octave = o
        self.oct_label.config(text=f"Octave {o}")

    def goto_pattern(self, n):
        self.cur_pattern = n
        self.pat_var.set(n)
        self.nb.select(self.tab_pat)
        self.pat_grid.cur_row = 0
        self.refresh_all()
        self.pat_grid.focus_set()

    def _subtune_changed(self):
        try:
            self.cur_subtune = min(max(self.sub_var.get() - 1, 0), 15)
        except tk.TclError:
            return
        for g in self.track_grids:
            g.cur_row = 0
        self.refresh_all()

    def _pattern_changed(self):
        try:
            self.cur_pattern = min(max(self.pat_var.get(), 1), MAX_PATTERNS)
        except tk.TclError:
            return
        self.pat_grid.cur_row = 0
        self.refresh_all()

    def _cmd_changed(self):
        try:
            self.cur_cmd = min(max(self.cmd_var.get(), 1), MAX_COMMANDS)
        except tk.TclError:
            pass

    def _tab_changed(self):
        names = ["song", "pattern", "commands", "wave", "pulse", "filt", "info"]
        self.help.config(text=HELP[names[self.nb.index(self.nb.select())]])
        self.refresh_all()

    # -- refresh -----------------------------------------------------------------
    def refresh_all(self):
        for g in self.track_grids:
            g.clamp(); g.redraw()
        self.pat_grid.clamp(); self.pat_grid.redraw()
        self.cmd_grid.redraw()
        for g in self.table_grids.values():
            g.clamp(); g.redraw()
        self._info_lock = True
        for k in ("title", "author", "released"):
            self.info_vars[k].set(getattr(self.song, k))
        self.info_vars["hr_param"].set(f"{self.song.hr_param:02X}")
        self.info_vars["first_wave"].set(f"{self.song.first_wave:02X}")
        self._info_lock = False
        self.update_status()
        self.title(f"NinjaTracker editor - {self.path or 'untitled'}{' *' if self.dirty else ''}")

    def _info_edit(self, key, var, hexval=False):
        if getattr(self, "_info_lock", True):
            return
        txt = var.get()
        if hexval:
            try:
                setattr(self.song, key, int(txt, 16) & 0xFF)
            except ValueError:
                return
        else:
            setattr(self.song, key, txt)
        self.dirty = True

    def validate(self) -> List[str]:
        s = self.song
        msgs = []
        ncmd, nleg = command_counts(s)
        for i, p in enumerate(s.patterns, 1):
            try:
                p.encode()
            except ValueError as e:
                msgs.append(f"pattern {i}: {e}")
        for si, st in enumerate(s.subtunes, 1):
            for vi, t in enumerate(st.tracks, 1):
                for it in t.items:
                    if it.kind == "pat" and (it.value > len(s.patterns) or not s.patterns[it.value - 1].rows):
                        msgs.append(f"subtune {si} voice {vi}: pattern {it.value:02X} is empty")
                if t.items and t.items[-1].kind == "trans":
                    msgs.append(f"subtune {si} voice {vi}: track ends with a transpose")
        for i in range(nleg):
            c = s.commands[i] if i < len(s.commands) else Command()
            for attr, n in (("wave", len(s.wave)), ("pulse", len(s.pulse)), ("filt", len(s.filt))):
                if getattr(c, attr) > n:
                    msgs.append(f"command {i + 1:02X}: {attr} pointer {getattr(c, attr):02X} beyond table end")
        for name, tbl in (("wave", s.wave), ("pulse", s.pulse), ("filter", s.filt)):
            for i, (l, r) in enumerate(tbl, 1):
                if l == 0xFF and r > len(tbl):
                    msgs.append(f"{name} table row {i:02X}: jump target {r:02X} beyond table end")
        try:
            pack(s)
        except (PackError, ValueError) as e:
            msgs.append(f"export: {e}")
        return msgs

    def update_status(self):
        s = self.song
        pat = s.pattern(self.cur_pattern)
        try:
            n = len(pat.encode())
        except ValueError:
            n = -1
        self.pat_info.config(text=f"Pattern {self.cur_pattern:02X}\n{len(pat.rows)} rows\n"
                                  f"{n if n >= 0 else '?'}/{MAX_PATTERN_BYTES} bytes")
        try:
            size = len(pack(s, DATA_ADDR))
            sz = f"data {size} bytes (${DATA_ADDR:04X}-${DATA_ADDR + size:04X})"
        except (PackError, ValueError) as e:
            sz = f"cannot export: {e}"
        self.status.config(text=f"{sz}   octave {self.octave}   command {self.cur_command_text()}")
        msgs = self.validate()
        self.report.config(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("end", f"{sz}\n\n" + ("\n".join(msgs) if msgs else "No problems found."))
        self.report.config(state="disabled")

    def cur_command_text(self):
        cs = self.song.commands
        name = cs[self.cur_cmd - 1].name if self.cur_cmd <= len(cs) else ""
        return f"{self.cur_cmd:02X} {name}"

    # -- file operations -----------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return messagebox.askyesno("Unsaved changes", "Discard unsaved changes?")

    def new(self):
        if self._confirm_discard():
            self._set_song(Song.new(), None)

    def _set_song(self, song: Song, path):
        self.stop()
        self.song, self.path, self.dirty = song, path, False
        self.undo.clear(); self.redo.clear()
        self.cur_pattern = self.cur_cmd = 1
        self.cur_subtune = 0
        self.sub_var.set(1); self.pat_var.set(1); self.cmd_var.set(1)
        self.refresh_all()

    def _open(self, path):
        try:
            if path.lower().endswith(".sid"):
                song = project.load_sid(path)
                self._set_song(song, None)
            elif path.lower().endswith(".bin"):
                self._set_song(project.load_packed(path), None)
            else:
                self._set_song(project.load_project(path), path)
        except Exception as e:
            messagebox.showerror("Open failed", str(e))

    def open_project(self):
        if not self._confirm_discard():
            return
        p = filedialog.askopenfilename(filetypes=[("Projects", "*.nt2.json *.json"), ("All", "*")])
        if p:
            self._open(p)

    def import_bin(self):
        if not self._confirm_discard():
            return
        p = filedialog.askopenfilename(filetypes=[("NinjaTracker packed data", "*.bin"), ("All", "*")])
        if p:
            self._open(p)

    def import_sid(self):
        if not self._confirm_discard():
            return
        p = filedialog.askopenfilename(filetypes=[("SID", "*.sid")])
        if p:
            self._open(p)

    def save(self):
        if not self.path:
            return self.save_as()
        try:
            project.save_project(self.song, self.path)
            self.dirty = False
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def save_as(self):
        p = filedialog.asksaveasfilename(defaultextension=".nt2.json",
                                         filetypes=[("Projects", "*.nt2.json"), ("JSON", "*.json")])
        if p:
            self.path = p
            self.save()

    def export_sid(self):
        msgs = [m for m in self.validate() if m.startswith("export") or "empty" in m]
        if msgs:
            messagebox.showerror("Cannot export", "\n".join(msgs))
            return
        p = filedialog.asksaveasfilename(defaultextension=".sid", filetypes=[("SID", "*.sid")])
        if p:
            try:
                write_psid(self.song, p)
                self.status.config(text=f"wrote {p}")
            except Exception as e:
                messagebox.showerror("Export failed", str(e))

    def export_wav(self):
        from .emu import render, write_wav
        p = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV", "*.wav")])
        if not p:
            return
        try:
            self.config(cursor="watch"); self.update_idletasks()
            write_wav(p, render(self.song, self.cur_subtune, 60.0, self.sid_6581.get()))
            self.status.config(text=f"wrote {p} (60 s)")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
        finally:
            self.config(cursor="")

    # -- playback --------------------------------------------------------------------
    def _start(self, song: Song, subtune: int):
        try:
            self.player.start(song, subtune, self.sid_6581.get(),
                              on_error=lambda m: self.after(0, lambda: self.status.config(text=m)))
            self.after(300, self._check_player)
        except (AudioError, ValueError, PackError) as e:
            messagebox.showerror("Cannot play", str(e))

    def _check_player(self):
        if self.player.error:
            self.status.config(text=self.player.error)

    def play_song(self):
        self.focus_set()
        self._start(self.song, self.cur_subtune)

    def play_pattern(self):
        s = copy.deepcopy(self.song)
        s.subtunes = [Subtune([Track([TrackItem("trans", 0), TrackItem("pat", self.cur_pattern)], 0),
                               Track(), Track()])]
        self._start(s, 0)

    def stop(self):
        self.player.stop()

    def quit_app(self):
        if self._confirm_discard():
            self.stop()
            self.destroy()


def main(argv=None):
    import sys
    argv = sys.argv[1:] if argv is None else argv
    App(argv[0] if argv else None).mainloop()


if __name__ == "__main__":
    main()
