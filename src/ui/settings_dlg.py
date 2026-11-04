"""Settings dialog for configuring the TrafficBox Widget."""

from __future__ import annotations

from typing import Callable
import urllib.request

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.api.fritz_monitor import FritzGuestMonitorClient
from src.api.upnp_client import FritzUpnpClient
from src.autostart import is_autostart_enabled, set_autostart
from src.config import AppConfig


class ColorButton(QPushButton):
    """Button that displays and selects a hex color."""

    def __init__(self, hex_color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = hex_color
        self.setFixedHeight(26)
        self.setMinimumWidth(110)
        self._update_style()
        self.clicked.connect(self._pick_color)

    @property
    def hex_color(self) -> str:
        return self._color

    @hex_color.setter
    def hex_color(self, value: str) -> None:
        self._color = value
        self._update_style()

    def _update_style(self) -> None:
        qcol = QColor(self._color)
        luminance = 0.299 * qcol.red() + 0.587 * qcol.green() + 0.114 * qcol.blue()
        text_col = "#111111" if luminance > 140 else "#F5F5F5"
        self.setText(self._color.upper())
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._color}; color: {text_col}; "
            "border: 1px solid #666; border-radius: 4px; font-weight: bold; }}"
        )

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, "Farbe wählen")
        if chosen.isValid():
            self.hex_color = chosen.name()


class SettingsDialog(QDialog):
    """Comprehensive settings window for TrafficBox with modern tabs."""

    def __init__(
        self,
        config: AppConfig,
        on_apply: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.on_apply = on_apply

        self.setWindowTitle("TrafficBox Einstellungen")
        self.setMinimumWidth(480)
        self._build_ui()
        self._load_from_config()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)

        tabs = QTabWidget(self)
        root_layout.addWidget(tabs)

        # --- TAB 1: Allgemein, Verbindung & Skalierung ---
        tab_general = QWidget()
        gen_layout = QVBoxLayout(tab_general)

        conn_group = QGroupBox("Fritz!Box Verbindung (UPnP && Optionaler Fritz!OS Login)")
        conn_form = QFormLayout(conn_group)
        self.txt_host = QLineEdit()
        self.txt_host.setPlaceholderText("z. B. fritz.box oder 192.168.178.1")
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_refresh = QSpinBox()
        self.spin_refresh.setRange(1, 60)
        self.spin_refresh.setSuffix(" Sek.")
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 120)
        self.spin_delay.setSuffix(" Sek.")

        self.chk_guest = QCheckBox(
            "Fritz!OS Login aktivieren (für Online-Zähler && Gäste-WLAN Anteil)"
        )
        self.txt_user = QLineEdit()
        self.txt_user.setPlaceholderText("Optional (leer lassen für Standard-Benutzer)")
        self.txt_pass = QLineEdit()
        self.txt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_pass.setPlaceholderText("Fritz!Box Passwort (für Online-Zähler & Gäste-WLAN)")
        self.chk_guest.toggled.connect(self._on_guest_toggled)

        self.btn_test_conn = QPushButton(" Verbindung && Login testen")
        self.btn_test_conn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_conn.clicked.connect(self._on_test_connection)
        self.lbl_test_result = QLabel("")
        self.lbl_test_result.setWordWrap(True)
        self.lbl_test_result.setVisible(False)

        self.lbl_bound_box = QLabel("")
        self.lbl_bound_box.setWordWrap(True)
        self.lbl_bound_box.setStyleSheet("color: #8E9297; font-size: 8.5pt;")

        conn_form.addRow("Fritz!Box Name/IP:", self.txt_host)
        conn_form.addRow("UPnP Port:", self.spin_port)
        conn_form.addRow("Aktualisierung (Refresh):", self.spin_refresh)
        conn_form.addRow("Startverzögerung:", self.spin_delay)
        conn_form.addRow("", self.chk_guest)
        conn_form.addRow("Fritz!Box Benutzer:", self.txt_user)
        conn_form.addRow("Fritz!Box Passwort:", self.txt_pass)
        conn_form.addRow("Box-Kopplung (Schutz):", self.lbl_bound_box)
        conn_form.addRow("", self.btn_test_conn)
        conn_form.addRow("", self.lbl_test_result)
        gen_layout.addWidget(conn_group)

        # Behavior & Display
        beh_group = QGroupBox("Darstellung && Verhalten")
        beh_grid = QGridLayout(beh_group)
        self.chk_autostart = QCheckBox("Autostart mit System")
        self.chk_always_on_top = QCheckBox("Immer im Vordergrund (Always on Top)")
        self.chk_locked_pos = QCheckBox("Position sperren (LockedPos)")
        self.chk_switch_up_down = QCheckBox("Download oben / Upload unten")
        self.chk_show_bits = QCheckBox("Als Bit/s anzeigen (Mbit/s statt MB/s)")
        self.chk_compact = QCheckBox("Kompakt-Modus (Graph ausblenden)")
        self.chk_session_totals = QCheckBox("Online- / Session-Zähler im Footer anzeigen")

        self.cmb_footer_mode = QComboBox()
        self.cmb_footer_mode.addItem("Heute (Fritz!Box Online-Zähler)", "today")
        self.cmb_footer_mode.addItem("Gestern (Fritz!Box Online-Zähler)", "yesterday")
        self.cmb_footer_mode.addItem("Aktuelle Woche (Fritz!Box Online-Zähler)", "week")
        self.cmb_footer_mode.addItem("Aktueller Monat (Fritz!Box Online-Zähler)", "month")
        self.cmb_footer_mode.addItem("Vormonat (Fritz!Box Online-Zähler)", "last_month")
        self.cmb_footer_mode.addItem("Seit Widget-Start (ohne Login)", "session")

        self.chk_show_peak = QCheckBox("Peak-Rate anzeigen (z. B. Peak 60s)")
        self.chk_show_guest_meta = QCheckBox("Gäste-WLAN-Rate unter Raten anzeigen")

        beh_grid.addWidget(self.chk_autostart, 0, 0)
        beh_grid.addWidget(self.chk_always_on_top, 0, 1)
        beh_grid.addWidget(self.chk_locked_pos, 1, 0)
        beh_grid.addWidget(self.chk_switch_up_down, 1, 1)
        beh_grid.addWidget(self.chk_show_bits, 2, 0)
        beh_grid.addWidget(self.chk_compact, 2, 1)
        beh_grid.addWidget(self.chk_session_totals, 3, 0)
        beh_grid.addWidget(self.cmb_footer_mode, 3, 1)
        beh_grid.addWidget(self.chk_show_peak, 4, 0)
        beh_grid.addWidget(self.chk_show_guest_meta, 4, 1)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Deckkraft (Opacity):"))
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(25, 100)
        self.lbl_opacity_val = QLabel("85%")
        self.slider_opacity.valueChanged.connect(
            lambda v: self.lbl_opacity_val.setText(f"{v}%")
        )
        opacity_row.addWidget(self.slider_opacity, 1)
        opacity_row.addWidget(self.lbl_opacity_val)
        beh_grid.addLayout(opacity_row, 5, 0, 1, 2)
        gen_layout.addWidget(beh_group)

        # Local Device Group
        pc_group = QGroupBox("Lokales Gerät (Eigener PC-Traffic Anteil)")
        pc_layout = QVBoxLayout(pc_group)
        self.chk_local_pc = QCheckBox("Eigenen PC-Traffic überwachen (Anteil am Internet-Traffic)")
        self.chk_pc_in_graph = QCheckBox("Eigenen Anteil im Graphen einfärben (abgedunkelte Nuance)")
        self.chk_pc_in_header = QCheckBox("Eigene Rate als Text unter den Haupt-Raten anzeigen")
        self.chk_local_pc.toggled.connect(self._on_local_pc_toggled)

        pc_layout.addWidget(self.chk_local_pc)
        pc_sub_row = QHBoxLayout()
        pc_sub_row.setContentsMargins(20, 0, 0, 0)
        pc_sub_row.addWidget(self.chk_pc_in_graph)
        pc_sub_row.addWidget(self.chk_pc_in_header)
        pc_layout.addLayout(pc_sub_row)
        gen_layout.addWidget(pc_group)

        # Scaling Group
        scale_group = QGroupBox("Graph-Skalierung && Leitungskapazität")
        scale_form = QFormLayout(scale_group)

        self.cmb_scale_mode = QComboBox()
        self.cmb_scale_mode.addItem(
            "Wurzel-Skala (Smart: kleine Raten sichtbar + bis 100% Leitung)", "sqrt"
        )
        self.cmb_scale_mode.addItem(
            "Dynamisch (Skaliert auf aktuellen Peak, %-Balken zeigt echte Last)",
            "dynamic",
        )
        self.cmb_scale_mode.addItem(
            "Fix auf Leitungskapazität (Original-Verhalten)", "fixed"
        )

        self.chk_auto_link = QCheckBox(
            "Maximale Bandbreite automatisch per UPnP von Fritz!Box lesen"
        )
        self.spin_max_down = QDoubleSpinBox()
        self.spin_max_down.setRange(1.0, 10000.0)
        self.spin_max_down.setDecimals(1)
        self.spin_max_down.setSuffix(" Mbit/s")

        self.spin_max_up = QDoubleSpinBox()
        self.spin_max_up.setRange(0.5, 10000.0)
        self.spin_max_up.setDecimals(1)
        self.spin_max_up.setSuffix(" Mbit/s")

        self.chk_auto_link.toggled.connect(self._on_auto_link_toggled)

        scale_form.addRow("Skalierungs-Modus:", self.cmb_scale_mode)
        scale_form.addRow("", self.chk_auto_link)
        scale_form.addRow("Max. Download (Manuell):", self.spin_max_down)
        scale_form.addRow("Max. Upload (Manuell):", self.spin_max_up)
        gen_layout.addWidget(scale_group)

        tabs.addTab(tab_general, "Allgemein && Skalierung")

        # --- TAB 2: Diagnose & Ping ---
        tab_diag = QWidget()
        diag_layout = QVBoxLayout(tab_diag)

        ping_group = QGroupBox("Internet Ping- && Jitter-Graph")
        ping_form = QFormLayout(ping_group)

        self.chk_ping_graph = QCheckBox("Ping- && Jitter-Graph unterhalb von Down/Up anzeigen")
        self.cmb_ping_endpoint = QComboBox()
        self.cmb_ping_endpoint.setEditable(True)
        self.cmb_ping_endpoint.addItems(["1.1.1.1", "8.8.8.8", "9.9.9.9", "heise.de", "google.com"])

        ping_form.addRow("", self.chk_ping_graph)
        ping_form.addRow("Ping-Ziel (Endpoint):", self.cmb_ping_endpoint)
        diag_layout.addWidget(ping_group)

        status_group = QGroupBox("Status- && Diagnose-Anzeige (Fußzeile)")
        status_form = QFormLayout(status_group)

        self.chk_wan_pill = QCheckBox("WAN-Verbindungsstatus anzeigen (✓ WAN OK / ⚠ Kein Sync / ✕ Offline)")
        self.chk_dns_pill = QCheckBox("Aktiven System-DNS-Server überwachen (Antwortzeit in ms)")

        status_form.addRow("", self.chk_wan_pill)
        status_form.addRow("", self.chk_dns_pill)
        diag_layout.addWidget(status_group)
        diag_layout.addStretch(1)

        tabs.addTab(tab_diag, "Diagnose && Ping")

        # --- TAB 3: Farben ---
        tab_colors = QWidget()
        col_layout = QVBoxLayout(tab_colors)

        colors_group = QGroupBox("Farben anpassen")
        colors_form = QFormLayout(colors_group)
        self.btn_col_down = ColorButton(self.config.download_color)
        self.btn_col_up = ColorButton(self.config.upload_color)
        self.btn_col_guest_down = ColorButton(self.config.guest_download_color)
        self.btn_col_guest_up = ColorButton(self.config.guest_upload_color)
        self.btn_col_ping = ColorButton(self.config.ping_color)
        self.btn_col_jitter = ColorButton(self.config.jitter_color)
        self.btn_col_bg = ColorButton(self.config.background_color)
        self.btn_col_border = ColorButton(self.config.border_color)
        self.btn_col_grid = ColorButton(self.config.grid_color)
        self.btn_col_title = ColorButton(self.config.title_color)

        colors_form.addRow("Download-Farbe:", self.btn_col_down)
        colors_form.addRow("Upload-Farbe:", self.btn_col_up)
        colors_form.addRow("Gäste-WLAN Download:", self.btn_col_guest_down)
        colors_form.addRow("Gäste-WLAN Upload:", self.btn_col_guest_up)
        colors_form.addRow("Ping-Farbe:", self.btn_col_ping)
        colors_form.addRow("Jitter-Farbe:", self.btn_col_jitter)
        colors_form.addRow("Hintergrundfarbe:", self.btn_col_bg)
        colors_form.addRow("Rahmenfarbe:", self.btn_col_border)
        colors_form.addRow("Rasterfarbe (Grid):", self.btn_col_grid)
        colors_form.addRow("Titelfarbe:", self.btn_col_title)
        col_layout.addWidget(colors_group)
        col_layout.addStretch(1)

        tabs.addTab(tab_colors, "Farben")

        # --- Bottom Action Buttons ---
        btn_row = QHBoxLayout()
        btn_reset = QPushButton("Reset (Standardwerte)")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_apply = QPushButton("Übernehmen")
        btn_apply.clicked.connect(self._apply_changes)
        btn_ok = QPushButton("Speichern && Schließen")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._save_and_close)

        btn_row.addWidget(btn_reset)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_apply)
        btn_row.addWidget(btn_ok)
        root_layout.addLayout(btn_row)

    def _on_auto_link_toggled(self, checked: bool) -> None:
        self.spin_max_down.setEnabled(not checked)
        self.spin_max_up.setEnabled(not checked)

    def _on_guest_toggled(self, checked: bool) -> None:
        self.txt_user.setEnabled(checked)
        self.txt_pass.setEnabled(checked)

    def _on_local_pc_toggled(self, checked: bool) -> None:
        self.chk_pc_in_graph.setEnabled(checked)
        self.chk_pc_in_header.setEnabled(checked)

    def _on_test_connection(self) -> None:
        """Test UPnP reachability and Fritz!OS login and show immediate inline feedback."""
        host = self.txt_host.text().strip() or "fritz.box"
        port = self.spin_port.value()
        user = self.txt_user.text().strip()
        pwd = self.txt_pass.text()

        self.btn_test_conn.setEnabled(False)
        self.btn_test_conn.setText(" Teste Verbindung...")
        self.lbl_test_result.setVisible(True)
        self.lbl_test_result.setText("Verbindung wird geprüft...")
        self.lbl_test_result.setStyleSheet("color: #CCCCCC; font-size: 8pt;")
        QApplication.processEvents()

        try:
            # 1. Test basic UPnP reachability and discover box identity
            upnp_client = FritzUpnpClient(host=host, port=port, timeout=2.5)
            try:
                upnp_client._discover_endpoints()
                upnp_ok = True
            except Exception:
                upnp_ok = False

            if not upnp_ok:
                self.lbl_test_result.setText(f"✕ Fritz!Box unter '{host}:{port}' nicht erreichbar.")
                self.lbl_test_result.setStyleSheet("color: #FF5252; font-weight: bold; font-size: 8.5pt;")
                return

            # Update detected box info
            if upnp_client.box_udn:
                short_id = upnp_client.box_udn.split("-")[-1]
                box_name = upnp_client.box_name or "FRITZ!Box"
                self.lbl_bound_box.setText(f"Erkannt: {box_name} (ID: {short_id})")

            # 2. Test Fritz!OS Login if enabled
            if self.chk_guest.isChecked():
                if not pwd:
                    self.lbl_test_result.setText("⚠ Bitte ein Passwort eingeben, um den Login zu testen.")
                    self.lbl_test_result.setStyleSheet("color: #FFAB00; font-weight: bold; font-size: 8.5pt;")
                    return

                client = FritzGuestMonitorClient(host=host, username=user, password=pwd, timeout=4.0)
                ok, msg, _block_time = client.test_login()
                if ok:
                    if upnp_client.box_udn:
                        self.config.bound_box_udn = upnp_client.box_udn
                        self.config.bound_box_name = upnp_client.box_name
                        short_id = upnp_client.box_udn.split("-")[-1]
                        box_name = upnp_client.box_name or "FRITZ!Box"
                        self.lbl_bound_box.setText(f"✓ Gekoppelt an {box_name} (ID: {short_id})")
                        self.lbl_bound_box.setStyleSheet("color: #00E676; font-size: 8.5pt;")
                    self.lbl_test_result.setText(f"✓ {msg}")
                    self.lbl_test_result.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 8.5pt;")
                elif msg.startswith("Bitte noch"):
                    self.lbl_test_result.setText(f"⚠ {msg}")
                    self.lbl_test_result.setStyleSheet("color: #FFAB00; font-weight: bold; font-size: 8.5pt;")
                else:
                    self.lbl_test_result.setText(f"✕ {msg}")
                    self.lbl_test_result.setStyleSheet("color: #FF5252; font-weight: bold; font-size: 8.5pt;")
            else:
                self.lbl_test_result.setText("✓ UPnP erreichbar (Live-Traffic aktiv).")
                self.lbl_test_result.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 8.5pt;")
        finally:
            self.btn_test_conn.setEnabled(True)
            self.btn_test_conn.setText(" Verbindung && Login testen")

    def _load_from_config(self) -> None:
        self.txt_host.setText(self.config.fritzbox_host)
        self.spin_port.setValue(self.config.upnp_port)
        self.spin_refresh.setValue(self.config.refresh_interval_sec)
        self.spin_delay.setValue(self.config.start_delay_sec)

        self.chk_autostart.setChecked(
            is_autostart_enabled() or self.config.autostart
        )
        self.chk_always_on_top.setChecked(self.config.always_on_top)
        self.chk_locked_pos.setChecked(self.config.locked_pos)
        self.chk_switch_up_down.setChecked(self.config.switch_up_down)
        self.chk_show_bits.setChecked(self.config.show_as_bits)
        self.chk_compact.setChecked(self.config.compact_mode)
        self.chk_session_totals.setChecked(self.config.show_session_totals)
        self.chk_show_peak.setChecked(self.config.show_peak_rate)
        self.chk_show_guest_meta.setChecked(self.config.show_guest_rate_labels)
        self.chk_local_pc.setChecked(self.config.enable_local_traffic_monitor)
        self.chk_pc_in_graph.setChecked(self.config.show_local_traffic_in_graph)
        self.chk_pc_in_header.setChecked(self.config.show_local_traffic_in_header)
        self._on_local_pc_toggled(self.config.enable_local_traffic_monitor)
        f_idx = self.cmb_footer_mode.findData(self.config.footer_counter_mode)
        self.cmb_footer_mode.setCurrentIndex(max(0, f_idx))
        self.slider_opacity.setValue(self.config.opacity)

        idx = self.cmb_scale_mode.findData(self.config.scale_mode)
        self.cmb_scale_mode.setCurrentIndex(max(0, idx))
        self.chk_auto_link.setChecked(self.config.auto_link_scale)
        self.spin_max_down.setValue(self.config.manual_download_mbps)
        self.spin_max_up.setValue(self.config.manual_upload_mbps)
        self._on_auto_link_toggled(self.config.auto_link_scale)

        self.chk_ping_graph.setChecked(self.config.enable_ping_graph)
        self.cmb_ping_endpoint.setEditText(self.config.ping_endpoint)
        self.chk_wan_pill.setChecked(self.config.show_wan_status_pill)
        self.chk_dns_pill.setChecked(self.config.enable_dns_monitor)

        self.btn_col_down.hex_color = self.config.download_color
        self.btn_col_up.hex_color = self.config.upload_color
        self.btn_col_guest_down.hex_color = self.config.guest_download_color
        self.btn_col_guest_up.hex_color = self.config.guest_upload_color
        self.btn_col_ping.hex_color = self.config.ping_color
        self.btn_col_jitter.hex_color = self.config.jitter_color
        self.btn_col_bg.hex_color = self.config.background_color
        self.btn_col_border.hex_color = self.config.border_color
        self.btn_col_grid.hex_color = self.config.grid_color
        self.btn_col_title.hex_color = self.config.title_color

        self.chk_guest.setChecked(self.config.enable_guest_monitor)
        self.txt_user.setText(self.config.fritz_username)
        self.txt_pass.setText(self.config.fritz_password)
        self._on_guest_toggled(self.config.enable_guest_monitor)

        if self.config.bound_box_udn:
            short_id = self.config.bound_box_udn.split("-")[-1]
            box_label = self.config.bound_box_name or "FRITZ!Box"
            self.lbl_bound_box.setText(f"✓ Gekoppelt an {box_label} (ID: {short_id})")
            self.lbl_bound_box.setStyleSheet("color: #00E676; font-size: 8.5pt;")
        else:
            self.lbl_bound_box.setText("Nicht gekoppelt (wird beim ersten Login automatisch an die Box gebunden)")
            self.lbl_bound_box.setStyleSheet("color: #8E9297; font-size: 8.5pt;")

    def _apply_changes(self) -> None:
        self.config.fritzbox_host = self.txt_host.text().strip() or "fritz.box"
        self.config.upnp_port = self.spin_port.value()
        self.config.refresh_interval_sec = self.spin_refresh.value()
        self.config.start_delay_sec = self.spin_delay.value()

        want_autostart = self.chk_autostart.isChecked()
        if want_autostart != is_autostart_enabled():
            set_autostart(want_autostart)
        self.config.autostart = want_autostart

        self.config.always_on_top = self.chk_always_on_top.isChecked()
        self.config.locked_pos = self.chk_locked_pos.isChecked()
        self.config.switch_up_down = self.chk_switch_up_down.isChecked()
        self.config.show_as_bits = self.chk_show_bits.isChecked()
        self.config.compact_mode = self.chk_compact.isChecked()
        self.config.show_session_totals = self.chk_session_totals.isChecked()
        self.config.show_peak_rate = self.chk_show_peak.isChecked()
        self.config.show_guest_rate_labels = self.chk_show_guest_meta.isChecked()
        self.config.enable_local_traffic_monitor = self.chk_local_pc.isChecked()
        self.config.show_local_traffic_in_graph = self.chk_pc_in_graph.isChecked()
        self.config.show_local_traffic_in_header = self.chk_pc_in_header.isChecked()
        self.config.footer_counter_mode = str(self.cmb_footer_mode.currentData() or "today")
        self.config.opacity = self.slider_opacity.value()

        self.config.scale_mode = str(self.cmb_scale_mode.currentData() or "sqrt")
        self.config.auto_link_scale = self.chk_auto_link.isChecked()
        self.config.manual_download_mbps = self.spin_max_down.value()
        self.config.manual_upload_mbps = self.spin_max_up.value()

        self.config.enable_ping_graph = self.chk_ping_graph.isChecked()
        self.config.ping_endpoint = self.cmb_ping_endpoint.currentText().strip() or "1.1.1.1"
        self.config.show_wan_status_pill = self.chk_wan_pill.isChecked()
        self.config.enable_dns_monitor = self.chk_dns_pill.isChecked()

        self.config.download_color = self.btn_col_down.hex_color
        self.config.upload_color = self.btn_col_up.hex_color
        self.config.guest_download_color = self.btn_col_guest_down.hex_color
        self.config.guest_upload_color = self.btn_col_guest_up.hex_color
        self.config.ping_color = self.btn_col_ping.hex_color
        self.config.jitter_color = self.btn_col_jitter.hex_color
        self.config.background_color = self.btn_col_bg.hex_color
        self.config.border_color = self.btn_col_border.hex_color
        self.config.grid_color = self.btn_col_grid.hex_color
        self.config.title_color = self.btn_col_title.hex_color

        self.config.enable_guest_monitor = self.chk_guest.isChecked()
        self.config.fritz_username = self.txt_user.text().strip()
        new_pwd = self.txt_pass.text()
        pwd_changed = new_pwd != self.config.fritz_password
        self.config.fritz_password = new_pwd

        if self.config.enable_guest_monitor and new_pwd:
            if not self.config.bound_box_udn or pwd_changed:
                try:
                    probe = FritzUpnpClient(host=self.config.fritzbox_host, port=self.config.upnp_port, timeout=1.5)
                    probe._discover_endpoints()
                    if probe.box_udn:
                        self.config.bound_box_udn = probe.box_udn
                        self.config.bound_box_name = probe.box_name
                except Exception:
                    pass
        elif not new_pwd:
            self.config.bound_box_udn = ""
            self.config.bound_box_name = ""

        self.config.save()
        self.on_apply()

    def _save_and_close(self) -> None:
        self._apply_changes()
        self.accept()

    def _reset_defaults(self) -> None:
        self.config.reset_defaults()
        self._load_from_config()
        self.config.save()
        self.on_apply()
