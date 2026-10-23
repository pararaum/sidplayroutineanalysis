import os, sys
from ntedit.gui import App
app = App("tests/data/gamemusic.bin"); app.update()

def shot(name):
    app.update(); os.system(f"import -window root /tmp/claude-0/{name}.png")

def keys(grid, *ks):
    grid.focus_force(); app.update()
    for k in ks:
        grid.event_generate("<KeyPress>", keysym=k); app.update()

for tab, nm in ((app.tab_song, "song"), (app.tab_pat, "pat"), (app.tab_cmd, "cmd")):
    app.nb.select(tab); app.update(); shot("s_" + nm)
# edit tests
app.nb.select(app.tab_song)
g = app.track_grids[1]; g.cur_row, g.cur_col = 1, 1
before = app.song.subtunes[0].tracks[1].items[1].value
keys(g, "plus"); g.event_generate("<KeyPress>", keysym="plus", ); 
g.event_generate("<Key>", keysym="plus"); app.update()
print("track item", before, "->", app.song.subtunes[0].tracks[1].items[1].value)
# table edit: wave row 1 left <- type 4 1
wg = app.table_grids["wave"]; app.nb.select(wg.master); app.update(); wg.cur_row, wg.cur_col = 0, 1
keys(wg, "4", "1")
print("wave[0]", app.song.wave[0])
app.do_undo(); print("after undo", app.song.wave[0])
shot("s_wave")
print("validate", app.validate())
app.destroy()
