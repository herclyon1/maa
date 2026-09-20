#!/usr/bin/env python3
"""air_sampler.py — list the functions of a Metal library (.metallib, MTLB container) and decode every constexpr sampler state they carry.

    python3 air_sampler.py <default.metallib> [--extract DIR] [--decode HEX...]

The container: header offsets at 0x18 (8 × u64: function list, public / private metadata, bitcode; offset + size each); the function list = u32 count,
then per function u32 size + tag/len/value records (NAME, TYPE, HASH, OFFT = 3 × u64 with the bitcode offset third, MDSZ = the bitcode size, ENDT).
Each function's bitcode (a 0x0B17C0DE-wrapped LLVM AIR module) is readable by Apple clang: `clang -S -emit-llvm f.bc` (the same LLVM); the samplers
appear as `@__air_sampler_state[.n] = … [i64 <value>, i64 0]` and every `air.sample_texture_*` call names the one it uses.
The bit layout of <value> (read by compiling one probe per field with `xcrun -sdk iphoneos metal -S -emit-llvm`, Apple metal 32023.921 — the version
that built QuartzCore's default.metallib; each field changed one at a time, 2026-09-20, R37):
  bits 0-2 / 3-5 / 6-8  s / t / r address: 0 clamp_to_zero (also clamp_to_border: border colour in bits 56-57, opaque_black 1 / opaque_white 2),
                        1 clamp_to_edge (the MSL default), 2 repeat, 3 mirrored_repeat
  bit 9   mag_filter linear      bit 11  min_filter linear      bits 13-14  mip_filter: 0 none, 1 (0x2000) nearest, 2 (0x4000) linear
  bit 15  coord::pixel           bits 16-18 compare_func (never 0, less 1 …)      bits 20-23 max_anisotropy − 1      bit 19: always set (unassigned here)
  bits 24-39 / 40-55  lod_clamp min / max as IEEE half (probe lod_clamp(1, 4) → 0x3c00 / 0x4400; defaults 0 / 0x7bff = 65504)
"""
import struct, sys, os, subprocess, re, glob, tempfile

def functions(path):
    data = open(path, 'rb').read(); assert data[:4] == b'MTLB', 'not a metallib'
    fl_off, fl_sz, pub_off, pub_sz, prv_off, prv_sz, bc_off, bc_sz = struct.unpack_from('<8Q', data, 0x18)
    count = struct.unpack_from('<I', data, fl_off)[0]; p = fl_off + 4; out = []
    for _ in range(count):
        esz = struct.unpack_from('<I', data, p)[0]; q = p + 4; end = p + esz; ent = {}
        while q < end:
            tag = data[q:q + 4].decode('ascii'); q += 4
            if tag == 'ENDT': break
            ln = struct.unpack_from('<H', data, q)[0]; q += 2; val = data[q:q + ln]; q += ln
            if tag == 'NAME': ent['name'] = val.rstrip(b'\0').decode()
            elif tag == 'TYPE': ent['type'] = val[0]
            elif tag == 'OFFT': ent['offt'] = struct.unpack('<3Q', val)
            elif tag == 'MDSZ': ent['mdsz'] = struct.unpack('<Q', val)[0]
        o = bc_off + ent['offt'][2]; ent['bc'] = data[o:o + ent['mdsz']]; out.append(ent); p = end
    return out

def half(h):
    s, e, m = (h >> 15) & 1, (h >> 10) & 0x1f, h & 0x3ff
    v = (m / 1024.0) * 2.0 ** -14 if e == 0 else float('inf') if e == 31 and m == 0 else float('nan') if e == 31 else (1 + m / 1024.0) * 2.0 ** (e - 15)
    return -v if s else v

def decode(v):
    addr = ['clamp_to_zero', 'clamp_to_edge', 'repeat', 'mirrored_repeat']
    a = [addr[(v >> sh) & 7] if ((v >> sh) & 7) < 4 else str((v >> sh) & 7) for sh in (0, 3, 6)]
    mip = ['none', 'nearest', 'linear', '3?'][(v >> 13) & 3]; border = (v >> 56) & 3
    return (f"address s/t/r {'/'.join(a)}" + (f" (clamp_to_border, border_color {['transparent_black', 'opaque_black', 'opaque_white'][border]})" if border else '')
            + f", mag {'linear' if v >> 9 & 1 else 'nearest'}, min {'linear' if v >> 11 & 1 else 'nearest'}, mip {mip}"
            + f", coord {'pixel' if v >> 15 & 1 else 'normalized'}, compare {(v >> 16) & 7}, anisotropy {((v >> 20) & 15) + 1}"
            + f", lod_clamp {half((v >> 24) & 0xffff):g} … {half((v >> 40) & 0xffff):g}")

def samplers(ll):
    txt = open(ll).read(); consts = {m.group(1): int(m.group(2)) for m in re.finditer(r'@(__air_sampler_state[.\d]*) = .*?\[i64 (\d+), i64', txt)}
    used = {}
    for m in re.finditer(r'call .*?@air\.(sample|gather)[\w.]*\(.*?@(__air_sampler_state[.\d]*)', txt):
        used[m.group(2)] = used.get(m.group(2), 0) + 1
    return {n: (consts[n], used.get(n, 0)) for n in consts}

if __name__ == '__main__':
    args = sys.argv[1:]
    if args and args[0] == '--decode':
        for h in args[1:]: v = int(h, 16); print(f'0x{v:x}: {decode(v)}')
        sys.exit(0)
    lib = args[0]; outdir = args[args.index('--extract') + 1] if '--extract' in args else tempfile.mkdtemp()
    os.makedirs(outdir, exist_ok=True); table = {}
    for f in functions(lib):
        bc = os.path.join(outdir, f['name'] + '.bc'); ll = bc[:-3] + '.ll'; open(bc, 'wb').write(f['bc'])
        if subprocess.run(['clang', '-S', '-emit-llvm', '-o', ll, bc], capture_output=True).returncode: print('!', f['name'], 'not disassembled'); continue
        for n, (v, k) in samplers(ll).items(): table.setdefault(v, []).append(f"{f['name']}:{n}×{k}")
    for v in sorted(table): print(f'0x{v:016x}  {decode(v)}\n    ' + ' '.join(sorted(table[v])))
