"""
Temporaeres Diagnose-Werkzeug fuer die Strom-/Touch-Aussetzer auf dem
Rahmen-Pi: protokolliert alle 30s Unterspannungsstatus, Temperatur und
Anzahl erkannter Eingabegeraete (zeigt, ob der Touchscreen gerade vom
USB abfaellt). Nach Behebung des Stromproblems wieder entfernen - das
ist kein Teil der eigentlichen Bilderrahmen-App.
"""
import datetime
import glob
import re
import subprocess

LOG_PATH = '/home/tay/strom_monitor.log'


def befehl_lesen(cmd):
    try:
        ergebnis = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return ergebnis.stdout.strip() or ergebnis.stderr.strip()
    except Exception as exc:
        return f"FEHLER({exc})"


def eingabegeraete_anzahl():
    try:
        with open('/proc/bus/input/devices', encoding='utf-8', errors='ignore') as f:
            inhalt = f.read()
        return len(re.findall(r'^I:', inhalt, re.MULTILINE))
    except Exception:
        return -1


def hdmi_status():
    try:
        werte = []
        for pfad in sorted(glob.glob('/sys/class/drm/*/status')):
            with open(pfad, encoding='utf-8') as f:
                werte.append(f.read().strip())
        return ','.join(werte) or 'keine'
    except Exception as exc:
        return f"FEHLER({exc})"


def kiosk_laeuft():
    ergebnis = befehl_lesen(['pgrep', '-f', 'rahmen/kiosk.py'])
    return bool(ergebnis)


def hauptlauf():
    jetzt = datetime.datetime.now().isoformat(timespec='seconds')
    throttled = befehl_lesen(['vcgencmd', 'get_throttled'])
    temp = befehl_lesen(['vcgencmd', 'measure_temp'])
    anzahl = eingabegeraete_anzahl()
    hdmi = hdmi_status()
    display_power = befehl_lesen(['vcgencmd', 'display_power'])
    kiosk = kiosk_laeuft()
    zeile = (
        f"{jetzt} {throttled} {temp} eingabegeraete={anzahl} "
        f"hdmi={hdmi} {display_power} kiosk_laeuft={kiosk}\n"
    )
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(zeile)


if __name__ == '__main__':
    hauptlauf()
