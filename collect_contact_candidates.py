"""Fetch known official homepages for review. Does not change the database or send mail."""
import concurrent.futures
import hashlib
import html
import json
import re
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

DATA=Path(__file__).parent/'data'
def fetch(record):
    url=record.get('Website','')
    if not url or urlparse(url).scheme not in ['https','http']:return None
    if urlparse(url).hostname in ['localhost','127.0.0.1','0.0.0.0']:return None
    try:
        # Prefer HTTPS without inventing a new domain or endpoint.
        secure=url.replace('http://','https://',1)
        request=urllib.request.Request(secure,headers={'User-Agent':'Mozilla/5.0 (institution directory research)'})
        with urllib.request.urlopen(request,timeout=12) as response:
            final=response.url
            if urlparse(final).hostname.removeprefix('www.') != urlparse(url).hostname.removeprefix('www.'):
                return dict(name=record['College_Name'],url=final,status='redirect requires review',candidates=[])
            body=response.read(2500000).decode('utf-8',errors='replace')
        decoded=html.unescape(body)
        for coded in re.findall(r'data-cfemail=["\x27]([0-9a-f]+)',decoded):
            try:
                values=bytes.fromhex(coded)
                decoded+=' '+''.join(chr(b^values[0]) for b in values[1:])
            except ValueError:pass
        emails=sorted(set(re.findall(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}',decoded)))
        emails=[e.lower() for e in emails if not e.lower().endswith(('.png','.jpg','.webp','.svg','.woff'))]
        generic=[e for e in emails if re.match(r'^(info|office|principal|contact|enquiry|inquiry|college|admin|placement|placements|tpo|career|crc|director|registrar|mail)[._@-]',e)]
        snapshot='contact-'+hashlib.sha256(url.encode()).hexdigest()[:12]+'.html'
        (DATA/'sources'/snapshot).write_text(body,encoding='utf-8')
        return dict(name=record['College_Name'],url=final,status='fetched',snapshot=snapshot,candidates=generic,
                    listed_email_found=record.get('TPO_Email','').lower() in [e.lower() for e in emails] if record.get('TPO_Email') else False)
    except Exception as error:
        return dict(name=record['College_Name'],url=url,status=type(error).__name__,candidates=[])

if __name__=='__main__':
    records=json.loads((DATA/'official_inventory.json').read_text(encoding='utf-8'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results=[r for r in pool.map(fetch,records) if r]
    (DATA/'contact_candidates.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print('Fetched:',sum(r['status']=='fetched' for r in results),'of',len(results))
    for result in results:
        if result['candidates'] or result.get('listed_email_found'):
            print(result['name'],'|',', '.join(result['candidates']),'| listed email:',result.get('listed_email_found'))
