# DAWNLoc Beta 0.2.0-beta.6

Experimentelle Testversion der WLAN-basierten Raumortung für Home Assistant, OpenWrt und DAWN.

## Testschwerpunkte

- AP-Räume und Ortung bei nur einem sehr starken AP
- gemeinsame Raumprofile aus mehreren Kalibrierungen
- Beibehalten des letzten Raums, solange das Gerät erreichbar ist
- OpenWrt-Zentrale und weitere Access Points
- JSON-Export und -Import

Vor dem Test ein vollständiges Home-Assistant-Backup erstellen.

## Optionale Kontextsensoren

Kontextsensoren werden in `/config/dawnloc_context.yaml` konfiguriert. Ohne
diese Datei arbeitet DawnLoc ausschließlich mit WLAN und BLE. Eine neutrale
Vorlage liegt als `dawnloc_context.example.yaml` im Repository.

`role: room` bestätigt kurzzeitig einen bereits in DawnLoc vorhandenen Raum.
`role: transition` ordnet niemanden direkt zu, kann aber einen durch WLAN oder
BLE belegten Raumwechsel beschleunigen. Änderungen werden nach einem Neustart
von Home Assistant eingelesen. Sensormessungen werden nicht in der
DawnLoc-Datenbank gespeichert.
