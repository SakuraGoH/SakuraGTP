import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import PE, PATH

pe = PE(PATH)
d = pe.d
start, end = 0x880, 0xC00
o = pe.r2o(0x29000 + start)
blob = d[o:o + (end - start)]
for i in range(0, len(blob), 16):
    chunk = blob[i:i + 16]
    hexs = ' '.join('%02x' % c for c in chunk)
    asc = ''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)
    print('%08x  %-47s  %s' % (0x29000 + start + i, hexs, asc))
