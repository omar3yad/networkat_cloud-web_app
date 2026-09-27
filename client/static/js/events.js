/**
 * Event log page (client/templates/events.html).
 *
 * List + filters + "Load older" over GET /events, live updates over the SSE
 * stream (EventSource; it resends Last-Event-ID itself after the 30-minute
 * close). After every (re)connect the gap is filled from GET /events?after_id=,
 * and rows are de-duplicated by id. The stream is closed while the tab is
 * hidden.
 */
(function () {
    const E = window.NkEvents;
    const CATEGORY_ORDER = Object.keys(E.CATEGORY_LABELS);
    const PAGE_SIZE = 50;
    const RETRY_MS = 30000;
    const PAUSE_OPTIONS = [[60, '1 hour'], [480, '8 hours'], [1440, '24 hours'], [10080, '7 days']];

    const S = {
        peerId: '',
        readonly: false,
        filters: { category: '', level: '', range: '', q: '' },
        rows: [],              // newest first
        ids: new Set(),
        topId: 0,              // highest id seen, for catch-up
        nextBeforeId: null,
        hasMore: false,
        counts: {},            // category -> count (client view)
        categories: [],        // from /categories
        config: null,          // from /config
        es: null,
        retryTimer: null,
        streamFails: 0,
        reloadSeq: 0,
        pendingNew: 0,
        searchTimer: null,
    };

    const $ = (id) => document.getElementById(id);

    // ── Filters ──────────────────────────────────────────────────────────────

    function filterParams() {
        const f = S.filters;
        const since = f.range ? new Date(Date.now() - Number(f.range) * 3600 * 1000).toISOString() : '';
        return { category: f.category, level: f.level, q: f.q.trim(), since };
    }

    function streamParams() {
        const f = S.filters;
        return { category: f.category, level: f.level, q: f.q.trim() };
    }

    function setCategory(name) {
        S.filters.category = name;
        document.querySelectorAll('#ev-chips .ev-chip').forEach((chip) => {
            chip.classList.toggle('active', chip.dataset.category === name);
        });
        refresh();
    }

    function applyFilters() {
        S.filters.level = $('ev-level').value;
        S.filters.range = $('ev-range').value;
        refresh();
    }

    function onSearchInput() {
        clearTimeout(S.searchTimer);
        S.searchTimer = setTimeout(() => {
            const q = $('ev-q').value;
            if (q.trim() === S.filters.q.trim()) return;
            S.filters.q = q;
            refresh();
        }, 350);
    }

    function refresh() {
        reload();
        startStream();
    }

    // ── Chips / counts ───────────────────────────────────────────────────────

    function renderChips() {
        const wrap = $('ev-chips');
        CATEGORY_ORDER.forEach((name) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'ev-chip';
            btn.dataset.category = name;
            btn.innerHTML = `<i class="fas ${E.CATEGORY_ICONS[name]}"></i><span>${E.esc(E.categoryLabel(name))}</span>` +
                `<span class="ev-chip-count" id="ev-count-${name}"></span>`;
            btn.onclick = () => setCategory(name);
            wrap.appendChild(btn);
        });
    }

    function renderCounts() {
        let total = 0;
        CATEGORY_ORDER.forEach((name) => {
            const n = S.counts[name];
            const el = $(`ev-count-${name}`);
            if (el) el.textContent = typeof n === 'number' ? n : '';
            if (typeof n === 'number') total += n;
        });
        const all = $('ev-count-all');
        if (all) all.textContent = S.categories.length ? total : '';
    }

    async function loadCategories() {
        try {
            const data = await E.api.categories(S.peerId);
            S.categories = data.categories || [];
            S.counts = {};
            S.categories.forEach((c) => {
                S.counts[c.name] = c.count || 0;
                const chip = document.querySelector(`#ev-chips .ev-chip[data-category="${c.name}"]`);
                if (chip && c.description) chip.title = c.description;
            });
            renderCounts();
        } catch (e) {
            // Counts are optional; the list shows the error state.
        }
    }

    // ── Rows ─────────────────────────────────────────────────────────────────

    function rowHtml(e) {
        const repeat = (e.repeat_count || 1) > 1;
        const icon = E.CATEGORY_ICONS[e.category] || 'fa-circle';
        return `<tr class="ev-row ev-row-${E.esc(e.level)}${repeat ? ' ev-row-repeat' : ''}" data-id="${e.id}">` +
            `<td class="ev-col-time" title="${E.esc(E.fullTime(e.time))}">${E.esc(E.shortTime(e.time))}</td>` +
            `<td class="ev-col-level">${E.levelBadge(e.level)}</td>` +
            `<td class="ev-col-cat"><i class="fas ${icon}"></i> ${E.esc(E.categoryLabel(e.category))}</td>` +
            `<td class="ev-msg">${E.esc(e.message || '')}` +
            (repeat ? ` <span class="ev-repeat">×${Number(e.repeat_count)}</span>` : '') + `</td>` +
            `<td class="ev-col-by">${E.esc(E.actorLabel(e.actor))}</td>` +
            `</tr>`;
    }

    function renderRows() {
        const body = $('ev-rows');
        body.innerHTML = S.rows.map(rowHtml).join('');
        if (S.rows.length) {
            $('ev-table').hidden = false;
            hideState();
        } else {
            $('ev-table').hidden = true;
            showState({ icon: 'fa-inbox', title: 'No events' });
        }
        $('ev-btn-more').hidden = !S.hasMore;
    }

    function addEntries(entries) {
        entries.forEach((e) => {
            if (!e || S.ids.has(e.id)) return;
            S.ids.add(e.id);
            S.rows.push(e);
            if (e.id > S.topId) S.topId = e.id;
        });
        S.rows.sort((a, b) => b.id - a.id);
    }

    // One live entry: insert in place, flash it, bump its count.
    function onLiveEntry(e) {
        if (!e || typeof e.id !== 'number' || S.ids.has(e.id)) return;
        if (e.id > S.topId) S.topId = e.id;
        S.ids.add(e.id);
        S.rows.push(e);
        S.rows.sort((a, b) => b.id - a.id);
        if (typeof S.counts[e.category] === 'number') {
            S.counts[e.category] += 1;
            renderCounts();
        }

        const body = $('ev-rows');
        const idx = S.rows.indexOf(e);
        const tpl = document.createElement('tbody');
        tpl.innerHTML = rowHtml(e);
        const tr = tpl.firstChild;
        tr.classList.add('ev-row-new');
        body.insertBefore(tr, body.children[idx] || null);
        $('ev-table').hidden = false;
        hideState();

        if (isScrolledAway()) {
            S.pendingNew += 1;
            $('ev-new-text').textContent = S.pendingNew === 1 ? '1 new event' : `${S.pendingNew} new events`;
            $('ev-new-pill').hidden = false;
        }
    }

    function isScrolledAway() {
        const card = $('ev-table-wrap');
        return card && card.getBoundingClientRect().top < 0;
    }

    function showNew() {
        S.pendingNew = 0;
        $('ev-new-pill').hidden = true;
        $('ev-chips').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // ── States ───────────────────────────────────────────────────────────────

    function showState({ icon, title, spin = false, action = null }) {
        const el = $('ev-state');
        el.innerHTML = `<i class="fas ${icon}${spin ? ' fa-spin' : ''}"></i>` +
            `<span class="ev-state-title">${E.esc(title)}</span>`;
        if (action) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'ev-btn';
            btn.innerHTML = action.html;
            btn.onclick = action.onClick;
            el.appendChild(btn);
        }
        el.hidden = false;
    }

    function hideState() {
        $('ev-state').hidden = true;
    }

    function showError(err) {
        const st = E.stateFor(err);
        let action = null;
        if (st.code === 'logs_disabled' && !S.readonly) {
            action = { html: '<i class="fas fa-power-off"></i><span>Turn on</span>', onClick: () => setService(true) };
        } else if (st.code === 'offline' || st.code === 'error') {
            action = { html: '<i class="fas fa-redo"></i><span>Retry</span>', onClick: refresh };
        } else if (st.code === 'signed_out') {
            action = { html: '<i class="fas fa-sign-in-alt"></i><span>Sign in</span>', onClick: () => { window.location.href = '/login'; } };
        }
        $('ev-table').hidden = true;
        $('ev-btn-more').hidden = true;
        showState({ icon: st.icon, title: st.title, action });
    }

    // ── Loading ──────────────────────────────────────────────────────────────

    async function reload() {
        const seq = ++S.reloadSeq;
        clearTimeout(S.retryTimer);
        S.rows = [];
        S.ids = new Set();
        S.pendingNew = 0;
        $('ev-new-pill').hidden = true;
        $('ev-table').hidden = true;
        $('ev-btn-more').hidden = true;
        showState({ icon: 'fa-spinner', title: 'Loading', spin: true });
        try {
            const data = await E.api.list(S.peerId, { ...filterParams(), limit: PAGE_SIZE });
            if (seq !== S.reloadSeq) return;
            addEntries(data.entries || []);
            if (data.last_id && data.last_id > S.topId) S.topId = data.last_id;
            S.hasMore = !!(data.page && data.page.has_more);
            S.nextBeforeId = data.page ? data.page.next_before_id : null;
            renderRows();
        } catch (err) {
            if (seq !== S.reloadSeq) return;
            showError(err);
            stopStream(err.code === 'offline' ? 'offline' : 'off');
            if (err.code === 'offline' || err.code === 'error') {
                S.retryTimer = setTimeout(refresh, RETRY_MS);
            }
        }
    }

    async function loadOlder() {
        if (!S.hasMore || !S.nextBeforeId) return;
        const btn = $('ev-btn-more');
        btn.disabled = true;
        try {
            const data = await E.api.list(S.peerId, { ...filterParams(), limit: PAGE_SIZE, before_id: S.nextBeforeId });
            addEntries(data.entries || []);
            S.hasMore = !!(data.page && data.page.has_more);
            S.nextBeforeId = data.page ? data.page.next_before_id : null;
            renderRows();
        } catch (err) {
            window.showError(err.message);
        } finally {
            btn.disabled = false;
        }
    }

    // Fill the gap after a (re)connect.
    async function catchUp() {
        if (!S.topId) return;
        try {
            const data = await E.api.list(S.peerId, { ...streamParams(), after_id: S.topId, limit: 500 });
            (data.entries || []).forEach(onLiveEntry);
        } catch (e) {
            // The stream keeps going; the next reconnect tries again.
        }
    }

    // ── Live stream ──────────────────────────────────────────────────────────

    function setLive(state) {
        const el = $('ev-live');
        el.dataset.state = state;
        $('ev-live-text').textContent = { connecting: 'Connecting', live: 'Live', paused: 'Paused', offline: 'Offline', off: 'Off' }[state] || state;
    }

    function stopStream(state) {
        if (S.es) {
            S.es.close();
            S.es = null;
        }
        if (state) setLive(state);
    }

    function startStream() {
        stopStream();
        if (document.hidden) {
            setLive('paused');
            return;
        }
        setLive('connecting');
        const es = new EventSource(E.api.streamUrl(S.peerId, streamParams()));
        S.es = es;
        es.onopen = () => {
            if (S.es !== es) return;
            S.streamFails = 0;
            setLive('live');
            catchUp();
        };
        es.addEventListener('log', (msg) => {
            if (S.es !== es) return;
            try {
                onLiveEntry(JSON.parse(msg.data));
            } catch (e) { /* ignore a bad frame */ }
        });
        es.onerror = () => {
            if (S.es !== es) return;
            if (es.readyState === EventSource.CLOSED) {
                // Refused or dropped for good (offline, log off, …). Back off; from
                // the second failure reload the list too, so its state says why.
                stopStream('offline');
                S.streamFails += 1;
                clearTimeout(S.retryTimer);
                const delay = Math.min(RETRY_MS, 5000 * 2 ** (S.streamFails - 1));
                S.retryTimer = setTimeout(S.streamFails >= 2 ? refresh : startStream, delay);
            } else {
                setLive('connecting');
            }
        };
    }

    // ── Settings ─────────────────────────────────────────────────────────────

    function openModal(id) { $(id).classList.add('active'); }
    function closeModal(id) { $(id).classList.remove('active'); }

    function overlayClose(event, which) {
        if (event.target !== event.currentTarget) return;
        if (which === 'settings') closeSettings();
        else closeClear();
    }

    async function openSettings() {
        openModal('ev-settings-modal');
        $('ev-settings-loading').hidden = false;
        $('ev-settings-error').hidden = true;
        $('ev-settings-body').hidden = true;
        try {
            S.config = await E.api.config(S.peerId);
            renderSettings();
            $('ev-settings-body').hidden = false;
        } catch (err) {
            $('ev-settings-error').textContent = E.stateFor(err).title;
            $('ev-settings-error').hidden = false;
        } finally {
            $('ev-settings-loading').hidden = true;
        }
    }

    function closeSettings() {
        closeModal('ev-settings-modal');
    }

    function pausedLabel(iso) {
        return iso ? `Paused until ${E.shortTime(iso)}` : '';
    }

    function renderSettings() {
        const cfg = S.config;
        const bounds = cfg.bounds || {};
        const alwaysOn = cfg.always_on || [];
        const dis = S.readonly ? 'disabled' : '';
        const rd = bounds.retention_days || [1, 365];
        const me = bounds.max_entries || [1000, 200000];
        const levels = bounds.min_level || E.LEVELS;

        const toggle = $('ev-service-toggle');
        toggle.checked = !!cfg.enabled;
        toggle.disabled = S.readonly;

        const names = CATEGORY_ORDER.filter((n) => cfg.categories && cfg.categories[n])
            .concat(Object.keys(cfg.categories || {}).filter((n) => !CATEGORY_ORDER.includes(n)));

        $('ev-settings-list').innerHTML = names.map((name) => {
            const c = cfg.categories[name];
            const locked = alwaysOn.includes(name);
            const pauseOpts = [`<option value="">${c.paused_until ? E.esc(pausedLabel(c.paused_until)) : 'Not paused'}</option>`]
                .concat(c.paused_until ? ['<option value="0">Resume now</option>'] : [])
                .concat(PAUSE_OPTIONS.map(([m, l]) => `<option value="${m}">Pause ${l}</option>`)).join('');
            return `
            <div class="ev-set-row" data-category="${E.esc(name)}">
                <div class="ev-set-head">
                    <span class="ev-set-name"><i class="fas ${E.CATEGORY_ICONS[name] || 'fa-circle'}"></i> ${E.esc(E.categoryLabel(name))}
                        ${locked ? '<i class="fas fa-lock ev-lock" title="Always on"></i>' : ''}</span>
                    <label class="switch" title="${locked ? 'Always on' : 'Show'}">
                        <input type="checkbox" data-field="enabled" ${c.enabled ? 'checked' : ''} ${locked || S.readonly ? 'disabled' : ''}>
                        <span class="slider"></span>
                    </label>
                </div>
                <div class="ev-set-grid">
                    <label class="ev-field"><span>Keep (days)</span>
                        <input type="number" class="ev-input" data-field="retention_days" min="${rd[0]}" max="${rd[1]}" step="1" value="${c.retention_days}" ${dis}>
                    </label>
                    <label class="ev-field"><span>Max events</span>
                        <input type="number" class="ev-input" data-field="max_entries" min="${me[0]}" max="${me[1]}" step="1000" value="${c.max_entries}" ${dis}>
                    </label>
                    <label class="ev-field"><span>Min level</span>
                        <select class="ev-select" data-field="min_level" ${dis}>
                            ${levels.map((l) => `<option value="${l}" ${l === c.min_level ? 'selected' : ''}>${E.levelLabel(l)}</option>`).join('')}
                        </select>
                    </label>
                    ${locked ? '' : `<label class="ev-field"><span>Pause</span>
                        <select class="ev-select" data-field="pause_minutes" ${dis || (c.enabled ? '' : 'disabled')}>${pauseOpts}</select>
                    </label>`}
                </div>
                <div class="inline-error-msg ev-set-error" hidden></div>
            </div>`;
        }).join('');

        $('ev-settings-list').querySelectorAll('input, select').forEach((el) => {
            el.addEventListener('input', onSettingsChange);
            el.addEventListener('change', onSettingsChange);
        });
        $('ev-settings-warn').hidden = true;
        const save = $('ev-settings-save');
        if (save) save.disabled = true;
    }

    // Changed fields only, per category. Returns {changes, errors, shrinks}.
    function collectSettings() {
        const cfg = S.config;
        const bounds = cfg.bounds || {};
        const changes = {};
        let errors = 0;
        let shrinks = false;
        document.querySelectorAll('#ev-settings-list .ev-set-row').forEach((row) => {
            const name = row.dataset.category;
            const cur = cfg.categories[name];
            const out = {};
            let error = '';
            row.querySelectorAll('[data-field]').forEach((el) => {
                const field = el.dataset.field;
                if (el.disabled && field !== 'pause_minutes') return;
                if (field === 'enabled') {
                    if (el.checked !== !!cur.enabled) out.enabled = el.checked;
                } else if (field === 'retention_days' || field === 'max_entries') {
                    const v = Number(el.value);
                    const [lo, hi] = bounds[field] || [1, Infinity];
                    if (!Number.isInteger(v) || v < lo || v > hi) {
                        error = `${field === 'retention_days' ? 'Days' : 'Max events'}: ${lo}–${hi}`;
                        el.classList.add('ev-input-error');
                        return;
                    }
                    el.classList.remove('ev-input-error');
                    if (v !== cur[field]) {
                        out[field] = v;
                        if (v < cur[field]) shrinks = true;
                    }
                } else if (field === 'min_level') {
                    if (el.value !== cur.min_level) out.min_level = el.value;
                } else if (field === 'pause_minutes') {
                    if (!el.disabled && el.value !== '') out.pause_minutes = Number(el.value);
                }
            });
            const errEl = row.querySelector('.ev-set-error');
            errEl.textContent = error;
            errEl.hidden = !error;
            if (error) errors += 1;
            if (Object.keys(out).length) changes[name] = out;
        });
        return { changes, errors, shrinks };
    }

    function onSettingsChange(ev) {
        // Pause only applies while the category is shown.
        if (ev && ev.target && ev.target.dataset.field === 'enabled') {
            const pause = ev.target.closest('.ev-set-row').querySelector('[data-field="pause_minutes"]');
            if (pause) pause.disabled = !ev.target.checked || S.readonly;
        }
        const { changes, errors, shrinks } = collectSettings();
        $('ev-settings-warn').hidden = !shrinks;
        const save = $('ev-settings-save');
        if (save) save.disabled = errors > 0 || Object.keys(changes).length === 0;
    }

    async function saveSettings() {
        const { changes, errors } = collectSettings();
        if (errors || !Object.keys(changes).length) return;
        const save = $('ev-settings-save');
        save.disabled = true;
        try {
            S.config = await E.api.saveConfig(S.peerId, changes);
            window.showSuccess('Saved');
            closeSettings();
            loadCategories();
        } catch (err) {
            window.showError(err.message);
            save.disabled = false;
        }
    }

    async function toggleService(input) {
        const on = input.checked;
        if (!on) {
            const ok = await window.nkConfirm('Hide all events on this device?', 'Turn off system logs?', 'Turn off');
            if (!ok) {
                input.checked = true;
                return;
            }
        }
        input.disabled = true;
        const done = await setService(on);
        input.disabled = S.readonly;
        if (!done) input.checked = !on;
        else if (S.config) S.config.enabled = on;
    }

    async function setService(on) {
        try {
            await E.api.setService(S.peerId, on ? 'enabled' : 'disabled');
            window.showSuccess(on ? 'System logs on' : 'System logs off');
            refresh();
            loadCategories();
            return true;
        } catch (err) {
            window.showError(err.message);
            return false;
        }
    }

    // ── Clear ────────────────────────────────────────────────────────────────

    function openClear() {
        const alwaysOn = (S.config && S.config.always_on) || ['audit'];
        const names = CATEGORY_ORDER.filter((n) => !alwaysOn.includes(n));
        $('ev-clear-list').innerHTML = names.map((n) => {
            const count = typeof S.counts[n] === 'number' ? `<span class="ev-chip-count">${S.counts[n]}</span>` : '';
            const checked = !S.filters.category || S.filters.category === n ? 'checked' : '';
            return `<label class="ev-clear-item"><input type="checkbox" value="${n}" ${checked}>` +
                `<i class="fas ${E.CATEGORY_ICONS[n]}"></i><span>${E.esc(E.categoryLabel(n))}</span>${count}</label>`;
        }).join('');
        $('ev-clear-list').querySelectorAll('input').forEach((el) => el.addEventListener('change', updateClearButton));
        updateClearButton();
        openModal('ev-clear-modal');
    }

    function closeClear() {
        closeModal('ev-clear-modal');
    }

    function selectedClear() {
        return Array.from($('ev-clear-list').querySelectorAll('input:checked')).map((el) => el.value);
    }

    function updateClearButton() {
        $('ev-clear-confirm').disabled = selectedClear().length === 0;
    }

    async function confirmClear() {
        const cats = selectedClear();
        if (!cats.length) return;
        const btn = $('ev-clear-confirm');
        btn.disabled = true;
        try {
            await E.api.clear(S.peerId, cats);
            window.showSuccess('Cleared');
            closeClear();
            reload();
            loadCategories();
        } catch (err) {
            window.showError(err.message);
        } finally {
            btn.disabled = false;
        }
    }

    // ── Init ─────────────────────────────────────────────────────────────────

    function init() {
        const page = $('events-page');
        if (!page) return;
        S.peerId = page.dataset.peerId;
        S.readonly = page.dataset.readonly === 'true';
        renderChips();
        loadCategories();
        refresh();

        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                if (S.es) stopStream('paused');
            } else if (!S.es && $('ev-live').dataset.state === 'paused') {
                startStream();
            }
        });
        window.addEventListener('scroll', () => {
            if (S.pendingNew && !isScrolledAway()) {
                S.pendingNew = 0;
                $('ev-new-pill').hidden = true;
            }
        }, { passive: true });
        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeSettings();
                if ($('ev-clear-modal')) closeClear();
            }
        });
    }

    window.EventsPage = {
        setCategory, applyFilters, onSearchInput, loadOlder, showNew,
        openSettings, closeSettings, saveSettings, toggleService,
        openClear, closeClear, confirmClear, overlayClose,
    };

    document.addEventListener('DOMContentLoaded', init);
})();
