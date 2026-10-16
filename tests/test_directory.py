import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import directory

class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch=patch('directory.DB_PATH',Path(self.temp.name)/'directory.sqlite3')
        self.patch.start();self.addCleanup(self.patch.stop)
        directory.initialize()

    def record(self,**changes):
        base = dict(College_Name='Example institution',City='Gurugram',Campus='',TPO_Email='office@example.edu',
                    contact_type='general',verification_status='verified',source_url='https://example.edu/contact',
                    checked_on=directory.today())
        base.update(changes)
        return base

    def test_migration_is_idempotent(self):
        self.assertEqual(len(directory.get_colleges()),25)
        directory.initialize()
        self.assertEqual(len(directory.get_colleges()),25)
        self.assertFalse(any(r['sendable'] for r in directory.get_colleges()))

    def test_persistence_alias_search_and_exact_area(self):
        row=directory.save_record(self.record())
        self.assertTrue(row['sendable'])
        self.assertEqual(directory.query_colleges(query='Gurgaon')['items'][0]['id'],row['id'])
        self.assertEqual(directory.query_colleges(city='Gurgaon')['total'],1)
        self.assertTrue(all(r['City']=='Noida' for r in directory.query_colleges(city='Noida')['items']))
        self.assertEqual(directory.query_colleges(page_size=1000)['page_size'],100)

    def test_verified_requires_evidence_and_safe_url(self):
        for field,value in [('source_url',''),('checked_on',''),('source_url','javascript:alert(1)'),('checked_on','2999-01-01'),('TPO_Email','bad\r\n@example.edu')]:
            record=self.record();record[field]=value
            with self.assertRaises(ValueError):directory.save_record(record)

    def test_edit_is_version_checked_and_audited(self):
        row=directory.save_record(self.record())
        updated=directory.save_record(dict(row,notes='reviewed',do_not_contact=True),row['id'],row['version'])
        self.assertFalse(updated['sendable'])
        self.assertEqual(len(directory.history(row['id'])),2)
        with self.assertRaises(ValueError):directory.save_record(row,row['id'],row['version'])

    def test_import_requires_review_and_does_not_trust_verified_flag(self):
        preview=directory.preview_import(json.dumps([self.record(),self.record()]))
        self.assertEqual(preview['add'],1);self.assertEqual(preview['duplicates'],1)
        self.assertEqual(len(directory.get_colleges()),25)
        self.assertEqual(directory.commit_import(preview['token'])['added'],1)
        row=directory.query_colleges(query='Example institution')['items'][0]
        self.assertEqual(row['verification_status'],'unverified');self.assertFalse(row['sendable'])
        with self.assertRaises(ValueError):directory.commit_import(preview['token'])

    def test_invalid_import_cannot_partially_commit(self):
        preview=directory.preview_import(json.dumps([self.record(),{'College_Name':'Outside','City':'Mumbai'}]))
        with self.assertRaises(ValueError):directory.commit_import(preview['token'])
        self.assertEqual(len(directory.get_colleges()),25)

    def test_expired_import_cannot_commit(self):
        preview=directory.preview_import(json.dumps([self.record()]))
        with directory.connect() as db:db.execute("UPDATE imports SET created=datetime('now','-2 hours')")
        with self.assertRaises(ValueError):directory.commit_import(preview['token'])

    def test_same_email_does_not_auto_merge_campuses(self):
        first=directory.save_record(self.record())
        second=directory.save_record(dict(self.record(),Campus='East'))
        self.assertNotEqual(first['id'],second['id'])
        self.assertTrue(any(p['first']==first['id'] and p['second']==second['id'] for p in directory.duplicates()))

    def test_merge_retains_audit_and_do_not_contact(self):
        first=directory.save_record(dict(self.record(),College_Name='Example college',do_not_contact=True))
        target=directory.save_record(self.record())
        merged=directory.merge_records(first['id'],target['id'],first['version'],target['version'])
        self.assertTrue(merged['do_not_contact'])
        self.assertFalse(merged['sendable'])
        self.assertIn('Example college',merged['Aliases'])
        self.assertEqual(len(directory.get_colleges()),26)
        self.assertTrue(any('merged source' in r['action'] for r in directory.history(target['id'])))

    def test_missing_email_and_coverage_are_honest(self):
        directory.save_record(dict(self.record(),TPO_Email='',verification_status='missing'))
        report=directory.coverage()
        self.assertFalse(report['coverage_complete'])
        self.assertEqual(report['inventory_date'], '2026-10-16')
        area=next(a for a in report['areas'] if a['area']=='Gurugram')
        self.assertEqual(area['missing'],1)
        self.assertEqual(area['sendable'],0)
        self.assertIn('contact_found', area)
        self.assertIn('reviewed', area)

    def test_coverage_tracks_all_five_areas(self):
        report = directory.coverage()
        area_names = [a['area'] for a in report['areas']]
        self.assertEqual(area_names, ['Delhi', 'Noida', 'Greater Noida', 'Ghaziabad', 'Gurugram'])

    def test_filter_by_contact_type_and_status(self):
        directory.save_record(self.record(College_Name='Placement Inst', contact_type='placement', verification_status='verified'))
        directory.save_record(self.record(College_Name='General Inst', contact_type='general', verification_status='verified'))
        directory.save_record(self.record(College_Name='Missing Inst', contact_type='unknown', verification_status='missing', TPO_Email=''))
        
        placements = directory.query_colleges(kind='placement', page_size=100)['items']
        self.assertTrue(any(r['College_Name'] == 'Placement Inst' for r in placements))
        self.assertTrue(all(r['contact_type'] == 'placement' for r in placements))
        
        generals = directory.query_colleges(kind='general', page_size=100)['items']
        self.assertTrue(any(r['College_Name'] == 'General Inst' for r in generals))
        
        missing = directory.query_colleges(status='missing', page_size=100)['items']
        self.assertTrue(any(r['College_Name'] == 'Missing Inst' for r in missing))
        self.assertTrue(all(r['verification_status'] == 'missing' for r in missing))

    def test_area_isolation_noida_and_greater_noida(self):
        directory.save_record(self.record(College_Name='Noida Campus', City='Noida'))
        directory.save_record(self.record(College_Name='Greater Noida Campus', City='Greater Noida'))
        
        noida = directory.query_colleges(city='Noida')
        gnoida = directory.query_colleges(city='Greater Noida')
        self.assertTrue(all(r['City'] == 'Noida' for r in noida['items']))
        self.assertTrue(all(r['City'] == 'Greater Noida' for r in gnoida['items']))
        self.assertTrue(any(r['College_Name'] == 'Noida Campus' for r in noida['items']))
        self.assertFalse(any(r['College_Name'] == 'Greater Noida Campus' for r in noida['items']))

    def test_query_discipline_filter(self):
        directory.save_record(self.record(College_Name='Engineering Campus', Type='Engineering & Technology'))
        directory.save_record(self.record(College_Name='Business School', Type='Autonomous Management Institute (PGDM)'))
        
        eng = directory.query_colleges(discipline='engineering', page_size=100)['items']
        mgmt = directory.query_colleges(discipline='management', page_size=100)['items']
        self.assertTrue(any(r['College_Name'] == 'Engineering Campus' for r in eng))
        self.assertFalse(any(r['College_Name'] == 'Business School' for r in eng))
        self.assertTrue(any(r['College_Name'] == 'Business School' for r in mgmt))

    def test_overview_and_outreach_tracking(self):
        row = directory.save_record(self.record(College_Name='Outreach Target'))
        directory.log_outreach(row['id'], row['TPO_Email'], row['College_Name'], 'Subject 1', 'sent')
        directory.log_outreach(row['id'], row['TPO_Email'], row['College_Name'], 'Subject 2', 'failed', 'Timeout')
        
        history = directory.get_outreach_history(row['id'])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['status'], 'failed')
        self.assertEqual(history[1]['status'], 'sent')
        
        c_id = directory.log_campaign('Batch 1', 'sender@example.org', 'Test Subject', 10, 9, 1, 'partial')
        self.assertGreater(c_id, 0)
        campaigns = directory.get_campaigns()
        self.assertTrue(any(c['name'] == 'Batch 1' for c in campaigns))
        
        overview = directory.get_overview_stats()
        self.assertIn('total', overview)
        self.assertIn('sendable', overview)
        self.assertIn('coverage', overview)
        self.assertTrue(any(f['error_message'] == 'Timeout' for f in overview['failures']))

    def test_college_detail_retrieval(self):
        row = directory.save_record(self.record(College_Name='Detail Test Institute'))
        directory.log_outreach(row['id'], row['TPO_Email'], row['College_Name'], 'Outreach Msg', 'sent')
        detail = directory.get_college_detail(row['id'])
        self.assertEqual(detail['record']['College_Name'], 'Detail Test Institute')
        self.assertEqual(len(detail['outreach']), 1)
        self.assertGreaterEqual(len(detail['history']), 1)

if __name__=='__main__':unittest.main()
