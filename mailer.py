"""Shared validated SMTP transport. Importing this module never sends mail."""
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.utils import make_msgid, formatdate, formataddr
from settings import BASE_DIR, load_settings

def validate_email(value):
    if not isinstance(value, str) or not re.fullmatch(r'[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+', value):
        raise ValueError('Enter a valid single email address.')

def validate_message(sender, password, recipient, subject):
    validate_email(sender)
    validate_email(recipient)
    if not isinstance(password, str) or not password.strip():
        raise ValueError('Enter a Google App Password for this session.')
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 250 or '\r' in subject or '\n' in subject:
        raise ValueError('Enter a subject of 1–250 characters without line breaks.')

def html_to_plain_text(html):
    """Generates a clean text alternative from HTML to maintain high deliverability."""
    text = re.sub(r'<(script|style)[^>]*>[\s\S]*?</\1>', '', html, flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</tr>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

def send_mail(sender_email, sender_password, recipient_email, recipient_name, subject, html_content, plain_text):
    validate_message(sender_email, sender_password, recipient_email, subject)
    config = load_settings()

    # 1. Clean and sync plain text representation (prevents MIME_HTML_ONLY / MPART_ALT_DIFF spam penalties)
    if not plain_text or len(plain_text.strip()) < 30:
        plain_text = html_to_plain_text(html_content)

    # 2. Inject anti-spam compliance footer (Physical address + clear opt-out statement required by Gmail/Yahoo 2024+ rules)
    processed_html = html_content
    processed_text = plain_text
    if 'unsubscribe' not in processed_html.lower() and 'opt-out' not in processed_html.lower():
        compliance_footer_html = '''
        <div style="margin-top: 32px; padding-top: 18px; border-top: 1px solid #e2e8f0; font-size: 11px; color: #94a3b8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.5;">
            <p style="margin: 0 0 4px 0;"><strong>Medantrik MedTech Pvt Ltd</strong> · Sector 63A, Noida, Uttar Pradesh 201301 | SIIC, IIT Kanpur</p>
            <p style="margin: 0;">You are receiving this academic outreach regarding campus placement & industry project collaboration. If you prefer not to receive future recruitment updates, simply reply with "Unsubscribe" to be removed immediately.</p>
        </div>
        '''
        processed_html = processed_html + compliance_footer_html
        processed_text = processed_text + '\n\n---\nMedantrik MedTech Pvt Ltd | Sector 63A, Noida, UP 201301 | SIIC, IIT Kanpur\nTo opt out of future recruitment updates, reply with "Unsubscribe".'

    # 3. Check for genuine inline media references
    needs_news_clipping = ('assets/ht_news_clipping_opt.jpg' in html_content or 'cid:ht_news_clipping' in html_content)
    processed_html = processed_html.replace('assets/ht_news_clipping_opt.jpg', 'cid:ht_news_clipping')
    image_path = BASE_DIR / 'assets' / 'ht_news_clipping_opt.jpg'

    alternative = MIMEMultipart('alternative')
    alternative.attach(MIMEText(processed_text, 'plain', 'utf-8'))
    alternative.attach(MIMEText(processed_html, 'html', 'utf-8'))

    # 4. RFC 5322 Required Email Headers for Spam Immunity
    sender_domain = sender_email.split('@')[1] if '@' in sender_email else 'medantrik.com'
    msg_id = make_msgid(domain=sender_domain)
    date_header = formatdate(localtime=True)
    display_sender = "Medantrik MedTech"

    from_header = formataddr((display_sender, sender_email))
    to_header = formataddr((recipient_name.strip(), recipient_email)) if (recipient_name and recipient_name.strip()) else recipient_email
    reply_to_header = formataddr((display_sender, sender_email))

    if needs_news_clipping and image_path.exists():
        message = MIMEMultipart('related')
        message['From'] = from_header
        message['To'] = to_header
        message['Reply-To'] = reply_to_header
        message['Subject'] = subject
        message['Date'] = date_header
        message['Message-ID'] = msg_id
        message['MIME-Version'] = '1.0'
        message['X-Mailer'] = 'Medantrik Campus Connect/1.0'
        message['Organization'] = 'Medantrik MedTech Pvt Ltd'
        message.attach(alternative)

        image = MIMEImage(image_path.read_bytes(), _subtype='jpeg')
        image.add_header('Content-ID', '<ht_news_clipping>')
        image.add_header('Content-Disposition', 'inline', filename='ht_news_clipping.jpg')
        message.attach(image)
    else:
        message = alternative
        message['From'] = from_header
        message['To'] = to_header
        message['Reply-To'] = reply_to_header
        message['Subject'] = subject
        message['Date'] = date_header
        message['Message-ID'] = msg_id
        message['MIME-Version'] = '1.0'
        message['X-Mailer'] = 'Medantrik Campus Connect/1.0'
        message['Organization'] = 'Medantrik MedTech Pvt Ltd'

    host, port = config.get('smtp_server', 'smtp.gmail.com'), int(config.get('smtp_port', 587))
    context = ssl.create_default_context()
    try:
        server = smtplib.SMTP_SSL(host, port, timeout=25, context=context) if port == 465 else smtplib.SMTP(host, port, timeout=25)
        try:
            if port != 465:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
            server.login(sender_email, sender_password.replace(' ', '').strip())
            server.sendmail(sender_email, [recipient_email], message.as_string())
        finally:
            server.close()
    except smtplib.SMTPAuthenticationError:
        raise ValueError('Sender authentication failed. Check your App Password and account policy.') from None
    except smtplib.SMTPRecipientsRefused:
        raise ValueError('The mail server rejected this recipient.') from None
    except (OSError, smtplib.SMTPException):
        raise ValueError('Send outcome is uncertain. Check Sent mail before retrying.') from None
