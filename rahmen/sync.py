"""
Naechtlicher Sync fuer den Bilderrahmen: zieht das Manifest vom Haupt-Pi,
berechnet anhand des lokalen Personenfilters welche Fotos erlaubt sind,
holt nur diese per rsync und raeumt bei Bedarf die aeltesten (nicht
favorisierten) Fotos raus, wenn der USB-Stick zu voll wird.

Eigene sqlite3-Verbindung, kein Flask-Import - gleiches Muster wie
gesichter_erkennen.py/rahmen_export.py.
"""
import os
import shutil
import sqlite3
import subprocess
import tempfile

RAHMEN_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(RAHMEN_DIR, 'rahmen.db')
MANIFEST_PATH = os.path.join(RAHMEN_DIR, 'manifest_latest.db')

# Auf der echten Hardware anzupassen, sobald der USB-Stick gemountet ist
# (siehe deploy/README.md) - siehe Plan §6.
FOTOS_DIR = os.environ.get('RAHMEN_FOTOS_DIR', '/mnt/rahmen-fotos')

HAUPT_PI_HOST = os.environ.get('RAHMEN_HAUPT_PI_HOST', 'home-pi')
HAUPT_PI_USER = os.environ.get('RAHMEN_HAUPT_PI_USER', 'tay')
HAUPT_PI_PFAD = os.environ.get('RAHMEN_HAUPT_PI_PFAD', '/home/tay/kalender')

QUOTA_SCHWELLE = 0.90


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def init_db(conn):
    """Legt das Schema an, falls rahmen/app.py auf diesem Geraet noch nie
    gelaufen ist (z.B. wenn der naechtliche Sync-Timer vor dem ersten
    App-Start feuert). Gleiches Schema wie in rahmen/app.py."""
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS einstellungen (
            schluessel TEXT PRIMARY KEY,
            wert TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS personen_cache (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            erlaubt INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS fotos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quelle_bild_id INTEGER NOT NULL UNIQUE,
            lokaler_dateiname TEXT NOT NULL,
            datum TEXT NOT NULL,
            ist_video INTEGER NOT NULL DEFAULT 0,
            favorit INTEGER NOT NULL DEFAULT 0,
            synced_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    ''')
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('sprache', 'de')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('anzeige_dauer_sek', '8')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('uebergang_typ', 'fade')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('uebergang_dauer_ms', '800')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('videos_aktiv', '1')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('datum_anzeigen', '1')")
    conn.commit()


def manifest_holen():
    quelle = f"{HAUPT_PI_USER}@{HAUPT_PI_HOST}:{HAUPT_PI_PFAD}/rahmen_export/manifest.db"
    subprocess.run(['rsync', '-az', quelle, MANIFEST_PATH], check=True)


def personen_cache_aktualisieren(conn, manifest):
    for p in manifest.execute("SELECT id, name FROM personen").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO personen_cache (id, name, erlaubt) VALUES (?, ?, 0)",
            (p['id'], p['name'])
        )
        conn.execute("UPDATE personen_cache SET name=? WHERE id=?", (p['name'], p['id']))
    conn.commit()


def erlaubte_personen_ids(conn):
    rows = conn.execute("SELECT id FROM personen_cache WHERE erlaubt=1").fetchall()
    return {r['id'] for r in rows}


def einstellung(conn, schluessel, default):
    row = conn.execute("SELECT wert FROM einstellungen WHERE schluessel=?", (schluessel,)).fetchone()
    return row['wert'] if row else default


def kandidaten_berechnen(manifest, erlaubte_ids, videos_aktiv):
    """Liefert {bild_id: (dateiname, datum, ist_video)} fuer alle Fotos, die
    laut Personenfilter UND Video-Einstellung geladen werden duerfen."""
    tags_pro_bild = {}
    for row in manifest.execute("SELECT bild_id, person_id FROM bild_personen").fetchall():
        tags_pro_bild.setdefault(row['bild_id'], set()).add(row['person_id'])

    kandidaten = {}
    for b in manifest.execute("SELECT id, dateiname, datum, ist_video FROM bilder").fetchall():
        personen = tags_pro_bild.get(b['id'])
        if not personen:
            continue  # keine Person getaggt -> nicht anzeigen (Datenschutz-Entscheidung)
        if not personen.issubset(erlaubte_ids):
            continue  # mindestens eine nicht erlaubte Person auf dem Foto
        if b['ist_video'] and not videos_aktiv:
            continue
        kandidaten[b['id']] = (b['dateiname'], b['datum'], b['ist_video'])
    return kandidaten


def fotos_abgleichen(conn, kandidaten):
    vorhandene = {
        r['quelle_bild_id']: r for r in conn.execute("SELECT * FROM fotos").fetchall()
    }
    neu_ids = set(kandidaten) - set(vorhandene)
    entfernen_ids = set(vorhandene) - set(kandidaten)
    return neu_ids, entfernen_ids, vorhandene


def alte_fotos_entfernen(conn, entfernen_ids, vorhandene):
    for bild_id in entfernen_ids:
        row = vorhandene[bild_id]
        pfad = os.path.join(FOTOS_DIR, row['lokaler_dateiname'])
        if os.path.exists(pfad):
            os.remove(pfad)
        conn.execute("DELETE FROM fotos WHERE id=?", (row['id'],))
    conn.commit()


def neue_fotos_holen(conn, neu_ids, kandidaten):
    if not neu_ids:
        return 0
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
        for bild_id in neu_ids:
            f.write(kandidaten[bild_id][0] + '\n')
        liste_pfad = f.name

    try:
        quelle = f"{HAUPT_PI_USER}@{HAUPT_PI_HOST}:{HAUPT_PI_PFAD}/static/uploads/"
        subprocess.run(
            ['rsync', '-az', f'--files-from={liste_pfad}', quelle, FOTOS_DIR + '/'],
            check=True
        )
    finally:
        os.remove(liste_pfad)

    geholt = 0
    for bild_id in neu_ids:
        dateiname, datum, ist_video = kandidaten[bild_id]
        if not os.path.exists(os.path.join(FOTOS_DIR, dateiname)):
            continue  # rsync konnte die Datei nicht holen (z.B. zwischenzeitlich geloescht)
        conn.execute(
            "INSERT INTO fotos (quelle_bild_id, lokaler_dateiname, datum, ist_video, favorit) "
            "VALUES (?, ?, ?, ?, 0)",
            (bild_id, dateiname, datum, ist_video)
        )
        geholt += 1
    conn.commit()
    return geholt


def speicher_aufraeumen(conn):
    entfernt = 0
    while True:
        usage = shutil.disk_usage(FOTOS_DIR)
        if usage.used / usage.total <= QUOTA_SCHWELLE:
            break
        row = conn.execute(
            "SELECT id, lokaler_dateiname FROM fotos WHERE favorit=0 "
            "ORDER BY datum ASC, synced_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            print("Warnung: Speicher > 90% belegt, aber nur noch favorisierte Fotos vorhanden.")
            break
        pfad = os.path.join(FOTOS_DIR, row['lokaler_dateiname'])
        if os.path.exists(pfad):
            os.remove(pfad)
        conn.execute("DELETE FROM fotos WHERE id=?", (row['id'],))
        conn.commit()
        entfernt += 1
    return entfernt


def hauptlauf():
    os.makedirs(FOTOS_DIR, exist_ok=True)

    manifest_holen()

    conn = get_db()
    manifest = sqlite3.connect(f"file:{MANIFEST_PATH}?mode=ro", uri=True)
    manifest.row_factory = sqlite3.Row

    personen_cache_aktualisieren(conn, manifest)
    erlaubte_ids = erlaubte_personen_ids(conn)
    videos_aktiv = einstellung(conn, 'videos_aktiv', '1') == '1'

    kandidaten = kandidaten_berechnen(manifest, erlaubte_ids, videos_aktiv)
    manifest.close()

    neu_ids, entfernen_ids, vorhandene = fotos_abgleichen(conn, kandidaten)
    alte_fotos_entfernen(conn, entfernen_ids, vorhandene)
    geholt = neue_fotos_holen(conn, neu_ids, kandidaten)
    entfernt_wegen_quota = speicher_aufraeumen(conn)

    conn.close()
    print(
        f"Sync fertig: {geholt} neu geholt, {len(entfernen_ids)} nicht mehr erlaubt entfernt, "
        f"{entfernt_wegen_quota} wegen Speicherplatz entfernt."
    )


if __name__ == '__main__':
    hauptlauf()
