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

**4. Dienste installieren:**
```bash
sudo cp deploy/rahmen-app.service deploy/rahmen-sync.service deploy/rahmen-sync.timer \
        deploy/rahmen-nacht-aus.service deploy/rahmen-nacht-aus.timer \
        deploy/rahmen-nacht-an.service deploy/rahmen-nacht-an.timer \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rahmen-app.service
sudo systemctl enable --now rahmen-sync.timer
sudo systemctl enable --now rahmen-nacht-aus.timer rahmen-nacht-an.timer
```

**5. Ersten Sync manuell anstoßen** (nicht bis 3:30 Uhr warten):
```bash
sudo systemctl start rahmen-sync.service
journalctl -u rahmen-sync.service -n 30
```

**6. Chromium-Kiosk** — auf Raspberry Pi OS **Lite** gibt es keinen fertigen
Desktop, `raspi-config`s "Desktop Autologin" (B4) bringt daher nichts (kein
Desktop-Paket installiert). Stattdessen minimales X + `startx` beim Login:

```bash
sudo raspi-config nonint do_boot_behaviour B2   # Konsolen-Autologin
sudo apt install -y xserver-xorg xinit x11-xserver-utils chromium
```
```bash
cat >> ~/.bash_profile << 'EOF'
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  startx
fi
EOF
cat > ~/.xinitrc << 'EOF'
#!/bin/bash
exec ~/rahmen-kiosk-start.sh
EOF
chmod +x ~/.xinitrc
```
`~/rahmen-kiosk-start.sh` (Kiosk-Startskript, wartet auf die lokale App und
startet Chromium im Vollbild):
```bash
cat > ~/rahmen-kiosk-start.sh << 'EOF'
#!/bin/bash
until curl -sf http://localhost:8600/ >/dev/null; do sleep 1; done
xset s off; xset -dpms; xset s noblank
chromium --kiosk --noerrdialogs --disable-infobars \
  --disable-session-crashed-bubble \
  --check-for-update-interval=31536000 \
  --autoplay-policy=no-user-gesture-required \
  http://localhost:8600/
EOF
chmod +x ~/rahmen-kiosk-start.sh
```
**Wichtig:** Das Paket heißt auf diesem Debian-trixie-basierten Image
`chromium` (Binary `/usr/bin/chromium`), **nicht** `chromium-browser` — mit
`which chromium` prüfen, falls sich das in einer künftigen Image-Version
wieder ändert.
