"""Freeze an explicit public allowlist and export a reviewable candidate ZIP.

No network, publishing or installer. A changed input requires a new plan. ZIP
metadata is fixed and no engineering/run/log/credential paths are traversed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import zipfile

LAB = Path(__file__).resolve().parent.parent
PACKAGE = LAB / 'package' if (LAB / 'package/app').is_dir() else LAB
PRODUCT = 'LLM-Wiki-Literature'
VERSION = '0.1.0'
ROOT_FILES = ('README.md', 'REQUIREMENTS.md', 'USER_GUIDE.md', 'AI_GUIDE.md',
              'AGENTS.md', 'launch.py', 'start.cmd', 'LICENSE', 'THIRD_PARTY_NOTICES.md')
APP_FILES = ('__init__.py', 'cli.py', 'client.py', 'common.py', 'core.py', 'documents.py',
             'environment.py', 'evidence.py', 'host.py', 'page_protocol.py', 'review.py', 'storage.py', 'workflow.py')
TEST_FILES = ('test_cli.py', 'test_client.py', 'test_documents.py', 'test_environment.py',
              'test_host.py', 'test_page_protocol.py', 'test_review.py', 'test_storage.py')
DOC_FILES = ('FILE_GUIDE.md', 'literature-panorama.png', 'literature-panorama.svg',
             'panorama-content.json', 'PANORAMA.md', 'RELEASE_NOTES.md', 'SOURCES_AND_FIRECRAWL.md')
EXAMPLE_FILES = ('MANIFEST.json', 'SYNTHETIC_READABLE_TWO_PAGES.pdf',
                 'SYNTHETIC_WORKFLOW_A.pdf', 'SYNTHETIC_WORKFLOW_B.pdf')
BUILD_FILES = ('acquire_runtime.ps1', 'acquire_license_materials.ps1', 'rebuild_runtime.py',
               'prepare_notices.py', 'complete_notices.py', 'export_release.py', 'verify_export.py', 'BUILD_RECIPE.md')
COMPONENT_FILES = ('DEPENDENCIES_LOCK.json', 'RUNTIME_SOURCES.json', 'LICENSE_SOURCE_PROVENANCE.json',
                   'CPython-3.13.16.spdx.json', 'CPython-3.13.16.sigstore')
FORBIDDEN_PARTS = {'__pycache__', '.git', '.work', '.system', '.codex', '.aws',
                   'engineering', 'run', 'runs', 'sessions', 'downloads', 'runtime-stage-001'}
# Auxiliary checks for common personal folders; not a complete path filter.
# The exact payload allowlist and a separate privacy review remain required.
PRIVATE_TEXT = (re.compile(r'(?i)[A-Z]:[\\/]+(?:Users|Documents and Settings)[\\/]'),
                re.compile(r'(?i)[A-Z]:[\\/]+(?:Codex|OneDrive)[\\/]'),
                re.compile(r'(?i)01a[0-9a-f]{5}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'),
                re.compile(r'sk-[A-Za-z0-9_-]{24,}'),
                re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'))
GENERATED_MANIFEST = 'RELEASE_FILE_MANIFEST.json'
FINAL_DOCUMENTS = {'README.md', 'REQUIREMENTS.md', 'USER_GUIDE.md', 'AI_GUIDE.md',
                   'docs/RELEASE_NOTES.md', 'docs/FILE_GUIDE.md', 'docs/PANORAMA.md'}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('DUPLICATE_JSON_KEY')
        value[key] = item
    return value


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)


def encode(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def no_reparse(path: Path) -> None:
    for item in (path, *path.parents):
        if os.path.lexists(item):
            info = item.lstat()
            if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('REPARSE_PATH')


def safe_name(name: str) -> str:
    win = PureWindowsPath(name)
    if not name or '\\' in name or ':' in name or win.drive or win.is_absolute():
        raise ValueError('INVALID_RELATIVE_PATH')
    for part in name.split('/'):
        if (part in ('', '.', '..') or part.endswith((' ', '.'))
                or any(ord(c) < 32 or c in '<>"|?*' for c in part)
                or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I)):
            raise ValueError('INVALID_RELATIVE_PATH')
    return name


def in_lab(path: Path) -> Path:
    no_reparse(path)
    path.resolve().relative_to(LAB.resolve())
    return path


def put_new(path: Path, data: bytes) -> None:
    in_lab(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(data)


def inspect_input(source: Path, destination: str, runtime: bool = False) -> dict:
    safe_name(destination)
    if any(part.casefold() in FORBIDDEN_PARTS for part in destination.split('/')):
        raise ValueError('FORBIDDEN_EXPORT_PATH')
    if destination.endswith('.pyc') and not (runtime and destination.startswith('runtime/python/Lib/')):
        raise ValueError('GENERATED_BYTECODE_REJECTED')
    in_lab(source)
    if not source.is_file():
        raise ValueError('ALLOWLIST_FILE_MISSING: ' + destination)
    data = source.read_bytes()
    if not runtime and not destination.startswith('licenses/'):
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = None
        if text and any(pattern.search(text) for pattern in PRIVATE_TEXT):
            raise ValueError('PRIVATE_DATA_IN_PUBLIC_INPUT: ' + destination)
    return {'path': destination, 'source': source.relative_to(LAB).as_posix(),
            'bytes': len(data), 'sha256': sha(data)}


def select_files(kind: str) -> list[dict]:
    selected = [inspect_input(PACKAGE / name, name) for name in ROOT_FILES]
    for prefix, names in (('app', APP_FILES), ('tests', TEST_FILES), ('docs', DOC_FILES), ('examples', EXAMPLE_FILES)):
        selected.extend(inspect_input(PACKAGE / prefix / name, prefix + '/' + name) for name in names)
    selected.append(inspect_input(PACKAGE / 'scripts/check-tests.py', 'scripts/check-tests.py'))
    selected.extend(inspect_input(PACKAGE / 'components' / name, 'components/' + name) for name in COMPONENT_FILES)
    licenses = read_json(PACKAGE / 'licenses/THIRD_PARTY_LICENSES.json')
    selected.append(inspect_input(PACKAGE / 'licenses/THIRD_PARTY_LICENSES.json', 'licenses/THIRD_PARTY_LICENSES.json'))
    for item in licenses['files']:
        name = safe_name(item['path'])
        if not name.startswith('licenses/'):
            raise ValueError('NOTICE_PATH_OUTSIDE_LICENSES')
        entry = inspect_input(PACKAGE / name, name)
        if entry['sha256'] != item['sha256'] or entry['bytes'] != item['bytes']:
            raise ValueError('ORIGINAL_NOTICE_CHANGED')
        selected.append(entry)
    selected.extend(inspect_input(LAB / 'build' / name, 'build/' + name) for name in BUILD_FILES)
    if kind == 'windows-x64':
        selected.append(inspect_input(PACKAGE / 'RUNTIME_MANIFEST.json', 'RUNTIME_MANIFEST.json'))
        runtime = read_json(PACKAGE / 'RUNTIME_MANIFEST.json')
        for item in runtime['files']:
            name = 'runtime/' + safe_name(item['path'])
            entry = inspect_input(PACKAGE / name, name, runtime=True)
            if entry['sha256'] != item['sha256'] or entry['bytes'] != item['bytes']:
                raise ValueError('RUNTIME_FILE_CHANGED')
            selected.append(entry)
        actual = {p.relative_to(PACKAGE / 'runtime').as_posix()
                  for p in (PACKAGE / 'runtime').rglob('*') if p.is_file()}
        if actual != {x['path'] for x in runtime['files']}:
            raise ValueError('RUNTIME_EXTRA_OR_MISSING_FILE')
    names = [item['path'].casefold() for item in selected]
    if len(names) != len(set(names)):
        raise ValueError('EXPORT_DUPLICATE_OR_CASE_ALIAS')
    examples = read_json(PACKAGE / 'examples/MANIFEST.json')
    if examples != {'synthetic_only': True, 'files': [{'path': 'SYNTHETIC_READABLE_TWO_PAGES.pdf',
                    'sha256': '73bd893812212a8e0c21e933f032c82937790c32922057ab14d6da2968a12f4b', 'bytes': 2546}]}:
        raise ValueError('SYNTHETIC_EXAMPLE_ALLOWLIST_CHANGED')
    return sorted(selected, key=lambda item: item['path'])


def freeze(args) -> None:
    name = safe_name(args.plan_id)
    if '/' in name or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,50}', name):
        raise ValueError('INVALID_PLAN_ID')
    files = select_files(args.kind)
    license_data = (PACKAGE / 'LICENSE').read_text(encoding='utf-8')
    if not license_data.startswith('MIT License\n\nCopyright (c) 2026 LLM-Wiki-Literature contributors\n'):
        raise ValueError('PROJECT_LICENSE_UNCONFIRMED_OR_CHANGED')
    plan = {'schema': 'release.explicit_export_plan.v1', 'product': PRODUCT, 'version': VERSION,
            'kind': args.kind, 'status': 'CANDIDATE', 'created_utc': datetime.now(timezone.utc).isoformat(),
            'filename': f'{PRODUCT}-{VERSION}-{args.kind}-candidate.zip',
            'program_sha256': sha(Path(__file__).read_bytes()), 'files': files,
            'file_count': len(files), 'input_bytes': sum(item['bytes'] for item in files),
            'exclusions': ['Engineering and actual run records', 'Actual task UUIDs and personal paths',
                           'Credentials and account settings', 'Generated caches', 'Real PDF and notes',
                           'Codex/Obsidian/Firecrawl/OCR', 'Downloads and old candidate/production files'],
            'required_release_gates': ['Independent code, notice and export review',
                                       'Final documentation matches actual commands',
                                       'Exact extracted ZIP full single-paper self-test',
                                       'Explicit release approval and destination'],
            'upload': 'NOT_RUN'}
    path = LAB / 'build/export-plans' / (name + '.json')
    put_new(path, encode(plan))
    print(json.dumps({'status': 'CANDIDATE_PLAN_FROZEN', 'plan': path.relative_to(LAB).as_posix(),
                      'sha256': sha(path.read_bytes()), 'file_count': len(files), 'input_bytes': plan['input_bytes']}))


def freeze_final(args) -> None:
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,50}', args.plan_id):
        raise ValueError('INVALID_PLAN_ID')
    baseline_path = Path(args.candidate_plan).resolve()
    in_lab(baseline_path)
    baseline = read_json(baseline_path)
    if (baseline.get('schema') != 'release.explicit_export_plan.v1' or baseline.get('status') != 'CANDIDATE'
            or baseline.get('program_sha256') != sha(Path(__file__).read_bytes())):
        raise ValueError('CANDIDATE_BASELINE_OR_EXPORTER_CHANGED')
    allowed = set(args.document)
    if not allowed <= FINAL_DOCUMENTS:
        raise ValueError('FINAL_DIFF_DOCUMENT_NOT_ALLOWED')
    current = select_files(baseline['kind'])
    prior = {item['path']: item for item in baseline['files']}
    newer = {item['path']: item for item in current}
    if set(prior) != set(newer):
        raise ValueError('FINAL_FILE_SET_CHANGED_NEW_CANDIDATE_REQUIRED')
    changes = []
    for name in sorted(prior):
        if newer[name] != prior[name]:
            if name not in allowed:
                raise ValueError('FINAL_NONAPPROVED_INPUT_CHANGED_NEW_CANDIDATE_REQUIRED: ' + name)
            changes.append({'path': name, 'before_sha256': prior[name]['sha256'],
                            'after_sha256': newer[name]['sha256'],
                            'before_bytes': prior[name]['bytes'], 'after_bytes': newer[name]['bytes']})
    plan = {**baseline, 'status': 'LOCAL_FINAL_UNPUBLISHED',
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'filename': f"{PRODUCT}-{VERSION}-{baseline['kind']}.zip",
            'files': current, 'input_bytes': sum(item['bytes'] for item in current),
            'candidate_plan_sha256': sha(baseline_path.read_bytes()),
            'allowed_document_changes': sorted(allowed), 'actual_document_changes': changes,
            'code_runtime_and_examples_equal_to_candidate': True,
            'workflow_acceptance': 'Separate parent-owned actual workflow evidence; not certified by this exporter'}
    out = LAB / 'build/export-plans' / (args.plan_id + '.json')
    put_new(out, encode(plan))
    print(json.dumps({'status': 'LOCAL_FINAL_PLAN_FROZEN', 'plan': out.relative_to(LAB).as_posix(),
                      'sha256': sha(out.read_bytes()), 'document_changes': changes,
                      'code_runtime_and_examples_equal_to_candidate': True}))


def load_frozen(plan_path: Path) -> dict:
    in_lab(plan_path)
    plan = read_json(plan_path)
    if (plan.get('schema') != 'release.explicit_export_plan.v1' or plan.get('status') not in ('CANDIDATE', 'LOCAL_FINAL_UNPUBLISHED')
            or plan.get('program_sha256') != sha(Path(__file__).read_bytes())):
        raise ValueError('PLAN_SCHEMA_OR_PROGRAM_CHANGED')
    actual = select_files(plan['kind'])
    if actual != plan['files']:
        raise ValueError('PLAN_INPUT_CHANGED_NEW_PLAN_REQUIRED')
    return plan


def zip_entry(name: str, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    safe_name(name)
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info, data


def export(args) -> None:
    path = Path(args.plan).resolve()
    plan = load_frozen(path)
    out_dir = LAB / ('dist/candidates' if plan['status'] == 'CANDIDATE' else 'dist/local-final') / path.stem
    in_lab(out_dir)
    if out_dir.exists():
        raise ValueError('CANDIDATE_OUTPUT_ALREADY_EXISTS')
    out_dir.mkdir(parents=True)
    zip_path = out_dir / plan['filename']
    public = {'schema': 'release.file_manifest.v1', 'product': PRODUCT, 'version': VERSION,
              'kind': plan['kind'], 'status': plan['status'],
              'files': [{k: item[k] for k in ('path', 'bytes', 'sha256')} for item in plan['files']],
              'manifest_scope': 'All payload files excluding this generated manifest itself',
              'signature_verification': 'NOT_RUN', 'upload': 'NOT_RUN'}
    with zipfile.ZipFile(zip_path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for item in plan['files']:
            source = LAB / item['source']
            data = source.read_bytes()
            if sha(data) != item['sha256'] or len(data) != item['bytes']:
                raise ValueError('EXPORT_INPUT_CHANGED')
            info, data = zip_entry(item['path'], data)
            z.writestr(info, data)
        info, data = zip_entry(GENERATED_MANIFEST, encode(public))
        z.writestr(info, data)
    from importlib.util import module_from_spec, spec_from_file_location
    verifier_path = Path(__file__).parent / 'verify_export.py'
    spec = spec_from_file_location('release_zip_verifier', verifier_path)
    verifier = module_from_spec(spec)
    spec.loader.exec_module(verifier)
    verification = verifier.verify(zip_path, out_dir / 'extracted', expected_files=public['files'])
    receipt = {'schema': 'release.candidate_export_receipt.v1', 'status': plan['status'] + '_ZIP_CONTENT_AND_EXTRACTION_VERIFIED',
               'plan_sha256': sha(path.read_bytes()), 'zip_filename': zip_path.name,
               'zip_sha256': sha(zip_path.read_bytes()), 'zip_bytes': zip_path.stat().st_size,
               'verification': verification, 'workflow_acceptance': 'Separate parent-owned actual workflow evidence', 'upload': 'NOT_RUN'}
    put_new(out_dir / 'EXPORT_RECEIPT.json', encode(receipt))
    print(json.dumps(receipt))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan'); p.add_argument('--kind', choices=('source', 'windows-x64'), required=True); p.add_argument('--plan-id', required=True)
    p = sub.add_parser('final-plan'); p.add_argument('--candidate-plan', required=True); p.add_argument('--plan-id', required=True)
    p.add_argument('--document', action='append', default=[])
    p = sub.add_parser('export'); p.add_argument('--plan', required=True)
    args = parser.parse_args()
    if args.command == 'plan':
        freeze(args)
    elif args.command == 'final-plan':
        freeze_final(args)
    else:
        export(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
