"""Single-paper storage transactions; review authority belongs to the fixed caller.

The callback is deliberately internal Python API. No storage receipt asserts that
a real author, independent reviewer, PDF parser, or Obsidian client has passed.
"""
from __future__ import annotations

import copy
import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Callable

from .core import (cas, check_ref, digest, encode, parse_time, put, read_json,
                   ref, require, safe, sha, utcnow, valid_part, write_json_new, writer)

LIBRARY = ".system/library.json"
REQUIRED_ASSETS = {
    "source.pdf", "source.md", "translation_zh.md", "summary.md",
    "science_notes.md", "provenance.json",
}
FIGURE = re.compile(r"figures/Figure-[0-9]{2,4}\.png\Z")
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
SCHEMA = "singlepaper.library.v1"
GRAPH_SEARCH = r"path:/^(papers|domains)\/[^\/]+\.md$/"
GRAPH_PAPER_COLOR = r"path:/^papers\/[^\/]+\.md$/"
GRAPH_DOMAIN_COLOR = r"path:/^domains\/[^\/]+\.md$/"
METADATA_FIELDS = {"title", "category_id", "pdf_sha256", "page_count", "run_id",
                   "input_sha256", "deadline_utc", "instance_id", "assets"}
PLAN_FIELDS = {"schema", "derivation", "transaction_id", "instance_id", "work_id",
               "created_utc", "deadline_utc", "bundle_root", "metadata", "inputs",
               "gate_receipt", "library", "outputs"}
DERIVATION = "singlepaper.storage_derivation.v1"


def _stamp() -> str:
    return utcnow().isoformat().replace("+00:00", "Z")


def _text(value, code: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), code)
    require(not any(ord(c) < 32 or ord(c) == 127 for c in value), code)
    return value


def _md(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()<>#!|])", r"\\\1", value)


def _categories(categories: list) -> None:
    require(isinstance(categories, list) and bool(categories), "CATEGORIES_REQUIRED")
    seen = set()
    for item in categories:
        require(isinstance(item, dict) and set(item) == {"id", "label"}, "CATEGORY_SHAPE")
        require(isinstance(item["id"], str) and IDENTIFIER.fullmatch(item["id"]), "CATEGORY_ID")
        valid_part(item["id"] + ".md")
        require(item["id"].casefold() not in seen, "CATEGORY_DUPLICATE")
        seen.add(item["id"].casefold())
        _text(item["label"], "CATEGORY_LABEL")


def _library(root: Path) -> tuple[dict, bytes]:
    path = safe(root, LIBRARY)
    original = path.read_bytes()
    value = read_json(path)
    require(path.read_bytes() == original, "LIBRARY_CHANGED_DURING_READ")
    _validate_library(root, value)
    return value, original


def _validate_library(root: Path, value: dict) -> None:
    require(isinstance(value, dict) and set(value) == {"schema", "instance_id", "vault_dir", "revision",
            "storage_layout", "created_utc", "root_binding", "categories", "works", "category_confirmation", "overview"}, "LIBRARY_FIELDS")
    require(value.get("schema") == SCHEMA, "LIBRARY_SCHEMA")
    require(value.get("storage_layout") == "immutable-reading.v2", "STORAGE_LAYOUT_UNSUPPORTED")
    require(isinstance(value.get("root_binding"), str) and Path(value["root_binding"]).is_absolute()
            and Path(value["root_binding"]).resolve() == root.resolve(), "ROOT_BINDING_MISMATCH")
    require(type(value.get("revision")) is int and value["revision"] >= 0, "LIBRARY_REVISION")
    require(str(uuid.UUID(value["instance_id"])) == value["instance_id"], "INSTANCE_ID")
    require(value.get("vault_dir") == "Reading-" + value["instance_id"][:8], "VAULT_DIRECTORY")
    _categories(value.get("categories"))
    require(isinstance(value.get("works"), list), "LIBRARY_WORKS")
    ids, pdfs = set(), set()
    for item in value["works"]:
        require(re.fullmatch(r"W[0-9]{4,}", item.get("id", "")), "WORK_ID")
        require(item["id"] not in ids and item.get("pdf_sha256") not in pdfs, "WORK_DUPLICATE")
        require(item.get("status") in {"STORED_OUTPUT_VERIFIED", "COMMITTED_READING_PENDING"}, "WORK_STATUS")
        require(item.get("category_id") in {c["id"] for c in value["categories"]}, "WORK_CATEGORY")
        ids.add(item["id"])
        pdfs.add(item.get("pdf_sha256"))


def _domain(library: dict, category: dict) -> bytes:
    lines = ["---", "node: domain", f"category_id: {category['id']}", "---", "",
             "# " + _md(category["label"]), ""]
    lines += ["此分类说明在初始化时建立，之后不由生成器改写。", "",
              "所属文献链接到本分类；可在 Obsidian 的反向链接中查看关联文献。"]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _start_page() -> bytes:
    return ("# 文献阅读入口\n\n"
            "请让 AI 打开当前文献索引，或查看 indexes 文件夹中的版本索引。\n\n"
            "当前正式索引由本实例的 library.overview 精确记录。\n"
            "版本索引保留保存时的文献清单，不会在原文件上更新。\n\n"
            "[用户 Idea](user/ideas/README.md)\n").encode("utf-8")


def _overview(library: dict) -> bytes:
    lines = ["# 文献阅读入口", "", "## 分类", ""]
    lines += [f"- [{_md(c['label'])}](../domains/{c['id']}.md)" for c in library["categories"]]
    lines += ["", "## 文献", ""]
    lines += [f"- [{_md(w['title'])}](../papers/{w['id']}.md)" for w in library["works"]]
    lines += ["", "[用户 Idea](../user/ideas/README.md)", ""]
    return "\n".join(lines).encode("utf-8")


def _paper(work: dict, categories: list) -> bytes:
    category = next(c for c in categories if c["id"] == work["category_id"])
    base = f"../assets/{work['id']}/r001"
    lines = ["---", "node: paper", f"work_id: {work['id']}",
             f"category_id: {work['category_id']}", "---", "", "# " + _md(work["title"]), "",
             f"分类：[{_md(category['label'])}](../domains/{category['id']}.md)", "",
             "## 阅读材料", ""]
    for label, name in [("原 PDF", "source.pdf"), ("整理原文", "source.md"),
                        ("逐页中文译文", "translation_zh.md"), ("摘要", "summary.md"),
                        ("系统科学说明", "science_notes.md"), ("来源与处理记录", "provenance.json")]:
        lines.append(f"- [{label}]({base}/{name})")
    lines += ["", f"[用户阅读说明](../user/notes/{work['id']}.md)", "",
              "[用户 Idea](../user/ideas/README.md)", ""]
    return "\n".join(lines).encode("utf-8")


def initialize(root: Path, categories: list, confirmation: dict) -> dict:
    """Create a genuinely new root, with exact confirmed category binding."""
    root = Path(root).absolute()
    require(not root.exists(), "ROOT_MUST_BE_NEW")
    require(root.parent.exists(), "ROOT_PARENT_MISSING")
    _categories(categories)
    require(isinstance(confirmation, dict) and confirmation.get("confirmed") is True,
            "CATEGORY_CONFIRMATION_REQUIRED")
    require(confirmation.get("categories_sha256") == sha(encode(categories)), "CATEGORY_CONFIRMATION_MISMATCH")
    require(confirmation.get("scope") in {"SYNTHETIC_DEMO", "USER_CONFIRMED"}, "CATEGORY_CONFIRMATION_SCOPE")
    if confirmation["scope"] == "SYNTHETIC_DEMO":
        require(len(categories) == 1 and categories[0]["id"] == "DEMO", "DEMO_CATEGORY_ONLY")
    _text(confirmation.get("authorization"), "CATEGORY_AUTHORIZATION_REQUIRED")
    # Safe traversal also rejects an aliased/reparse parent before making a root.
    safe(root.parent, root.name, must_exist=False)
    root.mkdir()
    instance_id = str(uuid.uuid4())
    vault = "Reading-" + instance_id[:8]
    library = {"schema": SCHEMA, "instance_id": instance_id, "vault_dir": vault, "revision": 0,
               "storage_layout": "immutable-reading.v2", "created_utc": _stamp(),
               "root_binding": str(root.resolve()), "categories": copy.deepcopy(categories), "works": []}
    confirmation_path = safe(root, ".system/category-confirmation.json", must_exist=False)
    write_json_new(confirmation_path, confirmation)
    library["category_confirmation"] = ref(root, confirmation_path)
    for category in categories:
        put(safe(root, f"{vault}/domains/{category['id']}.md", must_exist=False), _domain(library, category))
    put(safe(root, f"{vault}/Library.md", must_exist=False), _start_page())
    initial_index = safe(root, f"{vault}/indexes/Library-000000.md", must_exist=False)
    put(initial_index, _overview(library))
    library["overview"] = ref(root, initial_index)
    put(safe(root, f"{vault}/user/ideas/README.md", must_exist=False),
        "# 用户 Idea\n\n此目录由用户维护，生成器不改写。\n".encode("utf-8"))
    write_json_new(safe(root, f"{vault}/.obsidian/graph.json", must_exist=False), {
        "search": GRAPH_SEARCH, "showTags": False,
        "showAttachments": False, "hideUnresolved": True,
        "colorGroups": [{"query": GRAPH_PAPER_COLOR, "color": {"a": 1, "rgb": 4751606}},
                        {"query": GRAPH_DOMAIN_COLOR, "color": {"a": 1, "rgb": 14648870}}],
    })
    write_json_new(safe(root, LIBRARY, must_exist=False), library)
    return {"schema": "singlepaper.initialized.v1", "instance_id": library["instance_id"],
            "root": str(root), "vault_dir": vault, "library": ref(root, safe(root, LIBRARY)),
            "category_scope": confirmation["scope"], "client_validation": "NOT_RUN"}


def _deadline(metadata: dict) -> None:
    deadline = parse_time(metadata["deadline_utc"])
    require(utcnow() < deadline, "DEADLINE_EXPIRED")
    require(deadline <= utcnow() + timedelta(minutes=60), "DEADLINE_EXCEEDS_60_MINUTES")


def _inventory(bundle: Path, expected: list) -> list:
    expected = _asset_manifest(expected)
    names = [item["path"] for item in expected]
    for item in expected:
        check_ref(bundle, item)
    actual = set()
    for path in bundle.rglob("*"):
        relative = path.relative_to(bundle).as_posix()
        checked = safe(bundle, relative, must_exist=False)
        if checked.is_file():
            actual.add(relative)
        else:
            require(checked.is_dir() and relative == "figures", "BUNDLE_EXTRA_DIRECTORY")
    require(actual == set(names), "BUNDLE_INVENTORY_DRIFT")
    return expected


def _asset_manifest(expected: list) -> list:
    """Validate references without reading a bundle, including during recovery."""
    require(isinstance(expected, list) and bool(expected), "ASSET_MANIFEST_REQUIRED")
    names = []
    for item in expected:
        require(isinstance(item, dict) and set(item) == {"path", "sha256", "bytes"}, "ASSET_REF_SHAPE")
        name = item["path"]
        require(isinstance(name, str) and (name in REQUIRED_ASSETS or FIGURE.fullmatch(name)), "ASSET_NOT_ALLOWED")
        require(name not in names, "ASSET_DUPLICATE")
        names.append(name)
        require(isinstance(item["sha256"], str) and HASH.fullmatch(item["sha256"]), "ASSET_HASH")
        require(type(item["bytes"]) is int and item["bytes"] >= 0, "ASSET_BYTES")
    require(REQUIRED_ASSETS <= set(names), "ASSET_REQUIRED_MISSING")
    return sorted(expected, key=lambda x: x["path"])


def _derive(root: Path, library: dict, metadata: dict, inputs: list, tx: str) -> tuple[dict, dict, list]:
    """Sole derivation of new formal state and output bytes; never trust a gate's claims."""
    _validate_library(root, library)
    require(isinstance(metadata, dict) and set(metadata) == METADATA_FIELDS, "METADATA_FIELDS")
    require(metadata["instance_id"] == library["instance_id"], "INSTANCE_MISMATCH")
    require(all(w["status"] == "STORED_OUTPUT_VERIFIED" for w in library["works"]), "PENDING_COMMIT_EXISTS")
    _text(metadata["title"], "TITLE_REQUIRED")
    _text(metadata["run_id"], "RUN_ID_REQUIRED")
    require(metadata["category_id"] in {c["id"] for c in library["categories"]}, "CATEGORY_UNKNOWN")
    require(type(metadata["page_count"]) is int and metadata["page_count"] > 0, "PAGE_COUNT")
    for field in ("pdf_sha256", "input_sha256"):
        require(isinstance(metadata[field], str) and HASH.fullmatch(metadata[field]), "METADATA_HASH")
    require(metadata["pdf_sha256"] not in {w["pdf_sha256"] for w in library["works"]}, "PDF_ALREADY_REGISTERED")
    require(str(uuid.UUID(tx)) == tx, "TRANSACTION_ID")
    require(inputs == _asset_manifest(metadata["assets"]), "INPUT_MANIFEST_DERIVATION")
    require(next(a["sha256"] for a in inputs if a["path"] == "source.pdf") == metadata["pdf_sha256"], "PDF_HASH_MISMATCH")
    parse_time(metadata["deadline_utc"])
    vault = library["vault_dir"]
    work_id = f"W{max([int(w['id'][1:]) for w in library['works']] + [0]) + 1:04d}"
    prefix = f"{vault}/assets/{work_id}/r001"
    work = {"id": work_id, "title": metadata["title"], "category_id": metadata["category_id"],
            "pdf_sha256": metadata["pdf_sha256"], "page_count": metadata["page_count"],
            "run_id": metadata["run_id"], "input_sha256": metadata["input_sha256"],
            "content_revision": 1, "status": "COMMITTED_READING_PENDING", "transaction_id": tx,
            "assets": [{**a, "path": f"{prefix}/{a['path']}"} for a in inputs],
            "reading": {"paper": f"{vault}/papers/{work_id}.md", "category": f"{vault}/domains/{metadata['category_id']}.md",
                        "notes": f"{vault}/user/notes/{work_id}.md", "ideas": f"{vault}/user/ideas/README.md"}}
    committed = copy.deepcopy(library)
    committed["revision"] += 1
    committed["works"].append(work)
    complete = copy.deepcopy(committed)
    complete["revision"] += 1
    complete["works"][-1]["status"] = "STORED_OUTPUT_VERIFIED"
    overview_path = f"{vault}/indexes/Library-{complete['revision']:06d}.md"
    overview_bytes = _overview(complete)
    overview_ref = {"path": overview_path, "sha256": sha(overview_bytes), "bytes": len(overview_bytes)}
    committed["overview"] = overview_ref
    complete["overview"] = overview_ref
    outputs = [{"target": f"{prefix}/{a['path']}", "policy": "IMMUTABLE", "sha256": a["sha256"],
                "bytes": a["bytes"], "input": a, "content": None} for a in inputs]
    for target, policy, data in [
        (work["reading"]["paper"], "IMMUTABLE", _paper(work, library["categories"])),
        (overview_path, "IMMUTABLE", overview_bytes),
        (work["reading"]["notes"], "USER_CREATE", f"# 用户阅读说明：{_md(work['title'])}\n\n".encode("utf-8")),
    ]:
        outputs.append({"target": target, "policy": policy, "sha256": sha(data), "bytes": len(data),
                        "input": None, "content": data})
    return committed, complete, outputs


def _gate(callback: Callable[[], dict]) -> dict:
    require(callable(callback), "REVIEW_GATE_REQUIRED")
    result = callback()
    require(isinstance(result, dict) and bool(result), "REVIEW_GATE_RECEIPT_REQUIRED")
    # Encoding validates serializability; caller owns the report's authority.
    encode(result)
    return copy.deepcopy(result)


def _event(root: Path, plan: dict, kind: str, **data) -> dict:
    value = {"schema": "singlepaper.storage_event.v1", "event": kind,
             "transaction_id": plan["transaction_id"], "at_utc": _stamp(), **data}
    path = safe(root, f".transactions/{plan['transaction_id']}/events/{uuid.uuid4()}.json", must_exist=False)
    write_json_new(path, value)
    return ref(root, path)


def prepare(root: Path, bundle_dir: Path, metadata: dict, gate: Callable[[], dict]) -> dict:
    """Freeze all bytes and preimages; does not change the formal library."""
    root, bundle = Path(root).absolute(), Path(bundle_dir).absolute()
    with writer(root):
        library, old_bytes = _library(root)
        require(isinstance(metadata, dict) and set(metadata) == METADATA_FIELDS, "METADATA_FIELDS")
        assets = _asset_manifest(metadata["assets"])
        tx = str(uuid.uuid4())
        committed, complete, expected_outputs = _derive(root, library, metadata, assets, tx)
        _deadline(metadata)
        # Existing generated pages must still be the exact current projection.
        verify(root)
        _inventory(bundle, assets)
        gate_result = _gate(gate)
        base = f".transactions/{tx}"
        work_id = complete["works"][-1]["id"]
        outputs = []

        def stage(target: str, content: bytes, policy: str) -> None:
            destination = safe(root, target, must_exist=False)
            if destination.exists():
                require(policy == "USER_CREATE", "OUTPUT_ALREADY_EXISTS")
                require(destination.is_file(), "USER_NOTE_TYPE")
            staged = safe(root, f"{base}/stage/{target}", must_exist=False)
            put(staged, content)
            outputs.append({"target": target, "staged": ref(root, staged), "before": None, "policy": policy})

        for expected in expected_outputs:
            data = check_ref(bundle, expected["input"]) if expected["input"] else expected["content"]
            stage(expected["target"], data, expected["policy"])
        snapshots = {}
        for name, data in (("l0", old_bytes), ("l1", encode(committed)), ("l2", encode(complete))):
            path = safe(root, f"{base}/{name}.json", must_exist=False)
            put(path, data)
            snapshots[name] = ref(root, path)
        plan = {"schema": "singlepaper.storage_plan.v2", "derivation": DERIVATION, "transaction_id": tx,
                "instance_id": library["instance_id"], "work_id": work_id,
                "created_utc": _stamp(), "deadline_utc": metadata["deadline_utc"],
                "bundle_root": str(bundle), "metadata": copy.deepcopy(metadata),
                "inputs": assets, "gate_receipt": gate_result, "library": snapshots, "outputs": outputs}
        _inventory(bundle, assets)
        require(_library(root)[1] == old_bytes, "LIBRARY_DRIFT")
        _deadline(metadata)
        path = safe(root, f"{base}/plan.json", must_exist=False)
        write_json_new(path, plan)
        plan_ref = ref(root, path)
        _event(root, plan, "PREPARED", plan_ref=plan_ref)
        return plan_ref


def _load_plan(root: Path, plan_ref: dict) -> dict:
    check_ref(root, plan_ref)
    plan = read_json(safe(root, plan_ref["path"]))
    require(isinstance(plan, dict) and set(plan) == PLAN_FIELDS, "PLAN_FIELDS")
    require(plan.get("schema") == "singlepaper.storage_plan.v2" and plan["derivation"] == DERIVATION, "PLAN_SCHEMA")
    tx = plan["transaction_id"]
    require(str(uuid.UUID(tx)) == tx, "TRANSACTION_ID")
    require(plan_ref["path"] == f".transactions/{tx}/plan.json", "PLAN_LOCATION")
    require(isinstance(plan["library"], dict) and set(plan["library"]) == {"l0", "l1", "l2"}, "PLAN_LIBRARY_FIELDS")
    for name, value in plan["library"].items():
        require(value["path"] == f".transactions/{tx}/{name}.json", "SNAPSHOT_LOCATION")
        check_ref(root, value)
    baseline = read_json(safe(root, plan["library"]["l0"]["path"]))
    committed, complete, expected_outputs = _derive(root, baseline, plan["metadata"], plan["inputs"], tx)
    require(plan["instance_id"] == baseline["instance_id"], "PLAN_INSTANCE_DERIVATION")
    require(plan["work_id"] == complete["works"][-1]["id"], "PLAN_WORK_DERIVATION")
    require(plan["metadata"]["deadline_utc"] == plan["deadline_utc"], "PLAN_DEADLINE_DRIFT")
    created, deadline = parse_time(plan["created_utc"]), parse_time(plan["deadline_utc"])
    require(parse_time(baseline["created_utc"]) <= created <= utcnow(), "PLAN_CREATED_TIME")
    require(timedelta(0) < deadline - created <= timedelta(minutes=60), "PLAN_WINDOW")
    require(isinstance(plan["bundle_root"], str) and Path(plan["bundle_root"]).is_absolute(), "BUNDLE_ROOT_ABSOLUTE")
    require(isinstance(plan["gate_receipt"], dict) and bool(plan["gate_receipt"]), "REVIEW_GATE_RECEIPT_REQUIRED")
    require(check_ref(root, plan["library"]["l1"]) == encode(committed), "PLAN_L1_DERIVATION")
    require(check_ref(root, plan["library"]["l2"]) == encode(complete), "PLAN_L2_DERIVATION")
    require(isinstance(plan["outputs"], list) and len(plan["outputs"]) == len(expected_outputs), "PLAN_OUTPUT_COUNT")
    for output, expected in zip(plan["outputs"], expected_outputs):
        require(isinstance(output, dict) and set(output) == {"target", "staged", "before", "policy"}, "PLAN_OUTPUT_FIELDS")
        require(output["target"] == expected["target"] and output["policy"] == expected["policy"]
                and output["before"] is None, "PLAN_OUTPUT_DERIVATION")
        expected_ref = {"path": f".transactions/{tx}/stage/{expected['target']}",
                        "sha256": expected["sha256"], "bytes": expected["bytes"]}
        require(output["staged"] == expected_ref, "PLAN_STAGE_DERIVATION")
        data = check_ref(root, output["staged"])
        if expected["content"] is not None:
            require(data == expected["content"], "PLAN_STAGE_BYTES")
        safe(root, output["target"], must_exist=False)
    return plan


def _preimages(root: Path, plan: dict, *, committed: bool) -> None:
    for output in plan["outputs"]:
        path = safe(root, output["target"], must_exist=False)
        if output["policy"] == "USER_CREATE":
            require(not path.exists() or path.is_file(), "USER_NOTE_TYPE")
            continue
        actual = path.read_bytes() if path.exists() else None
        before = check_ref(root, output["before"]) if output["before"] else None
        desired = check_ref(root, output["staged"])
        require(actual == before or (committed and actual == desired), "GENERATED_PAGE_DRIFT")


def _intent(root: Path, plan: dict, plan_ref: dict) -> dict:
    path = safe(root, f".transactions/{plan['transaction_id']}/intent.json")
    value = read_json(path)
    require(value.get("schema") == "singlepaper.storage_intent.v1" and value.get("plan") == plan_ref,
            "INTENT_MISMATCH")
    require(value.get("library") == plan["library"], "INTENT_LIBRARY_MISMATCH")
    return value


def _apply_outputs(root: Path, plan: dict) -> None:
    for output in plan["outputs"]:
        path = safe(root, output["target"], must_exist=False)
        desired = check_ref(root, output["staged"])
        if output["policy"] == "USER_CREATE":
            if path.exists():
                require(path.is_file(), "USER_NOTE_TYPE")
                continue
            try:
                put(path, desired)
            except (FileExistsError, ValueError):
                # An external user may create notes concurrently. Never replace.
                checked = safe(root, output["target"])
                require(checked.is_file(), "USER_NOTE_TYPE")
            continue
        actual = path.read_bytes() if path.exists() else None
        if actual == desired:
            continue
        require(actual is None, "GENERATED_PAGE_DRIFT")
        # Windows no-replace rename in put protects even the gap after this read.
        # No Obsidian-visible file is ever sent to cas/os.replace.
        put(path, desired)


def _verify_outputs(root: Path, plan: dict) -> None:
    for output in plan["outputs"]:
        path = safe(root, output["target"])
        require(path.is_file(), "OUTPUT_NOT_FILE")
        if output["policy"] != "USER_CREATE":
            require(digest(path) == output["staged"]["sha256"] and path.stat().st_size == output["staged"]["bytes"],
                    "OUTPUT_HASH_MISMATCH")


def _finish(root: Path, plan: dict, plan_ref: dict) -> dict:
    _intent(root, plan, plan_ref)
    complete = read_json(safe(root, plan["library"]["l2"]["path"]))
    _verify_fixed_pages(root, complete)
    _preimages(root, plan, committed=True)
    _apply_outputs(root, plan)
    _verify_outputs(root, plan)
    _load_plan(root, plan_ref)
    _verify_reading(root, complete)
    live = safe(root, LIBRARY).read_bytes()
    l1, l2 = (check_ref(root, plan["library"][k]) for k in ("l1", "l2"))
    require(live in (l1, l2), "LIBRARY_DRIFT")
    if live == l1:
        cas(safe(root, LIBRARY), l1, l2)
    # A registered library is not itself evidence that all outputs still exist.
    _verify_outputs(root, plan)
    _verify_reading(root, complete)
    require(safe(root, LIBRARY).read_bytes() == l2, "LIBRARY_DRIFT")
    receipt_path = safe(root, f".transactions/{plan['transaction_id']}/receipt.json", must_exist=False)
    receipt = _receipt_value(plan, plan_ref)
    write_json_new(receipt_path, receipt)
    return receipt


def _receipt_value(plan: dict, plan_ref: dict) -> dict:
    return {"schema": "singlepaper.storage_receipt.v1", "status": "STORED_OUTPUT_VERIFIED",
            "transaction_id": plan["transaction_id"], "work_id": plan["work_id"], "plan": plan_ref,
            "library": plan["library"]["l2"], "client_validation": "NOT_RUN",
            "authority": "STORAGE_MECHANISM_ONLY"}


def _superseded(root: Path, plan: dict, plan_ref: dict, library: dict) -> dict | None:
    complete = read_json(safe(root, plan["library"]["l2"]["path"]))
    expected = next(w for w in complete["works"] if w["id"] == plan["work_id"])
    if library["revision"] > complete["revision"] and expected in library["works"]:
        _intent(root, plan, plan_ref)
        verify(root)
        return {"schema": "singlepaper.storage_receipt.v1", "status": "SUPERSEDED",
                "transaction_id": plan["transaction_id"], "work_id": plan["work_id"], "plan": plan_ref,
                "current_library": ref(root, safe(root, LIBRARY)), "client_validation": "NOT_RUN",
                "authority": "STORAGE_MECHANISM_ONLY", "no_writes": True}
    return None


def publish(root: Path, plan_ref: dict, gate: Callable[[], dict]) -> dict:
    root = Path(root).absolute()
    with writer(root):
        plan = _load_plan(root, plan_ref)
        try:
            library, live = _library(root)
            require(library["instance_id"] == plan["instance_id"], "INSTANCE_MISMATCH")
            l0, l1, l2 = (check_ref(root, plan["library"][k]) for k in ("l0", "l1", "l2"))
            if live in (l1, l2):
                return _finish(root, plan, plan_ref)
            superseded = _superseded(root, plan, plan_ref, library)
            if superseded:
                return superseded
            require(live == l0, "LIBRARY_DRIFT")
            verify(root)
            _deadline(plan["metadata"])
            _inventory(Path(plan["bundle_root"]), plan["inputs"])
            require(encode(_gate(gate)) == encode(plan["gate_receipt"]), "REVIEW_GATE_DRIFT")
            _preimages(root, plan, committed=False)
            # Re-read stage and all inputs after the caller's gate before intent.
            _load_plan(root, plan_ref)
            _inventory(Path(plan["bundle_root"]), plan["inputs"])
            require(safe(root, LIBRARY).read_bytes() == l0, "LIBRARY_DRIFT")
            _deadline(plan["metadata"])
            _event(root, plan, "PREVALIDATED", plan_ref=plan_ref)
            intent = {"schema": "singlepaper.storage_intent.v1", "plan": plan_ref,
                      "library": plan["library"], "gate_sha256": sha(encode(plan["gate_receipt"]))}
            write_json_new(safe(root, f".transactions/{plan['transaction_id']}/intent.json", must_exist=False), intent)
            _load_plan(root, plan_ref)
            _inventory(Path(plan["bundle_root"]), plan["inputs"])
            _preimages(root, plan, committed=False)
            verify(root)
            _deadline(plan["metadata"])
            cas(safe(root, LIBRARY), l0, l1)
            _event(root, plan, "LIBRARY_COMMITTED", library=plan["library"]["l1"])
            return _finish(root, plan, plan_ref)
        except Exception as exc:
            _event(root, plan, "STOPPED", error_type=type(exc).__name__, reason=str(exc))
            raise


def recover(root: Path, plan_ref: dict) -> dict:
    """Only finish a proven committed transaction; never create a new commit."""
    root = Path(root).absolute()
    with writer(root):
        plan = _load_plan(root, plan_ref)
        try:
            library, live = _library(root)
            require(library["instance_id"] == plan["instance_id"], "INSTANCE_MISMATCH")
            l1, l2 = (check_ref(root, plan["library"][k]) for k in ("l1", "l2"))
            if live in (l1, l2):
                return _finish(root, plan, plan_ref)
            superseded = _superseded(root, plan, plan_ref, library)
            if superseded:
                return superseded
            if live == check_ref(root, plan["library"]["l0"]):
                _deadline(plan["metadata"])
                raise ValueError("NOT_COMMITTED_NO_RECOVERY")
            raise ValueError("LIBRARY_DRIFT")
        except Exception as exc:
            _event(root, plan, "RECOVERY_STOPPED", error_type=type(exc).__name__, reason=str(exc))
            raise


def verify(root: Path) -> dict:
    """Read-only storage/integrity verification; does not rerun scientific review."""
    root = Path(root).absolute()
    library, original = _library(root)
    require(library["category_confirmation"]["path"] == ".system/category-confirmation.json", "CATEGORY_CONFIRMATION_LOCATION")
    check_ref(root, library["category_confirmation"])
    confirmation = read_json(safe(root, ".system/category-confirmation.json"))
    require(confirmation.get("confirmed") is True and confirmation.get("categories_sha256") == sha(encode(library["categories"])),
            "CATEGORY_CONFIRMATION_MISMATCH")
    require(all(w["status"] == "STORED_OUTPUT_VERIFIED" for w in library["works"]), "READING_OUTPUT_PENDING")
    count = 0
    for work in library["works"]:
        for asset in work["assets"]:
            check_ref(root, asset)
            count += 1
        require(safe(root, work["reading"]["paper"]).read_bytes() == _paper(work, library["categories"]), "GENERATED_PAGE_DRIFT")
        require(safe(root, work["reading"]["notes"]).is_file(), "USER_NOTE_MISSING")
        tx = work["transaction_id"]
        intent = read_json(safe(root, f".transactions/{tx}/intent.json"))
        plan = _load_plan(root, intent["plan"])
        _intent(root, plan, intent["plan"])
        complete = read_json(safe(root, plan["library"]["l2"]["path"]))
        require(work in complete["works"], "WORK_PLAN_MISMATCH")
        receipt = read_json(safe(root, f".transactions/{tx}/receipt.json"))
        require(receipt == _receipt_value(plan, intent["plan"]), "RECEIPT_MISMATCH")
    if library["works"]:
        require(original == check_ref(root, plan["library"]["l2"]), "LIBRARY_DRIFT")
    else:
        require(library["revision"] == 0, "LIBRARY_DRIFT")
    _verify_reading(root, library)
    require(safe(root, LIBRARY).read_bytes() == original, "LIBRARY_CHANGED_DURING_VERIFY")
    return {"schema": "singlepaper.storage_verification.v1", "status": "VERIFIED",
            "instance_id": library["instance_id"], "revision": library["revision"],
            "works": len(library["works"]), "assets_checked": count,
            "library_sha256": sha(original), "client_validation": "NOT_RUN",
            "authority": "STORAGE_MECHANISM_ONLY"}


def _verify_reading(root: Path, library: dict) -> None:
    """Read-only checks; never repair or merge externally edited reading files."""
    _verify_fixed_pages(root, library)
    vault = library["vault_dir"]
    expected_index = f"{vault}/indexes/Library-{library['revision']:06d}.md"
    require(library["overview"]["path"] == expected_index, "OVERVIEW_PATH")
    require(check_ref(root, library["overview"]) == _overview(library), "GENERATED_PAGE_DRIFT")
    for work in library["works"]:
        for asset in work["assets"]:
            check_ref(root, asset)
        require(safe(root, work["reading"]["paper"]).read_bytes() == _paper(work, library["categories"]), "GENERATED_PAGE_DRIFT")
        require(safe(root, work["reading"]["notes"]).is_file(), "USER_NOTE_MISSING")


def _verify_fixed_pages(root: Path, library: dict) -> None:
    vault = library["vault_dir"]
    for category in library["categories"]:
        require(safe(root, f"{vault}/domains/{category['id']}.md").read_bytes() == _domain(library, category), "GENERATED_PAGE_DRIFT")
    require(safe(root, f"{vault}/Library.md").read_bytes() == _start_page(), "GENERATED_PAGE_DRIFT")
    require(safe(root, f"{vault}/user/ideas/README.md").is_file(), "USER_IDEA_INDEX_MISSING")
