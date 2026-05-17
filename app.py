import os
import io
import shutil
import subprocess
import zipfile
import sqlite3
import calendar
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_file, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from PIL import Image as PILImage, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    PILLOW = True
except ImportError:
    PILLOW = False

IMAGE_MAX_PX = 1920
FFMPEG = shutil.which('ffmpeg') is not None

app = Flask(__name__)

_SECRET_KEY_FILE = os.path.join(os.path.dirname(__file__), '.secret_key')
if os.path.exists(_SECRET_KEY_FILE):
    with open(_SECRET_KEY_FILE, 'rb') as _f:
        app.secret_key = _f.read()
else:
    app.secret_key = os.urandom(32)
    with open(_SECRET_KEY_FILE, 'wb') as _f:
        _f.write(app.secret_key)

from datetime import timedelta
app.permanent_session_lifetime = timedelta(days=30)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

DB_PATH = os.path.join(os.path.dirname(__file__), 'kalender.db')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif',
                      'mp4', 'mov', 'webm', 'avi', 'mkv', 'm4v'}
VIDEO_EXTENSIONS = {'mp4', 'mov', 'webm', 'avi', 'mkv', 'm4v'}

WOCHENTAGE = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
MONATE = ['', 'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
          'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']


@app.template_filter('datum_kurz')
def datum_kurz_filter(datum):
    dt = datetime.strptime(datum, '%Y-%m-%d')
    return f"{dt.day}. {MONATE[dt.month]} {dt.year}"


@app.template_filter('kuchendiagramm')
def kuchendiagramm_filter(farben):
    farben = [f for f in farben if f]
    if not farben:
        return 'transparent'
    if len(farben) == 1:
        return farben[0]
    n = len(farben)
    stops = [f"{f} {round(i/n*100)}% {round((i+1)/n*100)}%" for i, f in enumerate(farben)]
    return f"conic-gradient({', '.join(stops)})"


@app.template_filter('hex_darken')
def hex_darken_filter(hex_color, factor=0.82):
    c = hex_color.lstrip('#')
    if len(c) != 6:
        return hex_color
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return f'#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}'


THEMES = {
    'dunkel': {
        'label': 'Dunkel',
        'farbe_bg': '#0f172a', 'farbe_surface': '#1e293b', 'farbe_surface2': '#334155', 'farbe_border': '#475569',
        'farbe_text': '#f1f5f9', 'farbe_text_muted': '#94a3b8',
        'farbe_akzent': '#3b82f6', 'farbe_danger': '#ef4444',
    },
    'hell': {
        'label': 'Hell',
        'farbe_bg': '#f0f4f8', 'farbe_surface': '#ffffff', 'farbe_surface2': '#e2e8f0', 'farbe_border': '#cbd5e1',
        'farbe_text': '#0f172a', 'farbe_text_muted': '#64748b',
        'farbe_akzent': '#2563eb', 'farbe_danger': '#dc2626',
    },
    'sepia': {
        'label': 'Sepia',
        'farbe_bg': '#f5f0e8', 'farbe_surface': '#ede8df', 'farbe_surface2': '#ddd5c5', 'farbe_border': '#c4b49a',
        'farbe_text': '#2c1a0e', 'farbe_text_muted': '#7a5c3a',
        'farbe_akzent': '#b45309', 'farbe_danger': '#b91c1c',
    },
    'synthwave': {
        'label': 'Synthwave',
        'farbe_bg': '#1b1033', 'farbe_surface': '#241648', 'farbe_surface2': '#342060', 'farbe_border': '#5c3d8f',
        'farbe_text': '#f0e6ff', 'farbe_text_muted': '#a78bda',
        'farbe_akzent': '#ff7edb', 'farbe_danger': '#fe4450',
    },
    'monokai': {
        'label': 'Monokai',
        'farbe_bg': '#272822', 'farbe_surface': '#3e3d32', 'farbe_surface2': '#49483e', 'farbe_border': '#75715e',
        'farbe_text': '#f8f8f2', 'farbe_text_muted': '#908b76',
        'farbe_akzent': '#a6e22e', 'farbe_danger': '#f92672',
    },
}
THEME_DEFAULTS = {k: v for k, v in next(iter(THEMES.values())).items() if k != 'label'}

@app.context_processor
def inject_theme():
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT schluessel, wert FROM einstellungen WHERE schluessel LIKE 'farbe_%'"
        ).fetchall()
        conn.close()
        t = {**THEME_DEFAULTS, **{r['schluessel']: r['wert'] for r in rows}}
    except Exception:
        t = dict(THEME_DEFAULTS)
    return {
        'theme_akzent':       t['farbe_akzent'],
        'theme_akzent_hover': hex_darken_filter(t['farbe_akzent']),
        'theme_bg':           t['farbe_bg'],
        'theme_surface':      t['farbe_surface'],
        'theme_surface2':     t.get('farbe_surface2', '#334155'),
        'theme_border':       t.get('farbe_border', '#475569'),
        'theme_text':         t.get('farbe_text', '#f1f5f9'),
        'theme_text_muted':   t.get('farbe_text_muted', '#94a3b8'),
        'theme_danger':       t['farbe_danger'],
    }


@app.template_filter('ist_video')
def ist_video_filter(dateiname):
    return '.' in str(dateiname) and str(dateiname).rsplit('.', 1)[1].lower() in VIDEO_EXTENSIONS


def ist_video(dateiname):
    return '.' in str(dateiname) and str(dateiname).rsplit('.', 1)[1].lower() in VIDEO_EXTENSIONS


def bytes_human(b):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('eingeloggt'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS kategorien (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            farbe TEXT NOT NULL DEFAULT '#3b82f6'
        );
        CREATE TABLE IF NOT EXISTS personen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ereignisse (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            titel TEXT DEFAULT '',
            text TEXT DEFAULT '',
            erstellt_am TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ereignis_kategorien (
            ereignis_id INTEGER REFERENCES ereignisse(id) ON DELETE CASCADE,
            kategorie_id INTEGER REFERENCES kategorien(id) ON DELETE CASCADE,
            PRIMARY KEY (ereignis_id, kategorie_id)
        );
        CREATE TABLE IF NOT EXISTS bilder (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ereignis_id INTEGER REFERENCES ereignisse(id) ON DELETE CASCADE,
            datum TEXT NOT NULL,
            dateiname TEXT NOT NULL,
            beschreibung TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS bild_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bild_id INTEGER REFERENCES bilder(id) ON DELETE CASCADE,
            tag TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bild_personen (
            bild_id INTEGER REFERENCES bilder(id) ON DELETE CASCADE,
            person_id INTEGER REFERENCES personen(id) ON DELETE CASCADE,
            PRIMARY KEY (bild_id, person_id)
        );
        CREATE TABLE IF NOT EXISTS ereignis_personen (
            ereignis_id INTEGER REFERENCES ereignisse(id) ON DELETE CASCADE,
            person_id INTEGER REFERENCES personen(id) ON DELETE CASCADE,
            PRIMARY KEY (ereignis_id, person_id)
        );
        CREATE TABLE IF NOT EXISTS einstellungen (
            schluessel TEXT PRIMARY KEY,
            wert TEXT NOT NULL
        );
        INSERT OR IGNORE INTO einstellungen VALUES ('darstellung',  'punkte');
        INSERT OR IGNORE INTO einstellungen VALUES ('farbe_theme',      'dunkel');
        INSERT OR IGNORE INTO einstellungen VALUES ('farbe_akzent',    '#3b82f6');
        INSERT OR IGNORE INTO einstellungen VALUES ('farbe_bg',        '#0f172a');
        INSERT OR IGNORE INTO einstellungen VALUES ('farbe_surface',   '#1e293b');
        INSERT OR IGNORE INTO einstellungen VALUES ('farbe_surface2',  '#334155');
        INSERT OR IGNORE INTO einstellungen VALUES ('farbe_border',    '#475569');
        INSERT OR IGNORE INTO einstellungen VALUES ('farbe_text',      '#f1f5f9');
        INSERT OR IGNORE INTO einstellungen VALUES ('farbe_text_muted','#94a3b8');
        INSERT OR IGNORE INTO einstellungen VALUES ('farbe_danger',    '#ef4444');
    ''')
    conn.commit()
    # Migration: avatar-Spalte für Personen
    try:
        conn.execute("ALTER TABLE personen ADD COLUMN avatar TEXT DEFAULT NULL")
        conn.commit()
    except Exception:
        pass
    # Migration: thumbnail-Spalte für Bilder
    try:
        conn.execute("ALTER TABLE bilder ADD COLUMN thumbnail TEXT DEFAULT NULL")
        conn.commit()
    except Exception:
        pass
    # Migration: favorit-Spalte für Personen
    try:
        conn.execute("ALTER TABLE personen ADD COLUMN favorit INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    conn.close()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_video_thumbnail(video_filename):
    if not FFMPEG:
        return None
    stem = os.path.splitext(video_filename)[0]
    thumb_name = f"{stem}_thumb.jpg"
    video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
    thumb_path = os.path.join(app.config['UPLOAD_FOLDER'], thumb_name)
    try:
        subprocess.run(
            ['ffmpeg', '-i', video_path, '-ss', '00:00:01', '-frames:v', '1', '-q:v', '2', '-y', thumb_path],
            capture_output=True, timeout=30
        )
        return thumb_name if os.path.exists(thumb_path) else None
    except Exception:
        return None


def datum_formatieren(datum):
    dt = datetime.strptime(datum, '%Y-%m-%d')
    return f"{WOCHENTAGE[dt.weekday()]}, {dt.day}. {MONATE[dt.month]} {dt.year}"


def bild_speichern(file):
    filename = secure_filename(file.filename)
    base, ext = os.path.splitext(filename)

    # HEIC/HEIF → JPEG
    if ext.lower() in {'.heic', '.heif'}:
        ext = '.jpg'
        filename = base + ext

    counter = 1
    target = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    while os.path.exists(target):
        filename = f"{base}_{counter}{ext}"
        target = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        counter += 1

    if ist_video(filename):
        file.save(target)
        return filename

    data = file.read()
    if PILLOW:
        try:
            img = PILImage.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img)
            if img.width > IMAGE_MAX_PX or img.height > IMAGE_MAX_PX:
                img.thumbnail((IMAGE_MAX_PX, IMAGE_MAX_PX), PILImage.LANCZOS)
            if ext.lower() in {'.jpg', '.jpeg'} and img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(target)
            return filename
        except Exception:
            pass

    with open(target, 'wb') as f:
        f.write(data)
    return filename


# ── Monatsansicht ──────────────────────────────────────────────────────────────

# ── Auth ───────────────────────────────────────────────────────────────────────

def get_passwort_hash():
    conn = get_db()
    row = conn.execute("SELECT wert FROM einstellungen WHERE schluessel='passwort_hash'").fetchone()
    conn.close()
    return row['wert'] if row else None


@app.route('/login', methods=['GET', 'POST'])
def login():
    passwort_hash = get_passwort_hash()
    if not passwort_hash:
        return redirect(url_for('passwort_einrichten'))
    fehler = None
    if request.method == 'POST':
        if check_password_hash(passwort_hash, request.form.get('passwort', '')):
            session.permanent = True
            session['eingeloggt'] = True
            return redirect(request.args.get('next') or url_for('index'))
        fehler = 'Falsches Passwort.'
    return render_template('login.html', fehler=fehler)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/passwort-einrichten', methods=['GET', 'POST'])
def passwort_einrichten():
    passwort_hash = get_passwort_hash()
    if passwort_hash and not session.get('eingeloggt'):
        return redirect(url_for('login'))
    if request.method == 'POST':
        pw = request.form.get('passwort', '')
        pw2 = request.form.get('passwort2', '')
        if len(pw) < 6:
            return render_template('passwort_einrichten.html', fehler='Mindestens 6 Zeichen.')
        if pw != pw2:
            return render_template('passwort_einrichten.html', fehler='Passwörter stimmen nicht überein.')
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO einstellungen VALUES ('passwort_hash', ?)",
                     (generate_password_hash(pw),))
        conn.commit()
        conn.close()
        session['eingeloggt'] = True
        return redirect(url_for('index'))
    return render_template('passwort_einrichten.html', fehler=None)


@app.route('/')
@login_required
def index():
    heute = date.today()
    return redirect(url_for('monat', jahr=heute.year, monat=heute.month))


@app.route('/monat/<int:jahr>/<int:monat>')
@login_required
def monat(jahr, monat):
    kategorie_filter = request.args.getlist('kategorien')
    person_filter = request.args.getlist('personen')
    cat_ids = [int(k) for k in kategorie_filter if k.isdigit()]
    person_ids = [int(p) for p in person_filter if p.isdigit()]
    prefix = f'{jahr:04d}-{monat:02d}-%'

    conn = get_db()

    # Kategorie-Farbpunkte — beide Filter berücksichtigen
    tage_daten = {}
    sql_dots = '''
        SELECT e.datum, k.farbe, k.name
        FROM ereignisse e
        JOIN ereignis_kategorien ek ON ek.ereignis_id = e.id
        JOIN kategorien k ON k.id = ek.kategorie_id
        WHERE e.datum LIKE ?
    '''
    params_dots = [prefix]
    if cat_ids:
        sql_dots += f" AND ek.kategorie_id IN ({','.join('?' * len(cat_ids))})"
        params_dots += cat_ids
    if person_ids:
        sql_dots += f" AND e.id IN (SELECT ereignis_id FROM ereignis_personen WHERE person_id IN ({','.join('?' * len(person_ids))}))"
        params_dots += person_ids
    for row in conn.execute(sql_dots, params_dots).fetchall():
        d = row['datum']
        if d not in tage_daten:
            tage_daten[d] = []
        if not any(x['farbe'] == row['farbe'] for x in tage_daten[d]):
            tage_daten[d].append({'farbe': row['farbe'], 'name': row['name']})

    # Tage mit Einträgen berechnen (AND-Logik bei mehreren Filtern)
    tage_mit_eintrag = None  # None = noch kein Filter angewandt

    if cat_ids:
        cat_days = {r['datum'] for r in conn.execute(
            f"SELECT DISTINCT e.datum FROM ereignisse e "
            f"JOIN ereignis_kategorien ek ON ek.ereignis_id = e.id "
            f"WHERE e.datum LIKE ? AND ek.kategorie_id IN ({','.join('?' * len(cat_ids))})",
            [prefix] + cat_ids
        ).fetchall()}
        tage_mit_eintrag = cat_days

    if person_ids:
        person_days = {r['datum'] for r in conn.execute(
            f"SELECT DISTINCT e.datum FROM ereignisse e "
            f"JOIN ereignis_personen ep ON ep.ereignis_id = e.id "
            f"WHERE e.datum LIKE ? AND ep.person_id IN ({','.join('?' * len(person_ids))})",
            [prefix] + person_ids
        ).fetchall()}
        tage_mit_eintrag = person_days if tage_mit_eintrag is None else tage_mit_eintrag & person_days

    if tage_mit_eintrag is None:
        # Kein Filter aktiv — alle Tage mit Inhalt
        tage_mit_eintrag = set()
        for r in conn.execute(
            "SELECT DISTINCT datum FROM ereignisse WHERE datum LIKE ? AND (titel != '' OR text != '')",
            (prefix,)
        ).fetchall():
            tage_mit_eintrag.add(r['datum'])
        for r in conn.execute(
            "SELECT DISTINCT datum FROM bilder WHERE datum LIKE ?", (prefix,)
        ).fetchall():
            tage_mit_eintrag.add(r['datum'])

    alle_kategorien = conn.execute("SELECT * FROM kategorien ORDER BY name").fetchall()
    alle_personen = conn.execute("SELECT * FROM personen ORDER BY favorit DESC, name").fetchall()
    darstellung = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel='darstellung'"
    ).fetchone()['wert']
    conn.close()

    cal = calendar.monthcalendar(jahr, monat)
    prev_m = monat - 1 if monat > 1 else 12
    prev_j = jahr if monat > 1 else jahr - 1
    next_m = monat + 1 if monat < 12 else 1
    next_j = jahr if monat < 12 else jahr + 1

    return render_template('kalender.html',
        kalender=cal, jahr=jahr, monat=monat, monat_name=MONATE[monat],
        heute=date.today().isoformat(), tage_daten=tage_daten,
        tage_mit_eintrag=tage_mit_eintrag, darstellung=darstellung,
        prev_monat=prev_m, prev_jahr=prev_j, next_monat=next_m, next_jahr=next_j,
        alle_kategorien=alle_kategorien, kategorie_filter=kategorie_filter,
        alle_personen=alle_personen, person_filter=person_filter,
    )


# ── Tagesansicht ───────────────────────────────────────────────────────────────

@app.route('/tag/<datum>')
@login_required
def tag(datum):
    conn = get_db()

    ereignisse = conn.execute(
        "SELECT * FROM ereignisse WHERE datum=? ORDER BY erstellt_am", (datum,)
    ).fetchall()

    alle_kategorien = conn.execute("SELECT * FROM kategorien ORDER BY name").fetchall()
    alle_personen = conn.execute("SELECT * FROM personen ORDER BY favorit DESC, name").fetchall()

    ereignis_kategorien = {}
    for e in ereignisse:
        rows = conn.execute(
            "SELECT kategorie_id FROM ereignis_kategorien WHERE ereignis_id=?", (e['id'],)
        ).fetchall()
        ereignis_kategorien[e['id']] = {r['kategorie_id'] for r in rows}

    bilder_pro_ereignis = {}
    bild_personen = {}
    for e in ereignisse:
        bilder = conn.execute(
            "SELECT b.*, GROUP_CONCAT(bt.tag, ',') as tags FROM bilder b "
            "LEFT JOIN bild_tags bt ON bt.bild_id=b.id "
            "WHERE b.ereignis_id=? GROUP BY b.id", (e['id'],)
        ).fetchall()
        bilder_pro_ereignis[e['id']] = bilder
        for bild in bilder:
            bp = conn.execute(
                "SELECT person_id FROM bild_personen WHERE bild_id=?", (bild['id'],)
            ).fetchall()
            bild_personen[bild['id']] = {r['person_id'] for r in bp}

    conn.close()

    return render_template('tag.html',
        datum=datum,
        datum_formatiert=datum_formatieren(datum),
        ereignisse=ereignisse,
        alle_kategorien=alle_kategorien,
        alle_personen=alle_personen,
        ereignis_kategorien=ereignis_kategorien,
        bilder_pro_ereignis=bilder_pro_ereignis,
        bild_personen=bild_personen,
    )


# ── Neues Ereignis anlegen ─────────────────────────────────────────────────────

@app.route('/tag/<datum>/neu', methods=['POST'])
@login_required
def ereignis_neu(datum):
    conn = get_db()
    conn.execute("INSERT INTO ereignisse (datum, titel, text) VALUES (?,?,?)", (datum, '', ''))
    eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return redirect(url_for('ereignis_bearbeiten', eid=eid))


# ── Ereignis bearbeiten ────────────────────────────────────────────────────────

@app.route('/ereignis/<int:eid>', methods=['GET', 'POST'])
@login_required
def ereignis_bearbeiten(eid):
    conn = get_db()
    e = conn.execute("SELECT * FROM ereignisse WHERE id=?", (eid,)).fetchone()
    if not e:
        conn.close()
        return redirect(url_for('index'))

    if request.method == 'POST':
        titel = request.form.get('titel', '').strip()
        text = request.form.get('text', '')
        neues_datum = request.form.get('datum', e['datum']).strip() or e['datum']
        kategorie_ids = request.form.getlist('kategorien')
        person_ids = request.form.getlist('ereignis_personen')

        conn.execute("UPDATE ereignisse SET titel=?, text=?, datum=? WHERE id=?",
                     (titel, text, neues_datum, eid))

        if neues_datum != e['datum']:
            conn.execute("UPDATE bilder SET datum=? WHERE ereignis_id=?", (neues_datum, eid))

        conn.execute("DELETE FROM ereignis_kategorien WHERE ereignis_id=?", (eid,))
        for kid in kategorie_ids:
            conn.execute("INSERT OR IGNORE INTO ereignis_kategorien VALUES (?,?)", (eid, int(kid)))

        conn.execute("DELETE FROM ereignis_personen WHERE ereignis_id=?", (eid,))
        for pid in person_ids:
            conn.execute("INSERT OR IGNORE INTO ereignis_personen VALUES (?,?)", (eid, int(pid)))

        conn.commit()
        conn.close()
        return redirect(url_for('tag', datum=neues_datum))

    ausgewaehlte_kategorien = {r['kategorie_id'] for r in conn.execute(
        "SELECT kategorie_id FROM ereignis_kategorien WHERE ereignis_id=?", (eid,)
    ).fetchall()}

    ausgewaehlte_personen = {r['person_id'] for r in conn.execute(
        "SELECT person_id FROM ereignis_personen WHERE ereignis_id=?", (eid,)
    ).fetchall()}

    alle_kategorien = conn.execute("SELECT * FROM kategorien ORDER BY name").fetchall()
    alle_personen = conn.execute("SELECT * FROM personen ORDER BY favorit DESC, name").fetchall()
    alle_tags = conn.execute("SELECT DISTINCT tag FROM bild_tags ORDER BY tag").fetchall()

    bilder = conn.execute(
        "SELECT b.*, GROUP_CONCAT(bt.tag, ',') as tags FROM bilder b "
        "LEFT JOIN bild_tags bt ON bt.bild_id=b.id "
        "WHERE b.ereignis_id=? GROUP BY b.id", (eid,)
    ).fetchall()

    bild_personen = {}
    for bild in bilder:
        bp = conn.execute(
            "SELECT person_id FROM bild_personen WHERE bild_id=?", (bild['id'],)
        ).fetchall()
        bild_personen[bild['id']] = {r['person_id'] for r in bp}

    conn.close()

    return render_template('ereignis.html',
        e=e,
        datum_formatiert=datum_formatieren(e['datum']),
        alle_kategorien=alle_kategorien,
        ausgewaehlte_kategorien=ausgewaehlte_kategorien,
        alle_personen=alle_personen,
        ausgewaehlte_personen=ausgewaehlte_personen,
        alle_tags=alle_tags,
        bilder=bilder,
        bild_personen=bild_personen,
    )


# ── Bilder hochladen (separat) ────────────────────────────────────────────────

@app.route('/ereignis/<int:eid>/bilder', methods=['POST'])
@login_required
def bilder_hochladen(eid):
    conn = get_db()
    e = conn.execute("SELECT * FROM ereignisse WHERE id=?", (eid,)).fetchone()
    if e:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        for file in request.files.getlist('bilder'):
            if file and file.filename and allowed_file(file.filename):
                filename = bild_speichern(file)
                thumb = generate_video_thumbnail(filename) if ist_video(filename) else None
                conn.execute(
                    "INSERT INTO bilder (ereignis_id, datum, dateiname, thumbnail) VALUES (?,?,?,?)",
                    (eid, e['datum'], filename, thumb)
                )
        conn.commit()
    conn.close()
    return redirect(url_for('ereignis_bearbeiten', eid=eid) + '#bilder')


# ── Ereignis löschen ───────────────────────────────────────────────────────────

@app.route('/ereignis/<int:eid>/loeschen', methods=['POST'])
@login_required
def ereignis_loeschen(eid):
    conn = get_db()
    e = conn.execute("SELECT * FROM ereignisse WHERE id=?", (eid,)).fetchone()
    if e:
        datum = e['datum']
        for bild in conn.execute("SELECT * FROM bilder WHERE ereignis_id=?", (eid,)).fetchall():
            pfad = os.path.join(app.config['UPLOAD_FOLDER'], bild['dateiname'])
            if os.path.exists(pfad):
                os.remove(pfad)
        conn.execute("DELETE FROM ereignisse WHERE id=?", (eid,))
        conn.commit()
        conn.close()
        return redirect(url_for('tag', datum=datum))
    conn.close()
    return redirect(url_for('index'))


# ── Bild-Metadaten ─────────────────────────────────────────────────────────────

@app.route('/bild/<int:bild_id>/meta', methods=['POST'])
@login_required
def bild_meta(bild_id):
    conn = get_db()
    beschreibung = request.form.get('beschreibung', '')
    tags_raw = request.form.get('tags', '')
    person_ids = request.form.getlist('personen')
    personen_neu = request.form.get('personen_neu', '')

    conn.execute("UPDATE bilder SET beschreibung=? WHERE id=?", (beschreibung, bild_id))
    conn.execute("DELETE FROM bild_tags WHERE bild_id=?", (bild_id,))
    for t in [x.strip() for x in tags_raw.split(',') if x.strip()]:
        conn.execute("INSERT INTO bild_tags (bild_id, tag) VALUES (?,?)", (bild_id, t))

    conn.execute("DELETE FROM bild_personen WHERE bild_id=?", (bild_id,))
    for pid in person_ids:
        conn.execute("INSERT OR IGNORE INTO bild_personen VALUES (?,?)", (bild_id, int(pid)))

    for name in [n.strip() for n in personen_neu.split(',') if n.strip()]:
        conn.execute("INSERT OR IGNORE INTO personen (name) VALUES (?)", (name,))
        p = conn.execute("SELECT id FROM personen WHERE name=?", (name,)).fetchone()
        conn.execute("INSERT OR IGNORE INTO bild_personen VALUES (?,?)", (bild_id, p['id']))

    row = conn.execute("SELECT ereignis_id FROM bilder WHERE id=?", (bild_id,)).fetchone()
    eid = row['ereignis_id'] if row else None
    conn.commit()
    conn.close()
    next_url = request.form.get('next')
    if next_url:
        return redirect(next_url)
    if eid:
        return redirect(url_for('ereignis_bearbeiten', eid=eid))
    return redirect(url_for('diashow'))


# ── Bild einem Ereignis zuweisen ──────────────────────────────────────────────

@app.route('/bild/<int:bild_id>/zuweisen', methods=['POST'])
@login_required
def bild_zuweisen(bild_id):
    eid = request.form.get('ereignis_id', type=int)
    if eid:
        conn = get_db()
        e = conn.execute("SELECT * FROM ereignisse WHERE id=?", (eid,)).fetchone()
        if e:
            conn.execute("UPDATE bilder SET ereignis_id=?, datum=? WHERE id=?",
                         (eid, e['datum'], bild_id))
            conn.commit()
        conn.close()
    next_url = request.form.get('next')
    return redirect(next_url if next_url else url_for('diashow'))


# ── Bild vom Ereignis lösen ────────────────────────────────────────────────────

@app.route('/bild/<int:bild_id>/loesen', methods=['POST'])
@login_required
def bild_loesen(bild_id):
    conn = get_db()
    conn.execute("UPDATE bilder SET ereignis_id = NULL WHERE id = ?", (bild_id,))
    conn.commit()
    conn.close()
    next_url = request.form.get('next')
    return redirect(next_url if next_url else url_for('diashow'))


# ── Bild löschen ───────────────────────────────────────────────────────────────

@app.route('/bild/<int:bild_id>/drehen', methods=['POST'])
@login_required
def bild_drehen(bild_id):
    conn = get_db()
    bild = conn.execute("SELECT * FROM bilder WHERE id=?", (bild_id,)).fetchone()
    if bild and PILLOW and not ist_video(bild['dateiname']):
        path = os.path.join(app.config['UPLOAD_FOLDER'], bild['dateiname'])
        if os.path.exists(path):
            img = PILImage.open(path)
            img = img.rotate(-90, expand=True)
            img.save(path)
    conn.close()
    return redirect(request.referrer or url_for('ereignis_bearbeiten', eid=bild['ereignis_id']))


@app.route('/bild/<int:bild_id>/loeschen', methods=['POST'])
@login_required
def bild_loeschen(bild_id):
    conn = get_db()
    bild = conn.execute("SELECT * FROM bilder WHERE id=?", (bild_id,)).fetchone()
    if bild:
        pfad = os.path.join(app.config['UPLOAD_FOLDER'], bild['dateiname'])
        if os.path.exists(pfad):
            os.remove(pfad)
        try:
            if bild['thumbnail']:
                thumb_pfad = os.path.join(app.config['UPLOAD_FOLDER'], bild['thumbnail'])
                if os.path.exists(thumb_pfad):
                    os.remove(thumb_pfad)
        except Exception:
            pass
        eid = bild['ereignis_id']
        conn.execute("DELETE FROM bilder WHERE id=?", (bild_id,))
        conn.commit()
        conn.close()
        next_url = request.form.get('next')
        return redirect(next_url if next_url else url_for('ereignis_bearbeiten', eid=eid))
    conn.close()
    return redirect(url_for('index'))


@app.route('/personen/<int:pid>/avatar', methods=['POST'])
@login_required
def person_avatar(pid):
    conn = get_db()
    p = conn.execute("SELECT * FROM personen WHERE id=?", (pid,)).fetchone()
    if p:
        file = request.files.get('avatar')
        if file and file.filename and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() not in VIDEO_EXTENSIONS and allowed_file(file.filename):
            if p['avatar']:
                old = os.path.join(app.config['UPLOAD_FOLDER'], p['avatar'])
                if os.path.exists(old):
                    os.remove(old)
            filename = bild_speichern(file)
            conn.execute("UPDATE personen SET avatar=? WHERE id=?", (filename, pid))
            conn.commit()
    conn.close()
    return redirect(url_for('personen'))


# ── Kategorien ─────────────────────────────────────────────────────────────────

@app.route('/kategorien')
@login_required
def kategorien():
    conn = get_db()
    alle = conn.execute("SELECT * FROM kategorien ORDER BY name").fetchall()
    conn.close()
    return render_template('kategorien.html', kategorien=alle)


@app.route('/kategorien/neu', methods=['POST'])
@login_required
def kategorie_neu():
    name = request.form.get('name', '').strip()
    farbe = request.form.get('farbe', '#3b82f6')
    if name:
        conn = get_db()
        conn.execute("INSERT INTO kategorien (name, farbe) VALUES (?,?)", (name, farbe))
        conn.commit()
        conn.close()
    return redirect(url_for('kategorien'))


@app.route('/kategorien/<int:kid>/bearbeiten', methods=['POST'])
@login_required
def kategorie_bearbeiten(kid):
    name = request.form.get('name', '').strip()
    farbe = request.form.get('farbe', '#3b82f6')
    if name:
        conn = get_db()
        conn.execute("UPDATE kategorien SET name=?, farbe=? WHERE id=?", (name, farbe, kid))
        conn.commit()
        conn.close()
    return redirect(url_for('kategorien'))


@app.route('/kategorien/<int:kid>/loeschen', methods=['POST'])
@login_required
def kategorie_loeschen(kid):
    conn = get_db()
    conn.execute("DELETE FROM kategorien WHERE id=?", (kid,))
    conn.commit()
    conn.close()
    return redirect(url_for('kategorien'))


# ── Personen ───────────────────────────────────────────────────────────────────

@app.route('/personen')
@login_required
def personen():
    conn = get_db()
    alle = conn.execute("SELECT * FROM personen ORDER BY favorit DESC, name").fetchall()
    conn.close()
    return render_template('personen.html', personen=alle)


@app.route('/personen/neu', methods=['POST'])
@login_required
def person_neu():
    name = request.form.get('name', '').strip()
    if name:
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO personen (name) VALUES (?)", (name,))
        conn.commit()
        conn.close()
    return redirect(url_for('personen'))


@app.route('/personen/<int:pid>/bearbeiten', methods=['POST'])
@login_required
def person_bearbeiten(pid):
    name = request.form.get('name', '').strip()
    if name:
        conn = get_db()
        conn.execute("UPDATE personen SET name=? WHERE id=?", (name, pid))
        conn.commit()
        conn.close()
    return redirect(url_for('personen'))


@app.route('/personen/<int:pid>/loeschen', methods=['POST'])
@login_required
def person_loeschen(pid):
    conn = get_db()
    conn.execute("DELETE FROM personen WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return redirect(url_for('personen'))


@app.route('/personen/<int:pid>/favorit', methods=['POST'])
@login_required
def person_favorit(pid):
    conn = get_db()
    conn.execute("UPDATE personen SET favorit = 1 - favorit WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return redirect(url_for('personen'))


# ── Suche ──────────────────────────────────────────────────────────────────────

@app.route('/suche')
@login_required
def suche():
    q = request.args.get('q', '').strip()
    tag_filter = request.args.get('tag', '').strip()
    person_filter = request.args.get('person', '').strip()
    kategorie_filter = request.args.getlist('kategorien')
    von = request.args.get('von', '').strip()
    bis = request.args.get('bis', '').strip()

    conn = get_db()
    ergebnisse_ereignisse = []
    ergebnisse_bilder = []

    if q or von or bis or kategorie_filter or person_filter:
        sql = "SELECT * FROM ereignisse WHERE 1=1"
        p = []
        if q:
            sql += " AND (titel LIKE ? OR text LIKE ?)"
            p += [f'%{q}%', f'%{q}%']
        if kategorie_filter:
            sql += f" AND id IN (SELECT ereignis_id FROM ereignis_kategorien WHERE kategorie_id IN ({','.join('?' * len(kategorie_filter))}))"
            p.extend([int(k) for k in kategorie_filter])
        if person_filter:
            sql += " AND id IN (SELECT ep.ereignis_id FROM ereignis_personen ep JOIN personen per ON per.id=ep.person_id WHERE per.name=?)"
            p.append(person_filter)
        if von:
            sql += " AND datum >= ?"
            p.append(von)
        if bis:
            sql += " AND datum <= ?"
            p.append(bis)
        sql += " ORDER BY datum DESC"
        ergebnisse_ereignisse = conn.execute(sql, p).fetchall()

    if q or tag_filter or person_filter or von or bis:
        sql = """
            SELECT DISTINCT b.* FROM bilder b
            LEFT JOIN bild_tags bt ON bt.bild_id=b.id
            LEFT JOIN bild_personen bp ON bp.bild_id=b.id
            LEFT JOIN personen p ON p.id=bp.person_id
            WHERE 1=1
        """
        p = []
        if q:
            sql += " AND (b.beschreibung LIKE ? OR bt.tag LIKE ?)"
            p += [f'%{q}%', f'%{q}%']
        if tag_filter:
            sql += " AND bt.tag LIKE ?"
            p.append(f'%{tag_filter}%')
        if person_filter:
            sql += " AND p.name LIKE ?"
            p.append(f'%{person_filter}%')
        if von:
            sql += " AND b.datum >= ?"
            p.append(von)
        if bis:
            sql += " AND b.datum <= ?"
            p.append(bis)
        sql += " ORDER BY b.datum DESC"
        ergebnisse_bilder = conn.execute(sql, p).fetchall()

    alle_personen = conn.execute("SELECT * FROM personen ORDER BY favorit DESC, name").fetchall()
    alle_tags = conn.execute("SELECT DISTINCT tag FROM bild_tags ORDER BY tag").fetchall()
    alle_kategorien = conn.execute("SELECT * FROM kategorien ORDER BY name").fetchall()
    conn.close()

    return render_template('suche.html',
        q=q, tag_filter=tag_filter, person_filter=person_filter,
        kategorie_filter=kategorie_filter, von=von, bis=bis,
        ergebnisse_ereignisse=ergebnisse_ereignisse,
        ergebnisse_bilder=ergebnisse_bilder,
        alle_personen=alle_personen, alle_tags=alle_tags,
        alle_kategorien=alle_kategorien,
    )


# ── Diashow / Galerie ──────────────────────────────────────────────────────────

@app.route('/diashow')
@login_required
def diashow():
    tag_filter = request.args.get('tag', '').strip()
    personen_filter = request.args.getlist('personen')
    kategorie_filter = request.args.getlist('kategorien')
    von = request.args.get('von', '').strip()
    bis = request.args.get('bis', '').strip()

    conn = get_db()
    sql = """
        SELECT DISTINCT b.*, e.titel as ereignis_titel, e.id as ereignis_id
        FROM bilder b
        LEFT JOIN ereignisse e ON e.id = b.ereignis_id
        LEFT JOIN bild_tags bt ON bt.bild_id=b.id
        LEFT JOIN bild_personen bp ON bp.bild_id=b.id
        LEFT JOIN personen p ON p.id=bp.person_id
        WHERE 1=1
    """
    params = []
    if tag_filter:
        sql += " AND bt.tag = ?"
        params.append(tag_filter)
    if personen_filter:
        sql += f" AND p.name IN ({','.join('?' * len(personen_filter))})"
        params.extend(personen_filter)
    if kategorie_filter:
        cat_ids = [int(k) for k in kategorie_filter if k.isdigit()]
        if cat_ids:
            sql += f" AND b.ereignis_id IN (SELECT ereignis_id FROM ereignis_kategorien WHERE kategorie_id IN ({','.join('?' * len(cat_ids))}))"
            params.extend(cat_ids)
    if von:
        sql += " AND b.datum >= ?"
        params.append(von)
    if bis:
        sql += " AND b.datum <= ?"
        params.append(bis)
    sql += " ORDER BY b.datum DESC, b.id DESC"

    bilder = conn.execute(sql, params).fetchall()
    gesamt = len(bilder)

    # Monats-Gruppierung
    bilder_nach_monat = []
    for bild in bilder:
        key = bild['datum'][:7]
        if bilder_nach_monat and bilder_nach_monat[-1]['key'] == key:
            bilder_nach_monat[-1]['bilder'].append(bild)
        else:
            jahr, monat = int(key[:4]), int(key[5:])
            bilder_nach_monat.append({
                'key': key,
                'monat_name': f"{MONATE[monat]} {jahr}",
                'bilder': [bild],
            })

    # Kategorie-Farben je Ereignis
    ereignis_ids = list({b['ereignis_id'] for b in bilder if b['ereignis_id']})
    event_kategorien = {}
    if ereignis_ids:
        rows = conn.execute(
            f"SELECT ek.ereignis_id, k.farbe, k.name FROM ereignis_kategorien ek "
            f"JOIN kategorien k ON k.id=ek.kategorie_id "
            f"WHERE ek.ereignis_id IN ({','.join('?'*len(ereignis_ids))})",
            ereignis_ids
        ).fetchall()
        for row in rows:
            event_kategorien.setdefault(row['ereignis_id'], []).append(
                {'farbe': row['farbe'], 'name': row['name']}
            )

    alle_personen = conn.execute("SELECT * FROM personen ORDER BY favorit DESC, name").fetchall()
    alle_tags = conn.execute("SELECT DISTINCT tag FROM bild_tags ORDER BY tag").fetchall()
    alle_kategorien = conn.execute("SELECT * FROM kategorien ORDER BY name").fetchall()
    alle_ereignisse = conn.execute(
        "SELECT id, datum, titel FROM ereignisse ORDER BY datum DESC"
    ).fetchall()
    verfuegbare_jahre = [r['jahr'] for r in conn.execute(
        "SELECT DISTINCT strftime('%Y', datum) as jahr FROM bilder ORDER BY jahr DESC"
    ).fetchall()]

    bild_ids = [b['id'] for b in bilder]
    bild_personen = {}
    bild_tags_map = {}
    if bild_ids:
        ph = ','.join('?' * len(bild_ids))
        for row in conn.execute(
            f"SELECT bild_id, person_id FROM bild_personen WHERE bild_id IN ({ph})", bild_ids
        ):
            bild_personen.setdefault(row['bild_id'], set()).add(row['person_id'])
        for row in conn.execute(
            f"SELECT bild_id, GROUP_CONCAT(tag, ',') as tags FROM bild_tags "
            f"WHERE bild_id IN ({ph}) GROUP BY bild_id", bild_ids
        ):
            bild_tags_map[row['bild_id']] = row['tags'] or ''

    conn.close()

    return render_template('diashow.html',
        bilder=bilder,
        bilder_nach_monat=bilder_nach_monat,
        event_kategorien=event_kategorien,
        alle_personen=alle_personen,
        alle_tags=alle_tags,
        alle_kategorien=alle_kategorien,
        tag_filter=tag_filter,
        personen_filter=personen_filter,
        kategorie_filter=kategorie_filter,
        von=von, bis=bis,
        gesamt=gesamt,
        alle_ereignisse=alle_ereignisse,
        bild_personen=bild_personen,
        bild_tags_map=bild_tags_map,
        verfuegbare_jahre=verfuegbare_jahre,
    )


@app.route('/diashow/download', methods=['POST'])
@login_required
def diashow_download():
    bild_ids = request.form.getlist('bild_ids')
    if not bild_ids:
        return redirect(url_for('diashow'))
    try:
        ids = [int(i) for i in bild_ids]
    except ValueError:
        return redirect(url_for('diashow'))

    conn = get_db()
    bilder = conn.execute(
        f"SELECT * FROM bilder WHERE id IN ({','.join('?' * len(ids))})", ids
    ).fetchall()
    conn.close()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for bild in bilder:
            pfad = os.path.join(app.config['UPLOAD_FOLDER'], bild['dateiname'])
            if os.path.exists(pfad):
                zf.write(pfad, f"{bild['datum']}_{bild['dateiname']}")
    buf.seek(0)

    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name='kalender_bilder.zip')


# ── Backup / Export ────────────────────────────────────────────────────────────

@app.route('/export')
@login_required
def export():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(DB_PATH):
            zf.write(DB_PATH, 'kalender.db')
        upload_dir = app.config['UPLOAD_FOLDER']
        if os.path.exists(upload_dir):
            for fname in os.listdir(upload_dir):
                fpath = os.path.join(upload_dir, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, f"uploads/{fname}")
    buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name=f'kalender_backup_{date.today().isoformat()}.zip')


# ── Einstellungen ──────────────────────────────────────────────────────────────

@app.route('/einstellungen', methods=['GET', 'POST'])
@login_required
def einstellungen():
    conn = get_db()
    if request.method == 'POST':
        if 'darstellung' in request.form:
            conn.execute(
                "INSERT OR REPLACE INTO einstellungen VALUES ('darstellung', ?)",
                (request.form.get('darstellung', 'punkte'),)
            )
        if 'farbe_theme' in request.form:
            name = request.form['farbe_theme']
            if name in THEMES:
                conn.execute("INSERT OR REPLACE INTO einstellungen VALUES ('farbe_theme', ?)", (name,))
                for k, v in THEMES[name].items():
                    if k != 'label':
                        conn.execute("INSERT OR REPLACE INTO einstellungen VALUES (?, ?)", (k, v))
        conn.commit()
        conn.close()
        return redirect(url_for('einstellungen'))
    darstellung = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel='darstellung'"
    ).fetchone()['wert']
    row_theme = conn.execute(
        "SELECT wert FROM einstellungen WHERE schluessel='farbe_theme'"
    ).fetchone()
    aktiver_theme = row_theme['wert'] if row_theme else 'standard'
    alle_tags = conn.execute(
        "SELECT tag, COUNT(*) as anzahl FROM bild_tags GROUP BY tag ORDER BY tag"
    ).fetchall()
    conn.close()
    usage = shutil.disk_usage(app.config['UPLOAD_FOLDER'])
    speicher = {
        'gesamt': bytes_human(usage.total),
        'belegt': bytes_human(usage.used),
        'frei': bytes_human(usage.free),
        'prozent': round(usage.used / usage.total * 100, 1),
    }
    return render_template('einstellungen.html', darstellung=darstellung,
                           themes=THEMES, aktiver_theme=aktiver_theme,
                           speicher=speicher, alle_tags=alle_tags)


@app.route('/einstellungen/tag/<path:tag>/loeschen', methods=['POST'])
@login_required
def tag_loeschen(tag):
    conn = get_db()
    conn.execute("DELETE FROM bild_tags WHERE tag=?", (tag,))
    conn.commit()
    conn.close()
    return redirect(url_for('einstellungen'))


if __name__ == '__main__':
    init_db()
    print("Kalender läuft auf http://127.0.0.1:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
