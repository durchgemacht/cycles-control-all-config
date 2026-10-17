| Control All Config, for Model:Cycles OS 1.13: leave single tracks out of Control All.
|
| Holding [TRACK] and turning a knob changes that parameter on all six tracks. The OS does it in
| five places, each a fixed loop over tracks 0..5. Every loop here first asks cac_skip whether
| track t is left out; if so the loop moves on to the next track without touching it.
|
| [TRACK] + [TRIG 1-6] toggles whether track 1-6 follows Control All. While [TRACK] is held the
| OS shows TrackSelectionView on top of the main screen; its key handler and its LED producer
| get a front end here, so TRIG 1-6 light for the tracks that follow. The active track always
| follows, so the knob never seems dead. The choice lives in RAM only: after power-on every
| track follows again, as in stock.
|
| The code sits in two sprite masks that have byte-identical copies elsewhere in the OS
| (the build points their constants at those copies). Addresses are OS 1.13 load addresses.

        | OS functions (C calling convention: d0-d1/a0-a1 scratch, result in d0)
        .equ    OS_PROJECT,        0x400cf866   | Project singleton
        .equ    OS_PROJECT_TRACKS, 0x4000eb90   | project -> its track selection (+48)
        .equ    OS_ACTIVE_TRACK,   0x40012412   | track selection -> active track 0..5
        .equ    OS_LEDS,           0x400cfaf4   | LED state singleton
        .equ    OS_LED_SET,        0x40005f86   | (leds, led, state): state 1 off, 2 on; first wins
        .equ    OS_LED_ON,         0x404a8c68   | 4th argument TrackSelectionView passes along
        .equ    OS_VIEW_LEDS,      0x400760ba   | (view): its LEDs changed, redo the LED frame

        | TrackSelectionView, stock entry points kept behind the front ends
        .equ    TSV_KEYS,          0x40024078   | consumeKeyEvent(view, event)
        .equ    TSV_LEDS,          0x40023d8c   | LED producer thunk (view + 0x68, avail, out)

        | KeyEvent fields
        .equ    EV_CODE,           12           | 2 TRACK, 16..31 TRIG 1..16
        .equ    EV_FLAGS,          16           | bit 0 down, bit 3 repeat, bit 5 long


        .section .cac_state,"ax"

        .ascii  "CAC1"
        .globl  cac_mask, cac_held
cac_mask:
        .byte   0                       | bit t: track t is left out of Control All
cac_held:
        .byte   0                       | bit t: the press of TRIG t+1 went to cac_keys
        .balign 2


        .section .cac_skip,"ax"

| d0 = track 0..5 -> d0 = 1 if Control All leaves it alone, else 0. Keeps d2-d7/a2-a6.
        .globl  cac_skip
cac_skip:
        moveq   #0,%d1
        move.b  cac_mask(%pc),%d1
        btst    %d0,%d1
        beq.s   1f
        move.l  %d0,-(%sp)
        jsr     OS_PROJECT
        move.l  %d0,-(%sp)
        jsr     OS_PROJECT_TRACKS
        move.l  %d0,(%sp)
        jsr     OS_ACTIVE_TRACK
        addq.l  #4,%sp
        move.l  (%sp)+,%d1
        cmp.l   %d0,%d1
        beq.s   1f                      | the active track always follows
        moveq   #1,%d0
        rts
1:      moveq   #0,%d0
        rts


| Each loop entry replaces the first 6 bytes of its loop body with "jmp cac_loopN". The moved
| instructions run here when the track follows; otherwise the counter steps on, as at the end
| of the stock loop.

| ParameterPageView::controlAll 0x4001d6e4: a turned knob, delta on every track (counter d2).
        .section .cac_loop1,"ax"
        .globl  cac_loop1
cac_loop1:
        move.l  %d2,%d0
        jsr     cac_skip(%pc)
        tst.l   %d0
        bne.s   2f
        move.l  (%a2),%a0               | moved from 0x4001d6f8
        move.l  124(%a0),%a3
        jmp     0x4001d6fe
2:      addq.l  #1,%d2
        moveq   #6,%d0
        cmp.l   %d2,%d0
        bne.s   cac_loop1
        jmp     0x4001d754

| ParameterPageView 0x4001d590: one value on every track, e.g. LFO depth (counter d2).
        .section .cac_loop2,"ax"
        .globl  cac_loop2
cac_loop2:
        move.l  %d2,%d0
        jsr     cac_skip(%pc)
        tst.l   %d0
        bne.s   2f
        move.l  (%a2),%a0               | moved from 0x4001d5a2
        move.l  %d3,-(%sp)
        move.l  %d2,-(%sp)
        jmp     0x4001d5a8
2:      addq.l  #1,%d2
        moveq   #6,%d0
        cmp.l   %d2,%d0
        bne.s   cac_loop2
        jmp     0x4001d5d8

| ParameterPageView::setLFO 0x4001eaa2: LFO destination on every track (counter a3).
        .section .cac_loop3,"ax"
        .globl  cac_loop3
cac_loop3:
        move.l  %a3,%d0
        jsr     cac_skip(%pc)
        tst.l   %d0
        bne.s   2f
        move.l  (%a2),%a0               | moved from 0x4001ebd2
        pea     0x20
        jmp     0x4001ebd8
2:      addq.l  #1,%a3
        moveq   #6,%d0
        cmp.l   %a3,%d0
        bne.s   cac_loop3
        jmp     0x4001ebfe

| 0x4001ac4a: [TRACK] + [PUNCH]/[GATE] toggles it on every track (counter d2).
        .section .cac_loop4,"ax"
        .globl  cac_loop4
cac_loop4:
        move.l  %d2,%d0
        jsr     cac_skip(%pc)
        tst.l   %d0
        bne.s   2f
        move.l  %d2,-(%sp)              | moved from 0x4001ac7a
        move.l  %d3,-(%sp)
        jsr     (%a2)
        jmp     0x4001ac80
2:      addq.l  #1,%d2
        moveq   #6,%d0
        cmp.l   %d2,%d0
        bne.s   cac_loop4
        jmp     0x4001ac8a

| MACHINES 0x400a2712: the machine on every track (counter d2, d4 walks 12-byte records).
        .section .cac_loop5,"ax"
        .globl  cac_loop5
cac_loop5:
        move.l  %d2,%d0
        jsr     cac_skip(%pc)
        tst.l   %d0
        bne.s   2f
        move.l  %d2,-(%sp)              | moved from 0x400a2798
        move.l  %d5,-(%sp)
        jsr     (%a4)
        jmp     0x400a279e
2:      addq.l  #1,%d2
        add.l   #12,%d4
        moveq   #6,%d0
        cmp.l   %d2,%d0
        bne.s   cac_loop5
        jmp     0x400a27e2


        .section .cac_keys,"ax"

| TrackSelectionView::consumeKeyEvent(view, event) -> d0 = 1 if the key was used.
| TRIG 1-6 toggle a track; their releases (and repeats) are used only when the press was, so a
| key pressed before [TRACK] still gets its release in the views below.
        .globl  cac_keys
cac_keys:
        move.l  8(%sp),%a0
        move.l  EV_CODE(%a0),%d0
        moveq   #2,%d1
        cmp.l   %d1,%d0
        bne.s   1f
        clr.b   cac_held                | [TRACK]: the view closes on its release
        bra.s   9f
1:      moveq   #16,%d1
        sub.l   %d1,%d0                 | TRIG 1..6 -> 0..5
        moveq   #5,%d1
        cmp.l   %d1,%d0
        bhi.s   9f
        move.l  EV_FLAGS(%a0),%d1
        btst    #0,%d1
        beq.s   5f                      | release
        andi.l  #0x28,%d1
        bne.s   6f                      | repeat or long press
        moveq   #0,%d1
        move.b  cac_mask,%d1
        bchg    %d0,%d1
        move.b  %d1,cac_mask
        moveq   #0,%d1
        move.b  cac_held,%d1
        bset    %d0,%d1
        move.b  %d1,cac_held
        move.l  4(%sp),-(%sp)
        jsr     OS_VIEW_LEDS
        addq.l  #4,%sp
        bra.s   8f
5:      moveq   #0,%d1
        move.b  cac_held,%d1
        bclr    %d0,%d1
        beq.s   9f                      | the press went elsewhere
        move.b  %d1,cac_held
        bra.s   8f
6:      moveq   #0,%d1
        move.b  cac_held,%d1
        btst    %d0,%d1
        beq.s   9f
8:      moveq   #1,%d0
        rts
9:      jmp     TSV_KEYS


| TrackSelectionView LED producer (view + 0x68, avail, out): stock lights [TRACK], then
| TRIG 1-6 light for the tracks that follow Control All and stay dark for the others.
        .section .cac_leds,"ax"
        .globl  cac_leds
cac_leds:
        move.l  12(%sp),-(%sp)
        move.l  12(%sp),-(%sp)
        move.l  12(%sp),-(%sp)
        jsr     TSV_LEDS
        lea     12(%sp),%sp
        lea     -12(%sp),%sp
        movem.l %d2-%d3/%a2,(%sp)
        move.l  24(%sp),%a2             | out: the LEDs this view sets
        jsr     OS_LEDS
        move.l  %d0,%d3
        moveq   #0,%d2
1:      moveq   #0,%d1
        move.b  cac_mask,%d1
        moveq   #2,%d0
        btst    %d2,%d1
        beq.s   2f
        moveq   #1,%d0
2:      pea     OS_LED_ON
        move.l  %d0,-(%sp)
        move.l  %d2,%d0
        addq.l  #1,%d0                  | LED n is TRIG n
        move.l  %d0,-(%sp)
        move.l  %d3,-(%sp)
        jsr     OS_LED_SET
        lea     16(%sp),%sp
        moveq   #1,%d0
        move.l  %d2,%d1
        addq.l  #1,%d1
        lsl.l   %d1,%d0
        or.l    %d0,(%a2)               | word 0 of the bitset holds LEDs 0..31
        addq.l  #1,%d2
        moveq   #6,%d0
        cmp.l   %d2,%d0
        bne.s   1b
        movem.l (%sp),%d2-%d3/%a2
        lea     12(%sp),%sp
        rts
