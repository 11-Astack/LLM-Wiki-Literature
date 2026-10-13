"""Check frozen page outputs and independently dispatched local review evidence.

Adapted from the isolated prototype review gate. The unchanged evidence module
owns raw Codex identity verification; documents owns reconstruction of the exact
reviewed bytes. This module is read-only and never grants publication authority.
Host records share the local user's trust boundary, without backend attestation.
"""
from datetime import timedelta
import os
from pathlib import Path
import re

from . import core as c, documents
from .evidence import verify_dispatch_input


REPORT_FIELDS = {
    'schema', 'input_sha256', 'checked_pages', 'checked_formula_ids',
    'checked_figure_numbers', 'checked_reference_numbers', 'cross_page_checked',
    'verdict', 'findings', 'scope_note',
}
MAX_RECORD_BYTES = 2_000_000


def _normal(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _host(context):
    """The caller, not a capture or document, supplies the read authority."""
    c.require(isinstance(context, dict) and set(context) == {'root', 'turn', 'allowed_log_paths'},
              'HOST_CONTEXT_SCHEMA')
    paths = context['allowed_log_paths']
    c.require(isinstance(paths, list) and bool(paths), 'HOST_ALLOWLIST_REQUIRED')
    c.require(all(isinstance(p, str) and Path(p).is_absolute() for p in paths),
              'HOST_ALLOWLIST_ABSOLUTE_PATHS_REQUIRED')
    c.require(len({_normal(p) for p in paths}) == len(paths), 'HOST_ALLOWLIST_DUPLICATE')
    return [c.absolute(p) for p in paths]


def _in_window(timestamp, start, deadline):
    value = c.parse_time(timestamp)
    c.require(start <= value < deadline, 'TASK_RECORD_OUTSIDE_SESSION')
    return value


def _execution_times(capture, identity, start, deadline):
    """Parent root metadata may predate intake; the actual dispatch may not."""
    call_id = identity['spawn_call_id']
    parent = capture['parent']
    entries = [entry for entry in parent['collaboration_calls']
               if entry['fields']['call_id'] == call_id]
    entries += [entry for entry in parent['collaboration_results']
                if entry['fields']['call_id'] == call_id]
    child = capture['child']
    entries += [child['session_metadata'], child['turn_context'], child['first_delegation']]
    # These refs have already been checked against their original log bytes.
    c.require(len(entries) == 5, 'TASK_TIME_RECORDS_MISSING')
    for entry in entries:
        _in_window(entry['ref']['timestamp'], start, deadline)


def _final_claim(log, turn_id, claims, start, deadline, delegation_offset):
    """Read only an allowlisted child's bounded record lines; retain no body."""
    active_turn, found = None, []
    boundary = log.stat().st_size
    with log.open('rb') as stream:
        line_number = 0
        while stream.tell() < boundary:
            offset = stream.tell()
            raw = stream.readline(min(MAX_RECORD_BYTES + 1, boundary - offset))
            line_number += 1
            c.require(len(raw) <= MAX_RECORD_BYTES, 'HOST_LOG_RECORD_TOO_LARGE')
            if not raw.endswith(b'\n'):
                # A growing host log can end with one incomplete record.
                break
            event = c.loads(raw)
            c.require(isinstance(event, dict), 'HOST_LOG_RECORD_SCHEMA')
            payload = event.get('payload', {})
            if event.get('type') == 'turn_context':
                c.require(isinstance(payload, dict), 'HOST_LOG_TURN_SCHEMA')
                active_turn = payload.get('turn_id')
            if active_turn != turn_id or event.get('type') != 'response_item':
                continue
            c.require(isinstance(payload, dict), 'HOST_LOG_MESSAGE_SCHEMA')
            if (payload.get('type') != 'message' or payload.get('role') != 'assistant'
                    or payload.get('phase') != 'final_answer'):
                continue
            c.require(offset > delegation_offset, 'FINAL_PRECEDES_DELEGATION')
            parts = payload.get('content')
            c.require(isinstance(parts, list) and parts and
                      all(isinstance(p, dict) and p.get('type') == 'output_text'
                          and isinstance(p.get('text'), str) for p in parts),
                      'FINAL_TEXT_NOT_AVAILABLE')
            lines = ''.join(part['text'] for part in parts).splitlines()
            for key, value in claims.items():
                marked = [line for line in lines if re.match(r'^\s*' + re.escape(key) + r'\s*=', line)]
                c.require(marked == [key + '=' + value], 'FINAL_CLAIM_MISMATCH')
            _in_window(event.get('timestamp'), start, deadline)
            found.append({'source_path': str(log), 'line': line_number,
                          'byte_offset': offset, 'byte_length': len(raw),
                          'raw_record_sha256': c.sha(raw), 'timestamp': event['timestamp'],
                          'claims': claims})
    c.require(len(found) == 1, 'EXACT_FINAL_CLAIM_NOT_UNIQUE')
    return found[0]


def _check_final_ref(item, allowed):
    normal = _normal(item['source_path'])
    c.require(normal in allowed, 'SOURCE_PATH_NOT_ALLOWLISTED')
    log = c.absolute(allowed[normal])
    with log.open('rb') as stream:
        stream.seek(item['byte_offset'])
        raw = stream.read(item['byte_length'])
    c.require(c.sha(raw) == item['raw_record_sha256'], 'FINAL_RECORD_CHANGED')


def _report(report, inputs, inputs_sha):
    c.require(isinstance(report, dict) and set(report) == REPORT_FIELDS, 'REPORT_SCHEMA')
    c.require(report['schema'] == 'singlepaper.semantic_review.v1'
              and report['input_sha256'] == inputs_sha, 'STALE_REPORT')
    for field, expected, kind in (
        ('checked_pages', list(range(1, inputs['page_count'] + 1)), int),
        ('checked_formula_ids', inputs['formula_ids'], str),
        ('checked_figure_numbers', inputs['figure_numbers'], int),
        ('checked_reference_numbers', inputs['reference_numbers'], int),
    ):
        actual = report[field]
        c.require(type(actual) is list and all(type(value) is kind for value in actual)
                  and actual == expected, 'REVIEW_COVERAGE_' + field.upper())
    c.require(report['cross_page_checked'] is True, 'CROSS_PAGE_REVIEW_REQUIRED')
    c.require(report['verdict'] in ('PASS', 'BLOCK') and type(report['findings']) is list,
              'REPORT_VERDICT_SCHEMA')
    note = report['scope_note']
    c.require(isinstance(note, str) and bool(re.search(r'[\u3400-\u9fff]', note)),
              'REPORT_CHINESE_SCOPE_REQUIRED')
    c.require(report['verdict'] == 'PASS' and report['findings'] == [], 'REVIEW_BLOCKED')


def check(package, run, report_path, author_capture, reviewer_capture, host_context, active=True):
    """Return deterministic evidence after recomputing all protected inputs.

    ``host_context`` is the coordinator-owned {root, turn, allowed_log_paths};
    the caller must bind it to immutable run/HOST_CONTEXT.json before invoking.
    Capture paths never extend that authority. ``active=False`` is solely for
    historical read-only verification, with original execution timestamps still
    restricted to the unchanged input session (at most 60 minutes).
    """
    c.require(type(active) is bool, 'ACTIVE_FLAG_SCHEMA')
    package, run = c.absolute(package), c.absolute(run)
    allowed_paths = _host(host_context)
    allowed = {_normal(path): path for path in allowed_paths}
    context_bytes = c.encode(host_context)
    capture_bytes = [c.encode(value) for value in (author_capture, reviewer_capture)]
    inp, inputs, inputs_sha = documents.verify_review_inputs(package, run, active=active)
    start, deadline = c.parse_time(inp['created_utc']), c.parse_time(inp['deadline_utc'])
    c.require(timedelta(0) < deadline - start <= timedelta(minutes=60), 'DEADLINE_CONTRACT')
    input_sha = inputs['input_sha256']

    report_path = Path(report_path).absolute()
    c.require(report_path.is_relative_to(run), 'REPORT_MUST_BE_IN_RUN')
    report_path = c.safe(run, report_path.relative_to(run).as_posix())
    report_bytes = report_path.read_bytes()
    report = c.loads(report_bytes)
    _report(report, inputs, inputs_sha)
    report_sha = c.sha(report_bytes)
    identities, final_refs = [], []
    for role, capture, bound_input, claims in (
        ('AUTHOR', author_capture, input_sha,
         {'INPUT_SHA256': input_sha, 'AUTHOR_OUTPUT_SHA256': inputs_sha}),
        ('REVIEWER', reviewer_capture, inputs_sha,
         {'INPUT_SHA256': inputs_sha, 'REPORT_SHA256': report_sha}),
    ):
        task = '/root/' + role.lower() + '_' + bound_input
        identity = verify_dispatch_input(capture, host_context['root'], host_context['turn'],
                                        task, allowed_paths, role=role,
                                        input_sha256=bound_input, binding_mode='task_name_v2')
        _execution_times(capture, identity, start, deadline)
        # Match lexically before inspecting any capture-supplied filesystem path.
        capture_path = capture['child']['source_path']
        c.require(isinstance(capture_path, str) and _normal(capture_path) in allowed,
                  'SOURCE_PATH_NOT_ALLOWLISTED')
        log = allowed[_normal(capture_path)]
        final_ref = _final_claim(log, identity['child_turn_id'], claims, start, deadline,
                                 capture['child']['first_delegation']['ref']['byte_offset'])
        identities.append(identity)
        final_refs.append({'role': role, **final_ref})
    c.require(identities[0]['child_thread_id'] != identities[1]['child_thread_id'], 'SAME_ACTUAL_TASK')
    c.require(identities[0]['child_turn_id'] != identities[1]['child_turn_id'], 'SAME_ACTUAL_TURN')

    repeated = documents.verify_review_inputs(package, run, expected_sha=inputs_sha, active=active)
    c.require(repeated == (inp, inputs, inputs_sha), 'REVIEW_CHANGED_DURING_VERIFICATION')
    c.require(report_path.read_bytes() == report_bytes, 'REPORT_CHANGED_DURING_VERIFICATION')
    c.require(c.encode(host_context) == context_bytes and
              [c.encode(x) for x in (author_capture, reviewer_capture)] == capture_bytes,
              'EVIDENCE_CONTEXT_CHANGED')
    for item in final_refs:
        _check_final_ref(item, allowed)
    # Re-read identity refs too: neither a capture summary nor a once-read log
    # can mask a change that happened while document reconstruction was running.
    for identity, capture in zip(identities, (author_capture, reviewer_capture)):
        again = verify_dispatch_input(capture, host_context['root'], host_context['turn'],
                                      identity['task_path'], allowed_paths, role=identity['role'],
                                      input_sha256=identity['input_sha256'], binding_mode='task_name_v2')
        c.require(again == identity, 'TASK_IDENTITY_CHANGED')
    if active:
        documents._active(inp)
    return {
        'schema': 'singlepaper.review_verified.v1', 'ok': True,
        'status': 'SEMANTIC_REVIEW_VERIFIED_CLIENT_PENDING',
        'input_sha256': input_sha, 'review_input_sha256': inputs_sha, 'report_sha256': report_sha,
        'review_inputs': c.ref(run, run / 'REVIEW_INPUTS.json'), 'report': c.ref(run, report_path),
        'host_context_sha256': c.sha(context_bytes),
        'capture_sha256': [c.sha(value) for value in capture_bytes],
        'identities': identities, 'task_final_refs': final_refs,
        'obsidian_reading': 'NOT_VERIFIED', 'publication_status': 'NOT_PUBLISHED',
        'scientific_acceptance': 'NONE', 'formal_processing_allowed': False,
        'scope_note': '已重算逐页输入并核验不同实际任务及报告；客户端阅读、发布权限与科学接受另行判断。',
        'trust_boundary': 'Same-user local host records; no tamper isolation, backend model attestation, or encrypted child-body equivalence.',
    }
