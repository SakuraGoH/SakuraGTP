"""Linear disassembly of FoxGTP.exe .text with string/import annotations.

Outputs a full listing plus an index of code references to interesting strings.
"""
import struct, re, sys, os, json, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import PE, PATH
import capstone

pe = PE(PATH)
d = pe.d
IMAGE_BASE = 0x400000

# ---- imports map: IAT address -> Name
iat = {}
rva, sz = pe.dd[1]
o = pe.r2o(rva)
i = 0
while True:
    ent = d[o + i * 20:o + i * 20 + 20]
    if len(ent) < 20 or ent == b'\x00' * 20:
        break
    oft, ts, fc, nameRva, ft = struct.unpack('<IIIII', ent)
    no = pe.r2o(nameRva)
    dll = d[no:d.index(b'\x00', no)].decode('latin1')
    fo = pe.r2o(oft or ft)
    j = 0
    while True:
        v = struct.unpack_from('<I', d, fo + j * 4)[0]
        if v == 0:
            break
        if not (v & 0x80000000):
            fn = pe.r2o(v)
            nm = d[fn + 2:d.index(b'\x00', fn + 2)].decode('latin1')
            iat[IMAGE_BASE + (oft or ft) + j * 4] = '%s!%s' % (dll, nm)
        j += 1
    i += 1

# ---- string map
strs = {}
for s in pe.secs:
    if s['name'] not in ('.rdata', '.data'):
        continue
    blob = d[s['ro']:s['ro'] + s['rsz']]
    for m in re.finditer(rb'[\x20-\x7e]{3,}', blob):
        va = IMAGE_BASE + s['va'] + m.start()
        strs[va] = m.group().decode('latin1')

text = [s for s in pe.secs if s['name'] == '.text'][0]
code = d[text['ro']:text['ro'] + text['rsz']]
code_va = IMAGE_BASE + text['va']

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True
md.skipdata = False

insns = []
for ins in md.disasm(code, code_va):
    insns.append(ins)

print('instructions:', len(insns))

# index by address
alist = [x.address for x in insns]


def annotate(ins):
    note = ''
    try:
        ops = ins.operands
    except Exception:
        return note
    for op in ops:
        if op.type == capstone.x86.X86_OP_IMM:
            v = op.imm
            if v in strs:
                note += ' ; STR %r' % strs[v]
            elif v in iat:
                note += ' ; IMP %s' % iat[v]
        elif op.type == capstone.x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
            v = op.mem.disp
            if v in strs:
                note += ' ; STR %r' % strs[v]
            elif v in iat:
                note += ' ; IMP %s' % iat[v]
    return note


# function starts: after padding (cc / int3) or after ret+jmp
funcs = []
start = 0
prev_end = None
for ins in insns:
    m = ins.mnemonic
    if prev_end is not None and ins.address != prev_end:
        funcs.append((start, prev_end))
        start = ins.address
    if m in ('ret', 'int3') and ins.address + ins.size == (insns[insns.index(ins) + 1].address if insns.index(ins) + 1 < len(insns) else 0):
        pass
    prev_end = ins.address + ins.size
funcs.append((start, prev_end))

# simpler function segmentation via int3 padding runs
funcs = []
cur = None
for ins in insns:
    if ins.mnemonic in ('int3',):
        if cur:
            funcs.append(cur)
            cur = None
        continue
    if cur is None:
        cur = [ins.address, ins.address + ins.size]
    else:
        cur[1] = ins.address + ins.size
if cur:
    funcs.append(tuple(cur))
print('functions(heuristic):', len(funcs))

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'listing.txt'), 'w', encoding='utf-8') as f:
    for fnstart, fnend in funcs:
        f.write('\n; ==== FUNC %08x - %08x ====\n' % (fnstart, fnend))
        for ins in insns:
            if fnstart <= ins.address < fnend:
                f.write('%08x  %-28s %s%s\n' % (
                    ins.address, (ins.mnemonic + ' ' + ins.op_str).strip(),
                    '', annotate(ins)))
print('wrote listing.txt')

# report interesting references
interesting = [k for k, v in strs.items() if re.search(
    r'(genmove|play |komi|boardsize|clear_board|time_|final_score|protocol_version|set_free|resign|pass|white|black|%c%d|error)', v)]
print('\n=== REFERENCES ===')
refmap = {}
for ins in insns:
    for op in ins.operands:
        v = None
        if op.type == capstone.x86.X86_OP_IMM:
            v = op.imm
        elif op.type == capstone.x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
            v = op.mem.disp
        if v in interesting:
            refmap.setdefault(v, []).append(ins.address)
for k in sorted(refmap):
    print('%08x %-30r <- %s' % (k, strs[k], ', '.join('%08x' % a for a in refmap[k])))
