import sys
import os
import shutil
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# On Vercel Serverless, file system is read-only except /tmp
if os.environ.get('VERCEL'):
    tmp_data = Path('/tmp/data')
    tmp_data.mkdir(exist_ok=True, parents=True)
    tmp_db = tmp_data / 'directory.sqlite3'
    orig_db = ROOT_DIR / 'data' / 'directory.sqlite3'

    # Seed /tmp database from bundled database if not already copied
    if not tmp_db.exists() and orig_db.exists():
        try:
            shutil.copy2(orig_db, tmp_db)
        except Exception:
            pass

    import directory
    if tmp_db.exists():
        directory.DB_PATH = tmp_db

from dashboard import CampaignHandler

class handler(CampaignHandler):
    """Vercel Python serverless entry handler."""
    pass
