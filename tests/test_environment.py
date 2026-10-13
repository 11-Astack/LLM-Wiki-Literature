"""Strict provider tests and a real fixed-package software probe.

Synthetic module metadata never proves a real AI role, client reading or release.
Runtime files are read-only. Missing/forged sources must stay rejected.
"""
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from app import environment

PACKAGE=Path(__file__).resolve().parents[1]
RUNTIME=PACKAGE/'runtime'
SCRATCH=PACKAGE/'tests/.scratch/environment'


class DoctorRegressionTests(unittest.TestCase):
    def test_new_bundled_runtime_strict_doctor_passes(self):
        result=environment.doctor(PACKAGE)
        self.assertTrue(result.get('software_checks_passed'),result)
        self.assertEqual(Path(result['components']['python']['origin']),RUNTIME/'python/python.exe')
        self.assertTrue(result['import_origins'])
        for name in ('pypdf','pypdfium2','PIL','latex2mathml'):
            self.assertEqual(result['components'][name]['status'],'PASS')


class OriginProviderTests(unittest.TestCase):
    def setUp(self):
        namespace={}
        exec(environment._ORIGIN_CAPTURE,namespace)
        self.capture=namespace['origin_provider']
        self.verified={item['path'].casefold():item['sha256'] for item in
            json.loads((PACKAGE/'RUNTIME_MANIFEST.json').read_text(encoding='utf-8'))['files']}
        SCRATCH.mkdir(parents=True,exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(prefix='synthetic-',dir=SCRATCH)
        self.base=Path(self.temporary.name)

    def tearDown(self):
        if not self.base.resolve().is_relative_to(SCRATCH.resolve()) or not self.base.name.startswith('synthetic-'):
            raise RuntimeError('ORIGIN_TEST_CLEANUP_OUTSIDE_OWNED_SCRATCH')
        self.temporary.cleanup()

    def frozen_provider(self):
        import _collections_abc
        return self.capture('_collections_abc',_collections_abc,RUNTIME)

    def test_real_frozen_module_is_bound_to_manifest_checked_python_dll(self):
        provider,record=self.frozen_provider()
        expected=RUNTIME/'python'/f'python{sys.version_info.major}{sys.version_info.minor}.dll'
        self.assertEqual(Path(provider),expected)
        self.assertEqual(record['kind'],'FROZEN_MODULE_PROVIDER')
        self.assertTrue(record['is_frozen_verified'])
        self.assertEqual(record['spec_name'],'_collections_abc')
        environment._validate_origins(RUNTIME,{'_collections_abc':provider},self.verified)

    def test_real_frozen_bootstrap_alias_is_supported_by_registered_identity(self):
        import importlib._bootstrap
        provider,record=self.capture('importlib._bootstrap',importlib._bootstrap,RUNTIME)
        self.assertEqual(record['spec_name'],'_frozen_importlib')
        self.assertEqual(record['kind'],'FROZEN_MODULE_PROVIDER')
        environment._validate_origins(RUNTIME,{'importlib._bootstrap':provider},self.verified)

    def test_normal_package_keeps_its_real_file_and_sha_check(self):
        import pypdf
        provider,record=self.capture('pypdf',pypdf,RUNTIME)
        self.assertEqual(Path(provider),Path(pypdf.__file__).resolve(strict=True))
        self.assertEqual(record['kind'],'MODULE_FILE')
        environment._validate_origins(RUNTIME,{'pypdf':provider},self.verified)

    def test_nonfrozen_missing_file_is_rejected(self):
        module=types.ModuleType('invented_missing_file')
        module.__file__=str(self.base/'missing.py')
        with self.assertRaises(FileNotFoundError):
            self.capture(module.__name__,module,RUNTIME)

    def test_self_reported_frozen_unknown_module_is_rejected_even_with_real_file(self):
        import pypdf
        module=types.ModuleType('invented_fake_frozen')
        module.__file__=pypdf.__file__
        module.__spec__=types.SimpleNamespace(name=module.__name__,origin='frozen',loader=importlib.machinery.FrozenImporter)
        module.__loader__=importlib.machinery.FrozenImporter
        with patch.dict(sys.modules,{module.__name__:module}):
            with self.assertRaisesRegex(ValueError,'FROZEN_MODULE_IDENTITY_NOT_VERIFIED'):
                self.capture(module.__name__,module,RUNTIME)

    def test_copying_known_frozen_spec_does_not_authenticate_arbitrary_module(self):
        module=types.ModuleType('invented_impersonator')
        module.__file__=str(self.base/'does-not-exist.py')
        module.__spec__=os.__spec__
        module.__loader__=os.__loader__
        with patch.dict(sys.modules,{module.__name__:module}):
            with self.assertRaisesRegex(ValueError,'FROZEN_MODULE_IDENTITY_NOT_VERIFIED'):
                self.capture(module.__name__,module,RUNTIME)

    def test_frozen_registry_name_requires_actual_frozen_importer(self):
        module=types.ModuleType('os')
        module.__file__=str(self.base/'does-not-exist.py')
        module.__spec__=types.SimpleNamespace(name='os',origin='frozen',loader=object())
        module.__loader__=module.__spec__.loader
        with patch.dict(sys.modules,{'os':module}):
            with self.assertRaisesRegex(ValueError,'FROZEN_MODULE_IDENTITY_NOT_VERIFIED'):
                self.capture('os',module,RUNTIME)

    def test_frozen_provider_absent_from_manifest_is_rejected(self):
        provider,_=self.frozen_provider()
        relative=Path(provider).relative_to(RUNTIME).as_posix().casefold()
        manifest=dict(self.verified)
        del manifest[relative]
        with self.assertRaisesRegex(ValueError,'IMPORTED_FILE_NOT_IN_RUNTIME_MANIFEST'):
            environment._validate_origins(RUNTIME,{'_collections_abc':provider},manifest)

    def test_frozen_provider_sha_drift_is_rejected_without_runtime_mutation(self):
        provider,_=self.frozen_provider()
        relative=Path(provider).relative_to(RUNTIME).as_posix().casefold()
        manifest={**self.verified,relative:'0'*64}
        with self.assertRaisesRegex(ValueError,'IMPORTED_FILE_CHANGED'):
            environment._validate_origins(RUNTIME,{'_collections_abc':provider},manifest)

    def test_normal_provider_outside_runtime_is_rejected(self):
        path=self.base/'outside.py'
        path.write_bytes(b'# Synthetic outside-provider fixture\n')
        module=types.ModuleType('invented_outside')
        module.__file__=str(path)
        with self.assertRaises(ValueError):
            self.capture(module.__name__,module,RUNTIME)


if __name__=='__main__':unittest.main()
