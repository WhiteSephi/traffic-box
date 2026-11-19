"""Unit tests for autostart command generation and platform integrations."""

import base64
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import tempfile
from src.autostart import (
    get_linux_autostart_cmd,
    get_windows_autostart_cmd,
    sync_kwin_position_rule,
)


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

    def test_linux_autostart_sh_script_with_spaces(self):
        fake_root = Path("/fake/path with spaces")
        with patch.object(sys, "frozen", False, create=True), patch.object(
            Path, "is_file", lambda p: str(p).endswith("start_linux.sh")
        ):
            cmd = get_linux_autostart_cmd(fake_root)
            self.assertEqual(cmd, f'"{fake_root / "start_linux.sh"}"')

    def test_linux_autostart_fallback(self):
        fake_root = Path("/fake/project")
        with patch.object(sys, "frozen", False, create=True), patch.object(
            Path, "is_file", lambda p: False
        ), patch.object(sys, "executable", "/usr/bin/python3"):
            cmd = get_linux_autostart_cmd(fake_root)
            self.assertEqual(cmd, "/usr/bin/python3 -m src.main")

    def test_sync_kwin_position_rule_non_linux(self):
        with patch.object(sys, "platform", "win32"):
            self.assertFalse(sync_kwin_position_rule(100, 200))

    def test_sync_kwin_position_rule_writes_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_home = Path(tmp_dir)
            fake_kwinrules = tmp_home / ".config" / "kwinrulesrc"
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(tmp_home / ".config")}), patch.object(
                sys, "platform", "linux"
            ):
                res = sync_kwin_position_rule(123, 456)
                self.assertTrue(res)
                self.assertTrue(fake_kwinrules.is_file())
                content = fake_kwinrules.read_text(encoding="utf-8")
                self.assertIn("[General]", content)
                self.assertIn("count=1", content)
                self.assertIn("rules=TrafficBox-Position", content)
                self.assertIn("Order=TrafficBox-Position", content)
                self.assertIn("[TrafficBox-Position]", content)
                self.assertIn("position=123,456", content)
                self.assertIn("positionrule=3", content)
                self.assertIn("wmclass=.*[Tt]raffic[Bb]ox.*", content)
                self.assertIn("wmclassmatch=3", content)
                self.assertIn("wmclasscomplete=false", content)
                self.assertIn("skiptaskbar=true", content)
                self.assertIn("skiptaskbarrule=2", content)
                self.assertIn("skipswitcher=true", content)
                self.assertIn("skipswitcherrule=2", content)

    def test_sync_kwin_position_rule_preserves_other_rules(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_home = Path(tmp_dir)
            cfg_dir = tmp_home / ".config"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            fake_kwinrules = cfg_dir / "kwinrulesrc"
            fake_kwinrules.write_text(
                "[General]\ncount=1\nrules=OtherRule\nOrder=OtherRule\n\n"
                "[OtherRule]\nDescription=Existing\n",
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(cfg_dir)}), patch.object(
                sys, "platform", "linux"
            ):
                res = sync_kwin_position_rule(999, 888)
                self.assertTrue(res)
                content = fake_kwinrules.read_text(encoding="utf-8")
                self.assertIn("count=2", content)
                self.assertIn("OtherRule,TrafficBox-Position", content)
                self.assertIn("[OtherRule]", content)
                self.assertIn("[TrafficBox-Position]", content)
                self.assertIn("position=999,888", content)

    def test_windows_fallback_handles_quotes_safely(self):
        fake_root = Path(r"C:\User's Dir\Traffic;Box")
        with patch.object(sys, "frozen", False, create=True), patch.object(
            Path, "is_file", lambda p: False
        ), patch.object(sys, "executable", r"C:\fake\python.exe"):
            cmd = get_windows_autostart_cmd(fake_root)
            self.assertNotIn("User's Dir", cmd)
            match = re.search(r"b64decode\('([A-Za-z0-9+/=]+)'\)", cmd)
            self.assertIsNotNone(match)
            decoded = base64.b64decode(match.group(1)).decode("utf-8")
            self.assertEqual(decoded, str(fake_root))

    def test_linux_desktop_exec_escapes_special_chars(self):
        fake_root = Path('/opt/my "quoted" $dir/100%app')
        with patch.object(sys, "frozen", False, create=True), patch.object(
            Path, "is_file", lambda p: str(p).endswith("start_linux.sh")
        ):
            cmd = get_linux_autostart_cmd(fake_root)
            self.assertTrue(cmd.startswith('"') and cmd.endswith('"'))
            self.assertIn(r'\"quoted\"', cmd)
            self.assertIn(r"\$dir", cmd)
            self.assertIn("100%%app", cmd)


if __name__ == "__main__":
    unittest.main()
