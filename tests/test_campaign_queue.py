"""Comprehensive unit tests for Phase 5: Persistent, staggered campaign sending, queue, rate caps, and scheduling."""
import io
import json
import unittest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from email.message import Message

import dashboard
import directory
import templates
import campaign_queue

class CampaignQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / 'test_queue.sqlite3'
        self.dir_patch = patch('directory.DB_PATH', self.db_path)
        self.dir_patch.start()
        self.addCleanup(self.dir_patch.stop)
        campaign_queue._SESSION_CREDENTIALS.clear()

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

    def create_sample_colleges(self):
        directory.initialize()
        records = [
            {'College_Name': 'Alpha Engineering College', 'City': 'Delhi', 'Location': 'Rohini, Delhi', 'TPO_Email': 'tpo@alpha.edu', 'contact_type': 'placement', 'verification_status': 'verified', 'source_url': 'https://alpha.edu/tpo', 'checked_on': '2026-10-10'},
            {'College_Name': 'Beta Institute of Tech', 'City': 'Noida', 'Location': 'Sector 62, Noida', 'TPO_Email': 'placement@beta.ac.in', 'contact_type': 'placement', 'verification_status': 'verified', 'source_url': 'https://beta.ac.in/placements', 'checked_on': '2026-10-11'},
            {'College_Name': 'Gamma University', 'City': 'Gurugram', 'Location': 'Sohna Road', 'TPO_Email': 'corporate@gamma.edu', 'contact_type': 'placement', 'verification_status': 'verified', 'source_url': 'https://gamma.edu/placement', 'checked_on': '2026-10-12'}
        ]
        ids = []
        for r in records:
            res = directory.save_record(r)
            ids.append(res['id'])
        return ids

    def test_create_campaign_and_queue_deduplication(self):
        col_ids = self.create_sample_colleges()
        # Request with duplicate ID
        config = {
            'name': 'Autumn Tech Placement',
            'sender_email': 'hiring@medantrik.com',
            'interval_seconds': 3,
            'hourly_cap': 40,
            'daily_cap': 150
        }
        camp = campaign_queue.create_staggered_campaign(config, [col_ids[0], col_ids[1], col_ids[0]], sender_password='dummy-app-pass')
        self.assertEqual(camp['name'], 'Autumn Tech Placement')
        self.assertEqual(camp['total_recipients'], 2)  # Duplicate col_ids[0] was deduplicated!
        self.assertEqual(camp['counts']['queued'], 2)
        self.assertEqual(camp['counts']['total'], 2)
        self.assertTrue(bool(camp['template_snapshot']))

        # Verify password in session
        self.assertEqual(campaign_queue.get_sender_password('hiring@medantrik.com'), 'dummy-app-pass')

    def test_timing_and_schedule_rules(self):
        col_ids = self.create_sample_colleges()
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Schedule Test',
            'sender_email': 'hiring@medantrik.com',
            'working_days_only': True,
            'sending_hours_start': '09:00',
            'sending_hours_end': '18:00'
        }, [col_ids[0]])

        ist = campaign_queue.get_ist_timezone()

        # 1. Tuesday at 11:30 AM IST -> Should be permitted
        tuesday_noon = datetime(2026, 10, 13, 11, 30, tzinfo=ist)
        allowed, reason = campaign_queue.can_dispatch_campaign_now(camp, tuesday_noon)
        self.assertTrue(allowed)

        # 2. Sunday at 11:30 AM IST -> Should be blocked (working_days_only)
        sunday_noon = datetime(2026, 10, 18, 11, 30, tzinfo=ist)
        allowed, reason = campaign_queue.can_dispatch_campaign_now(camp, sunday_noon)
        self.assertFalse(allowed)
        self.assertIn('Outside working days', reason)

        # 3. Tuesday at 07:30 AM IST -> Should be blocked (outside sending hours)
        tuesday_early = datetime(2026, 10, 13, 7, 30, tzinfo=ist)
        allowed, reason = campaign_queue.can_dispatch_campaign_now(camp, tuesday_early)
        self.assertFalse(allowed)
        self.assertIn('Outside business sending window', reason)

        # 4. Tuesday at 21:00 IST -> Should be blocked
        tuesday_night = datetime(2026, 10, 13, 21, 0, tzinfo=ist)
        allowed, reason = campaign_queue.can_dispatch_campaign_now(camp, tuesday_night)
        self.assertFalse(allowed)
        self.assertIn('Outside business sending window', reason)

    def test_rate_caps_enforcement(self):
        col_ids = self.create_sample_colleges()
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Cap Test',
            'sender_email': 'sender@example.com',
            'hourly_cap': 2,
            'daily_cap': 5
        }, col_ids)

        with directory.connect() as db:
            # Under cap: 0 sent
            allowed, _ = campaign_queue.check_sender_rate_caps('sender@example.com', 2, 5, db)
            self.assertTrue(allowed)

            # Simulate 2 sends in the last 10 minutes
            now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            db.execute("UPDATE campaign_queue SET status='accepted', sent_at=? WHERE id IN (SELECT id FROM campaign_queue LIMIT 2)", (now_str,))

            # Hourly cap reached
            allowed, reason = campaign_queue.check_sender_rate_caps('sender@example.com', 2, 5, db)
            self.assertFalse(allowed)
            self.assertIn('Hourly cap', reason)

    def test_pause_resume_cancel_campaign(self):
        col_ids = self.create_sample_colleges()
        camp = campaign_queue.create_staggered_campaign({
            'name': 'State Test',
            'sender_email': 'hiring@example.com'
        }, col_ids)
        c_id = camp['id']
        self.assertEqual(camp['status'], 'queued')

        # Pause
        paused = campaign_queue.pause_campaign(c_id)
        self.assertEqual(paused['status'], 'paused')

        # Worker should not dispatch while paused
        with directory.connect() as db:
            allowed, _ = campaign_queue.can_dispatch_campaign_now(paused)
            self.assertFalse(allowed)

        # Resume
        resumed = campaign_queue.resume_campaign(c_id, 'app-password')
        self.assertEqual(resumed['status'], 'queued')

        # Cancel
        cancelled = campaign_queue.cancel_campaign(c_id)
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertEqual(cancelled['counts']['cancelled'], len(col_ids))

    def test_single_message_dispatch_success_and_permanent_failure(self):
        col_ids = self.create_sample_colleges()
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Dispatch Test',
            'sender_email': 'hiring@example.com'
        }, [col_ids[0]], sender_password='pass')
        msg_id = camp['messages'][0]['id']

        # 1. Successful send
        with patch('campaign_queue.send_mail') as mock_send:
            outcome, err = campaign_queue.dispatch_single_queue_message(msg_id)
            self.assertEqual(outcome, 'accepted')
            self.assertIsNone(err)
            mock_send.assert_called_once()

        updated_camp = campaign_queue.get_campaign_detail(camp['id'])
        self.assertEqual(updated_camp['successful_count'], 1)
        self.assertEqual(updated_camp['counts']['accepted'], 1)

        # 2. Permanent Failure (Recipient Rejected 550)
        camp2 = campaign_queue.create_staggered_campaign({
            'name': 'Failure Test',
            'sender_email': 'hiring@example.com'
        }, [col_ids[1]], sender_password='pass')
        msg2_id = camp2['messages'][0]['id']

        with patch('campaign_queue.send_mail', side_effect=ValueError('The mail server rejected this recipient.')):
            outcome, err = campaign_queue.dispatch_single_queue_message(msg2_id)
            self.assertEqual(outcome, 'failed')
            self.assertIn('rejected', err)

        updated_camp2 = campaign_queue.get_campaign_detail(camp2['id'])
        self.assertEqual(updated_camp2['failed_count'], 1)
        self.assertEqual(updated_camp2['counts']['failed'], 1)
        # Should not schedule retry for permanent address failure
        self.assertEqual(updated_camp2['messages'][0]['failure_type'], 'permanent')

    def test_temporary_failure_and_retry_backoff(self):
        col_ids = self.create_sample_colleges()
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Retry Test',
            'sender_email': 'hiring@example.com'
        }, [col_ids[0]], sender_password='pass')
        msg_id = camp['messages'][0]['id']

        # Simulate temporary network error
        with patch('campaign_queue.send_mail', side_effect=ValueError('Temporary transport connection dropped.')):
            outcome, err = campaign_queue.dispatch_single_queue_message(msg_id)
            self.assertEqual(outcome, 'retry_scheduled')

        detail = campaign_queue.get_campaign_detail(camp['id'])
        msg = detail['messages'][0]
        self.assertEqual(msg['status'], 'queued')
        self.assertEqual(msg['retry_count'], 1)
        self.assertEqual(msg['failure_type'], 'temporary')

    def test_safe_restart_recovery(self):
        col_ids = self.create_sample_colleges()
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Crash Recovery Test',
            'sender_email': 'hiring@example.com'
        }, [col_ids[0]])

        # Simulate a crash leaving message in 'sending' and campaign in 'sending'
        with directory.connect() as db:
            db.execute("UPDATE campaign_queue SET status='sending' WHERE campaign_id=?", (camp['id'],))
            db.execute("UPDATE campaigns SET status='sending' WHERE id=?", (camp['id'],))

        # Run recovery
        campaign_queue.recover_stale_queue_on_startup()

        detail = campaign_queue.get_campaign_detail(camp['id'])
        self.assertEqual(detail['status'], 'paused')
        self.assertEqual(detail['messages'][0]['status'], 'needs_review')
        self.assertIn('restart', detail['messages'][0]['error_message'].lower())

    def test_campaign_rest_api_lifecycle(self):
        col_ids = self.create_sample_colleges()

        # 1. Create campaign via API
        handler = self.request('/api/campaigns/create', {
            'name': 'API Campaign Staggered',
            'sender_email': 'hiring@example.com',
            'sender_password': 'app-password',
            'college_ids': [col_ids[0], col_ids[1]],
            'interval_seconds': 2,
            'hourly_cap': 30
        })
        handler.do_POST()
        created = handler.reply.call_args.args[0]
        c_id = created['id']
        self.assertEqual(created['total_recipients'], 2)

        # 2. GET /api/campaigns
        handler = self.request('/api/campaigns')
        handler.do_GET()
        c_list = handler.reply.call_args.args[0]
        self.assertTrue(any(c['id'] == c_id for c in c_list))

        # 3. GET /api/campaigns/detail?id=X
        handler = self.request(f'/api/campaigns/detail?id={c_id}')
        handler.do_GET()
        detail = handler.reply.call_args.args[0]
        self.assertEqual(detail['id'], c_id)
        self.assertEqual(len(detail['messages']), 2)

        # 4. POST /api/campaigns/pause
        handler = self.request('/api/campaigns/pause', {'id': c_id})
        handler.do_POST()
        paused = handler.reply.call_args.args[0]
        self.assertEqual(paused['status'], 'paused')

        # 5. POST /api/campaigns/resume
        handler = self.request('/api/campaigns/resume', {'id': c_id, 'sender_password': 'app-password'})
        handler.do_POST()
        resumed = handler.reply.call_args.args[0]
        self.assertEqual(resumed['status'], 'queued')

        # 6. GET /api/queue/status
        handler = self.request('/api/queue/status')
        handler.do_GET()
        q_stat = handler.reply.call_args.args[0]
        self.assertIn('queued_messages', q_stat)
        self.assertIn('sent_last_hour', q_stat)

        # 7. POST /api/campaigns/cancel
        handler = self.request('/api/campaigns/cancel', {'id': c_id})
        handler.do_POST()
        cancelled = handler.reply.call_args.args[0]
        self.assertEqual(cancelled['status'], 'cancelled')

    def test_queue_step_endpoint_and_credential_override(self):
        col_ids = self.create_sample_colleges()
        camp = campaign_queue.create_staggered_campaign({
            'name': 'Step Test',
            'sender_email': 'step@example.com',
            'sending_hours_start': '00:00',
            'sending_hours_end': '23:59'
        }, [col_ids[0]])

        # Queue step with password override
        with patch('campaign_queue.send_mail') as mock_send:
            handler = self.request('/api/queue/step', {'sender_password': 'override-pass'})
            handler.do_POST()
            res = handler.reply.call_args.args[0]
            self.assertEqual(res['status'], 'ok')
            self.assertTrue(res['acted'])
            mock_send.assert_called_once()

if __name__ == '__main__':
    unittest.main()
