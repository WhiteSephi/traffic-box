"""Unit tests for autostart command generation and platform integrations."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src.autostart import get_linux_autostart_cmd, get_windows_autostart_cmd


class TestAutostart(unittest.TestCase):
    def test_windows_autostart_frozen(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "executable", r"C:\apps\TrafficBox.exe"
        ):
            cmd = get_windows_autostart_cmd(Path(r"C:\apps"))
            self.assertEqual(cmd, r'"C:\apps\TrafficBox.exe"')

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

    def test_linux_autostart_frozen(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "executable", "/usr/bin/TrafficBox"
        ):
            cmd = get_linux_autostart_cmd(Path("/opt/TrafficBox"))
            self.assertEqual(cmd, "/usr/bin/TrafficBox")

    def test_linux_autostart_sh_script_present(self):
        fake_root = Path("/fake/project")
        with patch.object(sys, "frozen", False, create=True), patch.object(
            Path, "is_file", lambda p: str(p).endswith("start_linux.sh")
        ):
            cmd = get_linux_autostart_cmd(fake_root)
            self.assertTrue(cmd.endswith("start_linux.sh"))

    def test_linux_autostart_fallback(self):
        fake_root = Path("/fake/project")
        with patch.object(sys, "frozen", False, create=True), patch.object(
            Path, "is_file", lambda p: False
        ), patch.object(sys, "executable", "/usr/bin/python3"):
            cmd = get_linux_autostart_cmd(fake_root)
            self.assertEqual(cmd, "/usr/bin/python3 -m src.main")


if __name__ == "__main__":
    unittest.main()
