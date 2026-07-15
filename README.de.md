# ha-dawnloc

[English](README.md) | **Deutsch**

![Version](https://img.shields.io/badge/version-0.1.0--rc.1-orange)
![Status](https://img.shields.io/badge/status-sehr%20frühe%20Beta-orange)

DAWNLoc ist eine Home-Assistant-App zur WLAN-basierten Raumortung mit
[OpenWrt](https://github.com/openwrt/openwrt) und
[DAWN](https://github.com/berlin-open-wireless-lab/DAWN).

Die App vergleicht die Signalwerte mehrerer Access Points und ermittelt daraus
den wahrscheinlichsten Raum eines WLAN-Geräts. Das Ergebnis wird über MQTT
Discovery an Home Assistant übertragen.

> [!WARNING]
> DAWNLoc befindet sich in einer sehr frühen Beta-Phase. Konfiguration,
> Entitäten und Verhalten können sich noch ändern.

[![Repository zu Home Assistant hinzufügen](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fslammo84%2Fha-dawnloc)

## Funktionen

- Raumortung mit mehreren OpenWrt-Access-Points
- Auswertung der DAWN Hearing Map
- automatische Erkennung ortbarer WLAN-Clients
- Anzeige von IP-Adresse, MAC-Adresse, geschätztem aktuellem AP, Kanal und Frequenzband
- Gruppierung der Geräte nach erkanntem Raum
- Anzeige der Ortungssicherheit
- automatische MQTT-Discovery für Home Assistant
- deutsche und englische Oberfläche
- vollständig lokale Verarbeitung

DAWNLoc bietet nur Clients zur Einrichtung an, die von mehreren physischen
Access Points gesehen werden.

## Voraussetzungen

- Home Assistant OS oder eine andere Installation mit App-Unterstützung
- MQTT-Integration in Home Assistant und ein MQTT-Broker
- mehrere OpenWrt-Access-Points mit DAWN
- eine funktionierende gemeinsame DAWN Hearing Map
- Root-Zugriff auf die beteiligten OpenWrt-Knoten

Du kannst die Hearing Map auf OpenWrt so prüfen:

```sh
ubus call dawn get_hearing_map
```

## Feste MAC-Adresse verwenden

Viele Smartphones, Tablets und Notebooks verwenden standardmäßig eine zufällige
oder private MAC-Adresse. Deaktiviere sie für dein vertrauenswürdiges Heim-WLAN
auf allen Geräten, die du mit DAWNLoc orten möchtest. Sonst kann DAWNLoc dasselbe
Gerät nach einem MAC-Wechsel als neuen Client erkennen.

In öffentlichen oder fremden WLANs kannst du die private MAC-Adresse weiterhin
verwenden.

## Home-Assistant-App installieren

Nutze den Button oben oder füge das Repository manuell hinzu:

```text
Einstellungen → Apps → App-Store → ⋮ → Repositories
```

```text
https://github.com/slammo84/ha-dawnloc
```

Danach kannst du **DAWNLoc** installieren und starten.

## OpenWrt-Agent installieren

Der Agent sendet die DAWN Hearing Map, lokale AP-Daten und verfügbare
DHCP-Clientdaten an MQTT. Installiere ihn auf jedem OpenWrt-Access-Point, dessen
Hostname und Funkbänder in DAWNLoc erscheinen sollen. Mindestens ein
installierter Knoten sollte Zugriff auf deine DHCP-Leases haben, damit Hostnamen
und IP-Adressen ergänzt werden können.

Empfohlene Installation:

```sh
wget -O /tmp/ha-dawnloc-install.sh \
  https://raw.githubusercontent.com/slammo84/ha-dawnloc/main/dawnloc/openwrt/install.sh

cat /tmp/ha-dawnloc-install.sh
sh /tmp/ha-dawnloc-install.sh
```

Schnellinstallation:

```sh
wget -qO- \
  https://raw.githubusercontent.com/slammo84/ha-dawnloc/main/dawnloc/openwrt/install.sh | sh
```

Das Skript erkennt `opkg` oder `apk`, installiert fehlende Abhängigkeiten, fragt
deine MQTT-Daten ab, erstellt die UCI-Konfiguration und startet den Dienst.

## Einrichtung

1. Lege die Räume an, die du unterscheiden möchtest.
2. Warte, bis ortbare Clients erscheinen.
3. Übernimm einen Client. Sein Hostname wird als Gerätename vorgeschlagen.
4. Kalibriere das Gerät in jedem Raum an typischen Positionen.

Gespeicherte Geräte werden nach ihrem stabilen Raum gruppiert. Der Device-Tracker
meldet `home`, solange das Gerät noch im Netzwerk gesehen wird, und erst nach Ablauf
des Offline-Timeouts `not_home`. Eine unsichere Raumortung ändert den Anwesenheitsstatus
nicht. Der letzte zuverlässige Raum bleibt bei kurzen Messlücken und bei nur einem
sichtbaren Access Point erhalten. Wenn du ein Gerät löschst, entfernt DAWNLoc auch
dessen MQTT-Discovery-Einträge und Home-Assistant-Entitäten.

Access Points werden über ihren Hostnamen angezeigt. Pro physischem AP erscheint
soweit verfügbar einmal 2,4 GHz und einmal 5 GHz. Name und BSSID werden
automatisch erkannt und können nicht bearbeitet werden.

## Ortungssicherheit

Die Ortungssicherheit zeigt dir, wie eindeutig die aktuellen Messwerte zu einem
Raum passen. Sie ist keine exakte Wahrscheinlichkeit und keine genaue
Positionsangabe. Wände, Möbel, Personen, Gerätehardware, Energiesparfunktionen
und Funkstörungen können das Ergebnis beeinflussen.

DAWNLoc ist für Komfortautomationen gedacht, nicht für Alarmanlagen,
Zutrittskontrollen oder andere sicherheitsrelevante Entscheidungen.

## Datenschutz

DAWNLoc arbeitet in deinem eigenen Netzwerk und sendet keine Daten an externe
Cloud-Dienste. Je nach Aufbau verarbeitet es MAC-Adressen, Hostnamen, lokale
IP-Adressen, WLAN-Signalwerte, Raumzuordnungen und Zeitpunkte.

Orte keine Personen oder Geräte ohne deren Zustimmung.

DAWNLoc ist ein eigenständiges Projekt und kein offizieller Bestandteil von
OpenWrt, DAWN oder Home Assistant.

## Autor

**slammo84**

## Lizenz

[Apache License 2.0](LICENSE)
