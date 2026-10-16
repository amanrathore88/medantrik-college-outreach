"""Persistent, staggered campaign queue engine and background worker for Phase 5.

Supports durable queueing, configurable staggering, hourly and daily rate caps,
India Standard Time (IST) working hours, pause/resume/cancellation,
safe restart recovery, exponential retries, and template snapshot isolation.
"""
import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from settings import BASE_DIR
from directory import connect, initialize as init_directory, get_colleges, log_outreach
import templates
from mailer import send_mail, validate_message

logger = logging.getLogger('campaign_queue')

# In-memory session credentials (passwords are NEVER stored on disk)
_SESSION_CREDENTIALS = {}
_WORKER_THREAD = None
_STOP_EVENT = threading.Event()
_LOCK = threading.RLock()

def get_ist_timezone():
    return timezone(timedelta(hours=5, minutes=30))

def now_ist():
    return datetime.now(get_ist_timezone())

def now_ist_iso():
    return now_ist().isoformat()

def initialize_queue():
    """Ensure database schema for campaigns and queue exists."""
    init_directory()
    templates.initialize_templates()
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sender_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            template_id INTEGER,
            template_snapshot TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            scheduled_at TEXT,
            interval_seconds INTEGER NOT NULL DEFAULT 2,
            hourly_cap INTEGER NOT NULL DEFAULT 50,
            daily_cap INTEGER NOT NULL DEFAULT 200,
            sending_hours_start TEXT DEFAULT '09:00',
            sending_hours_end TEXT DEFAULT '18:00',
            working_days_only INTEGER NOT NULL DEFAULT 1,
            total_recipients INTEGER NOT NULL DEFAULT 0,
            successful_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS campaign_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            college_id INTEGER,
            college_name TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            contact_type TEXT DEFAULT 'placement',
            subject TEXT NOT NULL,
            html_body TEXT NOT NULL,
            text_body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            next_attempt_at TEXT DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT,
            error_message TEXT,
            failure_type TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
            UNIQUE(campaign_id, recipient_email)
        );

        CREATE INDEX IF NOT EXISTS idx_cq_status ON campaign_queue(status, next_attempt_at);
        CREATE INDEX IF NOT EXISTS idx_cq_campaign ON campaign_queue(campaign_id);
        ''')

        # Add missing columns to campaigns table if migrating from Phase 2/4
        cols = [
            ('scheduled_at', 'TEXT'),
            ('interval_seconds', 'INTEGER DEFAULT 2'),
            ('hourly_cap', 'INTEGER DEFAULT 50'),
            ('daily_cap', 'INTEGER DEFAULT 200'),
            ('sending_hours_start', "TEXT DEFAULT '09:00'"),
            ('sending_hours_end', "TEXT DEFAULT '18:00'"),
            ('working_days_only', 'INTEGER DEFAULT 1'),
            ('notes', 'TEXT'),
            ('updated_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
        ]
        for col_name, col_def in cols:
            try:
                db.execute(f'ALTER TABLE campaigns ADD COLUMN {col_name} {col_def}')
            except sqlite3.OperationalError:
                pass

def set_sender_password(sender_email, password):
    if sender_email and password:
        with _LOCK:
            _SESSION_CREDENTIALS[sender_email.lower().strip()] = password.strip()

def get_sender_password(sender_email):
    with _LOCK:
        return _SESSION_CREDENTIALS.get(sender_email.lower().strip())

def clear_sender_password(sender_email):
    with _LOCK:
        _SESSION_CREDENTIALS.pop(sender_email.lower().strip(), None)

# ==================== CAMPAIGN CREATION & ENQUEUEING ====================
def create_staggered_campaign(config, recipient_college_ids, sender_password=None):
    """
    Creates a campaign and enqueues personalized messages for all selected colleges.
    Deduplicates recipients and freezes the template snapshot.
    """
    initialize_queue()
    name = str(config.get('name') or '').strip()
    sender_email = str(config.get('sender_email') or '').strip().lower()
    template_id = config.get('template_id')
    interval_seconds = max(1, int(config.get('interval_seconds') or 2))
    hourly_cap = max(1, int(config.get('hourly_cap') or 50))
    daily_cap = max(1, int(config.get('daily_cap') or 200))
    sending_hours_start = str(config.get('sending_hours_start') or '09:00').strip()
    sending_hours_end = str(config.get('sending_hours_end') or '18:00').strip()
    working_days_only = 1 if config.get('working_days_only', True) in [True, 1, '1', 'true'] else 0
    scheduled_at = config.get('scheduled_at')

    if not name:
        raise ValueError('Campaign name is required.')
    if not sender_email:
        raise ValueError('Sender email is required.')
    if '@' not in sender_email:
        raise ValueError('Invalid sender email format.')

    # Save password into memory session if provided
    if sender_password:
        set_sender_password(sender_email, sender_password)

    # Load and freeze template snapshot
    tpl = None
    if template_id:
        try:
            tpl = templates.get_template(int(template_id))
        except Exception:
            pass
    if not tpl:
        tpl = templates.get_template()  # default
        template_id = tpl['id']

    template_snapshot = templates.create_template_snapshot(template_id)
    subject_line = str(config.get('subject') or tpl['subject']).strip()

    # Determine initial status
    initial_status = 'scheduled' if (scheduled_at and str(scheduled_at) > now_ist_iso()) else 'queued'

    # Filter and validate recipient colleges from directory
    all_directory = get_colleges()
    college_map = {c['id']: c for c in all_directory}
    
    selected_colleges = []
    seen_emails = set()
    for cid in recipient_college_ids:
        c = college_map.get(int(cid))
        if not c or not c.get('sendable') or c.get('do_not_contact'):
            continue
        email = (c.get('TPO_Email') or '').lower().strip()
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)
        selected_colleges.append(c)

    if not selected_colleges:
        raise ValueError('Select at least one sendable, verified college from the directory.')

    with connect() as db:
        cur = db.execute('''
            INSERT INTO campaigns (
                name, sender_email, subject, template_id, template_snapshot,
                status, scheduled_at, interval_seconds, hourly_cap, daily_cap,
                sending_hours_start, sending_hours_end, working_days_only,
                total_recipients, successful_count, failed_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        ''', (
            name, sender_email, subject_line, template_id, template_snapshot,
            initial_status, scheduled_at, interval_seconds, hourly_cap, daily_cap,
            sending_hours_start, sending_hours_end, working_days_only,
            len(selected_colleges)
        ))
        campaign_id = cur.lastrowid

        # Personalize and enqueue each message
        for c in selected_colleges:
            rendered = templates.render_personalized(
                subject_line,
                tpl['html_body'],
                tpl['text_body'],
                c
            )
            db.execute('''
                INSERT OR IGNORE INTO campaign_queue (
                    campaign_id, college_id, college_name, recipient_email,
                    contact_type, subject, html_body, text_body, status, next_attempt_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', CURRENT_TIMESTAMP)
            ''', (
                campaign_id, c['id'], c.get('College_Name', ''), c['TPO_Email'].lower().strip(),
                c.get('contact_type', 'placement'), rendered['subject'], rendered['html'], rendered['text']
            ))

    return get_campaign_detail(campaign_id)

# ==================== CAMPAIGN CONTROLS ====================
def pause_campaign(campaign_id):
    initialize_queue()
    with connect() as db:
        c = db.execute('SELECT * FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
        if not c:
            raise ValueError('Campaign not found.')
        if c['status'] in ['completed', 'cancelled']:
            raise ValueError(f"Cannot pause a {c['status']} campaign.")
        db.execute("UPDATE campaigns SET status='paused', updated_at=CURRENT_TIMESTAMP WHERE id=?", (campaign_id,))
    return get_campaign_detail(campaign_id)

def resume_campaign(campaign_id, sender_password=None):
    initialize_queue()
    with connect() as db:
        c = db.execute('SELECT * FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
        if not c:
            raise ValueError('Campaign not found.')
        if c['status'] in ['completed', 'cancelled']:
            raise ValueError(f"Cannot resume a {c['status']} campaign.")
        
        if sender_password:
            set_sender_password(c['sender_email'], sender_password)
        
        # Determine whether queued or scheduled
        sched = c['scheduled_at']
        new_status = 'scheduled' if (sched and str(sched) > now_ist_iso()) else 'queued'
        db.execute("UPDATE campaigns SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, campaign_id))
    return get_campaign_detail(campaign_id)

def cancel_campaign(campaign_id):
    initialize_queue()
    with connect() as db:
        c = db.execute('SELECT * FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
        if not c:
            raise ValueError('Campaign not found.')
        db.execute("UPDATE campaigns SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=?", (campaign_id,))
        # Cancel all pending / queued / sending messages
        db.execute("UPDATE campaign_queue SET status='cancelled', error_message='Cancelled by user' WHERE campaign_id=? AND status IN ('queued', 'sending')", (campaign_id,))
    return get_campaign_detail(campaign_id)

def retry_failed_messages(campaign_id):
    initialize_queue()
    with connect() as db:
        c = db.execute('SELECT * FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
        if not c:
            raise ValueError('Campaign not found.')
        # Reset failed and needs_review messages to queued
        db.execute('''
            UPDATE campaign_queue
            SET status='queued', retry_count=0, next_attempt_at=CURRENT_TIMESTAMP, error_message=NULL, failure_type=NULL
            WHERE campaign_id=? AND status IN ('failed', 'needs_review')
        ''', (campaign_id,))
        # Refresh campaign counters
        failed_left = db.execute("SELECT COUNT(*) as cnt FROM campaign_queue WHERE campaign_id=? AND status='failed'", (campaign_id,)).fetchone()['cnt']
        db.execute("UPDATE campaigns SET status='queued', failed_count=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (failed_left, campaign_id))
    return get_campaign_detail(campaign_id)

# ==================== QUERYING & STATUS ====================
def get_campaign_detail(campaign_id):
    initialize_queue()
    with connect() as db:
        row = db.execute('SELECT * FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
        if not row:
            raise ValueError('Campaign not found.')
        camp = dict(row)
        
        # Queue breakdown
        queue_rows = db.execute('SELECT * FROM campaign_queue WHERE campaign_id=? ORDER BY id ASC', (campaign_id,)).fetchall()
        messages = [dict(r) for r in queue_rows]
        
        counts = {
            'queued': sum(1 for m in messages if m['status'] == 'queued'),
            'sending': sum(1 for m in messages if m['status'] == 'sending'),
            'accepted': sum(1 for m in messages if m['status'] == 'accepted'),
            'failed': sum(1 for m in messages if m['status'] == 'failed'),
            'cancelled': sum(1 for m in messages if m['status'] == 'cancelled'),
            'needs_review': sum(1 for m in messages if m['status'] == 'needs_review'),
            'total': len(messages)
        }
        
        # Calculate progress
        done = counts['accepted'] + counts['failed'] + counts['cancelled']
        camp['progress_pct'] = round((done / counts['total']) * 100) if counts['total'] > 0 else 0
        camp['counts'] = counts
        camp['messages'] = messages
        
        # Estimated completion
        remaining = counts['queued'] + counts['sending']
        interval = camp.get('interval_seconds', 2)
        camp['estimated_seconds_remaining'] = remaining * interval
        
        return camp

def list_campaigns(limit=50):
    initialize_queue()
    with connect() as db:
        rows = db.execute('SELECT * FROM campaigns ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        result = []
        for r in rows:
            c = dict(r)
            # Fetch summary counts
            stats = db.execute('''
                SELECT
                    SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) as queued_cnt,
                    SUM(CASE WHEN status='sending' THEN 1 ELSE 0 END) as sending_cnt,
                    SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) as accepted_cnt,
                    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed_cnt,
                    SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) as cancelled_cnt,
                    SUM(CASE WHEN status='needs_review' THEN 1 ELSE 0 END) as review_cnt
                FROM campaign_queue WHERE campaign_id=?
            ''', (c['id'],)).fetchone()
            
            c['queued_count'] = stats['queued_cnt'] or 0
            c['accepted_count'] = stats['accepted_cnt'] or 0
            c['failed_count'] = stats['failed_cnt'] or 0
            c['needs_review_count'] = stats['review_cnt'] or 0
            done = (stats['accepted_cnt'] or 0) + (stats['failed_cnt'] or 0) + (stats['cancelled_cnt'] or 0)
            total = c['total_recipients'] or 1
            c['progress_pct'] = min(100, round((done / total) * 100))
            result.append(c)
        return result

def get_queue_overview():
    initialize_queue()
    with connect() as db:
        now_str = now_ist_iso()
        queue_stats = db.execute('''
            SELECT
                SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) as queued,
                SUM(CASE WHEN status='sending' THEN 1 ELSE 0 END) as sending,
                SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) as accepted,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status='needs_review' THEN 1 ELSE 0 END) as needs_review
            FROM campaign_queue
        ''').fetchone()

        active_campaigns = db.execute('''
            SELECT COUNT(*) as cnt FROM campaigns WHERE status IN ('queued', 'sending')
        ''').fetchone()['cnt']

        # Count sends in the last hour & today (IST)
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        today_start = datetime.now(timezone.utc).strftime('%Y-%m-%d 00:00:00')
        
        last_hour_sends = db.execute('''
            SELECT COUNT(*) as cnt FROM campaign_queue WHERE status='accepted' AND sent_at >= ?
        ''', (one_hour_ago,)).fetchone()['cnt']
        
        today_sends = db.execute('''
            SELECT COUNT(*) as cnt FROM campaign_queue WHERE status='accepted' AND sent_at >= ?
        ''', (today_start,)).fetchone()['cnt']

        return {
            'worker_running': is_worker_running(),
            'active_campaigns': active_campaigns,
            'queued_messages': queue_stats['queued'] or 0,
            'sending_messages': queue_stats['sending'] or 0,
            'accepted_messages': queue_stats['accepted'] or 0,
            'failed_messages': queue_stats['failed'] or 0,
            'needs_review_messages': queue_stats['needs_review'] or 0,
            'sent_last_hour': last_hour_sends,
            'sent_today': today_sends,
            'current_time_ist': now_str
        }

# ==================== DISPATCH CONDITIONS & LIMIT CHECKS ====================
def can_dispatch_campaign_now(campaign, dt_ist=None):
    """
    Checks if a campaign is permitted to dispatch right now according to its schedule,
    working days rule, and sending hours in India Standard Time (IST).
    """
    current_time = dt_ist or now_ist()
    status = campaign.get('status')

    if status not in ['queued', 'sending', 'scheduled']:
        return False, f"Campaign status is '{status}'."

    # Check scheduled_at
    sched = campaign.get('scheduled_at')
    if sched:
        try:
            # Normalize ISO string
            sched_dt = datetime.fromisoformat(str(sched))
            if sched_dt.tzinfo is None:
                sched_dt = sched_dt.replace(tzinfo=get_ist_timezone())
            if current_time < sched_dt:
                return False, f"Scheduled for {sched}."
        except Exception:
            pass

    # Check working days (Mon-Fri)
    if campaign.get('working_days_only'):
        # weekday(): Monday is 0, Sunday is 6
        if current_time.weekday() >= 5:
            return False, "Outside working days (Monday–Friday IST)."

    # Check sending hours (IST)
    start_str = campaign.get('sending_hours_start') or '09:00'
    end_str = campaign.get('sending_hours_end') or '18:00'
    curr_hm = current_time.strftime('%H:%M')
    if curr_hm < start_str or curr_hm > end_str:
        return False, f"Outside business sending window ({start_str} to {end_str} IST)."

    return True, "Ready to send"

def check_sender_rate_caps(sender_email, hourly_cap, daily_cap, db):
    """
    Checks if the sender has exceeded their hourly or daily cap.
    """
    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    today_start = datetime.now(timezone.utc).strftime('%Y-%m-%d 00:00:00')

    hourly_sent = db.execute('''
        SELECT COUNT(*) as cnt FROM campaign_queue
        WHERE status='accepted'
          AND campaign_id IN (SELECT id FROM campaigns WHERE LOWER(sender_email)=?)
          AND sent_at >= ?
    ''', (sender_email.lower(), one_hour_ago)).fetchone()['cnt']

    if hourly_sent >= hourly_cap:
        return False, f"Hourly cap of {hourly_cap} reached ({hourly_sent} sent in last hour)."

    daily_sent = db.execute('''
        SELECT COUNT(*) as cnt FROM campaign_queue
        WHERE status='accepted'
          AND campaign_id IN (SELECT id FROM campaigns WHERE LOWER(sender_email)=?)
          AND sent_at >= ?
    ''', (sender_email.lower(), today_start)).fetchone()['cnt']

    if daily_sent >= daily_cap:
        return False, f"Daily cap of {daily_cap} reached ({daily_sent} sent today)."

    return True, "Within rate limits"

# ==================== RECOVERY ON APPLICATION RESTART ====================
def recover_stale_queue_on_startup():
    """
    Resets orphaned 'sending' messages from a previous crash/restart to 'needs_review' or 'queued'.
    Ensures that interrupted queues resume safely without duplicates.
    """
    initialize_queue()
    with connect() as db:
        # If the app restarted while a message was marked 'sending', mark as 'needs_review'
        # so staff can check Sent mail before re-dispatching
        stale_sending = db.execute("SELECT id FROM campaign_queue WHERE status='sending'").fetchall()
        for r in stale_sending:
            db.execute('''
                UPDATE campaign_queue
                SET status='needs_review', failure_type='uncertain',
                    error_message='Interrupted by application restart during transmission. Check Sent mail before retrying.'
                WHERE id=?
            ''', (r['id'],))
        
        # Reset campaign status to 'paused' if in 'sending' state so user can supply password
        db.execute('''
            UPDATE campaigns
            SET status='paused',
                notes='Application restarted. Please re-enter Google App Password and resume campaign.'
            WHERE status='sending'
        ''')

# ==================== WORKER LOOP & MESSAGE DISPATCH ====================
def dispatch_single_queue_message(msg_id, password_override=None):
    """
    Claims and sends a single queue message. Handles retries, permanent rejection,
    and authentication pause.
    Returns (status, error_message).
    """
    initialize_queue()
    with connect() as db:
        msg = db.execute('SELECT * FROM campaign_queue WHERE id=?', (msg_id,)).fetchone()
        if not msg:
            return 'not_found', 'Message does not exist'
        
        # Atomic claim
        db.execute("UPDATE campaign_queue SET status='sending' WHERE id=? AND status='queued'", (msg_id,))
        if db.total_changes == 0:
            return 'skipped', 'Message already claimed or not queued'

        camp = db.execute('SELECT * FROM campaigns WHERE id=?', (msg['campaign_id'],)).fetchone()
        sender_email = camp['sender_email']
        password = password_override or get_sender_password(sender_email)

        if not password:
            # Pause campaign - authentication required
            db.execute("UPDATE campaign_queue SET status='queued' WHERE id=?", (msg_id,))
            db.execute("UPDATE campaigns SET status='paused', notes='Sender password missing from session. Resume with App Password.' WHERE id=?", (camp['id'],))
            return 'paused', 'Authentication required'

        recipient_email = msg['recipient_email']
        college_name = msg['college_name']
        college_id = msg['college_id']
        subject = msg['subject']
        html_body = msg['html_body']
        text_body = msg['text_body']

        # Check directory do_not_contact and recruitment stage status
        dir_match = db.execute('SELECT payload FROM colleges WHERE id=?', (college_id,)).fetchone()
        if dir_match:
            try:
                payload = json.loads(dir_match['payload'])
                if payload.get('do_not_contact'):
                    db.execute("UPDATE campaign_queue SET status='cancelled', error_message='Marked Do-Not-Contact in directory' WHERE id=?", (msg_id,))
                    return 'cancelled', 'Recipient marked do not contact'
                stage = payload.get('recruitment_stage', 'not_contacted')
                if stage in ['replied', 'partnership_active', 'declined']:
                    db.execute("UPDATE campaign_queue SET status='cancelled', error_message=? WHERE id=?", (f"College is in stage '{stage}' — follow-ups halted", msg_id))
                    return 'cancelled', f'College is in stage {stage}'
            except Exception:
                pass

        # Attempt sending
        try:
            send_mail(sender_email, password, recipient_email, college_name, subject, html_body, text_body)
            # Mark accepted by provider
            sent_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            db.execute('''
                UPDATE campaign_queue
                SET status='accepted', sent_at=?, error_message=NULL, failure_type=NULL
                WHERE id=?
            ''', (sent_time, msg_id))
            db.execute('''
                UPDATE campaigns
                SET successful_count = successful_count + 1, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            ''', (camp['id'],))
            db.execute('''
                INSERT INTO outreach_log(college_id, recipient_email, college_name, subject, status, error_message)
                VALUES (?, ?, ?, ?, 'sent', '')
            ''', (college_id, (recipient_email or '').lower().strip(), college_name or '', subject or ''))

            # Automatically advance college stage to 'contacted' if not_contacted
            if dir_match:
                try:
                    payload = json.loads(dir_match['payload'])
                    if payload.get('recruitment_stage', 'not_contacted') == 'not_contacted':
                        payload['recruitment_stage'] = 'contacted'
                        db.execute('UPDATE colleges SET payload=? WHERE id=?', (json.dumps(payload), college_id))
                        db.execute(
                            "INSERT INTO outreach_notes(college_id, activity_type, notes, author) VALUES (?, 'stage_change', 'Automatically advanced to Contacted upon email dispatch.', 'System')",
                            (college_id,)
                        )
                except Exception:
                    pass

            return 'accepted', None

        except ValueError as err:
            err_msg = str(err)
            if 'authentication failed' in err_msg.lower():
                # Pause campaign for credential update
                db.execute("UPDATE campaign_queue SET status='queued' WHERE id=?", (msg_id,))
                db.execute("UPDATE campaigns SET status='paused', notes='Sender authentication failed (535). Check Google App Password.' WHERE id=?", (camp['id'],))
                return 'paused', err_msg

            if any(term in err_msg.lower() for term in ['rejected', 'not found', 'invalid', '550', '553']):
                # Permanent failure — never retry
                db.execute('''
                    UPDATE campaign_queue
                    SET status='failed', failure_type='permanent', error_message=?
                    WHERE id=?
                ''', (err_msg, msg_id))
                db.execute('''
                    UPDATE campaigns
                    SET failed_count = failed_count + 1, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                ''', (camp['id'],))
                db.execute('''
                    INSERT INTO outreach_log(college_id, recipient_email, college_name, subject, status, error_message)
                    VALUES (?, ?, ?, ?, 'failed', ?)
                ''', (college_id, (recipient_email or '').lower().strip(), college_name or '', subject or '', err_msg))
                return 'failed', err_msg

            if 'uncertain' in err_msg.lower():
                # Flag for review
                db.execute('''
                    UPDATE campaign_queue
                    SET status='needs_review', failure_type='uncertain', error_message=?
                    WHERE id=?
                ''', (err_msg, msg_id))
                db.execute('''
                    INSERT INTO outreach_log(college_id, recipient_email, college_name, subject, status, error_message)
                    VALUES (?, ?, ?, ?, 'uncertain', ?)
                ''', (college_id, (recipient_email or '').lower().strip(), college_name or '', subject or '', err_msg))
                return 'needs_review', err_msg

            # Temporary failure — schedule exponential retry
            retry_cnt = msg['retry_count'] + 1
            if retry_cnt <= msg['max_retries']:
                delay_sec = 60 * (2 ** (retry_cnt - 1))  # 1m, 2m, 4m
                next_dt = (datetime.now(timezone.utc) + timedelta(seconds=delay_sec)).strftime('%Y-%m-%d %H:%M:%S')
                db.execute('''
                    UPDATE campaign_queue
                    SET status='queued', retry_count=?, next_attempt_at=?, error_message=?, failure_type='temporary'
                    WHERE id=?
                ''', (retry_cnt, next_dt, f"Temporary failure (attempt {retry_cnt}/{msg['max_retries']}): {err_msg}", msg_id))
                return 'retry_scheduled', err_msg
            else:
                db.execute('''
                    UPDATE campaign_queue
                    SET status='failed', failure_type='temporary_exhausted', error_message=?
                    WHERE id=?
                ''', (f"Max retries ({msg['max_retries']}) exhausted: {err_msg}", msg_id))
                db.execute('''
                    UPDATE campaigns
                    SET failed_count = failed_count + 1, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                ''', (camp['id'],))
                db.execute('''
                    INSERT INTO outreach_log(college_id, recipient_email, college_name, subject, status, error_message)
                    VALUES (?, ?, ?, ?, 'failed', ?)
                ''', (college_id, (recipient_email or '').lower().strip(), college_name or '', subject or '', err_msg))
                return 'failed', err_msg

        except Exception as general_err:
            err_msg = str(general_err)
            db.execute('''
                UPDATE campaign_queue
                SET status='needs_review', failure_type='uncertain', error_message=?
                WHERE id=?
            ''', (f"Unexpected error: {err_msg}", msg_id))
            return 'needs_review', err_msg

def worker_step():
    """
    Executes one cycle of the queue worker:
    1. Identifies active campaigns.
    2. Checks timing, schedule, and limits.
    3. Picks and dispatches the next ready message.
    4. Updates campaign status to 'completed' when all messages finish.
    """
    initialize_queue()
    candidate_msg_id = None
    sleep_interval = 0

    with connect() as db:
        # Find active campaigns in priority order
        active_campaigns = db.execute('''
            SELECT * FROM campaigns
            WHERE status IN ('queued', 'sending', 'scheduled')
            ORDER BY id ASC
        ''').fetchall()

        if not active_campaigns:
            return False

        for c_row in active_campaigns:
            camp = dict(c_row)
            can_send, reason = can_dispatch_campaign_now(camp)
            if not can_send:
                continue

            # Check rate caps
            sender_email = camp['sender_email']
            within_limits, cap_reason = check_sender_rate_caps(
                sender_email, camp['hourly_cap'], camp['daily_cap'], db
            )
            if not within_limits:
                continue

            # Check if password is in session
            if not get_sender_password(sender_email):
                db.execute('''
                    UPDATE campaigns
                    SET status='paused',
                        notes='Sender password not in active session. Click Resume and supply App Password.'
                    WHERE id=?
                ''', (camp['id'],))
                continue

            # Mark campaign status 'sending'
            if camp['status'] != 'sending':
                db.execute("UPDATE campaigns SET status='sending', updated_at=CURRENT_TIMESTAMP WHERE id=?", (camp['id'],))

            # Fetch next queued message
            now_utc_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            msg = db.execute('''
                SELECT id FROM campaign_queue
                WHERE campaign_id=?
                  AND status='queued'
                  AND next_attempt_at <= ?
                ORDER BY id ASC LIMIT 1
            ''', (camp['id'], now_utc_str)).fetchone()

            if msg:
                candidate_msg_id = msg['id']
                sleep_interval = camp.get('interval_seconds', 2)
                break

            # Check if any messages remain pending or in retry
            pending = db.execute('''
                SELECT COUNT(*) as cnt FROM campaign_queue
                WHERE campaign_id=? AND status IN ('queued', 'sending')
            ''', (camp['id'],)).fetchone()['cnt']

            if pending == 0:
                # All messages handled! Check if any needs review
                review_cnt = db.execute('''
                    SELECT COUNT(*) as cnt FROM campaign_queue
                    WHERE campaign_id=? AND status='needs_review'
                ''', (camp['id'],)).fetchone()['cnt']

                final_status = 'needs_review' if review_cnt > 0 else 'completed'
                db.execute("UPDATE campaigns SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (final_status, camp['id']))

    if candidate_msg_id is not None:
        outcome, err = dispatch_single_queue_message(candidate_msg_id)
        if sleep_interval > 0:
            time.sleep(sleep_interval)
        return True

    return False

def worker_main_loop():
    logger.info('Campaign Queue Worker started.')
    while not _STOP_EVENT.is_set():
        try:
            acted = worker_step()
            if not acted:
                time.sleep(1.0)
        except Exception as e:
            logger.error(f'Worker loop exception: {e}')
            time.sleep(2.0)
    logger.info('Campaign Queue Worker stopped.')

def start_worker_thread():
    global _WORKER_THREAD
    if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
        return
    recover_stale_queue_on_startup()
    _STOP_EVENT.clear()
    _WORKER_THREAD = threading.Thread(target=worker_main_loop, name='CampaignQueueWorker', daemon=True)
    _WORKER_THREAD.start()

def stop_worker_thread():
    _STOP_EVENT.set()
    if _WORKER_THREAD and _WORKER_THREAD.is_alive():
        _WORKER_THREAD.join(timeout=3)

def is_worker_running():
    return _WORKER_THREAD is not None and _WORKER_THREAD.is_alive()
