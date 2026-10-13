"""Read-only ZIP validation followed by fresh safe extraction and byte checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import zipfile


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('DUPLICATE_JSON_KEY')
        value[key] = item
    return value


def safe_name(name: str) -> None:
    win = PureWindowsPath(name)
    if not name or '\\' in name or ':' in name or win.drive or win.is_absolute():
        raise ValueError('UNSAFE_ZIP_PATH')
    for part in name.split('/'):
        if (part in ('', '.', '..') or part.endswith((' ', '.'))
                or any(ord(c) < 32 or c in '<>"|?*' for c in part)
                or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I)):
            raise ValueError('UNSAFE_ZIP_PATH')


def no_reparse(path: Path) -> None:
    for part in (path, *path.parents):
        if os.path.lexists(part):
            info = part.lstat()
            if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('REPARSE_PATH')


def verify(zip_path: Path, destination: Path, expected_files: list[dict] | None = None) -> dict:
    no_reparse(zip_path)
    no_reparse(destination)
    destination.resolve().relative_to(zip_path.parent.resolve())
    if destination.exists():
        raise ValueError('EXTRACT_DESTINATION_ALREADY_EXISTS')
    listings = []
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > 500 * 1024 * 1024:
            raise ValueError('ZIP_LIMIT_EXCEEDED')
        names = set()
        for info in infos:
            safe_name(info.filename)
            if info.is_dir() or info.flag_bits & 1 or info.file_size > 64 * 1024 * 1024:
                raise ValueError('ZIP_MEMBER_TYPE_OR_LIMIT_REJECTED')
            if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK or info.external_attr & 0x400:
                raise ValueError('ZIP_LINK_REJECTED')
            folded = info.filename.casefold()
            if folded in names:
                raise ValueError('ZIP_DUPLICATE_OR_CASE_ALIAS')
            names.add(folded)
        for name in names:
            parts = name.split('/')
            if any('/'.join(parts[:end]) in names for end in range(1, len(parts))):
                raise ValueError('ZIP_FILE_DIRECTORY_ALIAS')
        doc = json.loads(z.read('RELEASE_FILE_MANIFEST.json').decode('utf-8'), object_pairs_hook=unique_pairs)
        records = doc['files']
        if expected_files is not None and records != expected_files:
            raise ValueError('ZIP_MANIFEST_DIFFERENT_FROM_FROZEN_PLAN')
        expected = {item['path']: item for item in records}
        if len(expected) != len(records) or set(z.namelist()) != set(expected) | {'RELEASE_FILE_MANIFEST.json'}:
            raise ValueError('ZIP_MEMBER_ALLOWLIST_MISMATCH')
        for info in infos:
            data = z.read(info.filename)
            record = {'path': info.filename, 'bytes': len(data), 'sha256': sha(data),
                      'compressed_bytes': info.compress_size, 'crc32': f'{info.CRC:08x}'}
            if info.filename in expected:
                item = expected[info.filename]
                if record['sha256'] != item['sha256'] or record['bytes'] != item['bytes']:
                    raise ValueError('ZIP_PAYLOAD_HASH_MISMATCH')
            listings.append(record)
        # All path and payload checks pass before the first write.
        destination.mkdir(parents=True)
        for info in infos:
            path = destination / info.filename
            no_reparse(path)
            path.resolve().relative_to(destination.resolve())
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as handle:
                handle.write(z.read(info.filename))
    actual = {path.relative_to(destination).as_posix() for path in destination.rglob('*') if path.is_file()}
    if actual != {item['path'] for item in listings}:
        raise ValueError('EXTRACTED_SET_MISMATCH')
    for item in listings:
        path = destination / item['path']
        no_reparse(path)
        if path.stat().st_size != item['bytes'] or sha(path.read_bytes()) != item['sha256']:
            raise ValueError('EXTRACTED_HASH_MISMATCH')
    return {'status': 'PASS', 'zip_sha256': sha(zip_path.read_bytes()),
            'zip_bytes': zip_path.stat().st_size, 'zip_entries': len(listings),
            'payload_files': len(expected), 'extracted_files': len(actual),
            'zip_listing': listings, 'content_hashes_and_exact_set': 'PASS',
            'safe_extraction_and_actual_hashes': 'PASS', 'workflow_self_test': 'NOT_RUN'}


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument('--zip', required=True); p.add_argument('--destination', required=True)
    args = p.parse_args()
    value = verify(Path(args.zip).resolve(), Path(args.destination).resolve())
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    main()
