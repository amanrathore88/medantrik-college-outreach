import os
import json
import csv
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import directory
import campaign_queue

class TestTrackingFollowups(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / 'test_dir.sqlite3'
        self.orig_db = directory.DB_PATH
        directory.DB_PATH = self.db_path
        directory.initialize()
        campaign_queue.initialize_queue()

        # Seed test college
        self.college_data = {
            'College_Name': 'Apex Institute of Technology',
            'City': 'Noida',
            'District': 'Gautam Buddha Nagar',
            'Location': 'Sector 62, Noida',
            'Campus': 'Main Campus',
            'Type': 'Engineering & Technology',
            'TPO_Email': 'placements@apex.edu.in',
            'contact_type': 'placement',
            'Contact_Person': 'Dr. Rajesh Sharma',
            'Phone': '0120-1234567',
            'verification_status': 'verified',
            'checked_on': '2026-10-16',
            'source_url': 'https://apex.edu.in/placements'
        }
        res = directory.save_record(self.college_data)
        self.college_id = res['id']

    def tearDown(self):
        directory.DB_PATH = self.orig_db
        self.tmp.cleanup()

    def test_default_recruitment_stage(self):
        """Newly created colleges should default to not_contacted."""
        colleges = directory.get_colleges()
        matching = next(c for c in colleges if c['id'] == self.college_id)
        self.assertEqual(matching.get('recruitment_stage'), 'not_contacted')
        self.assertTrue(matching['sendable'])

    def test_update_pipeline_stage(self):
        """Recruitment stage can be updated and logged to activity timeline."""
        saved = directory.update_pipeline_stage(
            self.college_id,
            'meeting_arranged',
            notes='Meeting arranged with Dean on Thursday 3 PM',
            assigned_to='Priya Verma'
        )
        self.assertEqual(saved['recruitment_stage'], 'meeting_arranged')

        # Verify in get_colleges
        colleges = directory.get_colleges()
        matching = next(c for c in colleges if c['id'] == self.college_id)
        self.assertEqual(matching['recruitment_stage'], 'meeting_arranged')
        self.assertEqual(matching.get('assigned_to'), 'Priya Verma')

        # Verify activity timeline
        acts = directory.get_college_activities(self.college_id)
        self.assertTrue(any('Meeting arranged with Dean' in a['notes'] for a in acts))
        self.assertTrue(any(a['type'] == 'stage_change' for a in acts))

    def test_invalid_stage_rejected(self):
        """Invalid pipeline stages must raise ValueError."""
        with self.assertRaises(ValueError):
            directory.update_pipeline_stage(self.college_id, 'invalid_stage')

    def test_declined_and_partnership_active_disable_sendable(self):
        """Moving to declined or partnership_active removes institution from sendable pool."""
        directory.update_pipeline_stage(self.college_id, 'declined')
        matching = next(c for c in directory.get_colleges() if c['id'] == self.college_id)
        self.assertFalse(matching['sendable'])

        directory.update_pipeline_stage(self.college_id, 'partnership_active')
        matching = next(c for c in directory.get_colleges() if c['id'] == self.college_id)
        self.assertFalse(matching['sendable'])

        # Resetting to contacted re-enables sendable if verified
        directory.update_pipeline_stage(self.college_id, 'contacted')
        matching = next(c for c in directory.get_colleges() if c['id'] == self.college_id)
        self.assertTrue(matching['sendable'])

    def test_record_reply_and_halt_followups(self):
        """Recording a reply updates stage and halts any pending queued messages."""
        # Create a campaign and queue a message for this college
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Test Fall Outreach',
            'sender_email': 'hiring@medantrik.com',
            'subject': 'Medantrik Campus Hiring'
        }, [self.college_id])
        camp_id = camp['id']

        # Verify message is queued
        with directory.connect() as db:
            q_row = db.execute('SELECT * FROM campaign_queue WHERE campaign_id=? AND college_id=?', (camp_id, self.college_id)).fetchone()
            self.assertEqual(q_row['status'], 'queued')

        # Now record an official reply from the placement cell
        directory.record_reply(
            self.college_id,
            'Placement director agreed to host campus drive for 2027 batch. Requested JD.',
            author='Amit Roy',
            next_stage='replied'
        )

        # Check college status
        matching = next(c for c in directory.get_colleges() if c['id'] == self.college_id)
        self.assertEqual(matching['recruitment_stage'], 'replied')
        self.assertIn('agreed to host campus drive', matching['last_reply_notes'])

        # Check that queued follow-up was cancelled
        with directory.connect() as db:
            q_row = db.execute('SELECT * FROM campaign_queue WHERE campaign_id=? AND college_id=?', (camp_id, self.college_id)).fetchone()
            self.assertEqual(q_row['status'], 'cancelled')
            self.assertIn('College replied', q_row['error_message'])

    def test_follow_up_deadlines_and_pipeline_stats(self):
        """Follow-up scheduling tracks overdue, today, and upcoming dates in pipeline stats."""
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        yesterday_str = (today - timedelta(days=1)).isoformat()
        today_str = today.isoformat()
        future_str = (today + timedelta(days=3)).isoformat()

        # Set follow-up to yesterday (overdue)
        directory.set_follow_up(self.college_id, yesterday_str, notes='Urgent follow-up call', assigned_to='Aman')
        stats = directory.get_pipeline_stats()
        self.assertEqual(stats['follow_ups']['overdue_count'], 1)
        self.assertEqual(stats['follow_ups']['today_count'], 0)
        self.assertEqual(len(stats['follow_ups']['urgent_items']), 1)
        self.assertEqual(stats['follow_ups']['urgent_items'][0]['id'], self.college_id)

        # Change to today
        directory.set_follow_up(self.college_id, today_str, notes='Call placement head')
        stats = directory.get_pipeline_stats()
        self.assertEqual(stats['follow_ups']['overdue_count'], 0)
        self.assertEqual(stats['follow_ups']['today_count'], 1)

        # Change to future
        directory.set_follow_up(self.college_id, future_str)
        stats = directory.get_pipeline_stats()
        self.assertEqual(stats['follow_ups']['today_count'], 0)
        self.assertEqual(stats['follow_ups']['upcoming_count'], 1)

    def test_invalid_follow_up_date_format(self):
        """Invalid follow up dates should raise ValueError."""
        with self.assertRaises(ValueError):
            directory.set_follow_up(self.college_id, '16-10-2026')
        with self.assertRaises(ValueError):
            directory.set_follow_up(self.college_id, 'invalid')

    def test_log_activity_and_timeline(self):
        """Internal notes, call summaries, and emails merge into a unified timeline."""
        directory.log_activity(self.college_id, 'call', 'Called Placement Officer. He asked for deck.', author='Priya')
        directory.log_activity(self.college_id, 'note', 'Reviewed website syllabus. Good AI/ML labs.', author='Dev')
        directory.log_outreach(self.college_id, 'placements@apex.edu.in', 'Apex Institute', 'Introduction', 'sent')

        activities = directory.get_college_activities(self.college_id)
        self.assertGreaterEqual(len(activities), 3)

        types = [a['type'] for a in activities]
        self.assertIn('call', types)
        self.assertIn('note', types)
        self.assertIn('email_sent', types)

    def test_recently_contacted_warning(self):
        """Colleges contacted within 14 days have recently_contacted flag set to True."""
        colleges = directory.get_colleges()
        matching = next(c for c in colleges if c['id'] == self.college_id)
        self.assertFalse(matching.get('recently_contacted', False))

        # Log outreach
        directory.log_outreach(self.college_id, 'placements@apex.edu.in', 'Apex Institute', 'Intro', 'sent')

        colleges_after = directory.get_colleges()
        matching_after = next(c for c in colleges_after if c['id'] == self.college_id)
        self.assertTrue(matching_after['recently_contacted'])
        self.assertEqual(matching_after['recruitment_stage'], 'contacted')

    def test_export_pipeline_csv(self):
        """Pipeline CSV export contains header and college records with stages."""
        directory.update_pipeline_stage(self.college_id, 'contacted')
        directory.set_follow_up(self.college_id, '2026-10-20', notes='Follow up after event', assigned_to='Aman')

        csv_text = directory.export_pipeline_csv()
        reader = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertGreaterEqual(len(reader), 1)

        row = next(r for r in reader if r['College_Name'] == 'Apex Institute of Technology')
        self.assertEqual(row['Recruitment_Stage'], 'Contacted')
        self.assertEqual(row['Follow_Up_Date'], '2026-10-20')
        self.assertEqual(row['Assigned_To'], 'Aman')

    def test_export_outreach_csv(self):
        """Outreach CSV export contains logged notes, calls, and email activities."""
        directory.log_activity(self.college_id, 'call', 'Detailed telephone screening with TPO', author='Aman')
        csv_text = directory.export_outreach_csv()
        reader = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertGreaterEqual(len(reader), 1)

        row = next(r for r in reader if 'screening with TPO' in r['Notes'])
        self.assertEqual(row['Activity_Type'], 'call')
        self.assertEqual(row['Author'], 'Aman')

    def test_export_campaign_csv(self):
        """Campaign CSV export generates delivery status per recipient."""
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Autumn 2026 Drive',
            'sender_email': 'hiring@medantrik.com',
            'subject': 'Campus Hiring at Medantrik'
        }, [self.college_id])
        camp_id = camp['id']

        csv_text = directory.export_campaign_csv(camp_id)
        reader = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(len(reader), 1)
        self.assertEqual(reader[0]['Recipient_Email'], 'placements@apex.edu.in')
        self.assertEqual(reader[0]['Status'], 'Queued')

if __name__ == '__main__':
    unittest.main()
