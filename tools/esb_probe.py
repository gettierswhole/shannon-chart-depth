import re, sys, zlib
b = open(sys.argv[1], 'rb').read()
print('size', len(b))
n = 0
for m in re.finditer(rb'<<(.*?)>>\s*stream\r?\n', b, re.S):
    start = m.end(); end = b.find(b'endstream', start)
    raw = b[start:end]
    hdr = m.group(1)[:200].replace(b'\n', b' ')
    try: d = zlib.decompress(raw)
    except Exception as e:
        try: d = zlib.decompressobj().decompress(raw)
        except Exception: d = None
    n += 1
    if d is None:
        print('--- stream', n, 'not flate', hdr[:120]); continue
    txt = d.decode('latin-1')
    kind = 'TEXT' if (' Tj' in txt or ' TJ' in txt) else 'other'
    print('--- stream', n, kind, len(d), hdr[:120])
    if kind == 'TEXT':
        strs = re.findall(r'\[(.*?)\]\s*TJ|\((.*?)\)\s*Tj|<([0-9A-Fa-f]+)>\s*Tj', txt)
        print('ops', len(strs))
        print(txt[:1500].replace('\r', '\n'))
        print('....')
        print(txt[len(txt)//2:len(txt)//2+1500].replace('\r', '\n'))
    elif b'beginbfchar' in d or b'beginbfrange' in d:
        print(txt[:1200])
