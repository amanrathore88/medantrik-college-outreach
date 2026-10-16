"""Non-secret configuration; passwords are supplied at runtime."""
import json
import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
PORT = 5050

def load_settings():
    config = json.loads((BASE_DIR / 'config.json').read_text(encoding='utf-8'))
    config.pop('sender_password', None)
    return config

def get_password():
    return os.environ.get('MEDANTRIK_SMTP_PASSWORD', '').replace(' ', '').strip()
