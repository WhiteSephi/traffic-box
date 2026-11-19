"""Unit tests for config.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.config import AppConfig, load_dotenv_file, read_dotenv_file


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
        self.assertEqual(cfg.title, "TrafficBox")
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

    def test_encrypted_password_on_disk(self) -> None:
        """Verify passwords are encrypted on disk but decrypted in memory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "config.json"
            cfg = AppConfig(fritz_password="my_secret_vault_pwd_123")
            cfg.save(tmp_path)

            raw_json = json.loads(tmp_path.read_text(encoding="utf-8"))
            # Disk must NOT contain the plaintext password!
            self.assertNotEqual(raw_json["fritz_password"], "my_secret_vault_pwd_123")
            self.assertTrue(raw_json["fritz_password"].startswith("enc:"))

            # Reloading must restore original plaintext password
            original_fn = AppConfig.config_file_path
            try:
                AppConfig.config_file_path = classmethod(lambda cls: tmp_path)  # type: ignore[assignment]
                loaded = AppConfig.load()
                self.assertEqual(loaded.fritz_password, "my_secret_vault_pwd_123")
            finally:
                AppConfig.config_file_path = original_fn  # type: ignore[assignment]

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

    def test_sanitize_corrupted_config_values(self) -> None:
        """Verify corrupted JSON values (letters in numbers, out of bounds) are safely sanitized."""
        corrupted = {
            "fritzbox_host": "   ",
            "ping_endpoint": "",
            "upnp_port": "not_a_port",
            "refresh_interval_sec": "three",
            "start_delay_sec": -50,
            "opacity": 500,
            "widget_width": "tiny",
            "manual_download_mbps": "invalid_speed",
            "manual_upload_mbps": -15.0,
            "scale_mode": "nonsense_scale",
            "active_view": "unknown_view",
            "footer_counter_mode": "invalid_mode",
            "compact_mode": "yes",
            "graph_only_mode": "invalid_bool",
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "config.json"
            tmp_path.write_text(json.dumps(corrupted), encoding="utf-8")

            original_fn = AppConfig.config_file_path
            try:
                AppConfig.config_file_path = classmethod(lambda cls: tmp_path)  # type: ignore[assignment]
                loaded = AppConfig.load()

                # Strings safely reset to defaults
                self.assertEqual(loaded.fritzbox_host, "fritz.box")
                self.assertEqual(loaded.ping_endpoint, "1.1.1.1")

                # Corrupted integers safely fall back or clamp
                self.assertEqual(loaded.upnp_port, 49000)
                self.assertEqual(loaded.refresh_interval_sec, 1)
                self.assertEqual(loaded.start_delay_sec, 0)
                self.assertEqual(loaded.opacity, 100)  # clamped from 500
                self.assertEqual(loaded.widget_width, 460)  # fallback from "tiny"

                # Corrupted floats safely fall back or clamp
                self.assertEqual(loaded.manual_download_mbps, 500.0)
                self.assertEqual(loaded.manual_upload_mbps, 0.5)  # clamped from -15.0

                # Corrupted enums safely reset to defaults
                self.assertEqual(loaded.scale_mode, "sqrt")
                self.assertEqual(loaded.active_view, "graph")
                self.assertEqual(loaded.footer_counter_mode, "today")

                # Corrupted booleans safely parsed
                self.assertTrue(loaded.compact_mode)
                self.assertFalse(loaded.graph_only_mode)
            finally:
                AppConfig.config_file_path = original_fn  # type: ignore[assignment]

    def test_settings_geometry_and_ui_scale(self) -> None:
        """Verify settings dialog position and UI scaling attributes and properties."""
        cfg = AppConfig(
            settings_pos_x=120,
            settings_pos_y=180,
            settings_width=720,
            settings_height=580,
            ui_scale_percent=125,
        )
        self.assertEqual(cfg.settings_pos_x, 120)
        self.assertEqual(cfg.settings_pos_y, 180)
        self.assertEqual(cfg.settings_width, 720)
        self.assertEqual(cfg.settings_height, 580)
        self.assertEqual(cfg.ui_scale_percent, 125)
        self.assertAlmostEqual(cfg.ui_scale, 1.25)

        # Clamping behavior
        cfg.ui_scale_percent = 500
        cfg.sanitize()
        self.assertEqual(cfg.ui_scale_percent, 300)
        self.assertAlmostEqual(cfg.ui_scale, 3.0)

        cfg.ui_scale_percent = 20
        cfg.sanitize()
        self.assertEqual(cfg.ui_scale_percent, 70)
        self.assertAlmostEqual(cfg.ui_scale, 0.7)

    def test_backward_compatible_ui_scale_loading(self) -> None:
        """Verify backward-compatible loading of float ui_scale into ui_scale_percent."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "config.json"
            tmp_path.write_text(json.dumps({"ui_scale": 1.5}), encoding="utf-8")
            original_fn = AppConfig.config_file_path
            try:
                AppConfig.config_file_path = classmethod(lambda cls: tmp_path)  # type: ignore[assignment]
                loaded = AppConfig.load()
                self.assertEqual(loaded.ui_scale_percent, 150)
                self.assertAlmostEqual(loaded.ui_scale, 1.5)
            finally:
                AppConfig.config_file_path = original_fn  # type: ignore[assignment]

    def test_invalid_host_ping_and_colors_sanitized(self) -> None:
        """Verify invalid hosts, ping endpoints, and hex colors are safely reset by sanitize()."""
        cfg = AppConfig(
            fritzbox_host="http://evil.invalid/path@1.2.3.4",
            ping_endpoint="-c 1 1.1.1.1",
            download_color="red; background: url(http://evil.invalid)",
            background_color="#ZZZ",
        )
        cfg.sanitize()
        self.assertEqual(cfg.fritzbox_host, "fritz.box")
        self.assertEqual(cfg.ping_endpoint, "1.1.1.1")
        self.assertEqual(cfg.download_color, "#FFEA00")
        self.assertEqual(cfg.background_color, "#1C2428")

    def test_dotenv_password_not_exposed_in_os_environ(self) -> None:
        """Verify AppConfig.load() reads .env secrets without leaking them into os.environ."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            env_file = tmp_root / ".env"
            env_file.write_text(
                "FRITZBOX_HOST=192.168.178.1\nFRITZBOX_PASSWORD=super_secret_env_pwd\n",
                encoding="utf-8",
            )
            cfg_file = tmp_root / "config.json"

            clean_env = {k: v for k, v in os.environ.items() if not k.startswith("FRITZBOX_")}
            original_fn = AppConfig.config_file_path
            try:
                AppConfig.config_file_path = classmethod(lambda cls: cfg_file)  # type: ignore[assignment]
                with patch.dict(os.environ, clean_env, clear=True), patch(
                    "src.config.read_dotenv_file", side_effect=lambda: read_dotenv_file(env_file)
                ):
                    loaded = AppConfig.load()
                    self.assertEqual(loaded.fritzbox_host, "192.168.178.1")
                    self.assertEqual(loaded.fritz_password, "super_secret_env_pwd")
                    self.assertTrue(loaded.enable_guest_monitor)
                    self.assertNotIn("FRITZBOX_PASSWORD", os.environ)
            finally:
                AppConfig.config_file_path = original_fn  # type: ignore[assignment]

    def test_enable_local_fallback_sanitized(self) -> None:
        """Verify string/int values for enable_local_fallback are coerced to bool."""
        cfg = AppConfig()
        cfg.enable_local_fallback = "false"  # type: ignore[assignment]
        cfg.sanitize()
        self.assertIs(cfg.enable_local_fallback, False)

        cfg.enable_local_fallback = 1  # type: ignore[assignment]
        cfg.sanitize()
        self.assertIs(cfg.enable_local_fallback, True)

    def test_internet_health_config_defaults_and_sanitize(self) -> None:
        """Verify defaults and sanitize clamping/validation for internet health fields."""
        defaults = AppConfig()
        self.assertTrue(defaults.enable_internet_health)
        self.assertEqual(defaults.health_probe_interval_sec, 30)
        self.assertEqual(defaults.health_ip_mode, "auto")
        self.assertTrue(defaults.health_uncached_dns)

        cfg = AppConfig(
            enable_internet_health="false",  # type: ignore[arg-type]
            health_probe_interval_sec=5,
            health_ip_mode="invalid_mode",
            health_uncached_dns=0,  # type: ignore[arg-type]
        )
        cfg.sanitize()
        self.assertIs(cfg.enable_internet_health, False)
        self.assertEqual(cfg.health_probe_interval_sec, 10)
        self.assertEqual(cfg.health_ip_mode, "auto")
        self.assertIs(cfg.health_uncached_dns, False)

        cfg.health_probe_interval_sec = 999
        cfg.health_ip_mode = "dual_stack"
        cfg.sanitize()
        self.assertEqual(cfg.health_probe_interval_sec, 120)
        self.assertEqual(cfg.health_ip_mode, "dual_stack")


if __name__ == "__main__":
    unittest.main()
