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
