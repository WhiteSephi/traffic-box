# Changelog

Alle relevanten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.
Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

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
