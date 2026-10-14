/* The two sprite masks the mod takes over (OS 1.13 load addresses, see build.py). */
SECTIONS
{
    .cac_a 0x4018d918 : { *(.cac_a) }   /* 41x41 mask, 328 bytes */
    .cac_b 0x4016f8c8 : { *(.cac_b) }   /* 34x34 mask, 272 bytes */
    /DISCARD/ : { *(*) }
}
