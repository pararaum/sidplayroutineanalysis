; PSID wrapper around the NinjaTracker V2.04 play routine (Cadaver, 2013).
; Layout:  $1000 jmp init / $1003 jmp play, then the play routine and its
; variables, then the packed song data at nt_end (appended by the exporter).
        .export init_entry, play_entry, nt_end, nt_music, nt_newmusic, nt_playsong, nt_playsfx, nt_hrparam, nt_firstwave
        .segment "CODE"
init_entry:
        jmp init
play_entry:
        jmp nt_music
init:   pha
        lda #<nt_end
        ldx #>nt_end
        jsr nt_newmusic
        pla
        jmp nt_playsong

        .include "nt2play.s"

nt_end:
