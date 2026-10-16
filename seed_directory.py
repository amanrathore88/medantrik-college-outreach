"""Apply reviewed official-source seed across Delhi, Noida, Greater Noida, Ghaziabad, and Gurugram.
Preserves operator changes and retains complete audit history.
"""
import json
from directory import BASE_DIR, initialize, connect, key, normalize, save_record, get_colleges

CHECKED = '2026-10-16'
REVIEWED_DU = {
    'Aditi Mahavidyalaya': 'info@aditi.du.ac.in',
    'Atma Ram Sanatan Dharma College': 'principal@arsd.du.ac.in',
    'Bhim Rao Ambedkar College': 'info@drbrambedkarcollege.ac.in',
    'Deen Dayal Upadhyaya College': 'office@ddu.du.ac.in',
    'Dyal Singh College': 'principal@dsc.du.ac.in',
    'Institute of Home Economics': 'principal@ihe.du.ac.in',
    'Kamla Nehru College for Women': 'office@knc.du.ac.in',
    'Keshav Mahavidyalaya': 'principal@keshav.du.ac.in',
    'Lady Shri Ram College for Women': 'principal@lsr.du.ac.in',
    'Maharaja Agarsen College': 'principal@mac.du.ac.in',
    'Maharshi Valmiki College of Education': 'info@mvced.du.ac.in',
    'Miranda House': 'principal@mirandahouse.ac.in',
    'P.G.D.A.V. College': 'principal@pgdav.du.ac.in',
    'Rajdhani College': 'principal@rajdhani.du.ac.in',
    'Satyawati College': 'principal@satyawati.du.ac.in',
    'Shaheed Bhagat Singh College (Evening)': 'info@sbse.du.ac.in',
    'Shaheed Rajguru College of Applied Sciences for Women': 'principal@rajguru.du.ac.in',
    'Shyam Lal College': 'principal@shyamlal.du.ac.in',
    'Sri Aurobindo College': 'principal@aurobindo.du.ac.in',
    'Sri Venkateswara College': 'principal@svc.ac.in',
    'Swami Shraddhanand College': 'principal@ss.du.ac.in',
    'Janta Degree College Patla, Ghaziabad': 'info@jdcpatala.org'
}

def main():
    initialize()
    data = BASE_DIR / 'data'
    records = json.loads((data / 'official_inventory.json').read_text(encoding='utf-8'))
    
    candidates_file = data / 'contact_candidates.json'
    candidates = {}
    if candidates_file.exists():
        candidates = {r['name']: r for r in json.loads(candidates_file.read_text(encoding='utf-8'))}

    for record in records:
        name = record['College_Name']
        if name in REVIEWED_DU:
            email = REVIEWED_DU[name]
            evidence = candidates.get(name)
            snapshot = evidence['snapshot'] if evidence and 'snapshot' in evidence else ''
            url = evidence['url'] if evidence and 'url' in evidence else record.get('Website', 'https://www.du.ac.in')
            record.update(
                TPO_Email=email, source_url=url, checked_on=CHECKED,
                verification_status='verified', contact_type='general',
                notes=f'Official institution homepage contact block reviewed. General office contact, not a placement mailbox. Evidence snapshot: {snapshot}' if snapshot else 'Official institution contact reviewed.'
            )
        if name == 'Sri Aurobindo College (Evening)':
            record['notes'] = 'Official homepage declares principal.sace.du@gmail.com non-operational/obsolete. Do not use that address; replacement contact still needed.'
        if name == 'Suraj Degree College, Sector-75, Gurugram':
            record['notes'] = 'Government directory email retained as unverified directory evidence. Linked website currently describes a B.Ed college in Mahendergarh; do not substitute that campus contact.'

    marker = 'official_seed_2026_10_16_v2'
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM metadata WHERE key=?', (marker,)).fetchone():
            print('Seed v2 already applied; operator changes preserved.')
            return

        updated_count = 0
        inserted_count = 0
        for raw in records:
            record = normalize(raw)
            old = db.execute('SELECT * FROM colleges WHERE identity=? AND archived=0', (key(record),)).fetchone()
            if old:
                previous = json.loads(old['payload'])
                # Preserve detailed legacy addresses and classifications while updating evidence.
                if previous.get('Location') and record['Location'] == record['City']:
                    record['Location'] = previous['Location']
                if previous.get('Aliases') and not record.get('Aliases'):
                    record['Aliases'] = previous['Aliases']
                if previous.get('do_not_contact'):
                    record['do_not_contact'] = True
                save_record(record, old['id'], old['version'], 'official source review', db)
                updated_count += 1
            else:
                save_record(record, action='official source inventory', db=db)
                inserted_count += 1

        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (marker, CHECKED))
        print(f'Seed v2 applied: updated {updated_count}, inserted {inserted_count} institutions.')

    colleges = get_colleges()
    print('Total active directory records:', len(colleges))
    for area in ['Delhi', 'Noida', 'Greater Noida', 'Ghaziabad', 'Gurugram']:
        subset = [c for c in colleges if c['City'] == area]
        verified = sum(c['verification_status'] == 'verified' for c in subset)
        missing = sum(not c['TPO_Email'] for c in subset)
        print(f"  {area:15s}: {len(subset):3d} identified | {verified:3d} verified | {missing:3d} missing email")

if __name__ == '__main__':
    main()
