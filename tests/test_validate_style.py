import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("validate_style", Path(__file__).parents[1] / "scripts/validate_style.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ValidateStyleTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name) / "sample-style"
        self.folder.mkdir()
        self.path = self.folder / "SKILL.md"

    def write(self, fields=None, body="解释机制时，先给一个最小例子。"):
        self.path.write_text("---\n" + (fields or 'name: sample-style\ndescription: 日常协作中的个人做事风格，按条件应用已确认偏好。')
                             + "\n---\n\n" + body, encoding="utf-8")

    def test_description_and_body_are_not_fixed_to_one_structure(self):
        descriptions = ("日常协作中的个人做事风格，按条件应用已确认偏好。",
                        ">-\n  在日常协作中自动应用个人风格。\n  技术讲解偏好先给最小例子，再解释机制。")
        bodies = ("解释机制时，先给例子，再展开执行链路。",
                  "- 解释机制时先给例子。\n- 例子之后展开执行链路。",
                  "## 技术讲解\n\n先给例子。\n\n### 展开机制\n\n解释执行链路。")
        for description in descriptions:
            for body in bodies:
                with self.subTest(description=description, body=body):
                    self.write("name: sample-style\ndescription: " + description, body)
                    self.assertEqual(validator.validate_style(self.folder), [])
                    self.assertEqual(validator.validate_style(self.path), [])

    def test_invalid_frontmatter_and_fields(self):
        cases = ('name: [broken', 'name: sample-style\nname: other-style\ndescription: A task.',
                 'name: other-style\ndescription: A task.', 'name: Sample-Style\ndescription: A task.',
                 'name: sample-style\ndescription: ""', 'name: sample-style\ndescription: [task]',
                 'name: sample-style\ndescription: ' + 'x' * 1025,
                 'name: sample-style\ndescription: A task.\ncontext: fork')
        for fields in cases:
            with self.subTest(fields=fields[:80]):
                self.write(fields)
                self.assertTrue(validator.validate_style(self.folder))

    def test_implicit_invocation_defaults_and_boolean_types(self):
        self.write()
        self.assertEqual(validator.validate_style(self.folder), [])
        for value, rejected in (("true", True), ('"false"', True), ("false", False)):
            with self.subTest(value=value):
                self.write('name: sample-style\ndescription: A task.\ndisable-model-invocation: ' + value)
                self.assertEqual(bool(validator.validate_style(self.folder)), rejected)
        self.write()
        config = self.folder / "agents/openai.yaml"
        config.parent.mkdir()
        for policy, rejected in (("false", True), ('"false"', True), ("true", False)):
            with self.subTest(policy=policy):
                config.write_text("policy:\n  allow_implicit_invocation: " + policy)
                self.assertEqual(bool(validator.validate_style(self.folder)), rejected)

    def test_empty_body_is_rejected(self):
        self.write(body=" ")
        self.assertTrue(validator.validate_style(self.folder))

    def test_local_links_are_bundled_and_exist(self):
        reference = self.folder / "examples/guide.md"
        reference.parent.mkdir()
        reference.write_text("Example.")
        self.write(body="[例子](examples/guide.md)\n[参考][guide]\n[guide]: examples/guide.md\n[外部](https://example.com)\n[本页](#topic)")
        self.assertEqual(validator.validate_style(self.folder), [])
        for link in ("examples/missing.md", "../outside.md", str(reference), reference.as_uri(), "C:/private/guide.md"):
            with self.subTest(link=link):
                self.write(body=f"[例子]({link})")
                self.assertTrue(validator.validate_style(self.folder))
        reference.unlink()
        reference.symlink_to(Path(self.temporary.name) / "outside.md")
        reference.resolve().write_text("External example.")
        self.write(body="[例子](examples/guide.md)")
        self.assertTrue(validator.validate_style(self.folder))

    def test_code_examples_are_not_resource_references(self):
        self.write(body="按任务需要提供可复制的示例。\n\n````markdown\n[示意](missing.md)\n```\n[仍是示意](other.md)\n````\n\n`[语法](absent.md)`")
        self.assertEqual(validator.validate_style(self.folder), [])

    def test_cli_is_read_only_and_reports_failure(self):
        self.write()
        before = self.path.read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = validator.main([str(self.folder)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), {"status": "valid", "errors": []})
        self.assertEqual(self.path.read_bytes(), before)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = validator.main([str(self.folder / "missing.md")])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
