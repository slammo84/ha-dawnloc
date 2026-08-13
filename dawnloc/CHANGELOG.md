# Changelog

## 0.2.0-beta.6

- Behält den Zustand geöffneter Signalwert-Details beim Live-Refresh bei.
- Entfernt Raumanker aus Datenmodell, API, Ortungslogik und Oberfläche.
- Bereinigt nicht funktionale oder redundante Bedienelemente.
- Aktualisiert die zentrale OpenWrt-Bezeichnung auf `AP-KELLER`.
- Ergänzt Personen mit mehreren WLAN-/BLE-Ortungsquellen.
- Nutzt konservative BLE-Hysterese und fünf ausgewählte HA-Kontextsensoren.
- Migriert MQTT Discovery von Geräte- auf Personen-Tracker.

## 0.2.0-beta.5

- Recorder-schonende MQTT-Entitäten und zustandsbasierte Publikation.
- BLE-Proxy-Bridge, Scanner-/Beacon-Zuordnung und konservative Wi-Fi/BLE-Fusion.
- Flüchtige BLE-Scans werden nicht in SQLite gespeichert.

## 0.2.0-beta.4

- Hotfix: Formulare behalten ihre Auswahl; Kalibrierung zeigt AP-, Signal- und Sampledetails.
- AP-Raumzuordnung, starke Ein-AP-Ortung und stabiler letzter Standort.
- Stationäre Raumanker ohne Home-Assistant-Entitäten.
- Rollenbasierter OpenWrt-Agent für Router und Access Points.
- Übersichtlichere Oberfläche, Datenimport/-export und neues Logo.
