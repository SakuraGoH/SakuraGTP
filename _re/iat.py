import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import PE, PATH

pe = PE(PATH)
d = pe.d
IMAGE_BASE = 0x400000
rva, sz = pe.dd[1]
o = pe.r2o(rva)
i = 0
rows = []
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
            nm = 'ord#%d' % (v & 0xffff)
        else:
            fn = pe.r2o(v)
            nm = d[fn + 2:d.index(b'\x00', fn + 2)].decode('latin1')
        rows.append((addr, '%s!%s' % (dll, nm)))
        j += 1
    i += 1
lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0
hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0xffffffff
for a, n in rows:
    if lo <= a <= hi:
        print('%08x  %s' % (a, n))
