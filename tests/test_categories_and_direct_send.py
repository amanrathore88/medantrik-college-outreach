import io
import json
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from email.message import Message
import dashboard
import directory

class CategoriesAndDirectSendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch('directory.DB_PATH', Path(self.temp.name) / 'test.sqlite3')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        directory.initialize()

    def request(self, path, body=None, token=True):
        handler = object.__new__(dashboard.CampaignHandler)
        handler.path = path
        handler.server = SimpleNamespace(server_port=5050)
        handler.headers = Message()
        handler.headers['Host'] = 'localhost:5050'
        if token:
            handler.headers['X-CSRF-Token'] = dashboard.CSRF_TOKEN
        handler.headers['Content-Type'] = 'application/json'
        payload = json.dumps(body or {}).encode('utf-8')
        handler.headers['Content-Length'] = str(len(payload))
        handler.rfile = io.BytesIO(payload)
        handler.reply = Mock()
        return handler

    def test_default_categories_seeded(self):
        cats = directory.get_categories()
        self.assertIn('Colleges', cats)
        self.assertIn('Gyms', cats)
        self.assertIn('Offices', cats)
        self.assertIn('Households', cats)

        counts = directory.get_categories_with_counts()
        self.assertTrue(any(c['name'] == 'Colleges' and c['count'] == 25 for c in counts))

    def test_add_and_delete_category(self):
        directory.add_category('Startups', 'Tech startups in NCR')
        cats = directory.get_categories()
        self.assertIn('Startups', cats)

        # Cannot delete default Colleges category
        with self.assertRaises(ValueError):
            directory.delete_category('Colleges')

        # Can delete empty Startups category
        directory.delete_category('Startups')
        self.assertNotIn('Startups', directory.get_categories())

    def test_create_and_filter_records_by_category(self):
        # Create a Gym record
        gym_record = directory.save_record({
            'College_Name': "Gold's Gym Sector 18",
            'category': 'Gyms',
            'City': 'Noida',
            'Location': 'Sector 18, Noida',
            'TPO_Email': 'noida@goldsgym.in',
            'Contact_Person': 'Gym Manager',
            'Phone': '9876543210',
            'notes': 'Fitness club partner'
        })
        self.assertEqual(gym_record['category'], 'Gyms')
        self.assertTrue(gym_record['sendable'])

        # Create an Office record
        office_record = directory.save_record({
            'College_Name': 'MedTech Innovations Corp',
            'category': 'Offices',
            'City': 'Delhi',
            'Location': 'Connaught Place',
            'TPO_Email': 'hr@medtechinnovations.com',
            'Contact_Person': 'HR Director',
            'Phone': '9876543211',
            'notes': 'Corporate workplace'
        })
        self.assertEqual(office_record['category'], 'Offices')
        self.assertTrue(office_record['sendable'])

        # Filter by Gyms
        gyms = directory.query_colleges(category='Gyms')['items']
        self.assertEqual(len(gyms), 1)
        self.assertEqual(gyms[0]['College_Name'], "Gold's Gym Sector 18")

        # Filter by Offices
        offices = directory.query_colleges(category='Offices')['items']
        self.assertEqual(len(offices), 1)
        self.assertEqual(offices[0]['College_Name'], 'MedTech Innovations Corp')

        # Filter by Colleges
        colleges = directory.query_colleges(category='Colleges')['items']
        self.assertEqual(len(colleges), 25)

        # Overview category counts
        stats = directory.get_overview_stats()
        cat_map = {c['name']: c['count'] for c in stats['categories']}
        self.assertEqual(cat_map['Colleges'], 25)
        self.assertEqual(cat_map['Gyms'], 1)
        self.assertEqual(cat_map['Offices'], 1)

    def test_direct_send_to_any_email_without_directory_entity(self):
        """User can send an email immediately to any email address on the spot."""
        recipient = 'external_partner@randomdomain.com'
        payload = {
            'sender_email': 'hiring@medantrik.com',
            'sender_password': 'test_app_password',
            'recipient_email': recipient,
            'recipient_name': 'Dr. Sharma / Fitness Lead',
            'subject': 'Immediate Direct Outreach Opportunity',
            'message': 'Hello Dr. Sharma,\n\nWe would like to introduce our healthcare technology.'
        }
        handler = self.request('/api/send-direct', payload)
        with patch('dashboard.send_mail') as mock_send:
            handler.do_POST()
            self.assertEqual(handler.reply.call_args.args[0]['status'], 'ok')
            mock_send.assert_called_once()
            # Verify recipient email passed to mailer
            self.assertEqual(mock_send.call_args.args[2], recipient)
            self.assertEqual(mock_send.call_args.args[4], 'Immediate Direct Outreach Opportunity')

        # Verify it was recorded in outreach_log
        with directory.connect() as db:
            log_row = db.execute('SELECT * FROM outreach_log WHERE recipient_email=?', (recipient,)).fetchone()
            self.assertIsNotNone(log_row)
            self.assertEqual(log_row['status'], 'sent')
            self.assertEqual(log_row['college_name'], 'Dr. Sharma / Fitness Lead')

    def test_direct_send_respects_dnc_if_known(self):
        """If an email is already known in the system and marked Do Not Contact, direct send blocks it."""
        first = directory.get_colleges()[0]
        directory.save_record(dict(first, do_not_contact=True), first['id'], first['version'])

        payload = {
            'sender_email': 'hiring@medantrik.com',
            'sender_password': 'test_app_password',
            'recipient_email': first['TPO_Email'],
            'subject': 'Hello',
            'message': 'Testing DNC'
        }
        handler = self.request('/api/send-direct', payload)
        with patch('dashboard.send_mail') as mock_send:
            handler.do_POST()
            mock_send.assert_not_called()
            self.assertEqual(handler.reply.call_args.args[1], 400)
            self.assertIn('do not contact', handler.reply.call_args.args[0]['message'].lower())
