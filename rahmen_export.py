"""
Exportiert nachts ein kleines Manifest (bilder/bild_personen/personen) für den
Bilderrahmen beim Vater. Der Rahmen-Pi zieht sich diese Datei per rsync und
entscheidet lokal, welche Fotos er anhand seines Personenfilters nachlädt.

Eigene DB-Verbindung wie migrieren.py/gesichter_erkennen.py — kein Import von
app.py nötig/gewollt.
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), 'kalender.db')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
EXPORT_DIR = os.path.join(os.path.dirname(__file__), 'rahmen_export')
MANIFEST_PATH = os.path.join(EXPORT_DIR, 'manifest.db')
MANIFEST_TMP_PATH = MANIFEST_PATH + '.tmp'

VIDEO_EXTENSIONS = {'mp4', 'mov', 'webm', 'avi', 'mkv', 'm4v'}


def ist_video(dateiname):
    return '.' in dateiname and dateiname.rsplit('.', 1)[1].lower() in VIDEO_EXTENSIONS


def datei_geaendert(dateiname):
    """Aenderungszeit der Fotodatei (ganze Sekunden). Der Rahmen vergleicht sie
    mit seiner Kopie, um z.B. gedrehte Fotos neu zu holen."""
    try:
        return int(os.path.getmtime(os.path.join(UPLOAD_FOLDER, dateiname)))
    except OSError:
        return None


def hauptlauf():
    os.makedirs(EXPORT_DIR, exist_ok=True)
    if os.path.exists(MANIFEST_TMP_PATH):
        os.remove(MANIFEST_TMP_PATH)

    quelle = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    quelle.row_factory = sqlite3.Row

    ziel = sqlite3.connect(MANIFEST_TMP_PATH)
    ziel.executescript('''
        CREATE TABLE bilder (
            id INTEGER PRIMARY KEY,
            dateiname TEXT NOT NULL,
            datum TEXT NOT NULL,
            ist_video INTEGER NOT NULL,
            geaendert INTEGER
        );
        CREATE TABLE bild_personen (
            bild_id INTEGER NOT NULL,
            person_id INTEGER NOT NULL
        );
        CREATE TABLE personen (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
    ''')

    bilder = quelle.execute("SELECT id, dateiname, datum FROM bilder").fetchall()
    ziel.executemany(
        "INSERT INTO bilder (id, dateiname, datum, ist_video, geaendert) VALUES (?, ?, ?, ?, ?)",
        [(b['id'], b['dateiname'], b['datum'], 1 if ist_video(b['dateiname']) else 0,
          datei_geaendert(b['dateiname'])) for b in bilder]
    )

    bild_personen = quelle.execute("SELECT bild_id, person_id FROM bild_personen").fetchall()
    ziel.executemany(
        "INSERT INTO bild_personen (bild_id, person_id) VALUES (?, ?)",
        [(r['bild_id'], r['person_id']) for r in bild_personen]
    )

    personen = quelle.execute("SELECT id, name FROM personen ORDER BY name").fetchall()
    ziel.executemany(
        "INSERT INTO personen (id, name) VALUES (?, ?)",
        [(p['id'], p['name']) for p in personen]
    )

    ziel.commit()
    ziel.close()
    quelle.close()

    os.replace(MANIFEST_TMP_PATH, MANIFEST_PATH)
    print(f"Manifest exportiert: {len(bilder)} Bilder, {len(personen)} Personen.")


if __name__ == '__main__':
    hauptlauf()
