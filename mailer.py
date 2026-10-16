"""Shared validated SMTP transport. Importing this module never sends mail."""
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
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

def send_mail(sender_email, sender_password, recipient_email, recipient_name, subject, html_content, plain_text):
    validate_message(sender_email, sender_password, recipient_email, subject)
    config = load_settings()
    # Check if template or custom message actually references the inline news clipping image
    needs_news_clipping = ('assets/ht_news_clipping_opt.jpg' in html_content or 'cid:ht_news_clipping' in html_content)
    processed_html = html_content.replace('assets/ht_news_clipping_opt.jpg', 'cid:ht_news_clipping')
    image_path = BASE_DIR / 'assets' / 'ht_news_clipping_opt.jpg'

    alternative = MIMEMultipart('alternative')
    alternative.attach(MIMEText(plain_text, 'plain', 'utf-8'))
    alternative.attach(MIMEText(processed_html, 'html', 'utf-8'))

    if needs_news_clipping and image_path.exists():
        message = MIMEMultipart('related')
        message['From'] = sender_email
        message['To'] = recipient_email
        message['Reply-To'] = sender_email
        message['Subject'] = subject
        message.attach(alternative)

        image = MIMEImage(image_path.read_bytes(), _subtype='jpeg')
        image.add_header('Content-ID', '<ht_news_clipping>')
        image.add_header('Content-Disposition', 'inline', filename='ht_news_clipping.jpg')
        message.attach(image)
    else:
        message = alternative
        message['From'] = sender_email
        message['To'] = recipient_email
        message['Reply-To'] = sender_email
        message['Subject'] = subject

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
