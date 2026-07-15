# DAWNLoc Beta – 0.2.0-beta.1

> Experimentelle Testversion. Nicht als stabile Produktivversion behandeln.

Diese Beta testet eine neue Raumortungslogik:

- eigene Geräte-Fingerprints werden weiterhin bevorzugt,
- fehlen eigene Fingerprints, werden gemeinsame Raumprofile aus bewusst kalibrierten Messungen anderer Geräte verwendet,
- Access-Point-Knoten können Räumen zugeordnet werden,
- die AP-Raumzuordnung ist nur ein schwacher Hinweis und niemals eine harte Raumregel.

## Installation in Home Assistant

Dieses Repository enthält zwei Add-on-Trees:

- `dawnloc/` – stabile Version
- `dawnloc-beta/` – experimentelle Version 0.2

Im Add-on-Store erscheint die Testversion als **DAWNLoc Beta**.

### Vor dem Test

1. Vollständiges Home-Assistant-Backup erstellen.
2. Stabiles DAWNLoc stoppen.
3. DAWNLoc Beta installieren und konfigurieren.
4. Stable und Beta niemals gleichzeitig starten, da beide dieselben OpenWrt-Rohdaten verarbeiten.
5. Räume und Kalibrierungen in der Beta zunächst kontrolliert neu anlegen.

## Testschwerpunkte

- Erkennt ein fremdes, noch nicht in diesem Raum kalibriertes Gerät den Raum anhand gemeinsamer Werte?
- Bleiben geräteeigene Fingerprints genauer und bevorzugt?
- Verbessert eine korrekte AP-Raumzuordnung knappe Entscheidungen?
- Verursacht eine falsche AP-Raumzuordnung keinen harten Fehlentscheid?
- Springt die stabile Raumzuordnung nicht zwischen benachbarten Räumen?

## APs Räumen zuordnen

Im Bereich **Access Points** kann jedem physischen AP-Knoten ein Raum zugewiesen werden. Alle BSSIDs und Frequenzbänder desselben Hostnamens teilen sich diese Standortangabe.

Die Zuordnung verändert keine Fingerprints. Sie liefert lediglich einen kleinen Bonus bei ansonsten ähnlichen Ergebnissen.

## Rückkehr zur Stable-Version

1. DAWNLoc Beta stoppen.
2. Stabiles DAWNLoc starten.
3. Beta bei Bedarf deinstallieren.
4. Bei Problemen das vorher erstellte Home-Assistant-Backup wiederherstellen.
