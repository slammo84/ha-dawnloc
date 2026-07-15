# DAWNLoc

WLAN-basierte Raumortung für Home Assistant mit OpenWrt und DAWN.

## Verfügbare Add-on-Trees

| Tree | Status | Zweck |
|---|---|---|
| `dawnloc/` | Stable | Produktiver Betrieb mit gerätebezogenen Fingerprints |
| `dawnloc-beta/` | Beta | Test von gemeinsamen Raumprofilen und AP-Raumzuordnung |

## Beta-Testing

Die Version `0.2.0-beta.1` ist bewusst getrennt von der stabilen Version. Sie erscheint im Home-Assistant-Add-on-Store als **DAWNLoc Beta**.

Vor dem Test:

1. vollständiges Home-Assistant-Backup erstellen,
2. stabile Instanz stoppen,
3. Beta installieren,
4. niemals Stable und Beta gleichzeitig betreiben.

Weitere Hinweise stehen in [`dawnloc-beta/README.md`](dawnloc-beta/README.md).

## Entwicklung

Die Beta gehört in den Branch `testing/0.2`. `main` bleibt für stabile Versionen reserviert.
