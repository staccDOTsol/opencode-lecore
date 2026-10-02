"""Contract tests over the real, vendored leCore engine."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("opencode_lecore_worker", Path(__file__).with_name("worker.py"))
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="opencode-lecore-test-")
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.worker = module.Worker(self.root / "state")

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self, items=(), query="Aurora registry", session="a", budget=4000, **fields):
        return self.worker.handle({"op": "index-recall", "workspace": str(self.workspace),
                                   "session": session, "items": list(items), "queries": [query],
                                   "budgetChars": budget, **fields})

    def test_exact_original_survives_restart_and_compaction(self):
        text = "ordinary irrelevant log record\n" * 180 + "\nAurora registry uses lease code amber-73.\n" + "tail filler\n" * 100
        result = self.ask([{"id": "tool-1", "text": text, "source": "read config", "kind": "tool"}])
        self.assertLess(len(result["entries"][0]["text"]), len(text))
        self.worker = module.Worker(self.root / "state")
        recalled = self.ask(query="Aurora lease code")
        self.assertTrue(any("amber-73" in item["text"] for item in recalled["evidence"]))
        exact = self.worker.handle({"op": "original", "workspace": str(self.workspace), "session": "a", "item_id": "tool-1"})
        self.assertEqual(exact["original"]["text"], text)

    def test_no_match_is_empty_on_tiny_corpus(self):
        result = self.ask([{"id": "one", "text": "Aurora registry retains the current lease.", "source": "fixture"}], query="unrelatedzx absentwordx")
        self.assertEqual(result["evidence"], [])
        self.assertTrue(result["metrics"]["no_match"])

    def test_session_and_workspace_isolation(self):
        self.ask([{"id": "secret", "text": "Aurora registry uses tenant secret amber-73.", "source": "user"}])
        self.assertEqual(self.ask(session="b")["evidence"], [])
        other = self.root / "other"
        other.mkdir()
        result = self.worker.handle({"op": "index-recall", "workspace": str(other), "session": "a", "items": [], "queries": ["Aurora registry"]})
        self.assertEqual(result["evidence"], [])

    def test_budget_and_deterministic_results(self):
        items = [{"id": str(i), "text": f"Aurora registry record {i}: " + "long concrete deployment detail " * 20, "source": f"file-{i}"} for i in range(10)]
        first = self.ask(items, budget=950)
        second = self.ask(items, budget=950)
        self.assertEqual(first["evidence"], second["evidence"])
        self.assertLessEqual(sum(len(e["header"]) + len(e["text"]) for e in first["evidence"]), 950)
        self.assertFalse(first["metrics"]["coverage_complete"])
        self.assertFalse(second["metrics"]["index_rebuilt"])
        self.assertEqual(second["metrics"]["new_items"], 0)

    def test_stale_file_evidence_is_invalidated_but_original_remains(self):
        path = self.workspace / "config.txt"
        original = "Aurora registry uses lease code amber-73."
        path.write_text(original)
        self.ask([{"id": "config", "text": original, "source": "config.txt", "kind": "file", "file_path": str(path)}])
        path.write_text("Aurora registry uses lease code violet-91.")
        result = self.ask()
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["metrics"]["stale_items"], 1)
        exact = self.worker.handle({"op": "original", "workspace": str(self.workspace), "session": "a", "item_id": "config"})
        self.assertEqual(exact["original"]["text"], original)
        self.assertTrue(exact["stale"])

    def test_same_id_revision_does_not_recall_old_version(self):
        self.ask([{"id": "file", "text": "Aurora registry lease code amber-73.", "source": "config"}])
        self.ask([{"id": "file", "text": "Aurora registry lease code violet-91.", "source": "config"}])
        result = self.ask()
        self.assertTrue(any("violet-91" in e["text"] for e in result["evidence"]))
        self.assertFalse(any("amber-73" in e["text"] for e in result["evidence"]))
        exact = self.worker.handle({"op": "original", "workspace": str(self.workspace), "session": "a", "item_id": "file", "hash": hashlib.sha256(b"Aurora registry lease code amber-73.").hexdigest()})
        self.assertIn("amber-73", exact["original"]["text"])

    def test_chunk_boundary_needle(self):
        text = "x" * 590 + " Aurora registry codeword is violet-91. " + "y" * 3000
        result = self.ask([{"id": "blob", "text": text, "source": "log"}], query="Aurora registry codeword")
        self.assertTrue(any("codeword is violet-91" in e["text"] for e in result["evidence"]))

    def test_protected_text_is_not_reinjected(self):
        result = self.ask([{"id": "recent", "text": "Aurora registry lease code amber-73.", "source": "recent user"}], compressIds=[])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["entries"], [])

    def test_rejected_batch_cannot_leak_partial_memory(self):
        with self.assertRaises(ValueError):
            self.ask([{"id": "valid", "text": "Aurora registry secret amber-73.", "source": "user"},
                      {"id": "invalid", "text": 12}])
        self.assertEqual(self.ask()["evidence"], [])
        with self.assertRaises(ValueError):
            self.ask([{"id": "valid", "text": "Aurora registry secret amber-73.", "source": "user"},
                      {"id": "outside", "text": "Forbidden scope", "file_path": str(self.root / "outside")}])
        self.assertEqual(self.ask()["evidence"], [])


if __name__ == "__main__":
    unittest.main()
