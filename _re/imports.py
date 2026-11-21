import struct, re, sys
from pe import PE, PATH

pe = PE(PATH)
d = pe.d

# ---- imports ----
rva, sz = pe.dd[1]
o = pe.r2o(rva)
print('=== IMPORTS ===')
i = 0
while True:
    ent = d[o + i * 20: o + i * 20 + 20]
    if len(ent) < 20 or ent == b'\x00' * 20:
        break
    oft, ts, fc, nameRva, ft = struct.unpack('<IIIII', ent)
    no = pe.r2o(nameRva)
    dll = d[no:d.index(b'\x00', no)].decode('latin1')
    print('\n' + dll)
    funcs = []
    fo = pe.r2o(oft or ft)
    j = 0
    while True:
        v = struct.unpack_from('<I', d, fo + j * 4)[0]
        if v == 0:
            break
        if v & 0x80000000:
            funcs.append('#%d' % (v & 0xffff))
        else:
            fn = pe.r2o(v)
            funcs.append(d[fn + 2: d.index(b'\x00', fn + 2)].decode('latin1'))
        j += 1
    print('  ' + ', '.join(funcs))
    i += 1

# ---- strings ----
print('\n=== ASCII STRINGS ===')
for s in pe.secs:
    if s['name'] not in ('.rdata', '.data', '.text'):
        continue
    blob = d[s['ro']:s['ro'] + s['rsz']]
    for m in re.finditer(rb'[\x20-\x7e]{4,}', blob):
        txt = m.group().decode('latin1')
        print('%s+%06x: %s' % (s['name'], m.start(), txt))
