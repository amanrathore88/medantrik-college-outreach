"""Template library, rich-text management, versioning, and personalization engine."""
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from settings import BASE_DIR, load_settings
from directory import connect, initialize as init_directory

def today_iso():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat()

def initialize_templates():
    init_directory()
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS email_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            html_body TEXT NOT NULL,
            text_body TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS template_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            html_body TEXT NOT NULL,
            text_body TEXT NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(template_id) REFERENCES email_templates(id)
        );
        ''')
        # Seed starter templates if table is empty
        row = db.execute('SELECT COUNT(*) as c FROM email_templates').fetchone()
        if row['c'] == 0:
            seed_starter_templates(db)

def seed_starter_templates(db):
    # 1. MedTech Placement Outreach (Default)
    html1_path = BASE_DIR / 'common_placement_outreach.html'
    text1_path = BASE_DIR / 'common_placement_outreach.txt'
    html1 = html1_path.read_text(encoding='utf-8') if html1_path.exists() else '<p>Hello {{College_Name}}</p>'
    text1 = text1_path.read_text(encoding='utf-8') if text1_path.exists() else 'Hello {{College_Name}}'
    
    # Inject personalization placeholder if not already in content
    if '{{College_Name}}' not in html1:
        html1 = html1.replace('Dear Training & Placement Officer / Placement Committee,', 'Dear {{Contact_Person}},<br><br><strong>{{College_Name}}</strong>')
    if '{{College_Name}}' not in text1:
        text1 = text1.replace('Dear Training & Placement Officer / Placement Committee,', 'Dear {{Contact_Person}},\n\n{{College_Name}}')

    cur1 = db.execute('''
        INSERT INTO email_templates (name, subject, html_body, text_body, is_default, version)
        VALUES (?, ?, ?, ?, 1, 1)
    ''', (
        'MedTech Hardware & Biomedical Engineering Placement Partnership (Default)',
        'Campus Placement Partnership & Industry Project Mentorship — {{College_Name}}',
        html1,
        text1
    ))
    t1_id = cur1.lastrowid
    db.execute('''
        INSERT INTO template_history (template_id, version, name, subject, html_body, text_body, note)
        VALUES (?, 1, ?, ?, ?, ?, 'Imported from common_placement_outreach.html starter design')
    ''', (t1_id, 'MedTech Hardware & Biomedical Engineering Placement Partnership (Default)', 'Campus Placement Partnership & Industry Project Mentorship — {{College_Name}}', html1, text1))

    # 2. Engineering Internship & Campus Hiring
    html2_path = BASE_DIR / 'college_outreach_email.html'
    html2 = html2_path.read_text(encoding='utf-8') if html2_path.exists() else '<p>Internship Opportunity</p>'
    text2 = "Subject: Internship & Campus Placement Opportunity - Medantrik MedTech\n\nDear {{Contact_Person}},\n\nGreetings from Medantrik MedTech Pvt Ltd (IIT Kanpur Incubated)!\n\nWe would like to invite students from {{College_Name}} ({{City}}) for internships and campus placement in our hardware and device R&D facility in Noida Sector 63A.\n\nPlease reply with placement coordinator details or let us know a suitable time for a brief Google Meet call.\n\nWarm regards,\nMedantrik MedTech Team"
    
    cur2 = db.execute('''
        INSERT INTO email_templates (name, subject, html_body, text_body, is_default, version)
        VALUES (?, ?, ?, ?, 0, 1)
    ''', (
        'Campus Recruitment & Paid Engineering Internship Opportunity',
        'Internship & Campus Placement Opportunity (Medantrik MedTech) — {{College_Name}}',
        html2,
        text2
    ))
    t2_id = cur2.lastrowid
    db.execute('''
        INSERT INTO template_history (template_id, version, name, subject, html_body, text_body, note)
        VALUES (?, 1, ?, ?, ?, ?, 'Imported from college_outreach_email.html starter design')
    ''', (t2_id, 'Campus Recruitment & Paid Engineering Internship Opportunity', 'Internship & Campus Placement Opportunity (Medantrik MedTech) — {{College_Name}}', html2, text2))

    # 3. Concise Executive Collaboration Brief
    html3 = '''<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px;">
<h2 style="color: #07172c; margin-top: 0;">Industry Mentorship & Campus Hiring Connect</h2>
<p>Dear {{Contact_Person}},</p>
<p>Greetings from <strong>Medantrik MedTech Pvt Ltd</strong> (Incubated at <strong>IIT Kanpur</strong>, manufacturing facility at Sector 63A, Noida).</p>
<p>We are reaching out to explore a structured placement and industry project partnership with <strong>{{College_Name}}</strong> for upcoming batches across engineering, biomedical, electronics, and technical programs.</p>
<p>Our core domains include indigenous respiratory medical devices, clean-air hardware, and clinical diagnostic instruments.</p>
<p>Could we schedule a brief 15-minute introductory video call with your placement team this week?</p>
<br>
<p>Warm regards,<br>
<strong>Hiring & University Relations Team</strong><br>
Medantrik MedTech Pvt Ltd<br>
<a href="https://medantrik.com">https://medantrik.com</a> · Noida Sector 63A</p>
</div>'''
    text3 = "Dear {{Contact_Person}},\n\nGreetings from Medantrik MedTech Pvt Ltd (IIT Kanpur Incubated)!\n\nWe are reaching out to explore an industry partnership and campus placement connect with {{College_Name}} in {{City}}.\n\nWe would welcome a quick 15-minute call with your Placement Cell to discuss batch schedules and role profiles.\n\nWarm regards,\nHiring & University Relations Team\nMedantrik MedTech Pvt Ltd\nhttps://medantrik.com"

    cur3 = db.execute('''
        INSERT INTO email_templates (name, subject, html_body, text_body, is_default, version)
        VALUES (?, ?, ?, ?, 0, 1)
    ''', (
        'Executive Industry Collaboration & Placement Invitation',
        'Industry Partnership & Campus Placement Connect — {{College_Name}}',
        html3,
        text3
    ))
    t3_id = cur3.lastrowid
    db.execute('''
        INSERT INTO template_history (template_id, version, name, subject, html_body, text_body, note)
        VALUES (?, 1, ?, ?, ?, ?, 'Concise executive outreach starter design')
    ''', (t3_id, 'Executive Industry Collaboration & Placement Invitation', 'Industry Partnership & Campus Placement Connect — {{College_Name}}', html3, text3))

# ==================== PERSONALIZATION ENGINE ====================
def render_personalized(subject, html_body, text_body, college=None):
    c = college or {}
    college_name = str(c.get('College_Name') or c.get('college_name') or '').strip() or 'Your Prestigious Institution'
    city = str(c.get('City') or c.get('city') or c.get('Location') or '').strip() or 'Delhi-NCR'
    contact_person = str(c.get('Contact_Person') or c.get('contact_person') or '').strip() or 'Training & Placement Officer'
    campus = str(c.get('Campus') or c.get('campus') or '').strip()
    website = str(c.get('Website') or c.get('website') or '').strip()
    contact_type = str(c.get('contact_type') or 'Placement Cell').capitalize()

    tokens = {
        '{{College_Name}}': college_name,
        '{{college_name}}': college_name,
        '{{COLLEGE_NAME}}': college_name,
        '{{City}}': city,
        '{{city}}': city,
        '{{Contact_Person}}': contact_person,
        '{{contact_person}}': contact_person,
        '{{Campus}}': campus,
        '{{campus}}': campus,
        '{{Website}}': website,
        '{{website}}': website,
        '{{contact_type}}': contact_type
    }

    def replace_tokens(text):
        if not text: return ''
        res = text
        for token, val in tokens.items():
            res = res.replace(token, val)
        return res

    return {
        'subject': replace_tokens(subject),
        'html': replace_tokens(html_body),
        'text': replace_tokens(text_body)
    }

# ==================== TEMPLATE CRUD ====================
def list_templates(include_archived=False):
    initialize_templates()
    with connect() as db:
        query = 'SELECT id, name, subject, is_default, version, archived, updated_at, created_at FROM email_templates'
        if not include_archived:
            query += ' WHERE archived=0'
        query += ' ORDER BY is_default DESC, id ASC'
        return [dict(r) for r in db.execute(query).fetchall()]

def get_template(template_id=None):
    initialize_templates()
    with connect() as db:
        if template_id:
            row = db.execute('SELECT * FROM email_templates WHERE id=?', (template_id,)).fetchone()
        else:
            row = db.execute('SELECT * FROM email_templates WHERE archived=0 ORDER BY is_default DESC, id ASC LIMIT 1').fetchone()
        if not row:
            raise ValueError('Template not found.')
        return dict(row)

def save_template(data, template_id=None):
    initialize_templates()
    name = str(data.get('name') or '').strip()
    subject = str(data.get('subject') or '').strip()
    html_body = str(data.get('html_body') or '').strip()
    text_body = str(data.get('text_body') or '').strip()
    is_default = 1 if data.get('is_default') in [True, 1, '1'] else 0
    note = str(data.get('note') or 'Saved edit').strip()

    if not name:
        raise ValueError('Template name is required.')
    if not subject:
        raise ValueError('Subject line is required.')
    if not html_body:
        raise ValueError('Formatted HTML body is required.')
    if not text_body:
        # Generate sensible plain text alternative if missing
        clean_text = re.sub(r'<[^>]+>', ' ', html_body)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        text_body = clean_text or subject

    target_id = None
    with connect() as db:
        if is_default:
            db.execute('UPDATE email_templates SET is_default=0')

        if template_id:
            old = db.execute('SELECT * FROM email_templates WHERE id=?', (template_id,)).fetchone()
            if not old:
                raise ValueError('Template no longer exists.')
            new_version = old['version'] + 1
            db.execute('''
                UPDATE email_templates
                SET name=?, subject=?, html_body=?, text_body=?, is_default=?, version=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            ''', (name, subject, html_body, text_body, is_default, new_version, template_id))
            db.execute('''
                INSERT INTO template_history (template_id, version, name, subject, html_body, text_body, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (template_id, new_version, name, subject, html_body, text_body, note))
            target_id = template_id
        else:
            cur = db.execute('''
                INSERT INTO email_templates (name, subject, html_body, text_body, is_default, version)
                VALUES (?, ?, ?, ?, ?, 1)
            ''', (name, subject, html_body, text_body, is_default))
            target_id = cur.lastrowid
            db.execute('''
                INSERT INTO template_history (template_id, version, name, subject, html_body, text_body, note)
                VALUES (?, 1, ?, ?, ?, ?, 'Initial template creation')
            ''', (target_id, name, subject, html_body, text_body))
    return get_template(target_id)

def duplicate_template(template_id):
    tpl = get_template(template_id)
    new_data = {
        'name': f"{tpl['name']} (Copy)",
        'subject': tpl['subject'],
        'html_body': tpl['html_body'],
        'text_body': tpl['text_body'],
        'is_default': 0,
        'note': f"Duplicated from #{tpl['id']} ({tpl['name']})"
    }
    return save_template(new_data)

def archive_template(template_id):
    initialize_templates()
    with connect() as db:
        tpl = db.execute('SELECT * FROM email_templates WHERE id=?', (template_id,)).fetchone()
        if not tpl:
            raise ValueError('Template not found.')
        if tpl['is_default']:
            raise ValueError('Cannot archive the default template. Assign a new default first.')
        db.execute('UPDATE email_templates SET archived=1 WHERE id=?', (template_id,))
        return {'status': 'ok', 'id': template_id}

def get_template_history(template_id):
    initialize_templates()
    with connect() as db:
        rows = db.execute('SELECT * FROM template_history WHERE template_id=? ORDER BY version DESC', (template_id,)).fetchall()
        return [dict(r) for r in rows]

def restore_template_version(template_id, history_id):
    initialize_templates()
    with connect() as db:
        hist = db.execute('SELECT * FROM template_history WHERE id=? AND template_id=?', (history_id, template_id)).fetchone()
        if not hist:
            raise ValueError('Template version history record not found.')
        data = {
            'name': hist['name'],
            'subject': hist['subject'],
            'html_body': hist['html_body'],
            'text_body': hist['text_body'],
            'note': f"Restored from version {hist['version']}"
        }
        return save_template(data, template_id)

def create_template_snapshot(template_id):
    tpl = get_template(template_id)
    snapshot = {
        'template_id': tpl['id'],
        'version': tpl['version'],
        'name': tpl['name'],
        'subject': tpl['subject'],
        'html_body': tpl['html_body'],
        'text_body': tpl['text_body'],
        'snapshotted_at': today_iso()
    }
    return json.dumps(snapshot)

# Backward-compatible loader for existing code (dashboard.py / send_college_campaign.py)
def load_templates():
    try:
        tpl = get_template()
        return (tpl['html_body'], tpl['text_body'])
    except Exception:
        config = load_settings()
        result = []
        for key, fallback in [('html_template_file', 'common_placement_outreach.html'), ('text_template_file', 'common_placement_outreach.txt')]:
            path = (BASE_DIR / config.get(key, fallback)).resolve()
            if not path.is_relative_to(BASE_DIR):
                raise ValueError('Template must be inside the application folder.')
            result.append(path.read_text(encoding='utf-8'))
        return tuple(result)
