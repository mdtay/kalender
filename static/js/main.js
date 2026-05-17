// Tag-Eingabe Komponente
class TagEingabe {
    constructor(container, vorschlaege) {
        this.container = container;
        this.vorschlaege = vorschlaege;
        this.hidden = container.querySelector('input[type=hidden]');
        this.tags = this.hidden.value.split(',').map(t => t.trim()).filter(Boolean);

        // Eingabe-Wrapper als letztes Element im Container
        this.wrapper = document.createElement('div');
        this.wrapper.className = 'tag-input-wrapper';

        this.textInput = document.createElement('input');
        this.textInput.type = 'text';
        this.textInput.className = 'tag-text-input';
        this.textInput.placeholder = 'Tag hinzufügen…';
        this.textInput.autocomplete = 'off';

        this.dropdown = document.createElement('div');
        this.dropdown.className = 'tag-dropdown';
        this.dropdown.style.display = 'none';

        this.wrapper.appendChild(this.textInput);
        this.wrapper.appendChild(this.dropdown);
        container.appendChild(this.wrapper);

        this.render();
        this.bindEvents();
    }

    render() {
        // Alle bestehenden Chips entfernen, neu einfügen
        this.container.querySelectorAll('.tag-chip').forEach(el => el.remove());
        this.tags.forEach(tag => {
            const chip = document.createElement('span');
            chip.className = 'tag-chip';
            chip.textContent = tag;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = '×';
            btn.addEventListener('click', e => { e.stopPropagation(); this.remove(tag); });
            chip.appendChild(btn);
            this.container.insertBefore(chip, this.wrapper);
        });
        this.hidden.value = this.tags.join(',');
        // Placeholder nur zeigen wenn keine Tags
        this.textInput.placeholder = this.tags.length ? '' : 'Tag hinzufügen…';
    }

    add(tag) {
        tag = tag.trim();
        if (!tag) return;
        if (this.tags.some(t => t.toLowerCase() === tag.toLowerCase())) return;
        this.tags.push(tag);
        this.render();
        this.textInput.value = '';
    }

    remove(tag) {
        this.tags = this.tags.filter(t => t !== tag);
        this.render();
    }

    zeigeDropdown(query) {
        const treffer = this.vorschlaege.filter(t =>
            t.toLowerCase().includes(query.toLowerCase()) &&
            !this.tags.some(x => x.toLowerCase() === t.toLowerCase())
        ).slice(0, 10);
        if (!treffer.length) { this.dropdown.style.display = 'none'; return; }
        this.dropdown.innerHTML = '';
        treffer.forEach(t => {
            const item = document.createElement('div');
            item.className = 'tag-dropdown-item';
            item.textContent = t;
            item.addEventListener('mousedown', e => {
                e.preventDefault();
                this.add(t);
                this.dropdown.style.display = 'none';
            });
            this.dropdown.appendChild(item);
        });
        this.dropdown.style.display = 'block';
    }

    bindEvents() {
        this.textInput.addEventListener('input', () => this.zeigeDropdown(this.textInput.value));
        this.textInput.addEventListener('focus', () => this.zeigeDropdown(this.textInput.value));
        this.textInput.addEventListener('blur', () => {
            setTimeout(() => this.dropdown.style.display = 'none', 150);
            if (this.textInput.value.trim()) this.add(this.textInput.value);
        });
        this.textInput.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault();
                this.add(this.textInput.value);
                this.dropdown.style.display = 'none';
            } else if (e.key === 'Backspace' && !this.textInput.value && this.tags.length) {
                this.remove(this.tags[this.tags.length - 1]);
            }
        });
    }
}

// Hamburger-Menü / Sidebar
function toggleNav() {
    const sidebar = document.getElementById('nav-sidebar');
    const overlay = document.querySelector('.nav-overlay');
    sidebar?.classList.toggle('offen');
    overlay?.classList.toggle('aktiv');
}
function schliesseNav() {
    document.getElementById('nav-sidebar')?.classList.remove('offen');
    document.querySelector('.nav-overlay')?.classList.remove('aktiv');
}
document.addEventListener('click', e => {
    const sidebar = document.getElementById('nav-sidebar');
    const toggle = document.querySelector('.nav-toggle');
    if (sidebar && toggle && !sidebar.contains(e.target) && !toggle.contains(e.target)) {
        sidebar.classList.remove('offen');
        document.querySelector('.nav-overlay')?.classList.remove('aktiv');
    }
});

// Lightbox
function oeffneLichtbox(img) {
    const lb = document.getElementById('lightbox');
    document.getElementById('lightbox-img').src = img.src;
    lb.classList.add('aktiv');
}
function schliesseLichtbox() {
    document.getElementById('lightbox')?.classList.remove('aktiv');
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') schliesseLichtbox(); });

// Diashow
let aktuellerSlide = 0;
let autoplayTimer = null;
const slides = document.querySelectorAll('.slide');
const thumbnails = document.querySelectorAll('.thumbnail');

function zeigeSlide(richtung) {
    if (!slides.length) return;
    geheZuSlide((aktuellerSlide + richtung + slides.length) % slides.length);
}

function geheZuSlide(index) {
    if (!slides.length) return;
    slides[aktuellerSlide].classList.remove('aktiv');
    thumbnails[aktuellerSlide]?.classList.remove('aktiv');
    aktuellerSlide = index;
    slides[aktuellerSlide].classList.add('aktiv');
    thumbnails[aktuellerSlide]?.classList.add('aktiv');
    thumbnails[aktuellerSlide]?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
    const zaehler = document.getElementById('slide-zaehler');
    if (zaehler) zaehler.textContent = `${aktuellerSlide + 1} / ${slides.length}`;
}

function toggleAutoplay() {
    const btn = document.getElementById('autoplay-btn');
    if (autoplayTimer) {
        clearInterval(autoplayTimer);
        autoplayTimer = null;
        if (btn) btn.textContent = '▶ Autoplay';
    } else {
        autoplayTimer = setInterval(() => zeigeSlide(1), 4000);
        if (btn) btn.textContent = '⏸ Pause';
    }
}

// Tastatursteuerung Diashow
document.addEventListener('keydown', e => {
    if (!slides.length) return;
    if (e.key === 'ArrowRight') zeigeSlide(1);
    if (e.key === 'ArrowLeft') zeigeSlide(-1);
});

// Hintergrundfarben für Kalender (darstellung=hintergrund)
document.querySelectorAll('[data-hintergrund]').forEach(el => {
    el.style.background = el.dataset.hintergrund;
});
