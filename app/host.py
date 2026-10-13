"""Current-task Codex metadata capture, without body export or log rewriting.

Environment UUIDs are hints. Exact filename, raw session/turn/dispatch records
and the unchanged evidence verifier must agree before a context is returned.
Capture/document paths never grant filesystem read authority. Host records are
same-user evidence, with no tamper isolation or provider attestation.
"""
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
import sqlite3

from . import core as c, evidence

MAX_LOG_BYTES = 512 * 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024
UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')
META_FIELDS = ('id', 'session_id', 'timestamp', 'cwd', 'originator', 'cli_version', 'model_provider', 'source', 'thread_source')
TRUST = 'Same-user local host records; no tamper isolation or backend model attestation.'


def _uuid(value, code):
    c.require(isinstance(value, str) and UUID.fullmatch(value), code)
    return value


def process_identity():
    return {'root': _uuid(os.environ.get('CODEX_SESSION_ID'), 'CURRENT_CODEX_SESSION_REQUIRED'),
            'thread': _uuid(os.environ.get('CODEX_THREAD_ID'), 'CURRENT_CODEX_THREAD_REQUIRED')}


def _codex_home():
    value = os.environ.get('CODEX_HOME')
    base = Path(value) if value else Path.home() / '.codex'
    c.require(base.is_absolute(), 'CODEX_HOME_MUST_BE_ABSOLUTE')
    return c.absolute(base)


def _sessions():
    return c.absolute(_codex_home() / 'sessions')


def _day_path(path):
    c.require(Path(path).is_absolute(), 'EXPLICIT_ABSOLUTE_DAY_REQUIRED')
    path = c.absolute(path, False)
    relative = path.relative_to(_sessions()) if path.is_relative_to(_sessions()) else None
    c.require(relative is not None and len(relative.parts) == 3, 'DAY_DIRECTORY_OUTSIDE_CODEX_SESSIONS')
    c.require(all(re.fullmatch(r'\d{' + str(size) + '}', part)
                  for part, size in zip(relative.parts, (4, 2, 2))), 'DAY_DIRECTORY_SHAPE')
    datetime.strptime('/'.join(relative.parts), '%Y/%m/%d')
    return path


def day_directories(extra=()):
    today = datetime.now().astimezone().date()
    days = [_sessions() / (today - timedelta(days=number)).strftime('%Y/%m/%d') for number in (0, 1)]
    days.extend(_day_path(path) for path in extra)
    unique = {}
    for path in days:
        c.no_reparse(path)
        unique[os.path.normcase(str(path))] = path
    return list(unique.values())


def _log_path(path, thread_id):
    value = os.fspath(path)
    if value.startswith('\\\\?\\'):
        c.require(re.match(r'^\\\\\?\\[A-Za-z]:\\', value), 'INDEX_NONLOCAL_PATH')
        path = value[4:]
    c.require(Path(path).is_absolute(), 'EXPLICIT_ABSOLUTE_LOG_REQUIRED')
    path = c.absolute(path)
    _day_path(path.parent)
    expected = (r'rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-' + re.escape(thread_id)
                + r'(?:_[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})?\.jsonl')
    c.require(path.is_file() and re.fullmatch(expected, path.name), 'LOG_FILENAME_THREAD_MISMATCH')
    return path


def locate(thread_id, days, explicit=None):
    _uuid(thread_id, 'SELECTED_THREAD_UUID_INVALID')
    index = c.absolute(_codex_home() / 'state_5.sqlite')
    connection = None
    try:
        connection = sqlite3.connect(index.as_uri() + '?mode=ro', uri=True)
        connection.execute('PRAGMA query_only=ON')
        columns = {row[1]: (row[2].upper(), row[3], row[5]) for row in connection.execute('PRAGMA table_info(threads)')}
        expected = {'id': ('TEXT', 0, 1), 'rollout_path': ('TEXT', 1, 0), 'history_mode': ('TEXT', 1, 0)}
        c.require(all(columns.get(key) == value for key, value in expected.items()), 'CURRENT_THREAD_INDEX_SCHEMA')
        rows = connection.execute('SELECT id,rollout_path,history_mode FROM threads WHERE id=?', (thread_id,)).fetchall()
        c.require(len(rows) == 1 and rows[0][0] == thread_id, 'CURRENT_THREAD_INDEX_ROW_REQUIRED')
        value, mode = rows[0][1:]
        c.require(isinstance(value, str) and mode in ('legacy', 'paginated'), 'CURRENT_THREAD_INDEX_ROW_SCHEMA')
    except sqlite3.Error:
        raise c.Rejected('CURRENT_THREAD_INDEX_SCHEMA') from None
    finally:
        if connection is not None:
            connection.close()
    selected = _log_path(value, thread_id)
    if explicit is not None:
        declared = _log_path(explicit, thread_id)
        c.require(os.path.normcase(str(declared)) == os.path.normcase(str(selected)), 'INDEX_EXPLICIT_PATH_CONFLICT')
    return selected


def closed_turn(payload, active_turn):
    if isinstance(payload, dict) and payload.get('type') in ('task_complete', 'turn_aborted', 'shutdown_complete'):
        return payload.get('turn_id') or active_turn
    return None


def _records(path):
    """Yield complete bounded records; never return an incomplete live tail."""
    c.no_reparse(path)
    with path.open('rb') as stream:
        boundary = os.fstat(stream.fileno()).st_size
        c.require(boundary <= MAX_LOG_BYTES, 'HOST_LOG_SIZE_LIMIT')
        number = 0
        while stream.tell() < boundary:
            offset = stream.tell()
            raw = stream.readline(min(MAX_RECORD_BYTES + 1, boundary - offset))
            c.require(len(raw) <= MAX_RECORD_BYTES, 'HOST_RECORD_SIZE_LIMIT')
            if not raw.endswith(b'\n'):
                c.require(stream.tell() == boundary, 'HOST_RECORD_INCOMPLETE')
                break
            number += 1
            record = c.loads(raw)
            c.require(isinstance(record, dict), 'HOST_RECORD_SCHEMA')
            ref = {'line': number, 'byte_offset': offset, 'byte_length': len(raw),
                   'raw_record_sha256': c.sha(raw), 'timestamp': record.get('timestamp')}
            yield record.get('type'), record.get('payload'), ref


def _first_meta(path, expected_thread, root, task=None):
    iterator = _records(path)
    try:
        kind, payload, ref = next(iterator)
        c.require(kind == 'session_meta' and isinstance(payload, dict), 'FIRST_SESSION_METADATA_REQUIRED')
        c.require(payload.get('id') == expected_thread and payload.get('session_id') == root, 'HOST_LOG_IDENTITY_MISMATCH')
        if task is None:
            c.require(expected_thread == root and payload.get('thread_source') == 'user', 'HOST_ROOT_IDENTITY_MISMATCH')
        else:
            source = payload.get('source')
            c.require(isinstance(source, dict) and set(source) == {'subagent'}, 'HOST_CHILD_SOURCE_REQUIRED')
            subagent = source['subagent']
            c.require(isinstance(subagent, dict) and set(subagent) == {'thread_spawn'}, 'HOST_CHILD_SPAWN_REQUIRED')
            spawn = subagent['thread_spawn']
            c.require(isinstance(spawn, dict) and spawn.get('parent_thread_id') == root
                      and type(spawn.get('depth')) is int and spawn['depth'] == 1
                      and spawn.get('agent_path') == task and payload.get('thread_source') == 'subagent',
                      'HOST_CHILD_CURRENT_TASK_MISMATCH')
        return payload, ref
    finally:
        iterator.close()


def _scalars(value, names):
    result = {}
    for key in names:
        if key in value:
            c.require(isinstance(value[key], (str, int, float, bool, type(None))), 'HOST_FIELD_SHAPE')
            result[key] = value[key]
    return result


def _turn_fields(payload):
    c.require(isinstance(payload, dict), 'HOST_TURN_SCHEMA')
    fields = _scalars(payload, ('turn_id', 'root_turn_id', 'model', 'effort', 'current_date', 'timezone', 'multi_agent_version'))
    mode = payload.get('collaboration_mode')
    c.require(isinstance(mode, dict) and isinstance(mode.get('settings'), dict), 'HOST_RUNTIME_SETTINGS_REQUIRED')
    fields['collaboration_settings'] = _scalars(mode['settings'], ('model', 'reasoning_effort'))
    return fields


def parent_identity(path, root):
    meta, meta_ref = _first_meta(path, root, root)
    turns, metadata, closed, active = [], [], set(), None
    for kind, payload, ref in _records(path):
        if kind == 'session_meta':
            metadata.append(ref)
        elif kind == 'turn_context':
            c.require(isinstance(payload, dict), 'HOST_TURN_SCHEMA')
            active = payload.get('turn_id')
            turns.append({'ref': ref, 'payload': payload})
        elif kind == 'event_msg':
            ended = closed_turn(payload, active)
            if ended is not None:
                closed.add(ended)
    c.require(len(metadata) == 1 and turns, 'HOST_PARENT_METADATA_OR_TURN_NOT_UNIQUE')
    latest = turns[-1]
    turn = _uuid(latest['payload'].get('turn_id'), 'HOST_CURRENT_TURN_UUID')
    c.require(turn not in closed, 'HOST_PARENT_TURN_CLOSED')
    consumed = [{'ref': entry['ref'], 'fields': _turn_fields(entry['payload'])}
                for entry in turns if entry['payload'].get('turn_id') == turn]
    reader = evidence._Reader([path])
    reader.record(path, {'ref': meta_ref, 'fields': _scalars(meta, ('id', 'session_id', 'thread_source'))}, 'session_meta')
    observed = set()
    for entry in consumed:
        c.require(metadata[0]['byte_offset'] < entry['ref']['byte_offset'], 'HOST_RECORD_ORDER')
        payload = reader.record(path, entry, 'turn_context')
        observed.add(evidence._turn(payload, entry['fields'], turn, is_parent=True))
    c.require(len(observed) == 1, 'HOST_MODEL_CHANGED_WITHIN_TURN')
    model, effort = next(iter(observed))
    return {'root': root, 'turn': turn, 'model': model, 'effort': effort,
            'parent_log': str(path), 'verified_record_refs': reader.refs,
            'message_bodies_exported': False, 'trust_boundary': TRUST}


def _parent_capture(path, root, turn, task):
    result = {'source_path': str(path), 'expected_thread_id': root, 'session_metadata': [],
              'turn_contexts': [], 'collaboration_calls': [], 'collaboration_results': [],
              'agent_message_metadata': [], 'inter_agent_metadata': [], 'diagnostics': [],
              'snapshot_boundary_bytes': path.stat().st_size, 'captured_task_names': []}
    active, selected = None, set()
    for kind, payload, ref in _records(path):
        if kind == 'session_meta':
            result['session_metadata'].append({'ref': ref, 'fields': _scalars(payload, META_FIELDS)})
        elif kind == 'turn_context':
            active = payload.get('turn_id') if isinstance(payload, dict) else None
            if active == turn:
                result['turn_contexts'].append({'ref': ref, 'fields': _turn_fields(payload)})
        elif active == turn and kind == 'response_item' and isinstance(payload, dict):
            if payload.get('type') == 'function_call' and payload.get('name') == 'spawn_agent':
                args = evidence._parse_arguments(payload)
                if '/root/' + str(args.get('task_name', '')) != task:
                    continue
                fields = _scalars(payload, ('name', 'call_id'))
                fields.update(arguments=_scalars(args, ('task_name', 'target', 'model', 'reasoning_effort', 'fork_turns')),
                              argument_field_names=sorted(args))
                c.require(isinstance(args.get('message'), str), 'DISPATCH_MESSAGE_REQUIRED')
                fields['message_utf8_sha256'] = c.sha(args['message'].encode('utf-8'))
                selected.add(payload.get('call_id'))
                result['collaboration_calls'].append({'ref': ref, 'fields': fields})
            elif payload.get('type') == 'function_call_output' and payload.get('call_id') in selected:
                output = evidence._json(payload['output']) if isinstance(payload.get('output'), str) else payload.get('output')
                c.require(isinstance(output, dict), 'SPAWN_RESULT_SCHEMA')
                result['collaboration_results'].append({'ref': ref, 'fields': {
                    'call_id': payload['call_id'], 'output_field_names': sorted(output),
                    'output': _scalars(output, ('task_name', 'agent_id', 'thread_id', 'threadId', 'parent_thread_id', 'status'))}})
                if output.get('task_name') == task:
                    result['captured_task_names'].append(task)
    c.require(result['captured_task_names'] == [task], 'CURRENT_TASK_DISPATCH_NOT_UNIQUE')
    return result


def _child_capture(path, child_id, root, turn, task, parent):
    meta, _ = _first_meta(path, child_id, root, task)
    result = {'source_path': str(path), 'environment_thread_hint': child_id, 'session_metadata': None,
              'turn_context': None, 'first_delegation': None, 'diagnostics': []}
    for kind, payload, ref in _records(path):
        c.require(isinstance(payload, dict), 'HOST_CHILD_PAYLOAD_SCHEMA')
        if kind == 'session_meta':
            fields = _scalars(payload, ('id', 'session_id', 'timestamp', 'originator', 'cli_version', 'model_provider', 'thread_source'))
            fields['thread_spawn'] = _scalars(meta['source']['subagent']['thread_spawn'], ('parent_thread_id', 'depth', 'agent_path'))
            c.require(result['session_metadata'] is None, 'CHILD_METADATA_NOT_UNIQUE')
            result['session_metadata'] = {'ref': ref, 'fields': fields}
        elif kind == 'turn_context' and result['turn_context'] is None:
            fields = _turn_fields(payload)
            evidence._turn(payload, fields, turn, is_parent=False)
            result['turn_context'] = {'ref': ref, 'fields': fields}
        elif kind == 'response_item' and payload.get('type') == 'agent_message':
            c.require(result['session_metadata'] is not None and result['turn_context'] is not None, 'DELEGATION_BEFORE_IDENTITY')
            c.require(payload.get('author') == '/root' and payload.get('recipient') == task, 'FIRST_DELEGATION_ROUTE_MISMATCH')
            c.require(len(parent['collaboration_calls']) == len(parent['collaboration_results']) == 1, 'DISPATCH_NOT_UNIQUE')
            call = parent['collaboration_calls'][0]['fields']
            content = payload.get('content')
            c.require(isinstance(content, list) and content, 'DELEGATION_CONTENT_REQUIRED')
            parts = []
            for index, part in enumerate(content):
                c.require(isinstance(part, dict), 'DELEGATION_PART_SCHEMA')
                entry = {'index': index, 'type': part.get('type'), 'encrypted_content_present': 'encrypted_content' in part}
                if 'text' in part:
                    c.require(isinstance(part['text'], str), 'DELEGATION_TEXT_SCHEMA')
                    digest = c.sha(part['text'].encode('utf-8'))
                    entry.update(text_utf8_sha256=digest, text_character_count=len(part['text']),
                                 equals_parent_dispatch_hash=digest == call['message_utf8_sha256'])
                parts.append(entry)
            fields = _scalars(payload, ('id', 'author', 'recipient'))
            fields.update(content_part_metadata=parts, parent_dispatch_call_id=call['call_id'],
                          parent_dispatch_message_utf8_sha256=call['message_utf8_sha256'], body_equivalence_status='NOT_PROVEN')
            result['first_delegation'] = {'ref': ref, 'fields': fields}
            break
    c.require(all(result[key] is not None for key in ('session_metadata', 'turn_context', 'first_delegation')), 'MISSING_CHILD_IDENTITY_EVIDENCE')
    result.update(identity_link_status='VERIFIED_FROM_HOST_RECORDS',
                  read_boundary='Stopped immediately after first agent_message; later child body not inspected.')
    return result


def _capture(parent_path, child_path, root, turn, child_id, task, days):
    parent = _parent_capture(parent_path, root, turn, task)
    capture = {'schema': 'codex-host-metadata-probe-v001', 'captured_at_utc': c.utcnow().isoformat(),
               'scope': {'root_thread_id': root, 'root_turn_id': turn, 'allowed_day_directories': [str(day) for day in days],
                         'message_bodies_exported': False, 'source_logs_modified': False},
               'process_environment': {'CODEX_SESSION_ID': root, 'CODEX_THREAD_ID': child_id},
               'parent': parent, 'child': _child_capture(child_path, child_id, root, turn, task, parent),
               'child_log_opened': True, 'claim_boundary': TRUST}
    identity = evidence.verify_identity(capture, root, turn, task, [parent_path, child_path])
    return capture, identity


def _startup(run):
    seal = c.read_json(c.safe(run, 'STARTUP_COMMIT.json'))
    c.require(set(seal) == {'files'} and len(seal['files']) == 2 and
              {item['path'] for item in seal['files']} == {'STARTUP_CONTEXT.json', 'STARTUP_PROBE.json'}, 'STARTUP_SEAL_SCHEMA')
    for item in seal['files']:
        c.check_ref(run, item)
    context = c.read_json(c.safe(run, 'STARTUP_CONTEXT.json'))
    c.require(set(context) == {'root', 'turn', 'allowed_log_paths'}, 'HOST_CONTEXT_SCHEMA')
    return context


def _task(package, run, role):
    from . import documents
    c.require(role in ('AUTHOR', 'REVIEWER'), 'ROLE_REQUIRED')
    if role == 'AUTHOR':
        _, digest = documents.input_record(package, run)
    else:
        _, _, digest = documents.verify_review_inputs(package, run)
    return '/root/' + role.lower() + '_' + digest


def create_context(package, *, extra_days=(), parent_log=None, run=None, author_thread=None, reviewer_thread=None):
    env = process_identity()
    c.require(env['thread'] == env['root'], 'COORDINATOR_CONTEXT_REQUIRED')
    days = day_directories(extra_days)
    parent_path = locate(env['root'], days, parent_log)
    proof = parent_identity(parent_path, env['root'])
    context = {'root': env['root'], 'turn': proof['turn'], 'allowed_log_paths': [str(parent_path)]}
    selected = []
    if run is not None or author_thread is not None or reviewer_thread is not None:
        c.require(run is not None and author_thread is not None and reviewer_thread is not None, 'REVIEW_CONTEXT_REQUIRES_BOTH_SELECTED_TASKS')
        run = c.absolute(run)
        startup = _startup(run)
        c.require(startup['root'] == env['root'] and startup['turn'] == proof['turn'], 'HOST_TASK_CHANGED')
        c.require(set(startup['allowed_log_paths']) == {str(parent_path)}, 'STARTUP_PARENT_LOG_CHANGED')
        c.require(author_thread != reviewer_thread, 'SAME_ACTUAL_TASK')
        for role, thread_id in (('AUTHOR', author_thread), ('REVIEWER', reviewer_thread)):
            task = _task(package, run, role)
            child_path = locate(thread_id, days)
            _first_meta(child_path, thread_id, env['root'], task)
            _, identity = _capture(parent_path, child_path, env['root'], proof['turn'], thread_id, task, days)
            context['allowed_log_paths'].append(str(child_path))
            selected.append({'role': role, **identity})
    c.require(parent_identity(parent_path, env['root']) == proof, 'HOST_CONTEXT_CHANGED_DURING_CAPTURE')
    c.require(locate(env['root'], days, parent_log) == parent_path, 'HOST_INDEX_SOURCE_CHANGED')
    return context, {'identity': proof, 'selected_tasks': selected}


def capture_current(package, run, role, *, extra_days=(), parent_log=None):
    env = process_identity()
    c.require(env['thread'] != env['root'], 'MUST_RUN_IN_ACTUAL_CHILD')
    run = c.absolute(run)
    task = _task(package, run, role)
    startup = _startup(run)
    c.require(startup['root'] == env['root'], 'CURRENT_TASK_ROOT_MISMATCH')
    days = day_directories(extra_days)
    parent_path = locate(env['root'], days, parent_log)
    c.require(startup['allowed_log_paths'] == [str(parent_path)], 'STARTUP_PARENT_LOG_CHANGED')
    proof = parent_identity(parent_path, env['root'])
    c.require(proof['turn'] == startup['turn'], 'HOST_CURRENT_TURN_MISMATCH')
    child_path = locate(env['thread'], days)
    _first_meta(child_path, env['thread'], env['root'], task)
    capture, identity = _capture(parent_path, child_path, env['root'], proof['turn'], env['thread'], task, days)
    c.require(parent_identity(parent_path, env['root']) == proof, 'HOST_CONTEXT_CHANGED_DURING_CAPTURE')
    c.require(locate(env['root'], days, parent_log) == parent_path, 'HOST_INDEX_SOURCE_CHANGED')
    return capture, identity


def write_output(path, value):
    c.require(Path(path).is_absolute(), 'EXPLICIT_ABSOLUTE_OUTPUT_REQUIRED')
    path = c.absolute(path, False)
    c.require(not path.exists(), 'HOST_OUTPUT_MUST_BE_NEW')
    c.write_json_new(path, value)
    return {'output': str(path), 'sha256': c.digest(path), 'bytes': path.stat().st_size}
