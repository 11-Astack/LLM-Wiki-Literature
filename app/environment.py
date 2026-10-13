"""Offline software probes and fail-closed creation of a new empty prototype.

This module never certifies a Codex identity, an Obsidian read, or publication.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import uuid

SCHEMA = "prototype.environment_doctor.v1"
SAMPLE_NAME = "SYNTHETIC_READABLE_TWO_PAGES.pdf"
SAMPLE_SHA256 = "73bd893812212a8e0c21e933f032c82937790c32922057ab14d6da2968a12f4b"
SAMPLE_BYTES = 2546
DEFAULT_CATEGORY_CANDIDATES = ["未分类", "基础概念", "方法与工具", "应用与案例"]
_PUBLIC_CODES = frozenset({
    "DUPLICATE_JSON_KEY", "REPARSE_PATH", "INVALID_RELATIVE_PATH",
    "SYNTHETIC_ALLOWLIST_MISMATCH", "SYNTHETIC_SAMPLE_CHANGED",
    "RUNTIME_MANIFEST_INVALID", "RUNTIME_MANIFEST_ENTRY_INVALID", "RUNTIME_FILE_CHANGED",
    "BUNDLED_PYTHON_NOT_IN_MANIFEST", "MISSING_IMPORT_ORIGINS",
    "IMPORTED_FILE_NOT_IN_RUNTIME_MANIFEST", "IMPORTED_FILE_CHANGED", "LOCAL_PACKAGE_REQUIRED",
    "SOFTWARE_PROBE_FAILED", "WRONG_PYTHON_EXECUTABLE", "SOFTWARE_PROBE_INCOMPLETE",
    "LOCAL_TARGET_REQUIRED", "TARGET_ALREADY_EXISTS", "TARGET_PARENT_MUST_EXIST",
    "INVALID_CATEGORY_CANDIDATES", "VALID_DOCTOR_RECEIPT_REQUIRED", "FRESH_SOFTWARE_CHECK_FAILED",
})


def _public_error(exc: Exception) -> dict:
    code = str(exc).split(":", 1)[0]
    if code not in _PUBLIC_CODES:
        if isinstance(exc, PermissionError):
            code = "ENVIRONMENT_PERMISSION_DENIED"
        elif isinstance(exc, FileNotFoundError):
            code = "ENVIRONMENT_FILE_MISSING"
        elif isinstance(exc, subprocess.TimeoutExpired):
            code = "ENVIRONMENT_PROBE_TIMEOUT"
        else:
            code = "ENVIRONMENT_CHECK_FAILED"
    return {"error": code, "exception_class": type(exc).__name__}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)


def _no_reparse(path: Path) -> None:
    # Inspect the lexical path before resolve() could hide a junction.
    for item in (path, *path.parents):
        if os.path.lexists(item):
            stat = item.lstat()
            if item.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError("REPARSE_PATH")


def _relative(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("INVALID_RELATIVE_PATH")
    win = PureWindowsPath(name)
    if win.drive or win.is_absolute() or ":" in name:
        raise ValueError("INVALID_RELATIVE_PATH")
    for part in name.split("/"):
        if (not part or part in (".", "..") or part.endswith((" ", "."))
                or any(ord(char) < 32 or char in '<>"|?*' for char in part)
                or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I)):
            raise ValueError("INVALID_RELATIVE_PATH")
    path = root / name
    _no_reparse(path)
    path.resolve().relative_to(root.resolve())
    return path


def _sample(package_root: Path) -> dict:
    manifest_path = _relative(package_root, "examples/MANIFEST.json")
    manifest = _json(manifest_path)
    expected = {"path": SAMPLE_NAME, "sha256": SAMPLE_SHA256, "bytes": SAMPLE_BYTES}
    if manifest != {"synthetic_only": True, "files": [expected]}:
        raise ValueError("SYNTHETIC_ALLOWLIST_MISMATCH")
    path = _relative(package_root, "examples/" + SAMPLE_NAME)
    if path.stat().st_size != SAMPLE_BYTES or _sha(path) != SAMPLE_SHA256:
        raise ValueError("SYNTHETIC_SAMPLE_CHANGED")
    return {"status": "PASS", **expected, "manifest_sha256": _sha(manifest_path)}


def _runtime_inventory(package_root: Path) -> dict:
    runtime = _relative(package_root, "runtime")
    manifest_path = _relative(package_root, "RUNTIME_MANIFEST.json")
    manifest = _json(manifest_path)
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("RUNTIME_MANIFEST_INVALID")
    verified = {}
    total_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
            raise ValueError("RUNTIME_MANIFEST_ENTRY_INVALID")
        name, sha, size = entry["path"], entry["sha256"], entry["bytes"]
        path = _relative(runtime, name)
        folded = name.casefold()
        if folded in verified or not re.fullmatch(r"[0-9a-f]{64}", sha or ""):
            raise ValueError("RUNTIME_MANIFEST_ENTRY_INVALID")
        if type(size) is not int or size < 0 or path.stat().st_size != size or _sha(path) != sha:
            raise ValueError("RUNTIME_FILE_CHANGED: " + name)
        verified[folded] = sha
        total_bytes += size
    if "python/python.exe" not in verified:
        raise ValueError("BUNDLED_PYTHON_NOT_IN_MANIFEST")
    return {"status": "PASS", "manifest_sha256": _sha(manifest_path),
            "verified_files": len(verified), "verified_bytes": total_bytes,
            "_verified": verified}


# Frozen modules execute code embedded in the versioned Python DLL. Their
# reported __file__ can be a nonexistent diagnostic path, so authenticate the
# frozen registry, actual registered module and FrozenImporter before selecting
# that fixed provider. A self-reported frozen spec never grants an exception.
_ORIGIN_CAPTURE = r'''
import _imp, importlib.machinery, pathlib, sys

def origin_provider(module_key, module, runtime):
    spec = getattr(module, '__spec__', None)
    reported = getattr(module, '__file__', None)
    if getattr(spec, 'origin', None) == 'frozen':
        frozen_name = getattr(spec, 'name', None)
        if (not isinstance(frozen_name, str) or not frozen_name
                or not _imp.is_frozen(frozen_name)
                or sys.modules.get(frozen_name) is not module
                or sys.modules.get(module_key) is not module
                or spec.loader is not importlib.machinery.FrozenImporter
                or getattr(module, '__loader__', None) is not spec.loader):
            raise ValueError('FROZEN_MODULE_IDENTITY_NOT_VERIFIED')
        provider = runtime / 'python' / ('python' + str(sys.version_info.major) + str(sys.version_info.minor) + '.dll')
        actual = provider.resolve(strict=True)
        actual.relative_to(runtime.resolve(strict=True))
        return str(actual), {'kind': 'FROZEN_MODULE_PROVIDER', 'provider': str(actual),
            'reported_file': reported, 'spec_origin': 'frozen', 'spec_name': frozen_name,
            'is_frozen_verified': True, 'registered_module_verified': True, 'loader': 'FrozenImporter'}
    if reported:
        actual = pathlib.Path(reported).resolve(strict=True)
        actual.relative_to(runtime.resolve(strict=True))
        return str(actual), {'kind': 'MODULE_FILE', 'provider': str(actual), 'reported_file': reported}
    return None
'''


# The child process has no current-directory, user-site or PYTHONPATH imports.
# Only the fixed synthetic PDF is opened; generated page bytes remain in memory.
_PROBE = _ORIGIN_CAPTURE + r'''
import sys, pathlib
runtime = pathlib.Path(sys.argv[1]).resolve(strict=True)
sample = pathlib.Path(sys.argv[2]).resolve(strict=True)
sys.dont_write_bytecode = True
sys.path[:] = [str(runtime / 'python' / 'Lib'), str(runtime / 'python' / 'DLLs'),
               str(runtime / 'python' / ('python' + str(sys.version_info.major) + str(sys.version_info.minor) + '.zip')),
               str(runtime / 'python'), str(runtime / 'vendor'), str(runtime / 'pdf-text-v1')]
import json, io, hashlib, xml.etree.ElementTree as ET
result = {'components': {}, 'origins': {}, 'origin_records': {}, 'executable': sys.executable}
try:
    if hashlib.sha256(sample.read_bytes()).hexdigest() != sys.argv[3]:
        raise ValueError('SYNTHETIC_SAMPLE_CHANGED_IN_PROBE')
    import pypdf
    reader = pypdf.PdfReader(str(sample), strict=True)
    text_lengths = [len((page.extract_text() or '').strip()) for page in reader.pages]
    if len(text_lengths) != 2 or not all(text_lengths):
        raise ValueError('SYNTHETIC_TEXT_PROBE_FAILED')
    result['components']['pypdf'] = {'status': 'PASS', 'pages': len(text_lengths),
        'text_characters_per_page': text_lengths, 'origin': pypdf.__file__}
    import pypdfium2
    document = pypdfium2.PdfDocument(str(sample))
    try:
        page = document[0]
        try:
            bitmap = page.render(scale=0.5)
            try:
                picture = bitmap.to_pil()
                try:
                    stream = io.BytesIO()
                    picture.save(stream, format='PNG')
                    png_bytes = stream.getvalue()
                    dimensions = list(picture.size)
                finally:
                    picture.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()
    if not all(dimensions) or not png_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('PDF_RENDER_PROBE_FAILED')
    result['components']['pypdfium2'] = {'status': 'PASS', 'rendered_page': 1,
        'dimensions': dimensions, 'png_bytes': len(png_bytes), 'origin': pypdfium2.__file__}
    import PIL, PIL.Image
    with PIL.Image.open(io.BytesIO(png_bytes)) as decoded:
        decoded.load()
        if list(decoded.size) != dimensions or decoded.format != 'PNG':
            raise ValueError('IMAGE_DECODE_PROBE_FAILED')
        result['components']['PIL'] = {'status': 'PASS', 'decoded_format': decoded.format,
            'dimensions': list(decoded.size), 'origin': PIL.__file__}
    import latex2mathml.converter
    mathml = latex2mathml.converter.convert(r'E = \frac{1}{2} m v^2')
    tree = ET.fromstring(mathml)
    if not tree.tag.endswith('math') or 'mfrac' not in mathml or 'msup' not in mathml:
        raise ValueError('MATHML_CONVERSION_PROBE_FAILED')
    result['components']['latex2mathml'] = {'status': 'PASS',
        'mathml_sha256': hashlib.sha256(mathml.encode('utf-8')).hexdigest(),
        'origin': latex2mathml.converter.__file__}
    for name, module in sorted(sys.modules.items()):
        source = origin_provider(name, module, runtime)
        if source is not None:
            result['origins'][name], result['origin_records'][name] = source
    result['ok'] = True
except Exception as exc:
    result['ok'] = False
    result['error'] = 'SOFTWARE_PROBE_FAILED'
    result['exception_class'] = type(exc).__name__
print(json.dumps(result, ensure_ascii=True))
sys.exit(0 if result['ok'] else 1)
'''


def _validate_origins(runtime: Path, origins: dict, verified: dict) -> None:
    if not isinstance(origins, dict) or not origins:
        raise ValueError("MISSING_IMPORT_ORIGINS")
    for origin in origins.values():
        path = Path(origin)
        _no_reparse(path)
        name = path.resolve(strict=True).relative_to(runtime.resolve()).as_posix()
        if name.casefold() not in verified:
            raise ValueError("IMPORTED_FILE_NOT_IN_RUNTIME_MANIFEST: " + name)
        if _sha(path) != verified[name.casefold()]:
            raise ValueError("IMPORTED_FILE_CHANGED: " + name)


def doctor(package_root: Path) -> dict:
    """Actually test bundled software; clients and formal permission stay unproved."""
    root = Path(os.path.abspath(package_root))
    result = {"schema": SCHEMA, "package_root": str(root), "ok": False,
              "software_checks_passed": False, "formal_processing_allowed": False,
              "status": "SOFTWARE_BLOCKED", "components": {},
              "clients": {"codex": {"status": "NOT_RUN", "reason": "TASK_IDENTITY_NOT_VERIFIED"},
                          "obsidian": {"status": "NOT_RUN", "reason": "CLIENT_READ_NOT_VERIFIED"}}}
    try:
        if str(root).startswith("\\\\"):
            raise ValueError("LOCAL_PACKAGE_REQUIRED")
        _no_reparse(root)
        root = root.resolve(strict=True)
        result["package_root"] = str(root)
        result["components"]["synthetic_sample"] = _sample(root)
        inventory = _runtime_inventory(root)
        verified = inventory.pop("_verified")
        result["components"]["runtime_inventory"] = inventory
        runtime = root / "runtime"
        executable = runtime / "python" / "python.exe"
        result["components"]["python"] = {"status": "PASS", "origin": str(executable),
            "sha256": verified["python/python.exe"]}
        completed = subprocess.run([str(executable), "-X", "utf8", "-I", "-S", "-B", "-c", _PROBE,
            str(runtime), str(root / "examples" / SAMPLE_NAME), SAMPLE_SHA256],
            cwd=str(runtime), capture_output=True, text=True, encoding="utf-8", errors="strict",
            timeout=45, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        probe = json.loads(completed.stdout, object_pairs_hook=_pairs)
        result["components"].update(probe.get("components", {}))
        if completed.returncode != 0 or probe.get("ok") is not True:
            raise ValueError(probe.get("error", "SOFTWARE_PROBE_FAILED"))
        if Path(probe["executable"]).resolve() != executable.resolve():
            raise ValueError("WRONG_PYTHON_EXECUTABLE")
        for name in ("pypdf", "pypdfium2", "PIL", "latex2mathml"):
            if result["components"].get(name, {}).get("status") != "PASS":
                raise ValueError("SOFTWARE_PROBE_INCOMPLETE")
        _validate_origins(runtime, probe.get("origins"), verified)
        result["import_origins"] = probe["origins"]
        records = probe.get("origin_records")
        if not isinstance(records, dict) or set(records) != set(probe["origins"]):
            raise ValueError("SOFTWARE_PROBE_INCOMPLETE")
        result["import_origin_records"] = {}
        for name, origin in probe["origins"].items():
            record = records[name]
            if not isinstance(record, dict) or record.get('provider') != origin:
                raise ValueError("SOFTWARE_PROBE_INCOMPLETE")
            relative = Path(origin).relative_to(runtime).as_posix()
            result["import_origin_records"][name] = {**record, 'runtime_path': relative,
                                                   'sha256': verified[relative.casefold()]}
        result.update(ok=True, software_checks_passed=True,
                      status="SOFTWARE_READY_AWAITING_CLIENT_PROBE")
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        result.update(_public_error(exc))
    return result


def _write_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def init_empty(target: Path, categories: list[str], doctor_receipt: dict) -> dict:
    """Create only a new, empty candidate; a fresh software probe is mandatory."""
    target = Path(os.path.abspath(target))
    result = {"schema": "prototype.empty_init.v1", "ok": False, "target": str(target),
              "status": "INIT_REJECTED", "formal_processing_allowed": False}
    created = False
    try:
        if str(target).startswith("\\\\"):
            raise ValueError("LOCAL_TARGET_REQUIRED")
        _no_reparse(target)
        if os.path.lexists(target):
            raise ValueError("TARGET_ALREADY_EXISTS")
        if not target.parent.is_dir():
            raise ValueError("TARGET_PARENT_MUST_EXIST")
        if (not isinstance(categories, list) or any(not isinstance(item, str) or not item.strip()
                or item != item.strip() or len(item) > 120 or any(ord(c) < 32 for c in item)
                for item in categories) or len(set(categories)) != len(categories)):
            raise ValueError("INVALID_CATEGORY_CANDIDATES")
        if (not isinstance(doctor_receipt, dict) or doctor_receipt.get("schema") != SCHEMA
                or doctor_receipt.get("software_checks_passed") is not True
                or doctor_receipt.get("formal_processing_allowed") is not False
                or not isinstance(doctor_receipt.get("package_root"), str)):
            raise ValueError("VALID_DOCTOR_RECEIPT_REQUIRED")
        # The caller's dictionary is not an authority. Re-run the actual probes.
        fresh = doctor(Path(doctor_receipt["package_root"]))
        if fresh["software_checks_passed"] is not True:
            raise ValueError("FRESH_SOFTWARE_CHECK_FAILED: " + fresh.get("error", "UNKNOWN"))
        _no_reparse(target)
        target.mkdir(exist_ok=False)
        created = True
        directories = [".prototype", "sources", "processing", "reading", "user-notes", "ideas"]
        for name in directories:
            _no_reparse(target)
            (target / name).mkdir(exist_ok=False)
        _write_new(target / ".prototype" / "doctor.json", fresh)
        _write_new(target / ".prototype" / "classification-candidates.json", {
            "schema": "prototype.classification_candidates.v1", "status": "UNCONFIRMED_CANDIDATES",
            "confirmed_by_user": False, "categories": categories or DEFAULT_CATEGORY_CANDIDATES,
            "source": "CALLER_CANDIDATES" if categories else "GENERIC_SUGGESTIONS"})
        instance_id = str(uuid.uuid4())
        _write_new(target / ".prototype" / "library.json", {
            "schema": "prototype.empty_registry.v1", "instance_id": instance_id,
            "works": [], "status": "EMPTY_AWAITING_CLIENT_PROBE",
            "formal_processing_allowed": False})
        marker = {"schema": "prototype.empty_library.v1", "status": "EMPTY_AWAITING_CLIENT_PROBE",
                  "instance_id": instance_id,
                  "formal_processing_allowed": False, "documents": [],
                  "codex_identity": "NOT_RUN", "obsidian_read": "NOT_RUN",
                  "classification_confirmed": False}
        _write_new(target / ".prototype" / "init.json", marker)
        result.update(ok=True, status=marker["status"], directories=directories, instance_id=instance_id,
                      classification_confirmed=False)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result.update(_public_error(exc))
        if created:
            result["status"] = "INIT_PARTIAL_RETAINED"
            result["partial_files_retained"] = True
    return result
