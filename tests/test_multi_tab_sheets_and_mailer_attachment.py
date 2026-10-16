import io
import json
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from email.message import Message
import openpyxl
import email

import dashboard
import directory
import mailer
from settings import BASE_DIR

class MultiTabSheetsAndMailerAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch('directory.DB_PATH', Path(self.temp.name) / 'test_sheets.sqlite3')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def request(self, path, body=None, token=True, raw=None):
        handler = object.__new__(dashboard.CampaignHandler)
        handler.path = path
        handler.server = SimpleNamespace(server_port=5050)
        handler.headers = Message()
        handler.headers['Host'] = 'localhost:5050'
        if token:
            handler.headers['X-CSRF-Token'] = dashboard.CSRF_TOKEN
        handler.headers['Content-Type'] = 'application/json'
        payload = raw if raw is not None else json.dumps(body or {}).encode()
        handler.headers['Content-Length'] = str(len(payload))
        handler.rfile = io.BytesIO(payload)
        handler.reply = Mock()
        return handler

    def test_mailer_no_unwanted_attachment_on_plain_emails(self):
        """Verify emails without news clipping reference have NO image attachment."""
        with patch('mailer.smtplib.SMTP') as mock_smtp:
            instance = Mock()
            mock_smtp.return_value = instance

            # 1. Custom plain message without template
            mailer.send_mail(
                'join@medantrik.com', 'testpwd123', 'candidate@example.org',
                'Candidate', 'Interview invitation', '<p>Hello Candidate</p>', 'Hello Candidate'
            )
            sent_str = instance.sendmail.call_args[0][2]
            msg = email.message_from_string(sent_str)
            content_types = [p.get_content_type() for p in msg.walk()]

            self.assertEqual(msg.get_content_type(), 'multipart/alternative')
            self.assertNotIn('image/jpeg', content_types)
            self.assertNotIn('image/png', content_types)
            self.assertNotIn('Content-Disposition', str(msg))

    def test_mailer_attaches_news_clipping_when_explicitly_referenced(self):
        """Verify emails referencing ht_news_clipping_opt.jpg attach the image inline."""
        with patch('mailer.smtplib.SMTP') as mock_smtp:
            instance = Mock()
            mock_smtp.return_value = instance

            mailer.send_mail(
                'join@medantrik.com', 'testpwd123', 'candidate@example.org',
                'Candidate', 'Interview invitation',
                '<p>Featured in Hindustan Times:</p><img src="assets/ht_news_clipping_opt.jpg">',
                'Featured in Hindustan Times.'
            )
            sent_str = instance.sendmail.call_args[0][2]
            msg = email.message_from_string(sent_str)
            content_types = [p.get_content_type() for p in msg.walk()]

            self.assertEqual(msg.get_content_type(), 'multipart/related')
            self.assertIn('image/jpeg', content_types)

    def test_multi_tab_workbook_generation_creates_tabs_for_all_categories(self):
        """Verify generate_multi_category_workbook creates a sheet for every category."""
        directory.initialize()

        # Add custom categories
        directory.add_category('Gyms', 'Fitness centers')
        directory.add_category('Offices', 'Workplaces')
        directory.add_category('Households', 'Residential communities')
        directory.add_category('Clinics & Healthcare', 'Clinics')

        wb = directory.generate_multi_category_workbook()
        sheet_names = wb.sheetnames

        self.assertIn('Overview & Categories', sheet_names)
        self.assertIn('Colleges', sheet_names)
        self.assertIn('Gyms', sheet_names)
        self.assertIn('Offices', sheet_names)
        self.assertIn('Households', sheet_names)
        self.assertIn('Clinics & Healthcare', sheet_names)

    def test_new_category_contact_populates_in_its_respective_tab(self):
        """Verify contacts added to a new category are placed on its dedicated tab."""
        directory.initialize()
        directory.add_category('Gyms')

        # Add a gym record
        directory.save_record({
            'College_Name': 'FitZone Gym',
            'category': 'Gyms',
            'City': 'Noida',
            'Location': 'Sector 18, Noida',
            'TPO_Email': 'manager@fitzone.com',
            'Contact_Person': 'Rajesh Sharma',
            'contact_type': 'general'
        })

        # Add a household record
        directory.save_record({
            'College_Name': 'Greenwood Apartments RWA',
            'category': 'Households',
            'City': 'Delhi',
            'Location': 'Dwarka Sector 10',
            'TPO_Email': 'rwa@greenwood.org',
            'Contact_Person': 'Sunita Rao',
            'contact_type': 'general'
        })

        wb = directory.generate_multi_category_workbook()
        gyms_ws = wb['Gyms']
        gyms_names = [gyms_ws.cell(row=i, column=1).value for i in range(2, gyms_ws.max_row + 1)]
        self.assertIn('FitZone Gym', gyms_names)

        households_ws = wb['Households']
        households_names = [households_ws.cell(row=i, column=1).value for i in range(2, households_ws.max_row + 1)]
        self.assertIn('Greenwood Apartments RWA', households_names)

        # Make sure FitZone Gym does not leak into Colleges tab
        colleges_ws = wb['Colleges']
        colleges_names = [colleges_ws.cell(row=i, column=1).value for i in range(2, colleges_ws.max_row + 1)]
        self.assertNotIn('FitZone Gym', colleges_names)

    def test_export_sheets_endpoint_returns_xlsx(self):
        """Verify GET /api/export/sheets returns valid multi-tab Excel spreadsheet."""
        directory.initialize()
        bytes_data = directory.export_multi_category_workbook_bytes()
        self.assertTrue(len(bytes_data) > 5000)

        # Parse with openpyxl to verify valid format
        wb = openpyxl.load_workbook(io.BytesIO(bytes_data))
        self.assertIn('Overview & Categories', wb.sheetnames)
        self.assertIn('Colleges', wb.sheetnames)

if __name__ == '__main__':
    unittest.main()
