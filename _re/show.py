import sys, re
f = open(r'C:\Users\10632\Desktop\SakuraGTP\_re\listing.txt', encoding='utf-8')
lines = f.readlines()
start = int(sys.argv[1], 16)
end = int(sys.argv[2], 16) if len(sys.argv) > 2 else start + 0x100
for ln in lines:
    m = re.match(r'^([0-9a-f]{8})  ', ln)
    if m:
        a = int(m.group(1), 16)
        if start <= a < end:
            sys.stdout.write(ln)
