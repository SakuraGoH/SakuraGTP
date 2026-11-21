import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import PE, PATH
import capstone

pe = PE(PATH)
d = pe.d
IB = 0x400000
strs = {}
for s in pe.secs:
    if s['name'] not in ('.rdata', '.data'):
        continue
    blob = d[s['ro']:s['ro'] + s['rsz']]
    for m in re.finditer(rb'[\x20-\x7e]{3,}', blob):
        strs[IB + s['va'] + m.start()] = m.group().decode('latin1')

inter = {k: v for k, v in strs.items() if v.startswith('$') and len(v) < 12}
for k in sorted(inter):
    print('%08x %r' % (k, inter[k]))

text = [s for s in pe.secs if s['name'] == '.text'][0]
code = d[text['ro']:text['ro'] + text['rsz']]
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True
refs = {}
for ins in md.disasm(code, IB + text['va']):
    try:
        ops = ins.operands
    except Exception:
        continue
    for op in ops:
        v = None
        if op.type == capstone.x86.X86_OP_IMM:
            v = op.imm
        elif op.type == capstone.x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
            v = op.mem.disp
        if v in inter:
            refs.setdefault(v, []).append(ins.address)
print('REFS:')
for k in sorted(refs):
    print('%08x %-14r <- %s' % (k, inter[k], ' '.join('%08x' % a for a in refs[k])))
