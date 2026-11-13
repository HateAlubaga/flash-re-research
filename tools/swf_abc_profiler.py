#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SWF / ABC static profiler, built from adobe/avmplus (MPL-2.0):
  - core/opcodes.tbl        -> canonical 256-entry AVM2 opcode table with operand counts
  - doc/abcFormat-46-16.txt -> canonical ABC layout

Purpose: measure what a heavy real AS3 game actually spends bytecode on,
so AVM2 optimization targets for Ruffle can be ranked by evidence instead of guesses.

Usage:
  python -I tools/swf_abc_profiler.py GAME.swf \
      --tbl <avmplus>/core/opcodes.tbl --json out.json
"""
import argparse, collections, json, os, re, struct, sys, zlib, lzma, time

def load_opcode_table(tbl_path):
    """Parse avmplus/core/opcodes.tbl -> {opcode: (name, operand_count, can_throw)}"""
    txt = open(tbl_path, "r", encoding="utf-8", errors="replace").read()
    pat = re.compile(
        r'ABC_(OP|UNUSED_OP|OP_F)\s*\(\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*([A-Za-z0-9_]+)\s*\)')
    entries = pat.findall(txt)
    table = {}
    for idx, (kind, opcnt, throw_, stk, internal, name) in enumerate(entries[:256]):
        table[idx] = (name, int(opcnt), int(throw_))
    if len(table) < 256:
        print(f"WARN: parsed only {len(table)} opcodes from {tbl_path}", file=sys.stderr)
    return table

def read_u30(b, p):
    v = 0
    for shift in range(0, 35, 7):
        if p >= len(b): raise IndexError("EOF in u30")
        c = b[p]; p += 1
        v |= (c & 0x7F) << shift
        if not (c & 0x80): break
    return v & 0xFFFFFFFF, p

def read_s24(b, p):
    if p + 3 > len(b): raise IndexError("EOF in s24")
    v = b[p] | (b[p+1] << 8) | (b[p+2] << 16)
    if v & 0x800000: v -= 0x1000000
    return v, p + 3

# opcodes whose single operand is s24 (relative branch offsets), not u30
S24_OPS = set(range(0x10, 0x1B))            # jump 0x10 .. ifstrictne 0x1A
S24_OPS |= {0x0C, 0x0D, 0x0E, 0x0F}        # ifnlt..ifnge
OP_LOOKUPSWITCH = 0x1B
OP_DEBUG = 0xEF
OP_PUSHBYPE = 0x24

TAG_NAMES = {
    0:"End",1:"ShowFrame",2:"DefineShape",4:"PlaceObject",5:"RemoveObject",6:"DefineBits",
    7:"DefineButton",8:"JPEGTables",9:"SetBackgroundColor",10:"DefineFont",11:"DefineText",
    12:"DoAction",13:"DefineFontInfo",14:"DefineSound",15:"StartSound",18:"SoundStreamHead",
    19:"SoundStreamBlock",20:"DefineBitsLossless",21:"DefineBitsJPEG2",22:"DefineShape2",
    24:"Protect",26:"PlaceObject2",28:"RemoveObject2",32:"DefineShape3",33:"DefineText2",
    34:"DefineButton2",35:"DefineBitsJPEG3",36:"DefineBitsLossless2",37:"DefineEditText",
    39:"DefineSprite",43:"FrameLabel",45:"SoundStreamHead2",46:"DefineMorphShape",
    48:"DefineFont2",56:"ExportAssets",57:"ImportAssets",58:"EnableDebugger",59:"DoInitAction",
    60:"DefineVideoStream",61:"VideoFrame",62:"DefineFontInfo2",63:"DebugID",64:"EnableDebugger2",
    65:"ScriptLimits",66:"SetTabIndex",69:"FileAttributes",70:"PlaceObject3",71:"ImportAssets2",
    73:"DefineFontAlignZones",74:"CSMTextSettings",75:"DefineFont3",76:"SymbolClass",77:"Metadata",
    78:"DefineScalingGrid",82:"DoABC",83:"DefineShape4",84:"DefineMorphShape2",
    86:"DefineSceneAndFrameLabelData",87:"DefineBinaryData",88:"DefineFontName",89:"StartSound2",
    90:"DefineBitsJPEG4",91:"DefineFont4",93:"EnableTelemetry",
}
DOABC = 82

def iter_tags(data):
    if len(data) < 8: raise ValueError("too short for SWF header")
    sig = data[:3]
    if sig not in (b"FWS", b"CWS", b"ZWS"): raise ValueError(f"not an SWF: {sig!r}")
    version = data[3]
    declared_len = struct.unpack_from("<I", data, 4)[0]
    body = data[8:]
    if sig == b"CWS": body = zlib.decompress(body)
    elif sig == b"ZWS": body = lzma.decompress(body)
    nbits = body[0] >> 3
    p = (5 + nbits * 4 + 7) // 8 + 4  # Rect + frame_rate(2) + frame_count(2)
    tag_counts, abc_blocks, total_bytes = collections.Counter(), [], 0
    while p + 2 <= len(body):
        (hdr,) = struct.unpack_from("<H", body, p); p += 2
        code, length = hdr >> 6, hdr & 0x3F
        if length == 0x3F:
            if p + 4 > len(body): break
            (length,) = struct.unpack_from("<I", body, p); p += 4
        if code == 0: break
        end = min(p + length, len(body))
        payload = body[p:end]
        tag_counts[code] += 1
        total_bytes += length
        if code == DOABC and len(payload) > 4:
            z = payload.find(b"\0", 4)
            name = payload[4:z].decode("utf-8", "replace") if z > 0 else "?"
            abc_blocks.append((name, payload[(z + 1) if z > 0 else 4:]))
        p = end
    return dict(version=version, declared_size=declared_len, tag_counts=tag_counts,
                tag_bytes=total_bytes, abc_blocks=abc_blocks, body_len=len(body))

class AbcReader:
    def __init__(self, data): self.b, self.p = data, 0
    def u8(self):
        v = self.b[self.p]; self.p += 1; return v
    def u16(self):
        v = struct.unpack_from("<H", self.b, self.p)[0]; self.p += 2; return v
    def u30(self):
        v, self.p = read_u30(self.b, self.p); return v
    def s24(self):
        v, self.p = read_s24(self.b, self.p); return v
    def skip(self, n): self.p += n

def parse_abc(abc, opmap, stats):
    r = AbcReader(abc)
    r.u16(); r.u16()                      # minor_version, major_version (U16 each!)
    # ---- constant pool: counts are 1-based ("0 entry is not used") ----
    # S32/U32 pool entries are VARIABLE-LENGTH U30-style, NOT fixed 4 bytes
    # (abcFormat-46-16.txt: "S32,U32 - same as U30 but 32 bits are allowed").
    n = r.u30()
    for _ in range(max(n - 1, 0)): r.u30()      # int
    n = r.u30()
    for _ in range(max(n - 1, 0)): r.u30()      # uint
    n = r.u30(); r.skip(8 * max(n - 1, 0))     # double: 8 fixed bytes each
    n = r.u30(); strings = [""]
    for _ in range(max(n - 1, 0)):
        ln = r.u30(); strings.append(r.b[r.p:r.p+ln].decode("utf-8", "replace")); r.skip(ln)
    n = r.u30()                                   # namespaces: kind(u8) + name_index(u30)
    for _ in range(max(n - 1, 0)):
        r.u8(); r.u30()
    n = r.u30()                                   # namespace sets
    for _ in range(max(n - 1, 0)):
        cnt = r.u30()
        for _ in range(cnt): r.u30()
    n = r.u30(); multinames = [None]             # multinames
    for _ in range(max(n - 1, 0)):
        k = r.u8()
        if   k in (0x07, 0x0D, 0x09, 0x0E):  # QName(A), Multiname(A): 2x u30
            r.u30(); r.u30()
        elif k in (0x0F, 0x10, 0x1B, 0x1C):  # RTQName(A), MultinameL(A): 1x u30
            r.u30()
        elif k in (0x11, 0x12, 0x13, 0x14):  # RTQNameL(A), NameL(A): no operands
            pass
        elif k == 0x1D:                        # TypeName: base + type param count + params
            r.u30(); c = r.u30()
            for _ in range(c): r.u30()
        multinames.append(k)
    # ---- methods ----
    nmethod = r.u30(); methods = []
    for _ in range(nmethod):
        nargs = r.u30(); r.u30()
        for _ in range(nargs): r.u30()
        ni = r.u30(); flags = r.u8()
        if flags & 0x08:
            no = r.u30()
            for _ in range(no): r.u30(); r.u8()
        if flags & 0x80:
            for _ in range(nargs): r.u30()
        methods.append(strings[ni] if ni < len(strings) else "?")
    def traits():
        n = r.u30()
        for _ in range(n):
            r.u30(); kind = r.u8(); form = kind & 0x0F
            if form in (0, 6):
                r.u30(); r.u30(); vi = r.u30()
                if vi: r.u8()
            elif form in (1, 2, 3, 4, 5): r.u30(); r.u30()
            if (kind >> 4) & 0x04:
                nm = r.u30()
                for _ in range(nm): r.u30()
    n = r.u30()                                    # metadata
    for _ in range(n):
        r.u30(); ni = r.u30()
        for _ in range(ni): r.u30(); r.u30()
    nclass = r.u30()
    for _ in range(nclass):                       # InstanceInfo[n]
        r.u30(); r.u30(); flags = r.u8()
        if flags & 0x08: r.u30()
        ni = r.u30()
        for _ in range(ni): r.u30()
        r.u30(); traits()
    for _ in range(nclass):                       # ClassInfo[n]
        r.u30(); traits()
    n = r.u30()                                    # ScriptInfo
    for _ in range(n): r.u30(); traits()
    nbodies = r.u30()
    stats["abc_blocks"] += 1
    stats["methods"] += nmethod; stats["bodies"] += nbodies
    stats["classes"] += nclass; stats["multinames"] += max(len(multinames) - 1, 0)
    hist = stats["opcode_hist"]
    bigrams = stats["bigrams"]
    for _ in range(nbodies):
        mi = r.u30(); r.u30(); r.u30(); r.u30(); r.u30()
        codelen = r.u30(); code = r.b[r.p:r.p+codelen]; r.skip(codelen)
        nexc = r.u30()
        for _ in range(nexc):
            for _ in range(5): r.u30()
        traits()
        stats["code_bytes"] += codelen
        q = 0
        prev_name = None
        while q < len(code):
            op = code[q]; q += 1
            name, nops, _ = opmap.get(op, (f"UNK_{op:02x}", 0, 0))
            hist[name] += 1; stats["total_instr"] += 1
            if prev_name is not None:
                bigrams[(prev_name, name)] += 1
            prev_name = name
            try:
                if op == OP_LOOKUPSWITCH:       # default:s24, case_count:u30, cases:(n+1)*s24
                    q += 3
                    nc, q = read_u30(code, q)
                    q += 3 * (nc + 1)
                elif op == OP_DEBUG:            # debug_type:u8, index:u30, reg:u8, extra:u30
                    q += 1
                    _, q = read_u30(code, q)
                    q += 1
                    _, q = read_u30(code, q)
                elif op in S24_OPS:
                    q += 3
                elif op == OP_PUSHBYPE:         # pushbyte: signed byte
                    q += 1
                else:
                    for _ in range(nops):
                        _, q = read_u30(code, q)
            except (IndexError, ValueError):
                break                           # tolerate malformed tail
    return

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("swf")
    ap.add_argument("--tbl", required=True)
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args()
    t0 = time.time()
    opmap = load_opcode_table(a.tbl)
    data = open(a.swf, "rb").read()
    info = iter_tags(data)
    stats = dict(abc_blocks=0, methods=0, bodies=0, classes=0, multinames=0,
                 code_bytes=0, total_instr=0, opcode_hist=collections.Counter(),
                 bigrams=collections.Counter())
    per_abc, failures = [], []
    for name, abc in info["abc_blocks"]:
        before = stats["code_bytes"]
        try: parse_abc(abc, opmap, stats)
        except Exception as e: failures.append(f"{name}: {type(e).__name__}: {e}")
        per_abc.append(dict(name=name, bytes=len(abc), code_bytes=stats["code_bytes"] - before))
    tot = max(stats["total_instr"], 1)
    out = dict(file=os.path.basename(a.swf), size_mb=round(len(data)/1048576, 1),
               swf_version=info["version"], declared_body_len=info["declared_size"],
               actual_body_len=info["body_len"], tag_total_bytes=info["tag_bytes"],
               tag_counts={TAG_NAMES.get(k, f"tag{k}"): v for k, v in info["tag_counts"].most_common()},
               abc_blocks=per_abc, parse_failures=failures,
               stats={k: v for k, v in stats.items()
                      if k not in ("opcode_hist", "bigrams")},
               top_opcodes=[dict(op=k, count=v, pct=round(100*v/tot, 2))
                            for k, v in stats["opcode_hist"].most_common(a.top)],
               all_opcodes=dict(stats["opcode_hist"]),
               top_bigrams=[dict(pair=f"{k[0]}+{k[1]}", count=v,
                                 pct=round(100*v/tot, 2))
                            for k, v in stats["bigrams"].most_common(30)],
               elapsed_s=round(time.time()-t0, 1))
    print(f"SWF {out['file']}  {out['size_mb']} MB  v{out['swf_version']}  "
          f"{len(info['abc_blocks'])} DoABC blocks  {time.time()-t0:.1f}s")
    print(f"  method bodies: {stats['bodies']:,}  classes: {stats['classes']:,}  "
          f"multinames: {stats['multinames']:,}  ABC code: {stats['code_bytes']:,} B  "
          f"decoded instrs: {stats['total_instr']:,}")
    if failures: print("  parse warnings:", "; ".join(failures[:3]))
    print("  top tags: " + ", ".join(f"{k}x{v}" for k, v in list(out["tag_counts"].items())[:12]))
    print("\n  TOP AVM2 opcodes in this game's bytecode:")
    for row in out["top_opcodes"][:24]:
        print(f"    {row['op']:<22} {row['count']:>9,}  {row['pct']:>5.2f}%  " +
              "#" * min(40, int(row["pct"] * 1.6)))
    print("\n  TOP opcode bigrams (candidates for superinstructions):")
    for row in out["top_bigrams"][:16]:
        print(f"    {row['pair']:<40} {row['count']:>9,}  {row['pct']:>5.2f}%")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f: json.dump(out, f, indent=1, ensure_ascii=False)
        print(f"\n  JSON -> {a.json}")

if __name__ == "__main__": main()
