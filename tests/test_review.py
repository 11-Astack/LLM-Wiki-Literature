"""Invented local host records for gate tests, never actual task evidence.

The document pipeline is exercised on a new synthetic three-page PDF. Test
translation strings and fabricated host records have no semantic evidentiary
authority; the parent coordinator must separately run real author/reviewer tasks.
"""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app import core as c, documents as d, page_protocol as pp, review


PACKAGE = Path(__file__).resolve().parents[1]
SCRATCH = PACKAGE / 'tests/.scratch/review'
START = datetime(2030, 1, 1, tzinfo=timezone.utc)
WHEN = (START + timedelta(minutes=1)).isoformat()
ROOT = '10000000-0000-0000-0000-000000000001'
TURN = '10000000-0000-0000-0000-000000000002'
AUTHOR = '10000000-0000-0000-0000-000000000003'
AUTHOR_TURN = '10000000-0000-0000-0000-000000000004'
REVIEWER = '10000000-0000-0000-0000-000000000005'
REVIEWER_TURN = '10000000-0000-0000-0000-000000000006'


def _records(path, rows):
    refs, blobs, offset = [], [], 0
    for number, (kind, payload, timestamp) in enumerate(rows, 1):
        data = (json.dumps({'type': kind, 'payload': payload, 'timestamp': timestamp},
                           ensure_ascii=False) + '\n').encode('utf-8')
        refs.append({'line': number, 'byte_offset': offset, 'byte_length': len(data),
                     'raw_record_sha256': c.sha(data), 'timestamp': timestamp})
        blobs.append(data)
        offset += len(data)
    path.write_bytes(b''.join(blobs))
    return refs


def _turn(turn):
    return {'turn_id': turn, 'root_turn_id': TURN, 'model': 'invented-test-model', 'effort': 'high',
            'collaboration_mode': {'mode': 'default', 'settings':
                                  {'model': 'invented-test-model', 'reasoning_effort': 'high'}}}


def _turn_fields(value):
    return {**{key: value[key] for key in ('turn_id', 'root_turn_id', 'model', 'effort')},
            'collaboration_settings': {'model': value['model'], 'reasoning_effort': value['effort']}}


class HostFixture:
    """Modeled on the prior verifier's synthetic fixture, not captured logs."""
    def __init__(self, directory, role, input_sha, output_sha, *, child_id=None, child_turn=None,
                 final_time=WHEN, dispatch_time=WHEN, claim_override=None, final_phase='final_answer',
                 task_override=None, repeat_final=False, marker_suffix=''):
        directory.mkdir(parents=True, exist_ok=True)
        child_id = child_id or (AUTHOR if role == 'AUTHOR' else REVIEWER)
        child_turn = child_turn or (AUTHOR_TURN if role == 'AUTHOR' else REVIEWER_TURN)
        task_name = task_override or role.lower() + '_' + input_sha
        task = '/root/' + task_name
        self.parent, self.child = directory / 'parent.jsonl', directory / 'child.jsonl'
        message = 'Invented unit-test dispatch. No actual task was created.'
        message_hash = c.sha(message.encode())
        old = (START - timedelta(hours=2)).isoformat()
        parent_meta = {'id': ROOT, 'session_id': ROOT, 'timestamp': old, 'originator': 'fixture',
                       'cli_version': 'fixture', 'model_provider': 'fixture',
                       'source': 'vscode', 'thread_source': 'user'}
        parent_turn = _turn(TURN)
        args = {'task_name': task_name, 'message': message, 'fork_turns': 'none'}
        call_id = 'call_' + role.lower()
        call = {'type': 'function_call', 'name': 'spawn_agent', 'call_id': call_id, 'arguments': json.dumps(args)}
        output = {'type': 'function_call_output', 'call_id': call_id,
                  'output': json.dumps({'task_name': task})}
        parent_refs = _records(self.parent, [('session_meta', parent_meta, old),
            ('turn_context', parent_turn, old), ('response_item', call, dispatch_time),
            ('response_item', output, dispatch_time)])
        spawn = {'parent_thread_id': ROOT, 'depth': 1, 'agent_path': task}
        child_meta = {'id': child_id, 'session_id': ROOT, 'timestamp': dispatch_time,
                      'originator': 'fixture', 'cli_version': 'fixture', 'model_provider': 'fixture',
                      'thread_source': 'subagent', 'source': {'subagent': {'thread_spawn': spawn}}}
        child_context = _turn(child_turn)
        wrapper = 'Invented encrypted-content placeholder.'
        delegation = {'type': 'agent_message', 'id': 'amsg_fixture', 'author': '/root', 'recipient': task,
                      'content': [{'type': 'input_text', 'text': wrapper},
                                  {'type': 'encrypted_content', 'encrypted_content': 'fixture_only'}]}
        claims = {'INPUT_SHA256': input_sha,
                  'AUTHOR_OUTPUT_SHA256' if role == 'AUTHOR' else 'REPORT_SHA256': output_sha}
        claims.update(claim_override or {})
        final = {'type': 'message', 'role': 'assistant', 'phase': final_phase,
                 'content': [{'type': 'output_text', 'text':
                              '\n'.join(key + '=' + value for key, value in claims.items()) + marker_suffix}]}
        rows = [('session_meta', child_meta, dispatch_time), ('turn_context', child_context, dispatch_time),
                ('response_item', delegation, dispatch_time), ('response_item', final, final_time)]
        if repeat_final:
            rows.append(('response_item', final, final_time))
        child_refs = _records(self.child, rows)
        self.capture = {
            'schema': 'codex-host-metadata-probe-v001', 'captured_at_utc': WHEN,
            'scope': {'root_thread_id': ROOT, 'root_turn_id': TURN, 'allowed_day_directories': [],
                      'message_bodies_exported': False, 'source_logs_modified': False},
            'process_environment': {'CODEX_SESSION_ID': ROOT, 'CODEX_THREAD_ID': child_id},
            'parent': {
                'source_path': str(self.parent), 'expected_thread_id': ROOT,
                'session_metadata': [{'ref': parent_refs[0], 'fields': parent_meta}],
                'turn_contexts': [{'ref': parent_refs[1], 'fields': _turn_fields(parent_turn)}],
                'collaboration_calls': [{'ref': parent_refs[2], 'fields': {
                    'name': 'spawn_agent', 'call_id': call_id,
                    'arguments': {key: value for key, value in args.items() if key != 'message'},
                    'argument_field_names': sorted(args), 'message_utf8_sha256': message_hash}}],
                'collaboration_results': [{'ref': parent_refs[3], 'fields': {
                    'call_id': call_id, 'output_field_names': ['task_name'], 'output': {'task_name': task}}}],
                'agent_message_metadata': [], 'inter_agent_metadata': [], 'diagnostics': [],
                'snapshot_boundary_bytes': self.parent.stat().st_size, 'captured_task_names': [task]},
            'child': {
                'source_path': str(self.child), 'environment_thread_hint': child_id,
                'session_metadata': {'ref': child_refs[0], 'fields': {
                    **{key: value for key, value in child_meta.items() if key != 'source'}, 'thread_spawn': spawn}},
                'turn_context': {'ref': child_refs[1], 'fields': _turn_fields(child_context)},
                'first_delegation': {'ref': child_refs[2], 'fields': {
                    'id': 'amsg_fixture', 'author': '/root', 'recipient': task,
                    'content_part_metadata': [
                        {'index': 0, 'type': 'input_text', 'encrypted_content_present': False,
                         'text_utf8_sha256': c.sha(wrapper.encode()), 'text_character_count': len(wrapper),
                         'equals_parent_dispatch_hash': False},
                        {'index': 1, 'type': 'encrypted_content', 'encrypted_content_present': True}],
                    'parent_dispatch_call_id': call_id, 'parent_dispatch_message_utf8_sha256': message_hash,
                    'body_equivalence_status': 'NOT_PROVEN'}},
                'diagnostics': [], 'identity_link_status': 'VERIFIED_FROM_HOST_RECORDS', 'read_boundary': 'fixture'},
            'child_log_opened': True, 'claim_boundary': 'Invented unit-test fixture only.'}


def _library(path):
    """Native _library shape only; test_cli owns complete storage integration."""
    (path / '.system').mkdir(parents=True)
    (path / '.work/runs').mkdir(parents=True)
    instance_id = '11111111-1111-4111-8111-111111111111'
    vault = 'Reading-' + instance_id[:8]
    categories = [{'id': 'TEST', 'label': '纯合成技术测试'}]
    confirmation = path / '.system/category-confirmation.json'
    confirmation.write_bytes(c.encode({'confirmed': True, 'categories_sha256': c.sha(c.encode(categories)),
                                      'scope': 'USER_CONFIRMED',
                                      'authorization': '虚构确认夹具，仅供机制测试，不代表真实授权'}))
    overview = path / vault / 'indexes/Library-000000.md'
    overview.parent.mkdir(parents=True)
    overview.write_bytes('# 纯合成机制测试索引\n'.encode())
    (path / '.system/library.json').write_bytes(c.encode({
        'schema': 'singlepaper.library.v1', 'instance_id': instance_id, 'vault_dir': vault, 'revision': 0,
        'storage_layout': 'immutable-reading.v2', 'created_utc': c.utcnow().isoformat(),
        'root_binding': str(path.resolve()), 'works': [], 'categories': categories,
        'category_confirmation': c.ref(path, confirmation), 'overview': c.ref(path, overview)}))


def _pdf(path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    font_ref = writer._add_object(font)
    for number in range(1, 4):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_ref})})
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 7 Tf 30 700 Td (Invented review module page ' + str(number) +
                         '. A synthetic document tests complete frozen inputs and independent task records only.) Tj ET').encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    with path.open('wb') as output:
        writer.write(output)


def _assemble(package, run):
    from PIL import Image, ImageChops
    inp, input_sha = d.input_record(package, run)
    caption = 'Figure 1. Invented component crop for technical testing.'
    reference = r'- \[1\] A. Example, "Invented component", Fictional Journal (2024).'
    source = ('<!-- PDF_PAGE: 1 -->\n# First component\n\n'
              'This invented component tests complete frozen inputs and protected numerical data 3 [1].\n\n'
              '<!-- LIT_FORMULA_TRANSCRIPTION {"formula_id":"EQ001","pdf_page":1} -->\n$$\nx + y = 3\n$$\n\n'
              '<!-- PDF_PAGE: 2 -->\n# Second component\n\n'
              'This second invented page contains a crop to check exact figure inventory coverage.\n\n'
              '![Figure 1](figures/Figure-01.png)\n\n' + caption + '\n\n'
              '<!-- PDF_PAGE: 3 -->\n# Third component\n\n'
              'This final invented page includes a bibliography for exact reference coverage.\n\n'
              '# References\n\n' + reference + '\n')
    with Image.open(run / inp['pages'][1]['image']['path']) as image:
        rgb = image.convert('RGB')
        bbox = ImageChops.difference(rgb, Image.new('RGB', image.size, 'white')).getbbox()
    inventory = {'schema': 'singlepaper.inventory.v1', 'input_sha256': input_sha,
                 'source_sha256': c.sha(source.encode()), 'page_count': 3, 'reviewed_pages': [1, 2, 3],
                 'formulas': [{'id': 'EQ001', 'page': 1, 'latex': 'x + y = 3', 'printed_label': None}],
                 'figures': [{'number': 1, 'page': 2, 'bbox_pixels': list(bbox), 'caption': caption}],
                 'references': [{'number': 1, 'page': 3, 'text': reference}]}
    (run / 'draft').mkdir()
    (run / 'draft/source.md').write_bytes(source.encode())
    (run / 'draft/inventory.json').write_bytes(c.encode(inventory))
    d.prepare_source(package, run, run / 'draft/source.md', run / 'draft/inventory.json')
    _, _, source_sha = d.source_record(package, run)
    for page in range(1, 4):
        original = (run / f'page-inputs/page-{page:03d}.md').read_text(encoding='utf-8')
        def fill(match):
            metadata = json.loads(match['meta'])
            numbers = d.NUMBER_RE.findall(match['body'])
            groups = pp.citation_groups(match['body'])
            for group in groups:
                for number in d.NUMBER_RE.findall(group):
                    numbers.remove(number)
            value = '纯合成技术测试仅用于检查受保护结构和完整记录，不构成语义检查或科学接受。' * 2
            value += ' ' + ' '.join(numbers) + ''.join(' [' + group + ']' for group in groups)
            return ('<!-- LIT_TRANSLATED_SPAN ' + json.dumps(metadata) + ' -->\n' + value +
                    '\n<!-- LIT_TRANSLATED_SPAN_END ' + metadata['id'] + ' -->')
        candidate = run / f'candidates/technical-{page:03d}.md'
        candidate.write_bytes((f'<!-- LIT_SESSION_SHA256 {source_sha} -->\n## PDF 第 {page} 页\n\n' +
                               pp.SPAN_INPUT_RE.sub(fill, original)).encode())
        d.validate_page(package, run, page, candidate)
    for name in ('summary.md', 'science_notes.md'):
        (run / name).write_bytes('这是纯合成技术机制测试说明，不代表真实语义审核结论。\n'.encode())
    d.assemble(package, run)


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='synthetic-', dir=SCRATCH)
        cls.base = Path(cls.temp.name)
        cls.descriptor = cls.base / 'descriptor'
        (cls.descriptor / 'app').mkdir(parents=True)
        (cls.descriptor / 'launch.py').write_bytes(b'# Module fixture descriptor only\n')
        (cls.descriptor / 'RUNTIME_MANIFEST.json').write_bytes(c.encode({'fixture_only': True}))
        for name in ('core.py', 'documents.py', 'page_protocol.py', 'evidence.py', 'review.py'):
            shutil.copyfile(PACKAGE / 'app' / name, cls.descriptor / 'app' / name)
        cls.seed_instance = cls.base / 'seed'
        _library(cls.seed_instance)
        _pdf(cls.base / 'invented.pdf')
        with patch.object(c, 'utcnow', return_value=START):
            response = d.intake(cls.descriptor, cls.seed_instance, cls.base / 'invented.pdf', '纯合成测试', 'TEST')
            cls.seed = Path(response['run'])
            _assemble(cls.descriptor, cls.seed)
        cls.ordinal = 0

    @classmethod
    def tearDownClass(cls):
        if not cls.base.resolve().is_relative_to(SCRATCH.resolve()) or not cls.base.name.startswith('synthetic-'):
            raise RuntimeError('CLEANUP_TARGET_OUTSIDE_OWNED_SCRATCH')
        cls.temp.cleanup()

    def setUp(self):
        type(self).ordinal += 1
        self.case = self.base / ('case-' + str(self.ordinal))
        self.case.mkdir()
        self.instance = self.case / 'instance'
        _library(self.instance)
        self.run = self.instance / '.work/runs' / self.seed.name
        shutil.copytree(self.seed, self.run)
        self.package = self.descriptor
        self.clock = patch.object(c, 'utcnow', return_value=START + timedelta(minutes=2))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        inp, inputs, inputs_sha = d.verify_review_inputs(self.package, self.run)
        self.inp, self.inputs, self.inputs_sha = inp, inputs, inputs_sha
        self.report = {'schema': 'singlepaper.semantic_review.v1', 'input_sha256': inputs_sha,
                       'checked_pages': [1, 2, 3], 'checked_formula_ids': ['EQ001'],
                       'checked_figure_numbers': [1], 'checked_reference_numbers': [1],
                       'cross_page_checked': True, 'verdict': 'PASS', 'findings': [],
                       'scope_note': '此报告仅为虚构机制单元测试，不能作为真实检查证据。'}
        self.report_path = self.run / 'review/report.json'
        self.report_path.parent.mkdir()
        self.report_path.write_bytes(c.encode(self.report))
        self.evidence()

    def evidence(self, author=None, reviewer=None):
        self.author = HostFixture(self.case / 'author', 'AUTHOR', self.inputs['input_sha256'],
                                  self.inputs_sha, **(author or {}))
        self.reviewer = HostFixture(self.case / 'reviewer', 'REVIEWER', self.inputs_sha,
                                    c.digest(self.report_path), **(reviewer or {}))
        self.host = {'root': ROOT, 'turn': TURN, 'allowed_log_paths':
                     [str(path) for path in (self.author.parent, self.author.child,
                                             self.reviewer.parent, self.reviewer.child)]}

    def check(self, **kwargs):
        return review.check(self.package, self.run, self.report_path,
                            self.author.capture, self.reviewer.capture, self.host, **kwargs)

    def changed_report(self, **updates):
        self.report.update(updates)
        self.report_path.write_bytes(c.encode(self.report))
        self.evidence()

    def reject(self, code, **kwargs):
        with self.assertRaisesRegex(ValueError, code):
            self.check(**kwargs)

    def test_complete_three_page_inputs_checked_with_deterministic_result(self):
        first = self.check()
        self.assertEqual(c.encode(first), c.encode(self.check()))
        self.assertEqual(first['schema'], 'singlepaper.review_verified.v1')
        self.assertEqual(first['review_inputs'], c.ref(self.run, self.run / 'REVIEW_INPUTS.json'))
        self.assertEqual(first['report'], c.ref(self.run, self.report_path))
        self.assertEqual(len(first['identities']), 2)
        self.assertEqual([x['binding_mode'] for x in first['identities']], ['task_name_v2'] * 2)
        self.assertEqual([x['role'] for x in first['task_final_refs']], ['AUTHOR', 'REVIEWER'])
        self.assertEqual(first['obsidian_reading'], 'NOT_VERIFIED')
        self.assertEqual(first['publication_status'], 'NOT_PUBLISHED')
        self.assertEqual(first['scientific_acceptance'], 'NONE')
        self.assertFalse(first['formal_processing_allowed'])
        self.assertEqual(first['host_context_sha256'], c.sha(c.encode(self.host)))

    def test_coverage_omissions_duplicates_reordering_and_boolean_numbers_rejected(self):
        cases = [('checked_pages', [1, 2]), ('checked_pages', [1, 2, 2]), ('checked_pages', [3, 2, 1]),
                 ('checked_pages', [True, 2, 3]), ('checked_formula_ids', []),
                 ('checked_formula_ids', ['EQ001', 'EQ001']), ('checked_figure_numbers', []),
                 ('checked_figure_numbers', [True]), ('checked_reference_numbers', []),
                 ('checked_reference_numbers', [True])]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                original = copy.deepcopy(self.report)
                self.changed_report(**{key: value})
                self.reject('REVIEW_COVERAGE')
                self.changed_report(**original)

    def test_cross_page_flag_is_required_and_strict(self):
        for value in (False, 1, 'true'):
            with self.subTest(value=value):
                self.changed_report(cross_page_checked=value)
                self.reject('CROSS_PAGE_REVIEW_REQUIRED')

    def test_block_or_nonempty_findings_rejected(self):
        self.changed_report(verdict='BLOCK')
        self.reject('REVIEW_BLOCKED')
        self.changed_report(verdict='PASS', findings=[{'description': '未解决的测试问题'}])
        self.reject('REVIEW_BLOCKED')

    def test_unknown_or_missing_report_fields_and_stale_report_rejected(self):
        self.changed_report(input_sha256='a' * 64)
        self.reject('STALE_REPORT')
        self.changed_report(input_sha256=self.inputs_sha, unexpected=True)
        self.reject('REPORT_SCHEMA')
        self.report.pop('unexpected')
        self.report.pop('checked_formula_ids')
        self.report_path.write_bytes(c.encode(self.report))
        self.reject('REPORT_SCHEMA')

    def test_duplicate_json_keys_rejected(self):
        data = c.encode(self.report).replace(b'"schema":', b'"verdict":"PASS", "schema":')
        self.report_path.write_bytes(data)
        self.reject('DUPLICATE_JSON_KEY')

    def test_scope_note_requires_chinese(self):
        self.changed_report(scope_note='Fixture only.')
        self.reject('REPORT_CHINESE_SCOPE_REQUIRED')

    def test_report_outside_run_rejected(self):
        self.report_path = self.case / 'outside.json'
        self.report_path.write_bytes(c.encode(self.report))
        self.reject('REPORT_MUST_BE_IN_RUN')

    def test_same_child_uuid_rejected_despite_different_names(self):
        self.evidence(reviewer={'child_id': AUTHOR})
        self.reject('SAME_ACTUAL_TASK')

    def test_same_child_turn_rejected(self):
        self.evidence(reviewer={'child_turn': AUTHOR_TURN})
        self.reject('SAME_ACTUAL_TURN')

    def test_wrong_actual_task_name_rejected(self):
        self.evidence(reviewer={'task_override': 'reviewer_' + 'a' * 64})
        self.reject('EXPECTED_TASK_DISPATCH_NOT_UNIQUE')

    def test_capture_cannot_add_host_read_authority(self):
        outside = self.case / 'unallowed.jsonl'
        outside.write_bytes(self.reviewer.child.read_bytes())
        self.reviewer.capture['child']['source_path'] = str(outside)
        self.reject('SOURCE_PATH_NOT_ALLOWLISTED')

    def test_context_extra_fields_duplicate_or_relative_paths_rejected(self):
        original = copy.deepcopy(self.host)
        self.host['author_task'] = 'invented'
        self.reject('HOST_CONTEXT_SCHEMA')
        self.host = copy.deepcopy(original)
        self.host['allowed_log_paths'].append(self.host['allowed_log_paths'][0])
        self.reject('HOST_ALLOWLIST_DUPLICATE')
        self.host = copy.deepcopy(original)
        self.host['allowed_log_paths'][0] = 'relative.jsonl'
        self.reject('HOST_ALLOWLIST_ABSOLUTE_PATHS_REQUIRED')

    def test_original_host_record_tamper_rejected(self):
        data = self.author.parent.read_bytes().replace(b'invented-test-model', b'tampered-test-model')
        self.author.parent.write_bytes(data)
        self.reject('RAW_RECORD_HASH_MISMATCH')

    def test_final_sha_claim_must_match_exact_frozen_bytes(self):
        self.evidence(author={'claim_override': {'AUTHOR_OUTPUT_SHA256': 'a' * 64}})
        self.reject('FINAL_CLAIM_MISMATCH')
        self.evidence(reviewer={'claim_override': {'REPORT_SHA256': 'a' * 64}})
        self.reject('FINAL_CLAIM_MISMATCH')

    def test_duplicate_final_or_indented_marker_rejected(self):
        self.evidence(reviewer={'repeat_final': True})
        self.reject('EXACT_FINAL_CLAIM_NOT_UNIQUE')
        self.evidence(reviewer={'marker_suffix': '\n INPUT_SHA256=' + self.inputs_sha})
        self.reject('FINAL_CLAIM_MISMATCH')

    def test_commentary_claim_not_final_rejected(self):
        self.evidence(reviewer={'final_phase': 'commentary'})
        self.reject('EXACT_FINAL_CLAIM_NOT_UNIQUE')

    def test_expired_active_rejected_readonly_retains_same_evidence(self):
        expected = self.check()
        with patch.object(c, 'utcnow', return_value=START + timedelta(hours=2)):
            self.reject('SESSION_EXPIRED_OR_CLOCK_CHANGED')
            self.assertEqual(self.check(active=False), expected)

    def test_late_or_predating_execution_is_rejected_even_readonly(self):
        for timestamp in ((START - timedelta(seconds=1)).isoformat(),
                          (START + timedelta(hours=1)).isoformat()):
            for role, kwargs in (('author', {'final_time': timestamp}),
                                 ('reviewer', {'final_time': timestamp}),
                                 ('author', {'dispatch_time': timestamp}),
                                 ('reviewer', {'dispatch_time': timestamp})):
                with self.subTest(role=role, kwargs=kwargs):
                    self.evidence(**{role: kwargs})
                    self.reject('TASK_RECORD_OUTSIDE_SESSION', active=False)

    def test_captured_time_can_be_after_deadline_for_readonly_verification(self):
        for fixture in (self.author, self.reviewer):
            fixture.capture['captured_at_utc'] = (START + timedelta(days=1)).isoformat()
        with patch.object(c, 'utcnow', return_value=START + timedelta(days=1)):
            self.assertTrue(self.check(active=False)['ok'])

    def test_self_report_pass_cannot_hide_actual_page_drift(self):
        path = self.run / 'accepted/page-002.md'
        path.write_bytes(path.read_bytes().replace('纯合成'.encode(), '恶意改动'.encode()))
        self.reject('REFERENCE_DRIFT')

    def test_self_report_pass_cannot_hide_actual_translation_drift(self):
        path = self.run / 'translation_zh.md'
        path.write_bytes(path.read_bytes() + '未被检查的新文字。'.encode())
        self.reject('REFERENCE_DRIFT')

    def test_reconstruction_repeated_and_report_change_during_check_rejected(self):
        original = d.verify_review_inputs
        count = 0
        def changed(*args, **kwargs):
            nonlocal count
            result = original(*args, **kwargs)
            count += 1
            if count == 2:
                self.report_path.write_bytes(c.encode({**self.report, 'scope_note': '中途改动测试报告。'}))
            return result
        with patch.object(d, 'verify_review_inputs', side_effect=changed):
            self.reject('REPORT_CHANGED_DURING_VERIFICATION')
        self.assertEqual(count, 2)

    def test_final_record_change_during_check_rejected(self):
        original = d.verify_review_inputs
        count = 0
        def changed(*args, **kwargs):
            nonlocal count
            result = original(*args, **kwargs)
            count += 1
            if count == 2:
                value = self.reviewer.child.read_bytes().replace(b'REPORT_SHA256=', b'REPORT_SHA257=')
                self.reviewer.child.write_bytes(value)
            return result
        with patch.object(d, 'verify_review_inputs', side_effect=changed):
            self.reject('FINAL_RECORD_CHANGED')

    def test_active_flag_requires_actual_boolean(self):
        self.reject('ACTIVE_FLAG_SCHEMA', active=0)


if __name__ == '__main__':
    unittest.main()
