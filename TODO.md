# TODO

Ergebnis der Fehleranalyse vom 07.10.2026.
Grundregel: Die Daten auf dem Haupt-Pi (`kalender.db`, Fotos) duerfen nie
verloren gehen - vor jedem Eingriff dort zuerst sichern.

## Kritisch

- [x] **Kalender-Migration laeuft unter gunicorn nie** - `init_db()` laeuft
      jetzt beim Start. Am 07.10. auf dem Haupt-Pi eingespielt (Sicherung
      vorher: `~/kalender_sicherungen/` und lokal `Kalender_Sicherungen/`).
- [x] **Rahmen-Sync-Timer nicht installiert** - am 07.10. auf dem Rahmen-Pi
      installiert (taeglich 03:30, wartet auf Netzwerk und Stick).
- [x] **19 Fotos fehlen auf dem Rahmen-Stick** - Sync holt fehlende Dateien
      jetzt selbst nach und laeuft nur mit eingebundenem Stick. Alle 19 wieder da.

## Mittel

- [x] Geaenderte Fotos (gedreht) und geaenderte Daten kommen nie beim Rahmen an.
      Export schreibt Aenderungszeit mit, Sync holt geaenderte Dateien neu.
- [x] Gleichzeitige Syncs (Knopf + Timer) koennen kollidieren - Dateisperre.
- [x] Gesichtserkennung aktiv - nur als Vorschlag: startet nach jedem Upload,
      nur fuer Fotos ohne Personen, wird erst beim Speichern zur Markierung.
- [ ] Gesichtserkennung verbessern: Profilfotos fuer alle Personen hinterlegen
      (aktuell nur Alvar, Yuna) und genaueren DNN-Detektor nachruesten
      (models/face_detector/README.md). Probelauf: ca. 60 % Trefferquote.
- [x] "Backup herunterladen" baut das Zip jetzt auf der Platte (getestet: 603 MB).

## Klein

- [x] `backup.sh` nutzt jetzt die SQLite-Backup-Funktion mit Integritaetspruefung.
- [ ] Naechtliches Backup sichert keine Fotos (nur die Datenbank).
- [ ] Logdateien wachsen unbegrenzt (`~/kiosk.log` schon 7 MB).
- [ ] "Bildschirm aus"/Nachtmodus: `vcgencmd display_power` wirkt mit dem
      KMS-Treiber nicht, es wird nur schwarz gezeichnet.
- [x] Haupt-Pi: `static/uploads` versehentlich in Git vorgemerkt.
- [ ] Geloeschte Personen bleiben in der Personenliste des Rahmens.
- [x] Ungueltige URLs (z.B. `/tag/abc`) leiten jetzt zur Startseite um.
- [x] Weiterleitungen nach Login/Speichern nur noch auf interne Seiten.

## Hardware (Bilderrahmen)

- [ ] Datenblocker anschliessen (bestellt), dann Touch pruefen.
- [ ] Anderes, kurzes HDMI-Kabel ohne Adapter testen.
