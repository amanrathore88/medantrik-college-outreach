"""Command-line sender using the same settings, templates and transport as the UI."""
import csv
import getpass
import time
from settings import BASE_DIR, load_settings, get_password
from directory import get_colleges
from templates import load_templates
from mailer import send_mail

def log_result(college_name, email, status, note=''):
    path = BASE_DIR / 'campaign_send_log.csv'
    exists = path.exists()
    with path.open('a', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        if not exists:
            writer.writerow(['Timestamp', 'College_Name', 'Email', 'Status', 'Note'])
        writer.writerow([time.strftime('%Y-%m-%d %H:%M:%S'), college_name, email, status, note])

def main():
    config = load_settings()
    html, text = load_templates()
    sender = config.get('sender_email', '')
    password = get_password() or getpass.getpass('Google App Password (not saved): ')
    subject = config.get('subject_line', '')
    test_mode = config.get('test_mode', True)
    rows = get_colleges()
    blocked = {r['TPO_Email'] for r in rows if r['do_not_contact']}
    seen = set()
    recipients = []
    for row in rows:
        if row['sendable'] and row['TPO_Email'] not in blocked and row['TPO_Email'] not in seen:
            recipients.append(row)
            seen.add(row['TPO_Email'])
    if test_mode:
        recipients = [{'College_Name': 'Test Placement Cell', 'TPO_Email': config.get('test_recipient_email', sender)}]
    print(f"Mode: {'TEST' if test_mode else 'LIVE'}; recipients: {len(recipients)}")
    if not test_mode and input('Type SEND to confirm this live campaign: ') != 'SEND':
        print('Cancelled.')
        return
    accepted = failed = 0
    for index, college in enumerate(recipients):
        try:
            send_mail(sender, password, college['TPO_Email'].strip(), college['College_Name'], subject, html, text)
            accepted += 1
            log_result(college['College_Name'], college['TPO_Email'], 'Accepted by provider')
        except (ValueError, OSError):
            failed += 1
            log_result(college['College_Name'], college['TPO_Email'], 'Failed or uncertain', 'Check account, address and Sent mail before retrying.')
            print('Sending stopped after an error. Check Sent mail before retrying.')
            break
        if index < len(recipients) - 1:
            time.sleep(max(2, float(config.get('delay_seconds_between_emails', 6))))
    print(f'Accepted by provider: {accepted}; failed or uncertain: {failed}; remaining: {len(recipients)-accepted-failed}')

if __name__ == '__main__':
    main()
