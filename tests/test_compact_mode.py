"""Unit tests for TrafficBox compact mode and layout sizing."""

from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.api.models import HealthStatus, InternetHealthSnapshot, TrafficSample
from src.api.net_health import set_shutting_down
from src.config import AppConfig
from src.ui.widget import TrafficBox

_app = QApplication.instance() or QApplication(sys.argv)


class TestCompactMode(unittest.TestCase):
    """Test compact mode geometry, element hierarchy and overlap prevention."""

    def setUp(self) -> None:
        self.config = AppConfig()
        self.config.compact_mode = False
        self.config.show_wan_status_pill = True
        self.config.enable_dns_monitor = True
        # Prevent test instances from overwriting the real user config on disk
        self.config.save = lambda *args, **kwargs: None  # type: ignore[method-assign]
        self.widget = TrafficBox(self.config)

    def tearDown(self) -> None:
        self.widget._stop_background_tasks(save_state=False)
        set_shutting_down(False)
        self.widget.deleteLater()

    def test_compact_mode_height_calculation(self) -> None:
        """Verify _get_compact_height accommodates minimum size hints without truncation."""
        self.widget._toggle_compact(True)
        base_h = self.widget._get_compact_height()
        self.assertGreaterEqual(base_h, 120)

        # Enabling local traffic header increases height
        self.config.enable_local_traffic_monitor = True
        self.config.show_local_traffic_in_header = True
        pc_h = self.widget._get_compact_height()
        self.assertGreater(pc_h, base_h)

    def test_compact_mode_toggle_prevents_overlap(self) -> None:
        """Verify no vertical overlap between header, rate labels, progress bars, and footer."""
        sample = TrafficSample(
            is_connected=True,
            wan_connected=True,
            download_bps=910000,
            upload_bps=1530000,
            max_download_bps=100000000,
            max_upload_bps=40000000,
            dns_ms=5.1,
            active_dns_ip="192.168.178.1",
        )
        self.widget._on_sample_received(sample)
        self.widget.show()
        _app.processEvents()

        # Switch to compact mode
        self.widget._toggle_compact(True)
        _app.processEvents()

        self.assertTrue(self.widget.config.compact_mode)
        self.assertFalse(self.widget.center_stack.isVisible())

        # Check vertical coordinates
        hdr_bottom = self.widget.lbl_down_header.mapTo(
            self.widget, self.widget.lbl_down_header.rect().bottomLeft()
        ).y()
        rate_top = self.widget.lbl_down_rate.mapTo(
            self.widget, self.widget.lbl_down_rate.rect().topLeft()
        ).y()
        rate_bottom = self.widget.lbl_down_rate.mapTo(
            self.widget, self.widget.lbl_down_rate.rect().bottomLeft()
        ).y()
        bar_top = self.widget.bar_down_util.mapTo(
            self.widget, self.widget.bar_down_util.rect().topLeft()
        ).y()
        bar_bottom = self.widget.bar_down_util.mapTo(
            self.widget, self.widget.bar_down_util.rect().bottomLeft()
        ).y()
        meta_top = self.widget.lbl_down_meta.mapTo(
            self.widget, self.widget.lbl_down_meta.rect().topLeft()
        ).y()
        meta_bottom = self.widget.lbl_down_meta.mapTo(
            self.widget, self.widget.lbl_down_meta.rect().bottomLeft()
        ).y()
        pill_top = self.widget.lbl_wan_pill.mapTo(
            self.widget, self.widget.lbl_wan_pill.rect().topLeft()
        ).y()

        self.assertLessEqual(hdr_bottom, rate_top)
        self.assertLessEqual(rate_bottom, bar_top)
        self.assertLessEqual(bar_bottom, meta_top)
        self.assertLessEqual(meta_bottom, pill_top)

    def test_graph_only_mode_toggle(self) -> None:
        """Verify graph-only mode hides rates container while keeping center graph visible."""
        self.widget.show()
        _app.processEvents()

        # Initially both are visible
        self.assertTrue(self.widget.rates_container.isVisible())
        self.assertTrue(self.widget.center_stack.isVisible())

        # Enable graph-only mode
        self.widget._toggle_graph_only(True)
        _app.processEvents()

        self.assertTrue(self.widget.config.graph_only_mode)
        self.assertFalse(self.widget.config.compact_mode)
        self.assertFalse(self.widget.rates_container.isVisible())
        self.assertTrue(self.widget.center_stack.isVisible())

        # Toggling compact mode turns off graph_only mode
        self.widget._toggle_compact(True)
        _app.processEvents()
        self.assertTrue(self.widget.config.compact_mode)
        self.assertFalse(self.widget.config.graph_only_mode)
        self.assertTrue(self.widget.rates_container.isVisible())
        self.assertFalse(self.widget.center_stack.isVisible())

        # Toggling graph_only turns off compact mode
        self.widget._toggle_graph_only(True)
        _app.processEvents()
        self.assertTrue(self.widget.config.graph_only_mode)
        self.assertFalse(self.widget.config.compact_mode)
        self.assertFalse(self.widget.rates_container.isVisible())
        self.assertTrue(self.widget.center_stack.isVisible())

    def test_position_save_timer(self) -> None:
        """Verify moveEvent ignores unprompted moves but debounces user moves."""
        self.widget.show()
        _app.processEvents()
        # Unprompted move (e.g. compositor mapping) should NOT trigger save timer
        self.widget.move(500, 300)
        _app.processEvents()
        self.assertFalse(self.widget._save_pos_timer.isActive())

        # User-initiated move should trigger save timer
        self.widget._user_is_moving = True
        self.widget.move(600, 400)
        _app.processEvents()
        self.assertTrue(self.widget._save_pos_timer.isActive())

    def test_window_flags_skip_taskbar(self) -> None:
        """Verify window has Tool and Frameless flags to remain hidden from taskbars across OSes."""
        from PySide6.QtCore import Qt

        flags = self.widget.windowFlags()
        self.assertTrue(bool(flags & Qt.WindowType.FramelessWindowHint))
        self.assertTrue(bool(flags & Qt.WindowType.Tool))

    def test_context_menu_footer_counter_states(self) -> None:
        """Verify context menu accurately reflects active vs deactivated footer counter."""
        # 1. Active state
        self.widget.config.show_session_totals = True
        self.widget.config.footer_counter_mode = "today"
        menu_active = self.widget._build_context_menu()
        menu_titles = [a.text() for a in menu_active.actions()]
        self.assertIn("Footer-Zähler (Zeitraum)", menu_titles)
        self.assertIn("Footer-Zähler anzeigen", menu_titles)

        act_footer = next(a for a in menu_active.actions() if a.text() == "Footer-Zähler anzeigen")
        self.assertTrue(act_footer.isChecked())

        # Submenu options
        footer_sub = act_footer.menu() or next(
            a.menu() for a in menu_active.actions() if a.text() == "Footer-Zähler (Zeitraum)"
        )
        sub_actions = {a.text(): a.isChecked() for a in footer_sub.actions() if not a.isSeparator()}
        self.assertFalse(sub_actions["Ausblenden (deaktiviert)"])
        self.assertTrue(sub_actions["Heute (Online-Zähler)"])

        # 2. Deactivated state
        self.widget.config.show_session_totals = False
        menu_deact = self.widget._build_context_menu()
        menu_deact_titles = [a.text() for a in menu_deact.actions()]
        self.assertIn("Footer-Zähler (Deaktiviert)", menu_deact_titles)

        act_footer_deact = next(a for a in menu_deact.actions() if a.text() == "Footer-Zähler anzeigen")
        self.assertFalse(act_footer_deact.isChecked())

        footer_sub_deact = next(
            a.menu() for a in menu_deact.actions() if a.text() == "Footer-Zähler (Deaktiviert)"
        )
        sub_deact_actions = {
            a.text(): a.isChecked() for a in footer_sub_deact.actions() if not a.isSeparator()
        }
        self.assertTrue(sub_deact_actions["Ausblenden (deaktiviert)"])
        self.assertFalse(sub_deact_actions["Heute (Online-Zähler)"])

        # 3. Toggling via _toggle_footer_counter
        self.widget._toggle_footer_counter(True)
        self.assertTrue(self.widget.config.show_session_totals)
        self.assertFalse(self.widget.lbl_footer.isHidden())

        self.widget._toggle_footer_counter(False)
        self.assertFalse(self.widget.config.show_session_totals)
        self.assertTrue(self.widget.lbl_footer.isHidden())

    def test_visual_size_grip_present_and_visible(self) -> None:
        """Verify custom VisualSizeGrip is configured and reacts to locked_pos / compact_mode."""
        from src.ui.widget import VisualSizeGrip

        self.assertIsInstance(self.widget.size_grip, VisualSizeGrip)
        self.widget.config.locked_pos = False
        self.widget.config.compact_mode = False
        self.widget._apply_config_visuals()
        self.assertFalse(self.widget.size_grip.isHidden())

        self.widget.config.locked_pos = True
        self.widget._apply_config_visuals()
        self.assertTrue(self.widget.size_grip.isHidden())

    def test_ui_scale_applied_to_elements(self) -> None:
        """Verify UI scaling factor updates fonts, header buttons, and minimum window size."""
        self.widget.config.ui_scale_percent = 150
        self.widget._apply_config_visuals()

        # Title font should scale from baseline 10pt -> 15pt
        self.assertEqual(self.widget.lbl_title.font().pointSize(), 15)

        # Header buttons height should scale from 30px -> 45px
        self.assertEqual(self.widget.btn_view_graph.height(), 45)
        self.assertEqual(self.widget.btn_view_counters.height(), 45)
        self.assertEqual(self.widget.btn_settings.height(), 45)

        # Minimum width scales from baseline 260 -> 390
        self.assertEqual(self.widget.minimumWidth(), 390)

        # Reset to 100%
        self.widget.config.ui_scale_percent = 100
        self.widget._apply_config_visuals()
        self.assertEqual(self.widget.lbl_title.font().pointSize(), 10)
        self.assertEqual(self.widget.btn_view_graph.height(), 30)
        self.assertEqual(self.widget.minimumWidth(), 260)

    def test_tooltip_escapes_html_injection(self) -> None:
        """Verify UPnP strings in connection tooltip are HTML-escaped to prevent injection."""
        sample = TrafficSample(
            is_connected=True,
            wan_connected=True,
            box_name="<img src=x onerror=alert(1)>",
            connection_status="<b>fake</b>",
            external_ip="<script>x</script>",
            error_message="<i>err</i>",
        )
        self.widget._update_tooltip(sample, 10.0, 5.0)
        tip = self.widget.lbl_icon.toolTip()
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", tip)
        self.assertIn("&lt;b&gt;fake&lt;/b&gt;", tip)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", tip)
        self.assertIn("&lt;i&gt;err&lt;/i&gt;", tip)
        self.assertNotIn("<img", tip)
        self.assertNotIn("<script>", tip)

    def test_health_pills_themes_and_tooltip_escaping(self) -> None:
        """Verify 5-state health pills, monochrome/light theme awareness, DNS thresholds, and HTML escaping."""
        # 1. Standard theme: STABLE -> green
        s_stable = TrafficSample(
            is_connected=True,
            wan_connected=True,
            health=InternetHealthSnapshot(
                status=HealthStatus.STABLE,
                short_tag="Stabil",
                reason="Alles normal",
                gateway_ip="192.168.178.1",
                lan_ping_ms=0.7,
                ipv4_ok=True,
                ipv4_quorum=(2, 2),
                ipv4_ms=19.0,
                dns_ip="192.168.178.2",
                dns_ok=True,
                dns_ms=18.5,
                wan_median_ms=14.0,
                wan_p95_ms=17.0,
                wan_jitter_ms=1.1,
            ),
        )
        self.widget._update_wan_status_pill(s_stable)
        self.widget._update_dns_pill(s_stable)
        self.assertEqual(self.widget.lbl_wan_pill.text(), "✓ Stabil")
        self.assertIn("#00E676", self.widget.lbl_wan_pill.styleSheet())
        self.assertIn("✓ DNS", self.widget.lbl_dns_pill.text())
        self.assertIn("#00E676", self.widget.lbl_dns_pill.styleSheet())

        # Local fallback STABLE
        s_fallback = TrafficSample(
            is_connected=True,
            box_reachable=False,
            is_local_fallback=True,
            health=InternetHealthSnapshot(status=HealthStatus.STABLE, short_tag="Stabil"),
        )
        self.widget._update_wan_status_pill(s_fallback)
        self.assertEqual(self.widget.lbl_wan_pill.text(), "⚡ Lokal • OK")

        # 2. Monochrome theme: calm neutral STABLE pill instead of bright neon green
        self.widget.config.download_color = "#FFFFFF"
        self.widget.config.guest_download_color = "#B0BEC5"
        self.widget.config.title_color = "#ECEFF1"
        self.widget._update_wan_status_pill(s_stable)
        self.assertIn("#ECEFF1", self.widget.lbl_wan_pill.styleSheet())
        self.assertNotIn("#00E676", self.widget.lbl_wan_pill.styleSheet())

        # Light custom background uses high-contrast dark green
        self.widget.config.download_color = "#FFEA00"
        self.widget.config.guest_download_color = "#00E676"
        self.widget.config.background_color = "#F5F5F5"
        self.widget._update_wan_status_pill(s_stable)
        self.assertIn("#1B7F46", self.widget.lbl_wan_pill.styleSheet())
        self.widget.config.background_color = "#1C2428"

        # 3. Error & Degraded states
        for status, expected_text, expected_color in [
            (HealthStatus.ZOMBIE_WAN, "✕ Kein Internet", "#FF5252"),
            (HealthStatus.DNS_ERROR, "⚠ DNS-Störung", "#FF7043"),
            (HealthStatus.LAN_ERROR, "✕ LAN-Problem", "#BB86FC"),
            (HealthStatus.DEGRADED, "⚠ Nur IPv4", "#FFAB00"),
        ]:
            s = TrafficSample(
                is_connected=True,
                wan_connected=True,
                health=InternetHealthSnapshot(
                    status=status,
                    short_tag="Nur IPv4" if status == HealthStatus.DEGRADED else "Tag",
                    gateway_ip="192.168.178.1",
                ),
            )
            self.widget.resize(460, 300)
            self.widget._update_wan_status_pill(s)
            self.assertEqual(self.widget.lbl_wan_pill.text(), expected_text)
            self.assertIn(expected_color, self.widget.lbl_wan_pill.styleSheet())

        # 4. DNS Pill transition (150ms -> warning, failure -> DNS_ERROR)
        s_dns_slow = TrafficSample(
            health=InternetHealthSnapshot(status=HealthStatus.STABLE, dns_ip="192.168.178.2", dns_ok=True, dns_ms=150.0)
        )
        self.widget._update_dns_pill(s_dns_slow)
        self.assertIn("⚠ DNS", self.widget.lbl_dns_pill.text())
        self.assertIn("#FFAB00", self.widget.lbl_dns_pill.styleSheet())

        s_dns_fail = TrafficSample(
            health=InternetHealthSnapshot(status=HealthStatus.DNS_ERROR, dns_ip="192.168.178.2", dns_ok=False, dns_error="servfail")
        )
        self.widget._update_dns_pill(s_dns_fail)
        self.assertEqual(self.widget.lbl_dns_pill.text(), "✕ DNS: SERVFAIL")
        self.assertIn("#FF7043", self.widget.lbl_dns_pill.styleSheet())

        # 5. Tooltip scoping, separation (header vs pill), and HTML escaping
        self.assertIn("QToolTip {", self.widget.styleSheet())
        self.assertTrue(self.widget.lbl_wan_pill.styleSheet().startswith("QLabel {"))

        s_degraded = TrafficSample(
            is_connected=True,
            wan_connected=True,
            box_name="FRITZ!Box 7590",
            health=InternetHealthSnapshot(
                status=HealthStatus.DEGRADED,
                short_tag="Hoher Ping",
                reason="Hohe Latenz, Hoher Jitter (Leitung ausgelastet)",
                gateway_ip="192.168.178.1",
                lan_ping_ms=2.2,
                ipv4_ok=True,
                ipv4_quorum=(2, 2),
                ipv4_ms=24.0,
                ipv6_ok=True,
                ipv6_quorum=(2, 2),
                ipv6_ms=22.0,
                wan_p95_ms=70.0,
                wan_jitter_ms=23.1,
                wan_loss_pct=0.0,
                baseline_rtt_ms=13.0,
                baseline_ready=True,
                is_line_saturated=True,
            ),
        )
        self.widget._update_tooltip(s_degraded, 84.0, 25.0)
        hdr_tip = self.widget.lbl_icon.toolTip()
        pill_tip = self.widget.lbl_wan_pill.toolTip()
        self.assertIn("FRITZ!Box 7590", hdr_tip)
        self.assertNotIn("<b>Internet:</b>", hdr_tip)
        self.assertIn("<b>Internet:</b>", pill_tip)
        self.assertIn("(Leitung ausgelastet)", pill_tip)
        self.assertNotIn("FRITZ!Box 7590", pill_tip)
        self.assertNotIn("<hr", pill_tip)
        self.assertLessEqual(len(pill_tip.split("<br>")), 4)

        s_xss_dns = TrafficSample(
            is_connected=True,
            wan_connected=True,
            health=InternetHealthSnapshot(
                status=HealthStatus.DNS_ERROR,
                short_tag="DNS-Störung",
                reason="<script>alert(1)</script>",
                dns_ip="<b>dns</b>",
                dns_ok=False,
                dns_error="<i>err</i>",
            ),
        )
        self.widget._update_tooltip(s_xss_dns, 5.0, 2.0)
        tip_dns = self.widget.lbl_wan_pill.toolTip()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", tip_dns)
        self.assertIn("&lt;b&gt;dns&lt;/b&gt;", tip_dns)
        self.assertIn("&lt;i&gt;err&lt;/i&gt;", tip_dns)
        self.assertNotIn("<script>", tip_dns)

        s_xss_lan = TrafficSample(
            is_connected=False,
            wan_connected=False,
            health=InternetHealthSnapshot(
                status=HealthStatus.LAN_ERROR,
                short_tag="LAN-Problem",
                reason="Router tot",
                gateway_ip="<img src=x>",
            ),
        )
        self.widget._update_tooltip(s_xss_lan, 0.0, 0.0)
        tip_lan = self.widget.lbl_wan_pill.toolTip()
        self.assertIn("&lt;img src=x&gt;", tip_lan)
        self.assertNotIn("<img", tip_lan)


if __name__ == "__main__":
    unittest.main()
