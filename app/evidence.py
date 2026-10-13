"""Verify Codex host records through an explicit caller-owned path allowlist.

This module has no machine-specific paths, task UUIDs, network calls, or writers.
Capture summaries are untrusted. Consumed records are reread, their original
bytes are hashed, and the runtime identity chain is checked against those bytes.
Local logs writable by the same OS user are not a tamper-isolated trust root.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


class EvidenceError(ValueError):
    """A required runtime fact could not be verified."""


_UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_TASK = re.compile(r"^/root/[a-z0-9_]+$")
_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
_SCHEMA = "codex-host-metadata-probe-v001"
_COLLAB = {"spawn_agent", "followup_task", "send_message", "list_agents", "wait_agent", "interrupt_agent"}


def _require(condition: Any, code: str) -> None:
    if not condition:
        raise EvidenceError(code)


def _object(value: Any, code: str = "EXPECTED_OBJECT") -> dict:
    _require(isinstance(value, dict), code)
    return value


def _keys(value: dict, required: set[str], optional: set[str] | None = None) -> None:
    _object(value)
    _require(required <= value.keys() and value.keys() <= required | (optional or set()), "UNKNOWN_OR_MISSING_FIELDS")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _json(data: str | bytes) -> dict:
    try:
        return _object(json.loads(data, object_pairs_hook=_no_duplicates))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise EvidenceError("INVALID_JSON_RECORD") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normal_path(value: str | Path) -> str:
    # Lexical normalization only: an untrusted receipt path is never resolved,
    # stat'ed, or opened before it matches a path supplied by the caller.
    return os.path.normcase(os.path.abspath(os.fspath(value)))


class _Reader:
    def __init__(self, allowed: list[Path]):
        _require(isinstance(allowed, list) and allowed, "EMPTY_LOG_ALLOWLIST")
        self.allowed: dict[str, Path] = {}
        for path in allowed:
            _require(isinstance(path, Path), "ALLOWLIST_REQUIRES_PATH_OBJECTS")
            normal = _normal_path(path)
            _require(normal not in self.allowed, "DUPLICATE_ALLOWLIST_PATH")
            self.allowed[normal] = path
        self.refs: list[dict] = []

    def path(self, value: Any) -> Path:
        _require(isinstance(value, str) and bool(value), "INVALID_CAPTURE_PATH")
        normal = _normal_path(value)
        _require(normal in self.allowed, "SOURCE_PATH_NOT_ALLOWLISTED")
        return self.allowed[normal]

    def record(self, path: Path, entry: dict, record_type: str) -> dict:
        _keys(entry, {"ref", "fields"})
        ref = _object(entry["ref"])
        _keys(ref, {"line", "byte_offset", "byte_length", "raw_record_sha256", "timestamp"})
        line, offset, length = ref["line"], ref["byte_offset"], ref["byte_length"]
        _require(type(line) is int and line > 0 and type(offset) is int and offset >= 0
                 and type(length) is int and 0 < length <= 2_000_000, "INVALID_RECORD_RANGE")
        _require(isinstance(ref["raw_record_sha256"], str) and _HASH.fullmatch(ref["raw_record_sha256"]), "INVALID_RECORD_HASH")
        try:
            with path.open("rb") as stream:
                # Count prefix newlines without decoding or retaining prefix
                # content. This verifies the displayed 1-based line locator.
                remaining, newlines, last = offset, 0, b""
                while remaining:
                    chunk = stream.read(min(remaining, 1_048_576))
                    _require(bool(chunk), "OFFSET_BEYOND_LOG")
                    remaining -= len(chunk)
                    newlines += chunk.count(b"\n")
                    last = chunk[-1:]
                _require((offset == 0 or last == b"\n") and newlines + 1 == line, "NOT_AN_EXACT_LINE_BOUNDARY")
                raw = stream.read(length)
        except OSError as exc:
            raise EvidenceError("SOURCE_LOG_UNREADABLE") from exc
        _require(len(raw) == length and raw.endswith(b"\n") and raw.count(b"\n") == 1, "INCOMPLETE_OR_MULTILINE_RECORD")
        _require(_sha(raw) == ref["raw_record_sha256"], "RAW_RECORD_HASH_MISMATCH")
        record = _json(raw)
        _require(record.get("type") == record_type and record.get("timestamp") == ref["timestamp"], "RECORD_TYPE_OR_TIME_MISMATCH")
        self.refs.append({"source_path": str(path), **ref})
        return _object(record.get("payload"))


def _project(payload: dict, fields: dict, names: set[str]) -> None:
    _require(fields.keys() <= names, "UNKNOWN_PROJECTED_FIELD")
    for key, value in fields.items():
        _require(key in payload and payload[key] == value, "PROJECTED_FIELD_MISMATCH")


def _turn(payload: dict, fields: dict, expected_turn: str, *, is_parent: bool) -> tuple[str, str]:
    required = {"turn_id", "root_turn_id", "model", "effort", "collaboration_settings"}
    optional = {"current_date", "timezone", "multi_agent_version", "collaboration_mode"}
    _keys(fields, required, optional)
    _project(payload, {k: v for k, v in fields.items() if k not in {"collaboration_settings", "collaboration_mode"}}, required | optional)
    _require(isinstance(payload.get("turn_id"), str) and _UUID.fullmatch(payload["turn_id"]), "INVALID_TURN_ID")
    _require(payload.get("root_turn_id") == expected_turn, "ROOT_TURN_MISMATCH")
    if is_parent:
        _require(payload["turn_id"] == expected_turn, "PARENT_TURN_MISMATCH")
    model, effort = payload.get("model"), payload.get("effort")
    _require(isinstance(model, str) and bool(model.strip()) and isinstance(effort, str) and effort in _EFFORTS, "UNKNOWN_MODEL_OR_EFFORT")
    mode = _object(payload.get("collaboration_mode"), "MISSING_COLLABORATION_MODE")
    settings = _object(mode.get("settings"), "MISSING_RUNTIME_SETTINGS")
    _require(settings.get("model") == model and settings.get("reasoning_effort") == effort, "MODEL_EFFORT_DISAGREEMENT")
    _require(fields["collaboration_settings"] == {"model": model, "reasoning_effort": effort}, "SETTINGS_PROJECTION_MISMATCH")
    if "collaboration_mode" in fields:
        _require(fields["collaboration_mode"] == {"mode": mode.get("mode")}, "MODE_PROJECTION_MISMATCH")
    return model, effort


def _parse_arguments(payload: dict) -> dict:
    arguments = payload.get("arguments")
    return _json(arguments) if isinstance(arguments, str) else _object(arguments)


def _verify(capture: dict, expected_root: str, expected_turn: str, expected_task: str,
            allowed_log_paths: list[Path]) -> tuple[dict, str]:
    _require(isinstance(expected_root, str) and _UUID.fullmatch(expected_root), "INVALID_EXPECTED_ROOT")
    _require(isinstance(expected_turn, str) and _UUID.fullmatch(expected_turn), "INVALID_EXPECTED_TURN")
    _require(isinstance(expected_task, str) and _TASK.fullmatch(expected_task), "UNSUPPORTED_EXPECTED_TASK_PATH")
    _keys(capture, {"schema", "captured_at_utc", "scope", "process_environment", "parent", "child_log_opened", "claim_boundary", "child"})
    _require(capture["schema"] == _SCHEMA, "UNKNOWN_CAPTURE_SCHEMA")
    _require(capture["child_log_opened"] is True, "CHILD_EVIDENCE_REQUIRED")
    scope = _object(capture["scope"])
    _keys(scope, {"root_thread_id", "root_turn_id", "allowed_day_directories", "message_bodies_exported", "source_logs_modified"})
    _require(scope["root_thread_id"] == expected_root and scope["root_turn_id"] == expected_turn, "CAPTURE_SCOPE_MISMATCH")
    _require(scope["message_bodies_exported"] is False and scope["source_logs_modified"] is False, "UNSUPPORTED_CAPTURE_PRIVACY_DECLARATION")
    parent, child = _object(capture["parent"]), _object(capture["child"])
    _keys(parent, {"source_path", "expected_thread_id", "session_metadata", "turn_contexts", "collaboration_calls",
                   "collaboration_results", "agent_message_metadata", "inter_agent_metadata", "diagnostics", "snapshot_boundary_bytes", "captured_task_names"})
    _keys(child, {"source_path", "environment_thread_hint", "session_metadata", "turn_context", "first_delegation",
                  "diagnostics", "identity_link_status", "read_boundary"})
    _require(parent["diagnostics"] == [] and child["diagnostics"] == [], "CAPTURE_HAS_DIAGNOSTICS")
    _require(parent["expected_thread_id"] == expected_root, "CAPTURE_PARENT_ID_MISMATCH")
    reader = _Reader(allowed_log_paths)
    # Validate both receipt paths before opening either source.
    parent_path, child_path = reader.path(parent["source_path"]), reader.path(child["source_path"])
    _require(_normal_path(parent_path) != _normal_path(child_path), "PARENT_CHILD_LOGS_NOT_DISTINCT")
    _require(isinstance(parent["session_metadata"], list) and len(parent["session_metadata"]) == 1, "PARENT_SESSION_NOT_UNIQUE")
    meta_entry = parent["session_metadata"][0]
    meta = reader.record(parent_path, meta_entry, "session_meta")
    _project(meta, _object(meta_entry["fields"]), {"id", "session_id", "timestamp", "cwd", "originator", "cli_version", "model_provider", "source", "thread_source"})
    _require(meta.get("id") == expected_root and meta.get("session_id") == expected_root and meta.get("thread_source") == "user", "PARENT_SESSION_IDENTITY_MISMATCH")
    _require(isinstance(parent["turn_contexts"], list) and bool(parent["turn_contexts"]), "MISSING_PARENT_TURN")
    parent_turns = []
    for entry in parent["turn_contexts"]:
        payload = reader.record(parent_path, entry, "turn_context")
        parent_turns.append((entry["ref"]["byte_offset"], *_turn(payload, entry["fields"], expected_turn, is_parent=True)))
    calls: dict[str, tuple[dict, dict, dict]] = {}
    for entry in parent["collaboration_calls"]:
        payload = reader.record(parent_path, entry, "response_item")
        fields = _object(entry["fields"])
        _keys(fields, {"name", "call_id", "arguments", "argument_field_names"}, {"message_utf8_sha256"})
        _require(payload.get("type") == "function_call" and payload.get("name") in _COLLAB, "NOT_A_SUPPORTED_COLLABORATION_CALL")
        _project(payload, {k: fields[k] for k in ("name", "call_id")}, {"name", "call_id"})
        args = _parse_arguments(payload)
        _project(args, _object(fields["arguments"]), {"task_name", "target", "model", "reasoning_effort", "fork_turns"})
        _require(fields["argument_field_names"] == sorted(args), "ARGUMENT_SCHEMA_PROJECTION_MISMATCH")
        if "message_utf8_sha256" in fields:
            _require(isinstance(args.get("message"), str) and _sha(args["message"].encode("utf-8")) == fields["message_utf8_sha256"], "DISPATCH_HASH_MISMATCH")
        call_id = payload.get("call_id")
        _require(isinstance(call_id, str) and bool(call_id) and call_id not in calls, "DUPLICATE_OR_MISSING_CALL_ID")
        calls[call_id] = (payload, args, entry)
    matches = []
    result_ids = set()
    for entry in parent["collaboration_results"]:
        payload = reader.record(parent_path, entry, "response_item")
        fields = _object(entry["fields"])
        _keys(fields, {"call_id", "output_field_names", "output"})
        _require(payload.get("type") == "function_call_output", "NOT_ACTUAL_TOOL_RESULT")
        call_id = payload.get("call_id")
        _require(call_id == fields["call_id"] and call_id in calls and call_id not in result_ids, "RESULT_CALL_LINK_MISMATCH")
        result_ids.add(call_id)
        _require(calls[call_id][0]["name"] == "spawn_agent", "RESULT_NOT_FROM_SPAWN")
        output = _json(payload["output"]) if isinstance(payload.get("output"), str) else _object(payload.get("output"))
        _keys(output, {"task_name"})
        _require(fields["output_field_names"] == ["task_name"] and fields["output"] == output, "RESULT_PROJECTION_MISMATCH")
        if output["task_name"] == expected_task:
            matches.append((call_id, calls[call_id], entry))
    _require(len(matches) == 1, "EXPECTED_TASK_DISPATCH_NOT_UNIQUE")
    call_id, (_, spawn_args, spawn_entry), result_entry = matches[0]
    _keys(spawn_args, {"task_name", "message"}, {"fork_turns", "model", "reasoning_effort"})
    _require(isinstance(spawn_args["task_name"], str), "INVALID_SPAWN_TASK_NAME")
    if "fork_turns" in spawn_args:
        _require(spawn_args["fork_turns"] in {"none", "all"}, "UNKNOWN_FORK_MODE")
    _require(isinstance(spawn_args["message"], str) and bool(spawn_args["message"]), "MISSING_DISPATCH_MESSAGE")
    _require("/root/" + spawn_args["task_name"] == expected_task, "SPAWN_REQUEST_TASK_MISMATCH")
    _require(spawn_entry["ref"]["byte_offset"] < result_entry["ref"]["byte_offset"], "RESULT_PRECEDES_SPAWN")
    prior_turns = [x for x in parent_turns if x[0] < spawn_entry["ref"]["byte_offset"]]
    _require(bool(prior_turns), "NO_PARENT_CONTEXT_BEFORE_SPAWN")
    _, parent_model, parent_effort = max(prior_turns)
    child_meta = reader.record(child_path, child["session_metadata"], "session_meta")
    child_fields = _object(child["session_metadata"]["fields"])
    _keys(child_fields, {"id", "session_id", "timestamp", "originator", "cli_version", "model_provider", "thread_source", "thread_spawn"})
    _project(child_meta, {k: v for k, v in child_fields.items() if k != "thread_spawn"}, set(child_fields))
    source = _object(child_meta.get("source"))
    _keys(source, {"subagent"})
    subagent = _object(source["subagent"])
    _keys(subagent, {"thread_spawn"})
    spawn = _object(subagent["thread_spawn"])
    _keys(spawn, {"parent_thread_id", "depth", "agent_path"}, {"agent_nickname", "agent_role"})
    _require(child_fields["thread_spawn"] == {k: spawn[k] for k in ("parent_thread_id", "depth", "agent_path")}, "CHILD_SOURCE_PROJECTION_MISMATCH")
    child_id = child_meta.get("id")
    _require(isinstance(child_id, str) and _UUID.fullmatch(child_id) and child_id != expected_root, "CHILD_ID_NOT_DISTINCT")
    _require(child_meta.get("session_id") == expected_root and child_meta.get("thread_source") == "subagent"
             and spawn["parent_thread_id"] == expected_root and type(spawn["depth"]) is int and spawn["depth"] == 1
             and spawn["agent_path"] == expected_task, "CHILD_PARENT_CHAIN_MISMATCH")
    _require(child["environment_thread_hint"] == child_id, "ENVIRONMENT_HINT_MISMATCH")
    _require(capture["process_environment"] == {"CODEX_SESSION_ID": expected_root, "CODEX_THREAD_ID": child_id}, "PROCESS_ENVIRONMENT_PROJECTION_MISMATCH")
    child_turn = reader.record(child_path, child["turn_context"], "turn_context")
    model, effort = _turn(child_turn, child["turn_context"]["fields"], expected_turn, is_parent=False)
    _require(child_turn["turn_id"] != expected_turn, "CHILD_TURN_NOT_DISTINCT")
    if "model" in spawn_args:
        _require(isinstance(spawn_args["model"], str) and spawn_args["model"] == model, "REQUESTED_MODEL_NOT_OBSERVED")
    if "reasoning_effort" in spawn_args:
        _require(spawn_args["reasoning_effort"] == effort, "REQUESTED_EFFORT_NOT_OBSERVED")
    delegation = reader.record(child_path, child["first_delegation"], "response_item")
    fields = _object(child["first_delegation"]["fields"])
    _keys(fields, {"id", "author", "recipient", "content_part_metadata", "parent_dispatch_call_id", "parent_dispatch_message_utf8_sha256", "body_equivalence_status"})
    _project(delegation, {k: fields[k] for k in ("id", "author", "recipient")}, {"id", "author", "recipient"})
    _require(delegation.get("type") == "agent_message" and delegation.get("author") == "/root" and delegation.get("recipient") == expected_task, "FIRST_DELEGATION_ROUTE_MISMATCH")
    message_hash = _sha(spawn_args["message"].encode("utf-8"))
    _require(fields["parent_dispatch_call_id"] == call_id and fields["parent_dispatch_message_utf8_sha256"] == message_hash, "CHILD_PARENT_DISPATCH_REFERENCE_MISMATCH")
    content = delegation.get("content")
    _require(isinstance(content, list) and bool(content), "UNSUPPORTED_DELEGATION_CONTENT")
    part_metadata = []
    for index, part in enumerate(content):
        _object(part)
        _require(part.get("type") in {"input_text", "encrypted_content"}, "UNKNOWN_DELEGATION_PART")
        part_result = {"index": index, "type": part["type"], "encrypted_content_present": "encrypted_content" in part}
        if "text" in part:
            _require(isinstance(part["text"], str), "INVALID_DELEGATION_TEXT")
            part_hash = _sha(part["text"].encode("utf-8"))
            part_result.update({"text_utf8_sha256": part_hash, "text_character_count": len(part["text"]), "equals_parent_dispatch_hash": part_hash == message_hash})
        part_metadata.append(part_result)
    _require(part_metadata == fields["content_part_metadata"] and fields["body_equivalence_status"] == "NOT_PROVEN", "UNSUPPORTED_DELEGATION_BODY_CLAIM")
    _require(child["session_metadata"]["ref"]["byte_offset"] < child["turn_context"]["ref"]["byte_offset"] < child["first_delegation"]["ref"]["byte_offset"], "CHILD_RECORD_ORDER_MISMATCH")
    result = {
        "status": "IDENTITY_VERIFIED", "root_thread_id": expected_root, "root_turn_id": expected_turn,
        "task_path": expected_task, "child_thread_id": child_id, "child_turn_id": child_turn["turn_id"],
        "parent_model": parent_model, "parent_effort": parent_effort, "model": model, "effort": effort,
        "spawn_call_id": call_id, "dispatch_task_name": spawn_args["task_name"],
        "dispatch_message_utf8_sha256": message_hash,
        "verified_record_count": len(reader.refs), "verified_record_refs": reader.refs,
        "dispatch_body_equivalence": "NOT_PROVEN", "user_authorization": "NOT_ASSESSED",
        "trust_boundary": "Same-user local host records; no tamper isolation or backend model attestation.",
    }
    return result, spawn_args["message"]


def verify_identity(capture: dict, expected_root: str, expected_turn: str,
                    expected_task: str, allowed_log_paths: list[Path]) -> dict:
    """Verify the identity chain from raw allowlisted host records.

    Unknown consumed schemas, missing facts and mismatches raise EvidenceError.
    Only identity-related references are consumed; unrelated communication
    summaries in the capture are not granted any evidentiary authority.
    """
    return _verify(capture, expected_root, expected_turn, expected_task, allowed_log_paths)[0]


def verify_dispatch_input(capture: dict, expected_root: str, expected_turn: str,
                          expected_task: str, allowed_log_paths: list[Path], *,
                          role: str, input_sha256: str,
                          binding_mode: str = "message_markers_v1") -> dict:
    """Bind role and input to a caller-selected raw parent dispatch field.

    message_markers_v1 (default) requires exact standalone ROLE and INPUT_SHA256
    lines in the stored message. An opaque/encrypted message fails this mode.
    task_name_v2 requires the actual task_name to be exactly author_<full hash>
    or reviewer_<full hash>. It must be explicitly selected; no fallback exists.
    Neither mode decrypts content or proves child encrypted-body equivalence.
    """
    _require(isinstance(role, str) and role in {"AUTHOR", "REVIEWER"}, "UNKNOWN_ROLE")
    _require(isinstance(input_sha256, str) and _HASH.fullmatch(input_sha256), "INVALID_INPUT_SHA256")
    _require(isinstance(binding_mode, str) and binding_mode in {"message_markers_v1", "task_name_v2"}, "UNKNOWN_BINDING_MODE")
    result, message = _verify(capture, expected_root, expected_turn, expected_task, allowed_log_paths)
    if binding_mode == "message_markers_v1":
        lines = message.splitlines()
        role_lines = [line for line in lines if re.match(r"^\s*ROLE\s*=", line)]
        input_lines = [line for line in lines if re.match(r"^\s*INPUT_SHA256\s*=", line)]
        _require(role_lines == [f"ROLE={role}"], "ROLE_MARKER_MISSING_DUPLICATE_OR_MISMATCHED")
        _require(input_lines == [f"INPUT_SHA256={input_sha256}"], "INPUT_MARKER_MISSING_DUPLICATE_OR_MISMATCHED")
        binding_source = "Raw parent spawn_agent.arguments.message markers; child body equivalence remains unproven."
    else:
        expected_name = role.lower() + "_" + input_sha256
        _require(result["dispatch_task_name"] == expected_name, "TYPED_TASK_NAME_ROLE_OR_INPUT_MISMATCH")
        binding_source = "Raw parent spawn_agent.arguments.task_name, linked to its actual result and child agent_path; message plaintext and body equivalence remain unproven."
    result.update({"status": "PARENT_DISPATCH_INPUT_VERIFIED", "role": role, "input_sha256": input_sha256,
                   "binding_mode": binding_mode, "binding_source": binding_source,
                   "message_plaintext_verified": False})
    return result
