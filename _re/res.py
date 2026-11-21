import struct, re, sys
from pe import PE, PATH

pe = PE(PATH)
d = pe.d

print('=== UTF-16LE STRINGS (.rdata/.data/.text) ===')
for s in pe.secs:
    if s['name'] not in ('.rdata', '.data', '.text'):
        continue
    blob = d[s['ro']:s['ro'] + s['rsz']]
    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){3,}', blob):
        txt = m.group().decode('utf-16le', 'replace')
        print('%s+%06x: %r' % (s['name'], m.start(), txt))

print('\n=== RESOURCE STRING TABLES ===')
rrva, _ = pe.dd[2]
base = pe.r2o(rrva)


def res_entries():
    out = []

    def walk(off, depth, path):
        nname, nid = struct.unpack_from('<HH', d, base + off + 12)
        for i in range(nname + nid):
            ep = base + off + 16 + i * 8
            nm, ofs = struct.unpack_from('<II', d, ep)
            if nm & 0x80000000:
                so2 = base + (nm & 0x7fffffff)
                ln = struct.unpack_from('<H', d, so2)[0]
                name = d[so2 + 2:so2 + 2 + ln * 2].decode('utf-16le', 'replace')
            else:
                name = nm
            if ofs & 0x80000000:
                walk(ofs & 0x7fffffff, depth + 1, path + [name])
            else:
                drva, dsz, cp, _ = struct.unpack_from('<IIII', d, base + ofs)
                out.append((path + [name], drva, dsz, cp))
    walk(0, 0, [])
    return out


ENTS = res_entries()

for path, drva, dsz, cp in ENTS:
    if path[0] != 6:
        continue
    blob = pe.data(drva, dsz)
    o = 0
    n = int(path[1])
    for k in range(16):
        if o + 2 > len(blob):
            break
        ln = struct.unpack_from('<H', blob, o)[0]
        o += 2
        st = blob[o:o + ln * 2].decode('utf-16le', 'replace')
        o += ln * 2
        sid = (n - 1) * 16 + k
        if st:
            print('str[%d] = %r' % (sid, st))

print('\n=== DIALOGS ===')


def decode_dialog(blob):
    o = 0
    style, exstyle, cdit, x, y, cx, cy = struct.unpack_from('<IIHHHHH', blob, 0)
    o = 18
    has_menu, cls, title = struct.unpack_from('<HHH', blob, o)
    o += 6
    menu = clsname = ttl = None
    if has_menu:
        if has_menu == 0xFFFF:
            menu = struct.unpack_from('<H', blob, o)[0]; o += 2
        else:
            e = blob.index(b'\x00\x00', o); menu = blob[o:e].decode('utf-16le'); o = e + 2
    if cls:
        if cls == 0xFFFF:
            clsname = struct.unpack_from('<H', blob, o)[0]; o += 2
        else:
            e = blob.index(b'\x00\x00', o); clsname = blob[o:e].decode('utf-16le'); o = e + 2
    if title:
        e = blob.index(b'\x00\x00', o); ttl = blob[o:e].decode('utf-16le'); o = e + 2
    print('dialog style=%08x ex=%08x items=%d pos=(%d,%d,%d,%d) cls=%r title=%r' % (
        style, exstyle, cdit, x, y, cx, cy, clsname, ttl))
    align = 4 if exstyle & 0x00100000 else 2
    for i in range(cdit):
        o = (o + (align - 1)) & ~(align - 1)
        cstyle, cex, cx0, cy0, ccx, ccy, cid = struct.unpack_from('<IIhhHHH', blob, o)
        o += 18
        ccls = None
        if struct.unpack_from('<H', blob, o)[0] == 0xFFFF:
            ccls = '#%d' % struct.unpack_from('<H', blob, o + 2)[0]; o += 4
        else:
            e = blob.index(b'\x00\x00', o); ccls = blob[o:e].decode('utf-16le'); o = e + 2
        if struct.unpack_from('<H', blob, o)[0] == 0xFFFF:
            txt = '#%d' % struct.unpack_from('<H', blob, o + 2)[0]; o += 4
        else:
            e = blob.index(b'\x00\x00', o); txt = blob[o:e].decode('utf-16le'); o = e + 2
        extra = 0
        if cstyle & 0x00000080:
            extra += 2
        if cstyle & 0x00000040:
            extra += 2
        if cstyle & 0x00000004:
            extra += 2
        o += extra
        print('   id=%-5d cls=%-20r style=%08x pos=(%d,%d,%d,%d) text=%r' % (
            cid, ccls, cstyle, cx0, cy0, ccx, ccy, txt))


for path, drva, dsz, cp in ENTS:
    if path[0] == 5:
        print('\n--- dialog %s (%d bytes) ---' % (path, dsz))
        try:
            decode_dialog(pe.data(drva, dsz))
        except Exception as e:
            print('parse error:', e)
