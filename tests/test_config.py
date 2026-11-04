"""Unit tests for config.py."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.config import AppConfig, load_dotenv_file


class TestConfig(unittest.TestCase):
    """Test configuration dataclass and .env loader."""

    def test_default_values(self) -> None:
        """Verify default configuration values."""
        cfg = AppConfig()
        self.assertEqual(cfg.fritzbox_host, "fritz.box")
        self.assertEqual(cfg.upnp_port, 49000)
        self.assertEqual(cfg.refresh_interval_sec, 1)
        self.assertFalse(cfg.enable_guest_monitor)
        self.assertFalse(cfg.enable_local_traffic_monitor)
        self.assertEqual(cfg.active_view, "graph")
        self.assertEqual(cfg.scale_mode, "sqrt")
        self.assertTrue(cfg.show_peak_rate)
        self.assertTrue(cfg.show_guest_rate_labels)

    def test_save_and_load_roundtrip(self) -> None:
        """Verify saving to JSON and reloading preserves custom values."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "config.json"
            cfg = AppConfig(
                fritzbox_host="192.168.178.1",
                refresh_interval_sec=2,
                enable_local_traffic_monitor=True,
                show_peak_rate=False,
                opacity=90,
            )
            cfg.save(tmp_path)

            self.assertTrue(tmp_path.is_file())
            raw_json = json.loads(tmp_path.read_text(encoding="utf-8"))
            self.assertEqual(raw_json["fritzbox_host"], "192.168.178.1")
            self.assertEqual(raw_json["refresh_interval_sec"], 2)
            self.assertTrue(raw_json["enable_local_traffic_monitor"])
            self.assertFalse(raw_json["show_peak_rate"])
            self.assertEqual(raw_json["opacity"], 90)

    def test_load_ignores_unknown_keys(self) -> None:
        """Verify loading safely ignores keys that do not belong to AppConfig."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "config.json"
            tmp_path.write_text(
                json.dumps({"fritzbox_host": "10.0.0.1", "non_existent_key": 12345}),
                encoding="utf-8",
            )
            # Patch config_file_path
            original_fn = AppConfig.config_file_path
            try:
                AppConfig.config_file_path = classmethod(lambda cls: tmp_path)  # type: ignore[assignment]
                loaded = AppConfig.load()
                self.assertEqual(loaded.fritzbox_host, "10.0.0.1")
                self.assertFalse(hasattr(loaded, "non_existent_key"))
            finally:
                AppConfig.config_file_path = original_fn  # type: ignore[assignment]

    def test_load_dotenv_file(self) -> None:
        """Verify .env parser extracts key=value pairs, ignores comments and whitespace."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text(
                "# Kommentar\n"
                "TEST_CFG_KEY1=hello_world\n"
                "  TEST_CFG_KEY2 = 'quoted_val'  \n"
                "\n"
                "# Noch ein Kommentar\n"
                "TEST_CFG_KEY3=\"double_quoted\"\n",
                encoding="utf-8",
            )
            import os

            load_dotenv_file(env_file)
            self.assertEqual(os.environ.get("TEST_CFG_KEY1"), "hello_world")
            self.assertEqual(os.environ.get("TEST_CFG_KEY2"), "quoted_val")
            self.assertEqual(os.environ.get("TEST_CFG_KEY3"), "double_quoted")


if __name__ == "__main__":
    unittest.main()
