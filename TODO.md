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
- [x] Gesichtserkennung lernt aus markierten Fotos (genau 1 Person + 1 Gesicht),
      Vorschlaege nur hervorgehoben statt angehakt. Probe: 79 % (Raten: 53 %).
- [ ] Gesichtserkennung beobachten: app.log zeigt "Gesichtsvorschlaege ... uebernommen/
      verworfen". Weiter verbessern: Profilfotos fuer alle Personen (aktuell nur
      Alvar, Yuna), genauerer DNN-Detektor (models/face_detector/README.md).
- [x] "Backup herunterladen" baut das Zip jetzt auf der Platte (getestet: 603 MB).

## Klein

- [x] `backup.sh` nutzt jetzt die SQLite-Backup-Funktion mit Integritaetspruefung.
- [ ] Naechtliches Backup sichert keine Fotos (nur die Datenbank).
- [x] Logdateien rotieren ab 1 MB. Ursache der 11 MB in kiosk.log: offene
      ALSA-Tonausgabe ohne Ton - Kiosk nutzt jetzt einen Blindtreiber.
- [ ] Kiosk braucht dauerhaft ~50-60 % CPU, weil 30x pro Sekunde neu gezeichnet
      wird, auch bei stehendem Bild. Nur bei Aenderungen zeichnen -> kuehler Pi.
- [ ] "Bildschirm aus"/Nachtmodus: `vcgencmd display_power` wirkt mit dem
      KMS-Treiber nicht, es wird nur schwarz gezeichnet.
- [x] Haupt-Pi: `static/uploads` versehentlich in Git vorgemerkt.
- [ ] Geloeschte Personen bleiben in der Personenliste des Rahmens.
- [x] Ungueltige URLs (z.B. `/tag/abc`) leiten jetzt zur Startseite um.
- [x] Weiterleitungen nach Login/Speichern nur noch auf interne Seiten.

## Hardware (Bilderrahmen)

- [ ] Datenblocker anschliessen (bestellt), dann Touch pruefen.
- [ ] Anderes, kurzes HDMI-Kabel ohne Adapter testen.
