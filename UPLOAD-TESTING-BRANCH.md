# Upload nach `testing/0.2`

## GitHub-Weboberfläche

1. ZIP lokal entpacken.
2. Im Repository `slammo84/ha-dawnloc` den Branch-Wähler öffnen.
3. **View all branches** → **New branch**.
4. Branchname `testing/0.2`, Quelle `main`.
5. In den neuen Branch wechseln.
6. **Add file** → **Upload files**.
7. Den kompletten Inhalt dieses Ordners hochladen, nicht den äußeren Ordner selbst.
8. Vorhandene Dateien beim Upload ersetzen.
9. Commit-Nachricht: `Prepare DAWNLoc 0.2.0-beta.1 testing tree`.
10. Prüfen, dass `main` weiterhin unverändert ist.

Home Assistant liest standardmäßig den Repository-Tree des hinzugefügten Repositorys. Für einen reinen Branch-Test kann die Tree-URL des Branches als Repository-Quelle genutzt werden:

`https://github.com/slammo84/ha-dawnloc/tree/testing/0.2`

Nach dem Hinzufügen erscheint `DAWNLoc Beta` im Add-on-Store.
