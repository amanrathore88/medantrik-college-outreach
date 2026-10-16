"""Exhaustive tests for Phase 4 template management, versioning, personalization, snapshots, and APIs."""
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
import templates

class TemplatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / 'test_templates.sqlite3'
        self.dir_patch = patch('directory.DB_PATH', self.db_path)
        self.dir_patch.start()
        self.addCleanup(self.dir_patch.stop)

    def request(self, path, body=None, token=True, raw=None):
        handler = object.__new__(dashboard.CampaignHandler)
        handler.path = path
        handler.server = SimpleNamespace(server_port=5050)
        handler.headers = Message()
        handler.headers['Host'] = 'localhost:5050'
        if token:
            handler.headers['X-CSRF-Token'] = dashboard.CSRF_TOKEN
        handler.headers['Content-Type'] = 'application/json'
        payload = raw if raw is not None else json.dumps(body or {}).encode('utf-8')
        handler.headers['Content-Length'] = str(len(payload))
        handler.rfile = io.BytesIO(payload)
        handler.reply = Mock()
        return handler

    def test_starter_templates_seeded(self):
        tpls = templates.list_templates()
        self.assertGreaterEqual(len(tpls), 3)
        default_tpl = next((t for t in tpls if t['is_default']), None)
        self.assertIsNotNone(default_tpl)
        self.assertIn('Default', default_tpl['name'])

        for t in tpls:
            detail = templates.get_template(t['id'])
            self.assertTrue(bool(detail['subject']))
            self.assertTrue(bool(detail['html_body']))
            self.assertTrue(bool(detail['text_body']))
            self.assertEqual(detail['version'], 1)

    def test_save_new_template_and_versioning(self):
        data = {
            'name': 'Robotics Lab Partnership',
            'subject': 'Industry Robotics Lab Connect — {{College_Name}}',
            'html_body': '<p>Dear {{Contact_Person}}, connect with us at {{College_Name}}.</p>',
            'text_body': 'Dear {{Contact_Person}}, connect with us at {{College_Name}}.',
            'is_default': False,
            'note': 'Initial release'
        }
        created = templates.save_template(data)
        self.assertIsNotNone(created['id'])
        self.assertEqual(created['version'], 1)
        self.assertEqual(created['name'], 'Robotics Lab Partnership')

        history = templates.get_template_history(created['id'])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['version'], 1)

        # Update template
        update_data = dict(created)
        update_data['subject'] = 'Updated Subject — {{College_Name}}'
        update_data['note'] = 'Second revision'
        updated = templates.save_template(update_data, created['id'])
        self.assertEqual(updated['version'], 2)
        self.assertEqual(updated['subject'], 'Updated Subject — {{College_Name}}')

        history2 = templates.get_template_history(created['id'])
        self.assertEqual(len(history2), 2)
        self.assertEqual(history2[0]['version'], 2)

    def test_validation_rules(self):
        with self.assertRaisesRegex(ValueError, 'name is required'):
            templates.save_template({'name': '', 'subject': 'Subj', 'html_body': '<p>Hi</p>'})
        with self.assertRaisesRegex(ValueError, 'Subject line is required'):
            templates.save_template({'name': 'Name', 'subject': '', 'html_body': '<p>Hi</p>'})
        with self.assertRaisesRegex(ValueError, 'Formatted HTML body is required'):
            templates.save_template({'name': 'Name', 'subject': 'Subj', 'html_body': ''})

    def test_duplicate_template(self):
        tpls = templates.list_templates()
        original = tpls[0]
        copy = templates.duplicate_template(original['id'])
        self.assertNotEqual(copy['id'], original['id'])
        self.assertEqual(copy['name'], f"{original['name']} (Copy)")
        self.assertEqual(copy['is_default'], 0)
        self.assertEqual(copy['version'], 1)

    def test_archive_template_rules(self):
        tpls = templates.list_templates()
        default_tpl = next(t for t in tpls if t['is_default'])
        
        # Default cannot be archived
        with self.assertRaisesRegex(ValueError, 'Cannot archive the default template'):
            templates.archive_template(default_tpl['id'])

        non_default = next(t for t in tpls if not t['is_default'])
        templates.archive_template(non_default['id'])

        # Excluded from active list
        active = templates.list_templates(include_archived=False)
        self.assertNotIn(non_default['id'], [t['id'] for t in active])

        # Included when include_archived=True
        all_tpls = templates.list_templates(include_archived=True)
        self.assertIn(non_default['id'], [t['id'] for t in all_tpls])

    def test_history_and_restore_version(self):
        data = {
            'name': 'Versioned Template',
            'subject': 'V1 Subject',
            'html_body': '<p>V1 Body</p>',
            'text_body': 'V1 Body'
        }
        t = templates.save_template(data)
        t_id = t['id']

        # Save v2
        t['subject'] = 'V2 Subject'
        t['html_body'] = '<p>V2 Body</p>'
        templates.save_template(t, t_id)

        # Save v3
        t['subject'] = 'V3 Subject'
        t['html_body'] = '<p>V3 Body</p>'
        templates.save_template(t, t_id)

        hist = templates.get_template_history(t_id)
        self.assertEqual(len(hist), 3)
        v1_hist = next(h for h in hist if h['version'] == 1)

        # Restore v1
        restored = templates.restore_template_version(t_id, v1_hist['id'])
        self.assertEqual(restored['version'], 4)
        self.assertEqual(restored['subject'], 'V1 Subject')
        self.assertEqual(restored['html_body'], '<p>V1 Body</p>')

    def test_personalization_tokens_and_fallbacks(self):
        # 1. Full College Data
        college = {
            'College_Name': 'Delhi Technological University',
            'City': 'Delhi',
            'Contact_Person': 'Dr. Rajesh Sharma',
            'Campus': 'Main Campus, Bawana Road',
            'Website': 'https://dtu.ac.in',
            'contact_type': 'placement'
        }
        subj = 'Placement at {{College_Name}} ({{City}})'
        html = '<p>Dear {{Contact_Person}}, visit {{Campus}} at {{Website}}.</p>'
        txt = 'Dear {{Contact_Person}}, {{College_Name}}'
        rendered = templates.render_personalized(subj, html, txt, college)

        self.assertEqual(rendered['subject'], 'Placement at Delhi Technological University (Delhi)')
        self.assertIn('Dear Dr. Rajesh Sharma', rendered['html'])
        self.assertIn('Main Campus, Bawana Road', rendered['html'])
        self.assertIn('https://dtu.ac.in', rendered['html'])

        # 2. Empty / Missing Contact & Institution fields -> Sensible Fallbacks
        empty_college = {}
        rendered_fb = templates.render_personalized(
            'Placement Connect — {{College_Name}}',
            '<p>Dear {{Contact_Person}}, greetings in {{City}}!</p>',
            'Dear {{Contact_Person}}, greetings in {{City}}!',
            empty_college
        )
        self.assertEqual(rendered_fb['subject'], 'Placement Connect — Your Prestigious Institution')
        self.assertIn('Dear Training & Placement Officer', rendered_fb['html'])
        self.assertIn('greetings in Delhi-NCR!', rendered_fb['html'])
        # Check no unparsed template tokens remain
        self.assertNotIn('{{', rendered_fb['subject'])
        self.assertNotIn('{{', rendered_fb['html'])
        self.assertNotIn('{{', rendered_fb['text'])

    def test_campaign_snapshot_immutability(self):
        data = {
            'name': 'Immutable Outreach',
            'subject': 'Snapshot Subject — {{College_Name}}',
            'html_body': '<p>Snapshot Content</p>',
            'text_body': 'Snapshot Content'
        }
        t = templates.save_template(data)
        snapshot_json = templates.create_template_snapshot(t['id'])
        snapshot = json.loads(snapshot_json)
        self.assertEqual(snapshot['version'], 1)
        self.assertEqual(snapshot['subject'], 'Snapshot Subject — {{College_Name}}')

        # Edit template later
        t['subject'] = 'MODIFIED SUBJECT AFTER CAMPAIGN'
        t['html_body'] = '<p>MODIFIED BODY</p>'
        templates.save_template(t, t['id'])

        # Snapshot remains untouched!
        frozen = json.loads(snapshot_json)
        self.assertEqual(frozen['subject'], 'Snapshot Subject — {{College_Name}}')
        self.assertEqual(frozen['html_body'], '<p>Snapshot Content</p>')

    def test_template_rest_api_endpoints(self):
        # 1. GET /api/templates
        handler = self.request('/api/templates')
        handler.do_GET()
        tpls = handler.reply.call_args.args[0]
        self.assertGreaterEqual(len(tpls), 3)

        # 2. GET /api/templates/detail
        handler = self.request(f"/api/templates/detail?id={tpls[0]['id']}")
        handler.do_GET()
        detail = handler.reply.call_args.args[0]
        self.assertEqual(detail['id'], tpls[0]['id'])

        # 3. POST /api/templates/save
        handler = self.request('/api/templates/save', {
            'name': 'API Template',
            'subject': 'API Subject — {{College_Name}}',
            'html_body': '<p>Hello from API</p>',
            'text_body': 'Hello from API'
        })
        handler.do_POST()
        res = handler.reply.call_args.args[0]
        self.assertEqual(res['name'], 'API Template')
        new_id = res['id']

        # 4. POST /api/templates/duplicate
        handler = self.request('/api/templates/duplicate', {'id': new_id})
        handler.do_POST()
        dup = handler.reply.call_args.args[0]
        self.assertIn('(Copy)', dup['name'])

        # 5. POST /api/templates/preview
        handler = self.request('/api/templates/preview', {
            'subject': 'Subject for {{College_Name}}',
            'html_body': '<p>Dear {{Contact_Person}}</p>',
            'text_body': 'Dear {{Contact_Person}}',
            'college_id': 1
        })
        handler.do_POST()
        prev = handler.reply.call_args.args[0]
        self.assertIn('subject', prev)
        self.assertIn('html', prev)
        self.assertNotIn('{{College_Name}}', prev['subject'])

        # 6. POST /api/campaign/record with template_id
        handler = self.request('/api/campaign/record', {
            'name': 'Campaign with Snapshot',
            'sender_email': 'hiring@example.org',
            'subject': 'Placement Outreach',
            'total_recipients': 5,
            'successful_count': 5,
            'failed_count': 0,
            'template_id': new_id
        })
        handler.do_POST()
        camp_res = handler.reply.call_args.args[0]
        self.assertEqual(camp_res['status'], 'ok')
        camp_id = camp_res['campaign_id']

        # Verify campaign record stored snapshot
        with directory.connect() as db:
            camp_row = db.execute('SELECT * FROM campaigns WHERE id=?', (camp_id,)).fetchone()
            self.assertEqual(camp_row['template_id'], new_id)
            self.assertTrue(bool(camp_row['template_snapshot']))
            snapshot_data = json.loads(camp_row['template_snapshot'])
            self.assertEqual(snapshot_data['name'], 'API Template')

if __name__ == '__main__':
    unittest.main()
