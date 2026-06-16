"""Tests for the miniClaudeCode tool system."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from miniclaudecode.tools.base import ToolRegistry
from miniclaudecode.tools.bash_tool import BashTool
from miniclaudecode.tools.file_read import FileReadTool
from miniclaudecode.tools.file_write import FileWriteTool
from miniclaudecode.tools.file_edit import FileEditTool
from miniclaudecode.tools.glob_tool import GlobTool
from miniclaudecode.tools.grep_tool import GrepTool


class TestToolRegistry(unittest.TestCase):
    def test_default_registry_has_six_tools(self):
        registry = ToolRegistry.default()
        tools = registry.all_tools()
        self.assertEqual(len(tools), 6)
        names = {t.name for t in tools}
        self.assertEqual(names, {"bash", "read_file", "write_file", "edit_file", "glob", "grep"})

    def test_api_schemas_valid(self):
        registry = ToolRegistry.default()
        schemas = registry.api_schemas()
        self.assertEqual(len(schemas), 6)
        for schema in schemas:
            self.assertIn("name", schema)
            self.assertIn("description", schema)
            self.assertIn("input_schema", schema)

    def test_get_tool(self):
        registry = ToolRegistry.default()
        self.assertIsNotNone(registry.get("bash"))
        self.assertIsNone(registry.get("nonexistent"))


class TestBashTool(unittest.TestCase):
    def setUp(self):
        self.tool = BashTool()

    def test_execute_echo(self):
        result = self.tool.execute({"command": "echo hello"})
        self.assertFalse(result.is_error)
        self.assertIn("hello", result.output)

    def test_permission_blocks_dangerous(self):
        denial = self.tool.check_permissions({"command": "rm -rf /"})
        self.assertIsNotNone(denial)

    def test_permission_allows_safe(self):
        denial = self.tool.check_permissions({"command": "echo safe"})
        self.assertIsNone(denial)

    def test_empty_command(self):
        result = self.tool.execute({"command": ""})
        self.assertTrue(result.is_error)


class TestFileReadTool(unittest.TestCase):
    def setUp(self):
        self.tool = FileReadTool()

    def test_read_existing_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("line1\nline2\nline3\n")
            f.flush()
            result = self.tool.execute({"path": f.name})
        self.assertFalse(result.is_error)
        self.assertIn("line1", result.output)
        self.assertIn("line2", result.output)
        Path(f.name).unlink()

    def test_read_nonexistent(self):
        result = self.tool.execute({"path": "/nonexistent/file.txt"})
        self.assertTrue(result.is_error)

    def test_read_with_offset_and_limit(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("a\nb\nc\nd\ne\n")
            f.flush()
            result = self.tool.execute({"path": f.name, "offset": 2, "limit": 2})
        self.assertFalse(result.is_error)
        self.assertIn("b", result.output)
        self.assertIn("c", result.output)
        self.assertNotIn("d", result.output)
        Path(f.name).unlink()


class TestFileWriteTool(unittest.TestCase):
    def setUp(self):
        self.tool = FileWriteTool()

    def test_write_new_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.txt"
            result = self.tool.execute({"path": str(path), "content": "hello world"})
            self.assertFalse(result.is_error)
            self.assertEqual(path.read_text(), "hello world")

    def test_write_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "dir" / "test.txt"
            result = self.tool.execute({"path": str(path), "content": "nested"})
            self.assertFalse(result.is_error)
            self.assertTrue(path.exists())


class TestFileEditTool(unittest.TestCase):
    def setUp(self):
        self.tool = FileEditTool()

    def test_replace_unique_string(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world\nfoo bar\n")
            f.flush()
            result = self.tool.execute({
                "path": f.name,
                "old_string": "foo bar",
                "new_string": "baz qux",
            })
        self.assertFalse(result.is_error)
        self.assertEqual(Path(f.name).read_text(), "hello world\nbaz qux\n")
        Path(f.name).unlink()

    def test_reject_non_unique(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("aaa\naaa\n")
            f.flush()
            result = self.tool.execute({
                "path": f.name,
                "old_string": "aaa",
                "new_string": "bbb",
            })
        self.assertTrue(result.is_error)
        self.assertIn("2 times", result.output)
        Path(f.name).unlink()

    def test_reject_not_found(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello\n")
            f.flush()
            result = self.tool.execute({
                "path": f.name,
                "old_string": "xyz",
                "new_string": "abc",
            })
        self.assertTrue(result.is_error)
        Path(f.name).unlink()


class TestGlobTool(unittest.TestCase):
    def setUp(self):
        self.tool = GlobTool()

    def test_find_python_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("pass")
            (Path(tmpdir) / "b.txt").write_text("text")
            result = self.tool.execute({"pattern": "*.py", "directory": tmpdir})
        self.assertFalse(result.is_error)
        self.assertIn("a.py", result.output)
        self.assertNotIn("b.txt", result.output)


class TestGrepTool(unittest.TestCase):
    def setUp(self):
        self.tool = GrepTool()

    def test_search_in_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            f.flush()
            result = self.tool.execute({"pattern": "hello", "path": f.name})
        self.assertFalse(result.is_error)
        self.assertIn("hello", result.output)
        Path(f.name).unlink()

    def test_no_matches(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("nothing here\n")
            f.flush()
            result = self.tool.execute({"pattern": "zzzzz", "path": f.name})
        self.assertIn("No matches", result.output)
        Path(f.name).unlink()


if __name__ == "__main__":
    unittest.main()
