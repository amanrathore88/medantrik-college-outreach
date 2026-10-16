"""Local dashboard entry point. Run python dashboard.py."""
import io
import csv
import json
import re
import mimetypes
import secrets
import time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs
import sqlite3
import directory
from settings import BASE_DIR, PORT, load_settings
from directory import get_colleges
import templates
from templates import load_templates
from mailer import send_mail, validate_message
import campaign_queue

import os
import hashlib

CSRF_SECRET = os.environ.get('CSRF_SECRET', 'medantrik_campus_outreach_salt_2026')
CSRF_TOKEN = hashlib.sha256(f"medantrik_csrf_{CSRF_SECRET}".encode('utf-8')).hexdigest()

def get_csrf_token():
    return CSRF_TOKEN

def health():
    checks = {}
    for name, check in [('settings', load_settings), ('directory', get_colleges), ('templates', load_templates), ('campaign_queue', campaign_queue.get_queue_overview)]:
        try:
            check()
            checks[name] = 'ok'
        except (OSError, ValueError, TypeError, sqlite3.Error):
            checks[name] = 'unavailable'
    return {'status': 'ok' if all(v == 'ok' for v in checks.values()) else 'degraded',
            'application': 'medantrik-outreach', 'version': 'phase-7', 'checks': checks}

class CampaignHandler(BaseHTTPRequestHandler):
    def reply(self, content, code=200, content_type='application/json; charset=utf-8'):
        body = json.dumps(content).encode('utf-8') if isinstance(content, (dict, list)) else content
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.end_headers()
        self.wfile.write(body)

    def is_authorized_host(self):
        if (
            os.environ.get('VERCEL')
            or os.environ.get('VERCEL_ENV')
            or os.environ.get('PORT')
            or os.environ.get('ALLOW_REMOTE_HOSTS') == '1'
            or bool(self.headers.get('x-vercel-id'))
            or 'vercel.app' in self.headers.get('Host', '')
        ):
            return True
        host = self.headers.get('Host', '')
        port = getattr(getattr(self, 'server', None), 'server_port', 5050)
        return host in {f'localhost:{port}', f'127.0.0.1:{port}', 'localhost', '127.0.0.1'}

    def local_host(self):
        return self.is_authorized_host()

    def do_GET(self):
        if not self.local_host():
            return self.reply({'status': 'error', 'message': 'Local access only.'}, 403)
        path = urlparse(self.path).path
        try:
            if path == '/api/health':
                result = health()
                return self.reply(result, 200 if result['status'] == 'ok' else 503)
            if path == '/api/settings':
                config = load_settings()
                return self.reply({'sender_email': config.get('sender_email', ''), 'subject_line': config.get('subject_line', ''), 'csrf_token': get_csrf_token()})
            if path == '/api/categories':
                return self.reply(directory.get_categories_with_counts())
            if path == '/api/colleges':
                return self.reply(get_colleges())
            if path == '/api/directory':
                args = {k:v[0] for k,v in parse_qs(urlparse(self.path).query).items()}
                return self.reply(directory.query_colleges(**{k:v for k,v in args.items() if k in ['query','city','status','kind','discipline','stage','category','page','page_size']}))
            if path == '/api/coverage':
                return self.reply(directory.coverage())
            if path == '/api/overview':
                return self.reply(directory.get_overview_stats())
            if path == '/api/campaigns':
                return self.reply(campaign_queue.list_campaigns())
            if path == '/api/campaigns/detail':
                c_id = int(parse_qs(urlparse(self.path).query).get('id', ['0'])[0])
                return self.reply(campaign_queue.get_campaign_detail(c_id))
            if path == '/api/queue/status':
                return self.reply(campaign_queue.get_queue_overview())
            if path == '/api/outreach':
                c_id = parse_qs(urlparse(self.path).query).get('college_id', [None])[0]
                return self.reply(directory.get_outreach_history(int(c_id) if c_id else None))
            if path == '/api/college-detail':
                c_id = int(parse_qs(urlparse(self.path).query).get('id', ['0'])[0])
                return self.reply(directory.get_college_detail(c_id))
            if path == '/api/duplicates':
                return self.reply(directory.duplicates())
            if path == '/api/history':
                return self.reply(directory.history(int(parse_qs(urlparse(self.path).query).get('id',['0'])[0])))
            if path == '/api/pipeline':
                return self.reply(directory.get_pipeline_stats())
            if path == '/api/college/activities':
                c_id = int(parse_qs(urlparse(self.path).query).get('id', ['0'])[0])
                return self.reply(directory.get_college_activities(c_id))
            if path == '/api/export/campaign':
                c_id = int(parse_qs(urlparse(self.path).query).get('id', ['0'])[0])
                csv_bytes = directory.export_campaign_csv(c_id).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/csv; charset=utf-8')
                self.send_header('Content-Disposition', f'attachment; filename="campaign_{c_id}_report.csv"')
                self.send_header('Content-Length', str(len(csv_bytes)))
                self.end_headers()
                self.wfile.write(csv_bytes)
                return
            if path == '/api/export/pipeline':
                csv_bytes = directory.export_pipeline_csv().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/csv; charset=utf-8')
                self.send_header('Content-Disposition', 'attachment; filename="recruitment_pipeline_report.csv"')
                self.send_header('Content-Length', str(len(csv_bytes)))
                self.end_headers()
                self.wfile.write(csv_bytes)
                return
            if path == '/api/export/outreach':
                csv_bytes = directory.export_outreach_csv().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/csv; charset=utf-8')
                self.send_header('Content-Disposition', 'attachment; filename="outreach_history_report.csv"')
                self.send_header('Content-Length', str(len(csv_bytes)))
                self.end_headers()
                self.wfile.write(csv_bytes)
                return
            if path in {'/api/export/workbook', '/api/export/sheets', '/export.xlsx', '/export-sheets.xlsx', '/export-directory.xlsx'}:
                xlsx_bytes = directory.export_multi_category_workbook_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                self.send_header('Content-Disposition', 'attachment; filename="delhi_ncr_directory_categories.xlsx"')
                self.send_header('Content-Length', str(len(xlsx_bytes)))
                self.end_headers()
                self.wfile.write(xlsx_bytes)
                return
            if path in {'/api/export/csv', '/export.csv'}:
                params = parse_qs(urlparse(self.path).query)
                cat_param = params.get('category', [None])[0]
                rows = get_colleges()
                filename = "colleges_delhi_ncr_all.csv"
                if cat_param and cat_param.lower() != 'all':
                    rows = [r for r in rows if (r.get('category') or 'Colleges').lower() == cat_param.lower()]
                    safe_cat = re.sub(r'[^a-zA-Z0-9_-]', '_', cat_param).lower()
                    filename = f"directory_{safe_cat}.csv"
                buf = io.StringIO()
                buf.write('\ufeff')
                writer = csv.DictWriter(buf, fieldnames=[
                    'College_Name', 'category', 'City', 'District', 'Campus', 'Location', 'Type',
                    'Website', 'TPO_Email', 'contact_type', 'Contact_Person', 'Phone',
                    'verification_status', 'recruitment_stage', 'follow_up_date', 'assigned_to',
                    'checked_on', 'source_url', 'institution_source',
                    'notes', 'do_not_contact', 'sendable', 'last_outreach'
                ], extrasaction='ignore')
                writer.writeheader()
                for r in rows:
                    writer.writerow(r)
                body = buf.getvalue().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/csv; charset=utf-8')
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == '/api/templates':
                return self.reply(templates.list_templates())
            if path == '/api/templates/detail':
                t_id = parse_qs(urlparse(self.path).query).get('id', [None])[0]
                return self.reply(templates.get_template(int(t_id) if t_id else None))
            if path == '/api/templates/history':
                t_id = int(parse_qs(urlparse(self.path).query).get('id', ['0'])[0])
                return self.reply(templates.get_template_history(t_id))
            if path in {'/preview', '/api/text-template'}:
                params = parse_qs(urlparse(self.path).query)
                t_id = params.get('id', [None])[0]
                c_id = params.get('college_id', [None])[0]
                try:
                    tpl = templates.get_template(int(t_id) if t_id else None)
                except Exception:
                    html, text = load_templates()
                    tpl = {'subject': '', 'html_body': html, 'text_body': text}
                college = None
                if c_id:
                    college = next((c for c in get_colleges() if c['id'] == int(c_id)), None)
                rendered = templates.render_personalized(tpl['subject'], tpl['html_body'], tpl['text_body'], college)
                return self.reply({'text': rendered['text']}) if path.endswith('text-template') else self.reply(rendered['html'].encode('utf-8'), content_type='text/html; charset=utf-8')
            if path in {'/', '/index.html', '/overview', '/colleges', '/templates', '/campaigns', '/settings'}:
                target = BASE_DIR / 'static' / 'dashboard.html'
            elif path == '/directory':
                target = BASE_DIR / 'static' / 'directory.html'
            elif path.startswith('/static/') or path.startswith('/assets/'):
                folder = BASE_DIR / path.split('/')[1]
                target = (BASE_DIR / unquote(path.lstrip('/'))).resolve()
                if not target.is_relative_to(folder.resolve()):
                    return self.reply({'status': 'error', 'message': 'Invalid asset path.'}, 403)
            else:
                return self.reply({'status': 'error', 'message': 'Page not found.'}, 404)
            if not target.is_file():
                return self.reply({'status': 'error', 'message': 'File not found.'}, 404)
            mime = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
            if target.suffix == '.js':
                mime = 'text/javascript'
            return self.reply(target.read_bytes(), content_type=mime + ('; charset=utf-8' if mime.startswith('text/') else ''))
        except (OSError, ValueError, TypeError, sqlite3.Error):
            self.reply({'status': 'error', 'message': 'A required file is missing or invalid. Check /api/health.'}, 503)

    def do_POST(self):
        if not self.local_host() or self.headers.get('X-CSRF-Token') not in {CSRF_TOKEN, get_csrf_token()}:
            return self.reply({'status': 'error', 'message': 'Reload the dashboard before sending.'}, 403)
        path = urlparse(self.path).path
        allowed_paths = {
            '/api/send-test', '/api/send-single', '/api/send-direct',
            '/api/categories', '/api/categories/delete',
            '/api/directory/save', '/api/directory/merge',
            '/api/import/preview', '/api/import/commit',
            '/api/campaign/record',
            '/api/campaigns/create', '/api/campaigns/pause',
            '/api/campaigns/resume', '/api/campaigns/cancel',
            '/api/campaigns/retry-failed', '/api/queue/step',
            '/api/templates/save', '/api/templates/duplicate',
            '/api/templates/archive', '/api/templates/restore',
            '/api/templates/preview',
            '/api/college/stage', '/api/college/reply',
            '/api/college/follow-up', '/api/college/note'
        }
        if path not in allowed_paths:
            return self.reply({'status': 'error', 'message': 'Endpoint not found.'}, 404)
        try:
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('Send JSON data.')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= (2200000 if path in {'/api/import/preview', '/api/templates/save'} else 65536):
                raise ValueError('Request is empty or too large.')
            try:
                data = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                raise ValueError('Request contains invalid JSON.') from None
            if not isinstance(data, dict):
                raise ValueError('Request must be an object.')

            # Phase 6: Recruitment Pipeline & CRM Activity endpoints
            if path == '/api/college/stage':
                c_id = data.get('college_id') or data.get('id')
                stage = data.get('stage')
                if not c_id or not stage: raise ValueError('College ID and stage are required.')
                return self.reply(directory.update_pipeline_stage(
                    int(c_id),
                    str(stage),
                    notes=str(data.get('notes') or ''),
                    follow_up_date=data.get('follow_up_date'),
                    assigned_to=data.get('assigned_to'),
                    author=str(data.get('author') or 'Hiring Team')
                ))
            if path == '/api/college/reply':
                c_id = data.get('college_id') or data.get('id')
                notes = data.get('notes')
                if not c_id or not notes: raise ValueError('College ID and reply notes are required.')
                return self.reply(directory.record_reply(
                    int(c_id),
                    str(notes),
                    author=str(data.get('author') or 'Hiring Team'),
                    next_stage=str(data.get('stage') or 'replied')
                ))
            if path == '/api/college/follow-up':
                c_id = data.get('college_id') or data.get('id')
                date = data.get('date') or data.get('follow_up_date')
                if not c_id or not date: raise ValueError('College ID and follow-up date (YYYY-MM-DD) are required.')
                return self.reply(directory.set_follow_up(
                    int(c_id),
                    str(date),
                    notes=str(data.get('notes') or ''),
                    assigned_to=data.get('assigned_to'),
                    author=str(data.get('author') or 'Hiring Team')
                ))
            if path == '/api/college/note':
                c_id = data.get('college_id') or data.get('id')
                content = data.get('content') or data.get('notes')
                act_type = data.get('activity_type') or data.get('type') or 'note'
                if not c_id or not content: raise ValueError('College ID and note content are required.')
                return self.reply(directory.log_activity(
                    int(c_id),
                    str(act_type),
                    str(content),
                    author=str(data.get('author') or 'Hiring Team')
                ))

            # Template CRUD endpoints
            if path == '/api/templates/save':
                tpl_id = data.get('id')
                return self.reply(templates.save_template(data, int(tpl_id) if tpl_id else None))
            if path == '/api/templates/duplicate':
                tpl_id = data.get('id')
                if not tpl_id: raise ValueError('Template ID is required.')
                return self.reply(templates.duplicate_template(int(tpl_id)))
            if path == '/api/templates/archive':
                tpl_id = data.get('id')
                if not tpl_id: raise ValueError('Template ID is required.')
                return self.reply(templates.archive_template(int(tpl_id)))
            if path == '/api/templates/restore':
                tpl_id = data.get('template_id') or data.get('id')
                hist_id = data.get('history_id')
                if not tpl_id or not hist_id: raise ValueError('Template ID and History ID are required.')
                return self.reply(templates.restore_template_version(int(tpl_id), int(hist_id)))
            if path == '/api/templates/preview':
                c_id = data.get('college_id')
                college = None
                if c_id:
                    college = next((c for c in get_colleges() if c['id'] == int(c_id)), None)
                rendered = templates.render_personalized(
                    str(data.get('subject') or ''),
                    str(data.get('html_body') or ''),
                    str(data.get('text_body') or ''),
                    college
                )
                return self.reply(rendered)

            if path == '/api/campaign/record':
                tpl_id = data.get('template_id')
                snapshot = data.get('template_snapshot')
                if tpl_id and not snapshot:
                    try:
                        snapshot = templates.create_template_snapshot(int(tpl_id))
                    except Exception:
                        snapshot = None
                elif isinstance(snapshot, dict):
                    snapshot = json.dumps(snapshot)
                c_id = directory.log_campaign(
                    str(data.get('name') or 'Outreach Campaign'),
                    str(data.get('sender_email') or ''),
                    str(data.get('subject') or ''),
                    int(data.get('total_recipients') or 0),
                    int(data.get('successful_count') or 0),
                    int(data.get('failed_count') or 0),
                    str(data.get('status') or 'completed'),
                    int(tpl_id) if tpl_id else None,
                    snapshot
                )
                return self.reply({'status': 'ok', 'campaign_id': c_id})

            # Campaign Queue management endpoints
            if path == '/api/campaigns/create':
                college_ids = data.get('college_ids', [])
                if not isinstance(college_ids, list):
                    raise ValueError('college_ids must be a list.')
                password = data.get('sender_password') or data.get('password')
                return self.reply(campaign_queue.create_staggered_campaign(data, college_ids, password))
            if path == '/api/campaigns/pause':
                c_id = data.get('id')
                if not c_id: raise ValueError('Campaign ID required.')
                return self.reply(campaign_queue.pause_campaign(int(c_id)))
            if path == '/api/campaigns/resume':
                c_id = data.get('id')
                if not c_id: raise ValueError('Campaign ID required.')
                password = data.get('sender_password') or data.get('password')
                res = campaign_queue.resume_campaign(int(c_id), password)
                if password:
                    campaign_queue.worker_step(password_override=password)
                return self.reply(res)
            if path == '/api/campaigns/cancel':
                c_id = data.get('id')
                if not c_id: raise ValueError('Campaign ID required.')
                return self.reply(campaign_queue.cancel_campaign(int(c_id)))
            if path == '/api/campaigns/retry-failed':
                c_id = data.get('id')
                if not c_id: raise ValueError('Campaign ID required.')
                res = campaign_queue.retry_failed_messages(int(c_id))
                password = data.get('sender_password') or data.get('password') or self.headers.get('X-Session-Password')
                if password:
                    campaign_queue.worker_step(password_override=password)
                return self.reply(res)
            if path == '/api/queue/step':
                password = data.get('sender_password') or data.get('password') or self.headers.get('X-Session-Password')
                acted = campaign_queue.worker_step(password_override=password)
                return self.reply({'acted': acted, 'status': 'ok', 'overview': campaign_queue.get_queue_overview()})
            if path == '/api/import/preview':
                return self.reply(directory.preview_import(data.get('text')))
            if path == '/api/import/commit':
                return self.reply(directory.commit_import(str(data.get('token',''))))
            if path == '/api/categories':
                name = data.get('name')
                if not name: raise ValueError('Category name is required.')
                return self.reply(directory.add_category(name, data.get('description', '')))
            if path == '/api/categories/delete':
                name = data.get('name')
                if not name: raise ValueError('Category name is required.')
                return self.reply(directory.delete_category(name))
            if path == '/api/send-direct':
                sender = str(data.get('sender_email') or '').strip()
                if not sender:
                    sender = load_settings().get('sender_email', '').strip()
                password = str(data.get('sender_password') or data.get('password') or '').strip()
                if not password:
                    password = campaign_queue.get_sender_password(sender)
                recipient = str(data.get('recipient_email') or '').strip()
                subject = str(data.get('subject') or '').strip()
                recipient_name = str(data.get('recipient_name') or '').strip()

                validate_message(sender, password, recipient, subject)

                rows = get_colleges()
                matching = next((c for c in rows if c.get('TPO_Email', '').lower() == recipient.lower()), None)
                if matching and matching.get('do_not_contact'):
                    raise ValueError('This email is marked do not contact.')

                college_id = matching['id'] if matching else None
                display_name = recipient_name or (matching['College_Name'] if matching else 'Direct Recipient')

                tpl_id = data.get('template_id')
                html_body = data.get('html_body')
                text_body = data.get('text_body')

                if tpl_id:
                    try:
                        tpl = templates.get_template(int(tpl_id))
                        rendered = templates.render_personalized(
                            subject or tpl.get('subject', ''),
                            tpl.get('html_body', ''),
                            tpl.get('text_body', ''),
                            matching or {'College_Name': display_name, 'Contact_Person': recipient_name or 'Sir/Madam', 'City': 'Delhi-NCR'}
                        )
                        subject = rendered['subject'] or subject
                        html_body = rendered['html']
                        text_body = rendered['text']
                    except Exception:
                        pass

                if not html_body:
                    if data.get('message'):
                        msg_text = str(data.get('message'))
                        esc = msg_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
                        html_body = f"<div style='font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #333;'>{esc}</div>"
                        text_body = msg_text
                    else:
                        default_html, default_text = load_templates()
                        html_body = default_html
                        text_body = default_text
                if not text_body:
                    text_body = re.sub(r'<[^>]+>', ' ', html_body)

                try:
                    send_mail(sender, password, recipient, display_name, subject, html_body, text_body)
                    if password:
                        campaign_queue.set_sender_password(sender, password)
                    directory.log_outreach(college_id, recipient, display_name, subject, 'sent')
                    return self.reply({'status': 'ok', 'message': f'Email successfully sent to {recipient}.'})
                except Exception as send_err:
                    directory.log_outreach(college_id, recipient, display_name, subject, 'failed', str(send_err))
                    raise
            if path == '/api/directory/save':
                record = data.get('record',{})
                if not isinstance(record,dict): raise ValueError('Invalid record.')
                is_col = (record.get('category') or 'Colleges').lower() == 'colleges'
                if is_col and record.get('verification_status') == 'verified' and data.get('verification_confirmed') is not True:
                    raise ValueError('Confirm that you checked this email on the official institutional source.')
                return self.reply(directory.save_record(record,data.get('id'),data.get('version')))
            if path == '/api/directory/merge':
                if data.get('confirmed') is not True: raise ValueError('Review and confirm the merge first.')
                return self.reply(directory.merge_records(data.get('source_id'),data.get('target_id'),data.get('source_version'),data.get('target_version')))

            # Validate message fields
            for k, v in data.items():
                if k == 'template_id':
                    if not isinstance(v, (int, str, type(None))):
                        raise ValueError('Message fields must be text.')
                elif not isinstance(v, str):
                    raise ValueError('Message fields must be text.')

            test = path == '/api/send-test'
            sender = data.get('email' if test else 'sender_email', '').strip()
            password = data.get('password' if test else 'sender_password', '')
            subject = data.get('subject', '')
            recipient = sender if test else data.get('recipient_email', '').strip()
            validate_message(sender, password, recipient, subject)
            college_id = None
            college_name = data.get('college_name', '')
            matching = None
            if not test:
                rows = get_colleges()
                matching = next((c for c in rows if c['TPO_Email'] == recipient.lower()), None)
                if matching:
                    college_id = matching['id']
                    college_name = matching.get('College_Name', college_name)
                if any(c['TPO_Email']==recipient.lower() and c['do_not_contact'] for c in rows):
                    raise ValueError('This email is marked do not contact.')
                if recipient.lower() not in {c['TPO_Email'] for c in rows if c['sendable']}:
                    raise ValueError('Choose a verified, contactable recipient from the directory.')

            tpl_id = data.get('template_id')
            if tpl_id:
                try:
                    tpl = templates.get_template(int(tpl_id))
                except Exception:
                    html, text = load_templates()
                    tpl = {'subject': subject, 'html_body': html, 'text_body': text}
            else:
                html, text = load_templates()
                tpl = {'subject': subject, 'html_body': html, 'text_body': text}

            rendered = templates.render_personalized(
                subject or tpl.get('subject', ''),
                tpl.get('html_body', ''),
                tpl.get('text_body', ''),
                matching
            )
            final_subject = rendered['subject'] or subject
            final_html = rendered['html']
            final_text = rendered['text']

            try:
                send_mail(sender, password, recipient, college_name, final_subject, final_html, final_text)
                if not test:
                    directory.log_outreach(college_id, recipient, college_name, final_subject, 'sent')
                    time.sleep(2)
                self.reply({'status': 'ok', 'message': 'Email accepted by the mail service.'})
            except Exception as send_err:
                if not test:
                    directory.log_outreach(college_id, recipient, college_name, final_subject, 'failed', str(send_err))
                raise
        except (ValueError, TypeError) as error:
            # Validation and transport errors contain fixed messages, never submitted secrets.
            self.reply({'status': 'error', 'message': str(error)}, 400)
        except (OSError, sqlite3.Error):
            self.reply({'status': 'error', 'message': 'A required file or service is unavailable. Check /api/health.'}, 503)

def run():
    campaign_queue.start_worker_thread()
    try:
        server = HTTPServer(('127.0.0.1', PORT), CampaignHandler)
    except OSError:
        campaign_queue.stop_worker_thread()
        print(f'Port {PORT} is unavailable. Check http://localhost:{PORT}/api/health or close the other application.', flush=True)
        raise SystemExit(1)
    print(f'Dashboard: http://localhost:{PORT}/\nHealth: http://localhost:{PORT}/api/health', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        campaign_queue.stop_worker_thread()

if __name__ == '__main__':
    run()
