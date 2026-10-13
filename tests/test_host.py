"""Invented host logs exercise task read authority; never actual AI evidence."""
import copy
from contextlib import closing
from datetime import datetime, timedelta
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import core as c, evidence, host
import test_review as fixture

PACKAGE = Path(__file__).resolve().parents[1]
SCRATCH = PACKAGE / 'tests/.scratch/host'
AUTHOR_HASH, REVIEW_HASH = 'a' * 64, 'b' * 64


class HostTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='synthetic-', dir=SCRATCH)
        self.base = Path(self.temporary.name)
        self.home = self.base / '宿主 带空格'
        self.days = self.home / 'sessions' / datetime.now().astimezone().strftime('%Y/%m/%d')
        self.days.mkdir(parents=True)
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(self.home),
            'CODEX_SESSION_ID': fixture.ROOT, 'CODEX_THREAD_ID': fixture.ROOT})
        self.env.start()
        self.addCleanup(self.env.stop)
        author = fixture.HostFixture(self.base/'author', 'AUTHOR', AUTHOR_HASH, REVIEW_HASH)
        reviewer = fixture.HostFixture(self.base/'reviewer', 'REVIEWER', REVIEW_HASH, 'c' * 64)
        self.parent = self.name(fixture.ROOT)
        self.author = self.name(fixture.AUTHOR)
        self.reviewer = self.name(fixture.REVIEWER)
        rows = [json.loads(line) for line in author.parent.read_bytes().splitlines()]
        rows.extend(json.loads(line) for line in reviewer.parent.read_bytes().splitlines()[2:])
        self.write_records(self.parent, rows)
        self.author.write_bytes(author.child.read_bytes())
        self.reviewer.write_bytes(reviewer.child.read_bytes())
        for identifier,path in ((fixture.ROOT,self.parent),(fixture.AUTHOR,self.author),(fixture.REVIEWER,self.reviewer)):
            self.index(identifier,path)
        self.run = self.base / '全新 文献库' / '.work/runs/synthetic-run'
        self.run.mkdir(parents=True)
        self.startup = {'root': fixture.ROOT, 'turn': fixture.TURN, 'allowed_log_paths': [str(self.parent)]}
        c.write_json_new(self.run/'STARTUP_CONTEXT.json', self.startup)
        c.write_json_new(self.run/'STARTUP_PROBE.json', {'fixture_only': True})
        c.write_json_new(self.run/'STARTUP_COMMIT.json', {'files': [c.ref(self.run,self.run/name)
            for name in ('STARTUP_CONTEXT.json','STARTUP_PROBE.json')]})
        self.task = patch.object(host, '_task', side_effect=lambda package,run,role:
            '/root/' + role.lower() + '_' + (AUTHOR_HASH if role=='AUTHOR' else REVIEW_HASH))
        self.task.start()
        self.addCleanup(self.task.stop)

    def tearDown(self):
        if not self.base.resolve().is_relative_to(SCRATCH.resolve()) or not self.base.name.startswith('synthetic-'):
            raise RuntimeError('HOST_TEST_CLEANUP_OUTSIDE_OWNED_SCRATCH')
        self.temporary.cleanup()

    def name(self, identifier, directory=None):
        return (directory or self.days) / ('rollout-' + datetime.now().astimezone().strftime('%Y-%m-%dT%H-%M-%S') + '-' + identifier + '.jsonl')

    def index(self,identifier,path,mode='legacy'):
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS threads (id TEXT PRIMARY KEY,rollout_path TEXT NOT NULL,history_mode TEXT NOT NULL DEFAULT 'legacy')")
            connection.execute('INSERT OR REPLACE INTO threads VALUES (?,?,?)',(identifier,str(path),mode))

    def write_records(self, path, rows):
        path.write_bytes(b''.join(c.encode(row).replace(b'\n', b'') + b'\n' for row in rows))

    def mutate(self, path, mutate):
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        mutate(rows)
        self.write_records(path, rows)

    def capture(self):
        with patch.dict(os.environ, {'CODEX_THREAD_ID': fixture.AUTHOR}):
            return host.capture_current(PACKAGE, self.run, 'AUTHOR')

    def test_current_context_uses_environment_and_current_raw_turn(self):
        context, proof = host.create_context(PACKAGE)
        self.assertEqual(context, self.startup)
        self.assertEqual(proof['identity']['model'], 'invented-test-model')
        self.assertEqual(proof['identity']['effort'], 'high')
        self.assertEqual(len(proof['identity']['verified_record_refs']), 2)

    def test_read_authority_never_comes_from_capture_or_document_path(self):
        outside = self.base/'unrelated.jsonl'
        outside.write_bytes(b'PRIVATE_UNRELATED_PLACEHOLDER_NOT_A_LOG\n')
        with self.assertRaisesRegex(ValueError, 'DAY_DIRECTORY_OUTSIDE_CODEX_SESSIONS'):
            host.create_context(PACKAGE, parent_log=outside)
        self.assertEqual(outside.read_bytes(), b'PRIVATE_UNRELATED_PLACEHOLDER_NOT_A_LOG\n')

    def test_current_child_capture_reuses_raw_verifier_and_exports_no_body(self):
        capture, identity = self.capture()
        self.assertEqual(identity['task_path'], '/root/author_' + AUTHOR_HASH)
        self.assertEqual(identity['child_thread_id'], fixture.AUTHOR)
        self.assertEqual(identity['verified_record_count'], 7)
        rendered = c.encode(capture)
        self.assertNotIn(b'Invented encrypted-content placeholder', rendered)
        self.assertNotIn(b'Invented unit-test dispatch', rendered)
        self.assertNotIn(b'AUTHOR_OUTPUT_SHA256=', rendered)
        self.assertEqual(evidence.verify_identity(capture,fixture.ROOT,fixture.TURN,
            '/root/author_'+AUTHOR_HASH,[self.parent,self.author]),identity)

    def test_wrong_current_child_role_is_rejected_before_body_read(self):
        with patch.dict(os.environ, {'CODEX_THREAD_ID': fixture.REVIEWER}):
            with self.assertRaisesRegex(ValueError, 'HOST_CHILD_CURRENT_TASK_MISMATCH'):
                host.capture_current(PACKAGE,self.run,'AUTHOR')

    def test_old_child_root_turn_is_rejected(self):
        self.mutate(self.author,lambda rows:rows[1]['payload'].update(root_turn_id='20000000-0000-0000-0000-000000000001'))
        with self.assertRaisesRegex(ValueError,'ROOT_TURN_MISMATCH'):
            self.capture()

    def test_new_parent_turn_invalidates_old_run(self):
        newer = '20000000-0000-0000-0000-000000000001'
        def append(rows):
            record = copy.deepcopy(rows[1])
            record['payload'].update(turn_id=newer,root_turn_id=newer)
            rows.append(record)
        self.mutate(self.parent,append)
        context,_ = host.create_context(PACKAGE)
        self.assertEqual(context['turn'],newer)
        with self.assertRaisesRegex(ValueError,'HOST_CURRENT_TURN_MISMATCH'):
            self.capture()

    def test_unconsumed_older_turn_schema_does_not_replace_current_evidence(self):
        def insert(rows):
            rows.insert(1,{'type':'turn_context','timestamp':'2001-01-01T00:00:00Z',
                'payload':{'turn_id':'20000000-0000-0000-0000-000000000001','obsolete_test_schema':True}})
        self.mutate(self.parent,insert)
        self.assertEqual(host.create_context(PACKAGE)[0],self.startup)
        self.assertEqual(self.capture()[1]['root_turn_id'],fixture.TURN)

    def test_forged_capture_path_does_not_extend_allowlist(self):
        capture,_ = self.capture()
        capture['child']['source_path'] = str(self.base/'unrelated.jsonl')
        with self.assertRaisesRegex(ValueError,'SOURCE_PATH_NOT_ALLOWLISTED'):
            evidence.verify_identity(capture,fixture.ROOT,fixture.TURN,
                '/root/author_'+AUTHOR_HASH,[self.parent,self.author])

    def test_forged_capture_raw_hash_is_rejected(self):
        capture,_ = self.capture()
        capture['child']['turn_context']['ref']['raw_record_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'RAW_RECORD_HASH_MISMATCH'):
            evidence.verify_identity(capture,fixture.ROOT,fixture.TURN,
                '/root/author_'+AUTHOR_HASH,[self.parent,self.author])

    def test_wrong_thread_metadata_is_rejected(self):
        self.mutate(self.author,lambda rows:rows[0]['payload'].update(id=fixture.REVIEWER))
        with self.assertRaisesRegex(ValueError,'HOST_LOG_IDENTITY_MISMATCH'):
            self.capture()

    def test_wrong_model_projection_is_rejected(self):
        self.mutate(self.author,lambda rows:rows[1]['payload'].update(model='different-local-model'))
        with self.assertRaisesRegex(ValueError,'MODEL_EFFORT_DISAGREEMENT'):
            self.capture()

    def test_coordinator_selects_two_actual_role_ids_independently(self):
        context,proof=host.create_context(PACKAGE,run=self.run,
            author_thread=fixture.AUTHOR,reviewer_thread=fixture.REVIEWER)
        self.assertEqual(context['allowed_log_paths'],list(map(str,(self.parent,self.author,self.reviewer))))
        self.assertEqual([x['role'] for x in proof['selected_tasks']],['AUTHOR','REVIEWER'])
        self.assertEqual(len({x['child_thread_id'] for x in proof['selected_tasks']}),2)

    def test_mismatched_selected_role_cannot_be_added_to_context(self):
        with self.assertRaisesRegex(ValueError,'HOST_CHILD_CURRENT_TASK_MISMATCH'):
            host.create_context(PACKAGE,run=self.run,
                author_thread=fixture.REVIEWER,reviewer_thread=fixture.AUTHOR)

    def test_duplicate_selected_thread_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'SAME_ACTUAL_TASK'):
            host.create_context(PACKAGE,run=self.run,
                author_thread=fixture.AUTHOR,reviewer_thread=fixture.AUTHOR)

    def test_parent_context_cannot_be_created_by_current_child(self):
        with patch.dict(os.environ,{'CODEX_THREAD_ID':fixture.AUTHOR}):
            with self.assertRaisesRegex(ValueError,'COORDINATOR_CONTEXT_REQUIRED'):
                host.create_context(PACKAGE)

    def test_multiple_files_do_not_override_exact_index_with_mtime_guessing(self):
        duplicate = self.days / ('rollout-2001-01-01T01-01-01-'+fixture.ROOT+'.jsonl')
        duplicate.write_bytes(self.parent.read_bytes())
        self.assertEqual(host.create_context(PACKAGE)[0],self.startup)

    def test_selected_older_parent_log_requires_no_date_constant(self):
        older = self.home/'sessions'/(datetime.now().astimezone().date()-timedelta(days=4)).strftime('%Y/%m/%d')
        older.mkdir(parents=True)
        saved = self.name(fixture.ROOT,older)
        self.parent.rename(saved)
        self.index(fixture.ROOT,saved)
        context,_=host.create_context(PACKAGE,extra_days=[older])
        self.assertEqual(context['allowed_log_paths'],[str(saved)])
        explicit,_=host.create_context(PACKAGE,parent_log=saved)
        self.assertEqual(context,explicit)

    def test_paged_index_selects_native_segment_over_closed_legacy_file(self):
        segment=self.parent.with_name(self.parent.stem+'_40000000-0000-0000-0000-000000000001.jsonl')
        segment.write_bytes(self.parent.read_bytes())
        self.mutate(self.parent,lambda rows:rows.append({'type':'event_msg','timestamp':fixture.WHEN,
            'payload':{'type':'task_complete','turn_id':fixture.TURN}}))
        self.index(fixture.ROOT,segment,'paginated')
        context,proof=host.create_context(PACKAGE)
        self.assertEqual(context['allowed_log_paths'],[str(segment)])
        self.assertEqual(proof['identity']['turn'],fixture.TURN)
        with self.assertRaisesRegex(ValueError,'INDEX_EXPLICIT_PATH_CONFLICT'):
            host.create_context(PACKAGE,parent_log=self.parent)

    def test_extended_local_index_and_explicit_paths_name_the_same_file(self):
        extended='\\\\?\\'+str(self.parent)
        self.index(fixture.ROOT,extended)
        self.assertEqual(host.create_context(PACKAGE,parent_log=extended)[0],self.startup)

    def test_extended_unc_and_devices_are_not_normalized_to_local_paths(self):
        for value in ('\\\\?\\UNC\\server\\share\\log.jsonl','\\\\.\\C:\\log.jsonl'):
            with self.subTest(value=value):
                self.index(fixture.ROOT,value)
                with self.assertRaises(ValueError):host.create_context(PACKAGE)

    def test_unknown_index_mode_and_schema_reject_without_legacy_fallback(self):
        self.index(fixture.ROOT,self.parent,'unknown-future-mode')
        with self.assertRaisesRegex(ValueError,'CURRENT_THREAD_INDEX_ROW_SCHEMA'):
            host.create_context(PACKAGE)
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as connection, connection:
            connection.execute('DROP TABLE threads')
            connection.execute('CREATE TABLE threads (id INTEGER PRIMARY KEY,rollout_path TEXT NOT NULL,history_mode TEXT NOT NULL)')
        with self.assertRaisesRegex(ValueError,'CURRENT_THREAD_INDEX_SCHEMA'):
            host.create_context(PACKAGE)

    def test_missing_root_index_row_rejects_even_when_legacy_file_exists(self):
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as connection, connection:
            connection.execute('DELETE FROM threads WHERE id=?',(fixture.ROOT,))
        with self.assertRaisesRegex(ValueError,'CURRENT_THREAD_INDEX_ROW_REQUIRED'):
            host.create_context(PACKAGE)

    def test_index_outside_sessions_is_rejected_before_log_body_read(self):
        outside=self.base/'outside.jsonl'
        outside.write_bytes(b'PRIVATE_UNRELATED_BODY_MUST_NOT_BE_READ\n')
        self.index(fixture.ROOT,outside)
        with self.assertRaisesRegex(ValueError,'DAY_DIRECTORY_OUTSIDE_CODEX_SESSIONS'):
            host.create_context(PACKAGE)

    def test_unselected_index_rows_and_log_bodies_are_not_read(self):
        outside=self.base/'private-placeholder.jsonl'
        outside.write_bytes(b'UNRELATED_BODY_NOT_VALID_JSON\n')
        self.index('30000000-0000-0000-0000-000000000001',outside,'unknown-mode')
        before=(self.home/'state_5.sqlite').read_bytes()
        self.assertEqual(host.create_context(PACKAGE)[0],self.startup)
        self.assertEqual((self.home/'state_5.sqlite').read_bytes(),before)

    def test_indexed_hardlink_is_rejected_before_reading_body(self):
        linked=self.days/'owned-link.jsonl'
        os.link(self.parent,linked)
        try:
            with self.assertRaisesRegex(ValueError,'HARDLINK_PATH'):
                host.create_context(PACKAGE)
        finally:
            linked.unlink()

    def test_latest_completed_or_aborted_parent_turn_is_rejected(self):
        original=self.parent.read_bytes()
        for kind in ('task_complete','turn_aborted','shutdown_complete'):
            with self.subTest(kind=kind):
                self.parent.write_bytes(original)
                self.mutate(self.parent,lambda rows:rows.append({'type':'event_msg','timestamp':fixture.WHEN,
                    'payload':{'type':kind,'turn_id':fixture.TURN}}))
                with self.assertRaisesRegex(ValueError,'HOST_PARENT_TURN_CLOSED'):
                    host.create_context(PACKAGE)

    def test_completed_selected_child_remains_valid_for_parent_review_context(self):
        self.mutate(self.author,lambda rows:rows.append({'type':'event_msg','timestamp':fixture.WHEN,
            'payload':{'type':'task_complete','turn_id':fixture.AUTHOR_TURN}}))
        context,proof=host.create_context(PACKAGE,run=self.run,
            author_thread=fixture.AUTHOR,reviewer_thread=fixture.REVIEWER)
        self.assertIn(str(self.author),context['allowed_log_paths'])
        self.assertEqual(proof['selected_tasks'][0]['child_thread_id'],fixture.AUTHOR)

    def test_unrelated_filename_is_not_opened(self):
        private=self.days/'rollout-2001-01-01T01-01-01-30000000-0000-0000-0000-000000000001.jsonl'
        private.write_bytes(b'UNRELATED_INVALID_JSON_MUST_NOT_BE_PARSED\n')
        self.assertEqual(host.create_context(PACKAGE)[0],self.startup)

    def test_incomplete_live_tail_is_excluded_without_export(self):
        with self.parent.open('ab') as stream:stream.write(b'{"payload":"incomplete private tail')
        self.assertEqual(host.create_context(PACKAGE)[0],self.startup)
        capture,_=self.capture()
        self.assertNotIn(b'incomplete private tail',c.encode(capture))

    def test_unknown_spawn_result_schema_is_rejected(self):
        def mutate(rows):
            output=json.loads(rows[3]['payload']['output'])
            output['thread_id']=fixture.AUTHOR
            rows[3]['payload']['output']=json.dumps(output)
        self.mutate(self.parent,mutate)
        with self.assertRaisesRegex(ValueError,'UNKNOWN_OR_MISSING_FIELDS'):
            self.capture()

    def test_output_is_new_and_does_not_overwrite(self):
        target=self.base/'新证据 空格.json'
        receipt=host.write_output(target,self.startup)
        self.assertEqual(receipt['sha256'],c.digest(target))
        before=target.read_bytes()
        with self.assertRaisesRegex(ValueError,'HOST_OUTPUT_MUST_BE_NEW'):
            host.write_output(target,{'different':True})
        self.assertEqual(target.read_bytes(),before)


if __name__=='__main__':
    unittest.main()
