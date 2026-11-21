import struct, sys, os, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import PE, PATH
import capstone

pe = PE(PATH)
d = pe.d
IMAGE_BASE = 0x400000
# IAT name map
rva, sz = pe.dd[1]
o = pe.r2o(rva)
names = {}
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
        addr = IMAGE_BASE + (oft or ft) + j * 4
        if v & 0x80000000:
            nm = '%s!ord#%d' % (dll, v & 0xffff)
        else:
            fn = pe.r2o(v)
            nm = '%s!%s' % (dll, d[fn + 2:d.index(b'\x00', fn + 2)].decode('latin1'))
        names[addr] = nm
        j += 1
    i += 1

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
for a in range(0x4291c0, 0x4292e0, 4):
    rva = a - IMAGE_BASE
    off = pe.r2o(rva)
    val = struct.unpack_from('<I', d, off)[0]
    # if val points into .text, disassemble 2 insns
    tgt_off = pe.r2o(val - IMAGE_BASE) if val >= IMAGE_BASE else None
    desc = ''
    if tgt_off:
        code = d[tgt_off:tgt_off + 16]
        for ins in md.disasm(code, val):
            desc += ' %s %s;' % (ins.mnemonic, ins.op_str)
            if ins.mnemonic == 'jmp':
                break
    print('%08x -> %08x %s' % (a, val, desc))
