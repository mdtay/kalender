import os
import sqlite3

from flask import Flask, request, redirect, url_for, render_template, send_from_directory, jsonify

from i18n import t

RAHMEN_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(RAHMEN_DIR, 'rahmen.db')
FOTOS_DIR = os.environ.get('RAHMEN_FOTOS_DIR', '/mnt/rahmen-fotos')

app = Flask(__name__)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
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
    conn.commit()
    conn.close()


def bytes_human(b):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def alle_einstellungen(conn):
    rows = conn.execute("SELECT schluessel, wert FROM einstellungen").fetchall()
    return {r['schluessel']: r['wert'] for r in rows}


@app.context_processor
def i18n_context():
    conn = get_db()
    sprache = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel='sprache'"
    ).fetchone()
    conn.close()
    sprache = sprache['wert'] if sprache else 'de'
    return {'t': lambda schluessel: t(schluessel, sprache), 'sprache': sprache}


@app.route('/')
def diashow():
    conn = get_db()
    einst = alle_einstellungen(conn)
    conn.close()
    return render_template('diashow.html', einst=einst)


@app.route('/api/fotos')
def api_fotos():
    conn = get_db()
    videos_aktiv = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel='videos_aktiv'"
    ).fetchone()['wert'] == '1'
    if videos_aktiv:
        rows = conn.execute(
            "SELECT id, lokaler_dateiname, ist_video, favorit FROM fotos ORDER BY RANDOM()"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, lokaler_dateiname, ist_video, favorit FROM fotos "
            "WHERE ist_video=0 ORDER BY RANDOM()"
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/foto/<path:dateiname>')
def foto_datei(dateiname):
    return send_from_directory(FOTOS_DIR, dateiname)


@app.route('/einstellungen', methods=['GET', 'POST'])
def einstellungen():
    conn = get_db()
    if request.method == 'POST':
        person_ids = request.form.getlist('personen')
        conn.execute("UPDATE personen_cache SET erlaubt=0")
        for pid in person_ids:
            conn.execute("UPDATE personen_cache SET erlaubt=1 WHERE id=?", (int(pid),))

        conn.execute(
            "INSERT OR REPLACE INTO einstellungen VALUES ('videos_aktiv', ?)",
            ('1' if request.form.get('videos_aktiv') else '0',)
        )
        conn.execute(
            "INSERT OR REPLACE INTO einstellungen VALUES ('anzeige_dauer_sek', ?)",
            (request.form.get('anzeige_dauer_sek', '8'),)
        )
        conn.execute(
            "INSERT OR REPLACE INTO einstellungen VALUES ('uebergang_typ', ?)",
            (request.form.get('uebergang_typ', 'fade'),)
        )
        conn.execute(
            "INSERT OR REPLACE INTO einstellungen VALUES ('uebergang_dauer_ms', ?)",
            (request.form.get('uebergang_dauer_ms', '800'),)
        )
        sprache = request.form.get('sprache', 'de')
        if sprache in ('de', 'tr'):
            conn.execute("INSERT OR REPLACE INTO einstellungen VALUES ('sprache', ?)", (sprache,))

        conn.commit()
        conn.close()
        return redirect(url_for('einstellungen'))

    einst = alle_einstellungen(conn)
    alle_personen = conn.execute(
        "SELECT * FROM personen_cache ORDER BY name"
    ).fetchall()
    letzter_sync = conn.execute("SELECT MAX(synced_at) as t FROM fotos").fetchone()['t']

    try:
        usage = __import__('shutil').disk_usage(FOTOS_DIR)
        speicher = {
            'belegt': bytes_human(usage.used),
            'gesamt': bytes_human(usage.total),
            'prozent': round(usage.used / usage.total * 100, 1),
        }
    except FileNotFoundError:
        speicher = None

    conn.close()
    return render_template(
        'einstellungen.html', einst=einst, alle_personen=alle_personen,
        letzter_sync=letzter_sync, speicher=speicher
    )


@app.route('/einstellungen/fotos')
def fotos_verwalten():
    seite = max(int(request.args.get('seite', 1)), 1)
    pro_seite = 60
    conn = get_db()
    gesamt = conn.execute("SELECT COUNT(*) as c FROM fotos").fetchone()['c']
    fotos = conn.execute(
        "SELECT * FROM fotos ORDER BY datum DESC LIMIT ? OFFSET ?",
        (pro_seite, (seite - 1) * pro_seite)
    ).fetchall()
    conn.close()
    return render_template(
        'fotos_verwalten.html', fotos=fotos, seite=seite,
        hat_weiter=(seite * pro_seite) < gesamt
    )


@app.route('/foto/<int:foto_id>/favorit', methods=['POST'])
def foto_favorit(foto_id):
    conn = get_db()
    conn.execute("UPDATE fotos SET favorit = 1 - favorit WHERE id=?", (foto_id,))
    conn.commit()
    conn.close()
    next_url = request.form.get('next')
    return redirect(next_url or url_for('fotos_verwalten'))


if __name__ == '__main__':
    init_db()
    print("Bilderrahmen läuft auf http://127.0.0.1:8600")
    app.run(host='127.0.0.1', port=8600)
else:
    init_db()
