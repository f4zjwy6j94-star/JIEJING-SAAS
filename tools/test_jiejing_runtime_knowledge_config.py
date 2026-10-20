"""Synthetic-only knowledge configuration regression; no HTTP service is started."""
from __future__ import annotations

import argparse
import ast
import json
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SUBJECT_PACKAGE = "_jiejing_runtime_knowledge_config_subject"
subject_package = types.ModuleType(SUBJECT_PACKAGE)
subject_package.__path__ = [str(ROOT / "jiejing_runtime")]
sys.modules[SUBJECT_PACKAGE] = subject_package
# Load the real source and relative models without broad package initialization.
knowledge = importlib.import_module(f"{SUBJECT_PACKAGE}.knowledge")


def synthetic_pack(item_id: str) -> dict:
    return {
        "version": "synthetic-selected-path-v1",
        "generated_at": "2026-10-18T00:00:00+00:00",
        "items": [{
            "item_id": item_id,
            "title": "Synthetic local regression note",
            "role": "all",
            "task_types": ["market.report"],
            "tags": ["synthetic"],
            "source_ref": f"fixture://{item_id}",
            "content": "Use supplied facts; leave unknown facts unconfirmed.",
            "source_type": "synthetic_test_fixture",
            "priority": 50,
        }],
        "redaction_report": {},
    }


def run_cli_serve(arguments: list[str], events: list[str]) -> int:
    """Real CLI function bodies; only server-start boundary is a fake."""
    source_path = ROOT / "tools" / "jiejing_saas_backend_cli.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    functions = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
                                and node.name in {"parse_args", "main"}], type_ignores=[])

    class NoSocketServer:
        def __init__(self, **kwargs):
            events.append("server_constructed")

        def serve_forever(self):
            events.append("serve_boundary_reached")

    namespace = {"argparse": argparse, "json": json, "os": os, "sys": sys,
                 "Path": Path, "ROOT": ROOT, "SaaSBackendServer": NoSocketServer}
    exec(compile(functions, str(source_path), "exec"), namespace)
    # Alias the already loaded real subject only; never import product initializer.
    package = types.ModuleType("jiejing_runtime")
    package.knowledge = knowledge
    with patch.dict(sys.modules, {"jiejing_runtime": package, "jiejing_runtime.knowledge": knowledge}), patch.object(
        sys, "argv", [str(source_path), *arguments],
    ):
        return namespace["main"]()


class KnowledgePathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="jiejing-knowledge-config-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fallback = self.write_pack("fallback.json", "fallback-fixture")
        self.selected = self.write_pack("selected.json", "selected-fixture")
        self.prior_default = knowledge.DEFAULT_KNOWLEDGE_PACK
        self.setting = "JIEJING_RUNTIME_KNOWLEDGE_PACK"
        self.prior_setting = os.environ.get(self.setting)
        self.addCleanup(self.restore_configuration)
        knowledge.DEFAULT_KNOWLEDGE_PACK = self.fallback
        os.environ.pop(self.setting, None)

    def restore_configuration(self) -> None:
        knowledge.DEFAULT_KNOWLEDGE_PACK = self.prior_default
        if self.prior_setting is None:
            os.environ.pop(self.setting, None)
        else:
            os.environ[self.setting] = self.prior_setting

    def write_pack(self, name: str, item_id: str) -> Path:
        path = self.root / name
        path.write_text(json.dumps(synthetic_pack(item_id)), encoding="utf-8")
        return path

    def retrieved_ids(self) -> list[str]:
        return [item.item_id for item in knowledge.load_default_knowledge_base().query(
            role="market-manager", task_type="market.report", limit=1,
        )]

    def test_explicit_selected_pack_is_retrieved_instead_of_fallback(self) -> None:
        os.environ[self.setting] = str(self.selected)
        self.assertEqual(self.retrieved_ids(), ["selected-fixture"])

    def test_explicit_blank_is_rejected_instead_of_empty_or_fallback(self) -> None:
        os.environ[self.setting] = "   "
        with self.assertRaisesRegex(ValueError, "non-blank"):
            self.retrieved_ids()

    def test_explicit_relative_path_is_rejected(self) -> None:
        os.environ[self.setting] = self.selected.name
        with self.assertRaisesRegex(ValueError, "absolute local"):
            self.retrieved_ids()

    def test_explicit_unc_is_rejected_without_filesystem_access(self) -> None:
        os.environ[self.setting] = r"\\synthetic.invalid\fixture\pack.json"
        # The filesystem boundary is fake for this unsafe syntax only: no UNC I/O.
        with patch.object(Path, "exists", return_value=False) as exists, patch.object(
            Path, "read_text", side_effect=AssertionError("UNC read forbidden"),
        ) as read:
            with self.assertRaisesRegex(ValueError, "absolute local"):
                self.retrieved_ids()
            exists.assert_not_called()
            read.assert_not_called()

    def test_explicit_missing_path_fails_instead_of_becoming_empty(self) -> None:
        os.environ[self.setting] = str(self.root / "not-created.json")
        with self.assertRaises(FileNotFoundError):
            self.retrieved_ids()

    def test_explicit_directory_fails_instead_of_empty_or_fallback(self) -> None:
        os.environ[self.setting] = str(self.root)
        with self.assertRaises(OSError):
            self.retrieved_ids()

    def test_explicit_bad_json_fails_instead_of_empty_or_fallback(self) -> None:
        self.selected.write_text("{not-json", encoding="utf-8")
        os.environ[self.setting] = str(self.selected)
        with self.assertRaises(json.JSONDecodeError):
            self.retrieved_ids()

    def test_explicit_wrong_pack_schema_is_rejected(self) -> None:
        self.selected.write_text(json.dumps({"unrelated": "not a knowledge pack"}), encoding="utf-8")
        os.environ[self.setting] = str(self.selected)
        with self.assertRaisesRegex(ValueError, "knowledge pack schema"):
            self.retrieved_ids()

    def test_explicit_invalid_items_are_not_silently_dropped_or_coerced(self) -> None:
        pack = synthetic_pack("selected-fixture")
        pack["items"] = [{}]
        self.selected.write_text(json.dumps(pack), encoding="utf-8")
        os.environ[self.setting] = str(self.selected)
        with self.assertRaisesRegex(ValueError, "knowledge item schema"):
            self.retrieved_ids()

    def test_unset_configuration_keeps_default_retrieval(self) -> None:
        self.assertEqual(self.retrieved_ids(), ["fallback-fixture"])

    def test_unset_configuration_keeps_missing_default_empty(self) -> None:
        knowledge.DEFAULT_KNOWLEDGE_PACK = self.root / "missing-default.json"
        self.assertEqual(self.retrieved_ids(), [])

    def test_explicit_disappearing_file_never_becomes_empty_or_fallback(self) -> None:
        os.environ[self.setting] = str(self.selected)
        original_read = Path.read_text

        def disappearing_read(path: Path, *args, **kwargs):
            if path == self.selected:
                raise FileNotFoundError("Synthetic disappearance at the read boundary")
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "exists", side_effect=AssertionError("Explicit read must not preflight")), patch.object(
            Path, "read_text", disappearing_read,
        ):
            with self.assertRaises(FileNotFoundError):
                self.retrieved_ids()

    def test_explicit_argument_wins_over_environment_and_default(self) -> None:
        os.environ[self.setting] = str(self.write_pack("environment.json", "environment-fixture"))
        actual = knowledge.load_default_knowledge_base(str(self.selected)).query(
            role="market-manager", task_type="market.report", limit=1,
        )
        self.assertEqual([item.item_id for item in actual], ["selected-fixture"])

    def test_invalid_argument_does_not_fall_back_to_valid_environment(self) -> None:
        os.environ[self.setting] = str(self.selected)
        with self.assertRaisesRegex(ValueError, "non-blank"):
            knowledge.load_default_knowledge_base("")

    def test_explicit_read_permission_failure_does_not_fall_back(self) -> None:
        os.environ[self.setting] = str(self.selected)
        original_read = Path.read_text

        def denied_read(path: Path, *args, **kwargs):
            if path == self.selected:
                raise PermissionError("Synthetic denied read")
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", denied_read):
            with self.assertRaises(PermissionError):
                self.retrieved_ids()

    def test_module_import_does_not_read_a_knowledge_pack(self) -> None:
        os.environ[self.setting] = str(self.selected)
        name = f"{SUBJECT_PACKAGE}.import_only_probe"
        spec = importlib.util.spec_from_file_location(name, ROOT / "jiejing_runtime" / "knowledge.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            with patch.object(Path, "read_text", side_effect=AssertionError("Import must not load a pack")), patch.object(
                Path, "exists", side_effect=AssertionError("Import must not probe a pack"),
            ):
                spec.loader.exec_module(module)
            self.assertTrue(callable(module.load_default_knowledge_base))
        finally:
            sys.modules.pop(name, None)

    def test_cli_environment_only_invalid_fails_before_server_construction(self) -> None:
        os.environ[self.setting] = str(self.root / "missing-environment.json")
        events = []
        with self.assertRaises(FileNotFoundError):
            run_cli_serve(["serve"], events)
        self.assertEqual(events, [])

    def test_cli_argument_overrides_invalid_environment_before_server(self) -> None:
        os.environ[self.setting] = str(self.root / "missing-environment.json")
        events = []
        self.assertEqual(run_cli_serve(["serve", "--runtime-knowledge-pack", str(self.selected)], events), 0)
        self.assertEqual(events, ["server_constructed", "serve_boundary_reached"])
        self.assertEqual(self.retrieved_ids(), ["selected-fixture"])

    def test_cli_unconfigured_startup_does_not_load_default_pack(self) -> None:
        original_read = Path.read_text
        cli_path = ROOT / "tools" / "jiejing_saas_backend_cli.py"

        def cli_source_only(path: Path, *args, **kwargs):
            if path == cli_path:
                return original_read(path, *args, **kwargs)
            raise AssertionError("Unconfigured CLI must not read a pack")

        events = []
        with patch.object(Path, "read_text", cli_source_only), patch.object(
            Path, "exists", side_effect=AssertionError("Unconfigured CLI must not probe a pack"),
        ):
            self.assertEqual(run_cli_serve(["serve"], events), 0)
        self.assertEqual(events, ["server_constructed", "serve_boundary_reached"])
        self.assertNotIn(self.setting, os.environ)

    def test_cli_invalid_argument_cannot_use_valid_env_or_start_server(self) -> None:
        os.environ[self.setting] = str(self.selected)
        events = []
        with self.assertRaisesRegex(ValueError, "non-blank"):
            run_cli_serve(["serve", "--runtime-knowledge-pack", ""], events)
        self.assertEqual(events, [])
        self.assertEqual(os.environ[self.setting], str(self.selected))

    def test_cli_environment_only_valid_is_preserved(self) -> None:
        os.environ[self.setting] = str(self.selected)
        events = []
        self.assertEqual(run_cli_serve(["serve"], events), 0)
        self.assertEqual(events, ["server_constructed", "serve_boundary_reached"])
        self.assertEqual(os.environ[self.setting], str(self.selected))
        self.assertEqual(self.retrieved_ids(), ["selected-fixture"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
