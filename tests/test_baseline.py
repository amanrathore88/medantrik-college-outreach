import io
import json
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from email.message import Message
import dashboard
import mailer
from settings import load_settings, BASE_DIR

class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch('directory.DB_PATH', Path(self.temp.name) / 'test.sqlite3')
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

    def test_health_and_unverified_directory(self):
        self.assertEqual(dashboard.health()['status'], 'ok')
        rows = dashboard.get_colleges()
        self.assertEqual(len(rows), 25)
        self.assertTrue(all(c['verification_status'] == 'unverified' for c in rows))

    def test_settings_and_html_do_not_contain_saved_password(self):
        self.assertNotIn('sender_password', load_settings())
        handler = self.request('/api/settings')
        handler.do_GET()
        self.assertEqual(set(handler.reply.call_args.args[0]), {'sender_email', 'subject_line', 'csrf_token'})
        html = (BASE_DIR / 'static/dashboard.html').read_text(encoding='utf-8')
        password_input = next(line for line in html.splitlines() if 'id="senderPassword"' in line)
        self.assertNotIn('value=', password_input)

    def test_invalid_requests_never_send(self):
        cases = [({}, True, None), ([], True, None), ({'email': 5}, True, None),
                 ({}, True, b'{invalid'), ({}, False, None),
                 ({'email': 'a@example.org', 'password': 'test', 'subject': 'hello\r\nBcc: x@example.org'}, True, None)]
        with patch('dashboard.send_mail') as send:
            for body, token, raw in cases:
                handler = self.request('/api/send-test', body, token, raw)
                handler.do_POST()
                self.assertIn(handler.reply.call_args.args[1], [400, 403])
            send.assert_not_called()

    def test_test_email_goes_only_to_sender(self):
        handler = self.request('/api/send-test', {'email': 'a@example.org', 'password': 'dummy', 'subject': 'Test', 'recipient_email': 'other@example.org'})
        with patch('dashboard.send_mail') as send:
            handler.do_POST()
            self.assertEqual(send.call_args.args[0], 'a@example.org')
            self.assertEqual(send.call_args.args[2], 'a@example.org')
            self.assertEqual(handler.reply.call_args.args[0]['status'], 'ok')

    def test_external_recipient_rejected(self):
        handler = self.request('/api/send-single', {'sender_email': 'a@example.org', 'sender_password': 'dummy', 'subject': 'Test', 'recipient_email': 'unknown@example.org'})
        with patch('dashboard.send_mail') as send:
            handler.do_POST()
            send.assert_not_called()
            self.assertEqual(handler.reply.call_args.args[1], 400)

    def test_static_path_cannot_escape(self):
        handler = self.request('/assets/%2e%2e/config.json')
        handler.do_GET()
        self.assertEqual(handler.reply.call_args.args[1], 403)

    def test_mailer_closes_connection_on_failure_without_leaking_password(self):
        with patch('mailer.smtplib.SMTP') as smtp:
            smtp.return_value.login.side_effect = mailer.smtplib.SMTPAuthenticationError(535, b'sensitive response')
            with self.assertRaisesRegex(ValueError, 'authentication failed') as raised:
                mailer.send_mail('a@example.org', 'dummy-secret', 'b@example.org', '', 'Test', '<p>Hi</p>', 'Hi')
            self.assertNotIn('sensitive', str(raised.exception))
            self.assertNotIn('dummy-secret', str(raised.exception))
            smtp.return_value.close.assert_called_once()

    def test_overview_and_campaign_endpoints(self):
        handler = self.request('/api/overview')
        handler.do_GET()
        overview = handler.reply.call_args.args[0]
        self.assertIn('total', overview)
        self.assertIn('coverage', overview)
        self.assertIn('records_needing_review', overview)

        handler = self.request('/api/campaign/record', {
            'name': 'Test Run', 'sender_email': 'hiring@example.org', 'subject': 'Subject',
            'total_recipients': 5, 'successful_count': 5, 'failed_count': 0
        })
        handler.do_POST()
        self.assertEqual(handler.reply.call_args.args[0]['status'], 'ok')

        handler = self.request('/api/campaigns')
        handler.do_GET()
        campaigns = handler.reply.call_args.args[0]
        self.assertTrue(any(c['name'] == 'Test Run' for c in campaigns))

    def test_navigation_routes_serve_dashboard(self):
        for route in ['/overview', '/colleges', '/templates', '/campaigns', '/settings']:
            handler = self.request(route)
            handler.do_GET()
            self.assertIn('text/html', handler.reply.call_args.kwargs['content_type'])

    def test_college_detail_api(self):
        handler = self.request('/api/college-detail?id=1')
        handler.do_GET()
        detail = handler.reply.call_args.args[0]
        self.assertIn('record', detail)
        self.assertIn('history', detail)
        self.assertIn('outreach', detail)

if __name__ == '__main__':
    unittest.main()
