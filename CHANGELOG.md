# Changelog

Alle relevanten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.
Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [0.4.1] - 2026-11-03
### Changed
- **Peak-Anzeige als gleitendes 60s-Maximum (`Peak (60s)`):** Der Peak-Wert bezieht sich jetzt automatisch auf das sichtbare Zeitfenster des Graphen (letzte 60 Sekunden) und setzt sich von selbst zurück, sobald eine Lastspitze aus dem Graphen herauswandert.
- **Verständliche Zähler-Bezeichnungen ohne Login:** Statt `Seit Sync (UPnP)` und `Widget-Session` heißen die Zähler nun selbsterklärend **`Seit Verbindung (2d 09h)`** (bzw. `Seit Router-Start`) und **`Seit Widget-Start`**.

## [0.4.0] - 2026-11-03
### Added
- Direkt-Umschalter im Widget-Header (`📈 Graph` | `📊 Zähler`) implementiert (`src/ui/online_counter_view.py` & `src/ui/widget.py`), mit dem sich die Hauptfläche des Widgets nahtlos zwischen dem Live-Graphen und der Online-Zähler-Tabelle (`Heute`, `Gestern`, `Aktuelle Woche`, `Aktueller Monat`, `Vormonat`) umschalten lässt.
- Intelligenter Fallback in der Zähler-Ansicht ohne Login: Zeigt `Widget-Session` und `Seit Sync (UPnP)` samt Direkt-Button zum Aktivieren des Fritz!OS-Logins in den Einstellungen.

## [0.3.0] - 2026-11-03
### Added
- Auslesen des offiziellen Fritz!Box **Online-Zählers** (`inetstat:status/Today`, `Yesterday`, `ThisWeek`, `ThisMonth`, `LastMonth` über `/query.lua` mit 64-Bit High/Low-Berechnung) in `src/api/fritz_monitor.py`.
- Umschaltbare Zeitraum-Anzeige im Widget-Footer (`Heute`, `Gestern`, `Aktuelle Woche`, `Aktueller Monat`, `Vormonat` oder `Widget-Session`) über die Einstellungen sowie das Rechtsklick-Kontextmenü (`Footer-Zähler`).
- Vollständige Online-Zähler-Tabelle (Gesamt, Gesendet, Empfangen für alle 5 Zeiträume) im Hover-Tooltip des Widgets.

## [0.2.2] - 2026-11-03
### Changed
- Zugangsdaten für den optionalen Gäste-WLAN-Monitor direkt in die Verbindungs-Sektion auf dem ersten Reiter (`Allgemein & Skalierung`) verschoben; zweiter Reiter enthält nun ausschließlich die Farbeinstellungen (`Farben`).

### Fixed
- Wiederherstellung der letzten Fenstergröße nach dem Beenden des Kompakt-Modus repariert (verhindert das Überschreiben der gespeicherten Höhe durch `resizeEvent` beim Ein-/Ausblenden des Graphen).
- Darstellung von `&`-Zeichen in Tab-Titeln, Gruppenrahmen und Checkboxen korrigiert (`&&` gegen Qt-Mnemonic-Verschlucken).

## [0.2.1] - 2026-11-03
### Changed
- Standard-Host der Fritz!Box in Code und `.env.example` auf `fritz.box` statt einer spezifischen lokalen IP-Adresse gesetzt.

## [0.2.0] - 2026-11-03
### Added
- Passwortfreier UPnP-SOAP-Client (`src/api/upnp_client.py`) für AVM FRITZ!Box über Port `49000` (`GetAddonInfos`, `GetCommonLinkProperties`, `GetStatusInfo`, `GetExternalIPAddress`) mit automatischer Endpunkt-Erkennung (`/igddesc.xml`).
- Optionaler authentifizierter Fritz!OS-Client (`src/api/fritz_monitor.py`) zur Abfrage des Gäste-WLAN-Anteils (`ds_guest_bps` / `us_guest_bps` via `login_sid.lua` v2 PBKDF2 & `netMoni`).
- Rahmenloses, transparentes Cross-Platform Desktop-Widget (`src/ui/widget.py`) auf Basis von PySide6 (Qt6) für CachyOS (KDE Plasma) und Windows.
- Pflicht-Feature: Live-Auslastungsanzeige in Prozent (`%`), Auslastungs-Fortschrittsbalken und Peak-Raten-Tracking relativ zur Leitungskapazität.
- Split-Area-Echtzeitgraph (`src/ui/graph_canvas.py`) mit drei umschaltbaren Skalierungs-Modi: Wurzel-Skala (`sqrt`), Dynamisch (`dynamic`) und Fix auf Leitungskapazität (`fixed`) sowie separater Gäste-WLAN-Kurveneinfärbung.
- Umfangreicher Einstellungs-Dialog (`src/ui/settings_dlg.py`), System-Tray-Integration (`src/ui/tray.py`) und plattformübergreifender Autostart (`src/autostart.py`).
- Start-Skripte für Windows (`start_windows.vbs`) und Linux/CachyOS (`start_linux.sh`).

## [0.1.0] - 2026-11-03
### Added
- Initiales Projekt-Setup aus dem Basis-Template erstellt (`traffic-box`).
