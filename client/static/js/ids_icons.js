/**
 * IDS icons: thin line icons (Lucide, ISC license) drawn as inline SVG, replacing Font Awesome on the IDS
 * page and its windows. Keys are the old Font Awesome names, so `<i class="fas fa-trash"></i>` becomes
 * IdsIcon('trash'). The icon takes the text color (currentColor) and the font size (1em).
 *
 *   IdsIcon(name)                  -> '<svg class="ids-i ids-i-name" ...>'
 *   IdsIcon(name, {spin: true})    -> spinning (loaders)
 *   IdsIcon(name, {cls: 'x'})      -> extra class
 *   <span data-ids-i="name"></span> in a template is filled once the page loads (IdsIcon.fill(root) for later HTML).
 *
 * A missing name draws nothing and logs once. To add one: the SVG body from lucide-static, under its old name.
 */
(function () {
    const P = {
        "triangle-exclamation": "<path d=\"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3\"/> <path d=\"M12 9v4\"/> <path d=\"M12 17h.01\"/>",
        "circle-notch": "<path d=\"M21 12a9 9 0 1 1-6.219-8.56\"/>",
        "spinner": "<path d=\"M12 2v4\"/> <path d=\"m16.2 7.8 2.9-2.9\"/> <path d=\"M18 12h4\"/> <path d=\"m16.2 16.2 2.9 2.9\"/> <path d=\"M12 18v4\"/> <path d=\"m4.9 19.1 2.9-2.9\"/> <path d=\"M2 12h4\"/> <path d=\"m4.9 4.9 2.9 2.9\"/>",
        "check": "<path d=\"M20 6 9 17l-5-5\"/>",
        "chevron-right": "<path d=\"m9 18 6-6-6-6\"/>",
        "chevron-down": "<path d=\"m6 9 6 6 6-6\"/>",
        "chevron-up": "<path d=\"m18 15-6-6-6 6\"/>",
        "chevron-left": "<path d=\"m15 18-6-6 6-6\"/>",
        "plus": "<path d=\"M5 12h14\"/> <path d=\"M12 5v14\"/>",
        "minus": "<path d=\"M5 12h14\"/>",
        "plus-circle": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <path d=\"M8 12h8\"/> <path d=\"M12 8v8\"/>",
        "circle-plus": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <path d=\"M8 12h8\"/> <path d=\"M12 8v8\"/>",
        "circle-exclamation": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <line x1=\"12\" x2=\"12\" y1=\"8\" y2=\"12\"/> <line x1=\"12\" x2=\"12.01\" y1=\"16\" y2=\"16\"/>",
        "exclamation-circle": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <line x1=\"12\" x2=\"12\" y1=\"8\" y2=\"12\"/> <line x1=\"12\" x2=\"12.01\" y1=\"16\" y2=\"16\"/>",
        "floppy-disk": "<path d=\"M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z\"/> <path d=\"M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7\"/> <path d=\"M7 3v4a1 1 0 0 0 1 1h7\"/>",
        "gear": "<path d=\"M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z\"/> <circle cx=\"12\" cy=\"12\" r=\"3\"/>",
        "trash": "<path d=\"M3 6h18\"/> <path d=\"M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6\"/> <path d=\"M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2\"/> <line x1=\"10\" x2=\"10\" y1=\"11\" y2=\"17\"/> <line x1=\"14\" x2=\"14\" y1=\"11\" y2=\"17\"/>",
        "trash-can": "<path d=\"M3 6h18\"/> <path d=\"M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6\"/> <path d=\"M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2\"/> <line x1=\"10\" x2=\"10\" y1=\"11\" y2=\"17\"/> <line x1=\"14\" x2=\"14\" y1=\"11\" y2=\"17\"/>",
        "trash-alt": "<path d=\"M3 6h18\"/> <path d=\"M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6\"/> <path d=\"M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2\"/> <line x1=\"10\" x2=\"10\" y1=\"11\" y2=\"17\"/> <line x1=\"14\" x2=\"14\" y1=\"11\" y2=\"17\"/>",
        "rotate-left": "<path d=\"M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8\"/> <path d=\"M3 3v5h5\"/>",
        "circle-info": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <path d=\"M12 16v-4\"/> <path d=\"M12 8h.01\"/>",
        "bell-slash": "<path d=\"M10.268 21a2 2 0 0 0 3.464 0\"/> <path d=\"M17 17H4a1 1 0 0 1-.74-1.673C4.59 13.956 6 12.499 6 8a6 6 0 0 1 .258-1.742\"/> <path d=\"m2 2 20 20\"/> <path d=\"M8.668 3.01A6 6 0 0 1 18 8c0 2.687.77 4.653 1.707 6.05\"/>",
        "magnifying-glass": "<circle cx=\"11\" cy=\"11\" r=\"8\"/> <path d=\"m21 21-4.3-4.3\"/>",
        "list-check": "<path d=\"m3 17 2 2 4-4\"/> <path d=\"m3 7 2 2 4-4\"/> <path d=\"M13 6h8\"/> <path d=\"M13 12h8\"/> <path d=\"M13 18h8\"/>",
        "external-link-alt": "<path d=\"M15 3h6v6\"/> <path d=\"M10 14 21 3\"/> <path d=\"M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6\"/>",
        "sliders": "<line x1=\"21\" x2=\"14\" y1=\"4\" y2=\"4\"/> <line x1=\"10\" x2=\"3\" y1=\"4\" y2=\"4\"/> <line x1=\"21\" x2=\"12\" y1=\"12\" y2=\"12\"/> <line x1=\"8\" x2=\"3\" y1=\"12\" y2=\"12\"/> <line x1=\"21\" x2=\"16\" y1=\"20\" y2=\"20\"/> <line x1=\"12\" x2=\"3\" y1=\"20\" y2=\"20\"/> <line x1=\"14\" x2=\"14\" y1=\"2\" y2=\"6\"/> <line x1=\"8\" x2=\"8\" y1=\"10\" y2=\"14\"/> <line x1=\"16\" x2=\"16\" y1=\"18\" y2=\"22\"/>",
        "signal": "<path d=\"M2 20h.01\"/> <path d=\"M7 20v-4\"/> <path d=\"M12 20v-8\"/> <path d=\"M17 20V8\"/> <path d=\"M22 4v16\"/>",
        "pen-to-square": "<path d=\"M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7\"/> <path d=\"M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z\"/>",
        "pen": "<path d=\"M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z\"/> <path d=\"m15 5 4 4\"/>",
        "network-wired": "<rect x=\"16\" y=\"16\" width=\"6\" height=\"6\" rx=\"1\"/> <rect x=\"2\" y=\"16\" width=\"6\" height=\"6\" rx=\"1\"/> <rect x=\"9\" y=\"2\" width=\"6\" height=\"6\" rx=\"1\"/> <path d=\"M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3\"/> <path d=\"M12 12V8\"/>",
        "gauge": "<path d=\"m12 14 4-4\"/> <path d=\"M3.34 19a10 10 0 1 1 17.32 0\"/>",
        "eye-slash": "<path d=\"M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49\"/> <path d=\"M14.084 14.158a3 3 0 0 1-4.242-4.242\"/> <path d=\"M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143\"/> <path d=\"m2 2 20 20\"/>",
        "circle-check": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <path d=\"m9 12 2 2 4-4\"/>",
        "box-archive": "<rect width=\"20\" height=\"5\" x=\"2\" y=\"3\" rx=\"1\"/> <path d=\"M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8\"/> <path d=\"M10 12h4\"/>",
        "ban": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <path d=\"m4.9 4.9 14.2 14.2\"/>",
        "power-off": "<path d=\"M12 2v10\"/> <path d=\"M18.4 6.6a9 9 0 1 1-12.77.04\"/>",
        "plug-circle-xmark": "<path d=\"m19 5 3-3\"/> <path d=\"m2 22 3-3\"/> <path d=\"M6.3 20.3a2.4 2.4 0 0 0 3.4 0L12 18l-6-6-2.3 2.3a2.4 2.4 0 0 0 0 3.4Z\"/> <path d=\"M7.5 13.5 10 11\"/> <path d=\"M10.5 16.5 13 14\"/> <path d=\"m12 6 6 6 2.3-2.3a2.4 2.4 0 0 0 0-3.4l-2.6-2.6a2.4 2.4 0 0 0-3.4 0Z\"/>",
        "memory": "<path d=\"M6 19v-3\"/> <path d=\"M10 19v-3\"/> <path d=\"M14 19v-3\"/> <path d=\"M18 19v-3\"/> <path d=\"M8 11V9\"/> <path d=\"M16 11V9\"/> <path d=\"M12 11V9\"/> <path d=\"M2 15h20\"/> <path d=\"M2 7a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v1.1a2 2 0 0 0 0 3.837V17a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-5.1a2 2 0 0 0 0-3.837Z\"/>",
        "magnifying-glass-chart": "<path d=\"M3 7V5a2 2 0 0 1 2-2h2\"/> <path d=\"M17 3h2a2 2 0 0 1 2 2v2\"/> <path d=\"M21 17v2a2 2 0 0 1-2 2h-2\"/> <path d=\"M7 21H5a2 2 0 0 1-2-2v-2\"/> <circle cx=\"12\" cy=\"12\" r=\"3\"/> <path d=\"m16 16-1.9-1.9\"/>",
        "lock": "<rect width=\"18\" height=\"11\" x=\"3\" y=\"11\" rx=\"2\" ry=\"2\"/> <path d=\"M7 11V7a5 5 0 0 1 10 0v4\"/>",
        "list": "<path d=\"M3 12h.01\"/> <path d=\"M3 18h.01\"/> <path d=\"M3 6h.01\"/> <path d=\"M8 12h13\"/> <path d=\"M8 18h13\"/> <path d=\"M8 6h13\"/>",
        "filter": "<polygon points=\"22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3\"/>",
        "crown": "<path d=\"M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.734H5.81a1 1 0 0 1-.957-.734L2.02 6.02a.5.5 0 0 1 .798-.519l4.276 3.664a1 1 0 0 0 1.516-.294z\"/> <path d=\"M5 21h14\"/>",
        "clock": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <polyline points=\"12 6 12 12 16 14\"/>",
        "circle-up": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <path d=\"m16 12-4-4-4 4\"/> <path d=\"M12 16V8\"/>",
        "arrow-alt-circle-up": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <path d=\"m16 12-4-4-4 4\"/> <path d=\"M12 16V8\"/>",
        "arrow-left": "<path d=\"m12 19-7-7 7-7\"/> <path d=\"M19 12H5\"/>",
        "arrow-right": "<path d=\"M5 12h14\"/> <path d=\"m12 5 7 7-7 7\"/>",
        "xmark": "<path d=\"M18 6 6 18\"/> <path d=\"m6 6 12 12\"/>",
        "eye": "<path d=\"M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0\"/> <circle cx=\"12\" cy=\"12\" r=\"3\"/>",
        "bell": "<path d=\"M10.268 21a2 2 0 0 0 3.464 0\"/> <path d=\"M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326\"/>",
        "shield": "<path d=\"M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z\"/>",
        "shield-halved": "<path d=\"M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z\"/> <path d=\"M12 22V2\"/>",
        "copy": "<rect width=\"14\" height=\"14\" x=\"8\" y=\"8\" rx=\"2\" ry=\"2\"/> <path d=\"M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2\"/>",
        "download": "<path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\"/> <polyline points=\"7 10 12 15 17 10\"/> <line x1=\"12\" x2=\"12\" y1=\"15\" y2=\"3\"/>",
        "upload": "<path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\"/> <polyline points=\"17 8 12 3 7 8\"/> <line x1=\"12\" x2=\"12\" y1=\"3\" y2=\"15\"/>",
        "refresh": "<path d=\"M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8\"/> <path d=\"M21 3v5h-5\"/> <path d=\"M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16\"/> <path d=\"M8 16H3v5\"/>",
        "rotate": "<path d=\"M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8\"/> <path d=\"M21 3v5h-5\"/>",
        "ellipsis": "<circle cx=\"12\" cy=\"12\" r=\"1\"/> <circle cx=\"19\" cy=\"12\" r=\"1\"/> <circle cx=\"5\" cy=\"12\" r=\"1\"/>",
        "circle-xmark": "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <path d=\"m15 9-6 6\"/> <path d=\"m9 9 6 6\"/>"
    };
    const warned = {};

    function IdsIcon(name, opt) {
        const key = String(name || '').replace(/^fa-/, '');
        const body = P[key];
        if (!body) {
            if (!warned[key]) { warned[key] = 1; console.warn('IdsIcon: no icon', key); }
            return '';
        }
        const o = opt || {};
        const cls = 'ids-i ids-i-' + key + (o.spin ? ' ids-i-spin' : '') + (o.cls ? ' ' + o.cls : '');
        return '<svg class="' + cls + '" xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 24 24" ' +
            'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
            body + '</svg>';
    }

    IdsIcon.has = (name) => !!P[String(name || '').replace(/^fa-/, '')];

    // Fill <span data-ids-i="name" [data-ids-spin]> placeholders under root.
    IdsIcon.fill = function (root) {
        (root || document).querySelectorAll('[data-ids-i]').forEach((el) => {
            if (el.dataset.idsDone) return;
            el.dataset.idsDone = '1';
            el.innerHTML = IdsIcon(el.dataset.idsI, { spin: 'idsSpin' in el.dataset });
        });
    };

    window.IdsIcon = IdsIcon;
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => IdsIcon.fill());
    else IdsIcon.fill();
})();
