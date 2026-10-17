/* The two sprite masks the mod takes over (OS 1.13 load addresses, see build.py). The code is in one
   section per routine so that a port can place them one by one; here they are laid out as before. */
SECTIONS
{
    .cac_a 0x4018d918 : { *(.cac_state) *(.cac_skip) *(.cac_loop1) *(.cac_loop2) *(.cac_loop3) *(.cac_loop4) *(.cac_loop5) }   /* 41x41 mask, 328 bytes */
    .cac_b 0x4016f8c8 : { *(.cac_keys) *(.cac_leds) }   /* 34x34 mask, 272 bytes */
    /DISCARD/ : { *(*) }
}
