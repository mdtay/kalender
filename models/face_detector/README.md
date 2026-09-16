# Gesichtsdetektor-Modell

`gesichter_erkennen.py` erwartet hier optional die Standard-OpenCV-Modelldateien
für den DNN-Gesichtsdetektor (res10_300x300_ssd, BSD-lizenziert, Teil der
offiziellen OpenCV-Samples):

- `deploy.prototxt`
- `res10_300x300_ssd_iter_140000_fp16.caffemodel`

Quelle (zum Zeitpunkt der Implementierung aktuelle URLs prüfen):
- `deploy.prototxt`: `opencv/opencv` Repo, `samples/dnn/face_detector/`
- `.caffemodel`: `opencv/opencv_3rdparty` Repo (dort liegen die Gewichte wegen
  der Repo-Größe separat)

**Ohne diese Dateien funktioniert die Erkennung trotzdem** — das Skript fällt
automatisch auf die in OpenCV eingebaute Haar-Cascade zurück (etwas
ungenauer, aber ohne zusätzlichen Download nutzbar).
