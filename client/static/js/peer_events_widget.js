/**
 * Peer details → "System logs": the latest 5 events, kept live over the same
 * SSE stream as the full page (events.js). New events slide in on top; the
 * stream pauses while the tab is hidden and catches up (after_id) on reconnect.
 */
(function () {
    const E = window.NkEvents;
    const LIMIT = 5;
    const RETRY_MS = 30000;

    const S = {
        peerId: null,
        rows: [],          // newest first, at most LIMIT
        ids: new Set(),
        topId: 0,
        es: null,
        fails: 0,
        timer: null,
        ready: false,      // first list loaded; the stream only runs after that
    };

    const $ = (id) => document.getElementById(id);

    function itemHtml(e, fresh) {
        const repeat = (e.repeat_count || 1) > 1;
        const cls = ['ev-widget-item', repeat ? 'ev-row-repeat' : '', fresh ? 'ev-row-new' : ''].join(' ').trim();
        return `<li class="${cls}">` +
            `<span class="ev-col-time" title="${E.esc(E.fullTime(e.time))}">${E.esc(E.shortTime(e.time))}</span>` +
            E.levelBadge(e.level) +
            `<span class="ev-msg" title="${E.esc(E.categoryLabel(e.category))} · ${E.esc(E.actorLabel(e.actor))}">` +
            `${E.esc(e.message || '')}${repeat ? ` <span class="ev-repeat">×${Number(e.repeat_count)}</span>` : ''}</span>` +
            `</li>`;
    }

    function render(freshIds) {
        const list = $('ev-widget-list');
        if (!S.rows.length) {
            list.hidden = true;
            setState('fa-inbox', 'No events');
            return;
        }
        list.innerHTML = S.rows.map((e) => itemHtml(e, freshIds && freshIds.has(e.id))).join('');
        list.hidden = false;
        $('ev-widget-state').hidden = true;
    }

    function setState(icon, title) {
        const el = $('ev-widget-state');
        el.innerHTML = `<i class="fas ${icon}"></i><span class="ev-state-title">${E.esc(title)}</span>`;
        el.hidden = false;
    }

    function setLive(state) {
        const el = $('ev-live');
        if (!el) return;
        el.hidden = state === 'off';
        el.dataset.state = state;
        $('ev-live-text').textContent = { connecting: 'Connecting', live: 'Live', paused: 'Paused', offline: 'Offline' }[state] || '';
    }

    function add(entries) {
        const fresh = new Set();
        entries.forEach((e) => {
            if (!e || typeof e.id !== 'number' || S.ids.has(e.id)) return;
            S.ids.add(e.id);
            S.rows.push(e);
            fresh.add(e.id);
            if (e.id > S.topId) S.topId = e.id;
        });
        if (!fresh.size) return;
        S.rows.sort((a, b) => b.id - a.id);
        S.rows.splice(LIMIT).forEach((e) => S.ids.delete(e.id));
        render(fresh);
    }

    // ── First load ───────────────────────────────────────────────────────────

    async function load() {
        clearTimeout(S.timer);
        try {
            const data = await E.api.list(S.peerId, { limit: LIMIT });
            S.rows = [];
            S.ids = new Set();
            S.topId = 0;
            (data.entries || []).forEach((e) => {
                S.rows.push(e);
                S.ids.add(e.id);
                if (e.id > S.topId) S.topId = e.id;
            });
            S.rows.sort((a, b) => b.id - a.id);
            render(null);
            S.ready = true;
            startStream();
        } catch (err) {
            const st = E.stateFor(err);
            $('ev-widget-list').hidden = true;
            setState(st.icon, st.title);
            S.ready = false;
            stopStream();
            setLive('off');
            // Offline / temporary errors heal on their own; the rest need action.
            if (st.code === 'offline' || st.code === 'error') S.timer = setTimeout(load, RETRY_MS);
        }
    }

    async function catchUp() {
        if (!S.topId) return;
        try {
            const data = await E.api.list(S.peerId, { after_id: S.topId, limit: LIMIT });
            add(data.entries || []);
        } catch (e) { /* the stream keeps going */ }
    }

    // ── Live stream ──────────────────────────────────────────────────────────

    function stopStream(state) {
        if (S.es) {
            S.es.close();
            S.es = null;
        }
        if (state) setLive(state);
    }

    function startStream() {
        stopStream();
        clearTimeout(S.timer);
        if (document.hidden) {
            setLive('paused');
            return;
        }
        setLive('connecting');
        const es = new EventSource(E.api.streamUrl(S.peerId, {}));
        S.es = es;
        es.onopen = () => {
            if (S.es !== es) return;
            S.fails = 0;
            setLive('live');
            catchUp();
        };
        es.addEventListener('log', (msg) => {
            if (S.es !== es) return;
            try {
                add([JSON.parse(msg.data)]);
            } catch (e) { /* ignore a bad frame */ }
        });
        es.onerror = () => {
            if (S.es !== es) return;
            if (es.readyState === EventSource.CLOSED) {
                // Refused or dropped for good. Back off; from the second failure
                // reload the list, so the widget says why (offline, log off, …).
                stopStream('offline');
                S.fails += 1;
                const delay = Math.min(RETRY_MS, 5000 * 2 ** (S.fails - 1));
                S.timer = setTimeout(S.fails >= 2 ? load : startStream, delay);
            } else {
                setLive('connecting');
            }
        };
    }

    document.addEventListener('DOMContentLoaded', () => {
        const widget = $('ev-widget');
        if (!widget || !E) return;
        S.peerId = widget.dataset.peerId;
        load();

        document.addEventListener('visibilitychange', () => {
            if (!S.ready) return;
            if (document.hidden) {
                if (S.es) stopStream('paused');
            } else if (!S.es && $('ev-live').dataset.state === 'paused') {
                startStream();
            }
        });
    });

    window.EventsWidget = { load, _state: S };
})();
