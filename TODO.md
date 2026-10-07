# TODO

Ergebnis der Fehleranalyse vom 07.10.2026.
Grundregel: Die Daten auf dem Haupt-Pi (`kalender.db`, Fotos) duerfen nie
verloren gehen - vor jedem Eingriff dort zuerst sichern.

## Kritisch

- [ ] **Kalender-Migration laeuft unter gunicorn nie** - nach dem naechsten
      Neustart des Haupt-Pi brechen Tagesansicht, Ereignis-Seite und Galerie
      mit `no such column: quelle` ab. `init_db()` muss beim Start laufen.
- [ ] **Rahmen-Sync-Timer nicht installiert** - der Rahmen-Pi synchronisiert
      nachts nicht, nur per Knopf.
- [ ] **19 Fotos fehlen auf dem Rahmen-Stick** - am 28.09. vor dem Einbinden
      des Sticks synchronisiert. Sync soll fehlende Dateien selbst nachholen
      und nur laufen, wenn der Stick eingebunden ist.

## Mittel

- [ ] Geaenderte Fotos (gedreht) und geaenderte Daten kommen nie beim Rahmen an.
- [ ] Gleichzeitige Syncs (Knopf + Timer) koennen kollidieren - Sperre einbauen.
- [ ] Gesichtserkennung auf dem Haupt-Pi nie aktiv. Vor dem Einschalten
      klaeren: sollen unbestaetigte Auto-Treffer den Rahmen-Filter beeinflussen?
- [ ] "Backup herunterladen" baut das ganze Zip im Arbeitsspeicher.

## Klein

- [ ] `backup.sh` kopiert die laufende DB per `cp` (Kopie kann inkonsistent
      sein) und sichert keine Fotos.
- [ ] Logdateien wachsen unbegrenzt (`~/kiosk.log` schon 7 MB).
- [ ] "Bildschirm aus"/Nachtmodus: `vcgencmd display_power` wirkt mit dem
      KMS-Treiber nicht, es wird nur schwarz gezeichnet.
- [ ] Haupt-Pi: `static/uploads` versehentlich in Git vorgemerkt.
- [ ] Geloeschte Personen bleiben in der Personenliste des Rahmens.
- [ ] Ungueltige URLs (z.B. `/tag/abc`) erzeugen Fehlerseiten.

## Hardware (Bilderrahmen)

- [ ] Datenblocker anschliessen (bestellt), dann Touch pruefen.
- [ ] Anderes, kurzes HDMI-Kabel ohne Adapter testen.
