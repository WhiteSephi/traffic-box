"""Unit tests for ui/settings_dlg.py."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src import __version__
from src.config import AppConfig
from src.ui.settings_dlg import ColorButton, ModernColorPickerPopup, SettingsDialog, THEMES

_app = QApplication.instance() or QApplication(sys.argv)


class TestSettingsDialog(unittest.TestCase):
    """Test SettingsDialog initialization, form fields, theme presets, and callbacks."""

    def setUp(self) -> None:
        self.config = AppConfig(
            fritzbox_host="192.168.178.1",
            upnp_port=49000,
            refresh_interval_sec=2,
            opacity=80,
            compact_mode=False,
            graph_only_mode=False,
            bound_box_udn="uuid:test-box-1234",
            bound_box_name="Test FRITZ!Box",
        )
        # Prevent test instances from overwriting the real user config on disk
        self.config.save = MagicMock()  # type: ignore[method-assign]
        self.applied = False

    def _on_apply(self) -> None:
        self.applied = True

    def test_dialog_init_and_load(self) -> None:
        """Verify settings dialog loads initial values from AppConfig into widgets."""
        dlg = SettingsDialog(self.config, self._on_apply)
        try:
            self.assertEqual(dlg.txt_host.text(), "192.168.178.1")
            self.assertEqual(dlg.spin_port.value(), 49000)
            self.assertEqual(dlg.spin_refresh.value(), 2)
            self.assertEqual(dlg.slider_opacity.value(), 80)
            self.assertFalse(dlg.chk_compact.isChecked())
            self.assertFalse(dlg.chk_graph_only.isChecked())
            self.assertIn("Test FRITZ!Box", dlg.lbl_bound_box.text())
        finally:
            dlg.deleteLater()

    def test_apply_changes_updates_config_and_fires_callback(self) -> None:
        """Verify modifying form fields and applying updates AppConfig and calls on_apply."""
        dlg = SettingsDialog(self.config, self._on_apply)
        try:
            # Change form values
            dlg.txt_host.setText("192.168.1.254")
            dlg.spin_port.setValue(49001)
            dlg.spin_refresh.setValue(4)
            dlg.slider_opacity.setValue(90)
            dlg.chk_compact.setChecked(True)
            dlg.chk_show_bits.setChecked(True)

            with patch("src.ui.settings_dlg.set_autostart") as mock_set_autostart:
                dlg._apply_changes()

            self.assertTrue(self.applied)
            self.assertEqual(self.config.fritzbox_host, "192.168.1.254")
            self.assertEqual(self.config.upnp_port, 49001)
            self.assertEqual(self.config.refresh_interval_sec, 4)
            self.assertEqual(self.config.opacity, 90)
            self.assertTrue(self.config.compact_mode)
            self.assertTrue(self.config.show_as_bits)
        finally:
            dlg.deleteLater()

    def test_apply_theme_presets(self) -> None:
        """Verify selecting a theme preset applies all colors to the swatch buttons."""
        dlg = SettingsDialog(self.config, self._on_apply)
        try:
            theme_name = "Emerald Matrix (Giftgrün & Minze)"
            self.assertIn(theme_name, THEMES)
            preset = THEMES[theme_name]

            dlg.cmb_theme.setCurrentText(theme_name)
            dlg._apply_selected_theme()
            self.assertEqual(dlg.btn_col_down.hex_color, preset["down"])
            self.assertEqual(dlg.btn_col_up.hex_color, preset["up"])
            self.assertEqual(dlg.btn_col_bg.hex_color, preset["bg"])
            self.assertEqual(dlg.btn_col_border.hex_color, preset["border"])
        finally:
            dlg.deleteLater()

    def test_reset_single_tab(self) -> None:
        """Verify _reset_single_tab restores default values for specific tab index."""
        dlg = SettingsDialog(self.config, self._on_apply)
        try:
            dlg.txt_host.setText("custom-host.invalid")
            dlg.spin_port.setValue(1234)

            # Reset Tab 0 (FRITZ!Box)
            dlg._reset_single_tab(0)
            defaults = AppConfig()
            self.assertEqual(dlg.txt_host.text(), defaults.fritzbox_host)
            self.assertEqual(dlg.spin_port.value(), defaults.upnp_port)

            # Reset Tab 1 (Allgemein)
            dlg.slider_opacity.setValue(30)
            dlg._reset_single_tab(1)
            self.assertEqual(dlg.slider_opacity.value(), defaults.opacity)
        finally:
            dlg.deleteLater()

    def test_about_tab_and_system_info(self) -> None:
        """Verify 'Über' tab displays version and disables reset button."""
        dlg = SettingsDialog(self.config, self._on_apply, initial_tab=5)
        try:
            self.assertEqual(dlg.tabs.count(), 6)
            self.assertEqual(dlg.tabs.tabText(5), "Über")
            self.assertEqual(dlg.tabs.currentIndex(), 5)
            self.assertFalse(dlg.btn_reset.isEnabled())
            self.assertEqual(dlg.lbl_about_version.text(), f"v{__version__}")

            # Switching back to tab 0 re-enables the reset button
            dlg.tabs.setCurrentIndex(0)
            self.assertTrue(dlg.btn_reset.isEnabled())
        finally:
            dlg.deleteLater()

    def test_color_button_and_picker_popup(self) -> None:
        """Verify ColorButton updates swatch and opens ModernColorPickerPopup."""
        btn = ColorButton("#FF00AA")
        try:
            self.assertEqual(btn.hex_color, "#FF00AA")
            btn.hex_color = "#00FFCC"
            self.assertEqual(btn.hex_color, "#00FFCC")

            popup = ModernColorPickerPopup("#00FFCC", lambda col: None)
            try:
                self.assertEqual(popup.txt_hex.text(), "#00FFCC")
                popup._on_hex_text_changed("#123456")
                self.assertEqual(popup.txt_hex.text(), "#00FFCC")
            finally:
                popup.deleteLater()
        finally:
            btn.deleteLater()

    def test_dialog_stays_on_top_and_geometry_saved(self) -> None:
        """Verify SettingsDialog has WindowStaysOnTopHint and geometry is persisted."""
        dlg = SettingsDialog(self.config, self._on_apply)
        try:
            self.assertTrue(bool(dlg.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
            dlg.move(250, 350)
            dlg.resize(700, 550)
            dlg._save_geometry_to_config()
            self.assertEqual(self.config.settings_pos_x, 250)
            self.assertEqual(self.config.settings_pos_y, 350)
            self.assertEqual(self.config.settings_width, 700)
            self.assertEqual(self.config.settings_height, 550)
        finally:
            dlg.deleteLater()

    def test_ui_scale_form_controls(self) -> None:
        """Verify modifying UI scale updates AppConfig upon apply."""
        dlg = SettingsDialog(self.config, self._on_apply)
        try:
            self.assertEqual(dlg.spin_ui_scale.value(), 100)
            self.assertEqual(dlg.slider_ui_scale.value(), 100)

            dlg.spin_ui_scale.setValue(150)
            self.assertEqual(dlg.slider_ui_scale.value(), 150)

            dlg._apply_changes()
            self.assertEqual(self.config.ui_scale_percent, 150)
            self.assertAlmostEqual(self.config.ui_scale, 1.5)

            # Test reset single tab
            dlg._reset_single_tab(2)
            self.assertEqual(dlg.spin_ui_scale.value(), 100)
        finally:
            dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
