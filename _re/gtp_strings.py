import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe import PE, PATH

pe = PE(PATH)
d = pe.d
pats = ['Leela', 'analyze', 'kata', 'undo', 'list_commands', 'known_command', 'ponder',
        'Illegal', 'illegal', 'unknown', 'Unknown', 'prefix', 'Prefix', 'byo', 'Byo',
        'handicap', 'boardsize', 'genmove', 'final_score', 'clear_board', 'time_left',
        'komi', 'resign', 'pass', 'Black', 'White', 'gtp', 'GTP', 'sync', 'Sync',
        'response', 'Response', 'move', 'Move', 'error', 'Error', 'invalid', 'Invalid']
seen = set()
for s in pe.secs:
    if s['name'] not in ('.rdata', '.data'):
        continue
    b = d[s['ro']:s['ro'] + s['rsz']]
    for m in re.finditer(rb'[\x20-\x7e]{3,}', b):
        t = m.group().decode('latin1')
        if t in seen:
            continue
        if any(p in t for p in pats):
            seen.add(t)
            print('%s+%06x: %s' % (s['name'], m.start(), t))
