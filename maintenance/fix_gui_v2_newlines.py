from pathlib import Path
p=Path("D:/dsh-fish/companion.py")
s=p.read_text(encoding="utf-8")
rep=[
 ("v['evidence_at']}"+chr(10)+'"', "v['evidence_at']}"+r'\n"'),
 ("号消息。"+chr(10)+'"',"号消息。"+r'\n"'),
 ("item['evidence_text'][:450]}"+chr(10)+chr(10)+'"', "item['evidence_text'][:450]}"+r'\n\n"')
]
for a,b in rep:
 if s.count(a)!=1: raise RuntimeError("Expected one newline bug: "+repr(a))
 s=s.replace(a,b)
p.write_text(s,encoding="utf-8")
print("NEWLINE_PATCH_OK")
