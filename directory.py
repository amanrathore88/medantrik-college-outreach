"""Persistent college directory with provenance, reviewable imports and audit history."""
import csv
import io
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlparse
from settings import BASE_DIR, load_settings
from mailer import validate_email

DB_PATH = BASE_DIR / 'data' / 'directory.sqlite3'
AREAS = ['Delhi', 'Noida', 'Greater Noida', 'Ghaziabad', 'Gurugram']
FIELDS = ['College_Name','category','Location','City','District','Type','Campus','Institution_ID','Aliases',
          'Website','TPO_Email','contact_type','Contact_Person','Phone','source_url',
          'institution_source','checked_on','verification_status','notes','do_not_contact',
          'recruitment_stage','follow_up_date','assigned_to','last_reply_at','last_reply_notes']

STAGE_CHOICES = {
    'not_contacted': 'Not Contacted',
    'contacted': 'Contacted',
    'replied': 'Replied',
    'meeting_arranged': 'Meeting Arranged',
    'partnership_active': 'Partnership Active',
    'declined': 'Declined / Inactive'
}

def today():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()

@contextmanager
def connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30.0)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=30000')
    try:
        with db:
            yield db
    finally:
        db.close()

def key(record):
    normalize = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
    cat = normalize(record.get('category', 'Colleges'))
    base = '|'.join(normalize(record.get(f, '')) for f in ['College_Name', 'City', 'Campus'])
    if cat and cat != 'colleges':
        return f"{cat}|{base}"
    return base

def city_from(location):
    text = location.lower()
    if 'greater noida' in text: return 'Greater Noida'
    if 'noida' in text: return 'Noida'
    if 'ghaziabad' in text: return 'Ghaziabad'
    if 'gurgaon' in text or 'gurugram' in text: return 'Gurugram'
    return 'Delhi' if 'delhi' in text else ''

def normalize(raw):
    if not isinstance(raw, dict): raise ValueError('Each record must be an object.')
    result = {f: str(raw.get(f, '') or '').strip() for f in FIELDS if f != 'do_not_contact'}
    if any(len(value) > 4000 for value in result.values()): raise ValueError('A field exceeds 4000 characters.')
    result['category'] = str(raw.get('category') or 'Colleges').strip() or 'Colleges'
    result['do_not_contact'] = raw.get('do_not_contact', False) in [True, 1, 'true', 'True', '1']
    result['City'] = result['City'] or city_from(result['Location'])
    if result['City'].lower() == 'gurgaon': result['City'] = 'Gurugram'
    if not result['College_Name']:
        raise ValueError('Institution name and a supported area are required.')
    if result['category'].lower() == 'colleges':
        if result['City'] not in AREAS:
            raise ValueError('Institution name and a supported area are required.')
    elif not result['City']:
        result['City'] = 'Delhi'
    result['District'] = result['District'] or {'Noida':'Gautam Buddha Nagar','Greater Noida':'Gautam Buddha Nagar'}.get(result['City'], result['City'])
    for field in ['Website','source_url','institution_source']:
        if result[field] and (urlparse(result[field]).scheme not in ['http','https'] or not urlparse(result[field]).hostname):
            raise ValueError('Sources and website must be valid HTTP(S) URLs.')
    if result['TPO_Email']:
        result['TPO_Email'] = result['TPO_Email'].lower()
        validate_email(result['TPO_Email'])
    result['contact_type'] = result['contact_type'] or 'unknown'
    if result['contact_type'] not in ['placement','general','unknown']: raise ValueError('Invalid contact type.')
    result['verification_status'] = result['verification_status'] or ('unverified' if result['TPO_Email'] else 'missing')
    if result['verification_status'] not in ['verified','directory-listed','unverified','missing']:
        raise ValueError('Invalid verification status.')
    if result['verification_status'] in ['verified','directory-listed']:
        if not result['TPO_Email'] or not result['source_url'] or not result['checked_on']:
            raise ValueError('Sourced contacts require email, source URL and date checked.')
    if result['checked_on']:
        try: date = datetime.strptime(result['checked_on'], '%Y-%m-%d').date()
        except ValueError: raise ValueError('Use YYYY-MM-DD for date checked.') from None
        if date.isoformat() > today(): raise ValueError('Date checked cannot be in the future.')
    if not result['TPO_Email']: result['verification_status'] = 'missing'
    result['recruitment_stage'] = result.get('recruitment_stage') or 'not_contacted'
    if result['recruitment_stage'] not in STAGE_CHOICES:
        result['recruitment_stage'] = 'not_contacted'
    if result.get('follow_up_date'):
        try:
            datetime.strptime(result['follow_up_date'], '%Y-%m-%d')
        except ValueError:
            raise ValueError('Use YYYY-MM-DD for follow-up date.') from None
    return result

def initialize():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS colleges(id INTEGER PRIMARY KEY, identity TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, college_id INTEGER, action TEXT, before_json TEXT, after_json TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS imports(token TEXT PRIMARY KEY, payload TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP, used INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS outreach_log(id INTEGER PRIMARY KEY AUTOINCREMENT, college_id INTEGER, recipient_email TEXT NOT NULL, college_name TEXT, subject TEXT, status TEXT NOT NULL, error_message TEXT, sent_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, sender_email TEXT NOT NULL, subject TEXT NOT NULL, total_recipients INTEGER NOT NULL, successful_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, template_id INTEGER, template_snapshot TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS outreach_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, college_id INTEGER NOT NULL, activity_type TEXT NOT NULL, notes TEXT NOT NULL, author TEXT DEFAULT 'Hiring Team', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(college_id) REFERENCES colleges(id));
        CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY, description TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        for cat, desc in [
            ('Colleges', 'Higher education institutions and universities'),
            ('Gyms', 'Fitness centers, gyms, and health clubs'),
            ('Offices', 'Corporate offices, commercial workplaces, and startups'),
            ('Households', 'Residential communities, RWAs, and individual households')
        ]:
            db.execute('INSERT OR IGNORE INTO categories(name, description) VALUES (?, ?)', (cat, desc))
        for col, col_type in [('template_id', 'INTEGER'), ('template_snapshot', 'TEXT')]:
            try:
                db.execute(f'ALTER TABLE campaigns ADD COLUMN {col} {col_type}')
            except sqlite3.OperationalError:
                pass
        if not db.execute("SELECT 1 FROM metadata WHERE key='legacy_migrated'").fetchone():
            with (BASE_DIR / 'colleges_delhi_ncr.csv').open(encoding='utf-8-sig', newline='') as file:
                for row in csv.DictReader(file):
                    record = normalize(dict(row, verification_status='unverified', contact_type='placement', notes='Original company CSV. Email and placement role not yet source-checked.'))
                    db.execute('INSERT OR IGNORE INTO colleges(identity,payload) VALUES (?,?)', (key(record), json.dumps(record)))
            db.execute("INSERT INTO metadata VALUES ('legacy_migrated','1')")

def serialize(row):
    record = json.loads(row['payload'])
    record.update(id=row['id'], version=row['version'])
    record['category'] = record.get('category') or 'Colleges'
    if 'recruitment_stage' not in record or record['recruitment_stage'] not in STAGE_CHOICES:
        record['recruitment_stage'] = 'not_contacted'
    for k in ['follow_up_date', 'assigned_to', 'last_reply_at', 'last_reply_notes']:
        if k not in record:
            record[k] = ''
    # For Colleges: verified status check. For other categories: any record with email that is not DNC.
    is_college = record['category'].lower() == 'colleges'
    if is_college:
        record['sendable'] = bool(
            record['TPO_Email'] and 
            record['verification_status'] == 'verified' and 
            record['contact_type'] != 'unknown' and 
            not record['do_not_contact'] and
            record['recruitment_stage'] not in ['declined', 'partnership_active']
        )
    else:
        record['sendable'] = bool(
            record['TPO_Email'] and 
            not record['do_not_contact'] and
            record['recruitment_stage'] not in ['declined', 'partnership_active']
        )
    return record

def get_colleges():
    initialize()
    with connect() as db:
        outreach_map = {}
        try:
            for r in db.execute('SELECT college_id, MAX(sent_at) as last_sent FROM outreach_log WHERE status="sent" GROUP BY college_id'):
                if r['college_id']:
                    outreach_map[r['college_id']] = r['last_sent']
        except sqlite3.Error:
            pass
        results = []
        today_date = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        for row in db.execute('SELECT * FROM colleges WHERE archived=0 ORDER BY id'):
            record = serialize(row)
            last_dt = outreach_map.get(row['id'])
            record['last_outreach'] = last_dt or 'Never'
            record['recently_contacted'] = False
            record['days_since_outreach'] = None
            if last_dt:
                try:
                    sent_d = datetime.strptime(last_dt[:10], '%Y-%m-%d').date()
                    delta = (today_date - sent_d).days
                    record['days_since_outreach'] = delta
                    record['recently_contacted'] = (delta <= 14)
                except Exception:
                    pass
            if record.get('recruitment_stage') == 'not_contacted' and last_dt:
                record['recruitment_stage'] = 'contacted'
            results.append(record)
        return results

def query_colleges(query='', city='', status='', kind='', discipline='', stage='', category='', page=1, page_size=25):
    rows = get_colleges()
    if category and category.lower() != 'all':
        rows = [r for r in rows if r.get('category', 'Colleges').lower() == category.lower()]
    q = query.casefold().replace('gurgaon', 'gurugram')
    if city.lower() == 'gurgaon': city = 'Gurugram'
    rows = [r for r in rows if (not city or r['City'] == city) and (not status or r['verification_status'] == status)
            and (not kind or r['contact_type'] == kind)
            and (not discipline or discipline.casefold() in str(r.get('Type', '')).casefold())
            and (not stage or r.get('recruitment_stage') == stage)
            and (not q or q in ' '.join(str(r[f]) for f in FIELDS).casefold().replace('gurgaon','gurugram'))]
    page_size = max(1, min(int(page_size),100))
    total = len(rows)
    page = max(1, min(int(page), max(1,(total + page_size - 1)//page_size)))
    return {'items':rows[(page-1)*page_size:page*page_size], 'total':total, 'page':page, 'page_size':page_size}

# ==================== CATEGORIES MANAGEMENT ====================
def get_categories():
    initialize()
    with connect() as db:
        rows = db.execute('''
            SELECT name FROM categories 
            ORDER BY 
                CASE 
                    WHEN LOWER(name)='colleges' THEN 1 
                    WHEN LOWER(name)='gyms' THEN 2 
                    WHEN LOWER(name)='offices' THEN 3 
                    WHEN LOWER(name)='households' THEN 4 
                    ELSE 5 
                END, name
        ''').fetchall()
        return [r['name'] for r in rows]

def get_categories_with_counts():
    initialize()
    categories = get_categories()
    rows = get_colleges()
    counts = {}
    for r in rows:
        cat = r.get('category') or 'Colleges'
        counts[cat] = counts.get(cat, 0) + 1
    
    result = []
    for c in categories:
        result.append({
            'name': c,
            'count': counts.get(c, 0)
        })
    return result

def add_category(name, description=''):
    name = str(name or '').strip()
    if not name or len(name) > 50:
        raise ValueError('Category name must be between 1 and 50 characters.')
    initialize()
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO categories(name, description) VALUES (?, ?)', (name, description or f'{name} directory'))
    sync_spreadsheet_file()
    push_to_google_sheet_webhook('category_created', {'name': name})
    return get_categories_with_counts()

def delete_category(name):
    name = str(name or '').strip()
    if name.lower() == 'colleges':
        raise ValueError('Cannot delete the default Colleges category.')
    initialize()
    rows = get_colleges()
    if any(r.get('category', '').lower() == name.lower() for r in rows):
        raise ValueError(f'Cannot delete category "{name}" because it contains directory records. Move or delete the records first.')
    with connect() as db:
        db.execute('DELETE FROM categories WHERE LOWER(name)=LOWER(?)', (name,))
    sync_spreadsheet_file()
    push_to_google_sheet_webhook('category_deleted', {'name': name})
    return get_categories_with_counts()

def coverage():
    rows = get_colleges()
    areas = []
    for area in AREAS:
        subset = [r for r in rows if r['City'] == area]
        areas.append({
            'area': area,
            'identified': len(subset),
            'reviewed': sum(bool(r['checked_on']) for r in subset),
            'contact_found': sum(bool(r['TPO_Email']) for r in subset),
            'verified': sum(r['verification_status'] == 'verified' for r in subset),
            'directory_listed': sum(r['verification_status'] == 'directory-listed' for r in subset),
            'missing': sum(not r['TPO_Email'] for r in subset),
            'sendable': sum(r['sendable'] for r in subset),
            'needs_review': sum(r['verification_status'] in ['unverified', 'directory-listed', 'missing'] for r in subset)
        })
    manifest = BASE_DIR / 'data' / 'source_manifest.json'
    return {
        'areas': areas,
        'total': len(rows),
        'coverage_complete': False,
        'inventory_date': '2026-10-16',
        'scope': 'Delhi NCT; Noida and Greater Noida separately; full Ghaziabad and Gurugram districts.',
        'note': 'Working inventory, not an exhaustive census. Institution existence and mailbox verification are separate.',
        'sources': json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
    }

def save_record(raw, record_id=None, version=None, action='edit', db=None):
    if db is None:
        initialize()
        with connect() as connection:
            res = save_record(raw, record_id, version, action, connection)
        sync_spreadsheet_file()
        push_to_google_sheet_webhook('record_saved', res)
        return res
    record = normalize(raw)
    cat = record.get('category') or 'Colleges'
    db.execute('INSERT OR IGNORE INTO categories(name, description) VALUES (?, ?)', (cat, f'{cat} directory'))
    old = db.execute('SELECT * FROM colleges WHERE id=? AND archived=0', (record_id,)).fetchone() if record_id else None
    if record_id and not old: raise ValueError('College no longer exists. Refresh the directory.')
    if old and version is not None and int(version) != old['version']: raise ValueError('Record changed since you opened it. Refresh before saving.')
    duplicate = db.execute('SELECT id FROM colleges WHERE identity=? AND archived=0', (key(record),)).fetchone()
    if duplicate and duplicate['id'] != record_id: raise ValueError('This name, city and campus already exist. Review or merge the records.')
    payload = json.dumps(record)
    if old:
        db.execute('UPDATE colleges SET identity=?,payload=?,version=version+1 WHERE id=?', (key(record),payload,record_id))
    else:
        record_id = db.execute('INSERT INTO colleges(identity,payload) VALUES (?,?)', (key(record),payload)).lastrowid
    db.execute('INSERT INTO audit(college_id,action,before_json,after_json) VALUES (?,?,?,?)', (record_id,action,old['payload'] if old else None,payload))
    return serialize(db.execute('SELECT * FROM colleges WHERE id=?',(record_id,)).fetchone())

def preview_import(text):
    initialize()
    if not isinstance(text,str) or len(text)>2000000: raise ValueError('Import must be text, up to 2 MB.')
    try: raw = json.loads(text) if text.lstrip().startswith('[') else list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
    except (ValueError,csv.Error): raise ValueError('Invalid JSON or CSV import.') from None
    if not isinstance(raw,list) or not 1<=len(raw)<=5000: raise ValueError('Import 1–5000 records at a time.')
    existing = {key(r):r for r in get_colleges()}
    seen = set()
    results = []
    for index,row in enumerate(raw,1):
        try:
            row = normalize(row)
            # Importing a source URL is not evidence of human verification.
            row['verification_status'] = 'unverified' if row['TPO_Email'] else 'missing'
            identity = key(row)
            duplicate = identity in existing or identity in seen
            results.append({'row':index,'action':'skip duplicate' if duplicate else 'add','record':row})
            seen.add(identity)
        except ValueError as error:
            results.append({'row':index,'action':'error','message':str(error)})
    token = secrets.token_urlsafe(24)
    with connect() as db:
        db.execute('INSERT INTO imports(token,payload) VALUES (?,?)',(token,json.dumps(results)))
    return {'token':token,'rows':results,'add':sum(r['action']=='add' for r in results),'errors':sum(r['action']=='error' for r in results), 'duplicates':sum(r['action']=='skip duplicate' for r in results)}

def commit_import(token):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        batch = db.execute("SELECT * FROM imports WHERE token=? AND used=0 AND created >= datetime('now','-1 hour')",(token,)).fetchone()
        if not batch: raise ValueError('Import preview expired or was already applied. Preview again.')
        rows = json.loads(batch['payload'])
        if any(r['action']=='error' for r in rows): raise ValueError('Correct all invalid rows and preview again.')
        added = skipped = 0
        for row in rows:
            if row['action'] != 'add' or db.execute('SELECT 1 FROM colleges WHERE identity=?',(key(row['record']),)).fetchone():
                skipped += 1
                continue
            save_record(row['record'],action='import',db=db)
            added += 1
        db.execute('UPDATE imports SET used=1 WHERE token=?',(token,))
    sync_spreadsheet_file()
    return {'added':added,'skipped':skipped}

def duplicates():
    rows = get_colleges()
    result = []
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            shared = bool(a['TPO_Email'] and a['TPO_Email']==b['TPO_Email'])
            similar = a['City']==b['City'] and SequenceMatcher(None,key(a),key(b)).ratio()>=0.87
            if shared or similar: result.append({'first':a['id'],'second':b['id'],'reason':'Shared email — may be separate campuses' if shared else 'Similar name — review before merging'})
    return result

def merge_records(source_id,target_id,source_version,target_version):
    if int(source_id)==int(target_id): raise ValueError('Choose two different records.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        source = db.execute('SELECT * FROM colleges WHERE id=? AND archived=0',(source_id,)).fetchone()
        target = db.execute('SELECT * FROM colleges WHERE id=? AND archived=0',(target_id,)).fetchone()
        if not source or not target: raise ValueError('Record not found.')
        if source['version']!=int(source_version) or target['version']!=int(target_version): raise ValueError('Records changed; review them again.')
        a,b = json.loads(source['payload']),json.loads(target['payload'])
        if a['City']!=b['City']: raise ValueError('Do not merge campuses in different areas.')
        b['Aliases'] = '; '.join(filter(None,[b['Aliases'],a['College_Name'],a['Aliases']]))
        b['do_not_contact'] = a['do_not_contact'] or b['do_not_contact']
        b['notes'] += f"\nMerged record {source_id}; original details retained in audit history."
        saved = save_record(b,target_id,target_version,'merge target',db)
        db.execute('UPDATE colleges SET archived=1,identity=?,version=version+1 WHERE id=?',(f'archived:{source_id}:{key(a)}',source_id))
        db.execute('INSERT INTO audit(college_id,action,before_json,after_json) VALUES (?,?,?,?)',(target_id,f'merged source {source_id}',source['payload'],json.dumps(b)))
        return saved

def history(record_id):
    with connect() as db:
        return [dict(row) for row in db.execute('SELECT action,before_json,after_json,at FROM audit WHERE college_id=? ORDER BY id DESC',(record_id,))]

def log_outreach(college_id, recipient_email, college_name, subject, status, error_message=''):
    initialize()
    with connect() as db:
        db.execute(
            'INSERT INTO outreach_log(college_id, recipient_email, college_name, subject, status, error_message) VALUES (?,?,?,?,?,?)',
            (college_id, (recipient_email or '').lower().strip(), college_name or '', subject or '', status, error_message or '')
        )

def get_outreach_history(college_id=None, limit=50):
    initialize()
    with connect() as db:
        if college_id:
            rows = db.execute('SELECT * FROM outreach_log WHERE college_id=? ORDER BY id DESC LIMIT ?', (college_id, limit)).fetchall()
        else:
            rows = db.execute('SELECT * FROM outreach_log ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]

def log_campaign(name, sender_email, subject, total_recipients, successful_count, failed_count, status='completed', template_id=None, template_snapshot=None):
    initialize()
    with connect() as db:
        cur = db.execute(
            'INSERT INTO campaigns(name, sender_email, subject, total_recipients, successful_count, failed_count, status, template_id, template_snapshot) VALUES (?,?,?,?,?,?,?,?,?)',
            (name, sender_email, subject, total_recipients, successful_count, failed_count, status, template_id, template_snapshot)
        )
        return cur.lastrowid

def get_campaigns(limit=20):
    initialize()
    with connect() as db:
        rows = db.execute('SELECT * FROM campaigns ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]

def get_overview_stats():
    cov = coverage()
    rows = get_colleges()
    with connect() as db:
        recent_dispatches = [dict(r) for r in db.execute('SELECT * FROM outreach_log ORDER BY id DESC LIMIT 10').fetchall()]
        failures = [dict(r) for r in db.execute('SELECT * FROM outreach_log WHERE status="failed" ORDER BY id DESC LIMIT 10').fetchall()]
        recent_campaigns = [dict(r) for r in db.execute('SELECT * FROM campaigns ORDER BY id DESC LIMIT 5').fetchall()]
        try:
            q_row = db.execute("SELECT COUNT(*) as cnt FROM campaign_queue WHERE status='queued'").fetchone()
            queued_count = q_row['cnt'] if q_row else 0
        except sqlite3.Error:
            queued_count = 0

    records_needing_review = [
        {
            'id': r['id'],
            'College_Name': r['College_Name'],
            'City': r['City'],
            'Campus': r.get('Campus', ''),
            'verification_status': r['verification_status'],
            'contact_type': r['contact_type'],
            'TPO_Email': r['TPO_Email'],
            'notes': r['notes']
        }
        for r in rows if r['verification_status'] in ['unverified', 'directory-listed', 'missing']
    ][:12]

    return {
        'total': len(rows),
        'sendable': sum(r['sendable'] for r in rows),
        'verified': sum(r['verification_status'] == 'verified' for r in rows),
        'directory_listed': sum(r['verification_status'] == 'directory-listed' for r in rows),
        'unverified': sum(r['verification_status'] == 'unverified' for r in rows),
        'missing': sum(r['verification_status'] == 'missing' for r in rows),
        'needs_review': sum(r['verification_status'] in ['unverified', 'directory-listed', 'missing'] for r in rows),
        'coverage': cov['areas'],
        'queued_messages': queued_count,
        'recent_dispatches': recent_dispatches,
        'failures': failures,
        'recent_campaigns': recent_campaigns,
        'records_needing_review': records_needing_review,
        'duplicates_count': len(duplicates()),
        'inventory_date': cov.get('inventory_date', '2026-10-16'),
        'scope': cov.get('scope', ''),
        'note': cov.get('note', ''),
        'pipeline': get_pipeline_stats(),
        'categories': get_categories_with_counts()
    }

def get_college_detail(college_id):
    initialize()
    with connect() as db:
        row = db.execute('SELECT * FROM colleges WHERE id=? AND archived=0', (college_id,)).fetchone()
        if not row:
            raise ValueError('College not found.')
        record = serialize(row)
        hist = history(college_id)
        outreach = get_outreach_history(college_id)
        activities = get_college_activities(college_id)
        return {'record': record, 'history': hist, 'outreach': outreach, 'activities': activities}

# ==================== PHASE 6: OUTREACH TRACKING & RECRUITMENT PIPELINE ====================

def log_activity(college_id, activity_type, notes, author='Hiring Team'):
    """Record an internal activity, call summary, or note for an institution."""
    initialize()
    allowed_types = ['note', 'reply', 'call', 'meeting', 'stage_change', 'follow_up']
    if activity_type not in allowed_types:
        activity_type = 'note'
    text = str(notes or '').strip()
    if not text:
        raise ValueError('Activity note text is required.')
    
    with connect() as db:
        row = db.execute('SELECT id FROM colleges WHERE id=? AND archived=0', (college_id,)).fetchone()
        if not row:
            raise ValueError('College not found.')
        cur = db.execute(
            'INSERT INTO outreach_notes(college_id, activity_type, notes, author) VALUES (?, ?, ?, ?)',
            (college_id, activity_type, text, author or 'Hiring Team')
        )
        note_id = cur.lastrowid
        created_at = db.execute('SELECT created_at FROM outreach_notes WHERE id=?', (note_id,)).fetchone()['created_at']
        return {'id': note_id, 'college_id': college_id, 'activity_type': activity_type, 'notes': text, 'author': author, 'created_at': created_at}

def get_college_activities(college_id):
    """Retrieve full unified CRM timeline: notes, logged calls/meetings, replies, and sent emails."""
    initialize()
    with connect() as db:
        notes_rows = db.execute(
            'SELECT id, activity_type, notes, author, created_at FROM outreach_notes WHERE college_id=? ORDER BY id DESC',
            (college_id,)
        ).fetchall()
        
        email_rows = db.execute(
            'SELECT id, subject, recipient_email, status, error_message, sent_at FROM outreach_log WHERE college_id=? ORDER BY id DESC',
            (college_id,)
        ).fetchall()

    timeline = []
    for n in notes_rows:
        timeline.append({
            'id': f"note-{n['id']}",
            'type': n['activity_type'],
            'notes': n['notes'],
            'author': n['author'] or 'Hiring Team',
            'timestamp': n['created_at'],
            'is_email': False
        })

    for e in email_rows:
        status_label = 'Accepted by SMTP provider' if e['status'] == 'sent' else f"Failed: {e['error_message']}"
        timeline.append({
            'id': f"outreach-{e['id']}",
            'type': 'email_sent' if e['status'] == 'sent' else 'email_failed',
            'notes': f"Subject: {e['subject']} · Recipient: {e['recipient_email']} · {status_label}",
            'author': 'Outreach System',
            'timestamp': e['sent_at'],
            'is_email': True,
            'status': e['status']
        })

    timeline.sort(key=lambda x: str(x.get('timestamp') or ''), reverse=True)
    return timeline

def update_pipeline_stage(college_id, stage, notes='', follow_up_date=None, assigned_to=None, author='Hiring Team'):
    """Advance or change the recruitment pipeline stage for a college."""
    if stage not in STAGE_CHOICES:
        raise ValueError(f"Invalid recruitment stage: {stage}. Choices: {list(STAGE_CHOICES.keys())}")
    
    with connect() as db:
        row = db.execute('SELECT * FROM colleges WHERE id=? AND archived=0', (college_id,)).fetchone()
        if not row:
            raise ValueError('College not found.')
        record = json.loads(row['payload'])
        old_stage = record.get('recruitment_stage', 'not_contacted')
        record['recruitment_stage'] = stage
        
        if follow_up_date is not None:
            f_str = str(follow_up_date or '').strip()
            if f_str:
                try: datetime.strptime(f_str, '%Y-%m-%d')
                except ValueError: raise ValueError('Follow-up date must be YYYY-MM-DD.')
            record['follow_up_date'] = f_str

        if assigned_to is not None:
            record['assigned_to'] = str(assigned_to or '').strip()

        # If moved to declined or partnership_active, stop pending queued outreach
        if stage in ['declined', 'partnership_active', 'replied']:
            try:
                db.execute('''
                    UPDATE campaign_queue
                    SET status='cancelled',
                        error_message=?
                    WHERE college_id=? AND status IN ('queued', 'sending')
                ''', (f"Stage changed to {STAGE_CHOICES[stage]} — automated follow-up cancelled", college_id))
            except sqlite3.OperationalError:
                pass

        saved = save_record(record, college_id, row['version'], f'pipeline stage: {stage}', db)

        # Log activity
        stage_label = STAGE_CHOICES[stage]
        act_text = f"Stage changed from {STAGE_CHOICES.get(old_stage, old_stage)} to {stage_label}."
        if notes:
            act_text += f" Notes: {notes}"
        db.execute(
            'INSERT INTO outreach_notes(college_id, activity_type, notes, author) VALUES (?, ?, ?, ?)',
            (college_id, 'stage_change', act_text, author or 'Hiring Team')
        )
        return saved

def record_reply(college_id, reply_text, author='Hiring Team', next_stage='replied'):
    """Record an official reply received from a placement officer or college authority."""
    text = str(reply_text or '').strip()
    if not text:
        raise ValueError('Reply summary or notes are required.')
    
    with connect() as db:
        row = db.execute('SELECT * FROM colleges WHERE id=? AND archived=0', (college_id,)).fetchone()
        if not row:
            raise ValueError('College not found.')
        record = json.loads(row['payload'])
        stage = next_stage if next_stage in STAGE_CHOICES else 'replied'
        record['recruitment_stage'] = stage
        now_str = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%Y-%m-%d %H:%M:%S')
        record['last_reply_at'] = now_str
        record['last_reply_notes'] = text

        # Automatic stopping of follow-ups when someone replies
        try:
            db.execute('''
                UPDATE campaign_queue
                SET status='cancelled',
                    error_message='College replied — automated follow-ups halted'
                WHERE college_id=? AND status IN ('queued', 'sending')
            ''', (college_id,))
        except sqlite3.OperationalError:
            pass

        saved = save_record(record, college_id, row['version'], 'recorded reply', db)

        db.execute(
            'INSERT INTO outreach_notes(college_id, activity_type, notes, author) VALUES (?, ?, ?, ?)',
            (college_id, 'reply', f"Reply Received: {text}", author or 'Hiring Team')
        )
        return saved

def set_follow_up(college_id, follow_up_date, notes='', assigned_to=None, author='Hiring Team'):
    """Schedule a follow-up reminder for a college."""
    f_str = str(follow_up_date or '').strip()
    if not f_str:
        raise ValueError('Follow-up date is required (YYYY-MM-DD).')
    try:
        datetime.strptime(f_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError('Follow-up date must be in YYYY-MM-DD format.')
    
    with connect() as db:
        row = db.execute('SELECT * FROM colleges WHERE id=? AND archived=0', (college_id,)).fetchone()
        if not row:
            raise ValueError('College not found.')
        record = json.loads(row['payload'])
        record['follow_up_date'] = f_str
        if assigned_to is not None:
            record['assigned_to'] = str(assigned_to or '').strip()

        saved = save_record(record, college_id, row['version'], 'set follow-up', db)

        act_text = f"Follow-up scheduled for {f_str}."
        if assigned_to:
            act_text += f" Assigned to: {assigned_to}."
        if notes:
            act_text += f" Notes: {notes}"
        db.execute(
            'INSERT INTO outreach_notes(college_id, activity_type, notes, author) VALUES (?, ?, ?, ?)',
            (college_id, 'follow_up', act_text, author or 'Hiring Team')
        )
        return saved

def get_pipeline_stats():
    """Aggregate statistics across recruitment stages and follow-up deadlines."""
    rows = get_colleges()
    today_str = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()

    stage_counts = {k: 0 for k in STAGE_CHOICES}
    for r in rows:
        st = r.get('recruitment_stage', 'not_contacted')
        if st in stage_counts:
            stage_counts[st] += 1
        else:
            stage_counts['not_contacted'] += 1

    overdue_list = []
    today_list = []
    upcoming_list = []

    for r in rows:
        f_date = r.get('follow_up_date')
        if f_date and r.get('recruitment_stage') not in ['partnership_active', 'declined']:
            item = {
                'id': r['id'],
                'College_Name': r['College_Name'],
                'City': r['City'],
                'TPO_Email': r['TPO_Email'],
                'Contact_Person': r.get('Contact_Person') or 'Placement Cell',
                'recruitment_stage': r.get('recruitment_stage', 'not_contacted'),
                'stage_label': STAGE_CHOICES.get(r.get('recruitment_stage', 'not_contacted'), 'Not Contacted'),
                'follow_up_date': f_date,
                'assigned_to': r.get('assigned_to') or 'Hiring Team',
                'last_outreach': r.get('last_outreach', 'Never'),
                'recently_contacted': r.get('recently_contacted', False)
            }
            if f_date < today_str:
                overdue_list.append(item)
            elif f_date == today_str:
                today_list.append(item)
            else:
                upcoming_list.append(item)

    overdue_list.sort(key=lambda x: x['follow_up_date'])
    today_list.sort(key=lambda x: x['College_Name'])
    upcoming_list.sort(key=lambda x: x['follow_up_date'])

    return {
        'stages': stage_counts,
        'stage_labels': STAGE_CHOICES,
        'follow_ups': {
            'overdue_count': len(overdue_list),
            'today_count': len(today_list),
            'upcoming_count': len(upcoming_list),
            'total_pending': len(overdue_list) + len(today_list) + len(upcoming_list),
            'urgent_items': overdue_list + today_list,
            'upcoming_items': upcoming_list[:15]
        }
    }

# ==================== PHASE 6: EXPORTS ====================

def export_campaign_csv(campaign_id):
    """Generate CSV string of delivery status and recipient records for a campaign."""
    initialize()
    with connect() as db:
        camp = db.execute('SELECT * FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
        if not camp:
            raise ValueError('Campaign not found.')
        rows = db.execute('''
            SELECT q.*, c.City, c.Location, c.Contact_Person
            FROM campaign_queue q
            LEFT JOIN (SELECT id, json_extract(payload, '$.City') as City, json_extract(payload, '$.Location') as Location, json_extract(payload, '$.Contact_Person') as Contact_Person FROM colleges) c
            ON q.college_id = c.id
            WHERE q.campaign_id=?
            ORDER BY q.id ASC
        ''', (campaign_id,)).fetchall()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        'Campaign_ID', 'Campaign_Name', 'Recipient_Email', 'College_Name', 'City', 'Location',
        'Contact_Role', 'Status', 'Attempts', 'Sent_At', 'Next_Attempt_At', 'Error_Details'
    ])
    writer.writeheader()
    for r in rows:
        status_name = 'Accepted by provider' if r['status'] == 'accepted' else r['status'].capitalize()
        writer.writerow({
            'Campaign_ID': camp['id'],
            'Campaign_Name': camp['name'],
            'Recipient_Email': r['recipient_email'],
            'College_Name': r['college_name'],
            'City': r['City'] or '',
            'Location': r['Location'] or '',
            'Contact_Role': r['contact_type'] or 'placement',
            'Status': status_name,
            'Attempts': r['retry_count'] or 0,
            'Sent_At': r['sent_at'] or '',
            'Next_Attempt_At': r['next_attempt_at'] or '',
            'Error_Details': r['error_message'] or ''
        })
    return buf.getvalue()

def export_pipeline_csv():
    """Generate CSV string of all institutions, stages, follow-up dates, and contact records."""
    rows = get_colleges()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        'College_Name', 'City', 'District', 'Campus', 'Type', 'TPO_Email', 'Contact_Person', 'Phone',
        'Verification_Status', 'Recruitment_Stage', 'Follow_Up_Date', 'Assigned_To', 'Last_Outreach',
        'Last_Reply_At', 'Last_Reply_Notes', 'Website', 'Notes'
    ])
    writer.writeheader()
    for r in rows:
        stage_name = STAGE_CHOICES.get(r.get('recruitment_stage', 'not_contacted'), 'Not Contacted')
        writer.writerow({
            'College_Name': r.get('College_Name', ''),
            'City': r.get('City', ''),
            'District': r.get('District', ''),
            'Campus': r.get('Campus', ''),
            'Type': r.get('Type', ''),
            'TPO_Email': r.get('TPO_Email', ''),
            'Contact_Person': r.get('Contact_Person', ''),
            'Phone': r.get('Phone', ''),
            'Verification_Status': r.get('verification_status', ''),
            'Recruitment_Stage': stage_name,
            'Follow_Up_Date': r.get('follow_up_date', ''),
            'Assigned_To': r.get('assigned_to', ''),
            'Last_Outreach': r.get('last_outreach', 'Never'),
            'Last_Reply_At': r.get('last_reply_at', ''),
            'Last_Reply_Notes': r.get('last_reply_notes', ''),
            'Website': r.get('Website', ''),
            'Notes': r.get('notes', '')
        })
    return buf.getvalue()

def export_outreach_csv():
    """Generate CSV string of full historical outreach log entries and internal activities."""
    initialize()
    with connect() as db:
        email_rows = db.execute('''
            SELECT o.id, o.college_id, o.college_name, json_extract(c.payload, '$.City') as City,
                   'email' as activity_type, o.subject as notes, 'Outreach System' as author,
                   o.sent_at as timestamp, o.status, o.error_message
            FROM outreach_log o
            LEFT JOIN colleges c ON o.college_id = c.id
        ''').fetchall()

        note_rows = db.execute('''
            SELECT n.id, n.college_id, json_extract(c.payload, '$.College_Name') as college_name,
                   json_extract(c.payload, '$.City') as City,
                   n.activity_type, n.notes, n.author,
                   n.created_at as timestamp, 'recorded' as status, '' as error_message
            FROM outreach_notes n
            LEFT JOIN colleges c ON n.college_id = c.id
        ''').fetchall()

    all_rows = list(email_rows) + list(note_rows)
    all_rows.sort(key=lambda r: str(r['timestamp'] or ''), reverse=True)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        'Activity_ID', 'College_ID', 'College_Name', 'City', 'Activity_Type', 'Notes',
        'Author', 'Status', 'Timestamp', 'Error_Details'
    ])
    writer.writeheader()
    for r in all_rows:
        status_name = 'Accepted by provider' if r['status'] == 'sent' else r['status'].capitalize()
        writer.writerow({
            'Activity_ID': r['id'],
            'College_ID': r['college_id'] or '',
            'College_Name': r['college_name'] or '',
            'City': r['City'] or '',
            'Activity_Type': r['activity_type'] or 'note',
            'Notes': r['notes'] or '',
            'Author': r['author'] or 'Hiring Team',
            'Status': status_name,
            'Timestamp': r['timestamp'] or '',
            'Error_Details': r['error_message'] or ''
        })
    return buf.getvalue()

# ==================== MULTI-CATEGORY SPREADSHEET (GOOGLE SHEETS & EXCEL) ====================

def generate_multi_category_workbook():
    """Build a multi-tab workbook where each category has its own dedicated worksheet."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default blank sheet

    categories = get_categories()
    if not categories:
        categories = ['Colleges']

    all_rows = get_colleges()

    # Sheet 1: Overview & Categories Summary
    ws_summary = wb.create_sheet(title='Overview & Categories')
    ws_summary.views.sheetView[0].showGridLines = True
    ws_summary.freeze_panes = 'A4'

    ws_summary['A1'] = 'Medantrik Outreach Platform — Multi-Category Directory'
    ws_summary['A1'].font = Font(name='Calibri', size=15, bold=True, color='0F172A')
    ws_summary['A2'] = f'Synchronized multi-tab spreadsheet. Automatically updated as new categories and contacts are added. Date: {today()}'
    ws_summary['A2'].font = Font(name='Calibri', size=10, italic=True, color='64748B')

    sum_headers = ['Category Name', 'Total Entities', 'Sendable Contacts', 'Verified Contacts', 'Last Outreach Recorded']
    ws_summary.append([])
    ws_summary.append(sum_headers)

    header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    for col_num in range(1, len(sum_headers) + 1):
        cell = ws_summary.cell(row=4, column=col_num)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border = thin_border

    for cat in categories:
        cat_records = [r for r in all_rows if (r.get('category') or 'Colleges').lower() == cat.lower()]
        tot = len(cat_records)
        sendable = sum(bool(r.get('sendable')) for r in cat_records)
        verified = sum(r.get('verification_status') == 'verified' for r in cat_records)
        outreaches = [r.get('last_outreach') for r in cat_records if r.get('last_outreach') and r.get('last_outreach') != 'Never']
        last_o = max(outreaches) if outreaches else 'Never'
        ws_summary.append([cat, tot, sendable, verified, last_o])

    for row in ws_summary.iter_rows(min_row=5, max_row=ws_summary.max_row, min_col=1, max_col=len(sum_headers)):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(vertical='center')

    for col in ws_summary.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or '')
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws_summary.column_dimensions[col_letter].width = max(16, min(max_len + 4, 45))

    # Data sheets: One dedicated worksheet per category
    data_headers = [
        'Entity_Name', 'Category', 'City', 'District', 'Location', 'Campus', 
        'Type', 'Website', 'Email', 'Contact_Person', 'Contact_Role', 'Phone',
        'Verification_Status', 'Recruitment_Stage', 'Follow_Up_Date', 'Assigned_To',
        'Last_Outreach', 'Notes'
    ]

    used_titles = {'overview & categories'}

    for cat in categories:
        clean_title = re.sub(r'[\\/*?:\[\]]', '', cat).strip()[:30] or 'Category'
        orig = clean_title
        idx = 1
        while clean_title.lower() in used_titles:
            clean_title = f"{orig[:27]}_{idx}"
            idx += 1
        used_titles.add(clean_title.lower())

        ws = wb.create_sheet(title=clean_title)
        ws.views.sheetView[0].showGridLines = True
        ws.freeze_panes = 'A2'

        ws.append(data_headers)
        ws.row_dimensions[1].height = 26

        for col_num in range(1, len(data_headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = thin_border

        cat_records = [r for r in all_rows if (r.get('category') or 'Colleges').lower() == cat.lower()]
        cat_records.sort(key=lambda r: str(r.get('College_Name') or '').lower())

        for r in cat_records:
            stage_label = STAGE_CHOICES.get(r.get('recruitment_stage', ''), r.get('recruitment_stage', ''))
            ws.append([
                r.get('College_Name', ''),
                r.get('category', cat),
                r.get('City', ''),
                r.get('District', ''),
                r.get('Location', ''),
                r.get('Campus', ''),
                r.get('Type', ''),
                r.get('Website', ''),
                r.get('TPO_Email', ''),
                r.get('Contact_Person', ''),
                r.get('contact_type', ''),
                r.get('Phone', ''),
                r.get('verification_status', ''),
                stage_label,
                r.get('follow_up_date', ''),
                r.get('assigned_to', ''),
                r.get('last_outreach', ''),
                r.get('notes', '')
            ])

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=len(data_headers)):
            for cell in row:
                cell.border = thin_border
                cell.alignment = Alignment(vertical='center')

        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or '')
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = max(12, min(max_len + 3, 40))

    return wb

def export_multi_category_workbook_bytes():
    """Return .xlsx bytes of the complete multi-category workbook."""
    wb = generate_multi_category_workbook()
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

_syncing_spreadsheet = False

def sync_spreadsheet_file():
    """Persist the multi-tab workbook to disk for Google Sheets / Excel users."""
    global _syncing_spreadsheet
    if _syncing_spreadsheet:
        return False
    _syncing_spreadsheet = True
    try:
        content = export_multi_category_workbook_bytes()
        # Always maintain backup copy in data directory
        (BASE_DIR / 'data' / 'directory_master.xlsx').write_bytes(content)

        # Attempt writing root convenience workbooks if not locked by Excel
        for filename in ['colleges_delhi_ncr_multi_category.xlsx', 'colleges_delhi_ncr_google_sheets.xlsx']:
            try:
                (BASE_DIR / filename).write_bytes(content)
            except OSError:
                pass
        return True
    except Exception:
        return False
    finally:
        _syncing_spreadsheet = False

def push_to_google_sheet_webhook(event_type, payload):
    """If google_sheet_webhook_url or google_sheets_sync_url is configured, dispatch live webhook."""
    try:
        config = load_settings()
        webhook_url = config.get('google_sheet_webhook_url') or config.get('google_sheets_sync_url')
        if not webhook_url:
            return
        import urllib.request
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps({'event': event_type, 'data': payload, 'timestamp': today()}).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"Notice: Google Sheets webhook notification failed: {e}")


