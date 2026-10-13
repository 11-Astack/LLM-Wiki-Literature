"""Bounded Windows client probes; an index is not proof of visual reading.

Only caller-supplied executable and host-log paths are opened. No log discovery,
shell, evaluation, network transport, default-vault query, or client mutation is
provided. Host records are same-user evidence, not backend model attestation.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

from . import core, evidence, storage

_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_VERSION = re.compile(r"(?:Obsidian\s+)?([0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?)(?:\s+\(installer\s+[0-9]+\.[0-9]+\.[0-9]+\))?\Z")
_MAX_LOG = 512 * 1024 * 1024
_MAX_RECORD = 8 * 1024 * 1024
_MAX_OUTPUT = 8 * 1024 * 1024
_TIMEOUT = 15


class _CommandRejected(core.Rejected):
    def __init__(self, code: str, receipt: dict):
        super().__init__(code)
        self.receipt = receipt


def _command_require(condition, code: str, receipt: dict) -> None:
    if not condition:
        raise _CommandRejected(code, receipt)


def _error(exc: Exception) -> dict:
    # Never put arbitrary exception text (paths, subprocess output, log text) in
    # a receipt. Core/evidence rejection codes contain no source content.
    value = str(exc)
    if isinstance(exc, subprocess.TimeoutExpired):
        code = "CLIENT_TIMEOUT"
    elif isinstance(exc, FileNotFoundError):
        code = "CLIENT_FILE_MISSING"
    elif isinstance(exc, PermissionError):
        code = "CLIENT_PERMISSION_DENIED"
    elif isinstance(exc, (core.Rejected, evidence.EvidenceError)) and re.fullmatch(r"[A-Z][A-Z0-9_]+", value):
        code = value
    else:
        code = "CLIENT_CHECK_FAILED"
    result = {"status": "FAIL", "error": code, "exception_class": type(exc).__name__}
    if isinstance(exc, _CommandRejected):
        result["command"] = exc.receipt
    return result


def _explicit_file(value, code: str) -> Path:
    core.require(isinstance(value, (Path, str)) and bool(str(value)), code)
    path = Path(value)
    core.require(path.is_absolute(), code)
    path = core.absolute(path)
    core.require(path.is_file(), code)
    return path


def _executable(value: Path) -> Path:
    core.require(os.name == "nt", "WINDOWS_REQUIRED")
    path = _explicit_file(value, "EXPLICIT_CLIENT_EXECUTABLE_REQUIRED")
    core.require(path.suffix.casefold() in {".exe", ".com"}, "CLIENT_EXECUTABLE_TYPE")
    return path


def _run(executable: Path, arguments: list[str]) -> tuple[str, dict]:
    completed = subprocess.run([str(executable), *arguments], cwd=str(executable.parent),
        stdin=subprocess.DEVNULL, capture_output=True, timeout=_TIMEOUT, check=False,
        shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    core.require(isinstance(completed.stdout, bytes) and isinstance(completed.stderr, bytes), "CLIENT_OUTPUT_TYPE")
    receipt = {"arguments": arguments, "exit_code": completed.returncode,
               "stdout_bytes": len(completed.stdout), "stdout_sha256": core.sha(completed.stdout),
               "stderr_bytes": len(completed.stderr), "stderr_sha256": core.sha(completed.stderr)}
    _command_require(completed.returncode == 0, "CLIENT_COMMAND_FAILED", receipt)
    _command_require(len(completed.stdout) <= _MAX_OUTPUT and len(completed.stderr) <= _MAX_OUTPUT, "CLIENT_OUTPUT_LIMIT", receipt)
    _command_require(not completed.stderr.strip(), "CLIENT_STDERR_NOT_EMPTY", receipt)
    value = completed.stdout.decode("utf-8", errors="strict")
    _command_require(not value.startswith("\ufeff") and "\x00" not in value, "CLIENT_OUTPUT_ENCODING", receipt)
    return value, receipt


def _version(executable: Path) -> dict:
    value, receipt = _run(executable, ["version"])
    lines = value.strip().splitlines()
    _command_require(len(lines) == 1, "CLIENT_VERSION_FORMAT", receipt)
    match = _VERSION.fullmatch(lines[0])
    _command_require(match is not None, "CLIENT_VERSION_FORMAT", receipt)
    return {"status": "PASS", "executable": str(executable),
            "executable_sha256": core.digest(executable), "version": match.group(1), "command": receipt}


def _metadata(path: Path) -> dict:
    """Read only an explicit file, discard message payloads, retain metadata."""
    from . import host
    records = {"session_meta": [], "turn_context": [], "closed_turns": []}
    active_turn = None
    with path.open("rb") as stream:
        boundary = os.fstat(stream.fileno()).st_size
        core.require(boundary <= _MAX_LOG, "HOST_LOG_SIZE_LIMIT")
        offset, line = 0, 0
        while offset < boundary:
            raw = stream.readline(min(_MAX_RECORD + 1, boundary - offset))
            core.require(len(raw) <= _MAX_RECORD, "HOST_RECORD_SIZE_LIMIT")
            if not raw.endswith(b"\n"):
                # A live append can leave the last record incomplete. It is
                # never consumed as evidence, nor copied to a new log.
                core.require(offset + len(raw) == boundary, "HOST_RECORD_INCOMPLETE")
                break
            line += 1
            record = core.loads(raw)
            core.require(isinstance(record, dict), "HOST_RECORD_SCHEMA")
            kind = record.get("type")
            if kind in records:
                payload = record.get("payload")
                core.require(isinstance(payload, dict), "HOST_METADATA_SCHEMA")
                entry = {"ref": {"line": line, "byte_offset": offset, "byte_length": len(raw),
                    "raw_record_sha256": core.sha(raw), "timestamp": record.get("timestamp")}, "payload": payload}
                records[kind].append(entry)
                if kind == 'turn_context':
                    active_turn = payload.get('turn_id')
            if kind == 'event_msg':
                ended = host.closed_turn(record.get('payload'), active_turn)
                if ended is not None:
                    records['closed_turns'].append(ended)
            offset += len(raw)
    records["snapshot_boundary_bytes"] = offset
    return records


def _parent_proof(context: dict) -> dict:
    from . import host
    core.require(isinstance(context, dict) and set(context) == {"root", "turn", "allowed_log_paths"}, "HOST_CONTEXT_SCHEMA")
    root, turn, allowed = context["root"], context["turn"], context["allowed_log_paths"]
    core.require(isinstance(root, str) and _UUID.fullmatch(root), "HOST_ROOT_UUID")
    core.require(isinstance(turn, str) and _UUID.fullmatch(turn), "HOST_TURN_UUID")
    core.require(type(allowed) is list and bool(allowed) and len(allowed) <= 32, "HOST_LOG_ALLOWLIST")
    paths = [_explicit_file(value, "HOST_LOG_EXPLICIT_PATH_REQUIRED") for value in allowed]
    names = [os.path.normcase(str(path)) for path in paths]
    core.require(len(set(names)) == len(names), "HOST_LOG_ALLOWLIST_DUPLICATE")
    core.require(host.process_identity()['root'] == root, 'HOST_CURRENT_ROOT_MISMATCH')
    canonical = host.locate(root, host.day_directories())
    core.require(os.path.normcase(str(canonical)) in names, 'HOST_INDEX_SOURCE_NOT_ALLOWLISTED')
    matches = []
    for path in paths:
        scanned = _metadata(path)
        roots = [x for x in scanned["session_meta"] if x["payload"].get("id") == root]
        if roots:
            core.require(len(scanned["session_meta"]) == 1, "HOST_PARENT_METADATA_NOT_UNIQUE")
            matches.append((path, scanned, roots[0]))
    core.require(len(matches) == 1, "HOST_PARENT_LOG_NOT_UNIQUE")
    path, scanned, meta_entry = matches[0]
    reader = evidence._Reader(paths)
    meta = reader.record(path, {"ref": meta_entry["ref"], "fields": {}}, "session_meta")
    core.require(meta.get("id") == root and meta.get("session_id") == root
                 and meta.get("thread_source") == "user", "HOST_PARENT_IDENTITY_MISMATCH")
    core.require(bool(scanned["turn_context"]), "HOST_TURN_MISSING")
    current = scanned["turn_context"][-1]
    core.require(current["payload"].get("turn_id") == turn
                 and current["payload"].get("root_turn_id") == turn, "HOST_CURRENT_TURN_MISMATCH")
    core.require(turn not in scanned['closed_turns'], 'HOST_PARENT_TURN_CLOSED')
    core.require(path == canonical, 'INDEX_EXPLICIT_PATH_CONFLICT')
    consumed = [x for x in scanned["turn_context"] if x["payload"].get("turn_id") == turn]
    identities = set()
    for entry in consumed:
        core.require(meta_entry["ref"]["byte_offset"] < entry["ref"]["byte_offset"], "HOST_RECORD_ORDER")
        payload = reader.record(path, {"ref": entry["ref"], "fields": {}}, "turn_context")
        settings = payload.get("collaboration_mode", {}).get("settings", {})
        fields = {name: payload.get(name) for name in ("turn_id", "root_turn_id", "model", "effort")}
        fields["collaboration_settings"] = {"model": settings.get("model"), "reasoning_effort": settings.get("reasoning_effort")}
        identities.add(evidence._turn(payload, fields, turn, is_parent=True))
    core.require(len(identities) == 1, "HOST_MODEL_CHANGED_WITHIN_TURN")
    model, effort = next(iter(identities))
    fresh = host.parent_identity(path, root)
    core.require((fresh['turn'], fresh['model'], fresh['effort']) == (turn, model, effort)
                 and fresh['verified_record_refs'] == reader.refs, 'HOST_CONTEXT_CHANGED_DURING_PARENT_CHECK')
    core.require(host.locate(root, host.day_directories()) == canonical, 'HOST_INDEX_SOURCE_CHANGED')
    return {"status": "PASS", "root_thread_id": root, "root_turn_id": turn,
            "model": model, "effort": effort, "parent_log": str(path),
            "snapshot_boundary_bytes": scanned["snapshot_boundary_bytes"],
            "verified_record_refs": reader.refs, "message_bodies_exported": False,
            "trust_boundary": "Same-user local host records; no tamper isolation or backend model attestation."}


def prereq(package: Path, obsidian_cli: Path, host_context: dict) -> dict:
    """Probe capability only; the caller separately runs environment.doctor."""
    result = {"schema": "singlepaper.client_prereq.v1", "status": "BLOCKED", "ok": False,
              "client_prerequisites_passed": False, "formal_processing_allowed": False,
              "checks": {}, "software_validation": "NOT_RUN", "client_reading": "NOT_RUN",
              "pdf_visual_validation": "NOT_RUN", "failures": []}
    checks = [("package", lambda: {"status": "PASS", "path": str(core.absolute(package))}),
              ("codex", lambda: _parent_proof(host_context)),
              ("obsidian_cli", lambda: _version(_executable(obsidian_cli)))]
    for name, action in checks:
        try:
            value = action()
            if name == "package":
                core.require(Path(value["path"]).is_dir(), "PACKAGE_DIRECTORY_REQUIRED")
                result["package_root"] = value["path"]
            result["checks"][name] = value
        except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError) as exc:
            result["checks"][name] = _error(exc)
            result["failures"].append({"component": name, **_error(exc)})
    if not result["failures"]:
        result.update(status="CLIENT_CAPABILITIES_READY", ok=True, client_prerequisites_passed=True)
    return result


def _expected_files(library: dict) -> set[str]:
    vault = library["vault_dir"] + "/"
    paths = {"Library.md", "user/ideas/README.md"}
    paths.update("domains/" + category["id"] + ".md" for category in library["categories"])
    references = [library["overview"]["path"]]
    for work in library["works"]:
        references.extend(asset["path"] for asset in work["assets"])
        references.extend(work["reading"].values())
    for path in references:
        core.require(isinstance(path, str) and path.startswith(vault), "CLIENT_ASSET_OUTSIDE_VAULT")
        paths.add(path[len(vault):])
    return paths


def read_index(instance: Path, obsidian_cli: Path) -> dict:
    """Verify a specifically bound vault before issuing any index command.

    A successful result is intentionally PARTIAL: file discovery and no
    unresolved links cannot prove PDF/image rendering or a full visual read.
    """
    result = {"schema": "singlepaper.client_index.v1", "status": "BLOCKED", "ok": False,
              "index_validation": "NOT_RUN", "vault_identity": {"status": "NOT_RUN"},
              "files": {"status": "NOT_RUN"}, "unresolved": {"status": "NOT_RUN"},
              "pdf_visual_validation": "NOT_RUN", "full_reading_validation": "NOT_RUN",
              "failures": []}
    stage = "vault_identity"
    try:
        root = core.absolute(instance)
        library, original = storage._library(root)
        vault = core.safe(root, library["vault_dir"], must_exist=False)
        core.require(vault.is_dir(), "CLIENT_VAULT_DIRECTORY_MISSING")
        executable = _executable(obsidian_cli)
        selector = "vault=" + library["vault_dir"]
        output, command = _run(executable, [selector, "vault", "info=path"])
        result["vault_identity"]["command"] = command
        lines = output.strip().splitlines()
        core.require(len(lines) == 1, "CLIENT_VAULT_PATH_FORMAT")
        actual = Path(lines[0])
        core.require(actual.is_absolute(), "CLIENT_VAULT_PATH_FORMAT")
        # Compare lexically before resolve/stat: a wrong reported path must not
        # cause any inspection of a private vault or another local directory.
        core.require(os.path.normcase(os.path.normpath(str(actual))) == os.path.normcase(str(vault)), "CLIENT_VAULT_PATH_MISMATCH")
        result["vault_identity"] = {"status": "PASS", "name": library["vault_dir"],
            "path": str(vault), "instance_id": library["instance_id"], "command": command}
        result["library_sha256"] = core.sha(original)
        result["library_revision"] = library["revision"]
        stage = "files"
        output, command = _run(executable, [selector, "files"])
        result["files"]["command"] = command
        paths = output.strip().splitlines() if output.strip() else []
        core.require(len({name.casefold() for name in paths}) == len(paths), "CLIENT_FILE_DUPLICATE")
        for name in paths:
            core.safe(vault, name, must_exist=False)
        expected = _expected_files(library)
        missing = sorted(expected - set(paths))
        result["files"] = {"status": "FAIL" if missing else "PASS", "indexed_count": len(paths),
            "expected_count": len(expected), "missing_expected": missing, "command": command}
        core.require(not missing, "CLIENT_EXPECTED_FILES_MISSING")
        stage = "unresolved"
        output, command = _run(executable, [selector, "unresolved", "total"])
        result["unresolved"]["command"] = command
        match = re.fullmatch(r"([0-9]+)(?:\r?\n)?", output)
        _command_require(match is not None, "CLIENT_UNRESOLVED_COUNT_FORMAT", command)
        count = int(match.group(1))
        result["unresolved"] = {"status": "PASS" if count == 0 else "FAIL", "count": count, "command": command}
        core.require(count == 0, "CLIENT_UNRESOLVED_LINKS")
        stage = "library"
        _, after = storage._library(root)
        core.require(after == original, "CLIENT_LIBRARY_CHANGED")
        result.update(status="PARTIAL", ok=True, index_validation="PASS")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError) as exc:
        failure = _error(exc)
        result["failures"].append({"component": stage, **failure})
        if stage in {"vault_identity", "files", "unresolved"}:
            result[stage] = {**result[stage], **failure}
        result["index_validation"] = "FAIL" if result["vault_identity"]["status"] == "PASS" else "NOT_RUN"
    return result
