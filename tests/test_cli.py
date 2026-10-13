"""CLI wiring tests with invented host evidence and mocked client capability.

No fixture is an actual model task, installed-client proof, or scientific review.
Every test initializes a new storage instance and uses real document, review and
storage modules. Only doctor/client capability and test time are substituted.
"""
from contextlib import redirect_stdout, redirect_stderr
from datetime import timedelta
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from app import cli, client, core as c, documents as d, environment, storage
import test_review as fixture


PACKAGE = Path(__file__).resolve().parents[1]
SCRATCH = PACKAGE / 'tests/.scratch/cli'


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='synthetic-', dir=SCRATCH)
        cls.base = Path(cls.temporary.name)
        cls.package = cls.base / 'descriptor'
        (cls.package / 'app').mkdir(parents=True)
        (cls.package / 'launch.py').write_bytes(b'# Synthetic CLI module descriptor only\n')
        (cls.package / 'RUNTIME_MANIFEST.json').write_bytes(c.encode({'fixture_only': True}))
        for source in (PACKAGE / 'app').glob('*.py'):
            shutil.copyfile(source, cls.package / 'app' / source.name)
        cls.pdf = cls.base / 'invented.pdf'
        fixture._pdf(cls.pdf)
        cls.ordinal = 0

    @classmethod
    def tearDownClass(cls):
        if not cls.base.resolve().is_relative_to(SCRATCH.resolve()) or not cls.base.name.startswith('synthetic-'):
            raise RuntimeError('CLI_TEST_CLEANUP_OUTSIDE_OWNED_SCRATCH')
        cls.temporary.cleanup()

    def setUp(self):
        type(self).ordinal += 1
        self.case = self.base / ('case-' + str(self.ordinal))
        self.case.mkdir()
        self.instance = self.case / 'new-instance'
        self.executable = self.case / 'capability-placeholder.exe'
        self.executable.write_bytes(b'Not executable: client capability is explicitly mocked.')
        self.host_path = self.case / 'startup-context.json'
        self.author_log = self.case / 'author/parent.jsonl'
        self.author_log.parent.mkdir()
        self.author_log.write_bytes(b'Invented fixture will replace this placeholder.\n')
        self.startup = {'root': fixture.ROOT, 'turn': fixture.TURN,
                        'allowed_log_paths': [str(self.author_log)]}
        self.host_path.write_bytes(c.encode(self.startup))
        categories = [{'id': 'DEMO', 'label': '纯合成接线测试'}]
        confirmation = {'confirmed': True, 'categories_sha256': c.sha(c.encode(categories)),
                        'scope': 'SYNTHETIC_DEMO', 'authorization': '仅为模块接线测试创建的全新合成库。'}
        (self.case / 'categories.json').write_bytes(c.encode(categories))
        (self.case / 'confirmation.json').write_bytes(c.encode(confirmation))
        self.clock = patch.object(c, 'utcnow', return_value=fixture.START)
        self.storage_clock = patch.object(storage, 'utcnow', return_value=fixture.START)
        self.doctor = patch.object(environment, 'doctor', return_value={
            'software_checks_passed': True, 'fixture_only': True, 'installed_capability': 'NOT_TESTED'})
        self.prereq = patch.object(client, 'prereq', return_value={
            'ok': True, 'fixture_only': True, 'installed_capability': 'NOT_TESTED'})
        self.now = self.clock.start()
        self.storage_now = self.storage_clock.start()
        self.doctor_mock = self.doctor.start()
        self.prereq_mock = self.prereq.start()
        for patcher in (self.clock, self.storage_clock, self.doctor, self.prereq):
            self.addCleanup(patcher.stop)
        self.invoke('init', '--instance', self.instance, '--categories', self.case/'categories.json',
                    '--confirmation', self.case/'confirmation.json', *self.startup_flags())
        intake = self.invoke('intake', '--instance', self.instance, '--pdf', self.pdf,
                             '--title', '纯合成三页接线检查', '--category', 'DEMO', *self.startup_flags())
        self.run = Path(intake['run'])
        # Reuse only helper construction, not ReviewTests inheritance or its tests.
        fixture._assemble(self.package, self.run)
        self.now.return_value = fixture.START + timedelta(minutes=2)
        self.storage_now.return_value = self.now.return_value
        _, inputs, input_sha = d.verify_review_inputs(self.package, self.run)
        self.report = {'schema': 'singlepaper.semantic_review.v1', 'input_sha256': input_sha,
                       'checked_pages': [1, 2, 3], 'checked_formula_ids': ['EQ001'],
                       'checked_figure_numbers': [1], 'checked_reference_numbers': [1],
                       'cross_page_checked': True, 'verdict': 'PASS', 'findings': [],
                       'scope_note': '虚构单元测试报告，仅验证程序连接，不证明真实模型检查。'}
        self.report_path = self.run / 'semantic-report.json'
        self.report_path.write_bytes(c.encode(self.report))
        self.author = fixture.HostFixture(self.case/'author', 'AUTHOR', inputs['input_sha256'], input_sha)
        self.reviewer = fixture.HostFixture(self.case/'reviewer', 'REVIEWER', input_sha, c.digest(self.report_path))
        self.context = {'root': fixture.ROOT, 'turn': fixture.TURN, 'allowed_log_paths': [
            str(path) for path in (self.author.parent, self.author.child, self.reviewer.parent, self.reviewer.child)]}
        self.context_path = self.case / 'review-context.json'
        self.context_path.write_bytes(c.encode(self.context))
        self.author_path, self.reviewer_path = self.case/'author.json', self.case/'reviewer.json'
        self.author_path.write_bytes(c.encode(self.author.capture))
        self.reviewer_path.write_bytes(c.encode(self.reviewer.capture))

    def startup_flags(self):
        return ('--obsidian-cli', self.executable, '--host-context', self.host_path)

    def invoke(self, *arguments, expected=0):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['singlepaper'] + [str(x) for x in arguments]), redirect_stdout(output):
            code = cli.main(self.package)
        value = json.loads(output.getvalue())
        self.assertEqual(code, expected, value)
        return value

    def review_check(self, expected=0):
        return self.invoke('review-check', '--run', self.run, '--report', self.report_path,
                           '--author-capture', self.author_path, '--reviewer-capture', self.reviewer_path,
                           '--host-context', self.context_path, expected=expected)

    def command(self, name, expected=0):
        return self.invoke(name, '--run', self.run, expected=expected)

    def test_public_parser_exposes_no_skip_or_expiry_override(self):
        for command, option in (('publish', '--skip-review'), ('prepare-publish', '--skip'),
                                ('review-verify', '--active=false')):
            with self.subTest(command=command), patch.object(sys, 'argv', [
                    'singlepaper', command, '--run', str(self.run), option]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli.main(self.package)
                self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.invoke('requirements')['status'], 'REQUIREMENTS_FIRST')

    def test_startup_seal_is_required_before_review_check(self):
        (self.run / 'STARTUP_COMMIT.json').unlink()
        self.assertIn('FILE_MISSING', self.review_check(expected=2)['error'])
        self.assertFalse((self.run / 'REVIEW_EVIDENCE_COMMIT.json').exists())
        self.assertEqual(storage.verify(self.instance)['works'], 0)

    def test_review_check_produces_immutable_recheckable_evidence_bundle(self):
        result = self.review_check()
        saved = c.read_json(self.run/'REVIEW_EVIDENCE.json')
        self.assertEqual(saved['result'], result)
        self.assertEqual(saved['report'], c.ref(self.run, self.report_path))
        self.assertEqual(c.read_json(self.run/'evidence/context.json'), self.context)
        self.assertEqual(self.command('review-verify'), result)
        self.assertEqual(self.review_check(), result)
        self.assertEqual(result['scientific_acceptance'], 'NONE')
        # Actual preflight wiring was exercised; installed capability was mocked.
        self.prereq_mock.assert_called_with(self.package, self.executable, self.startup)

    def test_forged_or_expired_report_cannot_reach_prepare_publish(self):
        self.report['input_sha256'] = 'a' * 64
        self.report_path.write_bytes(c.encode(self.report))
        self.assertIn('STALE_REPORT', self.review_check(expected=2)['error'])
        self.assertIn('FILE_MISSING', self.command('prepare-publish', expected=2)['error'])
        self.assertFalse((self.run/'PUBLICATION_PLAN_COMMIT.json').exists())
        self.assertEqual(storage.verify(self.instance)['works'], 0)
        self.report['input_sha256'] = c.digest(self.run/'REVIEW_INPUTS.json')
        self.report_path.write_bytes(c.encode(self.report))
        self.review_check()
        self.now.return_value = fixture.START + timedelta(hours=2)
        self.storage_now.return_value = self.now.return_value
        self.assertIn('SESSION_EXPIRED_OR_CLOCK_CHANGED', self.command('prepare-publish', expected=2)['error'])
        self.assertTrue(self.command('review-verify')['ok'])
        self.assertFalse((self.run/'PUBLICATION_PLAN_COMMIT.json').exists())

    def test_cli_pipeline_saves_only_checked_bytes_and_keeps_owner(self):
        original = c.read_json(self.instance/'.system/library.json')
        self.assertIn('FILE_MISSING', self.command('prepare-publish', expected=2)['error'])
        review_result = self.review_check()
        planned = self.command('prepare-publish')
        self.assertEqual(planned['status'], 'READY_TO_SAVE')
        self.assertEqual(storage.verify(self.instance)['works'], 0)
        saved = self.command('publish')
        self.assertEqual(saved['status'], 'STORED_OUTPUT_VERIFIED')
        self.assertEqual(saved['client_validation'], 'NOT_RUN')
        library = c.read_json(self.instance/'.system/library.json')
        self.assertEqual(library['instance_id'], original['instance_id'])
        self.assertEqual(library['works'][0]['run_id'], self.run.name)
        self.assertEqual(storage.verify(self.instance)['works'], 1)
        plan = c.loads(c.check_ref(self.instance, planned['plan']))
        self.assertEqual(plan['gate_receipt']['report_sha256'], review_result['report_sha256'])
        self.assertEqual(plan['gate_receipt']['instance_id'], original['instance_id'])
        provenance = c.read_json(self.run/'bundle/provenance.json')
        self.assertEqual([x['child_thread_id'] for x in provenance['actors']], [fixture.AUTHOR, fixture.REVIEWER])
        self.assertEqual(self.command('publish'), saved)

    def test_evidence_and_publication_bundle_drift_are_rejected(self):
        self.review_check()
        saved = (self.run/'evidence/author.json').read_bytes()
        (self.run/'evidence/author.json').write_bytes(saved + b' ')
        self.assertIn('REFERENCE_DRIFT', self.command('prepare-publish', expected=2)['error'])
        (self.run/'evidence/author.json').write_bytes(saved)
        self.command('prepare-publish')
        path = self.run/'bundle/summary.md'
        path.write_bytes(path.read_bytes() + '检查后新插入的文字。'.encode())
        error = self.command('publish', expected=2)['error']
        self.assertTrue('PUBLICATION_BUNDLE_CHANGED' in error or 'REFERENCE_DRIFT' in error, error)
        self.assertEqual(storage.verify(self.instance)['works'], 0)

    def test_startup_task_cannot_be_changed_by_later_review_context(self):
        changed = {**self.context, 'turn': '20000000-0000-0000-0000-000000000001'}
        self.context_path.write_bytes(c.encode(changed))
        self.assertIn('HOST_TASK_CHANGED', self.review_check(expected=2)['error'])
        self.assertFalse((self.run/'REVIEW_EVIDENCE_COMMIT.json').exists())

    def test_new_init_parameters_bind_explicit_categories_in_new_unicode_root(self):
        new_root=self.case/'用户 新目录'
        result=self.invoke('init','--instance',new_root,'--category','METHOD=方法 阅读',
            '--category','BASICS=基础概念','--authorization','用户明确选择这两个分类并初始化新库。',*self.startup_flags())
        value=c.read_json(new_root/'.system/library.json')
        confirmation=c.read_json(new_root/'.system/category-confirmation.json')
        self.assertEqual(value['categories'],[{'id':'METHOD','label':'方法 阅读'},{'id':'BASICS','label':'基础概念'}])
        self.assertEqual(confirmation['categories_sha256'],c.sha(c.encode(value['categories'])))
        self.assertEqual(result['category_scope'],'USER_CONFIRMED')
        before=(new_root/'.system/library.json').read_bytes()
        failure=self.invoke('init','--instance',new_root,'--demo','--authorization','新建合成库。',
            *self.startup_flags(),expected=2)
        self.assertEqual(failure['error'],'ROOT_MUST_BE_NEW')
        self.assertEqual((new_root/'.system/library.json').read_bytes(),before)

    def test_new_init_requires_explicit_authorization_and_valid_category(self):
        new_root=self.case/'未授权新库'
        failure=self.invoke('init','--instance',new_root,'--category','METHOD=方法',
            *self.startup_flags(),expected=2)
        self.assertEqual(failure['error'],'CATEGORY_AUTHORIZATION_REQUIRED')
        self.assertFalse(new_root.exists())
        failure=self.invoke('init','--instance',new_root,'--category','invalid-slash/=方法',
            '--authorization','用户选定的分类。',*self.startup_flags(),expected=2)
        self.assertEqual(failure['error'],'CATEGORY_ID')
        self.assertFalse(new_root.exists())

    def test_role_brief_requires_actual_work_and_does_not_prefill_pass(self):
        author=self.invoke('role-brief','--run',self.run,'--role','AUTHOR')
        reviewer=self.invoke('role-brief','--run',self.run,'--role','REVIEWER')
        self.assertEqual(author['task_name'],'author_'+c.digest(self.run/'INPUT.json'))
        self.assertEqual(reviewer['task_name'],'reviewer_'+c.digest(self.run/'REVIEW_INPUTS.json'))
        template=reviewer['report_template']
        self.assertEqual(template['verdict'],'BLOCK')
        self.assertFalse(template['cross_page_checked'])
        self.assertEqual(template['checked_pages'],[])
        self.assertEqual(storage.verify(self.instance)['works'],0)

    def test_role_final_binds_frozen_bytes_and_rejects_unchecked_report(self):
        author=self.invoke('role-final','--run',self.run,'--role','AUTHOR')
        self.assertEqual(author['claims']['AUTHOR_OUTPUT_SHA256'],c.digest(self.run/'REVIEW_INPUTS.json'))
        reviewer=self.invoke('role-final','--run',self.run,'--role','REVIEWER','--report',self.report_path)
        self.assertEqual(reviewer['claims']['REPORT_SHA256'],c.digest(self.report_path))
        self.report['cross_page_checked']=False
        self.report_path.write_bytes(c.encode(self.report))
        failure=self.invoke('role-final','--run',self.run,'--role','REVIEWER',
            '--report',self.report_path,expected=2)
        self.assertEqual(failure['error'],'CROSS_PAGE_REVIEW_REQUIRED')
        self.assertFalse((self.run/'REVIEW_EVIDENCE_COMMIT.json').exists())

    def test_recovery_finishes_only_committed_output_and_never_reruns_review(self):
        self.review_check()
        self.command('prepare-publish')
        self.assertIn('NOT_COMMITTED_NO_RECOVERY', self.command('recover', expected=2)['error'])
        with patch.object(storage, '_apply_outputs', side_effect=OSError('fixture-after-commit')):
            self.assertIn('fixture-after-commit', self.command('publish', expected=2)['error'])
        self.assertEqual(c.read_json(self.instance/'.system/library.json')['works'][0]['status'],
                         'COMMITTED_READING_PENDING')
        self.now.return_value = fixture.START + timedelta(hours=2)
        self.storage_now.return_value = self.now.return_value
        with patch.object(cli, '_gate', side_effect=AssertionError('Recovery must not rerun review')):
            result = self.command('recover')
        self.assertEqual(result['status'], 'STORED_OUTPUT_VERIFIED')
        self.assertEqual(storage.verify(self.instance)['works'], 1)


class CliMainExitTests(unittest.TestCase):
    """Public main must propagate structured failure without running a client."""

    def invoke_result(self, result):
        output = io.StringIO()
        arguments = ['singlepaper', 'read-index', '--instance', 'synthetic-instance',
                     '--obsidian-cli', 'synthetic-client.com']
        with patch.object(sys, 'argv', arguments), patch.object(cli, 'execute', return_value=result) as execute, redirect_stdout(output):
            code = cli.main(PACKAGE)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[1].command, 'read-index')
        self.assertEqual(json.loads(output.getvalue()), result)
        return code

    def test_main_structured_false_exits_two_and_keeps_receipt(self):
        result = {'schema': 'singlepaper.client_index.v1', 'ok': False,
                  'status': 'BLOCKED', 'index_validation': 'FAIL'}
        self.assertEqual(self.invoke_result(result), 2)

    def test_main_partial_success_exits_zero(self):
        result = {'ok': True, 'status': 'PARTIAL', 'pdf_visual_validation': 'NOT_RUN'}
        self.assertEqual(self.invoke_result(result), 0)

    def test_main_results_without_exact_false_keep_zero_exit(self):
        for result in ({'status': 'REQUIREMENTS_FIRST'}, {'ok': None}, {'ok': 0}, ['synthetic-result']):
            with self.subTest(result=result):
                self.assertEqual(self.invoke_result(result), 0)


if __name__ == '__main__':
    unittest.main()
