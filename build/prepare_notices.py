"""Collect exact official notice bytes; does not select the project license."""
from __future__ import annotations

from email.parser import Parser
import hashlib
import json
from pathlib import Path
import re

LAB = Path(__file__).resolve().parent.parent
PACKAGE = LAB / 'package' if (LAB / 'package/app').is_dir() else LAB
RUNTIME = PACKAGE / 'runtime'
DOWNLOADS = LAB / 'build/downloads/source-001'
LICENSES = PACKAGE / 'licenses'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def copy_exact(source: Path, destination: Path, source_ref: str, component: str,
               origin: dict | None = None) -> dict:
    data = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError('NOTICE_ALREADY_EXISTS')
    with destination.open('xb') as handle:
        handle.write(data)
    result = {'component': component, 'path': destination.relative_to(PACKAGE).as_posix(),
              'bytes': len(data), 'sha256': sha(data), 'source': source_ref,
              'transformation': 'NONE'}
    if origin:
        result['official_origin'] = origin
    return result


def main() -> None:
    if LICENSES.exists():
        raise ValueError('LICENSE_COLLECTION_ALREADY_EXISTS')
    entries = []
    entries.append(copy_exact(RUNTIME / 'python/LICENSE.txt', LICENSES / 'cpython/LICENSE.txt',
                              'runtime/python/LICENSE.txt', 'cpython'))
    extras = [
        ('CPython-3.13.16-license.rst', 'cpython/INCORPORATED_SOFTWARE_LICENSES.rst', 'cpython'),
        ('OpenSSL-3.5.9-LICENSE.txt', 'cpython/OpenSSL-3.5.9-LICENSE.txt', 'cpython-openssl'),
        ('libb2-0.98.1-COPYING', 'cpython/libb2-0.98.1-COPYING', 'cpython-libb2'),
        ('HACL-CPython-3.13.16-MIT-header.txt', 'cpython/HACL-MIT-header.txt', 'cpython-hacl'),
        ('latex2mathml-3.81.0-LICENSE', 'latex2mathml/LICENSE', 'latex2mathml'),
    ]
    acquisition = json.loads((DOWNLOADS / 'ACQUISITION_RECEIPT.json').read_text(encoding='utf-8'))
    supplements = json.loads((DOWNLOADS / 'LICENSE_ACQUISITION_RECEIPT.json').read_text(encoding='utf-8'))
    by_filename = {item['filename']: item for item in acquisition['files'] + supplements['files']}
    for filename, destination, component in extras:
        origin = {k: v for k, v in by_filename[filename].items() if k in
                  ('source_url', 'source_bytes', 'source_sha256', 'sha256', 'bytes', 'transform')}
        entries.append(copy_exact(DOWNLOADS / filename, LICENSES / destination,
                                  'Official corresponding license text', component, origin))
    components = []
    for metadata in sorted(RUNTIME.rglob('*.dist-info/METADATA')):
        parsed = Parser().parsestr(metadata.read_text(encoding='utf-8'))
        component = parsed['Name'].casefold()
        local = metadata.parent / 'licenses'
        copied = []
        if local.exists():
            for source in sorted(local.rglob('*')):
                if source.is_file():
                    record = copy_exact(source, LICENSES / component / source.relative_to(local),
                                        source.relative_to(PACKAGE).as_posix(), component)
                    entries.append(record)
                    copied.append(record['path'])
        if component == 'latex2mathml':
            copied.append('licenses/latex2mathml/LICENSE')
        missing = [value for value in parsed.get_all('License-File', [])
                   if not (local / value).is_file() and not (metadata.parent / value).is_file()]
        if missing or not copied:
            raise ValueError('LICENSE_TEXT_MISSING: ' + component)
        record = {'id': component, 'version': parsed['Version'],
                  'declared_license': parsed.get('License-Expression') or parsed.get('License'),
                  'license_files': copied,
                  'notice_material_presence': 'PASS',
                  'redistribution_review': 'PENDING_INDEPENDENT_REVIEW'}
        if component == 'pillow':
            text = (local / 'LICENSE').read_text(encoding='utf-8')
            record['compiled_dependency_notice_sections'] = re.findall(r'^===== (.+?) =====$', text, re.M)
        if component == 'pypdfium2':
            record['pdfium_version'] = json.loads((RUNTIME / 'pdf-text-v1/pypdfium2_raw/version.json').read_text(encoding='utf-8'))
            record['compiled_dependency_notices'] = [x for x in copied if '/BUILD_LICENSES/' in x]
        components.append(record)
    python_spdx = json.loads((DOWNLOADS / 'python-3.13.16-embed-amd64.zip.spdx.json').read_text(encoding='utf-8'))
    python_deps = []
    notice_mapping = {
        'bzip2': ['licenses/cpython/LICENSE.txt'],
        'expat': ['licenses/cpython/INCORPORATED_SOFTWARE_LICENSES.rst'],
        'hacl-star': ['licenses/cpython/HACL-MIT-header.txt'],
        'libb2': ['licenses/cpython/libb2-0.98.1-COPYING'],
        'libffi': ['licenses/cpython/LICENSE.txt', 'licenses/cpython/INCORPORATED_SOFTWARE_LICENSES.rst'],
        'mpdecimal': ['licenses/cpython/INCORPORATED_SOFTWARE_LICENSES.rst'],
        'openssl': ['licenses/cpython/LICENSE.txt', 'licenses/cpython/OpenSSL-3.5.9-LICENSE.txt'],
        'zlib': ['licenses/cpython/INCORPORATED_SOFTWARE_LICENSES.rst'],
    }
    for item in python_spdx['packages']:
        if item['name'] == 'CPython':
            continue
        dep = {key: item.get(key) for key in ('name', 'versionInfo', 'downloadLocation', 'licenseConcluded')}
        if item['name'] in ('tcl-core', 'tk', 'macholib'):
            dep.update({'runtime_presence': 'NOT_SHIPPED_IN_WINDOWS_EMBEDDED_ARCHIVE',
                        'notice_status': 'SPDX_BUILD_SOURCE_REFERENCE_ONLY'})
        elif item['name'] == 'sqlite':
            dep.update({'runtime_presence': 'sqlite3.dll',
                        'notice_status': 'Public-domain SQLite status still requires independent source review'})
        elif item['name'] == 'xz':
            dep.update({'runtime_presence': '_lzma.pyd',
                        'notice_status': 'Exact compiled-source licensing review remains explicit pending item'})
        else:
            dep.update({'notice_files': notice_mapping.get(item['name'], []),
                        'notice_status': 'Corresponding notice bytes retained; independent review pending'})
        python_deps.append(dep)
    vcs = []
    for name in ('vcruntime140.dll', 'vcruntime140_1.dll'):
        path = RUNTIME / 'python' / name
        vcs.append({'path': path.relative_to(PACKAGE).as_posix(), 'bytes': path.stat().st_size,
                    'sha256': sha(path.read_bytes()), 'source': 'Unchanged member of official CPython 3.13.16 embeddable ZIP',
                    'applicable_terms': 'licenses/cpython/LICENSE.txt: Additional Conditions for this Windows binary build',
                    'review_status': 'PENDING_INDEPENDENT_WINDOWS_REDISTRIBUTION_REVIEW'})
    components.insert(0, {'id': 'cpython', 'version': '3.13.16', 'declared_license': 'PSF-2.0 and incorporated software terms',
                          'license_files': [x['path'] for x in entries if x['component'].startswith('cpython')],
                          'notice_material_presence': 'PASS',
                          'redistribution_review': 'PENDING_INDEPENDENT_REVIEW',
                          'spdx_noassertion_entries': python_deps, 'microsoft_runtime': vcs,
                          'mimalloc': {'notice': 'licenses/cpython/INCORPORATED_SOFTWARE_LICENSES.rst: mimalloc',
                                       'note': 'CPython release notice retained; not silently omitted due to missing SPDX package record'}})
    manifest = {'schema': 'release.third_party_license_materials.v1',
                'status': 'NOTICE_MATERIALS_COLLECTED_INDEPENDENT_REVIEW_PENDING',
                'files': entries, 'components': components,
                'signature_cryptographic_verification': 'NOT_RUN',
                'project_license': 'MIT; Copyright (c) 2026 LLM-Wiki-Literature contributors',
                'project_scope': 'Own code, manuals, panorama, synthetic examples; third-party materials keep their terms',
                'unresolved_items': ['Independent review of notices and conditions',
                                     'SQLite 3.50.4.0 public-domain provenance text',
                                     'xz 5.2.5 compiled-code licensing notice',
                                     'Microsoft downstream terms review',
                                     'Target package integration and extracted ZIP self-test'],
                'public_release_status': 'CANDIDATE'}
    data = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    with (LICENSES / 'THIRD_PARTY_LICENSES.json').open('xb') as handle:
        handle.write(data)
    print(json.dumps({'status': manifest['status'], 'license_files': len(entries),
                      'components': len(components), 'manifest_sha256': sha(data),
                      'unresolved_items': manifest['unresolved_items']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
