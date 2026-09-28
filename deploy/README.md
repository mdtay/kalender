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

**6. Chromium-Kiosk** — siehe Hauptplan; grob: `raspi-config` → Desktop
Autologin aktivieren, `chromium-browser` installieren, Autostart-Eintrag unter
`~/.config/autostart/` anlegen, der auf `http://localhost:8600/` zeigt.
