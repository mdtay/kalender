(function () {
    const cfg = window.RAHMEN_EINSTELLUNGEN;
    const bildA = document.getElementById('bild-a');
    const bildB = document.getElementById('bild-b');
    const videoA = document.getElementById('video-a');
    const leerHinweis = document.getElementById('leer-hinweis');

    let fotos = [];
    let index = 0;
    let sichtbarIstA = true;
    let timerId = null;

    function ebenenFuerTyp(typ) {
        // liefert die CSS-Klassen fuer "kommt rein" und "geht raus" je nach Uebergangstyp
        if (typ === 'slide') {
            return { rein: 'slide-rein', rausVorher: 'slide-rechts', rausNachher: 'slide-links' };
        }
        return { rein: '', rausVorher: '', rausNachher: '' };
    }

    function naechstesBildZeigen() {
        if (fotos.length === 0) {
            leerHinweis.hidden = false;
            // Regelmaessig neu versuchen, statt fuer immer leer zu bleiben
            // (z.B. wenn noch nie synchronisiert wurde oder das Laden kurz fehlschlug).
            fotosLaden();
            planeNaechstes(15 * 1000);
            return;
        }
        leerHinweis.hidden = true;

        const foto = fotos[index % fotos.length];
        index += 1;

        const alteEbene = sichtbarIstA ? bildA : bildB;
        const neueEbene = sichtbarIstA ? bildB : bildA;
        sichtbarIstA = !sichtbarIstA;

        if (foto.ist_video) {
            alteEbene.classList.remove('sichtbar');
            bildA.classList.remove('sichtbar');
            bildB.classList.remove('sichtbar');
            videoA.src = '/foto/' + encodeURIComponent(foto.lokaler_dateiname);
            videoA.hidden = false;
            videoA.currentTime = 0;
            videoA.play().catch(() => {});
            videoA.onended = () => {
                videoA.hidden = true;
                planeNaechstes(200);
            };
            return;
        }

        videoA.hidden = true;
        videoA.pause();

        neueEbene.className = 'bild-ebene';
        neueEbene.style.transitionDuration = cfg.uebergangDauerMs + 'ms';
        neueEbene.src = '/foto/' + encodeURIComponent(foto.lokaler_dateiname);

        neueEbene.onload = () => {
            if (cfg.uebergangTyp === 'kenburns') {
                neueEbene.classList.remove('kenburns-aktiv');
            }
            if (cfg.uebergangTyp === 'rotate') {
                neueEbene.classList.remove('rotate-aktiv');
            }
            // kurz warten, damit der Browser den Ausgangszustand rendert, bevor animiert wird
            requestAnimationFrame(() => {
                neueEbene.classList.add('sichtbar');
                alteEbene.classList.remove('sichtbar');
                if (cfg.uebergangTyp === 'kenburns') {
                    neueEbene.classList.add('kenburns-aktiv');
                }
                if (cfg.uebergangTyp === 'rotate') {
                    neueEbene.classList.add('rotate-aktiv');
                }
            });
        };

        planeNaechstes(cfg.anzeigeDauerSek * 1000);
    }

    function planeNaechstes(verzoegerungMs) {
        clearTimeout(timerId);
        timerId = setTimeout(naechstesBildZeigen, verzoegerungMs);
    }

    async function fotosLaden() {
        try {
            const res = await fetch('/api/fotos');
            const geladen = await res.json();
            if (!Array.isArray(geladen) || geladen.length === 0) {
                // Leere/kaputte Antwort - alte Liste (falls vorhanden) lieber behalten
                // als eine funktionierende Diashow grundlos zu leeren.
                return;
            }
            fotos = geladen;
            // Fisher-Yates fuer eine zufaellige Reihenfolge, die sich nicht bei jedem Refresh wiederholt
            for (let i = fotos.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [fotos[i], fotos[j]] = [fotos[j], fotos[i]];
            }
        } catch (e) {
            // Netzwerk-/Serverfehler: alte Liste einfach behalten, naechstesBildZeigen()
            // versucht es von selbst erneut, solange fotos leer ist.
        }
    }

    async function start() {
        await fotosLaden();
        naechstesBildZeigen();
    }

    // Fotoliste periodisch neu laden, damit neu synchronisierte Fotos ohne
    // manuellen Neustart des Kiosk-Browsers auftauchen
    setInterval(fotosLaden, 60 * 60 * 1000);

    start();
})();
