"""Synthetic client-boundary tests; mocks do not certify an actual GUI read."""
import copy
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import client, core, storage


ROOT = "11111111-1111-4111-8111-111111111111"
TURN = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
SECRET = "PRIVATE MESSAGE MUST NOT BE EXPORTED"


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="singlepaper-client-")
        self.base = Path(self.temporary.name)
        self.package = self.base / "package"
        self.package.mkdir()
        self.executable = self.base / "Obsidian.com"
        self.executable.write_bytes(b"SYNTHETIC EXECUTABLE NEVER LAUNCHED")
        self.codex_home=self.base/'codex-home'
        self.day=self.codex_home/'sessions'/datetime.now().astimezone().strftime('%Y/%m/%d')
        self.day.mkdir(parents=True)
        self.log=self.day/('rollout-'+datetime.now().astimezone().strftime('%Y-%m-%dT%H-%M-%S')+'-'+ROOT+'.jsonl')
        with closing(sqlite3.connect(self.codex_home/'state_5.sqlite')) as connection, connection:
            connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY,rollout_path TEXT NOT NULL,history_mode TEXT NOT NULL DEFAULT 'legacy')")
            connection.execute('INSERT INTO threads VALUES (?,?,?)',(ROOT,str(self.log),'legacy'))
        self.codex_env=patch.dict(os.environ,{'CODEX_HOME':str(self.codex_home),'CODEX_SESSION_ID':ROOT,'CODEX_THREAD_ID':ROOT})
        self.codex_env.start();self.addCleanup(self.codex_env.stop)
        self.records = [
            {"timestamp": "2026-10-13T00:00:00Z", "type": "session_meta", "payload": {
                "id": ROOT, "session_id": ROOT, "thread_source": "user"}},
            {"timestamp": "2026-10-13T00:01:00Z", "type": "turn_context", "payload": {
                "turn_id": TURN, "root_turn_id": TURN, "model": "test-model", "effort": "high",
                "collaboration_mode": {"mode": "default", "settings": {"model": "test-model", "reasoning_effort": "high"}}}},
            {"timestamp": "2026-10-13T00:01:01Z", "type": "response_item", "payload": {
                "type": "message", "content": [{"text": SECRET}]}}]
        self.write_log()
        self.context = {"root": ROOT, "turn": TURN, "allowed_log_paths": [str(self.log)]}
        self.instance = self.base / "instance"
        categories = [{"id": "DEMO", "label": "合成演示"}]
        confirmation = {"confirmed": True, "categories_sha256": core.sha(core.encode(categories)),
                        "scope": "SYNTHETIC_DEMO", "authorization": "客户端边界合成测试"}
        initialized = storage.initialize(self.instance, categories, confirmation)
        self.vault = self.instance / initialized["vault_dir"]

    def tearDown(self):
        self.temporary.cleanup()

    def write_log(self):
        self.log.write_bytes(b"".join((json.dumps(x, ensure_ascii=False) + "\n").encode("utf-8") for x in self.records))

    def completed(self, stdout="", returncode=0, stderr=""):
        return subprocess.CompletedProcess([], returncode, stdout.encode("utf-8"), stderr.encode("utf-8"))

    def prereq(self):
        return client.prereq(self.package, self.executable, self.context)

    def index_outputs(self, files=None, unresolved="0\n"):
        if files is None:
            library, _ = storage._library(self.instance)
            files = "\n".join(sorted(client._expected_files(library))) + "\n"
        return [self.completed(str(self.vault) + "\r\n"), self.completed(files), self.completed(unresolved)]

    def test_prereq_is_deterministic_and_has_precise_claim_boundary(self):
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4 (installer 1.12.7)\r\n")) as run:
            first = self.prereq()
            second = self.prereq()
        self.assertEqual(first, second)
        self.assertTrue(first["ok"])
        self.assertEqual(first["checks"]["codex"]["model"], "test-model")
        self.assertEqual(first["checks"]["obsidian_cli"]["version"], "1.14.4")
        self.assertFalse(first["formal_processing_allowed"])
        self.assertEqual(first["software_validation"], "NOT_RUN")
        self.assertEqual(first["client_reading"], "NOT_RUN")
        self.assertEqual(first["pdf_visual_validation"], "NOT_RUN")
        self.assertNotIn(SECRET, json.dumps(first))
        args, kwargs = run.call_args
        self.assertEqual(args[0], [str(self.executable), "version"])
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 15)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)

    def test_only_explicit_allowlist_files_are_consumed(self):
        (self.base / "unrelated-private.jsonl").write_text("INVALID SECRET", encoding="utf-8")
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
            self.assertTrue(self.prereq()["ok"])

    def test_duplicate_parent_logs_are_rejected(self):
        duplicate = self.base / "duplicate.jsonl"
        duplicate.write_bytes(self.log.read_bytes())
        self.context["allowed_log_paths"].append(str(duplicate))
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
            result = self.prereq()
        self.assertFalse(result["ok"])
        self.assertEqual(result["checks"]["codex"]["error"], "HOST_PARENT_LOG_NOT_UNIQUE")

    def test_exact_parent_selected_among_allowlisted_child(self):
        child = self.base / "child.jsonl"
        child_record = copy.deepcopy(self.records[0])
        child_record["payload"].update(id=OTHER, thread_source="subagent")
        child.write_bytes((json.dumps(child_record) + "\n").encode())
        self.context["allowed_log_paths"].insert(0, child)
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
            result = self.prereq()
        self.assertTrue(result["ok"])
        self.assertEqual(result["checks"]["codex"]["parent_log"], str(self.log))

    def test_old_turn_cannot_be_reused_after_later_turn(self):
        later = copy.deepcopy(self.records[1])
        later["payload"].update(turn_id=OTHER, root_turn_id=OTHER)
        self.records.append(later)
        self.write_log()
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
            result = self.prereq()
        self.assertEqual(result["checks"]["codex"]["error"], "HOST_CURRENT_TURN_MISMATCH")

    def test_doctor_rejects_completed_and_aborted_current_parent(self):
        original=copy.deepcopy(self.records)
        for kind in ('task_complete','turn_aborted','shutdown_complete'):
            with self.subTest(kind=kind):
                self.records=copy.deepcopy(original)
                self.records.append({'timestamp':'2026-10-13T00:02:00Z','type':'event_msg',
                    'payload':{'type':kind,'turn_id':TURN}})
                self.write_log()
                with patch.object(client.subprocess,'run',return_value=self.completed('1.14.4\n')):
                    result=self.prereq()
                self.assertEqual(result['checks']['codex']['error'],'HOST_PARENT_TURN_CLOSED')

    def test_doctor_does_not_accept_an_explicit_stale_source_against_index(self):
        current=self.log.with_name(self.log.stem+'_40000000-0000-0000-0000-000000000001.jsonl')
        current.write_bytes(self.log.read_bytes())
        with closing(sqlite3.connect(self.codex_home/'state_5.sqlite')) as connection, connection:
            connection.execute('UPDATE threads SET rollout_path=?,history_mode=? WHERE id=?',(str(current),'paginated',ROOT))
        with patch.object(client.subprocess,'run',return_value=self.completed('1.14.4\n')):
            result=self.prereq()
        self.assertEqual(result['checks']['codex']['error'],'HOST_INDEX_SOURCE_NOT_ALLOWLISTED')

    def test_parent_completion_appended_after_metadata_scan_is_rejected(self):
        original=client.evidence._Reader.record
        appended=False
        def append_then_read(reader,path,entry,kind):
            nonlocal appended
            if not appended and path==self.log and kind=='session_meta':
                appended=True
                event={'timestamp':'2026-10-13T00:02:00Z','type':'event_msg',
                       'payload':{'type':'task_complete','turn_id':TURN}}
                with self.log.open('ab') as stream:
                    stream.write((json.dumps(event)+'\n').encode('utf-8'))
            return original(reader,path,entry,kind)
        with patch.object(client.evidence._Reader,'record',new=append_then_read):
            with self.assertRaisesRegex(ValueError,'HOST_PARENT_TURN_CLOSED'):
                client._parent_proof(self.context)
        self.assertTrue(appended)

    def test_runtime_model_and_effort_must_agree_with_settings(self):
        self.records[1]["payload"]["effort"] = "low"
        self.write_log()
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
            result = self.prereq()
        self.assertEqual(result["checks"]["codex"]["error"], "MODEL_EFFORT_DISAGREEMENT")

    def test_runtime_identity_change_inside_same_turn_is_rejected(self):
        later = copy.deepcopy(self.records[1])
        later["payload"]["effort"] = "low"
        later["payload"]["collaboration_mode"]["settings"]["reasoning_effort"] = "low"
        self.records.append(later)
        self.write_log()
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
            result = self.prereq()
        self.assertEqual(result["checks"]["codex"]["error"], "HOST_MODEL_CHANGED_WITHIN_TURN")

    def test_session_identity_mismatch_is_rejected(self):
        self.records[0]["payload"]["session_id"] = OTHER
        self.write_log()
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
            self.assertEqual(self.prereq()["checks"]["codex"]["error"], "HOST_PARENT_IDENTITY_MISMATCH")

    def test_duplicate_session_metadata_is_rejected(self):
        self.records.insert(1, copy.deepcopy(self.records[0]))
        self.write_log()
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
            self.assertEqual(self.prereq()["checks"]["codex"]["error"], "HOST_PARENT_METADATA_NOT_UNIQUE")

    def test_partial_final_record_is_not_consumed(self):
        with self.log.open("ab") as stream:
            stream.write(b'{"type":"turn_context","payload":')
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
            result = self.prereq()
        self.assertTrue(result["ok"])
        self.assertLess(result["checks"]["codex"]["snapshot_boundary_bytes"], self.log.stat().st_size)

    def test_duplicate_json_field_is_rejected(self):
        with self.log.open("ab") as stream:
            stream.write(b'{"type":"turn_context","type":"response_item"}\n')
        with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
            self.assertEqual(self.prereq()["checks"]["codex"]["error"], "DUPLICATE_JSON_KEY")

    def test_allowlist_cannot_be_directory_or_relative(self):
        for value in (str(self.base), "parent.jsonl"):
            with self.subTest(value=value):
                self.context["allowed_log_paths"] = [value]
                with patch.object(client.subprocess, "run", return_value=self.completed("1.14.4\n")):
                    self.assertEqual(self.prereq()["checks"]["codex"]["error"], "HOST_LOG_EXPLICIT_PATH_REQUIRED")

    def test_executable_must_be_explicit_native_file(self):
        for value in (Path("Obsidian.com"), self.base / "wrapper.cmd"):
            value_to_make = self.base / "wrapper.cmd"
            value_to_make.write_bytes(b"SYNTHETIC")
            with self.subTest(value=value), patch.object(client.subprocess, "run") as run:
                result = client.prereq(self.package, value, self.context)
                self.assertFalse(result["ok"])
                run.assert_not_called()

    def test_timeout_and_untrusted_output_do_not_leak(self):
        with patch.object(client.subprocess, "run", side_effect=subprocess.TimeoutExpired(SECRET, 15, output=SECRET)):
            result = self.prereq()
        self.assertEqual(result["checks"]["obsidian_cli"]["error"], "CLIENT_TIMEOUT")
        self.assertNotIn(SECRET, json.dumps(result))

    def test_unknown_version_stdout_is_not_capability_pass(self):
        with patch.object(client.subprocess, "run", return_value=self.completed(SECRET)):
            result = self.prereq()
        self.assertFalse(result["ok"])
        self.assertEqual(result["checks"]["obsidian_cli"]["error"], "CLIENT_VERSION_FORMAT")
        self.assertNotIn(SECRET, json.dumps(result))

    def test_command_failure_and_stderr_are_not_pass(self):
        for completed, error in ((self.completed("1.14.4", 1), "CLIENT_COMMAND_FAILED"),
                                 (self.completed("1.14.4", 0, SECRET), "CLIENT_STDERR_NOT_EMPTY")):
            with self.subTest(error=error), patch.object(client.subprocess, "run", return_value=completed):
                check = self.prereq()["checks"]["obsidian_cli"]
                self.assertEqual(check["error"], error)
                self.assertEqual(check["command"]["exit_code"], completed.returncode)
                self.assertEqual(check["command"]["stderr_sha256"], core.sha(completed.stderr))
                self.assertNotIn(SECRET, json.dumps(check))

    def test_real_index_success_still_does_not_claim_pdf_visual_read(self):
        before = {p.relative_to(self.instance).as_posix(): p.read_bytes() for p in self.instance.rglob("*") if p.is_file()}
        with patch.object(client.subprocess, "run", side_effect=self.index_outputs()) as run:
            result = client.read_index(self.instance, self.executable)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["index_validation"], "PASS")
        self.assertEqual(result["unresolved"]["count"], 0)
        self.assertEqual(result["pdf_visual_validation"], "NOT_RUN")
        self.assertEqual(result["full_reading_validation"], "NOT_RUN")
        selector = "vault=" + self.vault.name
        self.assertEqual([call.args[0][1:] for call in run.call_args_list],
                         [[selector, "vault", "info=path"], [selector, "files"], [selector, "unresolved", "total"]])
        after = {p.relative_to(self.instance).as_posix(): p.read_bytes() for p in self.instance.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_wrong_vault_path_stops_before_files_or_unresolved(self):
        with patch.object(client.subprocess, "run", return_value=self.completed(str(self.base / "PrivateDefaultVault"))) as run:
            result = client.read_index(self.instance, self.executable)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["error"], "CLIENT_VAULT_PATH_MISMATCH")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result["files"]["status"], "NOT_RUN")

    def test_wrong_library_binding_causes_no_client_call(self):
        path = self.instance / ".system/library.json"
        value = core.read_json(path)
        value["root_binding"] = str(self.base / "different")
        path.write_bytes(core.encode(value))
        with patch.object(client.subprocess, "run") as run:
            result = client.read_index(self.instance, self.executable)
        self.assertFalse(result["ok"])
        run.assert_not_called()

    def test_missing_expected_file_stops_before_unresolved(self):
        with patch.object(client.subprocess, "run", side_effect=self.index_outputs(files="Library.md\n")) as run:
            result = client.read_index(self.instance, self.executable)
        self.assertFalse(result["ok"])
        self.assertEqual(result["files"]["error"], "CLIENT_EXPECTED_FILES_MISSING")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result["unresolved"]["status"], "NOT_RUN")

    def test_index_relative_path_escape_is_rejected(self):
        with patch.object(client.subprocess, "run", side_effect=self.index_outputs(files="../private.md\n")):
            result = client.read_index(self.instance, self.executable)
        self.assertFalse(result["ok"])
        self.assertEqual(result["files"]["error"], "INVALID_PATH_PART")

    def test_duplicate_index_file_is_rejected(self):
        with patch.object(client.subprocess, "run", side_effect=self.index_outputs(files="Library.md\nlibrary.md\n")):
            self.assertEqual(client.read_index(self.instance, self.executable)["files"]["error"], "CLIENT_FILE_DUPLICATE")

    def test_unknown_unresolved_output_cannot_pass(self):
        with patch.object(client.subprocess, "run", side_effect=self.index_outputs(unresolved=SECRET + "\n")):
            result = client.read_index(self.instance, self.executable)
        self.assertFalse(result["ok"])
        self.assertEqual(result["unresolved"]["error"], "CLIENT_UNRESOLVED_COUNT_FORMAT")
        self.assertNotIn(SECRET, json.dumps(result))

    def test_actual_total_zero_format_passes_with_standard_line_endings(self):
        for output in ("0\n", "0\r\n", "0"):
            with self.subTest(output=repr(output)), patch.object(client.subprocess, "run", side_effect=self.index_outputs(unresolved=output)):
                result = client.read_index(self.instance, self.executable)
            self.assertTrue(result["ok"])
            self.assertEqual(result["unresolved"]["count"], 0)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["pdf_visual_validation"], "NOT_RUN")

    def test_positive_unresolved_total_is_rejected(self):
        for output in ("1\n", "12\r\n", "90"):
            with self.subTest(output=repr(output)), patch.object(client.subprocess, "run", side_effect=self.index_outputs(unresolved=output)):
                result = client.read_index(self.instance, self.executable)
            self.assertFalse(result["ok"])
            self.assertEqual(result["unresolved"]["error"], "CLIENT_UNRESOLVED_LINKS")
            self.assertEqual(result["unresolved"]["count"], int(output))

    def test_non_count_unresolved_formats_are_rejected(self):
        for output in ("No unresolved links found.\n", "", "\n", "-1\n", "+0\n",
                       "0.0\n", "Total: 0\n", "banner\n0\n", "0\n0\n", "0\n\n",
                       "\n0\n", " 0\n", "0 \n", "０\n"):
            with self.subTest(output=repr(output)), patch.object(client.subprocess, "run", side_effect=self.index_outputs(unresolved=output)):
                result = client.read_index(self.instance, self.executable)
            self.assertFalse(result["ok"])
            self.assertEqual(result["unresolved"]["error"], "CLIENT_UNRESOLVED_COUNT_FORMAT")
            self.assertEqual(result["unresolved"]["command"]["arguments"],
                             ["vault=" + self.vault.name, "unresolved", "total"])

    def test_library_drift_during_client_probe_is_rejected(self):
        outputs = self.index_outputs()
        def run(*args, **kwargs):
            result = outputs.pop(0)
            if not outputs:
                path = self.instance / ".system/library.json"
                value = core.read_json(path)
                value["revision"] += 1
                path.write_bytes(core.encode(value))
            return result
        with patch.object(client.subprocess, "run", side_effect=run):
            result = client.read_index(self.instance, self.executable)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["error"], "CLIENT_LIBRARY_CHANGED")


if __name__ == "__main__":
    unittest.main()
