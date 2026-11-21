# Changelog

Alle relevanten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.
Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [1.0.0] - 2026-11-21
### Added
- **Live-Traffic-Monitoring (passwortfrei per UPnP):**
  - Echtzeit-Erfassung von Download- und Upload-Raten an UPnP-fähigen Routern (z. B. AVM FRITZ!Box über Port `49000`) inklusive Leitungskapazität, Auslastungsbalken, rollierendem 60-Sekunden-Peak und umschaltbarer Darstellung (`Byte/s` ↔ `Bit/s`).
  - Eigener Qt6-Oszilloskop-Graph mit Wurzel-, dynamischer und fester Skalierung, interaktivem Hover-HUD, Kompakt-Modus („nur Zahlen“) und Nur-Graph-Modus.
- **Internet-Qualitäts-, Ping-, Jitter- & DNS-Diagnose:**
  - Live-Ping- & Jitter-Graph (native Win32-ICMP-API bzw. unprivilegierte Linux-ICMP-Sockets ohne externe Subprozesse) mit sichtbaren Timeout-/Verlustmarkern.
  - 5-stufige Internet-Erreichbarkeitsprüfung (*Stabil*, *Eingeschränkt*, *DNS-Störung*, *Kein Internet / Verbindung hängt*, *LAN-Problem*) mit Dual-Stack-HTTPS-`204`-Tests, direkter DNS-Prüfung ohne Cache und klickbarem Detail- & Tipps-Fenster.
- **Optionale Zusatzmodule & automatischer Fallback:**
  - Optionaler Fritz!OS-Login für integrierte Online-Zähler (*Heute, Gestern, Woche, Monat, Vormonat*) und Gäste-WLAN-Traffic-Anteil.
  - Lokaler PC-Traffic-Monitor sowie automatischer Fallback auf den lokalen Netzwerkadapter, wenn unterwegs keine FRITZ!Box erreichbar ist.
- **Desktop-Integration, Themes & Bedienung:**
  - Plattformübergreifend für **Windows 10/11** und **Linux / KDE Plasma** (Wayland/XWayland inkl. automatischer Taskleisten-Ausblendung und KWin-Positionsregel).
  - Rahmenloses Widget mit System-Tray-Icon + dynamischer Status-LED, magnetischem Einrasten an Bildschirmrändern (Edge Snapping), HiDPI-UI-Skalierung (`70–300 %`), 5 kuratierten Farb-Themes, modernem Color-Picker, Autostart und optionalem Portabel-Modus (`local/config.json`).
- **Sicherheit, Datenschutz & Diagnose:**
  - 100 % lokale Verarbeitung ohne Telemetrie; optionale externe Diagnose-Checks einzeln abschaltbar.
  - Gehärteter Fritz!OS-Login (PBKDF2-SHA256 Challenge-Response, MD5 standardmäßig blockiert), automatische Heim-Router-Bindung per UDN (fail-closed) und geschützte Passwort-Speicherung (Windows DPAPI bzw. Linux PBKDF2-HMAC + `0600`-Dateirechte).
  - Datensparsames Rotating-File-Logging mit automatischer Maskierung sensibler Daten sowie vorbefülltem, anonymisiertem GitHub-Fehlerbericht im „Über“-Tab.
- **Open-Source-Release, Tests & Automatisierung:**
  - Veröffentlicht unter der **MIT-Lizenz** (`LICENSE`) mit 128 isolierten Unit-Tests.
  - GitHub-Actions-Workflows für automatische Linux-/Windows-Tests (CI) und reproduzierbare Windows-Standalone-Releases (`TrafficBox.exe` + `SHA256SUMS.txt`).
