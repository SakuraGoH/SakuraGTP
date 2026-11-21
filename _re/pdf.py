import sys, os
from pypdf import PdfReader

BASE = r'C:\Users\10632\Desktop\野狐围棋AI接入程序和使用手册(Fox Go AI Program And Manual)20220606\Documents'
OUT = r'C:\Users\10632\Desktop\SakuraGTP\_re\pdf'
os.makedirs(OUT, exist_ok=True)

for fn in os.listdir(BASE):
    if not fn.lower().endswith('.pdf'):
        continue
    path = os.path.join(BASE, fn)
    try:
        r = PdfReader(path)
        txt = []
        for i, p in enumerate(r.pages):
            txt.append('\n===== PAGE %d =====\n' % (i + 1))
            txt.append(p.extract_text() or '')
        s = ''.join(txt)
        out = os.path.join(OUT, fn.replace('.pdf', '') + '.txt')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(s)
        print(fn, 'pages=', len(r.pages), 'chars=', len(s), '->', out)
    except Exception as e:
        print(fn, 'ERROR', e)
