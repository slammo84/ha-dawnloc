# Changelog

## 0.2.0-beta.1

### Neu

- Gemeinsame Raumprofile: Fehlen geräteeigene Fingerprints, nutzt DAWNLoc bewusst kalibrierte Messungen anderer Geräte als gemeinsames Raumprofil.
- Access Points können einem Raum zugeordnet werden.
- Der Raum des tatsächlich verbundenen APs wirkt ausschließlich als schwacher Bonus und bestimmt den Raum nie allein.
- Diagnosefeld `method` zeigt `device_fingerprint`, `shared_room_profile` oder `none`.
- Separater Home-Assistant-Testing-Tree `dawnloc-beta/`.

### Wichtige Hinweise

- Beta und Stable nicht gleichzeitig starten.
- Vor dem Wechsel ein Home-Assistant-Backup anlegen.
- Die Beta verwendet einen eigenen Add-on-Slug und eine eigene Datenablage.
- Diese Beta ist zum Testen der gemeinsamen Raumprofile gedacht, nicht als stabile Produktivversion.
