#!/usr/bin/env python3
"""Control All Config: build a Model:Cycles OS 1.13 image in which Control All can leave
single tracks out.

Control All: hold [TRACK] and turn a knob, and the parameter changes on all six tracks. With
this image, [TRACK] + [TRIG 1-6] takes track 1-6 out of Control All or puts it back; while
[TRACK] is held, TRIG 1-6 light for the tracks that follow. The active track always follows.
The choice is kept in RAM only, so after power-on every track follows again.

The OS changes Control All in five fixed loops over the tracks (knobs, one value on all
tracks, LFO destination, [PUNCH]/[GATE], MACHINES). Each loop gets a jump to src/control_all_config.s,
which skips the tracks left out. TrackSelectionView, the view the OS shows while [TRACK] is
held, gets a front end for its keys and its LEDs. The code lives in two sprite masks whose
pictures exist byte for byte elsewhere in the OS; their constructors are pointed at those copies.

It starts from your own copy of the official OS file (checked by its SHA-256) and needs
elektron-firmware-tool (MIT, Marcel Bierling, https://github.com/mischa85/elektron-firmware-tool)
and the m68k-elf binutils. Every write is checked against the stock bytes it replaces, and the
result is checked before it is kept: checksums and HMAC, an independent unpack that must give
back exactly the patched MAIN OS, and a diff against stock that may touch nothing else.

    python3 build.py --stock model-cycles_OS1.13.syx --tool PATH/elektron-firmware-tool
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "0.1"
HERE = Path(__file__).resolve().parent
STOCK_SHA256 = "44fe586269631a0ca7da25a3383fc6733c314809505fc3cc52f1e0ed9800640c"   # model-cycles_OS1.13.syx
TOOL_NAME = "elektron-firmware-tool"
TOOL_URL = "https://github.com/mischa85/elektron-firmware-tool"
_tool = None

MAIN_OS = 3
BASE = 0x40000400                   # dest of MAIN OS

# The sprite masks the code goes into: (mask, size, constant that names it, kept copy, section).
# Each mask is byte-identical to its kept copy and named only by that one constant
# (Modded-Cycles, tweaks/model-cycles_OS1.13/REGISTRY.md lists both as free).
MASKS = [
    (0x4018D918, 328, 0x400ACD1A, 0x40187298, ".cac_a"),     # 41x41
    (0x4016F8C8, 272, 0x400B0B3C, 0x4016BFC8, ".cac_b"),     # 34x34
]

# Loop bodies whose first 6 bytes become "jmp cac_loopN": (address, stock bytes, symbol).
# cac_loopN repeats those instructions 10 bytes in and jumps back to address + 6.
LOOPS = [
    (0x4001D6F8, "2052 2668 007c", "cac_loop1"),   # controlAll (knobs)
    (0x4001D5A2, "2052 2f03 2f02", "cac_loop2"),   # one value on all tracks
    (0x4001EBD2, "2052 4878 0020", "cac_loop3"),   # setLFO: destination
    (0x4001AC7A, "2f02 2f03 4e92", "cac_loop4"),   # PUNCH / GATE
    (0x400A2798, "2f02 2f05 4e94", "cac_loop5"),   # MACHINES
]

# TrackSelectionView vtable slots: (address, stock pointer, symbol).
VTABLE = [
    (0x40100EE8, 0x40024078, "cac_keys"),          # consumeKeyEvent
    (0x40100F98, 0x40023D8C, "cac_leds"),          # LED producer (view + 0x68)
]

APLIB_BIAS, APLIB_FAR, WINDOW, MAX_MATCH = 767, 3328, 1 << 20, 2048


# ---- the firmware tool and an independent check of its output -----------------------------------

def use_tool(path=None):
    """Find elektron-firmware-tool: the given path, else $ELEKTRON_FIRMWARE_TOOL, else PATH."""
    global _tool
    cand = path or os.environ.get("ELEKTRON_FIRMWARE_TOOL") or shutil.which(TOOL_NAME)
    if not cand or not Path(cand).is_file() or not os.access(cand, os.X_OK):
        sys.exit("%s not found: build it from %s (make), then pass --tool PATH, set "
                 "ELEKTRON_FIRMWARE_TOOL, or put it on PATH" % (TOOL_NAME, TOOL_URL))
    _tool = Path(cand)


def check_stock(path):
    """The official model-cycles_OS1.13.syx, or exit."""
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != STOCK_SHA256:
        sys.exit("%s is not the official Model:Cycles OS 1.13 file (SHA-256 %s...)" % (path, STOCK_SHA256[:16]))
    return data


def tool(*args):
    if _tool is None:
        use_tool()
    res = subprocess.run([str(_tool), *map(str, args)], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError("elektron-firmware-tool %s failed:\n%s%s" % (" ".join(map(str, args)), res.stdout, res.stderr))
    return res.stdout


def extract_main_os(syx, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    tool("-i", syx, "-d", MAIN_OS, "-o", outdir)
    return (outdir / "section_3_MAIN_OS.bin").read_bytes()


def depack(packed):
    """Unpack one stored section (8-byte header + stream); also report the largest offset and match."""
    length, total = struct.unpack_from(">II", packed, 0)
    stream = packed[8:8 + length]
    if sum(stream) & 0xFFFFFFFF != total:
        raise ValueError("stream byte sum does not match its header")
    pos, tag, left = 0, 0, 0
    out = bytearray()
    last, max_off, max_len = 1, 0, 0

    def bit():
        nonlocal pos, tag, left
        if left == 0:
            tag, pos, left = stream[pos], pos + 1, 8
        left -= 1
        return (tag >> left) & 1

    def gamma():
        v = 1
        while True:
            v = v * 2 + bit()
            if bit():
                return v

    while True:
        if bit():
            out.append(stream[pos])
            pos += 1
            continue
        g = gamma()
        if g == 2:
            off = last
        else:
            low = stream[pos]
            pos += 1
            if g == 0x1000002 and low == 255:
                break
            off = g * 256 + low - APLIB_BIAS
            last = off
        short = bit() * 2 + bit()
        count = (short or gamma() + 2) + (1 if off > APLIB_FAR else 0) + 1
        if not 1 <= off <= len(out):
            raise ValueError("match reaches outside the output")
        max_off, max_len = max(max_off, off), max(max_len, count)
        for _ in range(count):
            out.append(out[-off])
    if pos != len(stream):
        raise ValueError("stream does not end at its end marker")
    return bytes(out), max_off, max_len


def decode_8in7(enc):
    out = bytearray()
    for g in range(0, len(enc), 8):
        msb, data = enc[g], enc[g + 1:g + 8]
        out += bytes(b | (0x80 if msb & (1 << (6 - n)) else 0) for n, b in enumerate(data))
    return bytes(out)


def encode_8in7(dec):
    out = bytearray()
    for g in range(0, len(dec), 7):
        grp = dec[g:g + 7]
        out.append(sum(1 << (6 - n) for n, b in enumerate(grp) if b & 0x80))
        out += bytes(b & 0x7F for b in grp)
    return bytes(out)


def packet_checksum(body, base):
    """Byte 125 of a 126-byte data packet: covers body[6..124] (block, seq, payload)."""
    return (base + sum(body[6 + i] ^ (base + i) for i in range(119))) & 0x7F


def content_checksum(container):
    words = struct.unpack(">%dI" % (len(container) // 4), container[:len(container) // 4 * 4])
    return sum((k + 1) ^ w for k, w in enumerate(words)) & 0xFFFFFFFF


def pad_compressed_sections(syx, key):
    """Count the zero padding after each compressed stream into its table length, as Elektron's
    containers do, then re-sign. Rewrites only the packets whose decoded bytes change.
    Returns the new file and a list of (section id, old length, new length)."""
    data = bytearray(syx)
    msgs, pos = [], 0
    while (s := data.find(0xF0, pos)) >= 0:
        e = data.index(0xF7, s)
        msgs.append((s + 1, e))
        pos = e + 1
    base = next(data[s + 7] for s, e in msgs if data[s + 5] == 0x7F and data[s + 6] == 0x01)
    packets = [(s, e) for s, e in msgs if data[s + 5] == 0x7E and e - s == 126]
    old_stream = b"".join(decode_8in7(data[s + 9:s + 125]) for s, e in packets)

    clen, csum = struct.unpack_from(">II", old_stream, 0)
    container = bytearray(old_stream[8:8 + clen])
    if content_checksum(container) != csum:
        raise ValueError("content checksum of the tool's output does not verify")
    count = struct.unpack_from(">I", container, 0x1C)[0]
    entries = [list(struct.unpack_from(">4I", container, 0x20 + 16 * s)) for s in range(count)]
    starts = sorted(e[1] for e in entries)

    changes = []
    for s, (sid, off, length, _) in enumerate(entries):
        stream_len, stream_sum = struct.unpack_from(">II", container, off)
        if 8 + stream_len > length or sum(container[off + 8:off + 8 + stream_len]) & 0xFFFFFFFF != stream_sum:
            continue                                   # a raw section, not header + stream
        padded = 8 + stream_len + (-(8 + stream_len) % 4)
        if length == padded:
            continue
        nxt = min([x for x in starts if x > off] + [clen])
        if length != 8 + stream_len or off + padded > nxt or any(container[off + length:off + padded]):
            raise ValueError("section %d: cannot pad %d -> %d in place" % (sid, length, padded))
        struct.pack_into(">I", container, 0x20 + 16 * s + 8, padded)
        entries[s][2] = padded
        changes.append((sid, length, padded))
    if not changes:
        return bytes(data), []

    end = max(off + length for _, off, length, _ in entries)
    hmac_off = (end + 4 + 15) & ~15
    if hmac_off + 32 != clen:
        raise ValueError("the HMAC trailer is not where the padded layout puts it")
    container[hmac_off:] = hmac.new(key, bytes(container[:hmac_off]), hashlib.sha256).digest()
    new_stream = struct.pack(">II", clen, content_checksum(container)) + container + old_stream[8 + clen:]

    for k, (s, e) in enumerate(packets):
        new = new_stream[101 * k:101 * (k + 1)]
        if new != old_stream[101 * k:101 * (k + 1)]:
            data[s + 9:s + 125] = encode_8in7(new)
            data[s + 125] = packet_checksum(data[s:e], base)
    return bytes(data), changes


def section_table(verbose_report):
    """id -> (offset, stored length) from the tool's -v report."""
    table = {}
    for m in re.finditer(r"id=(\d+)\s+\S.*?off=0x([0-9a-f]+)\s+clen=0x([0-9a-f]+)", verbose_report):
        table[int(m.group(1))] = (int(m.group(2), 16), int(m.group(3), 16))
    return table


def changed_ranges(a, b):
    ranges, i, n = [], 0, len(a)
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            ranges.append((i, j))
            i = j
        else:
            i += 1
    return ranges


def check(stock, out, patched, work):
    """Check a built file independently of how it was made; exit on the first failure. Returns
    the section table of the output and its largest match offset and length."""
    summary = tool("-i", out)
    container_path = work / "out.container.bin"
    report = tool("-i", out, "-v", "--emit-container", container_path)
    if not re.search(r"checksums\s*:\s*ok", summary):
        sys.exit("output fails its checksums:\n" + summary)
    if not re.search(r"digest\s*:\s*\[ok\]", report):
        sys.exit("output HMAC does not verify:\n" + report)
    if extract_main_os(out, work / "out") != patched:
        sys.exit("MAIN OS read back from the output differs from the patched one")
    out_table = section_table(report)
    container = container_path.read_bytes()
    off, clen = out_table[MAIN_OS]
    unpacked, max_off, max_len = depack(container[off:off + clen])
    if unpacked != patched:
        sys.exit("independent unpack of the output differs from the patched MAIN OS")
    if max_off >= WINDOW or max_len > MAX_MATCH:
        sys.exit("packed stream leaves Elektron's envelope: offset %d, match %d" % (max_off, max_len))
    for sid, (o, n) in out_table.items():
        stream_len = struct.unpack_from(">I", container, o)[0]
        if 8 + stream_len <= n and (n % 4 or n - 8 - stream_len > 3 or any(container[o + 8 + stream_len:o + n])):
            sys.exit("section %d is not padded the way Elektron pads it" % sid)
    stock_table = section_table(tool("-i", stock, "-v"))
    if sorted(stock_table) != sorted(out_table):
        sys.exit("section list changed: %s -> %s" % (sorted(stock_table), sorted(out_table)))
    tool("-i", stock, "-o", work / "all-stock")
    tool("-i", out, "-o", work / "all-out")
    for f in sorted((work / "all-stock").iterdir()):
        if not f.name.startswith("section_3_") and f.read_bytes() != (work / "all-out" / f.name).read_bytes():
            sys.exit("%s differs from stock" % f.name)

    return out_table, max_off, max_len


# ---- the mod -----------------------------------------------------------------------------------

def cross(prefix, name):
    path = shutil.which(prefix + name)
    if not path:
        sys.exit("%s%s not found: install the m68k-elf binutils or pass --cross PREFIX" % (prefix, name))
    return path


def run(*cmd):
    res = subprocess.run(list(map(str, cmd)), capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit("%s failed:\n%s%s" % (" ".join(map(str, cmd)), res.stdout, res.stderr))
    return res.stdout


def assemble(prefix, work):
    """Assemble and link src/control_all_config.s -> {section: (address, bytes)}, {symbol: address}."""
    obj, elf = work / "control_all_config.o", work / "control_all_config.elf"
    run(cross(prefix, "as"), "-mcpu=54418", "-o", obj, HERE / "src" / "control_all_config.s")
    run(cross(prefix, "ld"), "-T", HERE / "src" / "link.ld", "-o", elf, obj)
    symbols = {}
    for line in run(cross(prefix, "nm"), elf).splitlines():
        addr, kind, name = line.split()
        if kind in "Tt":
            symbols[name] = int(addr, 16)
    sections = {}
    for mask, size, _, _, name in MASKS:
        raw = work / (name.strip(".") + ".bin")
        run(cross(prefix, "objcopy"), "-O", "binary", "-j", name, elf, raw)
        sections[name] = (mask, raw.read_bytes())
    return sections, symbols


def expect(image, addr, old, what):
    off = addr - BASE
    if image[off:off + len(old)] != old:
        sys.exit("%s at 0x%08x is %s, not the stock %s: is this OS 1.13?"
                 % (what, addr, image[off:off + len(old)].hex(), old.hex()))


def patch(stock_os, sections, symbols):
    """The patched MAIN OS and the list of (address, length, what) it changes."""
    image = bytearray(stock_os)
    writes = []

    def put(addr, new, what):
        image[addr - BASE:addr - BASE + len(new)] = new
        writes.append((addr, len(new), what))

    for mask, size, const, kept, name in MASKS:
        addr, code = sections[name]
        if addr != mask or len(code) > size:
            sys.exit("%s: %d bytes at 0x%08x do not fit the %d-byte mask at 0x%08x" % (name, len(code), addr, size, mask))
        expect(image, mask, stock_os[kept - BASE:kept - BASE + size], "mask")
        if stock_os.count(struct.pack(">I", mask)) != 1:
            sys.exit("mask 0x%08x is named more than once" % mask)
        expect(image, const, struct.pack(">I", mask), "mask constant")
        put(const, struct.pack(">I", kept), "constant -> kept copy 0x%08x" % kept)
        put(mask, code, "code %s" % name)

    for addr, old, sym in LOOPS:
        old = bytes.fromhex(old)
        expect(image, addr, old, "loop entry")
        tramp = symbols[sym] - BASE
        moved, back = image[tramp + 10:tramp + 16], image[tramp + 16:tramp + 22]
        if moved != old or back != b"\x4e\xf9" + struct.pack(">I", addr + 6):
            sys.exit("%s does not repeat the stock bytes of 0x%08x and jump back to 0x%08x" % (sym, addr, addr + 6))
        put(addr, b"\x4e\xf9" + struct.pack(">I", symbols[sym]), "jmp %s" % sym)

    for addr, old, sym in VTABLE:
        expect(image, addr, struct.pack(">I", old), "vtable slot")
        put(addr, struct.pack(">I", symbols[sym]), "vtable -> %s (stock 0x%08x)" % (sym, old))

    patched = bytes(image)
    allowed = [(a - BASE, a - BASE + n) for a, n, _ in writes]
    stray = [r for r in changed_ranges(stock_os, patched) if not any(lo <= r[0] and r[1] <= hi for lo, hi in allowed)]
    if stray:
        sys.exit("internal error: bytes outside the writes changed: %s" % stray)
    return patched, writes


def build(args, work):
    stock_os = extract_main_os(args.stock, work / "stock")
    sections, symbols = assemble(args.cross, work)
    patched, writes = patch(stock_os, sections, symbols)
    out = args.out or HERE / "build" / ("model-cycles_OS1.13-control-all-config-v%s.syx" % VERSION)

    patched_path = work / "main_os.patched.bin"
    patched_path.write_bytes(patched)
    out.parent.mkdir(parents=True, exist_ok=True)
    tool("-i", args.stock, "-c", MAIN_OS, patched_path, "-o", out)
    key = re.search(r"key \(from input\)\s*:\s*([0-9a-f]{64})", tool("-i", out, "-v"))
    if not key:
        sys.exit("the tool reported no HMAC key for its output")
    fixed, padding = pad_compressed_sections(out.read_bytes(), bytes.fromhex(key.group(1)))
    out.write_bytes(fixed)

    out_table, max_off, max_len = check(args.stock, out, patched, work)

    out_bytes = out.read_bytes()
    result = {
        "control_all_config_version": VERSION,
        "stock": {"file": args.stock.name, "sha256": STOCK_SHA256},
        "output": {"file": out.name, "sha256": hashlib.sha256(out_bytes).hexdigest(), "bytes": len(out_bytes)},
        "code": {name: {"at": "0x%08x" % mask, "bytes": len(sections[name][1]), "mask_bytes": size}
                 for mask, size, _, _, name in MASKS},
        "writes": [{"at": "0x%08x" % a, "bytes": n, "what": w} for a, n, w in writes],
        "section_padding_added": [{"section": sid, "table_length": "0x%x -> 0x%x" % (a, b)} for sid, a, b in padding],
        "checks": {
            "stock_bytes_before_each_write": "as expected",
            "checksums": "ok", "hmac": "ok",
            "main_os_read_back": "identical to patched",
            "independent_unpack": "identical to patched",
            "other_sections": "identical to stock",
            "padding": "every compressed section ends on a 4-byte boundary, zero-filled",
            "max_match_offset": max_off, "max_match_length": max_len,
            "sections": sorted(out_table),
        },
    }
    Path(str(out) + ".json").write_text(json.dumps(result, indent=2) + "\n")
    print("%s\n  %d bytes, SHA-256 %s\n  %d writes, all on the stock bytes they replace; checksums, HMAC, read-back, "
          "independent unpack, padding and the untouched sections all check out\n  report: %s.json"
          % (out, len(out_bytes), result["output"]["sha256"], len(writes), out))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stock", type=Path, required=True, help="your official model-cycles_OS1.13.syx")
    ap.add_argument("--out", type=Path, help="output .syx (default: build/model-cycles_OS1.13-control-all-config-v%s.syx)" % VERSION)
    ap.add_argument("--tool", help="path to elektron-firmware-tool (default: $ELEKTRON_FIRMWARE_TOOL, then PATH)")
    ap.add_argument("--cross", default="m68k-elf-", help="binutils prefix (default: m68k-elf-)")
    ap.add_argument("--keep-work", type=Path, metavar="DIR", help="keep the intermediate files in DIR")
    args = ap.parse_args()
    check_stock(args.stock)
    use_tool(args.tool)
    if args.keep_work:
        args.keep_work.mkdir(parents=True, exist_ok=True)
        build(args, args.keep_work)
    else:
        with tempfile.TemporaryDirectory(prefix="control-all-config-") as tmp:
            build(args, Path(tmp))


if __name__ == "__main__":
    main()
