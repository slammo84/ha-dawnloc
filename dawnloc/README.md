# DAWNLoc Beta â€“ 0.2.0-beta.2

> Experimentelle Testversion. Nicht als stabile Produktivversion behandeln.

Diese Beta testet eine neue Raumortungslogik:

- Eigene GerÃ¤te-Fingerprints werden weiterhin bevorzugt.
- Fehlen eigene Fingerprints, werden gemeinsame Raumprofile aus bewusst kalibrierten Messungen anderer GerÃ¤te verwendet.
- Access-Point-Knoten kÃ¶nnen RÃ¤umen zugeordnet werden.
- Die AP-Raumzuordnung ist nur ein schwacher Hinweis und niemals eine harte Raumregel.

## Branches

Stabile Version:

```text
main
```

Beta-Version:

```text
testing/0.2
```

Beide Branches enthalten die App im Ordner `dawnloc/` und verwenden denselben Slug `dawnloc`. Es handelt sich daher nicht um zwei parallel installierbare Apps.

Eine URL mit `/tree/testing/0.2` ist keine klonbare Repository-Adresse und darf nicht als Repository-Quelle verwendet werden.

## Vor dem Test

1. VollstÃ¤ndiges Home-Assistant-Backup erstellen.
2. Stabiles DAWNLoc stoppen.
3. Sicherstellen, dass wirklich der Branch `testing/0.2` verwendet wird.
4. Vor dem Start die angezeigte Version `0.2.0-beta.2` prÃ¼fen.
5. Nach dem Betatest wieder auf `main` wechseln.

## Behoben in Beta 2

Beta 2 behebt einen JavaScript-Abbruch beim Laden der OberflÃ¤che.

Dadurch werden gespeicherte RÃ¤ume und GerÃ¤te wieder angezeigt. Sie stehen auÃŸerdem wieder in den Kalibrierungs-Dropdowns zur VerfÃ¼gung. Die Raumzuordnungen der Access Points werden vor deren Darstellung geladen.

## Testschwerpunkte

- Werden vorhandene RÃ¤ume und GerÃ¤te direkt nach dem Start angezeigt?
- Sind GerÃ¤te und RÃ¤ume in den Kalibrierungs-Dropdowns vorhanden?
- Enthalten die AP-Dropdowns alle angelegten RÃ¤ume?
- Erkennt ein noch nicht fÃ¼r den Raum kalibriertes GerÃ¤t den Raum anhand gemeinsamer Werte?
- Bleiben gerÃ¤teeigene Fingerprints bevorzugt?
- Verbessert eine korrekte AP-Raumzuordnung knappe Entscheidungen?
- Verursacht eine falsche AP-Raumzuordnung keine harte Fehlentscheidung?

## APs RÃ¤umen zuordnen

Im Bereich **Access Points** kann jedem physischen AP-Knoten ein Raum zugewiesen werden. Alle BSSIDs und FrequenzbÃ¤nder desselben Hostnamens teilen sich diese Standortangabe.

Die Zuordnung verÃ¤ndert keine Fingerprints. Sie liefert lediglich einen kleinen Bonus bei ansonsten Ã¤hnlichen Ergebnissen.

## RÃ¼ckkehr zur stabilen Version

1. DAWNLoc stoppen.
2. Wieder den Branch `main` verwenden.
3. PrÃ¼fen, dass die stabile Versionsnummer angezeigt wird.
4. Bei Problemen das zuvor erstellte Home-Assistant-Backup wiederherstellen.
