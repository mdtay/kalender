# Lastenheft: Raspberry Pi Setup

## Phase 1 — Pi 5 Grundeinrichtung
- [ ] Raspberry Pi OS Lite auf MicroSD flashen (mit Raspberry Pi Imager)
- [ ] WLAN, Benutzername und SSH direkt beim Flashen einstellen
- [ ] Pi starten, per SSH verbinden
- [ ] System aktualisieren (`apt update && apt upgrade`)
- [ ] Python, pip und Abhängigkeiten installieren
- [ ] USB-SSD anschließen und mit festem Mountpunkt `/mnt/kalender` einbinden (`/etc/fstab`)

## Phase 2 — Kalender-App
- [ ] Git auf dem PC einrichten (`git init`, erster Commit)
- [ ] Git auf dem Pi installieren und Repository klonen
- [ ] Uploads-Ordner auf die SSD verschieben (`/mnt/kalender/uploads`)
- [ ] Pillow + pillow-heif installieren
- [ ] App lokal testen (Flask Dev-Server)
- [ ] Gunicorn installieren und konfigurieren
- [ ] Nginx installieren und als Reverse Proxy einrichten
- [ ] App als Systemd-Service einrichten (startet automatisch nach Neustart)

## Weiterer Entwicklungs-Workflow (nach Setup)
1. Änderungen lokal auf dem PC entwickeln und testen
2. `git add . && git commit -m "Beschreibung"` auf dem PC
3. `git push` auf dem PC
4. Per SSH auf den Pi verbinden
5. `git pull` auf dem Pi
6. `sudo systemctl restart kalender` — App neu starten
7. Fertig

## Phase 3 — Pi-hole
- [ ] Pi-hole installieren
- [ ] In der Fritz!Box als DNS-Server eintragen
- [ ] Testen ob Werbung blockiert wird

## Phase 4 — Fernzugriff
- [ ] Tailscale auf dem Pi installieren
- [ ] Tailscale auf beiden Smartphones installieren
- [ ] Testen ob Kalender-App von unterwegs erreichbar ist

## Phase 5 — Digitaler Bilderrahmen (Vater)
- [ ] `/rahmen`-Seite in Kalender-App einbauen (Vollbild-Diashow)
- [ ] Pi Zero 2 W bestellen und einrichten
- [ ] Raspberry Pi OS Lite auf Pi Zero flashen
- [ ] Tailscale auf Pi Zero installieren
- [ ] Chromium im Kiosk-Modus einrichten (zeigt `/rahmen` im Vollbild)
- [ ] Pi Zero bei Vater aufstellen und testen

## Einkaufsliste
- Raspberry Pi 5 Official Black Kit (2 GB) — welectron.com ~95 €
- Lexar MicroSD 32 GB (A1) — ~10 €
- Samsung T7 / Intenso TX800 500 GB USB-SSD — ~60–80 €
- Raspberry Pi Zero 2 W — ~20 €
- Micro-USB Netzteil für Pi Zero — ~8 €
- Mini-HDMI → HDMI Kabel — ~5 €
- MicroSD 16 GB für Pi Zero — ~8 €
- Kleiner HDMI Monitor 10–15" — ~50–80 €
