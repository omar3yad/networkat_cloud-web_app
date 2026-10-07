/**
 * IDS — shared by the IDS page (ids.js) and the peer details frame (peer_ids_widget.js).
 *
 * Data comes from FastAPI: /api/v2/client/peers/<id>/ids/...
 * (fastapi_app/routes/client/ids_ips.py), authenticated by the session cookie;
 * writes get the CSRF header from the fetch interceptor in client_base.html.
 * Errors come back as {"detail": "...", "code": "..."}; `code` picks the state.
 */
(function () {
    const SEVERITIES = ['high', 'medium', 'low'];
    const SEV_LABELS = { high: 'High', medium: 'Medium', low: 'Low' };

    // One entry per page state (design S2): pill, message line, overlay text.
    // tone: ok (blue), warn (amber), err (red), off (grey).
    const STATES = {
        running: { tone: 'ok', icon: 'magnifying-glass-chart', pill: 'Watching', title: 'Watching your network', sw: 'on' },
        starting: {
            tone: 'ok', icon: 'circle-notch', spin: true, pill: 'Starting', title: 'Starting…',
            text: 'First start downloads rules, can take minutes', sw: 'on', busy: true,
        },
        applying: { tone: 'ok', icon: 'gear', spin: true, pill: 'Applying', title: 'Applying change…', sw: 'on', busy: true },
        dropping: { tone: 'warn', icon: 'triangle-exclamation', pill: 'Watching', title: 'Watching your network', sw: 'on' },
        off: {
            tone: 'off', icon: 'power-off', pill: 'Off', title: 'IDS is off',
            text: 'Turn on to watch your network', sw: 'off', veil: 'IDS is off',
        },
        error: {
            tone: 'err', icon: 'circle-exclamation', pill: 'Off', title: 'IDS is off',
            text: 'Turn on to try again', sw: 'off', veil: 'IDS is off',
        },
        memory: {
            tone: 'warn', icon: 'memory', pill: 'Not available', title: 'Not available on this device',
            text: 'Needs 4 GB memory', sw: 'off', lock: true, veil: 'Not available on this device',
        },
        unavailable: {
            tone: 'off', icon: 'clock', pill: 'Unavailable', title: 'Unavailable now',
            text: 'Comes back by itself', sw: 'off', lock: true, veil: 'Unavailable now',
        },
        offline: { tone: 'off', icon: 'plug-circle-xmark', pill: 'Offline', title: 'Device offline', veil: 'Device offline' },
        unsupported: {
            tone: 'off', icon: 'circle-up', pill: 'Update needed', title: 'Update device',
            text: 'This device needs an update for IDS', veil: 'Update device',
        },
        upgrade: {
            tone: 'off', icon: 'crown', pill: 'Not in plan', title: 'Not in your plan',
            text: 'Upgrade to use IDS', veil: 'Not in your plan',
        },
        loading: { tone: 'off', icon: 'circle-notch', spin: true, pill: 'Loading', title: 'Loading' },
        failed: { tone: 'off', icon: 'triangle-exclamation', pill: 'Error', title: 'Couldn\'t load', veil: 'Couldn\'t load' },
    };

    // detection.last_error -> the reason after "Could not start: ".
    const START_ERRORS = {
        insufficient_memory: 'not enough memory',
        insufficient_disk: 'not enough disk space',
        image_unavailable: 'download failed',
        rules_unavailable: 'rules download failed',
        rules_failed: 'rules did not load',
        engine_failed: 'stopped unexpectedly',
    };

    class ApiError extends Error {
        constructor(status, detail, code) {
            super(detail || 'Request failed');
            this.status = status;
            this.code = code || (status === 401 ? 'signed_out' : status === 404 ? 'not_found' : 'error');
        }
    }

    function base(peerId) {
        return `/api/v2/client/peers/${encodeURIComponent(peerId)}/ids`;
    }

    function query(params) {
        return new URLSearchParams(
            Object.entries(params || {}).filter(([, v]) => v !== null && v !== undefined && v !== '')
        ).toString();
    }

    // Reads shared by many windows (settings, aliases): one request serves every caller for a few
    // seconds, and each caller gets its own copy. Any write clears it (bust), so a read after a
    // save is always fresh. The short life also covers changes made from another tab.
    const CACHE_MS = 10000;
    const cache = new Map();

    function copy(v) {
        return v === undefined ? v : JSON.parse(JSON.stringify(v));
    }

    function cached(key, fetcher) {
        const hit = cache.get(key);
        if (hit && Date.now() - hit.at < CACHE_MS) return hit.p.then(copy);
        const entry = { at: Date.now(), p: fetcher() };
        cache.set(key, entry);
        entry.p.catch(() => { if (cache.get(key) === entry) cache.delete(key); });
        return entry.p.then(copy);
    }

    function bust() {
        cache.clear();
    }

    async function request(peerId, path, { method = 'GET', params, body } = {}) {
        const qs = query(params);
        const init = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
        if (body !== undefined) {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(body);
        }
        let res;
        try {
            res = await fetch(base(peerId) + path + (qs ? `?${qs}` : ''), init);
        } catch (e) {
            if (method !== 'GET') bust();
            throw new ApiError(0, 'Network error', 'error');
        }
        if (method !== 'GET') bust();
        let data = null;
        try { data = await res.json(); } catch (e) { /* empty body */ }
        if (!res.ok) {
            const detail = data && typeof data.detail === 'string' ? data.detail : null;
            throw new ApiError(res.status, detail, data && data.code);
        }
        return data;
    }

    // The peer's alias lists, as the alias API returns them (each window picks what it shows).
    async function fetchAliases(peerId) {
        const res = await fetch(`${window.API_BASE || ''}/api/peers/${encodeURIComponent(peerId)}/aliases`,
            { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        const data = await res.json();
        if (!res.ok) throw new Error('aliases');
        return data;
    }

    const api = {
        status: (peerId) => request(peerId, ''),
        setEnabled: (peerId, enabled) => request(peerId, '/enabled', { method: 'PUT', body: { enabled } }),
        settings: (peerId) => cached(`${peerId}:settings`, () => request(peerId, '/settings')),
        aliases: (peerId) => cached(`${peerId}:aliases`, () => fetchAliases(peerId)),
        bust,
        threats: (peerId, params) => request(peerId, '/threats', { params }),
        summary: (peerId, since) => request(peerId, '/threats/summary', { params: { since } }),
        clear: (peerId) => request(peerId, '/threats', { method: 'DELETE' }),
        setRule: (peerId, sid, change) => request(peerId, `/rules/${encodeURIComponent(sid)}`, { method: 'PUT', body: change }),
        removeRule: (peerId, sid) => request(peerId, `/rules/${encodeURIComponent(sid)}`, { method: 'DELETE' }),
        list: (peerId, name) => request(peerId, `/${name}`),
        add: (peerId, name, item) => request(peerId, `/${name}`, { method: 'POST', body: item }),
        remove: (peerId, name, id) => request(peerId, `/${name}/${encodeURIComponent(id)}`, { method: 'DELETE' }),
        streamUrl: (peerId, params) => {
            const qs = query(params);
            return base(peerId) + '/threats/stream' + (qs ? `?${qs}` : '');
        },
    };

    // The page state from GET /ids (or null when the IDS is on and fine).
    function stateFromStatus(status) {
        const d = (status && status.detection) || {};
        if (d.state === 'unavailable') return 'unavailable';
        if (d.state !== 'enabled') {
            if (d.enough_memory === false) return 'memory';
            return d.last_error ? 'error' : 'off';
        }
        if (d.starting || (!d.running && !d.last_error)) return 'starting';
        if (!d.running) return 'error';
        if (d.applying) return 'applying';
        return d.dropping_packets ? 'dropping' : 'running';
    }

    function stateFromError(err) {
        const code = err && err.code;
        if (code === 'offline' || code === 'unsupported' || code === 'upgrade' || code === 'unavailable') return code;
        return 'failed';
    }

    function startError(status) {
        const d = (status && status.detection) || {};
        if (!d.last_error) return '';
        const why = START_ERRORS[d.last_error] || 'it stopped';
        return `Could not start: ${why}` + (d.last_error_at ? ` · ${dateTime(d.last_error_at)}` : '');
    }

    function esc(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    function pad(n) {
        return String(n).padStart(2, '0');
    }

    // "YYYY-MM-DD HH:MM" local.
    function dateTime(iso) {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    // "YYYY-MM-DD HH:MM:SS" local, for hover.
    function fullTime(iso) {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        return `${dateTime(iso)}:${pad(d.getSeconds())}`;
    }

    // Table time: "HH:MM" today, "MM-DD" before.
    function shortTime(iso) {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        const now = new Date();
        if (d.toDateString() === now.toDateString()) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
        return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    }

    function sevLabel(sev) {
        return SEV_LABELS[sev] || sev || '';
    }

    function sevClass(sev) {
        return `ids-sev-${SEVERITIES.includes(sev) ? sev : 'low'}`;
    }

    // Older peers name a WAN "Internet link N"; the portal says "WAN N".
    function placeLabel(label) {
        if (!label) return '';
        return String(label).replace(/^Internet link (\d+)$/, 'WAN $1');
    }

    function deviceLabel(e) {
        const d = e.lan_device || {};
        return d.name || d.ip || placeLabel(e.interface_label) || '—';
    }

    function remoteLabel(e) {
        const r = e.remote || {};
        return r.name || r.ip || '—';
    }

    function timesLabel(n) {
        n = Number(n) || 1;
        return n === 1 ? '1 time' : `${n.toLocaleString('en-US')} times`;
    }

    function stateIcon(s) {
        return IdsIcon(s.icon, { spin: !!s.spin });
    }

    function pillHtml(stateKey) {
        const s = STATES[stateKey] || STATES.failed;
        const run = stateKey === 'running' ? ' ids-pill-run' : '';
        return `<span class="ids-pill ids-tone-${s.tone}${run}">${stateIcon(s)}${esc(s.pill)}</span>`;
    }

    // "Update device" link, like system logs: opens the update window on the
    // details page, or goes there with ?update=1.
    function updateLink(detailsUrl) {
        const a = document.createElement('a');
        a.className = 'sl-state-link';
        a.innerHTML = IdsIcon('arrow-alt-circle-up') + '<span>Update device</span>';
        if (typeof window.openUpdatesModal === 'function') {
            a.href = 'javascript:void(0)';
            a.onclick = () => window.openUpdatesModal();
        } else {
            a.href = `${detailsUrl}${detailsUrl.includes('?') ? '&' : '?'}update=1`;
        }
        return a;
    }

    // A window that opens takes the keyboard focus itself, never its first field: no cursor and no
    // on-screen keyboard on phones until the person picks a field. Tab, Enter and Escape still work from it.
    function focusDialog(root) {
        const card = root && (root.querySelector('[role="dialog"], .modal-card') || root);
        if (!card) return;
        if (!card.hasAttribute('tabindex')) card.setAttribute('tabindex', '-1');
        card.style.outline = 'none';
        card.focus({ preventScroll: true });
    }

    window.NkIds = {
        SEVERITIES, STATES, stateIcon, ApiError, api, esc, focusDialog,
        stateFromStatus, stateFromError, startError,
        dateTime, fullTime, shortTime, sevLabel, sevClass, placeLabel, deviceLabel, remoteLabel, timesLabel,
        pillHtml, updateLink,
    };
})();
