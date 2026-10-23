"""Headless GUI smoke test: run with  xvfb-run -a python tests/gui_smoke.py"""
import sys
from ntedit.gui import App
from ntedit.model import note_name

app = App()
app.update()
app.nb.select(app.tab_pat); app.update()
g = app.pat_grid
g.focus_force(); app.update()

def press(key, char=""):
    g.event_generate("<Key>", keysym=key)
    app.update()

# overwrite row 0 with an E-4 via piano key 'c' (lower row: C=z D=x E=c)
g.cur_row, g.cur_col = 0, 1
g.event_generate("<KeyPress>", keysym="c"); app.update()
print("row0:", app.song.patterns[0].rows[0])
assert app.song.patterns[0].rows[0].note == 12 + 36 + 4, app.song.patterns[0].rows[0]
app.update()
app.song.patterns[0].rows[0].note
# validate messages and export
print("validate:", app.validate())
import os, tempfile
out = os.path.join(tempfile.mkdtemp(), "t.sid")
from ntedit.psid import write_psid
write_psid(app.song, out)
print("sid bytes", os.path.getsize(out))
app.update_idletasks()
os.system(f"import -window root {sys.argv[1] if len(sys.argv) > 1 else '/tmp/claude-0/shot.png'}")
app.destroy()
print("OK")
