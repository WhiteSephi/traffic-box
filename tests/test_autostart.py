"""Unit tests for autostart command generation and platform integrations."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src.autostart import get_windows_autostart_cmd


class TestAutostart(unittest.TestCase):
    def test_windows_autostart_frozen(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "executable", r"C:\apps\FB-Traffic-Widget.exe"
        ):
            cmd = get_windows_autostart_cmd(Path(r"C:\apps"))
            self.assertEqual(cmd, r'"C:\apps\FB-Traffic-Widget.exe"')

    def test_windows_autostart_vbs_script_present(self):
        fake_root = Path(r"C:\fake\project")
        with patch.object(sys, "frozen", False, create=True), patch.object(
            Path, "is_file", lambda p: str(p).endswith("start_windows.vbs")
        ):
            cmd = get_windows_autostart_cmd(fake_root)
            self.assertIn("wscript.exe", cmd)
            self.assertIn("start_windows.vbs", cmd)

    def test_windows_autostart_vbs_missing_fallback(self):
        fake_root = Path(r"C:\fake\project")
        with patch.object(sys, "frozen", False, create=True), patch.object(
            Path, "is_file", lambda p: False
        ), patch.object(sys, "executable", r"C:\fake\python.exe"):
            cmd = get_windows_autostart_cmd(fake_root)
            self.assertIn("sys.path.insert(0", cmd)
            self.assertIn("os.chdir", cmd)
            self.assertIn("from src.main import main", cmd)


if __name__ == "__main__":
    unittest.main()
