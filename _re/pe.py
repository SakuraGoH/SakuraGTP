import struct, sys, os

# 指向野狐官方接入包里的 FoxGTP.exe；用环境变量覆盖，别把本机路径写死
PATH = os.environ.get(
    'FOXGTP_EXE',
    r'C:\FoxGTP\FoxGTP.exe')


class PE:
    def __init__(self, path):
        self.path = path
        self.d = open(path, 'rb').read()
        d = self.d
        e = struct.unpack_from('<I', d, 0x3c)[0]
        self.e = e
        nsec = struct.unpack_from('<H', d, e + 6)[0]
        optsz = struct.unpack_from('<H', d, e + 20)[0]
        opt = e + 24
        self.opt = opt
        magic = struct.unpack_from('<H', d, opt)[0]
        self.pe32plus = magic == 0x20b
        ddoff = opt + (112 if self.pe32plus else 96)
        ndd = struct.unpack_from('<I', d, opt + (108 if self.pe32plus else 92))[0]
        self.dd = [struct.unpack_from('<II', d, ddoff + i * 8) for i in range(min(ndd, 16))]
        self.secs = []
        so = opt + optsz
        for i in range(nsec):
            o = so + i * 40
            name = d[o:o + 8].rstrip(b'\x00').decode('latin1')
            vsz, va, rsz, ro = struct.unpack_from('<IIII', d, o + 8)
            chars = struct.unpack_from('<I', d, o + 36)[0]
            self.secs.append(dict(name=name, va=va, vsz=vsz, ro=ro, rsz=rsz, chars=chars))

    def r2o(self, rva):
        for s in self.secs:
            if s['va'] <= rva < s['va'] + max(s['vsz'], s['rsz']):
                return s['ro'] + (rva - s['va'])
        return None

    def o2r(self, off):
        for s in self.secs:
            if s['ro'] <= off < s['ro'] + s['rsz']:
                return s['va'] + (off - s['ro'])
        return None

    def data(self, rva, size):
        o = self.r2o(rva)
        return self.d[o:o + size]


def main():
    pe = PE(PATH)
    print('sections:')
    for s in pe.secs:
        print('  %-8s VA=%08x VSZ=%08x RAW=%08x RSZ=%08x chars=%08x' % (
            s['name'], s['va'], s['vsz'], s['ro'], s['rsz'], s['chars']))
    print('data dirs:')
    for i, (r, v) in enumerate(pe.dd):
        if r or v:
            print('  %2d rva=%08x size=%08x' % (i, r, v))
    rva, sz = pe.dd[6]
    if rva:
        o = pe.r2o(rva)
        print('debug entries:')
        for i in range(sz // 28):
            fields = struct.unpack('<IIHHIIII', pe.d[o + i * 28:o + i * 28 + 28])
            ch, t, ma, mi, dsz, addr, ptr, res = fields[0], fields[4], 0, 0, fields[5], fields[6], fields[7], 0
            print('  type=%d size=%d ptr=%08x' % (t, dsz, ptr))
            if ptr:
                print('   ', pe.d[ptr:ptr + dsz])

    print('resources:')
    rrva, _ = pe.dd[2]
    base = pe.r2o(rrva)

    def walk(off, depth, path):
        nname, nid = struct.unpack_from('<HH', pe.d, base + off + 12)
        for i in range(nname + nid):
            ep = base + off + 16 + i * 8
            nm, ofs = struct.unpack_from('<II', pe.d, ep)
            if nm & 0x80000000:
                so2 = base + (nm & 0x7fffffff)
                ln = struct.unpack_from('<H', pe.d, so2)[0]
                name = pe.d[so2 + 2:so2 + 2 + ln * 2].decode('utf-16le', 'replace')
            else:
                name = nm
            if ofs & 0x80000000:
                walk(ofs & 0x7fffffff, depth + 1, path + [name])
            else:
                drva, dsz, cp, _ = struct.unpack_from('<IIII', pe.d, base + ofs)
                print('  ' * depth + '%s data_off=%s size=%d' % (path + [name], hex(pe.r2o(drva)), dsz))

    walk(0, 0, [])


if __name__ == '__main__':
    main()
