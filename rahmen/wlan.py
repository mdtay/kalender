"""
WLAN-Verwaltung fuer den Rahmen ueber NetworkManager (nmcli).

Neue Zugangsdaten landen immer in einem eigenen, neuen Verbindungsprofil.
Klappt die Verbindung nicht (z.B. falsches Passwort), wird nur dieses neue
Profil geloescht - das bisher funktionierende WLAN bleibt unangetastet und
NetworkManager verbindet sich automatisch wieder damit. Wichtig, weil der
Rahmen im Ausland steht und sonst nur noch vor Ort repariert werden koennte.
"""
import subprocess
import time

PROFIL_PRAEFIX = 'rahmen-'
RECHTE_FEHLER = ('not authorized', 'insufficient privileges', 'nicht berechtigt')


def _nmcli(args, timeout=45):
    """Fuehrt nmcli aus; fehlen Rechte, nochmal per 'sudo -n' (siehe
    deploy/README.md fuer die sudoers-Regel). Liefert (ok, ausgabe)."""
    try:
        erg = subprocess.run(['nmcli'] + args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return False, 'nmcli nicht gefunden'
    except subprocess.TimeoutExpired:
        return False, 'Zeitueberschreitung'
    ausgabe = (erg.stdout + erg.stderr).strip()
    if erg.returncode != 0 and any(m in ausgabe.lower() for m in RECHTE_FEHLER):
        try:
            erg = subprocess.run(['sudo', '-n', 'nmcli'] + args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, 'Zeitueberschreitung'
        ausgabe = (erg.stdout + erg.stderr).strip()
    return erg.returncode == 0, ausgabe


def _terse_felder(zeile):
    """Zerlegt eine 'nmcli -t'-Zeile; ':' und '\\' in Werten sind mit '\\' maskiert."""
    felder, aktuell, i = [], '', 0
    while i < len(zeile):
        zeichen = zeile[i]
        if zeichen == '\\' and i + 1 < len(zeile):
            aktuell += zeile[i + 1]
            i += 2
            continue
        if zeichen == ':':
            felder.append(aktuell)
            aktuell = ''
        else:
            aktuell += zeichen
        i += 1
    felder.append(aktuell)
    return felder


def netzwerke_suchen():
    """Liefert (aktuelle_ssid_oder_None, [{'ssid', 'signal', 'gesichert'}, ...])
    nach Signalstaerke sortiert, oder wirft RuntimeError mit nmcli-Meldung."""
    ok, ausgabe = _nmcli(['-t', '-f', 'ACTIVE,SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list', '--rescan', 'yes'])
    if not ok:
        raise RuntimeError(ausgabe.splitlines()[0] if ausgabe else 'nmcli Fehler')
    aktuell = None
    netze = {}
    for zeile in ausgabe.splitlines():
        felder = _terse_felder(zeile)
        if len(felder) < 4 or not felder[1]:
            continue
        aktiv, ssid, signal, sicherheit = felder[0], felder[1], felder[2], felder[3]
        if aktiv == 'yes':
            aktuell = ssid
        signal = int(signal) if signal.isdigit() else 0
        if ssid not in netze or netze[ssid]['signal'] < signal:
            netze[ssid] = {'ssid': ssid, 'signal': signal, 'gesichert': sicherheit not in ('', '--')}
    return aktuell, sorted(netze.values(), key=lambda n: -n['signal'])


def verbinden(ssid, passwort):
    """Legt ein neues Profil an und aktiviert es. Liefert (ok, meldung)."""
    profil = f"{PROFIL_PRAEFIX}{ssid}-{int(time.time())}"
    args = ['connection', 'add', 'type', 'wifi', 'con-name', profil, 'ssid', ssid,
            'connection.autoconnect-priority', '10']
    if passwort:
        args += ['wifi-sec.key-mgmt', 'wpa-psk', 'wifi-sec.psk', passwort]
    ok, ausgabe = _nmcli(args)
    if not ok:
        return False, ausgabe

    ok, ausgabe = _nmcli(['--wait', '40', 'connection', 'up', profil], timeout=60)
    if not ok:
        _nmcli(['connection', 'delete', profil])
        return False, ausgabe

    # Aeltere Rahmen-Profile fuer dasselbe Netz aufraeumen, sonst sammeln sie
    # sich bei jeder Passwortaenderung an.
    ok_liste, liste = _nmcli(['-t', '-f', 'NAME', 'connection', 'show'])
    if ok_liste:
        for zeile in liste.splitlines():
            name = _terse_felder(zeile)[0]
            if name.startswith(f"{PROFIL_PRAEFIX}{ssid}-") and name != profil:
                _nmcli(['connection', 'delete', name])
    return True, ''
