"""Add the exact SQLite/xz materials and preserve the first notice manifest."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
PACKAGE = LAB / 'package' if (LAB / 'package/app').is_dir() else LAB
DOWNLOADS = LAB / 'build/downloads/source-001'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    manifest_path = PACKAGE / 'licenses/THIRD_PARTY_LICENSES.json'
    old = manifest_path.read_bytes()
    saved = LAB / 'engineering/supply/THIRD_PARTY_LICENSES.initial.json'
    saved.parent.mkdir(parents=True, exist_ok=True)
    with saved.open('xb') as handle:
        handle.write(old)
    manifest = json.loads(old)
    supplements = [
        ('SQLite-3.50.4-LICENSE.md', 'cpython/SQLite-3.50.4-LICENSE.md', 'cpython-sqlite',
         'https://raw.githubusercontent.com/sqlite/sqlite/version-3.50.4/LICENSE.md',
         3864, 'a7a58d6022c090c528e3167026167b3141d682efc6a3c188b473ba59f1788fc7'),
        ('xz-5.2.5-COPYING', 'cpython/xz-5.2.5-COPYING', 'cpython-xz',
         'https://raw.githubusercontent.com/tukaani-project/xz/v5.2.5/COPYING',
         2775, 'bcb02973ef6e87ea73d331b3a80df7748407f17efdb784b61b47e0e610d3bb5c'),
    ]
    for filename, destination, component, url, size, expected in supplements:
        data = (DOWNLOADS / filename).read_bytes()
        if len(data) != size or digest(data) != expected:
            raise ValueError('SUPPLEMENT_LICENSE_CHANGED')
        target = PACKAGE / 'licenses' / destination
        with target.open('xb') as handle:
            handle.write(data)
        manifest['files'].append({'component': component,
                                  'path': target.relative_to(PACKAGE).as_posix(),
                                  'bytes': size, 'sha256': expected,
                                  'source': 'Exact official component version license',
                                  'official_origin': {'source_url': url, 'sha256': expected, 'bytes': size},
                                  'transformation': 'NONE'})
    python = next(c for c in manifest['components'] if c['id'] == 'cpython')
    python['license_files'] += ['licenses/cpython/SQLite-3.50.4-LICENSE.md', 'licenses/cpython/xz-5.2.5-COPYING']
    for dep in python['spdx_noassertion_entries']:
        if dep['name'] == 'sqlite':
            dep.update({'notice_files': ['licenses/cpython/SQLite-3.50.4-LICENSE.md'],
                        'notice_status': 'Exact-version official source says SQLite build products public domain; independent review pending'})
        if dep['name'] == 'xz':
            dep.update({'notice_files': ['licenses/cpython/xz-5.2.5-COPYING'],
                        'notice_status': 'Exact-version liblzma public-domain statement and compiler-code qualification retained; independent review pending'})
    for vc in python['microsoft_runtime']:
        vc['file_version'] = '14.51.36247.0'
        vc['version_evidence'] = 'Windows PE FileVersion/ProductVersion read from official archive member'
    manifest['unresolved_items'] = ['Independent review of full notice bytes and distribution conditions',
                                    'Microsoft downstream terms review',
                                    'Target package integration and extracted ZIP self-test']
    manifest['free_type_notice_path'] = 'THIRD_PARTY_NOTICES.md'
    manifest['review_boundary'] = 'Collected original notice bytes and exact source facts do not constitute a blanket legal warranty'
    replacement = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    manifest_path.write_bytes(replacement)
    receipt = {'schema': 'release.notice_supplement_receipt.v1',
               'previous_manifest_sha256': digest(old),
               'current_manifest_sha256': digest(replacement),
               'license_files': len(manifest['files']),
               'new_component_binaries': 0, 'status': 'MATERIALS_COMPLETE_PENDING_INDEPENDENT_REVIEW'}
    with (LAB / 'engineering/supply/NOTICE_SUPPLEMENT_RECEIPT.json').open('xb') as handle:
        handle.write((json.dumps(receipt, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
