"""Synthetic mechanism tests; mocked gates prove no real scientific review."""
import copy
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app import core, storage
from app.core import encode, read_json, ref, sha, utcnow, writer


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="singlepaper-storage-")
        self.base = Path(self.temporary.name)
        self.root = self.base / "instance"
        categories = [{"id": "DEMO", "label": "合成演示"}]
        confirmation = {"confirmed": True, "categories_sha256": sha(encode(categories)),
                        "scope": "SYNTHETIC_DEMO", "authorization": "机制测试：仅合成夹具"}
        self.initialized = storage.initialize(self.root, categories, confirmation)
        self.vault = self.root / self.initialized["vault_dir"]
        self.bundle, self.metadata = self.bundle_metadata("one")
        self.gate = lambda: {"mechanism_test_only": True, "review_ref": "mock-frozen-review"}

    def tearDown(self):
        self.temporary.cleanup()

    def bundle_metadata(self, name):
        bundle = self.base / ("bundle-" + name)
        bundle.mkdir()
        values = {"source.pdf": b"%PDF-1.7\nSYNTHETIC STORAGE TEST ONLY " + name.encode(),
                  "source.md": b"# Synthetic source\n\n![Figure 1](figures/Figure-01.png)\n",
                  "translation_zh.md": "# 合成译文\n\n![图1](figures/Figure-01.png)\n".encode(),
                  "summary.md": "# 合成摘要\n".encode(), "science_notes.md": "# 合成说明\n".encode(),
                  "provenance.json": encode({"synthetic_storage_fixture": True}),
                  "figures/Figure-01.png": b"SYNTHETIC IMAGE BYTES, NOT A CLIENT TEST"}
        for relative, data in values.items():
            path = bundle / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        metadata = {"title": "合成测试 " + name, "category_id": "DEMO", "pdf_sha256": sha(values["source.pdf"]),
                    "page_count": 2, "run_id": "synthetic-" + name, "input_sha256": sha(b"frozen-inputs-" + name.encode()),
                    "deadline_utc": (utcnow() + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
                    "instance_id": self.initialized["instance_id"],
                    "assets": [ref(bundle, bundle / key) for key in sorted(values)]}
        return bundle, metadata

    def prepare(self):
        return storage.prepare(self.root, self.bundle, self.metadata, self.gate)

    def library(self):
        return read_json(self.root / ".system/library.json")

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_initialization_is_new_unique_and_exact_confirmation(self):
        self.assertEqual(storage.verify(self.root)["works"], 0)
        self.assertEqual(self.vault.name, "Reading-" + self.initialized["instance_id"][:8])
        with self.assertRaisesRegex(ValueError, "ROOT_MUST_BE_NEW"):
            storage.initialize(self.root, [], {})
        categories = [{"id": "DEMO", "label": "演示"}]
        with self.assertRaisesRegex(ValueError, "CATEGORY_CONFIRMATION_MISMATCH"):
            storage.initialize(self.base / "bad", categories, {"confirmed": True, "categories_sha256": "0" * 64})
        self.assertFalse((self.base / "bad").exists())

    def test_success_frozen_assets_relations_and_readonly_verification(self):
        plan_ref = self.prepare()
        self.assertEqual(self.library()["revision"], 0)
        self.assertFalse((self.vault / "papers/W0001.md").exists())
        receipt = storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(receipt["status"], "STORED_OUTPUT_VERIFIED")
        self.assertEqual(receipt["client_validation"], "NOT_RUN")
        self.assertEqual(self.library()["revision"], 2)
        self.assertEqual(self.library()["works"][0]["status"], "STORED_OUTPUT_VERIFIED")
        self.assertIn("../domains/DEMO.md", (self.vault / "papers/W0001.md").read_text(encoding="utf-8"))
        self.assertIn("反向链接", (self.vault / "domains/DEMO.md").read_text(encoding="utf-8"))
        self.assertNotIn("W0001", (self.vault / "domains/DEMO.md").read_text(encoding="utf-8"))
        self.assertIn("../papers/W0001.md", (self.root / self.library()["overview"]["path"]).read_text(encoding="utf-8"))
        before = self.snapshot()
        result = storage.verify(self.root)
        self.assertEqual((result["works"], result["assets_checked"]), (1, 7))
        self.assertEqual(before, self.snapshot())

    def test_duplicate_publish_idempotent_and_same_pdf_cannot_get_new_id(self):
        plan_ref = self.prepare()
        first = storage.publish(self.root, plan_ref, self.gate)
        before = self.snapshot()
        self.assertEqual(first, storage.publish(self.root, plan_ref, lambda: self.fail("gate called after commit")))
        self.assertEqual(before, self.snapshot())
        with self.assertRaisesRegex(ValueError, "PDF_ALREADY_REGISTERED"):
            self.prepare()
        self.assertEqual(len(self.library()["works"]), 1)

    def test_two_distinct_pdfs_get_distinct_ids_and_old_plan_is_superseded(self):
        first = self.prepare()
        storage.publish(self.root, first, self.gate)
        bundle2, metadata2 = self.bundle_metadata("two")
        second = storage.prepare(self.root, bundle2, metadata2, self.gate)
        storage.publish(self.root, second, self.gate)
        before = self.snapshot()
        self.assertEqual(storage.publish(self.root, first, self.gate)["status"], "SUPERSEDED")
        self.assertEqual(storage.recover(self.root, first)["status"], "SUPERSEDED")
        self.assertEqual(before, self.snapshot())
        self.assertEqual([w["id"] for w in self.library()["works"]], ["W0001", "W0002"])
        self.assertEqual(storage.verify(self.root)["works"], 2)

    def test_beforecommit_failure_preserves_library_and_intent_then_retry(self):
        plan_ref = self.prepare()
        original = (self.root / ".system/library.json").read_bytes()
        with patch.object(storage, "cas", side_effect=OSError("simulated-beforecommit")):
            with self.assertRaisesRegex(OSError, "simulated-beforecommit"):
                storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(original, (self.root / ".system/library.json").read_bytes())
        self.assertTrue((self.root / plan_ref["path"]).with_name("intent.json").is_file())
        with self.assertRaisesRegex(ValueError, "NOT_COMMITTED_NO_RECOVERY"):
            storage.recover(self.root, plan_ref)
        self.assertEqual(storage.publish(self.root, plan_ref, self.gate)["status"], "STORED_OUTPUT_VERIFIED")

    def test_aftercommit_failure_recovery_after_deadline_uses_frozen_stage(self):
        plan_ref = self.prepare()
        with patch.object(storage, "_apply_outputs", side_effect=OSError("simulated-aftercommit")):
            with self.assertRaisesRegex(OSError, "simulated-aftercommit"):
                storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(self.library()["works"][0]["status"], "COMMITTED_READING_PENDING")
        with self.assertRaisesRegex(ValueError, "READING_OUTPUT_PENDING"):
            storage.verify(self.root)
        # Source and review may be unavailable after commit. Recovery does not reopen them.
        for path in self.bundle.rglob("*"):
            if path.is_file():
                path.write_bytes(b"unavailable-after-commit")
        with patch.object(storage, "utcnow", return_value=utcnow() + timedelta(hours=2)):
            self.assertEqual(storage.recover(self.root, plan_ref)["status"], "STORED_OUTPUT_VERIFIED")
        self.assertEqual(storage.verify(self.root)["works"], 1)

    def test_intermediate_output_failure_recovers_without_replacing_written_asset(self):
        plan_ref = self.prepare()
        real_put = storage.put
        count = [0]

        def interrupted(path, data):
            if "/assets/" in Path(path).as_posix() and "/stage/" not in Path(path).as_posix():
                count[0] += 1
                if count[0] == 3:
                    raise OSError("simulated-mid-output")
            return real_put(path, data)

        with patch.object(storage, "put", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "simulated-mid-output"):
                storage.publish(self.root, plan_ref, self.gate)
        files = list((self.vault / "assets").rglob("*"))
        prior = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files if p.is_file()}
        self.assertEqual(len(prior), 2)
        storage.recover(self.root, plan_ref)
        for path, state in prior.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state)
        self.assertEqual(storage.verify(self.root)["works"], 1)

    def test_receipt_failure_after_complete_library_can_recover(self):
        plan_ref = self.prepare()
        original = storage.write_json_new

        def fail_receipt(path, value):
            if Path(path).name == "receipt.json":
                raise OSError("simulated-receipt-failure")
            return original(path, value)

        with patch.object(storage, "write_json_new", side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, "simulated-receipt-failure"):
                storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(self.library()["works"][0]["status"], "STORED_OUTPUT_VERIFIED")
        with self.assertRaisesRegex(ValueError, "FILE_MISSING"):
            storage.verify(self.root)
        self.assertEqual(storage.recover(self.root, plan_ref)["status"], "STORED_OUTPUT_VERIFIED")

    def test_verification_rejects_complete_library_revision_drift(self):
        storage.publish(self.root, self.prepare(), self.gate)
        library = self.library()
        library["revision"] += 1
        (self.root / ".system/library.json").write_bytes(encode(library))
        with self.assertRaisesRegex(ValueError, "LIBRARY_DRIFT"):
            storage.verify(self.root)

    def test_verification_rejects_changed_confirmation_authorization(self):
        path = self.root / ".system/category-confirmation.json"
        confirmation = read_json(path)
        confirmation["authorization"] = "changed authority claim"
        path.write_bytes(encode(confirmation))
        with self.assertRaisesRegex(ValueError, "REFERENCE_DRIFT"):
            storage.verify(self.root)

    def test_uncommitted_expiry_cannot_publish_or_recover(self):
        plan_ref = self.prepare()
        original = (self.root / ".system/library.json").read_bytes()
        with patch.object(storage, "utcnow", return_value=utcnow() + timedelta(hours=2)):
            with self.assertRaisesRegex(ValueError, "DEADLINE_EXPIRED"):
                storage.publish(self.root, plan_ref, self.gate)
            with self.assertRaisesRegex(ValueError, "DEADLINE_EXPIRED"):
                storage.recover(self.root, plan_ref)
        self.assertEqual(original, (self.root / ".system/library.json").read_bytes())

    def test_deadline_rechecked_after_slow_gate(self):
        plan_ref = self.prepare()
        future = utcnow() + timedelta(hours=2)

        def slow_gate():
            self.clock = patch.object(storage, "utcnow", return_value=future)
            self.clock.start()
            return self.gate()

        try:
            with self.assertRaisesRegex(ValueError, "DEADLINE_EXPIRED"):
                storage.publish(self.root, plan_ref, slow_gate)
        finally:
            self.clock.stop()
        self.assertEqual(self.library()["revision"], 0)

    def test_gate_drift_does_not_commit(self):
        plan_ref = self.prepare()
        with self.assertRaisesRegex(ValueError, "REVIEW_GATE_DRIFT"):
            storage.publish(self.root, plan_ref, lambda: {"different": True})
        self.assertEqual(self.library()["revision"], 0)

    def test_input_changed_during_intent_write_cannot_commit(self):
        plan_ref = self.prepare()
        original = storage.write_json_new

        def changed_during_intent(path, value):
            original(path, value)
            if Path(path).name == "intent.json":
                (self.bundle / "source.md").write_bytes(b"changed after prevalidation")

        with patch.object(storage, "write_json_new", side_effect=changed_during_intent):
            with self.assertRaisesRegex(ValueError, "REFERENCE_DRIFT"):
                storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(self.library()["revision"], 0)

    def test_staged_input_changed_during_output_stops_completion(self):
        plan_ref = self.prepare()
        plan = read_json(self.root / plan_ref["path"])
        original = storage._apply_outputs

        def changed_during_output(root, value):
            original(root, value)
            (self.root / plan["outputs"][0]["staged"]["path"]).write_bytes(b"changed after output write")

        with patch.object(storage, "_apply_outputs", side_effect=changed_during_output):
            with self.assertRaisesRegex(ValueError, "REFERENCE_DRIFT"):
                storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(self.library()["works"][0]["status"], "COMMITTED_READING_PENDING")

    def test_source_drift_does_not_commit(self):
        plan_ref = self.prepare()
        (self.bundle / "summary.md").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "REFERENCE_DRIFT"):
            storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(self.library()["revision"], 0)

    def test_bundle_addition_and_path_traversal_rejected(self):
        (self.bundle / "extra.txt").write_bytes(b"unexpected")
        with self.assertRaisesRegex(ValueError, "BUNDLE_INVENTORY_DRIFT"):
            self.prepare()
        (self.bundle / "extra.txt").unlink()
        metadata = copy.deepcopy(self.metadata)
        metadata["assets"][0]["path"] = "../private.txt"
        with self.assertRaisesRegex(ValueError, "ASSET_NOT_ALLOWED"):
            storage.prepare(self.root, self.bundle, metadata, self.gate)

    def test_hardlinked_asset_rejected(self):
        outside = self.base / "outside.txt"
        outside.write_bytes(b"private sentinel")
        target = self.bundle / "summary.md"
        target.unlink()
        os.link(outside, target)
        with self.assertRaisesRegex(ValueError, "HARDLINK_PATH"):
            self.prepare()
        self.assertEqual(outside.read_bytes(), b"private sentinel")

    def test_old_library_drift_rejects_and_preserves_new_bytes(self):
        plan_ref = self.prepare()
        path = self.root / ".system/library.json"
        library = self.library()
        library["revision"] += 1
        drifted = encode(library)
        path.write_bytes(drifted)
        with self.assertRaisesRegex(ValueError, "LIBRARY_DRIFT"):
            storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(path.read_bytes(), drifted)

    def test_generated_page_user_edits_rejected_beforecommit(self):
        plan_ref = self.prepare()
        path = self.vault / "domains/DEMO.md"
        changed = path.read_bytes() + "\n用户写入\n".encode()
        path.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "GENERATED_PAGE_DRIFT"):
            storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(path.read_bytes(), changed)
        self.assertEqual(self.library()["revision"], 0)

    def test_generated_page_user_edits_rejected_aftercommit(self):
        plan_ref = self.prepare()
        with patch.object(storage, "_apply_outputs", side_effect=OSError("pause")):
            with self.assertRaises(OSError):
                storage.publish(self.root, plan_ref, self.gate)
        path = self.vault / "domains/DEMO.md"
        changed = path.read_bytes() + b"user edit\n"
        path.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "GENERATED_PAGE_DRIFT"):
            storage.recover(self.root, plan_ref)
        self.assertEqual(path.read_bytes(), changed)
        self.assertEqual(self.library()["works"][0]["status"], "COMMITTED_READING_PENDING")

    def test_user_notes_ideas_and_graph_never_overwritten(self):
        note = self.vault / "user/notes/W0001.md"
        note.parent.mkdir()
        note.write_bytes(b"private user note\n")
        idea = self.vault / "user/ideas/README.md"
        idea.write_bytes(b"private idea\n")
        graph = self.vault / ".obsidian/graph.json"
        graph.write_bytes(b'{"custom_user_settings":true}\n')
        plan_ref = self.prepare()
        note.write_bytes(b"concurrent changed user note\n")
        storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(note.read_bytes(), b"concurrent changed user note\n")
        self.assertEqual(idea.read_bytes(), b"private idea\n")
        self.assertEqual(graph.read_bytes(), b'{"custom_user_settings":true}\n')
        self.assertEqual(storage.verify(self.root)["status"], "VERIFIED")

    def test_concurrent_user_note_creation_is_preserved(self):
        plan_ref = self.prepare()
        note = self.vault / "user/notes/W0001.md"
        real_put = storage.put

        def race(path, data):
            if Path(path) == note:
                note.parent.mkdir(parents=True, exist_ok=True)
                note.write_bytes(b"user won the creation race")
            return real_put(path, data)

        with patch.object(storage, "put", side_effect=race):
            storage.publish(self.root, plan_ref, self.gate)
        self.assertEqual(note.read_bytes(), b"user won the creation race")

    def test_recovery_rejects_mutated_stage_without_writing_outputs(self):
        plan_ref = self.prepare()
        with patch.object(storage, "_apply_outputs", side_effect=OSError("pause")):
            with self.assertRaises(OSError):
                storage.publish(self.root, plan_ref, self.gate)
        plan = read_json(self.root / plan_ref["path"])
        target = self.root / plan["outputs"][0]["staged"]["path"]
        target.write_bytes(b"tampered staged content")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "REFERENCE_DRIFT"):
            storage.recover(self.root, plan_ref)
        self.assertEqual(before, self.snapshot())

    def test_recovery_rejects_plan_or_snapshot_tampering(self):
        plan_ref = self.prepare()
        with patch.object(storage, "_apply_outputs", side_effect=OSError("pause")):
            with self.assertRaises(OSError):
                storage.publish(self.root, plan_ref, self.gate)
        plan_path = self.root / plan_ref["path"]
        plan_path.write_bytes(plan_path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "REFERENCE_DRIFT"):
            storage.recover(self.root, plan_ref)

    def test_pending_work_blocks_next_prepare(self):
        plan_ref = self.prepare()
        with patch.object(storage, "_apply_outputs", side_effect=OSError("pause")):
            with self.assertRaises(OSError):
                storage.publish(self.root, plan_ref, self.gate)
        bundle2, metadata2 = self.bundle_metadata("two")
        with self.assertRaisesRegex(ValueError, "PENDING_COMMIT_EXISTS"):
            storage.prepare(self.root, bundle2, metadata2, self.gate)

    def test_separate_process_writer_is_excluded(self):
        plan_ref = self.prepare()
        package = Path(__file__).resolve().parents[1]
        runtime = package / 'runtime'
        executable = runtime / 'python/python.exe'
        code = (
            "import sys; from pathlib import Path\n"
            "package=Path(sys.argv[1]).resolve(strict=True); runtime=package/'runtime'\n"
            "if Path(sys.executable).resolve()!=(runtime/'python/python.exe').resolve(): raise SystemExit('BUNDLED_PYTHON_REQUIRED')\n"
            "sys.dont_write_bytecode=True\n"
            "sys.path[:]=[str(runtime/'python/Lib'),str(runtime/'python/DLLs'),str(runtime/'python'/f'python{sys.version_info.major}{sys.version_info.minor}.zip'),str(runtime/'python'),str(runtime/'vendor'),str(runtime/'pdf-text-v1'),str(package)]\n"
            "import json; from app import storage\n"
            "try:\n"
            " storage.publish(Path(sys.argv[2]),json.loads(sys.argv[3]),lambda: {'mechanism_test_only':True,'review_ref':'mock-frozen-review'})\n"
            "except ValueError as exc:\n"
            " print(str(exc)); sys.exit(7 if str(exc)=='WRITER_BUSY' else 8)\n"
        )
        with writer(self.root):
            result = subprocess.run([str(executable), '-X', 'utf8', '-I', '-S', '-B', '-c', code,
                                     str(package), str(self.root), json.dumps(plan_ref)],
                                    cwd=package, capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "WRITER_BUSY")
        self.assertEqual(self.library()["revision"], 0)
        self.assertEqual(storage.publish(self.root, plan_ref, self.gate)["status"], "STORED_OUTPUT_VERIFIED")

    def test_reserved_category_names_fail_before_creating_any_root(self):
        for identifier in ["CON", "prn", "AUX", "NUL", "COM1", "LPT9"]:
            with self.subTest(identifier=identifier):
                categories = [{"id": identifier, "label": "Reserved-name fixture"}]
                confirmation = {"confirmed": True, "scope": "USER_CONFIRMED",
                                "categories_sha256": sha(encode(categories)), "authorization": "Synthetic mechanism test"}
                destination = self.base / ("reject-" + identifier)
                with self.assertRaisesRegex(ValueError, "RESERVED_PATH"):
                    storage.initialize(destination, categories, confirmation)
                self.assertFalse(destination.exists())

    def test_graph_search_selects_only_root_paper_domain_markdown(self):
        graph = read_json(self.vault / ".obsidian/graph.json")
        query = graph["search"]
        self.assertTrue(query.startswith("path:/") and query.endswith("/"))
        pattern = re.compile(query[len("path:/"):-1])
        expected = ["papers/W0001.md", "domains/DEMO.md", "papers/合成名称.md"]
        rejected = ["assets/papers.md", "papers_backup/example.md", "domains_old/example.md",
                    "assets/domains/example.md", "assets/W0001/r001/papers/example.md",
                    "assets/papers/W0001.md", "user/notes/W0001.md", "user/ideas/DEMO.md",
                    "indexes/Library-000002.md", "Library.md", "papers/sub/example.md",
                    "domains/sub/example.md", "papers/W0001.pdf", "papers/W0001.md.backup",
                    "other/papers/W0001.md", "domains/DEMO.md/file.md", "papers/.png"]
        for path in expected:
            with self.subTest(expected=path):
                self.assertIsNotNone(pattern.search(path))
        for path in rejected:
            with self.subTest(rejected=path):
                self.assertIsNone(pattern.search(path))
        self.assertIs(graph["showAttachments"], False)
        self.assertIs(graph["showTags"], False)
        self.assertIs(graph["hideUnresolved"], True)

    def test_graph_color_queries_use_the_same_exact_root_scope(self):
        graph = read_json(self.vault / ".obsidian/graph.json")
        paper, domain = [re.compile(item["query"][len("path:/"):-1]) for item in graph["colorGroups"]]
        for path, expected in [("papers/W0001.md", (True, False)), ("domains/DEMO.md", (False, True)),
                               ("assets/papers/W0001.md", (False, False)), ("papers_backup/W0001.md", (False, False)),
                               ("domains_old/DEMO.md", (False, False)), ("domains/nested/DEMO.md", (False, False)),
                               ("domains/DEMO.pdf", (False, False))]:
            with self.subTest(path=path):
                self.assertEqual((bool(paper.search(path)), bool(domain.search(path))), expected)

    def test_plain_copy_to_other_root_rejects_without_rebinding(self):
        copied = self.base / "copied-instance"
        shutil.copytree(self.root, copied)
        with self.assertRaisesRegex(ValueError, "ROOT_BINDING_MISMATCH"):
            storage.verify(copied)
        self.assertEqual(storage.verify(self.root)["works"], 0)

    def test_each_publish_creates_new_index_and_never_cas_replaces_visible_pages(self):
        fixed_paths = [self.vault / "Library.md", self.vault / "domains/DEMO.md", self.root / self.library()["overview"]["path"]]
        initial = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in fixed_paths}
        original_cas = storage.cas
        called = []

        def private_library_cas_only(path, before, after):
            self.assertEqual(Path(path), self.root / ".system/library.json")
            called.append(path)
            return original_cas(path, before, after)

        with patch.object(storage, "cas", side_effect=private_library_cas_only):
            first = self.prepare()
            storage.publish(self.root, first, self.gate)
            index1 = self.root / self.library()["overview"]["path"]
            index1_original = (index1.read_bytes(), index1.stat().st_mtime_ns)
            bundle2, metadata2 = self.bundle_metadata("two")
            second = storage.prepare(self.root, bundle2, metadata2, self.gate)
            storage.publish(self.root, second, self.gate)
        self.assertEqual(len(called), 4)
        self.assertEqual(index1.name, "Library-000002.md")
        self.assertEqual(Path(self.library()["overview"]["path"]).name, "Library-000004.md")
        self.assertEqual((index1.read_bytes(), index1.stat().st_mtime_ns), index1_original)
        for path, expected in initial.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), expected)

    def _external_write(self, path, content):
        result = subprocess.run(
            [sys.executable, "-c", "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(bytes.fromhex(sys.argv[2]))", str(path), content.hex()],
            capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_real_external_process_edits_static_domain_during_commit_are_preserved(self):
        plan_ref = self.prepare()
        domain = self.vault / "domains/DEMO.md"
        external_content = domain.read_bytes() + b"\nEXTERNAL USER CONTENT\n"
        original_cas = storage.cas
        edited = [False]

        def edit_during_commit(path, before, after):
            result = original_cas(path, before, after)
            if not edited[0]:
                edited[0] = True
                self._external_write(domain, external_content)
            return result

        with patch.object(storage, "cas", side_effect=edit_during_commit):
            with self.assertRaisesRegex(ValueError, "GENERATED_PAGE_DRIFT"):
                storage.publish(self.root, plan_ref, self.gate)
        self.assertTrue(edited[0])
        self.assertEqual(domain.read_bytes(), external_content)
        self.assertEqual(self.library()["works"][0]["status"], "COMMITTED_READING_PENDING")

    def test_real_external_process_wins_new_paper_creation_without_being_overwritten(self):
        self._external_creation_wins("paper")

    def test_real_external_process_wins_new_index_creation_without_being_overwritten(self):
        self._external_creation_wins("index")

    def _external_creation_wins(self, kind):
        plan_ref = self.prepare()
        plan = read_json(self.root / plan_ref["path"])
        final_library = read_json(self.root / plan["library"]["l2"]["path"])
        target = self.root / (final_library["overview"]["path"] if kind == "index" else final_library["works"][0]["reading"]["paper"])
        external_content = b"EXTERNAL USER CREATED THIS FILE IN THE NO-REPLACE RENAME GAP\n"
        original_stage = core._stage
        raced = [False]

        def race_after_stage(path, data):
            result = original_stage(path, data)
            if Path(path) == target and not raced[0]:
                raced[0] = True
                self._external_write(target, external_content)
            return result

        with patch.object(core, "_stage", side_effect=race_after_stage):
            with self.assertRaisesRegex(ValueError, "IMMUTABLE_TARGET_CHANGED"):
                storage.publish(self.root, plan_ref, self.gate)
        self.assertTrue(raced[0])
        self.assertEqual(target.read_bytes(), external_content)
        self.assertEqual(self.library()["works"][0]["status"], "COMMITTED_READING_PENDING")
        with self.assertRaisesRegex(ValueError, "GENERATED_PAGE_DRIFT"):
            storage.recover(self.root, plan_ref)
        self.assertEqual(target.read_bytes(), external_content)

    def _rewrite_plan(self, original_ref, plan):
        path = self.root / original_ref["path"]
        path.write_bytes(encode(plan))
        return ref(self.root, path)

    def _rewrite_candidate_libraries(self, plan, change, *, render=False):
        values = {}
        for name in ("l1", "l2"):
            path = self.root / plan["library"][name]["path"]
            value = read_json(path)
            change(value)
            values[name] = value
        if render:
            complete = values["l2"]
            new_index = storage._overview(complete)
            for value in values.values():
                value["overview"].update(sha256=sha(new_index), bytes=len(new_index))
            paper_target = complete["works"][-1]["reading"]["paper"]
            for output in plan["outputs"]:
                if output["target"] in (paper_target, complete["overview"]["path"]):
                    content = (storage._paper(complete["works"][-1], complete["categories"])
                               if output["target"] == paper_target else new_index)
                    path = self.root / output["staged"]["path"]
                    path.write_bytes(content)
                    output["staged"] = ref(self.root, path)
        for name, value in values.items():
            path = self.root / plan["library"][name]["path"]
            path.write_bytes(encode(value))
            plan["library"][name] = ref(self.root, path)

    def _assert_derived_rejection(self, mutate, code):
        original_ref = self.prepare()
        plan = read_json(self.root / original_ref["path"])
        original_metadata = copy.deepcopy(plan["metadata"])
        original_gate = copy.deepcopy(plan["gate_receipt"])
        original_inputs = copy.deepcopy(plan["inputs"])
        live = (self.root / ".system/library.json").read_bytes()
        mutate(plan)
        changed_ref = self._rewrite_plan(original_ref, plan)
        with self.assertRaisesRegex(ValueError, code):
            storage.publish(self.root, changed_ref, self.gate)
        self.assertEqual((self.root / ".system/library.json").read_bytes(), live)
        return plan, original_metadata, original_gate, original_inputs

    def test_derivation_rejects_coordinated_title_library_paper_and_index_tamper(self):
        def mutate(plan):
            self._rewrite_candidate_libraries(plan, lambda lib: lib["works"][-1].update(title="UNREVIEWED TITLE"), render=True)
        plan, metadata, gate, inputs = self._assert_derived_rejection(mutate, "PLAN_L1_DERIVATION")
        self.assertEqual((plan["metadata"], plan["gate_receipt"], plan["inputs"]), (metadata, gate, inputs))

    def test_derivation_rejects_coordinated_category_and_reading_page_tamper(self):
        self.root = self.base / "multi-category-instance"
        categories = [{"id": "A", "label": "Synthetic A"}, {"id": "B", "label": "Synthetic B"}]
        self.initialized = storage.initialize(self.root, categories, {
            "confirmed": True, "scope": "USER_CONFIRMED", "authorization": "Synthetic test only",
            "categories_sha256": sha(encode(categories))})
        self.vault = self.root / self.initialized["vault_dir"]
        self.metadata.update(instance_id=self.initialized["instance_id"], category_id="A")
        def change(lib):
            lib["works"][-1]["category_id"] = "B"
            lib["works"][-1]["reading"]["category"] = f"{lib['vault_dir']}/domains/B.md"
        self._assert_derived_rejection(lambda p: self._rewrite_candidate_libraries(p, change, render=True), "PLAN_L1_DERIVATION")

    def test_derivation_rejects_coordinated_summary_bytes_and_asset_refs_tamper(self):
        def mutate(plan):
            output = next(o for o in plan["outputs"] if o["target"].endswith("/summary.md"))
            path = self.root / output["staged"]["path"]
            path.write_bytes(b"Unreviewed replacement scientific summary\n")
            output["staged"] = ref(self.root, path)
            def change(lib):
                asset = next(a for a in lib["works"][-1]["assets"] if a["path"].endswith("/summary.md"))
                asset.update(sha256=output["staged"]["sha256"], bytes=output["staged"]["bytes"])
            self._rewrite_candidate_libraries(plan, change)
        plan, metadata, gate, inputs = self._assert_derived_rejection(mutate, "PLAN_L1_DERIVATION")
        self.assertEqual((plan["metadata"], plan["gate_receipt"], plan["inputs"]), (metadata, gate, inputs))

    def test_derivation_rejects_staged_summary_hash_reseal_without_library_change(self):
        def mutate(plan):
            output = next(o for o in plan["outputs"] if o["target"].endswith("/summary.md"))
            path = self.root / output["staged"]["path"]
            path.write_bytes(b"Unreviewed replacement bytes\n")
            output["staged"] = ref(self.root, path)
        self._assert_derived_rejection(mutate, "PLAN_STAGE_DERIVATION")

    def test_derivation_rejects_added_removed_reordered_or_retargeted_outputs(self):
        mutations = [
            (lambda p: p["outputs"].pop(), "PLAN_OUTPUT_COUNT"),
            (lambda p: p["outputs"].append(copy.deepcopy(p["outputs"][0])), "PLAN_OUTPUT_COUNT"),
            (lambda p: p["outputs"].reverse(), "PLAN_OUTPUT_DERIVATION"),
            (lambda p: p["outputs"][0].update(target="other/unreviewed.md"), "PLAN_OUTPUT_DERIVATION"),
            (lambda p: p["outputs"][0].update(policy="USER_CREATE"), "PLAN_OUTPUT_DERIVATION"),
            (lambda p: p["outputs"][0]["staged"].update(path=p["outputs"][1]["staged"]["path"]), "PLAN_STAGE_DERIVATION"),
        ]
        for mutate, code in mutations:
            with self.subTest(code=code):
                self._assert_derived_rejection(mutate, code)

    def test_derivation_rejects_unknown_plan_metadata_output_and_work_fields(self):
        mutations = [
            (lambda p: p.update(unrecognized=True), "PLAN_FIELDS"),
            (lambda p: p["metadata"].update(unrecognized=True), "METADATA_FIELDS"),
            (lambda p: p["outputs"][0].update(unrecognized=True), "PLAN_OUTPUT_FIELDS"),
            (lambda p: self._rewrite_candidate_libraries(p, lambda lib: lib["works"][-1].update(unrecognized=True)), "PLAN_L1_DERIVATION"),
        ]
        for mutate, code in mutations:
            with self.subTest(code=code):
                self._assert_derived_rejection(mutate, code)

    def test_derivation_rejects_instance_work_id_vault_root_and_window_tamper(self):
        def wrong_root(plan):
            path = self.root / plan["library"]["l0"]["path"]
            baseline = read_json(path)
            baseline["root_binding"] = str(self.base / "unrelated-root")
            path.write_bytes(encode(baseline))
            plan["library"]["l0"] = ref(self.root, path)
        def wrong_window(plan):
            later = (utcnow() + timedelta(hours=2)).isoformat()
            plan["deadline_utc"] = later
            plan["metadata"]["deadline_utc"] = later
        mutations = [
            (lambda p: p.update(instance_id="00000000-0000-0000-0000-000000000000"), "PLAN_INSTANCE_DERIVATION"),
            (lambda p: p.update(work_id="W9999"), "PLAN_WORK_DERIVATION"),
            (lambda p: self._rewrite_candidate_libraries(p, lambda lib: lib.update(vault_dir="Reading-other")), "PLAN_L1_DERIVATION"),
            (lambda p: self._rewrite_candidate_libraries(p, lambda lib: lib["works"][-1].update(transaction_id="00000000-0000-0000-0000-000000000000")), "PLAN_L1_DERIVATION"),
            (wrong_root, "ROOT_BINDING_MISMATCH"),
            (wrong_window, "PLAN_WINDOW"),
        ]
        for mutate, code in mutations:
            with self.subTest(code=code):
                self._assert_derived_rejection(mutate, code)


if __name__ == "__main__":
    unittest.main()
