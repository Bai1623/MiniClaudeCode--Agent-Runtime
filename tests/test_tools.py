"""Tests for the miniClaudeCode tool system."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from miniclaudecode.config import Config
from miniclaudecode.runtime.tool_loader import discover_tool_specs, discover_tools
from miniclaudecode.tools.base import ToolRegistry
from miniclaudecode.tools.bash_tool import BashTool
from miniclaudecode.tools.file_edit import FileEditTool
from miniclaudecode.tools.file_read import FileReadTool
from miniclaudecode.tools.file_write import FileWriteTool
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

    def test_duplicate_tool_name_rejected(self):
        registry = ToolRegistry()
        registry.register(BashTool())
        with self.assertRaisesRegex(ValueError, "Duplicate tool name: bash"):
            registry.register(BashTool())

    def test_discovery_loads_builtin_tools(self):
        tools = discover_tools()
        names = {tool.name for tool in tools}
        self.assertEqual(names, {"bash", "read_file", "write_file", "edit_file", "glob", "grep"})

    def test_discovery_exposes_tool_manifests(self):
        specs = discover_tool_specs()
        manifests = {spec.manifest.name: spec.manifest for spec in specs}

        self.assertEqual(set(manifests), {"bash", "read_file", "write_file", "edit_file", "glob", "grep"})
        self.assertEqual(manifests["read_file"].version, "1.0.0")
        self.assertTrue(manifests["read_file"].read_only)
        self.assertIn("read", manifests["read_file"].capabilities)
        self.assertFalse(manifests["write_file"].read_only)

    def test_discovery_filters_disabled_tools(self):
        config = Config(disabled_tools=["bash", "write_file"])

        tools = discover_tools(config=config)
        names = {tool.name for tool in tools}
        specs = discover_tool_specs(config=config)
        disabled = {spec.manifest.name for spec in specs if not spec.enabled}

        self.assertNotIn("bash", names)
        self.assertNotIn("write_file", names)
        self.assertEqual(disabled, {"bash", "write_file"})

    def test_registry_exports_manifests(self):
        registry = ToolRegistry.default(config=Config(enabled_tools=["read_file"]))

        manifests = registry.manifests()

        self.assertEqual([manifest["name"] for manifest in manifests], ["read_file"])
        self.assertTrue(manifests[0]["read_only"])
        self.assertEqual(manifests[0]["enabled"], True)

    def test_default_tool_runtime_properties(self):
        registry = ToolRegistry.default()
        for name in ("bash", "write_file", "edit_file"):
            tool = registry.get(name)
            self.assertIsNotNone(tool)
            self.assertEqual(tool.timeout_seconds, 30)
            self.assertFalse(tool.retryable)
            self.assertFalse(tool.is_read_only)

    def test_read_only_tools_are_retryable(self):
        registry = ToolRegistry.default()
        for name in ("read_file", "glob", "grep"):
            tool = registry.get(name)
            self.assertIsNotNone(tool)
            self.assertTrue(tool.retryable)
            self.assertTrue(tool.is_read_only)


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

    def test_execute_blocks_absolute_path(self):
        result = self.tool.execute({"command": "cat /etc/passwd"})
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")

    def test_execute_blocks_embedded_absolute_path(self):
        result = self.tool.execute({"command": "python -c \"open('/etc/passwd').read()\""})
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")

    def test_execute_blocks_home_expansion(self):
        result = self.tool.execute({"command": "cat $HOME/.ssh/config"})
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")

    def test_execute_blocks_command_substitution(self):
        result = self.tool.execute({"command": "cat $(pwd)/README.md"})
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")

    def test_execute_blocks_embedded_parent_path(self):
        result = self.tool.execute({"command": "python -c \"open('../secret.txt').read()\""})
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")

    def test_execute_runs_in_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = BashTool(config=Config(workspace_root=tmpdir))
            result = tool.execute({"command": "pwd"})
        self.assertFalse(result.is_error)
        self.assertIn(tmpdir, result.output)


class TestFileReadTool(unittest.TestCase):
    def make_tool(self, workspace_root: str) -> FileReadTool:
        return FileReadTool(config=Config(workspace_root=workspace_root))

    def test_runtime_properties(self):
        tool = FileReadTool()
        self.assertTrue(tool.retryable)
        self.assertTrue(tool.is_read_only)
        self.assertEqual(tool.timeout_seconds, 30)

    def test_read_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.txt"
            path.write_text("line1\nline2\nline3\n", encoding="utf-8")
            result = self.make_tool(tmpdir).execute({"path": "sample.txt"})
        self.assertFalse(result.is_error)
        self.assertIn("line1", result.output)
        self.assertIn("line2", result.output)

    def test_read_nonexistent(self):
        result = FileReadTool().execute({"path": "nonexistent/file.txt"})
        self.assertTrue(result.is_error)

    def test_read_rejects_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.make_tool(tmpdir).execute({"path": "/etc/passwd"})
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")

    def test_read_rejects_parent_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.make_tool(tmpdir).execute({"path": "../secret.txt"})
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")

    def test_read_with_offset_and_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.txt"
            path.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
            result = self.make_tool(tmpdir).execute({"path": "sample.txt", "offset": 2, "limit": 2})
        self.assertFalse(result.is_error)
        self.assertIn("b", result.output)
        self.assertIn("c", result.output)
        self.assertNotIn("d", result.output)


class TestFileWriteTool(unittest.TestCase):
    def make_tool(self, workspace_root: str) -> FileWriteTool:
        return FileWriteTool(config=Config(workspace_root=workspace_root))

    def test_write_new_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.txt"
            result = self.make_tool(tmpdir).execute({"path": "test.txt", "content": "hello world"})
            self.assertFalse(result.is_error)
            self.assertEqual(path.read_text(), "hello world")

    def test_write_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "dir" / "test.txt"
            result = self.make_tool(tmpdir).execute({"path": "sub/dir/test.txt", "content": "nested"})
            self.assertFalse(result.is_error)
            self.assertTrue(path.exists())

    def test_preview_new_file_diff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.make_tool(tmpdir).preview({"path": "test.txt", "content": "hello\n"})
        self.assertFalse(result.is_error)
        self.assertIn("--- a/", result.output)
        self.assertIn("+++ b/", result.output)
        self.assertIn("+hello", result.output)

    def test_execute_includes_diff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.make_tool(tmpdir).execute({"path": "test.txt", "content": "hello\n"})
        self.assertFalse(result.is_error)
        self.assertIn("Diff:", result.output)
        self.assertIn("+hello", result.output)

    def test_write_rejects_parent_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.make_tool(tmpdir).execute({"path": "../outside.txt", "content": "x"})
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")


class TestFileEditTool(unittest.TestCase):
    def make_tool(self, workspace_root: str) -> FileEditTool:
        return FileEditTool(config=Config(workspace_root=workspace_root))

    def test_replace_unique_string(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.txt"
            path.write_text("hello world\nfoo bar\n", encoding="utf-8")
            result = self.make_tool(tmpdir).execute({
                "path": "sample.txt",
                "old_string": "foo bar",
                "new_string": "baz qux",
            })
            self.assertFalse(result.is_error)
            self.assertEqual(path.read_text(), "hello world\nbaz qux\n")

    def test_reject_non_unique(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.txt"
            path.write_text("aaa\naaa\n", encoding="utf-8")
            result = self.make_tool(tmpdir).execute({
                "path": "sample.txt",
                "old_string": "aaa",
                "new_string": "bbb",
            })
        self.assertTrue(result.is_error)
        self.assertIn("2 times", result.output)

    def test_reject_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.txt"
            path.write_text("hello\n", encoding="utf-8")
            result = self.make_tool(tmpdir).execute({
                "path": "sample.txt",
                "old_string": "xyz",
                "new_string": "abc",
            })
        self.assertTrue(result.is_error)

    def test_preview_edit_diff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.txt"
            path.write_text("hello world\nfoo bar\n", encoding="utf-8")
            result = self.make_tool(tmpdir).preview({
                "path": "sample.txt",
                "old_string": "foo bar",
                "new_string": "baz qux",
            })
        self.assertFalse(result.is_error)
        self.assertIn("-foo bar", result.output)
        self.assertIn("+baz qux", result.output)

    def test_execute_edit_includes_diff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.txt"
            path.write_text("hello world\nfoo bar\n", encoding="utf-8")
            result = self.make_tool(tmpdir).execute({
                "path": "sample.txt",
                "old_string": "foo bar",
                "new_string": "baz qux",
            })
        self.assertFalse(result.is_error)
        self.assertIn("Diff:", result.output)
        self.assertIn("-foo bar", result.output)
        self.assertIn("+baz qux", result.output)

    def test_edit_rejects_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.make_tool(tmpdir).execute({
                "path": "/tmp/outside.txt",
                "old_string": "x",
                "new_string": "y",
            })
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")


class TestGlobTool(unittest.TestCase):
    def make_tool(self, workspace_root: str) -> GlobTool:
        return GlobTool(config=Config(workspace_root=workspace_root))

    def test_runtime_properties(self):
        tool = GlobTool()
        self.assertTrue(tool.retryable)
        self.assertTrue(tool.is_read_only)
        self.assertEqual(tool.timeout_seconds, 30)

    def test_find_python_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "a.py").write_text("pass")
            (Path(tmpdir) / "b.txt").write_text("text")
            result = self.make_tool(tmpdir).execute({"pattern": "*.py", "directory": "."})
        self.assertFalse(result.is_error)
        self.assertIn("a.py", result.output)
        self.assertNotIn("b.txt", result.output)

    def test_glob_rejects_absolute_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.make_tool(tmpdir).execute({"pattern": "*.py", "directory": "/tmp"})
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")


class TestGrepTool(unittest.TestCase):
    def make_tool(self, workspace_root: str) -> GrepTool:
        return GrepTool(config=Config(workspace_root=workspace_root))

    def test_runtime_properties(self):
        tool = GrepTool()
        self.assertTrue(tool.retryable)
        self.assertTrue(tool.is_read_only)
        self.assertEqual(tool.timeout_seconds, 30)

    def test_search_in_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.py"
            path.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
            result = self.make_tool(tmpdir).execute({"pattern": "hello", "path": "sample.py"})
        self.assertFalse(result.is_error)
        self.assertIn("hello", result.output)

    def test_no_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.py"
            path.write_text("nothing here\n", encoding="utf-8")
            result = self.make_tool(tmpdir).execute({"pattern": "zzzzz", "path": "sample.py"})
        self.assertIn("No matches", result.output)

    def test_grep_rejects_parent_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.make_tool(tmpdir).execute({"pattern": "x", "path": "../outside.py"})
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "workspace_violation")


if __name__ == "__main__":
    unittest.main()
