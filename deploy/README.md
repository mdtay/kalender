# Deploy-Dateien

Diese Unit-Dateien liegen nur als Vorlage im Repo — systemd liest sie erst,
wenn sie auf dem Pi nach `/etc/systemd/system/` kopiert werden:

```bash
sudo cp deploy/kalender-gesichter.service deploy/kalender-gesichter.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kalender-gesichter.timer
systemctl list-timers | grep gesichter
journalctl -u kalender-gesichter.service -f
```

Passt Pfade/Benutzer (`tay`, `/home/tay/kalender`) an, falls sich der
Deploy-Ort auf dem Pi ändert.

## Bilderrahmen — Haupt-Pi (home-pi)

Exportiert nachts ein Manifest, das der Rahmen-Pi sich per rsync holt:

```bash
sudo cp deploy/kalender-rahmen-export.service deploy/kalender-rahmen-export.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kalender-rahmen-export.timer
journalctl -u kalender-rahmen-export.service -n 30
```

## Bilderrahmen — Rahmen-Pi (beim Vater)

**1. SSH-Zugang zum Haupt-Pi einrichten** (einmalig, für rsync):
```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
ssh-copy-id tay@home-pi
ssh tay@home-pi "echo verbunden"   # testen
```

**2. Python-Abhängigkeiten installieren** (eigenes, schlankes requirements.txt):
```bash
cd /home/tay/kalender
python3 -m venv venv
venv/bin/pip install -r rahmen/requirements.txt
```

**3. USB-Stick mounten** — Pfad ermitteln und in `/etc/fstab` eintragen:
```bash
lsblk
sudo blkid   # UUID des Sticks notieren
sudo mkdir -p /mnt/rahmen-fotos
# in /etc/fstab ergänzen:
# UUID=<hier-UUID> /mnt/rahmen-fotos ext4 defaults,nofail 0 2
sudo mount -a
```
Falls ein anderer Pfad als `/mnt/rahmen-fotos` gewählt wird: `RAHMEN_FOTOS_DIR`
in `deploy/rahmen-app.service` und `deploy/rahmen-sync.service` per
`Environment=RAHMEN_FOTOS_DIR=...` setzen.

**4. Dienste installieren** (kein `rahmen-app.service` mehr — die Anzeige
läuft jetzt als natives `pygame`-Programm direkt über X, kein Webserver
nötig):
```bash
sudo cp deploy/rahmen-sync.service deploy/rahmen-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rahmen-sync.timer
```
**Hinweis Nachtmodus:** `deploy/rahmen-nacht-aus.*`/`rahmen-nacht-an.*` liegen
noch im Repo, werden aber **nicht mehr gebraucht** — der Nachtmodus ist jetzt
direkt in den Einstellungen von `kiosk.py` einstellbar (Uhrzeiten per
Touchscreen, kein SSH mehr nötig). Falls die alten Timer auf einem Gerät
schon installiert waren, deaktivieren, sonst schalten beide Mechanismen
gleichzeitig am Bildschirm herum:
```bash
sudo systemctl disable --now rahmen-nacht-aus.timer rahmen-nacht-an.timer 2>/dev/null || true
```

**5. Ersten Sync manuell anstoßen** (nicht bis 3:30 Uhr warten):
```bash
sudo systemctl start rahmen-sync.service
journalctl -u rahmen-sync.service -n 30
```

**6. Kiosk-Anzeige (pygame, kein Browser)** — auf Raspberry Pi OS **Lite**
gibt es keinen fertigen Desktop. Wir brauchen nur ein minimales X für Touch-
Eingabe + `pygame`, kein Chromium, kein Webserver:

```bash
sudo raspi-config nonint do_boot_behaviour B2   # Konsolen-Autologin
sudo apt install -y xserver-xorg xinit python3-pygame python3-pil mpv
```
`python3-pygame`/`python3-pil` landen im System-Python, nicht automatisch im
venv — venv deshalb mit `--system-site-packages` anlegen (spart das
langsame Kompilieren von pygame per pip auf dem Pi 3):
```bash
cd /home/tay/kalender
rm -rf venv
python3 -m venv --system-site-packages venv
venv/bin/python -c "import pygame, PIL; print('ok')"
```
```bash
cat >> ~/.bash_profile << 'EOF'
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  startx
fi
EOF
cat > ~/.xinitrc << 'EOF'
#!/bin/bash
xset s off; xset -dpms; xset s noblank
while true; do
  /home/tay/kalender/venv/bin/python /home/tay/kalender/rahmen/kiosk.py >> /home/tay/kiosk.log 2>&1
  echo "$(date '+%Y-%m-%d %H:%M:%S'): kiosk.py beendet (Exit $?) - Neustart in 3s" >> /home/tay/kiosk.log
  sleep 3
done
EOF
chmod +x ~/.xinitrc
```
Kein `curl`-Warteskript mehr nötig (das gab es nur, weil vorher auf den
Flask-Webserver gewartet werden musste) — `kiosk.py` öffnet direkt sein
eigenes Vollbildfenster. Die `while true`-Schleife startet `kiosk.py`
automatisch neu, falls es doch mal komplett abstürzt (z.B. SDL-Fehler) —
sonst bliebe der Bildschirm dauerhaft auf "Kein Signal" hängen, bis jemand
manuell neu startet. Stdout/stderr sammelt sich in `~/kiosk.log` (wächst mit
der Zeit, ggf. gelegentlich leeren); zusätzlich loggt `kiosk.py` selbst
Fehler mit Zeitstempel nach `rahmen/kiosk_fehler.log` — dort zuerst
nachschauen, falls der Bildschirm schwarz bleibt oder "Kein Signal" zeigt.

Kiosk neu starten (kein volles Reboot nötig):
```bash
sudo systemctl restart getty@tty1.service
```
