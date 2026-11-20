"""Clickable status pill and detailed Internet Health diagnosis & advice dialog."""

from __future__ import annotations

from datetime import datetime
import html
from typing import Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QHideEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.api.internet_health import _format_dns_error
from src.api.models import HealthStatus, TrafficSample
from src.config import AppConfig
from src.ui.tray import create_router_icon

_STATUS_META: dict[HealthStatus, tuple[str, str]] = {
    HealthStatus.STABLE: ("Stabil", "#00E676"),
    HealthStatus.DEGRADED: ("Eingeschränkt", "#FFAB00"),
    HealthStatus.DNS_ERROR: ("DNS-Störung", "#FF7043"),
    HealthStatus.ZOMBIE_WAN: ("Verbindung hängt", "#FF5252"),
    HealthStatus.OFFLINE: ("Offline", "#FF5252"),
    HealthStatus.LAN_ERROR: ("LAN-Problem", "#BB86FC"),
    HealthStatus.UNKNOWN: ("Prüfe…", "#94A3B8"),
}


class ClickablePillLabel(QLabel):
    """QLabel subclass emitting clicked() on left-click without triggering parent window drag."""

    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            was_pressed = self._pressed
            self._pressed = False
            if was_pressed and self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def build_health_advice(sample: TrafficSample) -> tuple[str, list[str]]:
    """Build context-aware diagnosis headline and actionable improvement tips in German."""
    h = sample.health
    st = h.status

    if st == HealthStatus.STABLE:
        bullets = [
            "Heimnetz, HTTPS, DNS und Latenz liegen im normalen Bereich — kein Handlungsbedarf."
        ]
        if not h.baseline_ready:
            bullets.append(
                "Hinweis: Normalwert wird noch gelernt (ca. 15 s geringe Auslastung nötig)."
            )
        if not h.ipv6_available:
            bullets.append(
                "Info: Auf diesem Gerät ist aktuell nur IPv4 aktiv; IPv6 wird deshalb neutral übersprungen."
            )
        return "Verbindung läuft stabil – kein Handlungsbedarf", bullets

    if st == HealthStatus.DEGRADED:
        reason_l = h.reason.lower()
        tag_l = h.short_tag.lower()

        if h.is_line_saturated and ("latenz" in reason_l or "jitter" in reason_l or tag_l in ("hoher ping", "hoher jitter")):
            return (
                "Bufferbloat durch hohe Leitungsauslastung (meist keine ISP-Störung)",
                [
                    "Bei nahezu voller Down- oder Upload-Auslastung steigen Ping und Jitter technisch normal an — sobald der Transfer endet, normalisiert sich der Wert wieder.",
                    "Tipp 1: Im Router eine Priorisierung für Echtzeitanwendungen / Gaming bzw. VoIP aktivieren (z. B. FRITZ!Box: Internet → Filter → Priorisierung).",
                    "Tipp 2: Große Downloads, Cloud-Backups oder Updates bei Bedarf auf ca. 80–85 % der Leitungskapazität drosseln.",
                    "Tipp 3: Prüfen, ob ein anderes Gerät im Heimnetz den Upload komplett auslastet.",
                ],
            )

        if "latenz" in reason_l or "jitter" in reason_l or tag_l in ("hoher ping", "hoher jitter"):
            lan_hint = (
                f" (aktuell {h.lan_ping_ms:.1f} ms)".replace(".", ",")
                if h.lan_ping_ms is not None
                else ""
            )
            return (
                "Erhöhte Latenz oder Jitter trotz geringer Auslastung",
                [
                    f"Vergleiche Stufe 1 (LAN-Ping{lan_hint}) mit dem WAN-Ping:",
                    "Ist der LAN-Ping > 5–10 ms: WLAN-Funkkanal / 5-GHz-Band, Repeater-Strecke oder LAN-Kabel prüfen.",
                    "Ist der LAN-Ping sauber (< 2 ms): Ursache liegt meist im Provider-Segment oder Peering (lokal kaum behebbar; zu Stoßzeiten beobachten und bei Dauerproblem dem Anbieter melden).",
                ],
            )

        if "verlust" in reason_l or tag_l.startswith("verlust"):
            return (
                "Paketverlust auf der Verbindung",
                [
                    "Zuerst prüfen, ob oben bereits im Heimnetz (LAN-Verlust %) Pakete verloren gehen — falls ja, WLAN-Verbindung oder LAN-Kabel/Switch testen.",
                    "Bei 0 % LAN-Verlust: Fehlerzähler/Leitungswerte im Router sowie Anschlusskabel und TAE-/Koax-/Glasfaser-Stecker kontrollieren.",
                    "Bleibt der Paketverlust im Leerlauf dauerhaft bestehen, liegt wahrscheinlich eine Leitungsstörung beim Internetanbieter vor.",
                ],
            )

        if "ipv4" in reason_l or "ipv6" in reason_l or tag_l in ("nur ipv4", "nur ipv6"):
            return (
                "Teilausfall im Dual-Stack (nur ein IP-Protokoll erreichbar)",
                [
                    "Bei „Nur IPv6“ ist häufig das DS-Lite-/AFTR-Gateway des Providers überlastet — ein „Neu verbinden“ im Router hilft oft sofort.",
                    "Bei „Nur IPv4“ prüfen, ob im Router IPv6-Unterstützung & Präfix-Delegation aktiv sind oder der PC-Adapter IPv6 per VPN deaktiviert hat.",
                ],
            )

        if "dns" in reason_l or tag_l == "dns langsam":
            return (
                "Langsame DNS-Namensauflösung",
                [
                    "Upstream-DNS-Server im lokalen Resolver (z. B. AdGuard Home oder FRITZ!Box) prüfen und ggf. schnellere europäische DoT-/DoH-Server testen.",
                    "Bei lokalem AdGuard/Pi-hole prüfen, ob parallele Upstream-Abfragen aktiviert sind und das Host-System nicht ausgelastet ist.",
                ],
            )

        return (
            "Verbindungsqualität vorübergehend eingeschränkt",
            [
                "Messwerte weichen leicht vom Normalbereich ab — über „Jetzt prüfen“ direkt erneut testen."
            ],
        )

    if st == HealthStatus.DNS_ERROR:
        dns_lbl = h.dns_ip or "System-DNS"
        return (
            "Internet per IP erreichbar – lokaler DNS-Server gestört",
            [
                f"Der direkte HTTPS-Check ins Internet funktioniert, aber der aktive DNS ({dns_lbl}) liefert Fehler oder antwortet nicht.",
                "Tipp 1: Lokalen DNS-Dienst (z. B. AdGuard Home / Pi-hole / Unbound) auf Erreichbarkeit prüfen und ggf. neu starten.",
                "Tipp 2: Upstream-Resolver in AdGuard/Router sowie korrekte Systemuhrzeit prüfen (wichtig für DNSSEC & verschlüsseltes DoT/DoH).",
                "Tipp 3: Falls nötig, im Router oder auf dem PC vorübergehend einen alternativen Fallback-DNS testen.",
            ],
        )

    if st == HealthStatus.ZOMBIE_WAN:
        return (
            "Kein Internet trotz aktiver Router-Verbindung",
            [
                "Die FRITZ!Box meldet zwar „Verbunden“, es kommen aber keine Internet-Daten durch.",
                "Tipp 1: In der Router-Oberfläche „Neu verbinden“ auslösen.",
                "Tipp 2: Falls das nicht hilft, Router/Modem ca. 30 Sekunden vom Strom trennen.",
                "Tipp 3: Bei häufigem Auftreten Ereignislog sichern und dem Anbieter melden.",
            ],
        )

    if st == HealthStatus.OFFLINE:
        if h.captive_portal_detected:
            return (
                "Captive Portal / WLAN-Anmeldung erforderlich",
                [
                    "HTTPS-Anfragen werden umgeleitet — vermutlich ist in diesem WLAN/Hotspot noch eine Anmeldung oder AGB-Bestätigung im Browser nötig."
                ],
            )
        if sample.box_reachable and not sample.is_local_fallback and not sample.physical_link_up:
            return (
                "Kein DSL-/Kabel-/Glasfaser-Sync am Router",
                [
                    "Der Router hat aktuell keine physikalische Verbindung zum Netz des Anbieters.",
                    "Tipp 1: Anschlusskabel zwischen Router/Modem und Wanddose auf festen Sitz prüfen.",
                    "Tipp 2: Power-/DSL-/Cable-LED am Router kontrollieren und bei Bedarf eine bekannte Netzstörung beim Anbieter prüfen.",
                ],
            )
        return (
            "Keine Internetverbindung",
            [
                "Der Router bzw. das Netz hat aktuell keinen funktionierenden Internetzugang.",
                "Tipp 1: Verbindungsstatus im Router prüfen und ggf. „Neu verbinden“ oder einen Router-Neustart durchführen.",
                "Tipp 2: Prüfen, ob eine Wartung oder Großstörung beim Internetanbieter vorliegt.",
            ],
        )

    if st == HealthStatus.LAN_ERROR:
        return (
            "Lokales Netzwerkproblem (Router/Gateway nicht erreichbar)",
            [
                "Das Problem liegt im Heimnetz, nicht beim Internetanbieter.",
                "Tipp 1: WLAN-Verbindung, LAN-Kabel, Switch oder Powerline/Repeater zwischen PC und Router prüfen.",
                "Tipp 2: Prüfen, ob der Router Strom hat oder gerade neu startet.",
                "Tipp 3: Aktive VPN-Clients oder strikte lokale Firewall-Regeln testen, die Gateway-/LAN-Verkehr blockieren könnten.",
            ],
        )

    return (
        "Erste Verbindungsprüfung läuft",
        [
            "TrafficBox sammelt gerade die ersten End-to-End-Messwerte (dauert nur wenige Sekunden).",
            "Falls dieser Status dauerhaft bleibt, prüfe in den Diagnose-Einstellungen, ob die aktive Internet-Erreichbarkeit aktiviert ist.",
        ],
    )


class InternetHealthDialog(QDialog):
    """Non-modal live diagnosis dialog showing multi-stage metrics, legend, and tips."""

    def __init__(
        self,
        config: AppConfig,
        *,
        on_recheck: Callable[[], None] | None = None,
        on_open_settings: Callable[[], None] | None = None,
        parent: QWidget | None = None,
        initial_tab: int = 0,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._on_recheck = on_recheck
        self._on_open_settings = on_open_settings
        self._last_icon_col = ""
        self._recheck_timer = QTimer(self)
        self._recheck_timer.setSingleShot(True)
        self._recheck_timer.timeout.connect(self._restore_recheck_button)

        self.setWindowTitle("TrafficBox – Internet-Diagnose & Status")
        self.setWindowIcon(create_router_icon(True))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(480, 420)

        self._apply_dialog_stylesheet()
        self._build_ui()
        self._restore_geometry()

        if 0 <= initial_tab < self.tabs.count():
            self.tabs.setCurrentIndex(initial_tab)

    def _restore_geometry(self) -> None:
        """Restore window position and size from config if visible on current screens."""
        cfg_w = max(480, self.config.health_width)
        cfg_h = max(420, self.config.health_height)
        self.resize(cfg_w, cfg_h)

        if self.config.health_pos_x != -1 or self.config.health_pos_y != -1:
            target_pt = QPoint(self.config.health_pos_x, self.config.health_pos_y)
            target_rect = QRect(target_pt, QSize(cfg_w, cfg_h))
            for screen in QApplication.screens():
                if screen.availableGeometry().intersects(target_rect):
                    self.move(target_pt)
                    return

        primary = QApplication.primaryScreen()
        if primary:
            avail = primary.availableGeometry()
            x = avail.x() + max(0, (avail.width() - cfg_w) // 2)
            y = avail.y() + max(0, (avail.height() - cfg_h) // 2)
            self.move(x, y)

    def _save_geometry_to_config(self) -> None:
        """Store current dialog position and size in config."""
        self.config.health_pos_x = self.x()
        self.config.health_pos_y = self.y()
        self.config.health_width = self.width()
        self.config.health_height = self.height()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_geometry_to_config()
        self.config.save()
        super().closeEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self._save_geometry_to_config()
        super().hideEvent(event)

    def accept(self) -> None:
        self._save_geometry_to_config()
        self.config.save()
        super().accept()

    def reject(self) -> None:
        self._save_geometry_to_config()
        self.config.save()
        super().reject()

    def _apply_dialog_stylesheet(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background-color: #161B22;
                color: #E2E8F0;
            }
            QTabWidget::pane {
                border: 1px solid #2D3748;
                border-radius: 6px;
                background-color: #1A2029;
            }
            QTabBar::tab {
                background-color: #1E2631;
                color: #94A3B8;
                border: 1px solid #2D3748;
                border-bottom: none;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                padding: 6px 12px;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                background-color: #1A2029;
                color: #F8FAFC;
                font-weight: bold;
            }
            QGroupBox {
                border: 1px solid #2D3748;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 8px;
                font-weight: bold;
                color: #CBD5E1;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLabel {
                color: #E2E8F0;
            }
            QPushButton {
                background-color: #242D3A;
                color: #E2E8F0;
                border: 1px solid #3B4656;
                border-radius: 5px;
                padding: 5px 11px;
            }
            QPushButton:hover {
                background-color: #2E394A;
                border-color: #60A5FA;
            }
            QPushButton:disabled {
                color: #64748B;
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
            """
        )

    @staticmethod
    def _wrap_in_scroll(widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(widget)
        return scroll

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        # --- TAB 1: Aktuelle Diagnose ---
        tab_live = QWidget()
        live_layout = QVBoxLayout(tab_live)
        live_layout.setContentsMargins(10, 10, 10, 10)
        live_layout.setSpacing(8)

        # Status Banner
        self.banner_frame = QFrame()
        self.banner_frame.setObjectName("HealthBanner")
        banner_layout = QVBoxLayout(self.banner_frame)
        banner_layout.setContentsMargins(12, 9, 12, 9)
        banner_layout.setSpacing(4)

        top_banner_row = QHBoxLayout()
        self.lbl_status_title = QLabel("Prüfe…")
        self.lbl_status_title.setStyleSheet("font-size: 11.5pt; font-weight: bold;")
        self.lbl_probe_meta = QLabel("Ausstehend")
        self.lbl_probe_meta.setStyleSheet("color: #94A3B8; font-size: 8pt;")
        self.lbl_probe_meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top_banner_row.addWidget(self.lbl_status_title, 1)
        top_banner_row.addWidget(self.lbl_probe_meta, 0)

        self.lbl_status_reason = QLabel("Erste Verbindungsprüfung läuft…")
        self.lbl_status_reason.setWordWrap(True)
        self.lbl_status_reason.setStyleSheet("color: #CBD5E1; font-size: 9pt;")

        banner_layout.addLayout(top_banner_row)
        banner_layout.addWidget(self.lbl_status_reason)
        live_layout.addWidget(self.banner_frame)

        # Stages Overview
        stages_group = QGroupBox("Messstufen (Live)")
        stages_form = QFormLayout(stages_group)
        stages_form.setContentsMargins(10, 10, 10, 10)
        stages_form.setVerticalSpacing(6)
        stages_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.lbl_stage_lan = QLabel("-")
        self.lbl_stage_https = QLabel("-")
        self.lbl_stage_dns = QLabel("-")
        self.lbl_stage_quality = QLabel("-")
        for lbl in (
            self.lbl_stage_lan,
            self.lbl_stage_https,
            self.lbl_stage_dns,
            self.lbl_stage_quality,
        ):
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.TextFormat.PlainText)

        stages_form.addRow("1. Heimnetz / Router:", self.lbl_stage_lan)
        stages_form.addRow("2. Internet (HTTPS 204):", self.lbl_stage_https)
        stages_form.addRow("3. DNS (Uncached):", self.lbl_stage_dns)
        stages_form.addRow("4. Qualität (Live 15s):", self.lbl_stage_quality)
        live_layout.addWidget(stages_group)

        # Advice & Tips
        advice_group = QGroupBox("Einschätzung & Handlungstipps")
        advice_layout = QVBoxLayout(advice_group)
        advice_layout.setContentsMargins(10, 10, 10, 10)
        advice_layout.setSpacing(6)

        self.lbl_advice_headline = QLabel("")
        self.lbl_advice_headline.setWordWrap(True)
        self.lbl_advice_headline.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_advice_headline.setStyleSheet("font-weight: bold; font-size: 9.5pt; color: #F8FAFC;")

        self.lbl_advice_body = QLabel("")
        self.lbl_advice_body.setWordWrap(True)
        self.lbl_advice_body.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_advice_body.setStyleSheet("color: #CBD5E1; font-size: 8.8pt;")

        advice_layout.addWidget(self.lbl_advice_headline)
        advice_layout.addWidget(self.lbl_advice_body)
        live_layout.addWidget(advice_group)
        live_layout.addStretch(1)

        self.tabs.addTab(self._wrap_in_scroll(tab_live), "Aktuelle Diagnose")

        # --- TAB 2: Status-Erklärung & Legende ---
        tab_legend = self._build_legend_tab()
        self.tabs.addTab(self._wrap_in_scroll(tab_legend), "Status-Erklärung && Legende")

        # --- Bottom Action Buttons ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_recheck = QPushButton("🔄 Jetzt prüfen")
        self.btn_recheck.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_recheck.clicked.connect(self._handle_recheck_clicked)

        self.btn_settings = QPushButton("⚙ Diagnose-Einstellungen...")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self._handle_settings_clicked)

        self.btn_close = QPushButton("Schließen")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(self.close)

        btn_row.addWidget(self.btn_recheck)
        btn_row.addWidget(self.btn_settings)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

    def _build_legend_tab(self) -> QWidget:
        """Build the static reference tab explaining all 5 statuses and measurement logic."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        cards = [
            (
                "#00E676",
                "🟢 Stabil",
                "Heimnetz ok, HTTPS-204-Quorum ok (IPv4 + ggf. IPv6), Uncached-DNS ≤ 200 ms, Latenz/Jitter im gelernten Korridor, kein aktueller Verlust.",
                "Internet funktioniert normal.",
                "Alles in Ordnung.",
            ),
            (
                "#FFAB00",
                "🟡 Eingeschränkt",
                "Internet erreichbar, aber Verlust (≥ 2 Drops), p85-Latenz/Jitter > 2,5× Ruhe-Basis, DNS > 200 ms oder Dual-Stack-Teilausfall (nur IPv4 / nur IPv6).",
                "Leitung nutzbar, aber gebremst oder einseitig gestört.",
                "Oft Bufferbloat bei Downloads, WLAN-Schwankung oder hängendes DS-Lite-/IPv6-Gateway.",
            ),
            (
                "#FF7043",
                "🟠 DNS-Störung",
                "HTTPS-Tests ins Internet ok, aber direkte DNS-Anfrage (ohne Cache) schlägt fehl oder wird umgeleitet.",
                "Internet funktioniert, aber Domainnamen werden nicht mehr frisch aufgelöst.",
                "Gestörter lokaler DNS-Dienst (AdGuard/Pi-hole), Upstream-Resolver oder falsche Systemzeit.",
            ),
            (
                "#FF5252",
                "🔴 Offline / Verbindung hängt",
                "Heimnetz ok, aber alle HTTPS-Verbindungstests (Cloudflare & Google) scheitern oder > 20 % Verlust.",
                "Kein Internetverkehr möglich (auch wenn die FRITZ!Box noch „Verbunden“ meldet).",
                "Hängende Provider-Session, fehlender Router-Sync, Anmeldeportal (Captive Portal) oder Netzausfall.",
            ),
            (
                "#BB86FC",
                "🟣 LAN-Problem",
                "Router/Gateway per UPnP & Ping nicht erreichbar oder > 10 % Paketverlust bereits bis zum Gateway.",
                "Störung liegt im lokalen Heimnetz, nicht beim Internetanbieter.",
                "Abgebrochenes WLAN, defektes LAN-Kabel, hängender Switch/Repeater oder blockierende VPN-/Firewall-Regel.",
            ),
        ]

        for accent, title, cond, meaning, cause in cards:
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background-color: #1E2530; border: 1px solid #2D3748; "
                f"border-left: 4px solid {accent}; border-radius: 5px; }}"
            )
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(10, 7, 10, 7)
            c_layout.setSpacing(3)

            lbl_t = QLabel(title)
            lbl_t.setStyleSheet(f"color: {accent}; font-weight: bold; font-size: 9.5pt; border: none;")
            lbl_body = QLabel(
                f"<b>Bedingung:</b> {html.escape(cond)}<br>"
                f"<b>Bedeutung:</b> {html.escape(meaning)}<br>"
                f"<b>Typische Ursache:</b> {html.escape(cause)}"
            )
            lbl_body.setWordWrap(True)
            lbl_body.setTextFormat(Qt.TextFormat.RichText)
            lbl_body.setStyleSheet("color: #CBD5E1; font-size: 8.4pt; border: none;")

            c_layout.addWidget(lbl_t)
            c_layout.addWidget(lbl_body)
            layout.addWidget(card)

        how_group = QGroupBox("Wie TrafficBox misst")
        how_layout = QVBoxLayout(how_group)
        how_layout.setContentsMargins(10, 8, 10, 8)
        lbl_how = QLabel(
            "• <b>Dual-Stack HTTPS (204):</b> Prüft 2 unabhängige Ziele (Cloudflare & Google) — ein einzelnes Ziel löst keinen Alarm aus.<br>"
            "• <b>Direkte DNS-Prüfung:</b> Fragt Zufalls-Subdomains ab (30 s / 5 s bei Störung), um lokale DNS-Caches zu umgehen.<br>"
            "• <b>Live-Verlauf & Normalwert:</b> Lernt die Ruhe-Latenz bei geringer Last (&lt; 40 %) und erholt sich nach Downloads in ca. 15–20 s.<br>"
            "• <b>Verzögerter Alarm:</b> Erst nach 2 Fehlversuchen, um kurze Einzel-Aussetzer abzufangen."
        )
        lbl_how.setWordWrap(True)
        lbl_how.setTextFormat(Qt.TextFormat.RichText)
        lbl_how.setStyleSheet("color: #CBD5E1; font-size: 8.4pt;")
        how_layout.addWidget(lbl_how)
        layout.addWidget(how_group)
        layout.addStretch(1)
        return tab

    def _handle_recheck_clicked(self) -> None:
        self.btn_recheck.setEnabled(False)
        self.btn_recheck.setText("⏳ Prüfe…")
        if self._on_recheck is not None:
            self._on_recheck()
        self._recheck_timer.start(1500)

    def _restore_recheck_button(self) -> None:
        self.btn_recheck.setEnabled(True)
        self.btn_recheck.setText("🔄 Jetzt prüfen")

    def _handle_settings_clicked(self) -> None:
        if self._on_open_settings is not None:
            self._on_open_settings()

    def update_from_sample(self, sample: TrafficSample, down_pct: float = 0.0, up_pct: float = 0.0) -> None:
        """Refresh live banner, measurement stages, and contextual tips from a TrafficSample."""
        h = sample.health
        st = h.status
        status_name, status_col = _STATUS_META.get(st, ("Unbekannt", "#94A3B8"))

        if status_col != self._last_icon_col:
            self._last_icon_col = status_col
            self.setWindowIcon(create_router_icon(sample.is_connected, status_color=status_col))

        self.banner_frame.setStyleSheet(
            f"QFrame#HealthBanner {{ background-color: #1E2530; border: 1px solid #2D3748; "
            f"border-left: 4px solid {status_col}; border-radius: 6px; }}"
        )
        self.lbl_status_title.setText(status_name)
        self.lbl_status_title.setStyleSheet(f"color: {status_col}; font-size: 11.5pt; font-weight: bold;")

        if h.last_probe_ts > 0:
            ts_str = datetime.fromtimestamp(h.last_probe_ts).strftime("%H:%M:%S")
            mode_str = "Schnellprüfung (5 s)" if h.in_burst_mode else f"Normal ({self.config.health_probe_interval_sec} s)"
            self.lbl_probe_meta.setText(f"Zuletzt geprüft: {ts_str} • {mode_str}")
        else:
            self.lbl_probe_meta.setText("Ausstehend…")

        if not self.config.enable_internet_health:
            self.lbl_status_reason.setText("Aktive Internet-Erreichbarkeitsprüfung ist in den Einstellungen deaktiviert.")
        else:
            self.lbl_status_reason.setText(h.reason or "Erste Verbindungsprüfung läuft…")

        # 1. LAN / Router
        gw_txt = h.gateway_ip or "-"
        lan_rtt = f"{h.lan_ping_ms:.1f} ms".replace(".", ",") if h.lan_ping_ms is not None else "n/a"
        if sample.is_local_fallback:
            router_state = "Lokal-Fallback (ohne Box)"
        elif not sample.box_reachable:
            router_state = "UPnP nicht erreichbar"
        elif not sample.physical_link_up:
            router_state = "Kein DSL-/WAN-Sync"
        elif not sample.wan_connected:
            router_state = "Sync OK, WAN getrennt"
        else:
            router_state = "UPnP & Sync OK"
        lan_loss = f" • Verlust: {h.lan_loss_pct:.0f} %" if h.lan_loss_pct > 0 else ""
        self.lbl_stage_lan.setText(f"Gateway {gw_txt} • Ping: {lan_rtt}{lan_loss} • {router_state}")

        # 2. Dual-Stack HTTPS 204
        v4_ok, v4_tot = h.ipv4_quorum
        if v4_tot > 0:
            v4_rtt = f" ({h.ipv4_ms:.0f} ms)" if (h.ipv4_ok and h.ipv4_ms is not None) else ""
            v4_txt = f"IPv4 {v4_ok}/{v4_tot}{v4_rtt}" if h.ipv4_ok else f"IPv4 Fehler (0/{v4_tot})"
        else:
            v4_txt = "IPv4 ausstehend"

        v6_ok, v6_tot = h.ipv6_quorum
        if v6_tot > 0:
            v6_rtt = f" ({h.ipv6_ms:.0f} ms)" if (h.ipv6_ok and h.ipv6_ms is not None) else ""
            v6_txt = f"IPv6 {v6_ok}/{v6_tot}{v6_rtt}" if h.ipv6_ok else f"IPv6 Fehler (0/{v6_tot})"
        elif self.config.health_ip_mode == "ipv4_only":
            v6_txt = "IPv6 deaktiviert (nur IPv4)"
        else:
            v6_txt = "IPv6 nicht aktiv (nur IPv4)"
        portal_txt = " • Captive Portal erkannt!" if h.captive_portal_detected else ""
        self.lbl_stage_https.setText(f"{v4_txt}  •  {v6_txt}{portal_txt}")

        # 3. Uncached DNS
        if not self.config.enable_dns_monitor:
            self.lbl_stage_dns.setText("DNS-Überwachung deaktiviert")
        elif not self.config.health_uncached_dns:
            d_ip = sample.active_dns_ip or "-"
            d_ms = f"{sample.dns_ms:.1f} ms".replace(".", ",") if sample.dns_ms is not None else "n/a"
            self.lbl_stage_dns.setText(f"Server {d_ip} • Standard-Check: {d_ms}")
        elif h.dns_ok is None:
            self.lbl_stage_dns.setText("Warte auf erste DNS-Prüfung…")
        elif h.dns_ok:
            d_ms = f"{h.dns_ms:.1f} ms".replace(".", ",") if h.dns_ms is not None else "-"
            self.lbl_stage_dns.setText(f"Server {h.dns_ip or '-'} • {d_ms} (ohne Cache)")
        else:
            d_err = _format_dns_error(h.dns_error)
            self.lbl_stage_dns.setText(f"Server {h.dns_ip or '-'} • Gestört ({d_err})")

        # 4. Quality 15s / Baseline / Utilization
        p85_s = f"{h.wan_p95_ms:.0f} ms" if h.wan_p95_ms is not None else "-"
        med_s = f"{h.wan_median_ms:.1f} ms".replace(".", ",") if h.wan_median_ms is not None else "-"
        jit_s = f"{h.wan_jitter_ms:.1f} ms".replace(".", ",")
        loss_s = f"{h.wan_loss_pct:.0f} %"
        if h.baseline_ready and h.baseline_rtt_ms is not None:
            b_jit = f"{h.baseline_jitter_ms:.1f}".replace(".", ",") if h.baseline_jitter_ms is not None else "-"
            base_s = f"{h.baseline_rtt_ms:.0f} ms / {b_jit} ms"
        else:
            base_s = "Lernphase…"
        load_s = f"Down {down_pct:.0f}% • Up {up_pct:.0f}%".replace(".", ",")
        self.lbl_stage_quality.setText(
            f"p85: {p85_s} • Med: {med_s} • Jitter: {jit_s} • Loss: {loss_s}\n"
            f"Normalwert: {base_s} • Auslastung: {load_s}"
        )

        # Advice & Tips
        headline, bullets = build_health_advice(sample)
        self.lbl_advice_headline.setText(headline)
        html_bullets = "<br>".join(f"• {html.escape(line)}" for line in bullets)
        self.lbl_advice_body.setText(html_bullets)
