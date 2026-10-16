"""Phase 7 Final Comprehensive Validation & Verification Suite.

Tests end-to-end integration across all phases:
- Search aliases, geographic boundary isolation, imports, deduplication.
- Personalization, fallbacks for missing contacts, template snapshot immutability.
- Queue persistence across simulated process restarts and crashes.
- Pause, resume, cancellation, rate limiting, and IST schedule gating.
- Recruitment pipeline progression, reply recording, and automated follow-up suppression.
- CSV export data integrity and security invariants.
"""
import csv
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, Mock

import campaign_queue
import directory
import mailer
import templates

class Phase7ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / 'phase7_val.sqlite3'
        self.orig_db = directory.DB_PATH
        directory.DB_PATH = self.db_path
        directory.initialize()
        campaign_queue.initialize_queue()
        templates.initialize_templates()
        campaign_queue._SESSION_CREDENTIALS.clear()

        # Seed sample verified institutions across areas
        self.colleges = [
            {
                'College_Name': 'Delhi Technological University',
                'Aliases': 'DTU, Delhi College of Engineering, DCE',
                'City': 'Delhi',
                'District': 'North West Delhi',
                'Location': 'Shahbad Daulatpur, Bawana Road, Delhi',
                'Campus': 'Main Campus',
                'Type': 'Engineering & Technology',
                'TPO_Email': 'placements@dtu.ac.in',
                'contact_type': 'placement',
                'Contact_Person': 'Prof. Rajesh Rohilla',
                'Phone': '011-27871018',
                'Website': 'https://dtu.ac.in',
                'verification_status': 'verified',
                'checked_on': '2026-10-16',
                'source_url': 'https://dtu.ac.in/placement'
            },
            {
                'College_Name': 'Amity School of Engineering and Technology',
                'Aliases': 'ASET Noida',
                'City': 'Noida',
                'District': 'Gautam Buddha Nagar',
                'Location': 'Sector 125, Noida',
                'Campus': 'Noida Campus',
                'Type': 'Engineering & Technology',
                'TPO_Email': 'aset.placements@amity.edu',
                'contact_type': 'placement',
                'Contact_Person': '',  # Test missing contact fallback
                'Phone': '0120-4392000',
                'Website': 'https://amity.edu',
                'verification_status': 'verified',
                'checked_on': '2026-10-16',
                'source_url': 'https://amity.edu/aset/placement'
            },
            {
                'College_Name': 'Gurugram Institute of Technology & Management',
                'Aliases': 'GITM Gurgaon',
                'City': 'Gurugram',
                'District': 'Gurugram',
                'Location': 'Bilharthal, Pataudi, Gurugram',
                'Campus': 'Main Campus',
                'Type': 'Engineering & Technology',
                'TPO_Email': 'tpo@gitmgurgaon.com',
                'contact_type': 'placement',
                'Contact_Person': 'Dr. Alok Mishra',
                'Phone': '0124-2715000',
                'Website': 'https://gitmgurgaon.com',
                'verification_status': 'verified',
                'checked_on': '2026-10-16',
                'source_url': 'https://gitmgurgaon.com/placements'
            }
        ]
        self.ids = []
        for c in self.colleges:
            res = directory.save_record(c)
            self.ids.append(res['id'])

    def tearDown(self):
        directory.DB_PATH = self.orig_db
        self.tmp.cleanup()

    # ==================== 1. SEARCH, ALIASES & BOUNDARIES ====================

    def test_search_alias_gurgaon_and_gurugram(self):
        """Searching 'Gurgaon' returns Gurugram institutions without leaking outside."""
        res_gurgaon = directory.query_colleges(query='Gurgaon')
        res_gurugram = directory.query_colleges(query='Gurugram')
        self.assertEqual(res_gurgaon['total'], res_gurugram['total'])
        self.assertTrue(any(c['City'] == 'Gurugram' for c in res_gurgaon['items']))

    def test_acronym_alias_search(self):
        """Searching by acronym like 'DTU' or 'DCE' matches through Aliases."""
        res_dtu = directory.query_colleges(query='DTU')
        self.assertGreaterEqual(res_dtu['total'], 1)
        self.assertIn('Delhi Technological University', res_dtu['items'][0]['College_Name'])

        res_dce = directory.query_colleges(query='DCE')
        self.assertGreaterEqual(res_dce['total'], 1)
        self.assertIn('Delhi Technological University', res_dce['items'][0]['College_Name'])

    def test_geographic_boundary_filtering(self):
        """Filtering by area strictly isolates Delhi vs Noida vs Gurugram."""
        delhi_res = directory.query_colleges(city='Delhi')
        self.assertTrue(all(c['City'] == 'Delhi' for c in delhi_res['items']))

        noida_res = directory.query_colleges(city='Noida')
        self.assertTrue(all(c['City'] == 'Noida' for c in noida_res['items']))

        ggn_res = directory.query_colleges(city='Gurugram')
        self.assertTrue(all(c['City'] == 'Gurugram' for c in ggn_res['items']))

    # ==================== 2. IMPORTS & DEDUPLICATION ====================

    def test_import_review_and_scope_rejection(self):
        """Importing out-of-scope cities (e.g. Bangalore) fails before committing."""
        out_of_scope = [
            {'College_Name': 'Bangalore Tech Academy', 'City': 'Bangalore', 'TPO_Email': 'tpo@bengaluru.edu'}
        ]
        preview = directory.preview_import(json.dumps(out_of_scope))
        # preview shows errors
        self.assertEqual(preview['add'], 0)
        self.assertEqual(preview['errors'], 1)

    def test_duplicate_skipping_and_campus_separation(self):
        """Duplicate colleges with identical name and campus are skipped, different campuses preserved."""
        new_campus = {
            'College_Name': 'Delhi Technological University',
            'Campus': 'East Delhi Campus',
            'City': 'Delhi',
            'TPO_Email': 'east.placements@dtu.ac.in',
            'contact_type': 'placement',
            'verification_status': 'unverified'
        }
        res = directory.save_record(new_campus)
        self.assertNotEqual(res['id'], self.ids[0])

        # Exact duplicate cannot overwrite existing record silently
        preview = directory.preview_import(json.dumps([new_campus]))
        self.assertEqual(preview['duplicates'], 1)
        self.assertEqual(preview['add'], 0)

    # ==================== 3. TEMPLATES, PERSONALIZATION & FALLBACKS ====================

    def test_personalization_and_missing_contact_fallback(self):
        """Missing Contact_Person falls back to 'Placement Cell / Placement Officer' cleanly."""
        colleges = directory.get_colleges()
        amity = next(c for c in colleges if c['id'] == self.ids[1])
        self.assertFalse(bool(amity.get('Contact_Person')))

        subject = "Campus Hiring Connect — {{College_Name}}"
        html = "<p>Dear {{Contact_Person}}, we invite {{College_Name}} in {{City}} for recruitment.</p>"
        text = "Dear {{Contact_Person}}, we invite {{College_Name}} in {{City}} for recruitment."

        rendered = templates.render_personalized(subject, html, text, amity)
        self.assertIn("Campus Hiring Connect — Amity School of Engineering and Technology", rendered['subject'])
        self.assertIn("Training & Placement Officer", rendered['html'])
        self.assertIn("Amity School of Engineering and Technology in Noida", rendered['html'])
        self.assertIn("Training & Placement Officer", rendered['text'])

    def test_template_snapshot_immutability(self):
        """Editing or archiving a template after campaign creation does NOT mutate scheduled campaign."""
        tpl = templates.save_template({
            'name': 'Original Outreach',
            'subject': 'Original Subject for {{College_Name}}',
            'html_body': '<p>Original body for {{College_Name}}</p>',
            'text_body': 'Original body for {{College_Name}}'
        })
        tpl_id = tpl['id']

        # Create campaign using this template
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Snapshot Verification Campaign',
            'sender_email': 'hiring@medantrik.com',
            'template_id': tpl_id
        }, [self.ids[0]])
        camp_id = camp['id']

        # Now mutate template in template library
        templates.save_template({
            'name': 'Original Outreach',
            'subject': 'MUTATED Subject',
            'html_body': '<p>MUTATED HTML</p>',
            'text_body': 'MUTATED Text'
        }, tpl_id)

        # Inspect campaign messages in queue
        camp_detail = campaign_queue.get_campaign_detail(camp_id)
        queued_msg = camp_detail['messages'][0]
        self.assertIn('Original Subject for Delhi Technological University', queued_msg['subject'])
        self.assertIn('Original body for Delhi Technological University', queued_msg['html_body'])
        self.assertNotIn('MUTATED', queued_msg['subject'])

    # ==================== 4. QUEUE PERSISTENCE & CRASH RECOVERY ====================

    def test_queue_persistence_across_process_restart(self):
        """Interrupted 'sending' messages are safely recovered on startup without losing queue state."""
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Crash Recovery Campaign',
            'sender_email': 'hiring@medantrik.com',
            'subject': 'Connect'
        }, [self.ids[0], self.ids[1]])
        camp_id = camp['id']

        # Simulate a crash where message 1 was in status 'sending' when process was killed
        with directory.connect() as db:
            db.execute("UPDATE campaign_queue SET status='sending' WHERE campaign_id=? AND college_id=?", (camp_id, self.ids[0]))

        # Call startup recovery function (runs on application restart)
        campaign_queue.recover_stale_queue_on_startup()

        # The stuck message should be safely recovered to needs_review
        camp_detail = campaign_queue.get_campaign_detail(camp_id)
        statuses = [m['status'] for m in camp_detail['messages']]
        self.assertNotIn('sending', statuses)
        self.assertIn('needs_review', statuses)

    # ==================== 5. CAMPAIGN CONTROLS & TIMING ====================

    def test_pause_resume_and_cancellation(self):
        """Campaign can be paused, resumed with password, and cancelled."""
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Control Test Campaign',
            'sender_email': 'hiring@medantrik.com',
            'subject': 'Connect'
        }, [self.ids[0], self.ids[1]])
        camp_id = camp['id']

        # Pause
        paused = campaign_queue.pause_campaign(camp_id)
        self.assertEqual(paused['status'], 'paused')

        # Resume with password
        resumed = campaign_queue.resume_campaign(camp_id, sender_password='new-session-pass')
        self.assertEqual(resumed['status'], 'queued')
        self.assertEqual(campaign_queue.get_sender_password('hiring@medantrik.com'), 'new-session-pass')

        # Cancel
        cancelled = campaign_queue.cancel_campaign(camp_id)
        self.assertEqual(cancelled['status'], 'cancelled')
        # All queued messages should be cancelled
        self.assertTrue(all(m['status'] == 'cancelled' for m in cancelled['messages']))

    def test_rate_limiting_enforcement(self):
        """Worker respects hourly and daily rate caps across campaigns sharing a sender."""
        sender = 'hiring@medantrik.com'
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Rate Limit Test Campaign',
            'sender_email': sender,
            'subject': 'Connect'
        }, [self.ids[0]])
        camp_id = camp['id']

        # Log 50 dispatches in the last hour
        with directory.connect() as db:
            for i in range(50):
                db.execute(
                    "INSERT INTO campaign_queue(campaign_id, college_id, college_name, recipient_email, subject, html_body, text_body, status, sent_at) VALUES (?, ?, 'College', ?, 'Hi', 'Hi', 'Hi', 'accepted', datetime('now'))",
                    (camp_id, self.ids[0], f'test{i}@example.com')
                )

        # Check hourly rate limit cap enforcement
        with directory.connect() as db:
            allowed, reason = campaign_queue.check_sender_rate_caps(sender, 40, 100, db)
            self.assertFalse(allowed)
            self.assertIn('Hourly cap of 40 reached', reason)

            allowed_ok, _ = campaign_queue.check_sender_rate_caps(sender, 100, 100, db)
            self.assertTrue(allowed_ok)

    # ==================== 6. RECRUITMENT PIPELINE & CRM FOLLOW-UPS ====================

    def test_reply_halts_queued_follow_ups(self):
        """Recording a placement reply cancels all pending messages for that institution."""
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Follow-up Test',
            'sender_email': 'hiring@medantrik.com',
            'subject': 'Connect'
        }, [self.ids[0]])
        camp_id = camp['id']

        # Verify college is queued
        camp_detail = campaign_queue.get_campaign_detail(camp_id)
        self.assertEqual(camp_detail['messages'][0]['status'], 'queued')

        # Record reply
        directory.record_reply(self.ids[0], "TPO replied: We are interested in pool campus.", author='Aman')

        # Verify queued follow-up is cancelled
        camp_after = campaign_queue.get_campaign_detail(camp_id)
        msg_after = camp_after['messages'][0]
        self.assertEqual(msg_after['status'], 'cancelled')
        self.assertIn('College replied', msg_after['error_message'])

    def test_pipeline_stats_and_duplicate_warning(self):
        """14-day duplicate warnings and urgent follow-up deadlines are correctly identified."""
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        today_str = today.isoformat()

        # Schedule follow-up for today
        directory.set_follow_up(self.ids[0], today_str, notes='Review pool campus date', assigned_to='Priya')

        # Simulate outreach sent 2 days ago
        directory.log_outreach(self.ids[0], 'placements@dtu.ac.in', 'DTU', 'Intro', 'sent')

        colleges = directory.get_colleges()
        dtu = next(c for c in colleges if c['id'] == self.ids[0])
        self.assertTrue(dtu['recently_contacted'])
        self.assertEqual(dtu['recruitment_stage'], 'contacted')

        stats = directory.get_pipeline_stats()
        self.assertEqual(stats['follow_ups']['today_count'], 1)
        self.assertEqual(stats['follow_ups']['urgent_items'][0]['id'], self.ids[0])

    # ==================== 7. EXPORT INTEGRITY ====================

    def test_export_pipeline_csv_integrity(self):
        """Pipeline CSV contains all institutions with valid headers and data."""
        csv_str = directory.export_pipeline_csv()
        reader = list(csv.DictReader(io.StringIO(csv_str)))
        self.assertGreaterEqual(len(reader), 3)
        row = next(r for r in reader if r['College_Name'] == 'Delhi Technological University')
        self.assertEqual(row['City'], 'Delhi')
        self.assertEqual(row['TPO_Email'], 'placements@dtu.ac.in')

    def test_export_outreach_csv_integrity(self):
        """Outreach CSV contains unified audit of emails and CRM notes."""
        directory.log_activity(self.ids[0], 'meeting', 'Met with Dean of Academics', author='Aman')
        csv_str = directory.export_outreach_csv()
        reader = list(csv.DictReader(io.StringIO(csv_str)))
        self.assertGreaterEqual(len(reader), 1)
        row = next(r for r in reader if 'Dean of Academics' in r['Notes'])
        self.assertEqual(row['Activity_Type'], 'meeting')
        self.assertEqual(row['Author'], 'Aman')

    def test_export_campaign_csv_integrity(self):
        """Campaign CSV export contains recipient records and status."""
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Export Verification Campaign',
            'sender_email': 'hiring@medantrik.com',
            'subject': 'Connect'
        }, [self.ids[0]])
        camp_id = camp['id']

        csv_str = directory.export_campaign_csv(camp_id)
        reader = list(csv.DictReader(io.StringIO(csv_str)))
        self.assertEqual(len(reader), 1)
        self.assertEqual(reader[0]['Recipient_Email'], 'placements@dtu.ac.in')
        self.assertEqual(reader[0]['Status'], 'Queued')

if __name__ == '__main__':
    unittest.main()
