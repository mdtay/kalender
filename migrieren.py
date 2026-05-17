"""
Migriert die bestehende Datenbank auf das neue Schema (mehrere Ereignisse pro Tag).
Sicher ausführen: bestehende Daten bleiben erhalten.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'kalender.db')
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = OFF")

print("Starte Migration...")

# 1. Neue Tabellen anlegen (falls noch nicht vorhanden)
conn.executescript('''
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
''')
conn.commit()
print("  Neue Tabellen erstellt.")

# 2. Alte Tage-Einträge als Ereignisse übernehmen
tage = conn.execute("SELECT * FROM tage").fetchall()
datum_zu_ereignis = {}

for tag in tage:
    # Prüfen ob schon ein Ereignis für dieses Datum existiert
    existing = conn.execute(
        "SELECT id FROM ereignisse WHERE datum=?", (tag['datum'],)
    ).fetchone()

    if existing:
        eid = existing['id']
    else:
        conn.execute(
            "INSERT INTO ereignisse (datum, titel, text) VALUES (?, '', ?)",
            (tag['datum'], tag['text'])
        )
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    datum_zu_ereignis[tag['datum']] = eid

    # Kategorien übertragen
    kats = conn.execute(
        "SELECT kategorie_id FROM tag_kategorien WHERE tag_id=?", (tag['id'],)
    ).fetchall()
    for k in kats:
        conn.execute(
            "INSERT OR IGNORE INTO ereignis_kategorien VALUES (?,?)",
            (eid, k['kategorie_id'])
        )

conn.commit()
print(f"  {len(tage)} Tage-Einträge als Ereignisse übernommen.")

# 3. ereignis_id Spalte zu bilder hinzufügen (falls noch nicht vorhanden)
spalten = [r[1] for r in conn.execute("PRAGMA table_info(bilder)").fetchall()]
if 'ereignis_id' not in spalten:
    conn.execute("ALTER TABLE bilder ADD COLUMN ereignis_id INTEGER")
    conn.commit()
    print("  Spalte 'ereignis_id' zu bilder hinzugefügt.")

# 4. Bilder mit dem passenden Ereignis verknüpfen
bilder = conn.execute("SELECT * FROM bilder WHERE ereignis_id IS NULL").fetchall()
for bild in bilder:
    datum = bild['datum']
    if datum in datum_zu_ereignis:
        eid = datum_zu_ereignis[datum]
    else:
        # Kein Tageseintrag vorhanden -> neues Ereignis anlegen
        conn.execute(
            "INSERT INTO ereignisse (datum, titel, text) VALUES (?, '', '')", (datum,)
        )
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        datum_zu_ereignis[datum] = eid

    conn.execute("UPDATE bilder SET ereignis_id=? WHERE id=?", (eid, bild['id']))

conn.commit()
print(f"  {len(bilder)} Bilder verknüpft.")

conn.execute("PRAGMA foreign_keys = ON")
conn.close()
print("\nMigration erfolgreich abgeschlossen!")
print("Du kannst jetzt 'python app.py' starten.")
