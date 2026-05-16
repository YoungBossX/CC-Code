from pathlib import Path
import re
root=Path(r'x:/Git_Clone/CC-Code')
patterns=[
    (re.compile(r'CC-Code'), 'CC-Code'),
    (re.compile(r'CC-Code'), 'CC-Code'),
    (re.compile(r'cc-code', re.IGNORECASE), 'cc-code'),
    (re.compile(r'CC_CODE'), 'CC_CODE'),
    (re.compile(r'CC-CODE'), 'CC-CODE'),
    (re.compile(r'cc_code'), 'cc_code'),
    (re.compile(r'cc-code'), 'cc-code'),
]
changed=[]
for p in root.rglob('*'):
    if p.is_file():
        try:
            s=p.read_text(encoding='utf-8')
        except Exception:
            continue
        orig=s
        for pat, rep in patterns:
            s=pat.sub(rep, s)
        if s!=orig:
            p.write_text(s, encoding='utf-8')
            changed.append(str(p.relative_to(root)))
print('FILES_CHANGED:', len(changed))
for f in changed:
    print(f)
