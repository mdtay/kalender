"""
Natives Bilderrahmen-Kiosk ohne Browser/Webserver.

Laeuft plattformuebergreifend: unter Windows als normales Fenster zum
lokalen Entwickeln/Testen, unter Linux (Rahmen-Pi) im Vollbild via X11.
Liest/schreibt direkt in rahmen.db - dieselbe Datenbank, die rahmen/sync.py
befuellt. Kein Flask, kein HTTP, kein Chromium.
"""
import datetime
import json
import math
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import traceback
from collections import deque

import pygame

from i18n import t

RAHMEN_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(RAHMEN_DIR, 'rahmen.db')
THUMBS_DIR = os.path.join(RAHMEN_DIR, 'thumbnails')
FEHLER_LOG = os.path.join(RAHMEN_DIR, 'kiosk_fehler.log')
SYNC_FORTSCHRITT_PATH = os.path.join(RAHMEN_DIR, 'sync_progress.json')
IST_LINUX = sys.platform.startswith('linux')
FOTOS_DIR = os.environ.get(
    'RAHMEN_FOTOS_DIR',
    '/mnt/rahmen-fotos' if IST_LINUX else os.path.join(RAHMEN_DIR, 'fotos_test')
)


def fehler_loggen(kontext):
    """Schreibt Zeitstempel + Traceback nach kiosk_fehler.log, wirft nie selbst."""
    try:
        with open(FEHLER_LOG, 'a', encoding='utf-8') as f:
            f.write(f"\n[{datetime.datetime.now().isoformat(timespec='seconds')}] {kontext}\n")
            f.write(traceback.format_exc())
    except Exception:
        pass

FOTO_REFRESH_INTERVALL_MS = 60 * 60 * 1000
ZAHNRAD_ANZEIGE_MS = 6000
FPS = 30

FARBE_HINTERGRUND = (0, 0, 0)
FARBE_TEXT = (240, 240, 240)
FARBE_TEXT_GEDAEMPFT = (150, 150, 150)

# ── Helles, modernes Design fuer Einstellungen/Fotos-verwalten ─────────
FARBE_SEITE = (246, 247, 250)
FARBE_KARTE = (255, 255, 255)
FARBE_KARTE_RAND = (228, 230, 236)
FARBE_KARTE_AKTIV = (232, 240, 254)
FARBE_KARTE_AKTIV_RAND = (59, 130, 246)
FARBE_TEXT_DUNKEL = (32, 34, 40)
FARBE_TEXT_DUNKEL_GEDAEMPFT = (120, 124, 136)
FARBE_AKZENT = (59, 130, 246)
FARBE_AKZENT_DUNKEL = (37, 99, 235)
FARBE_TOGGLE_AUS = (210, 213, 222)


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
        CREATE INDEX IF NOT EXISTS idx_fotos_datum ON fotos(datum);
    ''')
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('sprache', 'de')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('anzeige_dauer_sek', '8')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('uebergang_typ', 'fade')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('uebergang_dauer_ms', '800')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('videos_aktiv', '1')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('datum_anzeigen', '1')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('nacht_aktiv', '0')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('nacht_start_stunde', '22')")
    conn.execute("INSERT OR IGNORE INTO einstellungen VALUES ('nacht_ende_stunde', '7')")
    conn.commit()
    conn.close()


def bytes_human(b):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def datum_de_formatieren(iso_text):
    """'2026-09-28 21:15:03' -> '28.09.2026' (nur das Datum, ohne Uhrzeit)."""
    if not iso_text:
        return None
    try:
        jahr, monat, tag = iso_text[:10].split('-')
        return f"{tag}.{monat}.{jahr}"
    except ValueError:
        return iso_text


def einstellung_holen(conn, schluessel, default):
    row = conn.execute("SELECT wert FROM einstellungen WHERE schluessel=?", (schluessel,)).fetchone()
    return row['wert'] if row else default


def einstellung_setzen(conn, schluessel, wert):
    conn.execute("INSERT OR REPLACE INTO einstellungen VALUES (?, ?)", (schluessel, str(wert)))
    conn.commit()


MONATSNAMEN = {
    'de': ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
           'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'],
    'tr': ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
           'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'],
}

UEBERGANG_TYPEN_KONKRET = ['fade', 'slide', 'wipe', 'rotate']
UEBERGANG_TYPEN = UEBERGANG_TYPEN_KONKRET + ['random']
DATUM_EINBLEND_DAUER_MS = 350
DATUM_AUSBLEND_START_MS = 3000
DATUM_AUSBLEND_DAUER_MS = 400


def fotos_laden(conn):
    videos_aktiv = einstellung_holen(conn, 'videos_aktiv', '1') == '1'
    if videos_aktiv:
        rows = conn.execute("SELECT id, lokaler_dateiname, ist_video, favorit, datum FROM fotos").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, lokaler_dateiname, ist_video, favorit, datum FROM fotos WHERE ist_video=0"
        ).fetchall()
    return [dict(r) for r in rows]


def reihenfolge_mischen(fotos, zuletzt_ids):
    """Zufaellige Reihenfolge, aber kuerzlich gezeigte Fotos kommen ans Ende
    (aelteste zuerst) und Fotos vom selben Tag stehen moeglichst nicht direkt
    hintereinander."""
    random.shuffle(fotos)
    position = {foto_id: n for n, foto_id in enumerate(zuletzt_ids)}
    frisch = [f for f in fotos if f['id'] not in position]
    kuerzlich = sorted((f for f in fotos if f['id'] in position), key=lambda f: position[f['id']])
    return _tage_verteilen(frisch) + kuerzlich


def _tage_verteilen(fotos, vorausschau=30):
    # Begrenzte Vorausschau statt Komplettsuche: bleibt auch bei 10.000+
    # Fotos auf dem Pi 3 schnell genug.
    for i in range(1, len(fotos)):
        if fotos[i]['datum'] != fotos[i - 1]['datum']:
            continue
        for j in range(i + 1, min(i + vorausschau, len(fotos))):
            if fotos[j]['datum'] != fotos[i - 1]['datum']:
                fotos[i], fotos[j] = fotos[j], fotos[i]
                break
    return fotos


class App:
    def __init__(self):
        os.makedirs(FOTOS_DIR, exist_ok=True)
        pygame.init()
        pygame.mouse.set_visible(False)

        if IST_LINUX:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            for cmd in (['xset', 's', 'off'], ['xset', '-dpms'], ['xset', 's', 'noblank']):
                try:
                    subprocess.run(cmd, check=False)
                except FileNotFoundError:
                    pass
        else:
            self.screen = pygame.display.set_mode((1024, 600))
        pygame.display.set_caption('Bilderrahmen')

        self.w, self.h = self.screen.get_size()
        self.clock = pygame.time.Clock()

        schrift = 'dejavusans,arial,sans-serif'
        self.font_gross = pygame.font.SysFont(schrift, 34)
        self.font_mittel = pygame.font.SysFont(schrift, 24)
        self.font_klein = pygame.font.SysFont(schrift, 18)

        init_db()
        self.conn = get_db()
        self.sprache = einstellung_holen(self.conn, 'sprache', 'de')

        self.state = 'SLIDESHOW'
        self.running = True

        # Diashow-Zustand
        self.zuletzt_gezeigt = deque(maxlen=1000)
        self.fotos = []
        self.foto_index = 0
        self.fotos_neu_laden()
        self.aktuelle_surface = None
        self.naechste_surface = None
        self.in_uebergang = False
        self.uebergang_start = 0
        self.uebergang_dauer = int(einstellung_holen(self.conn, 'uebergang_dauer_ms', '800'))
        self.foto_uebergang_typ = 'fade'
        self.uebergang_alt_frame = None
        self.uebergang_neu_frame = None
        self.aktuelles_datum = None
        self.anzeige_start = 0
        self.letztes_foto_laden = pygame.time.get_ticks()
        self.zahnrad_bis = 0
        self._bildschirm_auto_aus = False
        self._letzter_nachtcheck = 0
        self._sync_prozess = None

        # Einstellungen-Zustand
        self._settings_zeilen = []
        self._settings_personen_chips = []
        self._settings_top_rects = None
        self._settings_inhalt_hoehe = self.h
        self.settings_scroll = 0
        self.settings_drag_start = None
        self.settings_drag_start_scroll = 0
        self.settings_drag_bewegt = False

        # Fotos-verwalten-Zustand
        self.fotos_seite = 0
        self._fotos_verwalten_liste = []
        self._fotos_verwalten_hat_weiter = False
        self._fotos_verwalten_gesamt = 0
        self.fv_filter_jahr = None
        self.fv_filter_monat = None
        self._fv_jahre_liste = []
        self._fv_rects = []
        self._fv_zurueck_rect = None
        self._fv_weiter_rect = None
        self._fv_einst_rect = None
        self._fv_jahr_rect = None
        self._fv_monat_rect = None

    def t(self, schluessel):
        return t(schluessel, self.sprache)

    # ── Diashow ──────────────────────────────────────────────────────

    def bild_skaliert_laden(self, pfad):
        try:
            img = pygame.image.load(pfad).convert()
        except Exception:
            return None
        iw, ih = img.get_size()
        if iw == 0 or ih == 0:
            return None
        if iw > ih:
            # Querformat: volle Bildschirmbreite nutzen, dafuer oben/unten
            # ggf. leicht beschneiden statt Balken links/rechts zu zeigen.
            skala = self.w / iw
        else:
            # Hochformat/quadratisch: komplett einpassen (Balken links/rechts),
            # sonst wuerde zu viel vom Bild oben/unten verloren gehen.
            skala = min(self.w / iw, self.h / ih)
        groesse = (max(1, int(iw * skala)), max(1, int(ih * skala)))
        return pygame.transform.smoothscale(img, groesse)

    def video_abspielen(self, pfad):
        try:
            subprocess.run(
                ['mpv', '--fullscreen', '--really-quiet', '--quiet', '--no-input-default-bindings', pfad],
                check=False
            )
        except FileNotFoundError:
            pass  # mpv fehlt (z.B. lokaler Windows-Testlauf) - Video einfach ueberspringen

    def bildschirm_ausschalten(self):
        if IST_LINUX:
            try:
                subprocess.run(['vcgencmd', 'display_power', '0'], check=False)
            except FileNotFoundError:
                pass
        self.state = 'BILDSCHIRM_AUS'

    def bildschirm_einschalten(self):
        if IST_LINUX:
            try:
                subprocess.run(['vcgencmd', 'display_power', '1'], check=False)
            except FileNotFoundError:
                pass
        self.state = 'SLIDESHOW'
        self._bildschirm_auto_aus = False

    def bildschirm_aus_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.bildschirm_einschalten()

    def bildschirm_aus_zeichnen(self):
        self.screen.fill(FARBE_HINTERGRUND)

    @staticmethod
    def _ist_nachtstunde(stunde_jetzt, start_stunde, ende_stunde):
        if start_stunde == ende_stunde:
            return False
        if start_stunde < ende_stunde:
            return start_stunde <= stunde_jetzt < ende_stunde
        return stunde_jetzt >= start_stunde or stunde_jetzt < ende_stunde

    def nachtplan_pruefen(self):
        jetzt = pygame.time.get_ticks()
        if jetzt - self._letzter_nachtcheck < 20000:
            return
        self._letzter_nachtcheck = jetzt

        if einstellung_holen(self.conn, 'nacht_aktiv', '0') != '1':
            return
        start_stunde = int(einstellung_holen(self.conn, 'nacht_start_stunde', '22'))
        ende_stunde = int(einstellung_holen(self.conn, 'nacht_ende_stunde', '7'))
        soll_aus = self._ist_nachtstunde(datetime.datetime.now().hour, start_stunde, ende_stunde)

        if soll_aus and self.state != 'BILDSCHIRM_AUS':
            self.bildschirm_ausschalten()
            self._bildschirm_auto_aus = True
        elif not soll_aus and self.state == 'BILDSCHIRM_AUS' and self._bildschirm_auto_aus:
            self.bildschirm_einschalten()

    def sync_starten(self):
        if self._sync_prozess and self._sync_prozess.poll() is None:
            return  # laeuft schon
        sync_skript = os.path.join(RAHMEN_DIR, 'sync.py')
        try:
            self._sync_prozess = subprocess.Popen([sys.executable, sync_skript])
        except Exception:
            fehler_loggen('Datenabgleich konnte nicht gestartet werden')
            self._sync_prozess = None

    def sync_laeuft(self):
        return bool(self._sync_prozess and self._sync_prozess.poll() is None)

    def _sync_fortschritt_lesen(self):
        try:
            with open(SYNC_FORTSCHRITT_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def fotos_neu_laden(self):
        self.fotos = fotos_laden(self.conn)
        self.fotos_mischen()

    def fotos_mischen(self):
        # Nur die juengere Haelfte zaehlt als "kuerzlich", sonst landet bei
        # wenigen Fotos alles im Kuerzlich-Block und das Mischen verpufft.
        fenster = len(self.fotos) // 2
        zuletzt = list(self.zuletzt_gezeigt)[-fenster:] if fenster else []
        self.fotos = reihenfolge_mischen(self.fotos, zuletzt)
        self.foto_index = 0

    def naechstes_foto_starten(self):
        if not self.fotos:
            self.aktuelle_surface = None
            return
        versuche = 0
        while versuche < len(self.fotos):
            versuche += 1
            if self.foto_index >= len(self.fotos):
                self.fotos_mischen()
            foto = self.fotos[self.foto_index]
            self.foto_index += 1
            self.zuletzt_gezeigt.append(foto['id'])
            pfad = os.path.join(FOTOS_DIR, foto['lokaler_dateiname'])
            if foto['ist_video']:
                self.video_abspielen(pfad)
                continue
            surface = self.bild_skaliert_laden(pfad)
            if surface is None:
                continue
            self.naechste_surface = surface
            self.aktuelles_datum = foto.get('datum')
            roh_typ = einstellung_holen(self.conn, 'uebergang_typ', 'fade')
            if roh_typ == 'random':
                self.foto_uebergang_typ = random.choice(UEBERGANG_TYPEN_KONKRET)
            else:
                self.foto_uebergang_typ = roh_typ
            self.uebergang_dauer = int(einstellung_holen(self.conn, 'uebergang_dauer_ms', '800'))
            self.uebergang_start = pygame.time.get_ticks()
            # Vollbild-Rahmen (inkl. schwarzer Balken) einmalig vorberechnen,
            # damit beim Ueberblenden nicht nur die Fotos selbst, sondern auch
            # ihre unterschiedlich breiten Balken sauber mit ausblenden -
            # sonst bleiben bei Quer-/Hochformat-Wechseln Reste des alten
            # Fotos an den Raendern sichtbar (die vom neuen Foto nicht
            # ueberdeckt werden, weil dessen Balken anders liegen).
            self.uebergang_alt_frame = self._vollbild_frame(self.aktuelle_surface)
            self.uebergang_neu_frame = self._vollbild_frame(self.naechste_surface)
            self.in_uebergang = True
            return
        self.aktuelle_surface = None
        self.naechste_surface = None

    def _rect_zentriert(self, surface):
        return surface.get_rect(center=(self.w // 2, self.h // 2))

    def _vollbild_frame(self, surface):
        """Komponiert ein Foto (mit ggf. schwarzen Balken) auf eine Surface in
        exakter Bildschirmgroesse, damit Uebergaenge zwischen unterschiedlich
        grossen/orientierten Fotos sauber ueberblenden koennen."""
        frame = pygame.Surface((self.w, self.h))
        frame.fill(FARBE_HINTERGRUND)
        if surface:
            frame.blit(surface, self._rect_zentriert(surface))
        return frame

    def _uebergang_zeichnen(self, typ, fortschritt):
        alt = self.uebergang_alt_frame
        neu = self.uebergang_neu_frame

        if typ == 'slide':
            self.screen.blit(alt, (-int(self.w * fortschritt), 0))
            self.screen.blit(neu, (int(self.w * (1 - fortschritt)), 0))
            return

        if typ == 'rotate':
            self.screen.blit(alt, (0, 0))
            skala = 1.05 - 0.05 * fortschritt
            winkel = 3 * (1 - fortschritt)
            gedreht = pygame.transform.rotozoom(neu, winkel, skala)
            gedreht = gedreht.convert_alpha()
            gedreht.set_alpha(int(255 * fortschritt))
            self.screen.blit(gedreht, gedreht.get_rect(center=(self.w // 2, self.h // 2)))
            return

        if typ == 'wipe':
            self.screen.blit(alt, (0, 0))
            breite_sichtbar = max(1, int(self.w * fortschritt))
            self.screen.set_clip(pygame.Rect(0, 0, breite_sichtbar, self.h))
            self.screen.blit(neu, (0, 0))
            self.screen.set_clip(None)
            return

        # 'fade' ist der Standard-Uebergang
        self.screen.blit(alt, (0, 0))
        neu_kopie = neu.copy()
        neu_kopie.set_alpha(int(255 * fortschritt))
        self.screen.blit(neu_kopie, (0, 0))

    def _bild_zeichnen(self, surface, anzeige_ms):
        self.screen.blit(surface, self._rect_zentriert(surface))
        self._datum_overlay_zeichnen(anzeige_ms)

    def _datum_overlay_zeichnen(self, anzeige_ms):
        if not self.aktuelles_datum:
            return
        if einstellung_holen(self.conn, 'datum_anzeigen', '1') != '1':
            return

        ausblend_ende = DATUM_AUSBLEND_START_MS + DATUM_AUSBLEND_DAUER_MS
        if anzeige_ms < DATUM_EINBLEND_DAUER_MS:
            fortschritt = anzeige_ms / DATUM_EINBLEND_DAUER_MS
        elif anzeige_ms < DATUM_AUSBLEND_START_MS:
            fortschritt = 1.0
        elif anzeige_ms < ausblend_ende:
            fortschritt = 1.0 - (anzeige_ms - DATUM_AUSBLEND_START_MS) / DATUM_AUSBLEND_DAUER_MS
        else:
            return

        text_anzeige = datum_de_formatieren(self.aktuelles_datum)
        if not text_anzeige:
            return

        alpha = int(255 * fortschritt)
        balken_hoehe = 50
        balken = pygame.Surface((self.w, balken_hoehe), pygame.SRCALPHA)
        balken.fill((0, 0, 0, int(140 * fortschritt)))
        text = self.font_mittel.render(text_anzeige, True, (255, 255, 255))
        text.set_alpha(alpha)
        balken.blit(text, text.get_rect(center=(self.w // 2, balken_hoehe // 2)))
        self.screen.blit(balken, (0, self.h - balken_hoehe))

    def slideshow_update_und_zeichnen(self):
        jetzt = pygame.time.get_ticks()

        if jetzt - self.letztes_foto_laden > FOTO_REFRESH_INTERVALL_MS:
            self.fotos_neu_laden()
            self.letztes_foto_laden = jetzt

        if self.aktuelle_surface is None and self.naechste_surface is None and not self.in_uebergang:
            self.naechstes_foto_starten()

        self.screen.fill(FARBE_HINTERGRUND)

        if self.aktuelle_surface is None and self.naechste_surface is None:
            text = self.font_mittel.render(self.t('keine_fotos'), True, FARBE_TEXT_GEDAEMPFT)
            self.screen.blit(text, text.get_rect(center=(self.w // 2, self.h // 2)))
            return

        typ = self.foto_uebergang_typ

        if self.in_uebergang:
            fortschritt = min(1.0, (jetzt - self.uebergang_start) / max(1, self.uebergang_dauer))
            self._uebergang_zeichnen(typ, fortschritt)
            if fortschritt >= 1.0:
                self.aktuelle_surface = self.naechste_surface
                self.naechste_surface = None
                self.in_uebergang = False
                self.anzeige_start = jetzt
        else:
            self._bild_zeichnen(self.aktuelle_surface, jetzt - self.anzeige_start)
            dauer = int(einstellung_holen(self.conn, 'anzeige_dauer_sek', '8')) * 1000
            if jetzt - self.anzeige_start > dauer:
                self.naechstes_foto_starten()

    def zahnrad_rect(self):
        groesse = 64
        return pygame.Rect(self.w - groesse - 16, 16, groesse, groesse)

    def _zahnrad_icon_zeichnen(self, center, radius, farbe):
        pygame.draw.circle(self.screen, farbe, center, radius)
        pygame.draw.circle(self.screen, (25, 25, 25), center, int(radius * 0.45))
        for i in range(8):
            winkel = (2 * math.pi / 8) * i
            x1 = center[0] + math.cos(winkel) * (radius - 2)
            y1 = center[1] + math.sin(winkel) * (radius - 2)
            x2 = center[0] + math.cos(winkel) * (radius + 7)
            y2 = center[1] + math.sin(winkel) * (radius + 7)
            pygame.draw.line(self.screen, farbe, (x1, y1), (x2, y2), width=6)

    def zahnrad_zeichnen(self):
        if pygame.time.get_ticks() > self.zahnrad_bis:
            return
        rect = self.zahnrad_rect()
        self._zahnrad_icon_zeichnen(rect.center, rect.width // 2 - 8, (235, 235, 235))

    def slideshow_event(self, ev):
        if ev.type != pygame.MOUSEBUTTONDOWN:
            return
        jetzt = pygame.time.get_ticks()
        if jetzt <= self.zahnrad_bis and self.zahnrad_rect().collidepoint(ev.pos):
            self.state = 'SETTINGS'
            self.settings_scroll = 0
            self._settings_zeilen = self.settings_zeilen_aufbauen()
            return
        self.zahnrad_bis = jetzt + ZAHNRAD_ANZEIGE_MS

    # ── Einstellungen ────────────────────────────────────────────────

    def settings_zeilen_aufbauen(self):
        zeilen = []
        y = 24
        row_h = 60
        gap = 12

        zeilen.append(('top_buttons', None, y))
        y += 54 + 24

        zeilen.append(('titel', self.t('personen_titel'), y))
        y += 44
        chips, y = self._settings_personen_chips_aufbauen(y)
        self._settings_personen_chips = chips
        if not chips:
            zeilen.append(('hinweis', self.t('personen_hinweis'), y))
            y += 36
        y += 28

        zeilen.append(('video_toggle', None, y)); y += row_h + gap
        zeilen.append(('datum_toggle', None, y)); y += row_h + gap
        zeilen.append(('dauer_stepper', None, y)); y += row_h + gap
        zeilen.append(('uebergang_dauer', None, y)); y += row_h + gap
        zeilen.append(('uebergang_typ', None, y)); y += row_h + gap
        zeilen.append(('sprache', None, y)); y += row_h + gap
        y += 20
        zeilen.append(('nacht_toggle', None, y)); y += row_h + gap
        if einstellung_holen(self.conn, 'nacht_aktiv', '0') == '1':
            zeilen.append(('nacht_start_stepper', None, y)); y += row_h + gap
            zeilen.append(('nacht_ende_stepper', None, y)); y += row_h + gap
        y += 20
        zeilen.append(('button_sync', None, y)); y += row_h + gap
        zeilen.append(('status', None, y)); y += 58

        self._settings_inhalt_hoehe = y + 24
        return zeilen

    def _settings_personen_chips_aufbauen(self, start_y):
        personen = self.conn.execute("SELECT * FROM personen_cache ORDER BY name").fetchall()
        chips = []
        x = 28
        y = start_y
        chip_h = 46
        gap = 10
        max_x = self.w - 28
        for p in personen:
            text_breite = self.font_mittel.size(p['name'])[0]
            chip_breite = text_breite + 44
            if x + chip_breite > max_x and x > 28:
                x = 28
                y += chip_h + gap
            chips.append((pygame.Rect(x, y, chip_breite, chip_h), dict(p)))
            x += chip_breite + gap
        ende_y = (y + chip_h) if personen else start_y
        return chips, ende_y

    def _karte(self, rect, aktiv=False):
        hintergrund = FARBE_KARTE_AKTIV if aktiv else FARBE_KARTE
        rand = FARBE_KARTE_AKTIV_RAND if aktiv else FARBE_KARTE_RAND
        pygame.draw.rect(self.screen, hintergrund, rect, border_radius=16)
        pygame.draw.rect(self.screen, rand, rect, width=2, border_radius=16)

    def _zeile_toggle(self, rect, label, an):
        self._karte(rect, aktiv=an)
        text = self.font_mittel.render(label, True, FARBE_TEXT_DUNKEL)
        self.screen.blit(text, (rect.x + 20, rect.y + (rect.height - text.get_height()) // 2))
        # Pill-Schalter rechts
        pill = pygame.Rect(rect.right - 78, rect.centery - 16, 58, 32)
        pygame.draw.rect(self.screen, FARBE_AKZENT if an else FARBE_TOGGLE_AUS, pill, border_radius=16)
        knopf_x = pill.right - 16 if an else pill.left + 16
        pygame.draw.circle(self.screen, (255, 255, 255), (knopf_x, pill.centery), 13)

    def _zeile_stepper(self, rect, label):
        self._karte(rect)
        text = self.font_mittel.render(label, True, FARBE_TEXT_DUNKEL)
        self.screen.blit(text, (rect.x + 88, rect.y + (rect.height - text.get_height()) // 2))
        for cx, zeichen in ((rect.x + 44, '-'), (rect.right - 44, '+')):
            pygame.draw.circle(self.screen, FARBE_SEITE, (cx, rect.centery), 22)
            pygame.draw.circle(self.screen, FARBE_KARTE_RAND, (cx, rect.centery), 22, width=2)
            t = self.font_mittel.render(zeichen, True, FARBE_AKZENT_DUNKEL)
            self.screen.blit(t, t.get_rect(center=(cx, rect.centery - 1)))

    def _zeile_button(self, rect, label, akzent=False):
        if akzent:
            pygame.draw.rect(self.screen, FARBE_AKZENT, rect, border_radius=16)
            textfarbe = (255, 255, 255)
        else:
            self._karte(rect)
            textfarbe = FARBE_TEXT_DUNKEL
        text = self.font_mittel.render(label, True, textfarbe)
        self.screen.blit(text, text.get_rect(center=rect.center))

    def _sync_fortschritt_zeichnen(self, rect):
        fortschritt = self._sync_fortschritt_lesen() or {}
        erledigt = fortschritt.get('erledigt', 0)
        gesamt = fortschritt.get('gesamt', 0)

        self._karte(rect)
        if gesamt > 0:
            anteil = max(0.0, min(1.0, erledigt / gesamt))
            fuell_breite = int((rect.width - 6) * anteil)
            if fuell_breite > 0:
                fuell_rect = pygame.Rect(rect.x + 3, rect.y + 3, fuell_breite, rect.height - 6)
                pygame.draw.rect(self.screen, FARBE_AKZENT, fuell_rect, border_radius=12)
            text = f"{self.t('sync_laeuft_label')} ({erledigt}/{gesamt})"
        else:
            text = self.t('sync_laeuft_label')
        t_surf = self.font_mittel.render(text, True, FARBE_TEXT_DUNKEL)
        self.screen.blit(t_surf, t_surf.get_rect(center=rect.center))

    def _status_zeichnen(self, rect):
        try:
            usage = shutil.disk_usage(FOTOS_DIR)
            prozent = round(usage.used / usage.total * 100, 1)
            speicher_text = (f"{self.t('speicher_belegt')}: "
                              f"{bytes_human(usage.used)} / {bytes_human(usage.total)} ({prozent}%)")
        except FileNotFoundError:
            speicher_text = f"{self.t('speicher_belegt')}: -"
        zeile = self.conn.execute(
            "SELECT wert FROM einstellungen WHERE schluessel = 'letzter_sync_lauf'"
        ).fetchone()
        letzter = zeile['wert'] if zeile else None
        letzter_text = datum_de_formatieren(letzter) or self.t('noch_nie')
        sync_text = f"{self.t('letzter_sync')}: {letzter_text}"
        self.screen.blit(self.font_klein.render(speicher_text, True, FARBE_TEXT_DUNKEL_GEDAEMPFT), (rect.x, rect.y))
        self.screen.blit(self.font_klein.render(sync_text, True, FARBE_TEXT_DUNKEL_GEDAEMPFT), (rect.x, rect.y + 26))

    def _settings_personen_chip_zeichnen(self, rect, name, aktiv):
        if aktiv:
            pygame.draw.rect(self.screen, FARBE_AKZENT, rect, border_radius=rect.height // 2)
            textfarbe = (255, 255, 255)
        else:
            pygame.draw.rect(self.screen, FARBE_KARTE, rect, border_radius=rect.height // 2)
            pygame.draw.rect(self.screen, FARBE_KARTE_RAND, rect, width=2, border_radius=rect.height // 2)
            textfarbe = FARBE_TEXT_DUNKEL
        text = self.font_mittel.render(name, True, textfarbe)
        self.screen.blit(text, text.get_rect(center=rect.center))

    def _settings_top_buttons_zeichnen(self, rect):
        gap = 10
        drittel = (rect.width - 2 * gap) // 3
        r1 = pygame.Rect(rect.x, rect.y, drittel, rect.height)
        r2 = pygame.Rect(r1.right + gap, rect.y, drittel, rect.height)
        r3 = pygame.Rect(r2.right + gap, rect.y, rect.right - (r2.right + gap), rect.height)
        self._zeile_button(r1, self.t('fotos_verwalten_titel'), akzent=True)
        self._zeile_button(r2, self.t('zur_diashow'), akzent=True)
        self._zeile_button(r3, self.t('bildschirm_aus_button'))
        self._settings_top_rects = (r1, r2, r3)

    def settings_zeichnen(self):
        self.screen.fill(FARBE_SEITE)

        for rect, person in self._settings_personen_chips:
            angepasst = rect.move(0, -self.settings_scroll)
            if angepasst.bottom < -10 or angepasst.top > self.h + 10:
                continue
            self._settings_personen_chip_zeichnen(angepasst, person['name'], person['erlaubt'])

        for art, daten, row_y in self._settings_zeilen:
            y = row_y - self.settings_scroll
            if y < -60 or y > self.h + 10:
                continue
            if art == 'titel':
                text = self.font_gross.render(daten, True, FARBE_TEXT_DUNKEL)
                self.screen.blit(text, (28, y))
                continue
            if art == 'hinweis':
                text = self.font_klein.render(daten, True, FARBE_TEXT_DUNKEL_GEDAEMPFT)
                self.screen.blit(text, (28, y))
                continue

            rect = pygame.Rect(28, y, self.w - 56, 60)
            if art == 'top_buttons':
                self._settings_top_buttons_zeichnen(pygame.Rect(28, y, self.w - 56, 54))
            elif art == 'video_toggle':
                an = einstellung_holen(self.conn, 'videos_aktiv', '1') == '1'
                self._zeile_toggle(rect, self.t('videos_label'), an)
            elif art == 'datum_toggle':
                an = einstellung_holen(self.conn, 'datum_anzeigen', '1') == '1'
                self._zeile_toggle(rect, self.t('datum_anzeigen_label'), an)
            elif art == 'dauer_stepper':
                wert = einstellung_holen(self.conn, 'anzeige_dauer_sek', '8')
                self._zeile_stepper(rect, f"{self.t('anzeige_dauer_label')}: {wert}s")
            elif art == 'uebergang_typ':
                typ = einstellung_holen(self.conn, 'uebergang_typ', 'fade')
                self._zeile_button(rect, f"{self.t('uebergang_typ_label')}: {self.t('uebergang_' + typ)}")
            elif art == 'uebergang_dauer':
                wert = einstellung_holen(self.conn, 'uebergang_dauer_ms', '800')
                self._zeile_stepper(rect, f"{self.t('uebergang_dauer_label')}: {wert}ms")
            elif art == 'sprache':
                spr = einstellung_holen(self.conn, 'sprache', 'de')
                self._zeile_button(rect, f"{self.t('sprache_label')}: {'Deutsch' if spr == 'de' else 'Türkçe'}")
            elif art == 'nacht_toggle':
                an = einstellung_holen(self.conn, 'nacht_aktiv', '0') == '1'
                self._zeile_toggle(rect, self.t('nacht_aktiv_label'), an)
            elif art == 'nacht_start_stepper':
                wert = einstellung_holen(self.conn, 'nacht_start_stunde', '22')
                self._zeile_stepper(rect, f"{self.t('nacht_start_label')}: {int(wert):02d}:00")
            elif art == 'nacht_ende_stepper':
                wert = einstellung_holen(self.conn, 'nacht_ende_stunde', '7')
                self._zeile_stepper(rect, f"{self.t('nacht_ende_label')}: {int(wert):02d}:00")
            elif art == 'button_sync':
                if self.sync_laeuft():
                    self._sync_fortschritt_zeichnen(rect)
                else:
                    self._zeile_button(rect, self.t('sync_button_label'), akzent=True)
            elif art == 'status':
                self._status_zeichnen(rect)

    def _stepper_tap(self, x, rect, schluessel, minimum, maximum, schritt):
        aktuell = int(einstellung_holen(self.conn, schluessel, str(minimum)))
        if x < rect.x + 70:
            aktuell = max(minimum, aktuell - schritt)
        elif x > rect.right - 70:
            aktuell = min(maximum, aktuell + schritt)
        else:
            return
        einstellung_setzen(self.conn, schluessel, aktuell)

    def _stunden_stepper_tap(self, x, rect, schluessel):
        """Wie _stepper_tap, aber mit Umlauf 0-23 (fuer Uhrzeiten)."""
        aktuell = int(einstellung_holen(self.conn, schluessel, '0'))
        if x < rect.x + 70:
            aktuell = (aktuell - 1) % 24
        elif x > rect.right - 70:
            aktuell = (aktuell + 1) % 24
        else:
            return
        einstellung_setzen(self.conn, schluessel, aktuell)

    def _settings_tap(self, pos):
        x, y = pos
        y_inhalt = y + self.settings_scroll

        for rect, person in self._settings_personen_chips:
            if rect.collidepoint(x, y_inhalt):
                neu = 0 if person['erlaubt'] else 1
                self.conn.execute("UPDATE personen_cache SET erlaubt=? WHERE id=?", (neu, person['id']))
                self.conn.commit()
                self._settings_zeilen = self.settings_zeilen_aufbauen()
                return

        for art, daten, row_y in self._settings_zeilen:
            rect = pygame.Rect(28, row_y, self.w - 56, 60)
            if not rect.collidepoint(x, y_inhalt):
                continue
            if art == 'top_buttons':
                if self._settings_top_rects:
                    r1, r2, r3 = self._settings_top_rects
                    if r1.collidepoint(x, y_inhalt):
                        self.state = 'FOTOS_VERWALTEN'
                        self.fotos_seite = 0
                        self.fv_filter_jahr = None
                        self.fv_filter_monat = None
                        self._fv_jahre_liste = self._fv_verfuegbare_jahre()
                        self.fotos_verwalten_laden_seite()
                        return
                    if r2.collidepoint(x, y_inhalt):
                        self.state = 'SLIDESHOW'
                        self.fotos_neu_laden()
                        return
                    if r3.collidepoint(x, y_inhalt):
                        self.bildschirm_ausschalten()
                        self._bildschirm_auto_aus = False
                        return
                return
            elif art == 'video_toggle':
                aktuell = einstellung_holen(self.conn, 'videos_aktiv', '1')
                einstellung_setzen(self.conn, 'videos_aktiv', '0' if aktuell == '1' else '1')
            elif art == 'datum_toggle':
                aktuell = einstellung_holen(self.conn, 'datum_anzeigen', '1')
                einstellung_setzen(self.conn, 'datum_anzeigen', '0' if aktuell == '1' else '1')
            elif art == 'dauer_stepper':
                self._stepper_tap(x, rect, 'anzeige_dauer_sek', 2, 120, 1)
            elif art == 'uebergang_typ':
                aktuell = einstellung_holen(self.conn, 'uebergang_typ', 'fade')
                idx = (UEBERGANG_TYPEN.index(aktuell) + 1) % len(UEBERGANG_TYPEN) if aktuell in UEBERGANG_TYPEN else 0
                einstellung_setzen(self.conn, 'uebergang_typ', UEBERGANG_TYPEN[idx])
            elif art == 'uebergang_dauer':
                self._stepper_tap(x, rect, 'uebergang_dauer_ms', 200, 5000, 100)
            elif art == 'sprache':
                aktuell = einstellung_holen(self.conn, 'sprache', 'de')
                neu = 'tr' if aktuell == 'de' else 'de'
                einstellung_setzen(self.conn, 'sprache', neu)
                self.sprache = neu
            elif art == 'nacht_toggle':
                aktuell = einstellung_holen(self.conn, 'nacht_aktiv', '0')
                einstellung_setzen(self.conn, 'nacht_aktiv', '0' if aktuell == '1' else '1')
            elif art == 'nacht_start_stepper':
                self._stunden_stepper_tap(x, rect, 'nacht_start_stunde')
            elif art == 'nacht_ende_stepper':
                self._stunden_stepper_tap(x, rect, 'nacht_ende_stunde')
            elif art == 'button_sync':
                self.sync_starten()
            self._settings_zeilen = self.settings_zeilen_aufbauen()
            return

    def settings_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.settings_drag_start = ev.pos
            self.settings_drag_start_scroll = self.settings_scroll
            self.settings_drag_bewegt = False
        elif ev.type == pygame.MOUSEMOTION and self.settings_drag_start is not None:
            dy = ev.pos[1] - self.settings_drag_start[1]
            if abs(dy) > 4:
                self.settings_drag_bewegt = True
            max_scroll = max(0, self._settings_inhalt_hoehe - self.h)
            self.settings_scroll = min(max_scroll, max(0, self.settings_drag_start_scroll - dy))
        elif ev.type == pygame.MOUSEBUTTONUP:
            start = self.settings_drag_start
            self.settings_drag_start = None
            if start is not None and not self.settings_drag_bewegt:
                self._settings_tap(ev.pos)

    # ── Fotos verwalten ──────────────────────────────────────────────

    FV_SPALTEN = 4
    FV_REIHEN = 2
    FV_RAND = 20

    def _fv_verfuegbare_jahre(self):
        rows = self.conn.execute(
            "SELECT DISTINCT substr(datum,1,4) as jahr FROM fotos ORDER BY jahr DESC"
        ).fetchall()
        return [r['jahr'] for r in rows]

    def _fv_where_klausel(self):
        bedingungen, parameter = [], []
        if self.fv_filter_jahr:
            bedingungen.append("substr(datum,1,4)=?")
            parameter.append(self.fv_filter_jahr)
        if self.fv_filter_monat:
            bedingungen.append("substr(datum,6,2)=?")
            parameter.append(f"{self.fv_filter_monat:02d}")
        where = ("WHERE " + " AND ".join(bedingungen)) if bedingungen else ""
        return where, parameter

    def fotos_verwalten_laden_seite(self):
        pro_seite = self.FV_SPALTEN * self.FV_REIHEN
        where, parameter = self._fv_where_klausel()
        gesamt = self.conn.execute(f"SELECT COUNT(*) as c FROM fotos {where}", parameter).fetchone()['c']
        zeilen = self.conn.execute(
            f"SELECT * FROM fotos {where} ORDER BY datum DESC LIMIT ? OFFSET ?",
            parameter + [pro_seite, self.fotos_seite * pro_seite]
        ).fetchall()
        self._fotos_verwalten_liste = [dict(r) for r in zeilen]
        self._fotos_verwalten_gesamt = gesamt
        self._fotos_verwalten_hat_weiter = (self.fotos_seite + 1) * pro_seite < gesamt

    def _fv_jahr_zyklus(self, richtung):
        optionen = [None] + self._fv_jahre_liste
        idx = optionen.index(self.fv_filter_jahr) if self.fv_filter_jahr in optionen else 0
        self.fv_filter_jahr = optionen[(idx + richtung) % len(optionen)]
        self.fotos_seite = 0
        self.fotos_verwalten_laden_seite()

    def _fv_monat_zyklus(self, richtung):
        optionen = [None] + list(range(1, 13))
        idx = optionen.index(self.fv_filter_monat) if self.fv_filter_monat in optionen else 0
        self.fv_filter_monat = optionen[(idx + richtung) % len(optionen)]
        self.fotos_seite = 0
        self.fotos_verwalten_laden_seite()

    def thumbnail_laden(self, dateiname):
        os.makedirs(THUMBS_DIR, exist_ok=True)
        thumb_pfad = os.path.join(THUMBS_DIR, dateiname)
        if not os.path.exists(thumb_pfad):
            try:
                from PIL import Image
                bild = Image.open(os.path.join(FOTOS_DIR, dateiname))
                bild.thumbnail((320, 320))
                bild.convert('RGB').save(thumb_pfad, 'JPEG', quality=85)
            except Exception:
                return None
        try:
            return pygame.image.load(thumb_pfad).convert()
        except Exception:
            return None

    FV_KOPF_HOEHE = 132
    FV_FUSS_HOEHE = 86
    FV_BESCHRIFTUNG_H = 22

    def _fv_zellen_geometrie(self):
        spalten, reihen, rand = self.FV_SPALTEN, self.FV_REIHEN, self.FV_RAND
        beschriftung_h = self.FV_BESCHRIFTUNG_H
        verfuegbare_breite = self.w - rand * (spalten + 1)
        verfuegbare_hoehe = (self.h - self.FV_KOPF_HOEHE - self.FV_FUSS_HOEHE
                              - rand * (reihen - 1) - reihen * beschriftung_h)
        zelle = min(verfuegbare_breite // spalten, verfuegbare_hoehe // reihen)
        raster_breite = spalten * zelle + (spalten - 1) * rand
        start_x = (self.w - raster_breite) // 2
        return zelle, rand, start_x

    def _fv_cycler_zeichnen(self, rect, text):
        self._karte(rect)
        for cx, zeichen in ((rect.x + 30, '‹'), (rect.right - 30, '›')):
            t_surf = self.font_mittel.render(zeichen, True, FARBE_AKZENT_DUNKEL)
            self.screen.blit(t_surf, t_surf.get_rect(center=(cx, rect.centery)))
        t_surf = self.font_klein.render(text, True, FARBE_TEXT_DUNKEL)
        self.screen.blit(t_surf, t_surf.get_rect(center=rect.center))

    def fotos_verwalten_zeichnen(self):
        self.screen.fill(FARBE_SEITE)
        titel = self.font_gross.render(self.t('fotos_verwalten_titel'), True, FARBE_TEXT_DUNKEL)
        self.screen.blit(titel, (28, 20))

        # Filterleiste: Jahr + Monat
        filter_y = 70
        breite_halb = (self.w - 56) // 2
        self._fv_jahr_rect = pygame.Rect(28, filter_y, breite_halb, 48)
        self._fv_monat_rect = pygame.Rect(28 + breite_halb + 8, filter_y, breite_halb, 48)
        jahr_text = self.fv_filter_jahr or self.t('alle_jahre')
        monat_text = MONATSNAMEN.get(self.sprache, MONATSNAMEN['de'])[self.fv_filter_monat - 1] \
            if self.fv_filter_monat else self.t('alle_monate')
        self._fv_cycler_zeichnen(self._fv_jahr_rect, jahr_text)
        self._fv_cycler_zeichnen(self._fv_monat_rect, monat_text)

        zelle, rand, start_x = self._fv_zellen_geometrie()
        self._fv_rects = []

        if not self._fotos_verwalten_liste:
            hinweis = self.font_klein.render(self.t('keine_fotos'), True, FARBE_TEXT_DUNKEL_GEDAEMPFT)
            self.screen.blit(hinweis, (28, self.FV_KOPF_HOEHE + 20))

        for i, foto in enumerate(self._fotos_verwalten_liste):
            col, row = i % self.FV_SPALTEN, i // self.FV_SPALTEN
            x = start_x + col * (zelle + rand)
            y = self.FV_KOPF_HOEHE + row * (zelle + self.FV_BESCHRIFTUNG_H + rand)
            rect = pygame.Rect(x, y, zelle, zelle)
            self._fv_rects.append((rect, foto))

            thumb = None if foto['ist_video'] else self.thumbnail_laden(foto['lokaler_dateiname'])
            pygame.draw.rect(self.screen, FARBE_KARTE, rect, border_radius=14)
            pygame.draw.rect(self.screen, FARBE_KARTE_RAND, rect, width=2, border_radius=14)
            if thumb:
                innen = rect.inflate(-6, -6)
                skala = min(innen.width / thumb.get_width(), innen.height / thumb.get_height())
                groesse = (max(1, int(thumb.get_width() * skala)), max(1, int(thumb.get_height() * skala)))
                thumb = pygame.transform.smoothscale(thumb, groesse)
                thumb_rect = thumb.get_rect(center=rect.center)
                # abgerundete Ecken der Kachel respektieren: leicht kleiner clippen
                self.screen.set_clip(rect.inflate(-4, -4))
                self.screen.blit(thumb, thumb_rect)
                self.screen.set_clip(None)
            elif foto['ist_video']:
                pygame.draw.circle(self.screen, FARBE_SEITE, rect.center, 26)
                pygame.draw.polygon(self.screen, FARBE_AKZENT_DUNKEL, [
                    (rect.centerx - 8, rect.centery - 13),
                    (rect.centerx - 8, rect.centery + 13),
                    (rect.centerx + 14, rect.centery),
                ])

            stern_center = (rect.right - 24, rect.top + 24)
            stern_farbe = (245, 158, 11) if foto['favorit'] else FARBE_KARTE_RAND
            pygame.draw.circle(self.screen, (255, 255, 255), stern_center, 18)
            pygame.draw.circle(self.screen, stern_farbe, stern_center, 18, width=0 if foto['favorit'] else 2)
            self._stern_zeichnen(stern_center, 10, (255, 255, 255) if foto['favorit'] else (200, 200, 205))

            datum_text = datum_de_formatieren(foto.get('datum'))
            if datum_text:
                t_surf = self.font_klein.render(datum_text, True, FARBE_TEXT_DUNKEL_GEDAEMPFT)
                self.screen.blit(t_surf, t_surf.get_rect(midtop=(rect.centerx, rect.bottom + 2)))

        pro_seite = self.FV_SPALTEN * self.FV_REIHEN
        gesamt_seiten = max(1, math.ceil(self._fotos_verwalten_gesamt / pro_seite))
        seiten_text = f"{self.t('seite')} {self.fotos_seite + 1}/{gesamt_seiten}"
        seiten_surf = self.font_klein.render(seiten_text, True, FARBE_TEXT_DUNKEL_GEDAEMPFT)
        self.screen.blit(seiten_surf, seiten_surf.get_rect(centerx=self.w // 2, y=self.h - 108))

        unten_y = self.h - 70
        self._fv_zurueck_rect = pygame.Rect(20, unten_y, 150, 54)
        self._fv_weiter_rect = pygame.Rect(self.w - 170, unten_y, 150, 54)
        self._fv_einst_rect = pygame.Rect(self.w // 2 - 100, unten_y, 200, 54)
        self._zeile_button(self._fv_einst_rect, self.t('zu_einstellungen'), akzent=True)
        if self.fotos_seite > 0:
            self._zeile_button(self._fv_zurueck_rect, self.t('zurueck'))
        if self._fotos_verwalten_hat_weiter:
            self._zeile_button(self._fv_weiter_rect, self.t('weiter'))

    def _stern_zeichnen(self, center, radius, farbe):
        punkte = []
        for i in range(10):
            winkel = math.pi / 2 + i * math.pi / 5
            r = radius if i % 2 == 0 else radius * 0.45
            punkte.append((center[0] + math.cos(winkel) * r, center[1] - math.sin(winkel) * r))
        pygame.draw.polygon(self.screen, farbe, punkte)

    def fotos_verwalten_event(self, ev):
        if ev.type != pygame.MOUSEBUTTONDOWN:
            return
        pos = ev.pos
        if self._fv_jahr_rect and self._fv_jahr_rect.collidepoint(pos):
            richtung = -1 if pos[0] < self._fv_jahr_rect.centerx else 1
            self._fv_jahr_zyklus(richtung)
            return
        if self._fv_monat_rect and self._fv_monat_rect.collidepoint(pos):
            richtung = -1 if pos[0] < self._fv_monat_rect.centerx else 1
            self._fv_monat_zyklus(richtung)
            return
        for rect, foto in self._fv_rects:
            stern_rect = pygame.Rect(rect.right - 42, rect.top + 6, 36, 36)
            if stern_rect.collidepoint(pos):
                self.conn.execute("UPDATE fotos SET favorit = 1 - favorit WHERE id=?", (foto['id'],))
                self.conn.commit()
                self.fotos_verwalten_laden_seite()
                return
        if self._fv_zurueck_rect and self._fv_zurueck_rect.collidepoint(pos) and self.fotos_seite > 0:
            self.fotos_seite -= 1
            self.fotos_verwalten_laden_seite()
            return
        if self._fv_weiter_rect and self._fv_weiter_rect.collidepoint(pos) and self._fotos_verwalten_hat_weiter:
            self.fotos_seite += 1
            self.fotos_verwalten_laden_seite()
            return
        if self._fv_einst_rect and self._fv_einst_rect.collidepoint(pos):
            self.state = 'SETTINGS'
            self._settings_zeilen = self.settings_zeilen_aufbauen()

    # ── Hauptschleife ────────────────────────────────────────────────

    def run(self):
        fehler_zaehler = 0
        fehler_fenster_start = pygame.time.get_ticks()

        while self.running:
            try:
                self.nachtplan_pruefen()
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        self.running = False
                    elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE and not IST_LINUX:
                        self.running = False
                    elif self.state == 'SLIDESHOW':
                        self.slideshow_event(ev)
                    elif self.state == 'SETTINGS':
                        self.settings_event(ev)
                    elif self.state == 'FOTOS_VERWALTEN':
                        self.fotos_verwalten_event(ev)
                    elif self.state == 'BILDSCHIRM_AUS':
                        self.bildschirm_aus_event(ev)

                if self.state == 'SLIDESHOW':
                    self.slideshow_update_und_zeichnen()
                    self.zahnrad_zeichnen()
                elif self.state == 'SETTINGS':
                    self.settings_zeichnen()
                elif self.state == 'FOTOS_VERWALTEN':
                    self.fotos_verwalten_zeichnen()
                elif self.state == 'BILDSCHIRM_AUS':
                    self.bildschirm_aus_zeichnen()

                pygame.display.flip()
            except Exception:
                # Ein einzelner Fehler (z.B. defektes Foto) soll die Diashow nicht
                # komplett beenden - loggen, kurz warten, weitermachen. Haeufen sich
                # die Fehler aber (z.B. echter Programmfehler), lieber sauber
                # beenden - das Kiosk-Startskript startet dann automatisch neu.
                fehler_loggen('Fehler in der Hauptschleife')
                jetzt = pygame.time.get_ticks()
                if jetzt - fehler_fenster_start > 5000:
                    fehler_zaehler = 0
                    fehler_fenster_start = jetzt
                fehler_zaehler += 1
                if fehler_zaehler > 20:
                    fehler_loggen('Zu viele Fehler in kurzer Zeit - beende kiosk.py')
                    self.running = False

            self.clock.tick(FPS)

        self.conn.close()
        pygame.quit()


if __name__ == '__main__':
    try:
        App().run()
    except Exception:
        fehler_loggen('Fehler beim Start (App-Konstruktion)')
        raise
