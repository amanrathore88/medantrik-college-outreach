import json,re,html
from pathlib import Path
root=Path(__file__).parent/'data'
for r in json.loads((root/'contact_candidates.json').read_text()):
    if not r.get('snapshot') or not (r['candidates'] or r.get('listed_email_found')):continue
    body=(root/'sources'/r['snapshot']).read_text(encoding='utf-8')
    title=re.search('<title[^>]*>(.*?)</title>',body,re.S|re.I)
    text=html.unescape(re.sub('<[^>]+>',' ',re.sub(r'<(script|style)\b.*?</\1>','',body,flags=re.S|re.I)))
    text=' '.join(text.split())
    print('\n'+r['name']+' | '+r['url']+' | '+(html.unescape(title[1]).strip()[:90] if title else ''))
    for email in r['candidates']:
        pos=text.lower().find(email)
        print(email+' | '+(text[max(0,pos-90):pos+len(email)+90] if pos>=0 else 'In page HTML/link; not visible in extracted text'))
