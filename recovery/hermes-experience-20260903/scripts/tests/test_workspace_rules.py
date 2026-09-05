import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "normalize_workspace_rules.py"
SPEC = importlib.util.spec_from_file_location("workspace_rules", SCRIPT)
RULES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RULES)


class RuleRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.agents = self.home / "workspace" / "AGENTS.md"

    def snapshot(self):
        return {str(p.relative_to(self.home)): p.read_bytes()
                for p in self.home.rglob("*") if p.is_file()}

    def restore(self, **kwargs):
        return RULES.restore_rules(self.agents, self.home, **kwargs)

    def test_fresh_restore_and_idempotence(self):
        self.assertEqual(len(self.restore()), 5)
        before = self.snapshot()
        self.assertEqual(self.restore(), [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.restore(check=True), [])

    def test_check_missing_does_not_create_files(self):
        with self.assertRaises(ValueError):
            self.restore(check=True)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_check_drift_is_read_only(self):
        self.restore()
        (self.home / "SOUL.md").write_text("User custom identity\n")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.restore(check=True)
        self.assertEqual(self.snapshot(), before)

    def test_restore_backs_up_custom_rules(self):
        self.restore()
        self.agents.write_text("User custom rules\n")
        self.restore()
        backups = list((self.home / "backups").glob("rules-before-restore-*/AGENTS.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "User custom rules\n")

    def test_private_state_is_untouched(self):
        for name in ("memories/USER.md", "memories/MEMORY.md", "sessions/sessions.json", "config.yaml"):
            target = self.home / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("private sentinel")
        private = self.snapshot()
        self.restore()
        after = self.snapshot()
        for name, content in private.items():
            self.assertEqual(after[name], content)

    def test_missing_template_fails_before_writes(self):
        before = self.snapshot()
        with patch.object(RULES, "TEMPLATES", self.home / "missing"):
            with self.assertRaises(FileNotFoundError):
                self.restore()
        self.assertEqual(self.snapshot(), before)

    def test_workspace_only_mode(self):
        self.assertEqual(RULES.restore_rules(self.agents, None), [self.agents])
        self.assertFalse((self.home / "SOUL.md").exists())


if __name__ == "__main__":
    unittest.main()
