# Builds the PSID player blob with cc65. Outputs are committed so that the
# Python package works without cc65 installed.
all: ../ntedit/player.bin ../ntedit/player.lbl

sidwrap.o: sidwrap.s ../ntedit/nt2play.s
	ca65 -I ../ntedit -o $@ sidwrap.s

../ntedit/player.bin ../ntedit/player.lbl: sidwrap.o sid.cfg
	ld65 -C sid.cfg -o ../ntedit/player.bin -Ln ../ntedit/player.lbl sidwrap.o

clean:
	rm -f sidwrap.o
