"""Offline rebuild from the fixed official archives; no pip or installers.

Only reads the local locked source set. Rejects existing output, unsafe ZIP
members, RECORD inconsistencies and source hash drift before execution.
"""
from __future__ import annotations

import argparse
import base64
import csv
from email.parser import Parser
import hashlib
import io
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import zipfile


LAB = Path(__file__).resolve().parent.parent
PACKAGE = LAB / 'package' if (LAB / 'package/app').is_dir() else LAB
LOCK = PACKAGE / 'components/DEPENDENCIES_LOCK.json'
SOURCES = LAB / 'build/downloads/source-001'
ALLOWED_ROOTS = {
    'pypdf': {'pypdf', 'pypdf-6.10.0.dist-info'},
    'latex2mathml': {'latex2mathml', 'latex2mathml-3.81.0.dist-info'},
    'pypdfium2': {'pypdfium2', 'pypdfium2_cfg', 'pypdfium2_raw', 'pypdfium2_cli', 'pypdfium2-5.13.0.dist-info'},
    'pillow': {'PIL', 'pillow-12.3.0.dist-info'},
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def no_reparse(path: Path) -> None:
    for item in (path, *path.parents):
        if os.path.lexists(item):
            info = item.lstat()
            if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('REPARSE_PATH')


def inside_lab(path: Path) -> None:
    no_reparse(path)
    path.resolve().relative_to(LAB.resolve())


def safe_name(name: str) -> str:
    win = PureWindowsPath(name)
    if not name or '\\' in name or ':' in name or win.drive or win.is_absolute():
        raise ValueError('UNSAFE_ARCHIVE_PATH')
    for part in name.split('/'):
        if (part in ('', '.', '..') or part.endswith((' ', '.'))
                or any(ord(c) < 32 or c in '<>"|?*' for c in part)
                or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I)):
            raise ValueError('UNSAFE_ARCHIVE_PATH')
    return name


def validate_zip(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    seen = set()
    infos = z.infolist()
    if len(infos) > 10000 or sum(i.file_size for i in infos) > 350 * 1024 * 1024:
        raise ValueError('ARCHIVE_LIMIT_EXCEEDED')
    for info in infos:
        name = safe_name(info.filename[:-1] if info.is_dir() else info.filename)
        folded = name.casefold()
        if folded in seen:
            raise ValueError('DUPLICATE_OR_CASE_ALIAS_ARCHIVE_PATH')
        seen.add(folded)
        if (stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK
                or info.external_attr & 0x400 or info.flag_bits & 1):
            raise ValueError('ARCHIVE_LINK_OR_ENCRYPTION_REJECTED')
        if info.file_size > 64 * 1024 * 1024:
            raise ValueError('ARCHIVE_MEMBER_LIMIT_EXCEEDED')
    file_names = {i.filename.casefold() for i in infos if not i.is_dir()}
    for info in infos:
        parts = info.filename.rstrip('/').split('/')
        if any('/'.join(parts[:end]).casefold() in file_names for end in range(1, len(parts))):
            raise ValueError('ARCHIVE_FILE_DIRECTORY_ALIAS')
    return infos


def verify_record(z: zipfile.ZipFile, component_id: str) -> dict:
    records = [n for n in z.namelist() if n.endswith('.dist-info/RECORD')]
    if len(records) != 1:
        raise ValueError('WHEEL_RECORD_COUNT_INVALID')
    record_name = records[0]
    rows = list(csv.reader(io.StringIO(z.read(record_name).decode('utf-8'))))
    row_names = set()
    checked = 0
    for name, checksum, size in rows:
        safe_name(name)
        if name in row_names:
            raise ValueError('DUPLICATE_WHEEL_RECORD_ROW')
        row_names.add(name)
        data = z.read(name)
        if name != record_name:
            encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode('ascii')
            if checksum != 'sha256=' + encoded or size != str(len(data)):
                raise ValueError('WHEEL_RECORD_CHECKSUM_MISMATCH')
            checked += 1
        elif checksum or size:
            raise ValueError('WHEEL_RECORD_SELF_HASH_INVALID')
    if row_names != {i.filename for i in z.infolist() if not i.is_dir()}:
        raise ValueError('WHEEL_RECORD_INCOMPLETE')
    roots = {name.split('/')[0] for name in row_names}
    if roots != ALLOWED_ROOTS[component_id]:
        raise ValueError('WHEEL_ROOT_ALLOWLIST_MISMATCH')
    return {'component': component_id, 'record_member': record_name,
            'record_sha256': digest(z.read(record_name)), 'checked_members': checked}


def put(path: Path, data: bytes) -> None:
    inside_lab(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(data)


def json_put(path: Path, value: dict) -> None:
    put(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def extract(z: zipfile.ZipFile, destination: Path, archive: dict,
            mappings: list[dict], nested_member: str | None = None) -> None:
    infos = validate_zip(z)
    for info in infos:
        if info.is_dir():
            continue
        data = z.read(info.filename)
        if len(data) != info.file_size:
            raise ValueError('ARCHIVE_MEMBER_SIZE_MISMATCH')
        path = destination / info.filename
        put(path, data)
        mapped = {'path': path.relative_to(destination.parents[0] if destination.name in ('python', 'vendor', 'pdf-text-v1') else destination.parents[1]).as_posix(),
                  'component': archive['id'], 'archive_filename': archive['filename'],
                  'archive_sha256': archive['sha256'], 'archive_member': nested_member or info.filename,
                  'bytes': len(data), 'sha256': digest(data)}
        if nested_member:
            mapped['nested_archive_member'] = info.filename
        mappings.append(mapped)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--copy-to-package', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'runtime-stage-[0-9]{3}', args.run_id):
        raise ValueError('INVALID_RUN_ID')
    stage = LAB / 'build' / args.run_id
    inside_lab(stage)
    if stage.exists():
        raise ValueError('STAGE_ALREADY_EXISTS')
    if args.copy_to_package and (PACKAGE / 'runtime').exists():
        raise ValueError('PACKAGE_RUNTIME_ALREADY_EXISTS')
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    if [x['id'] for x in lock['components']] != ['cpython', 'pypdf', 'latex2mathml', 'pypdfium2', 'pillow']:
        raise ValueError('FIXED_COMPONENT_SET_CHANGED')
    validated = []
    for item in lock['components']:
        archive_path = SOURCES / safe_name(item['filename'])
        inside_lab(archive_path)
        data = archive_path.read_bytes()
        if len(data) != item['bytes'] or digest(data) != item['sha256']:
            raise ValueError('LOCKED_ARCHIVE_CHANGED')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            validate_zip(z)
            record = verify_record(z, item['id']) if item['kind'] == 'wheel' else None
        validated.append({'archive': item, 'data': data, 'wheel_record': record})
    # All five size/hash/path/RECORD validations pass before the first extraction.
    stage.mkdir()
    runtime = stage / 'runtime'
    mappings = []
    for item in validated:
        archive = item['archive']
        with zipfile.ZipFile(io.BytesIO(item['data'])) as z:
            extract(z, runtime / archive['destination'], archive, mappings)
    python_archive = validated[0]['archive']
    stdlib_path = runtime / 'python/python313.zip'
    with zipfile.ZipFile(stdlib_path) as z:
        extract(z, runtime / 'python/Lib', python_archive, mappings, nested_member='python313.zip')
    pth = runtime / 'python/python313._pth'
    original_pth = pth.read_bytes()
    replacement = b'Lib\r\npython313.zip\r\n.\r\n'
    pth.write_bytes(replacement)
    for mapping in mappings:
        if mapping['path'] == 'python/python313._pth':
            mapping['original_sha256'] = mapping['sha256']
            mapping['original_bytes'] = mapping['bytes']
            mapping['sha256'] = digest(replacement)
            mapping['bytes'] = len(replacement)
            mapping['transform'] = 'Explicit isolated search path; Lib, python313.zip, .; import site remains disabled'
    files = []
    for path in sorted(runtime.rglob('*')):
        no_reparse(path)
        if path.is_file():
            files.append({'path': path.relative_to(runtime).as_posix(),
                          'sha256': digest(path.read_bytes()), 'bytes': path.stat().st_size})
    mapped_by_name = {entry['path']: entry for entry in mappings}
    if len(mapped_by_name) != len(files):
        raise ValueError('SOURCE_MAPPING_NOT_BIJECTIVE')
    for file in files:
        mapped = mapped_by_name[file['path']]
        if mapped['sha256'] != file['sha256'] or mapped['bytes'] != file['bytes']:
            raise ValueError('EXTRACTED_SOURCE_MAPPING_MISMATCH')
    manifest = {'schema': 'release.runtime_manifest.v1',
                'status': 'OFFICIAL_ARCHIVE_HASHES_AND_SOURCE_MAP_VERIFIED',
                'platform': 'Windows x64', 'python': '3.13.16',
                'source_lock_sha256': digest(LOCK.read_bytes()), 'files': files}
    sources = {'schema': 'release.runtime_sources.v1',
               'archives': [{k: x['archive'][k] for k in ('id', 'version', 'filename', 'url', 'sha256', 'bytes')}
                            for x in validated], 'files': mappings,
               'wheel_records': [x['wheel_record'] for x in validated if x['wheel_record']],
               'transform': {'path': 'python/python313._pth',
                             'original_utf8': original_pth.decode('utf-8'),
                             'original_sha256': digest(original_pth),
                             'result_sha256': digest(replacement),
                             'note': 'No interpreter source changes; stdlib ZIP copied and safely unpacked without recompiling'},
               'signature_cryptographic_verification': 'NOT_RUN'}
    json_put(stage / 'RUNTIME_MANIFEST.json', manifest)
    json_put(stage / 'RUNTIME_SOURCES.json', sources)
    if args.copy_to_package:
        target = PACKAGE / 'runtime'
        inside_lab(runtime)
        inside_lab(target)
        if target.exists():
            raise ValueError('PACKAGE_RUNTIME_ALREADY_EXISTS')
        destinations = [(PACKAGE / 'RUNTIME_MANIFEST.json', (stage / 'RUNTIME_MANIFEST.json').read_bytes()),
                        (PACKAGE / 'components/RUNTIME_SOURCES.json', (stage / 'RUNTIME_SOURCES.json').read_bytes())]
        for destination, data in destinations:
            inside_lab(destination)
            if destination.exists() and destination.read_bytes() != data:
                raise ValueError('EXISTING_RUNTIME_REFERENCE_CHANGED')
        # Source and target absolute paths are verified within this one lab.
        runtime.rename(target)
        for destination, data in destinations:
            if not destination.exists():
                put(destination, data)
    summary = {'schema': 'release.runtime_rebuild_receipt.v1', 'status': 'PASS',
               'runtime_files': len(files), 'runtime_bytes': sum(x['bytes'] for x in files),
               'manifest_sha256': digest((stage / 'RUNTIME_MANIFEST.json').read_bytes()),
               'runtime_sources_sha256': digest((stage / 'RUNTIME_SOURCES.json').read_bytes()),
               'materialized_to_package': args.copy_to_package,
               'source_archives_size_sha256': 'PASS', 'safe_zip_paths': 'PASS', 'wheel_records': 'PASS',
               'source_mapping_and_actual_files': 'PASS', 'runtime_executed': False,
               'signature_cryptographic_verification': 'NOT_RUN',
               'public_release': 'CANDIDATE_LICENSE_AND_INTEGRATION_REVIEW_PENDING'}
    json_put(stage / 'REBUILD_RECEIPT.json', summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
