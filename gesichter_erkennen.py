"""
Automatische Gesichtserkennung für hochgeladene Fotos.

Läuft periodisch (per systemd-Timer, siehe deploy/kalender-gesichter.*) neben der
eigentlichen Flask-App. Trainiert ein leichtgewichtiges LBPH-Modell aus den
Avatar-Fotos der hinterlegten Personen und gleicht damit alle noch nicht
verarbeiteten Fotos ab. Treffer werden als "auto"-Vorschlag in bild_personen
eingetragen (bestätigte Zuordnungen werden nie überschrieben).

Eigene DB-Verbindung wie migrieren.py — kein Import von app.py nötig/gewollt.
"""
import os
import sqlite3

import cv2
import numpy as np

DB_PATH = os.path.join(os.path.dirname(__file__), 'kalender.db')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
MODELS_DIR = os.path.join(os.path.dirname(__file__), 'models', 'face_detector')

VIDEO_EXTENSIONS = {'mp4', 'mov', 'webm', 'avi', 'mkv', 'm4v'}

FACE_SIZE = (200, 200)
BATCH_LIMIT = 20
DETECTOR_MIN_CONFIDENCE = 0.5  # nur für den DNN-Detektor
LBPH_MAX_DISTANCE = 70  # LBPH: niedriger Wert = besserer Match. Nach Praxistests anpassen.


def ist_video(dateiname):
    return '.' in dateiname and dateiname.rsplit('.', 1)[1].lower() in VIDEO_EXTENSIONS


def lade_detektor():
    prototxt = os.path.join(MODELS_DIR, 'deploy.prototxt')
    caffemodel = os.path.join(MODELS_DIR, 'res10_300x300_ssd_iter_140000_fp16.caffemodel')
    if os.path.exists(prototxt) and os.path.exists(caffemodel):
        net = cv2.dnn.readNetFromCaffe(prototxt, caffemodel)

        def detect(image_bgr):
            h, w = image_bgr.shape[:2]
            blob = cv2.dnn.blobFromImage(cv2.resize(image_bgr, (300, 300)), 1.0,
                                          (300, 300), (104.0, 177.0, 123.0))
            net.setInput(blob)
            detections = net.forward()
            boxen = []
            for i in range(detections.shape[2]):
                konfidenz = float(detections[0, 0, i, 2])
                if konfidenz < DETECTOR_MIN_CONFIDENCE:
                    continue
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                x1, y1, x2, y2 = box.astype(int)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                if x2 > x1 and y2 > y1:
                    boxen.append((x1, y1, x2 - x1, y2 - y1))
            return boxen

        print("Gesichtsdetektor: DNN (res10_300x300_ssd)")
        return detect

    print("Gesichtsdetektor: DNN-Modelldateien fehlen in models/face_detector/ — "
          "verwende Haar-Cascade-Fallback (weniger genau).")
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

    def detect_haar(image_bgr):
        grau = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gesichter = cascade.detectMultiScale(grau, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        return [tuple(g) for g in gesichter]

    return detect_haar


def gesicht_zuschneiden(image_bgr, box):
    x, y, w, h = box
    crop = image_bgr[y:y + h, x:x + w]
    grau = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.resize(grau, FACE_SIZE)


def groesste_box(boxen):
    return max(boxen, key=lambda b: b[2] * b[3])


def trainingsdaten_aufbauen(conn, detect_faces):
    bilder, labels = [], []
    personen = conn.execute("SELECT id, name, avatar FROM personen WHERE avatar IS NOT NULL").fetchall()
    for p in personen:
        pfad = os.path.join(UPLOAD_FOLDER, p['avatar'])
        avatar = cv2.imread(pfad)
        if avatar is None:
            print(f"  Warnung: Avatar von '{p['name']}' konnte nicht gelesen werden ({p['avatar']}).")
            continue
        boxen = detect_faces(avatar)
        if not boxen:
            print(f"  Warnung: Kein Gesicht im Avatar von '{p['name']}' erkannt — wird nicht trainiert.")
            continue
        bilder.append(gesicht_zuschneiden(avatar, groesste_box(boxen)))
        labels.append(p['id'])
    return bilder, labels


def hauptlauf():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    detect_faces = lade_detektor()

    trainingsbilder, labels = trainingsdaten_aufbauen(conn, detect_faces)
    if not trainingsbilder:
        print("Keine Trainingsdaten – überspringe diesen Durchlauf.")
        conn.close()
        return

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(trainingsbilder, np.array(labels))
    print(f"LBPH-Modell trainiert mit {len(trainingsbilder)} Gesicht(ern) von "
          f"{len(set(labels))} Person(en).")

    kandidaten = conn.execute(
        "SELECT id, dateiname FROM bilder WHERE gesicht_status='ausstehend' ORDER BY id LIMIT ?",
        (BATCH_LIMIT,)
    ).fetchall()

    verarbeitet = uebersprungen = fehler = 0

    for bild in kandidaten:
        bild_id, dateiname = bild['id'], bild['dateiname']
        if ist_video(dateiname):
            conn.execute("UPDATE bilder SET gesicht_status='uebersprungen' WHERE id=?", (bild_id,))
            conn.commit()
            uebersprungen += 1
            continue

        try:
            pfad = os.path.join(UPLOAD_FOLDER, dateiname)
            image = cv2.imread(pfad)
            if image is None:
                raise ValueError(f"Bilddatei nicht lesbar: {dateiname}")

            for box in detect_faces(image):
                gesicht = gesicht_zuschneiden(image, box)
                person_id, distanz = recognizer.predict(gesicht)
                if distanz <= LBPH_MAX_DISTANCE:
                    conn.execute(
                        "INSERT OR IGNORE INTO bild_personen (bild_id, person_id, quelle) VALUES (?, ?, 'auto')",
                        (bild_id, int(person_id))
                    )

            conn.execute("UPDATE bilder SET gesicht_status='erledigt' WHERE id=?", (bild_id,))
            conn.commit()
            verarbeitet += 1
        except Exception as exc:
            print(f"  Fehler bei Bild {bild_id} ('{dateiname}'): {exc}")
            conn.execute("UPDATE bilder SET gesicht_status='fehler' WHERE id=?", (bild_id,))
            conn.commit()
            fehler += 1

    conn.close()
    print(f"Fertig: {verarbeitet} verarbeitet, {uebersprungen} übersprungen, {fehler} Fehler.")


if __name__ == '__main__':
    hauptlauf()
