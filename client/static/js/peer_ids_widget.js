/**
 * Peer details → "IDS": the state pill, a last-24-hours strip (counts per
 * severity, like a language bar) and the latest 5 threats, kept live over the
 * same SSE stream as the IDS page. A row opens the IDS page with that threat
 * open; a legend item opens it filtered by that severity.
 */
(function () {
    const N = window.NkIds;
    const LIMIT = 5;
    const RETRY_MS = 30000;
    const STATUS_MS = 60000;

    const S = {
        peerId: null,
        pageUrl: '',
        rows: [],          // newest first, at most LIMIT
        counts: null,      // last 24 h {high, medium, low}
        state: 'loading',
        es: null,
        fails: 0,
        timer: null,
        statusTimer: null,
        summaryTimer: null,
        ready: false,
    };

    const $ = (id) => document.getElementById(id);

    function link(params) {
        const qs = new URLSearchParams(params).toString();
        return S.pageUrl + (qs ? `?${qs}` : '');
    }

    function setPill(stateKey, status) {
        S.state = stateKey;
        const pillEl = $('ids-widget-pill');
        if (pillEl) {
            N.updatePill(pillEl, status, stateKey);
        }
    }

    function setBox(stateKey, extraTitle, extraText) {
        const s = N.STATES[stateKey] || N.STATES.failed;
        const el = $('ids-widget-state');
        const title = extraTitle || s.veil || s.title;
        const text = extraText !== undefined ? extraText : (s.text || '');
        el.className = `sl-state ids-state ids-tone-${s.tone}`;
        el.innerHTML = `${N.stateIcon(s)}<span class="sl-state-title">${N.esc(title)}</span>` +
            (text ? `<span class="sl-state-text">${N.esc(text)}</span>` : '');
        if (stateKey === 'unsupported') el.appendChild(N.updateLink(''));
        el.hidden = false;
    }

    function stripHtml() {
        const c = S.counts || { high: 0, medium: 0, low: 0 };
        const total = N.SEVERITIES.reduce((n, k) => n + (Number(c[k]) || 0), 0);
        const bar = N.SEVERITIES.filter((k) => c[k] > 0)
            .map((k) => `<i class="${N.sevClass(k)}" style="flex:${Number(c[k])}" title="${N.sevLabel(k)}: ${Number(c[k]).toLocaleString('en-US')}"></i>`)
            .join('');
        const legend = N.SEVERITIES.map((k) =>
            `<a class="${N.sevClass(k)}" href="${N.esc(link({ severity: k, range: '24h' }))}">` +
            `<span class="ids-dot"></span>${N.sevLabel(k)} <span>${(Number(c[k]) || 0).toLocaleString('en-US')}</span></a>`).join('');
        return `<div class="ids-strip"><div class="ids-strip-head"><b>Last 24 hours</b>${total.toLocaleString('en-US')} ${total === 1 ? 'threat' : 'threats'}</div>` +
            `<div class="ids-strip-bar">${bar}</div><div class="ids-strip-legend">${legend}</div></div>`;
    }

    function rowHtml(e, fresh) {
        return `<tr class="${N.sevClass(e.severity)}${fresh ? ' ids-row-new' : ''}" data-id="${Number(e.id)}" tabindex="0">` +
            `<td><span class="ids-sev-dot"><span>${N.sevLabel(e.severity)}</span></span></td>` +
            `<td title="${N.esc(N.fullTime(e.last_seen || e.time))}">${N.esc(N.shortTime(e.last_seen || e.time))}</td>` +
            `<td class="ids-c-kind">${N.esc(e.kind || '')}</td>` +
            `<td title="${N.esc(N.deviceLabel(e))}">${N.esc(N.deviceLabel(e))}</td>` +
            `<td class="ids-c-rem" title="${N.esc(N.remoteLabel(e))}">${N.esc(N.remoteLabel(e))}</td>` +
            `<td title="Seen ${N.esc(N.timesLabel(e.repeat_count))}">${(Number(e.repeat_count) || 1).toLocaleString('en-US')}</td></tr>`;
    }

    function render(freshId) {
        const body = $('ids-widget-body');
        if (S.state !== 'running' && S.state !== 'dropping' && S.state !== 'applying' && S.state !== 'starting') {
            body.hidden = true;
            setBox(S.state);
            return;
        }
        let html = stripHtml();
        if (S.rows.length) {
            html += '<table class="ids-mini"><colgroup><col class="ids-c-sev"><col class="ids-c-time"><col class="ids-c-kind"><col><col class="ids-c-rem"><col class="ids-c-n"></colgroup>' +
                '<thead><tr><th><span class="ids-c-sevt">Severity</span></th><th>Time</th><th class="ids-c-kind">Kind</th><th>Device</th><th class="ids-c-rem">Remote</th><th>Times</th></tr></thead>' +
                `<tbody>${S.rows.map((e) => rowHtml(e, e.id === freshId)).join('')}</tbody></table>`;
            $('ids-widget-state').hidden = true;
        } else {
            setBox('running', 'No threats', 'Nothing found in the last 24 hours.');
            $('ids-widget-state').className = 'sl-state ids-state ids-tone-ok';
            $('ids-widget-state').querySelector('.ids-i').outerHTML = IdsIcon('circle-check');
        }
        body.innerHTML = html;
        body.hidden = false;
    }

    // ── Loading ──────────────────────────────────────────────────────────────

    function scheduleStatus(status) {
        clearTimeout(S.statusTimer);
        const d = (status && status.detection) || {};
        const hasProgress = typeof d.progress === 'number' && !isNaN(d.progress);
        const isBusy = hasProgress || d.applying === true || d.starting === true;
        const delay = isBusy ? 1000 : STATUS_MS;
        S.statusTimer = setTimeout(refreshStatus, delay);
    }

    async function refreshStatus() {
        try {
            const status = await N.api.status(S.peerId);
            const key = N.stateFromStatus(status);
            const changed = key !== S.state;
            setPill(key, status);
            if (changed) render(null);
            scheduleStatus(status);
        } catch (err) {
            setPill(N.stateFromError(err), null);
            render(null);
            scheduleStatus(null);
        }
    }

    async function refreshSummary() {
        try {
            const sum = await N.api.summary(S.peerId);
            S.counts = sum.counts || null;
            render(null);
        } catch (e) { /* keeps the last counts */ }
    }

    async function load() {
        clearTimeout(S.timer);
        clearTimeout(S.statusTimer);
        try {
            const [status, sum, list] = await Promise.all([
                N.api.status(S.peerId),
                N.api.summary(S.peerId),
                N.api.threats(S.peerId, { limit: LIMIT }),
            ]);
            setPill(N.stateFromStatus(status), status);
            S.counts = sum.counts || null;
            S.rows = (list.entries || []).slice(0, LIMIT);
            render(null);
            S.ready = true;
            scheduleStatus(status);
            startStream();
        } catch (err) {
            const key = N.stateFromError(err);
            setPill(key, null);
            render(null);
            S.ready = false;
            stopStream();
            if (key === 'offline' || key === 'failed') S.timer = setTimeout(load, RETRY_MS);
        }
    }

    function onThreat(e) {
        if (!e || typeof e.id !== 'number' || S.rows.some((r) => r.id === e.id)) return;
        S.rows.unshift(e);
        S.rows.splice(LIMIT);
        if (S.counts && e.severity in S.counts) S.counts[e.severity] += Number(e.repeat_count) || 1;
        render(e.id);
    }

    function onRepeat(d) {
        const row = S.rows.find((r) => r.id === d.id);
        if (row) {
            row.repeat_count = d.repeat_count;
            row.last_seen = d.last_seen;
            render(null);
        }
        // A repeat of an older row changes the counts too: re-read them, at most every 10 s.
        if (!S.summaryTimer) S.summaryTimer = setTimeout(() => { S.summaryTimer = null; refreshSummary(); }, 10000);
    }

    // ── Live stream ──────────────────────────────────────────────────────────

    function stopStream(state) {
        if (S.es) {
            S.es.close();
            S.es = null;
        }
        if (state === 'paused') S.paused = true;
    }

    function startStream() {
        stopStream();
        clearTimeout(S.timer);
        S.paused = false;
        if (document.hidden) {
            S.paused = true;
            return;
        }
        const es = new EventSource(N.api.streamUrl(S.peerId, {}));
        S.es = es;
        es.onopen = () => {
            if (S.es !== es) return;
            S.fails = 0;
        };
        es.addEventListener('threat', (msg) => {
            if (S.es !== es) return;
            try { onThreat(JSON.parse(msg.data)); } catch (e) { /* ignore a bad frame */ }
        });
        es.addEventListener('repeat', (msg) => {
            if (S.es !== es) return;
            try { onRepeat(JSON.parse(msg.data)); } catch (e) { /* ignore a bad frame */ }
        });
        es.onerror = () => {
            if (S.es !== es) return;
            if (es.readyState === EventSource.CLOSED) {
                stopStream('offline');
                S.fails += 1;
                const delay = Math.min(RETRY_MS, 5000 * 2 ** (S.fails - 1));
                S.timer = setTimeout(S.fails >= 2 ? load : startStream, delay);
            }
        };
    }

    function openRow(tr) {
        if (tr && tr.dataset.id) window.location.href = link({ threat: tr.dataset.id });
    }

    document.addEventListener('DOMContentLoaded', () => {
        const widget = $('ids-widget');
        if (!widget || !N) return;
        S.peerId = widget.dataset.peerId;
        S.pageUrl = widget.dataset.pageUrl;
        if (widget.dataset.peerOnline !== 'true') {
            setPill('offline');
            render(null);
            return;
        }
        setPill('loading');
        load();

        $('ids-widget-body').addEventListener('click', (e) => openRow(e.target.closest('tr[data-id]')));
        $('ids-widget-body').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') openRow(e.target.closest('tr[data-id]'));
        });
        document.addEventListener('visibilitychange', () => {
            if (!S.ready) return;
            if (document.hidden) {
                if (S.es) stopStream('paused');
            } else if (!S.es && S.paused) {
                startStream();
                refreshSummary();
            }
        });
    });

    window.PeerIdsWidget = { load, _state: S };
})();
