# Control All Config V1.0

With this mod, you can select the tracks that are affected by "Control All".
Compatible with Elektron Model:Cycles, OS 1.13.

## How to use

- **[TRACK] + [TRIG 1–6]** takes track 1–6 out of Control All, or puts it back.
- While [TRACK] is held, **TRIG 1–6 light for the tracks that follow** Control All and stay dark
  for the ones left out.
- **The active track always follows Control All** as it does on the Digiboxes.
- Left-out tracks also keep their machine, LFO destination and PUNCH/GATE when you change those
  with [TRACK] held.
- The choice is not saved: **after power-on every track follows again**, as in stock.

**Status:** tested on a Model:Cycles and in the digiemu emulator 0.4.1 (2026-10-14): works.
1.0 is that build, byte for byte; the number says the mod is finished.

## Build

You need your own copy of the official `model-cycles_OS1.13.syx`,
[elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool) and the m68k-elf
binutils (Homebrew: `m68k-elf-binutils`).

```sh
python3 build.py --stock model-cycles_OS1.13.syx --tool path/to/elektron-firmware-tool
```

This writes `build/model-cycles_OS1.13-control-all-config-v1.0.syx` and a `.json` report. The
script checks the SHA-256 of the stock file and the stock bytes under every write. It checks the
result before keeping it: checksums, HMAC, an independent unpack, and a diff that may touch nothing
but its writes.

## How it works

The OS has no single Control All function. Five places loop over tracks 0–5 when [TRACK] is held:
knobs on the parameter page, one value on all tracks (LFO depth), LFO destination, [PUNCH]/[GATE],
and the MACHINES page. Each loop gets a jump into `src/control_all_config.s`, which skips the
tracks left out. While [TRACK] is held the OS shows a view of its own (TrackSelectionView); its key
handler and LED producer get a front end for TRIG 1–6. TRIG 7–16 and everything else go to the
stock code.

The code (about 500 bytes) sits in two sprite masks whose pictures also exist byte for byte
elsewhere in the OS (see the free-space registry of Modded-Cycles). The build points the two
constructors at those copies, so nothing on screen changes. The new code only runs while [TRACK]
is held, so booting and the UPGRADE menu do not go through it.

## License

MIT, see [LICENSE](LICENSE). The repository holds no Elektron firmware, only addresses and the
few stock bytes each write checks before it replaces them; the build works on your own copy of
the official OS file.
