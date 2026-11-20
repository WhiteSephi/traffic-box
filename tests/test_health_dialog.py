"""Unit tests for ClickablePillLabel, InternetHealthDialog, and build_health_advice."""

from __future__ import annotations

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from src.api.internet_health import InternetHealthMonitor
from src.api.models import HealthStatus, InternetHealthSnapshot, TrafficSample
from src.api.net_health import DnsQueryResult, HttpsCanaryResult, set_shutting_down
from src.config import AppConfig
from src.ui.health_dialog import ClickablePillLabel, InternetHealthDialog, build_health_advice
from src.ui.widget import TrafficBox

_app = QApplication.instance() or QApplication(sys.argv)


class TestBuildHealthAdvice(unittest.TestCase):
    """Verify context-aware diagnosis headlines and actionable tips for every state."""

    def test_advice_covers_all_health_states(self) -> None:
        # 1. STABLE
        h_ok, b_ok = build_health_advice(
            TrafficSample(health=InternetHealthSnapshot(status=HealthStatus.STABLE, baseline_ready=True, ipv6_available=True))
        )
        self.assertIn("stabil", h_ok.lower())
        self.assertTrue(any("kein handlungsbedarf" in x.lower() for x in b_ok))

        # 2. DEGRADED - Bufferbloat under high utilization
        h_bb, b_bb = build_health_advice(
            TrafficSample(
                health=InternetHealthSnapshot(
                    status=HealthStatus.DEGRADED,
                    short_tag="Hoher Ping",
                    reason="Hohe Latenz (Leitung ausgelastet)",
                    is_line_saturated=True,
                )
            )
        )
        self.assertIn("Bufferbloat", h_bb)
        self.assertTrue(any("Priorisierung" in x for x in b_bb))

        # 3. DEGRADED - High latency/jitter at idle
        h_idle, b_idle = build_health_advice(
            TrafficSample(
                health=InternetHealthSnapshot(
                    status=HealthStatus.DEGRADED,
                    short_tag="Hoher Ping",
                    reason="Hohe Latenz",
                    is_line_saturated=False,
                    lan_ping_ms=1.1,
                )
            )
        )
        self.assertIn("geringer Auslastung", h_idle)
        self.assertTrue(any("LAN-Ping" in x for x in b_idle))

        # 4. DEGRADED - Packet loss
        h_loss, b_loss = build_health_advice(
            TrafficSample(health=InternetHealthSnapshot(status=HealthStatus.DEGRADED, short_tag="Verlust 5%", reason="Paketverlust 5 %"))
        )
        self.assertIn("Paketverlust", h_loss)

        # 5. DEGRADED - Dual-Stack partial outage
        h_ds, b_ds = build_health_advice(
            TrafficSample(health=InternetHealthSnapshot(status=HealthStatus.DEGRADED, short_tag="Nur IPv4", reason="IPv6 gestört (nur IPv4)"))
        )
        self.assertIn("Dual-Stack", h_ds)

        # 6. DEGRADED - Slow DNS
        h_dns_slow, _ = build_health_advice(
            TrafficSample(health=InternetHealthSnapshot(status=HealthStatus.DEGRADED, short_tag="DNS langsam", reason="DNS langsam (240 ms)"))
        )
        self.assertIn("DNS", h_dns_slow)

        # 7. DNS_ERROR
        h_dns_err, b_dns_err = build_health_advice(
            TrafficSample(health=InternetHealthSnapshot(status=HealthStatus.DNS_ERROR, dns_ip="192.168.178.2", dns_error="servfail"))
        )
        self.assertIn("lokaler DNS", h_dns_err)
        self.assertTrue(any("AdGuard" in x for x in b_dns_err))

        # 8. ZOMBIE_WAN
        h_zmb, b_zmb = build_health_advice(
            TrafficSample(health=InternetHealthSnapshot(status=HealthStatus.ZOMBIE_WAN))
        )
        self.assertIn("Kein Internet", h_zmb)
        self.assertTrue(any("Neu verbinden" in x for x in b_zmb))

        # 9. OFFLINE variants (Captive Portal, No Sync, Generic)
        h_cap, _ = build_health_advice(
            TrafficSample(health=InternetHealthSnapshot(status=HealthStatus.OFFLINE, captive_portal_detected=True))
        )
        self.assertIn("Captive Portal", h_cap)

        h_sync, _ = build_health_advice(
            TrafficSample(box_reachable=True, physical_link_up=False, health=InternetHealthSnapshot(status=HealthStatus.OFFLINE))
        )
        self.assertIn("Sync", h_sync)

        h_off, _ = build_health_advice(
            TrafficSample(box_reachable=True, physical_link_up=True, wan_connected=False, health=InternetHealthSnapshot(status=HealthStatus.OFFLINE))
        )
        self.assertIn("Keine Internetverbindung", h_off)

        # 10. LAN_ERROR & UNKNOWN
        h_lan, b_lan = build_health_advice(
            TrafficSample(health=InternetHealthSnapshot(status=HealthStatus.LAN_ERROR))
        )
        self.assertIn("Lokales Netzwerkproblem", h_lan)
        self.assertTrue(any("Heimnetz" in x for x in b_lan))

        h_unk, _ = build_health_advice(TrafficSample())
        self.assertIn("Erste Verbindungsprüfung", h_unk)


class TestInternetHealthDialogAndPill(unittest.TestCase):
    """Verify InternetHealthDialog UI, live updates, HTML escaping, and clickable footer pills."""

    def setUp(self) -> None:
        set_shutting_down(False)
        self.config = AppConfig()
        self.config.save = MagicMock()  # type: ignore[method-assign]

    def tearDown(self) -> None:
        set_shutting_down(False)

    def test_dialog_live_update_tabs_callbacks_and_escaping(self) -> None:
        recheck_cb = MagicMock()
        settings_cb = MagicMock()
        dlg = InternetHealthDialog(
            self.config,
            on_recheck=recheck_cb,
            on_open_settings=settings_cb,
        )
        try:
            self.assertTrue(bool(dlg.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
            self.assertEqual(dlg.tabs.count(), 2)
            self.assertEqual(dlg.tabs.tabText(0), "Aktuelle Diagnose")
            self.assertEqual(dlg.tabs.tabText(1), "Status-Erklärung && Legende")

            sample = TrafficSample(
                is_connected=True,
                wan_connected=True,
                health=InternetHealthSnapshot(
                    status=HealthStatus.DNS_ERROR,
                    short_tag="DNS-Störung",
                    reason="<script>alert(1)</script>",
                    gateway_ip="192.168.178.1",
                    lan_ping_ms=1.2,
                    ipv4_ok=True,
                    ipv4_quorum=(2, 2),
                    ipv4_ms=19.0,
                    dns_ip="<img src=x>",
                    dns_ok=False,
                    dns_error="servfail",
                    wan_median_ms=13.0,
                    wan_p95_ms=16.0,
                    wan_jitter_ms=0.9,
                    baseline_rtt_ms=12.0,
                    baseline_jitter_ms=0.6,
                    baseline_ready=True,
                    in_burst_mode=True,
                    last_probe_ts=1_700_000_000.0,
                ),
            )
            dlg.update_from_sample(sample, down_pct=15.0, up_pct=5.0)
            self.assertEqual(dlg.lbl_status_title.text(), "DNS-Störung")
            self.assertIn("Schnellprüfung (5 s)", dlg.lbl_probe_meta.text())
            self.assertIn("192.168.178.1", dlg.lbl_stage_lan.text())
            self.assertIn("IPv4 2/2", dlg.lbl_stage_https.text())
            self.assertIn("SERVFAIL", dlg.lbl_stage_dns.text())
            # RichText advice label must escape HTML from dynamic dns_ip
            self.assertIn("&lt;img src=x&gt;", dlg.lbl_advice_body.text())
            self.assertNotIn("<img", dlg.lbl_advice_body.text())

            dlg.btn_recheck.click()
            recheck_cb.assert_called_once()
            self.assertFalse(dlg.btn_recheck.isEnabled())

            dlg.btn_settings.click()
            settings_cb.assert_called_once()

            # Geometry persistence on move/resize/close
            dlg.move(220, 180)
            dlg.resize(600, 560)
            dlg.close()
            self.assertEqual(self.config.health_pos_x, 220)
            self.assertEqual(self.config.health_pos_y, 180)
            self.assertEqual(self.config.health_width, 600)
            self.assertEqual(self.config.health_height, 560)
            self.config.save.assert_called()
        finally:
            dlg.close()
            dlg.deleteLater()

        # Re-opening restores saved position and size
        dlg2 = InternetHealthDialog(self.config)
        try:
            self.assertEqual(dlg2.x(), 220)
            self.assertEqual(dlg2.y(), 180)
            self.assertEqual(dlg2.width(), 600)
            self.assertEqual(dlg2.height(), 560)
        finally:
            dlg2.close()
            dlg2.deleteLater()

    def test_clickable_pill_opens_health_dialog_and_context_menu_entry(self) -> None:
        widget = TrafficBox(self.config)
        try:
            self.assertIsInstance(widget.lbl_wan_pill, ClickablePillLabel)
            self.assertIsInstance(widget.lbl_dns_pill, ClickablePillLabel)

            # Context menu contains new Internet-Diagnose & Details... entry
            menu = widget._build_context_menu()
            titles = [a.text() for a in menu.actions()]
            self.assertIn("Internet-Diagnose && Details...", titles)

            # Simulate real mouse press + release on lbl_wan_pill
            widget.show()
            _app.processEvents()
            pos = QPointF(4.0, 4.0)
            press = QMouseEvent(
                QMouseEvent.Type.MouseButtonPress,
                pos,
                pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            release = QMouseEvent(
                QMouseEvent.Type.MouseButtonRelease,
                pos,
                pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
            widget.lbl_wan_pill.mousePressEvent(press)
            widget.lbl_wan_pill.mouseReleaseEvent(release)
            _app.processEvents()

            self.assertIsNotNone(widget._health_dlg)
            self.assertTrue(widget._health_dlg.isVisible())

            # Clicking DNS pill focuses existing dialog without duplicating it
            first_dlg = widget._health_dlg
            widget.lbl_dns_pill.clicked.emit()
            _app.processEvents()
            self.assertIs(widget._health_dlg, first_dlg)
        finally:
            widget._stop_background_tasks(save_state=False)
            set_shutting_down(False)
            widget.deleteLater()

    def test_trigger_probe_now_runs_immediately(self) -> None:
        done = threading.Event()

        def fake_canary(connect_ip: str, server_hostname: str, **kwargs) -> HttpsCanaryResult:
            done.set()
            return HttpsCanaryResult(ok=True, latency_ms=15.0, status_code=204)

        mon = InternetHealthMonitor(
            probe_interval_sec=120,
            ping_fn=lambda host: 1.0,
            dns_fn=lambda srv: DnsQueryResult(ok=True, latency_ms=12.0, rcode=3),
            detect_dns_fn=lambda: "192.168.178.2",
            canary_fn=fake_canary,
            ipv6_fn=lambda: False,
            resolve_fn=lambda host, fam: "198.51.100.1",
            gateway_fn=lambda: "192.168.178.1",
        )
        try:
            started = mon.trigger_probe_now()
            self.assertTrue(started)
            self.assertTrue(done.wait(timeout=2.0))
            if mon._probe_thread is not None:
                mon._probe_thread.join(timeout=1.0)
            self.assertEqual(mon.get_snapshot().status, HealthStatus.STABLE)
        finally:
            mon.stop()


if __name__ == "__main__":
    unittest.main()
