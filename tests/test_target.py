import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("style_target", Path(__file__).parents[1] / "scripts/target.py")
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


class TargetTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.record = self.root / "state/target.json"
        binding = patch.object(target, "RECORD", self.record)
        binding.start()
        self.addCleanup(binding.stop)
        self.first = self.make_skill("one-style")
        self.second = self.make_skill("two-style")

    def make_skill(self, name):
        path = self.root / name / "SKILL.md"
        path.parent.mkdir()
        path.write_text(f'---\nname: "{name}"\ndescription: Personal style.\n---\n', encoding="utf-8")
        return {"name": name, "path": str(path.resolve())}

    def call(self, command, binding=None, expected=None):
        arguments = [command]
        for prefix, values in (("", binding), ("expected-", expected)):
            if values is not None:
                for key, value in values.items():
                    arguments.extend([f"--{prefix}{key}", value])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = target.main(arguments)
        return code, json.loads(output.getvalue())

    def test_read_create_update_and_stale_update(self):
        self.assertEqual(self.call("read")[1]["status"], "unbound")
        self.assertFalse(self.record.parent.exists())
        self.assertEqual(self.call("create", self.first)[0], 0)
        self.assertEqual(self.call("read")[1]["target"], self.first)
        self.assertEqual(self.call("create", self.second)[0], 1)
        self.assertEqual(self.call("update", self.second, self.first)[0], 0)
        self.assertEqual(self.call("update", self.first, self.first)[0], 1)
        self.assertEqual(self.call("read")[1]["target"], self.second)

    def test_bad_record_is_not_treated_as_missing(self):
        self.record.parent.mkdir()
        for invalid in ('{', '{}', '{"name":"one-style","name":"two-style","path":"/a/SKILL.md"}'):
            with self.subTest(invalid=invalid):
                self.record.write_text(invalid, encoding="utf-8")
                self.assertEqual(self.call("read")[0], 1)
                self.assertEqual(self.call("create", self.first)[0], 1)
                self.assertEqual(self.record.read_text(), invalid)

    def test_invalid_target_and_relative_path_do_not_write(self):
        for invalid in (dict(self.first, name="other-style"), dict(self.first, path="one-style/SKILL.md"),
                        dict(self.first, path=str(self.root / "missing/SKILL.md"))):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.call("create", invalid)[0], 1)
                self.assertFalse(self.record.exists())

    def test_missing_target_can_be_rebound_after_read(self):
        self.assertEqual(self.call("create", self.first)[0], 0)
        Path(self.first["path"]).unlink()
        code, result = self.call("read")
        self.assertEqual(code, 1)
        self.assertEqual(result["target"], self.first)
        self.assertEqual(self.call("update", self.second, result["target"])[0], 0)

    def test_busy_lock_and_failed_replace_preserve_binding(self):
        self.assertEqual(self.call("create", self.first)[0], 0)
        lock = self.record.with_name("target.lock")
        lock.touch()
        self.assertEqual(self.call("update", self.second, self.first)[0], 1)
        self.assertTrue(lock.exists())
        lock.unlink()
        with patch.object(target.os, "replace", side_effect=OSError("write interrupted")):
            self.assertEqual(self.call("update", self.second, self.first)[0], 1)
        self.assertEqual(json.loads(self.record.read_text()), self.first)
        self.assertEqual(list(self.record.parent.iterdir()), [self.record])


if __name__ == "__main__":
    unittest.main()
