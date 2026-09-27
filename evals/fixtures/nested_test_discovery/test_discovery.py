import tempfile
import unittest
from pathlib import Path

from discovery import discover_tests


class TestDiscovery(unittest.TestCase):
    def test_finds_root_test(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "test_root.py").touch()
            self.assertEqual(discover_tests(tmpdir), ["test_root.py"])

    def test_recursively_finds_and_sorts_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "unit").mkdir()
            (root / "integration").mkdir()
            (root / "unit" / "test_zeta.py").touch()
            (root / "integration" / "test_alpha.py").touch()
            (root / "integration" / "helper.py").touch()
            self.assertEqual(
                discover_tests(root),
                ["integration/test_alpha.py", "unit/test_zeta.py"],
            )


if __name__ == "__main__":
    unittest.main()
