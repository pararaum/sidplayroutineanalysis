;-------------------------------------------------------------------------------
; NinjaTracker V2.04 gamemusic playroutine
;
; Cadaver 6/2013
;-------------------------------------------------------------------------------

;-------------------------------------------------------------------------------
; Defines
;-------------------------------------------------------------------------------

NT_FIRSTNOTE       = $18
NT_DUR             = $c0

NT_HEADERLENGTH    = 6
NT_NUMFIXUPS       = 21
NT_ADDZERO         = $80
NT_ADDWAVE         = $00
NT_ADDPULSE        = $04
NT_ADDFILT         = $08
NT_ADDCMD          = $0c
NT_ADDLEGATOCMD    = $10
NT_ADDPATT         = $14

NT_HRPARAM         = $00
NT_FIRSTWAVE       = $09
NT_SFXHRPARAM      = $00
NT_SFXFIRSTWAVE    = $09

;-------------------------------------------------------------------------------
; Zeropage work area. 2 consecutive addresses are needed.
;-------------------------------------------------------------------------------

nt_zpbase       = $fc
nt_temp1        = nt_zpbase+0
nt_temp2        = nt_zpbase+1

;-------------------------------------------------------------------------------
; NT_NEWMUSIC
;
; Call to set correct musicdata accesses within the playroutine. Needed before
; first playing or each time after loading new musicdata. Note that while this
; is running, do not let your interrupt call NT_MUSIC, as both share the same
; zeropage variables.
;
; Parameters: A:Musicdata address lobyte
;             X:Musicdata address hibyte
; Returns: -
; Modifies: A,X,Y,nt_temp1-nt_temp2
;-------------------------------------------------------------------------------

nt_newmusic:    sta nt_nmgetsize+1
                stx nt_nmgetsize+2
                clc
                adc #NT_HEADERLENGTH-1
                sta nt_temp1
                bcc nt_nmnotover
                inx
nt_nmnotover:   stx nt_temp2
                ldx #NT_NUMFIXUPS-1
nt_nmloop:      lda nt_fixuplo,x
                sta nt_nmstore+1
                lda nt_fixuphi,x
                sta nt_nmstore+2
                lda nt_fixupadd,x
                pha
                bmi nt_nmadddone
                lsr
                lsr
nt_nmaddsize:   tay
nt_nmgetsize:   lda $1000,y
                clc
                adc nt_temp1
                sta nt_temp1
                bcc nt_nmadddone
                inc nt_temp2
nt_nmadddone:   pla
                and #$03
                clc
                adc nt_temp1
                ldy #$01
                jsr nt_nmstore
                lda #$00
                adc nt_temp2
                iny
                jsr nt_nmstore
                dex
                bpl nt_nmloop
nt_nmstore:     sta nt_music,y
                rts

        ;New song initialization

nt_doinit:      asl
                asl
                adc nt_initsongnum+1
                tay
nt_songtblp0:   lda $1000,y
                sta nt_tracklo+1
nt_songtblp1:   lda $1000,y
                sta nt_trackhi+1
                txa
                sta nt_filtpos+1
                sta $d417
                ldx #21
nt_initloop:    sta nt_chnpattpos-1,x
                dex
                bne nt_initloop
                jsr nt_initchn
                ldx #$07
                jsr nt_initchn
                ldx #$0e
nt_initchn:    
nt_songtblp2:   lda $1000,y
                sta nt_chnsongpos,x
                iny
                lda #$ff
                sta nt_chnnewnote,x
                sta nt_chnduration,x
                sta nt_chntrans,x

;-------------------------------------------------------------------------------
; NT_PLAYSONG
;
; Call to start playback of a tune.
;
; Parameters: A:Tune number (0-15)
; Returns: -
; Modifies: -
;-------------------------------------------------------------------------------

nt_playsong:    sta nt_initsongnum+1
                rts

;-------------------------------------------------------------------------------
; NT_PLAYSFX
;
; Call to start a sound effect on a channel. Has a built in priority system:
; a sound at higher memory address can interrupt one that is lower, but not the
; other way around.
;
; Sounds can be converted from GT1.xx or GT2.xx instruments with the ins2nt2
; utility, or created by following this dataformat:
;
; - Sustain/Release
; - Attack/Decay
; - Pulsewidth, with nybbles reversed (pulse 400 = $04)
; - Note,Wave pairs for each frame of the sound (note ranges from $8C to $DF,
;   wave from $01 to $81). If waveform stays the same, it can be omitted
; - End with $00
;
; Parameters: A:Sound effect address lobyte
;             X:Sound effect address hibyte
;             Y:Channel index (0,7 or 14)
; Returns: -
; Modifies: A
;-------------------------------------------------------------------------------

nt_playsfx:     sta nt_playsfxlo+1
                cmp nt_chnsfxlo,y
                txa
                sbc nt_chnsfxhi,y
                bpl nt_playsfxok
                lda nt_chnsfx,y
                bne nt_playsfxskip
nt_playsfxok:   lda #$01
                sta nt_chnsfx,y
nt_playsfxlo:   lda #$00
                sta nt_chnsfxlo,y
                txa
                sta nt_chnsfxhi,y
nt_playsfxskip: rts

;-------------------------------------------------------------------------------
; NT_MUSIC
;
; Call each frame to play music and sound effects.
;
; Parameters: -
; Returns: -
; Modifies: A,X,Y,nt_temp1-nt_temp2
;-------------------------------------------------------------------------------

nt_music:       ldx #$00
nt_initsongnum: lda #$00
                bpl nt_doinit

          ;Filter execution

nt_filtpos:     ldy #$00
                beq nt_filtdone
nt_filttimem1:  lda $1000,y
                bpl nt_filtmod
                cmp #$ff
                bcs nt_filtjump
nt_setfilt:     sta $d417
                and #$70
                sta nt_filtdone+1
nt_filtjump:    
nt_filtspdm1a:  lda $1000,y
                bcs nt_filtjump2
nt_nextfilt:    inc nt_filtpos+1
                bcc nt_storecutoff
nt_filtjump2:   sta nt_filtpos+1
                bcs nt_filtdone
nt_filtmod:     clc
                dec nt_filttime
                bmi nt_newfiltmod
                bne nt_filtcutoff
                inc nt_filtpos+1
                bcc nt_filtdone
nt_newfiltmod:  sta nt_filttime
nt_filtcutoff:  lda #$00
nt_filtspdm1b:  adc $1000,y
nt_storecutoff: sta nt_filtcutoff+1
                sta $d416
nt_filtdone:    lda #$00
                ora #$0f
                sta $d418

        ;Channel execution

                jsr nt_chnexec
                ldx #$07
                jsr nt_chnexec
                ldx #$0e

        ;Update duration counter

nt_chnexec:     inc nt_chncounter,x
                bne nt_nopattern

        ;Get data from pattern

nt_pattern:     ldy nt_chnpattnum,x
nt_patttbllom1: lda $1000,y
                sta nt_temp1
nt_patttblhim1: lda $1000,y
                sta nt_temp2
                ldy nt_chnpattpos,x
                lda (nt_temp1),y
                lsr
                sta nt_chnnewnote,x
                bcc nt_nonewcmd
nt_newcmd:      iny
                lda (nt_temp1),y
                sta nt_chncmd,x
                bcc nt_rest
nt_checkhr:     bmi nt_rest
                lda nt_chnsfx,x
                bne nt_rest
                lda #$fe
                sta nt_chngate,x
                sta $d405,x
                nt_hrparam:     lda #NT_HRPARAM
                sta $d406,x
nt_rest:        iny
                lda (nt_temp1),y
                cmp #$c0
                bcc nt_nonewdur
                iny
                sta nt_chnduration,x
nt_nonewdur:    lda (nt_temp1),y
                beq nt_endpatt
                tya
nt_endpatt:     sta nt_chnpattpos,x
nt_jumptowave:  ldy nt_chnsfx,x
                bne nt_jumptosfx
                jmp nt_waveexec
nt_jumptosfx:   jmp nt_sfxexec

        ;No new command, or gate control

nt_nonewcmd:    cmp #NT_FIRSTNOTE/2
                bcc nt_gatectrl
                lda nt_chncmd,x
                bcs nt_checkhr
nt_gatectrl:    lsr
                ora #$fe
                sta nt_chngate,x
                bcc nt_newcmd
                sta nt_chnnewnote,x
                bcs nt_rest

        ;No new pattern data

nt_legatocmd:   tya
                and #$7f
                tay
                bpl nt_skipadsr

nt_jumptopulse: ldy nt_chnsfx,x
                bne nt_jumptosfx
                jmp nt_pulseexec
nt_nopattern:   lda nt_chncounter,x
                cmp #$02
                bne nt_jumptopulse

        ;Reload counter and check for new note / command exec / track access

nt_reload:      lda nt_chnduration,x
                sta nt_chncounter,x
                lda nt_chnnewnote,x
                bpl nt_newnoteinit
                lda nt_chnpattpos,x
                bne nt_jumptopulse

         ;Get data from track

nt_track:
nt_tracklo:     lda #$00
                sta nt_temp1
nt_trackhi:     lda #$00
                sta nt_temp2
                ldy nt_chnsongpos,x
                lda (nt_temp1),y
                bne nt_nosongjump
                iny
                lda (nt_temp1),y
                tay
                lda (nt_temp1),y
nt_nosongjump:  bpl nt_nosongtrans
                sta nt_chntrans,x
                iny
                lda (nt_temp1),y
nt_nosongtrans: sta nt_chnpattnum,x
                iny
                tya
                sta nt_chnsongpos,x
                bcs nt_jumptowave
                bcc nt_cmdexecuted

        ;New note init / command exec

nt_newnoteinit: cmp #NT_FIRSTNOTE/2
                bcc nt_skipnote
                adc nt_chntrans,x
                asl
                sta nt_chnnote,x
                sec
nt_skipnote:    ldy nt_chncmd,x
                bmi nt_legatocmd
nt_cmdadm1:     lda $1000,y
                sta $d405,x
nt_cmdsrm1:     lda $1000,y
                sta $d406,x
                bcc nt_skipgate
                lda #$ff
                sta nt_chngate,x
                nt_firstwave:   lda #NT_FIRSTWAVE
                sta $d404,x
nt_skipgate:
nt_skipadsr:
nt_cmdwavem1:   lda $1000,y
                beq nt_skipwave
                sta nt_chnwavepos,x
                lda #$00
                sta nt_chnwavetime,x
nt_skipwave:    
nt_cmdpulsem1:  lda $1000,y
                beq nt_skippulse
                sta nt_chnpulsepos,x
                lda #$00
                sta nt_chnpulsetime,x
nt_skippulse:   
nt_cmdfiltm1:   lda $1000,y
                beq nt_skipfilt
                sta nt_filtpos+1
                lda #$00
                sta nt_filttime
nt_skipfilt:    clc
                lda nt_chnpattpos,x
                beq nt_track
nt_cmdexecuted:
nt_notrack:     rts

        ;Pulse execution

nt_nopulsemod:  cmp #$ff
nt_pulsespdm1a: lda $1000,y
                bcs nt_pulsejump
                inc nt_chnpulsepos,x
                bcc nt_storepulse
nt_pulsejump:   sta nt_chnpulsepos,x
                bcs nt_pulsedone
nt_pulseexec:   ldy nt_chnpulsepos,x
                beq nt_pulsedone
nt_pulsetimem1: lda $1000,y
                bmi nt_nopulsemod
nt_pulsemod:    clc
                dec nt_chnpulsetime,x
                bmi nt_newpulsemod
                bne nt_nonewpulsemod
                inc nt_chnpulsepos,x
                bcc nt_pulsedone
nt_newpulsemod: sta nt_chnpulsetime,x
nt_nonewpulsemod:
                lda nt_chnpulse,x
nt_pulsespdm1b: adc $1000,y
                adc #$00
nt_storepulse:  sta nt_chnpulse,x
                sta $d402,x
                sta $d403,x
nt_pulsedone:

        ;Wavetable execution

nt_waveexec:    ldy nt_chnwavepos,x
                beq nt_wavedone
nt_wavem1:      lda $1000,y     
                cmp #$c0
                bcs nt_slideorvib
                cmp #$90
                bcc nt_wavechange

        ;Delayed wavetable

nt_wavedelay:   beq nt_nowavechange
                dec nt_chnwavetime,x
                beq nt_nowavechange
                bpl nt_wavedone
                sbc #$90
                sta nt_chnwavetime,x
                bcs nt_wavedone

        ;Wave change + arpeggio

nt_wavechange:  sta nt_chnwave,x
                tya
                sta nt_chnwaveold,x
nt_nowavechange:
nt_wavep0:      lda $1000,y
                cmp #$ff
                bcs nt_wavejump
nt_nowavejump:  inc nt_chnwavepos,x
                bcc nt_wavejumpdone
nt_wavejump:
nt_notep0:      lda $1000,y
                sta nt_chnwavepos,x
nt_wavejumpdone:
nt_notem1a:     lda $1000,y
                asl
                bcs nt_absfreq
                adc nt_chnnote,x
nt_absfreq:     tay
                bne nt_notenum
nt_slidedone:   ldy nt_chnnote,x
                lda nt_chnwaveold,x
                sta nt_chnwavepos,x
nt_notenum:     lda nt_freqtbl-24,y
                sta nt_chnfreqlo,x
                sta $d400,x
                lda nt_freqtbl-23,y
nt_storefreqhi: sta $d401,x
                sta nt_chnfreqhi,x
nt_wavedone:    lda nt_chnwave,x
                and nt_chngate,x
                sta $d404,x
                rts

        ;Slide or vibrato

nt_slideorvib:  sbc #$e0
                sta nt_temp1
                lda nt_chncounter,x
                beq nt_wavedone
nt_notem1b:     lda $1000,y
                sta nt_temp2
                bcc nt_vibrato

        ;Slide (toneportamento)

nt_slide:       ldy nt_chnnote,x
                lda nt_chnfreqlo,x
                sbc nt_freqtbl-24,y
                pha
                lda nt_chnfreqhi,x
                sbc nt_freqtbl-23,y
                tay
                pla
                bcs nt_slidedown
nt_slideup:     adc nt_temp2
                tya
                adc nt_temp1
                bcs nt_slidedone
nt_freqadd:     lda nt_chnfreqlo,x
                adc nt_temp2
                sta nt_chnfreqlo,x
                sta $d400,x
                lda nt_chnfreqhi,x
                adc nt_temp1
                jmp nt_storefreqhi

        ;Sound effect hard restart
       
nt_sfxhr:       lda #NT_SFXHRPARAM
                sta $d406,x
                bcc nt_wavedone

nt_slidedown:   sbc nt_temp2
                tya
                sbc nt_temp1
                bcc nt_slidedone
nt_freqsub:     lda nt_chnfreqlo,x
                sbc nt_temp2
                sta nt_chnfreqlo,x
                sta $d400,x
                lda nt_chnfreqhi,x
                sbc nt_temp1
                jmp nt_storefreqhi

          ;Vibrato

nt_vibrato:     lda nt_chnwavetime,x
                bpl nt_vibnodir
                cmp nt_temp1
                bcs nt_vibnodir2
                eor #$ff
nt_vibnodir:    sec
nt_vibnodir2:   sbc #$02
                sta nt_chnwavetime,x
                lsr
                lda #$00
                sta nt_temp1
                bcc nt_freqadd
                bcs nt_freqsub

          ;Sound effect

nt_sfxexec:     lda nt_chnsfxlo,x
                sta nt_temp1
                lda nt_chnsfxhi,x
                sta nt_temp2
                lda #$fe
                sta nt_chnnewnote,x
                sta nt_chngate,x
                inc nt_chnsfx,x
                cpy #$02
                beq nt_sfxinit
                bcc nt_sfxhr
nt_sfxmain:     lda (nt_temp1),y
                beq nt_sfxend
nt_sfxnoend:    asl
                tay
                lda nt_freqtbl-24,y
                sta $d400,x
                lda nt_freqtbl-23,y
                sta $d401,x
                ldy nt_chnsfx,x
                lda (nt_temp1),y
                beq nt_sfxdone
                cmp #$82
                bcs nt_sfxdone
                inc nt_chnsfx,x
nt_sfxwavechg:  sta nt_chnwave,x
                sta $d404,x
nt_sfxdone:     rts
nt_sfxend:      sta nt_chnsfx,x
                sta nt_chnwavepos,x
                sta nt_chnwaveold,x
                beq nt_sfxwavechg
nt_sfxinit:     lda (nt_temp1),y
                sta $d402,x
                sta $d403,x
                dey
                lda (nt_temp1),y
                sta $d405,x
                dey
                lda (nt_temp1),y
                sta $d406,x
                lda #NT_SFXFIRSTWAVE
                bcs nt_sfxwavechg

;-------------------------------------------------------------------------------
; Playroutine data
;-------------------------------------------------------------------------------

nt_freqtbl:     .word $022d,$024e,$0271,$0296,$02be,$02e8
                .word $0314,$0343,$0374,$03a9,$03e1,$041c
                .word $045a,$049c,$04e2,$052d,$057c,$05cf
                .word $0628,$0685,$06e8,$0752,$07c1,$0837
                .word $08b4,$0939,$09c5,$0a5a,$0af7,$0b9e
                .word $0c4f,$0d0a,$0dd1,$0ea3,$0f82,$106e
                .word $1168,$1271,$138a,$14b3,$15ee,$173c
                .word $189e,$1a15,$1ba2,$1d46,$1f04,$20dc
                .word $22d0,$24e2,$2714,$2967,$2bdd,$2e79
                .word $313c,$3429,$3744,$3a8d,$3e08,$41b8
                .word $45a1,$49c5,$4e28,$52cd,$57ba,$5cf1
                .word $6278,$6853,$6e87,$751a,$7c10,$8371
                .word $8b42,$9389,$9c4f,$a59b,$af74,$b9e2
                .word $c4f0,$d0a6,$dd0e,$ea33,$f820,$ffff

;-------------------------------------------------------------------------------
; Playroutine fixup data
;-------------------------------------------------------------------------------

nt_fixuplo:     .byte <nt_songtblp2
                .byte <nt_songtblp1
                .byte <nt_songtblp0
                .byte <nt_patttblhim1
                .byte <nt_patttbllom1
                .byte <nt_cmdfiltm1
                .byte <nt_cmdpulsem1
                .byte <nt_cmdwavem1
                .byte <nt_cmdsrm1
                .byte <nt_cmdadm1
                .byte <nt_filtspdm1b
                .byte <nt_filtspdm1a
                .byte <nt_filttimem1
                .byte <nt_pulsespdm1b
                .byte <nt_pulsespdm1a
                .byte <nt_pulsetimem1
                .byte <nt_notep0
                .byte <nt_notem1b
                .byte <nt_notem1a
                .byte <nt_wavep0
                .byte <nt_wavem1

nt_fixuphi:     .byte >nt_songtblp2
                .byte >nt_songtblp1
                .byte >nt_songtblp0
                .byte >nt_patttblhim1
                .byte >nt_patttbllom1
                .byte >nt_cmdfiltm1
                .byte >nt_cmdpulsem1
                .byte >nt_cmdwavem1
                .byte >nt_cmdsrm1
                .byte >nt_cmdadm1
                .byte >nt_filtspdm1b
                .byte >nt_filtspdm1a
                .byte >nt_filttimem1
                .byte >nt_pulsespdm1b
                .byte >nt_pulsespdm1a
                .byte >nt_pulsetimem1
                .byte >nt_notep0
                .byte >nt_notem1b
                .byte >nt_notem1a
                .byte >nt_wavep0
                .byte >nt_wavem1

nt_fixupadd:    .byte NT_ADDZERO+3
                .byte NT_ADDZERO+2
                .byte NT_ADDPATT+1
                .byte NT_ADDPATT
                .byte NT_ADDLEGATOCMD
                .byte NT_ADDLEGATOCMD
                .byte NT_ADDLEGATOCMD
                .byte NT_ADDCMD
                .byte NT_ADDCMD
                .byte NT_ADDFILT
                .byte NT_ADDZERO
                .byte NT_ADDFILT
                .byte NT_ADDPULSE
                .byte NT_ADDZERO
                .byte NT_ADDPULSE
                .byte NT_ADDWAVE
                .byte NT_ADDZERO+1
                .byte NT_ADDZERO
                .byte NT_ADDWAVE
                .byte NT_ADDZERO+1
                .byte NT_ADDZERO

;-------------------------------------------------------------------------------
; Playroutine variables
;-------------------------------------------------------------------------------

nt_chnpattpos:  .byte 0
nt_chncounter:  .byte 0
nt_chnnewnote:  .byte 0
nt_chnwavepos:  .byte 0
nt_chnpulsepos: .byte 0
nt_chnwave:     .byte 0
nt_chnpulse:    .byte 0

                .byte 0,0,0,0,0,0,0
                .byte 0,0,0,0,0,0,0

nt_chngate:     .byte $fe
nt_chntrans:    .byte $ff
nt_chncmd:      .byte $01
nt_chnsongpos:  .byte 0
nt_chnpattnum:  .byte 0
nt_chnduration: .byte 0
nt_chnnote:     .byte 0

                .byte $fe,$ff,$01,0,0,0,0
                .byte $fe,$ff,$01,0,0,0,0

nt_chnfreqlo:   .byte 0
nt_chnfreqhi:   .byte 0
nt_chnwavetime: .byte 0
nt_chnpulsetime:.byte 0
nt_chnsfx:      .byte 0
nt_chnsfxlo:    .byte 0
nt_chnsfxhi:    
nt_chnwaveold:  .byte 0

                .byte 0,0,0,0,0,0,0
                .byte 0,0,0,0,0,0,0

nt_filttime:    .byte 0


