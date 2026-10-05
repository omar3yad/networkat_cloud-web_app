/**
 * System logs page (client/templates/system_logs.html).
 *
 * List + filters + "Load older" over GET /logs/system, live updates over the SSE
 * stream (EventSource; it resends Last-Event-ID itself after the 30-minute
 * close). After every (re)connect the gap is filled from GET /logs/system?after_id=,
 * and rows are de-duplicated by id. The stream is closed while the tab is
 * hidden.
 */
(function () {
    const E = window.NkSystemLogs;
    const CATEGORY_ORDER = Object.keys(E.CATEGORY_LABELS);
    const PAGE_SIZE = 50;
    const RETRY_MS = 30000;
    const PAUSE_OPTIONS = [[60, '1 hour'], [480, '8 hours'], [1440, '24 hours'], [10080, '7 days']];

    const S = {
        peerId: '',
        readonly: false,
        detailsUrl: '',
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
        document.querySelectorAll('#sl-chips .sl-chip').forEach((chip) => {
            chip.classList.toggle('active', chip.dataset.category === name);
        });
        refresh();
    }

    function applyFilters() {
        S.filters.level = $('sl-level').value;
        S.filters.range = $('sl-range').value;
        refresh();
    }

    function onSearchInput() {
        clearTimeout(S.searchTimer);
        S.searchTimer = setTimeout(() => {
            const q = $('sl-q').value;
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
        const wrap = $('sl-chips');
        CATEGORY_ORDER.forEach((name) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'sl-chip';
            btn.dataset.category = name;
            btn.innerHTML = `<i class="fas ${E.CATEGORY_ICONS[name]}"></i><span>${E.esc(E.categoryLabel(name))}</span>` +
                `<span class="sl-chip-count" id="sl-count-${name}"></span>`;
            btn.onclick = () => setCategory(name);
            wrap.appendChild(btn);
        });
    }

    function renderCounts() {
        let total = 0;
        CATEGORY_ORDER.forEach((name) => {
            const n = S.counts[name];
            const el = $(`sl-count-${name}`);
            if (el) el.textContent = typeof n === 'number' ? n : '';
            if (typeof n === 'number') total += n;
        });
        const all = $('sl-count-all');
        if (all) all.textContent = S.categories.length ? total : '';
    }

    async function loadCategories() {
        try {
            const data = await E.api.categories(S.peerId);
            S.categories = data.categories || [];
            S.counts = {};
            S.categories.forEach((c) => {
                S.counts[c.name] = c.count || 0;
                const chip = document.querySelector(`#sl-chips .sl-chip[data-category="${c.name}"]`);
                if (chip && c.description) chip.title = c.description;
            });
            renderCounts();
        } catch (e) {
            // Counts are optional; the list shows the error state.
        }
    }

    // ── Rows ─────────────────────────────────────────────────────────────────

    function rowHtml(e) {
        const isGated = e.code === 'paid_only' || e.code === 'premium_only';
        if (isGated) {
            return `<tr class="sl-row sl-row-gated" data-id="${e.id}">` +
                `<td class="sl-col-time" title="${E.esc(E.fullTime(e.time))}">${E.esc(E.shortTime(e.time))}</td>` +
                `<td class="sl-col-level"><span class="sl-premium-badge"><i class="fas fa-lock"></i> Paid plan</span></td>` +
                `<td class="sl-col-cat"><i class="fas fa-lock"></i> System</td>` +
                `<td class="sl-msg"><i class="fas fa-lock" style="margin-right:0.35rem; color:#b45309;"></i> Available on paid plans</td>` +
                `<td class="sl-col-by">&mdash;</td>` +
                `</tr>`;
        }
        const repeat = (e.repeat_count || 1) > 1;
        const icon = E.CATEGORY_ICONS[e.category] || 'fa-circle';
        return `<tr class="sl-row sl-row-${E.esc(e.level)}${repeat ? ' sl-row-repeat' : ''}" data-id="${e.id}">` +
            `<td class="sl-col-time" title="${E.esc(E.fullTime(e.time))}">${E.esc(E.shortTime(e.time))}</td>` +
            `<td class="sl-col-level">${E.levelBadge(e.level)}</td>` +
            `<td class="sl-col-cat"><i class="fas ${icon}"></i> ${E.esc(E.categoryLabel(e.category))}</td>` +
            `<td class="sl-msg">${E.esc(e.message || '')}` +
            (repeat ? ` <span class="sl-repeat">×${Number(e.repeat_count)}</span>` : '') + `</td>` +
            `<td class="sl-col-by">${E.esc(E.actorLabel(e.actor))}</td>` +
            `</tr>`;
    }

    function renderRows() {
        const body = $('sl-rows');
        body.innerHTML = S.rows.map(rowHtml).join('');
        const bannerArea = $('sl-banner-area');
        const existingBanner = $('sl-premium-banner');
        if (S.rows.length) {
            $('sl-table').hidden = false;
            hideState();
            if (S.isGated) {
                if (!existingBanner) {
                    const banner = document.createElement('div');
                    banner.id = 'sl-premium-banner';
                    banner.className = 'sl-premium-banner';
                    banner.innerHTML = `<div class="sl-premium-banner-left">` +
                        `<i class="fas fa-lock" style="color:#2563eb;"></i>` +
                        `<span>To view all logs, upgrade to a paid plan</span>` +
                        `</div>` +
                        `<a href="/contact" class="sl-premium-btn"><i class="fas fa-arrow-up-right-from-square"></i> Upgrade plan</a>`;
                    if (bannerArea) {
                        bannerArea.appendChild(banner);
                    } else {
                        $('sl-table-wrap').prepend(banner);
                    }
                }
            } else if (existingBanner) {
                existingBanner.remove();
            }
        } else {
            $('sl-table').hidden = true;
            if (existingBanner) existingBanner.remove();
            showState({ icon: 'fa-inbox', title: 'No entries' });
        }
        $('sl-btn-more').hidden = S.isGated ? true : !S.hasMore;
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

    function enforceGating() {
        if (!S.isGated) return;
        const limit = S.trialLimit || 5;
        let unmaskedCount = 0;
        S.rows.forEach((r) => {
            if (unmaskedCount < limit) {
                if (r.code !== 'paid_only' && r.code !== 'premium_only') {
                    unmaskedCount++;
                }
            } else {
                r.code = 'paid_only';
                r.message = 'Available on paid plans';
                r.data = null;
            }
        });
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

        if (S.isGated) {
            enforceGating();
            renderRows();
            const firstRow = $('sl-rows')?.firstElementChild;
            if (firstRow) firstRow.classList.add('sl-row-new');
        } else {
            const body = $('sl-rows');
            const idx = S.rows.indexOf(e);
            const tpl = document.createElement('tbody');
            tpl.innerHTML = rowHtml(e);
            const tr = tpl.firstChild;
            tr.classList.add('sl-row-new');
            body.insertBefore(tr, body.children[idx] || null);
            $('sl-table').hidden = false;
            hideState();
        }

        if (isScrolledAway()) {
            S.pendingNew += 1;
            $('sl-new-text').textContent = S.pendingNew === 1 ? '1 new entry' : `${S.pendingNew} new entries`;
            $('sl-new-pill').hidden = false;
        }
    }

    function isScrolledAway() {
        const card = $('sl-table-wrap');
        return card && card.getBoundingClientRect().top < 0;
    }

    function showNew() {
        S.pendingNew = 0;
        $('sl-new-pill').hidden = true;
        $('sl-chips').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // ── States ───────────────────────────────────────────────────────────────

    function showState({ icon, title, text = '', spin = false, action = null, link = null }) {
        const el = $('sl-state');
        el.innerHTML = `<i class="fas ${icon}${spin ? ' fa-spin' : ''}"></i>` +
            `<span class="sl-state-title">${E.esc(title)}</span>` +
            (text ? `<span class="sl-state-text">${E.esc(text)}</span>` : '');
        if (link) el.appendChild(link);
        if (action) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'sl-btn';
            btn.innerHTML = action.html;
            btn.onclick = action.onClick;
            el.appendChild(btn);
        }
        el.hidden = false;
    }

    function hideState() {
        $('sl-state').hidden = true;
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
        $('sl-table').hidden = true;
        $('sl-btn-more').hidden = true;
        const link = st.code === 'unsupported' ? E.updateLink(S.detailsUrl) : null;
        showState({ icon: st.icon, title: st.title, text: st.text, action, link });
    }

    // ── Loading ──────────────────────────────────────────────────────────────

    async function reload() {
        const seq = ++S.reloadSeq;
        clearTimeout(S.retryTimer);
        S.rows = [];
        S.ids = new Set();
        S.pendingNew = 0;
        $('sl-new-pill').hidden = true;
        $('sl-table').hidden = true;
        $('sl-btn-more').hidden = true;
        showState({ icon: 'fa-spinner', title: 'Loading', spin: true });
        try {
            const data = await E.api.list(S.peerId, { ...filterParams(), limit: PAGE_SIZE });
            if (seq !== S.reloadSeq) return;
            S.isGated = !!data.is_gated;
            S.trialLimit = data.trial_log_limit || 5;
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
        const btn = $('sl-btn-more');
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
        const el = $('sl-live');
        el.dataset.state = state;
        $('sl-live-text').textContent = { connecting: 'Connecting', live: 'Live', paused: 'Paused', offline: 'Offline', off: 'Off' }[state] || state;
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
        else if (which === 'pause') closePause();
        else closeClear();
    }

    async function openSettings() {
        openModal('sl-settings-modal');
        $('sl-settings-loading').hidden = false;
        $('sl-settings-error').hidden = true;
        $('sl-settings-body').hidden = true;
        try {
            S.config = await E.api.config(S.peerId);
            renderSettings();
            $('sl-settings-body').hidden = false;
        } catch (err) {
            $('sl-settings-error').textContent = E.stateFor(err).title;
            $('sl-settings-error').hidden = false;
        } finally {
            $('sl-settings-loading').hidden = true;
        }
    }

    function closeSettings() {
        closeMenu();
        closeModal('sl-settings-modal');
    }

    function pausedLabel(iso) {
        if (!iso) return '';
        const t = E.shortTime(iso);
        return `Paused until ${t.length >= 16 ? t.slice(0, 16) : t}`;
    }

    // ── Settings rows ────────────────────────────────────────────────────────

    const LEVEL_LIST = E.LEVELS || ['info', 'notice', 'warning', 'error', 'critical'];

    function levelPill(level) {
        return `<span class="sl-level sl-level-${E.esc(level)}">${E.esc(E.levelLabel(level))}</span>`;
    }

    function summaryText(c) {
        return `${c.retention_days} days · ${Number(c.max_entries).toLocaleString()} max · ${E.esc(E.levelLabel(c.min_level))}+`;
    }

    function levelField(c, levels, locked, dis) {
        const lock = locked ? 'disabled title="Always on"' : (dis ? 'disabled' : '');
        return `<button type="button" class="sl-lv-btn" data-field="min_level" data-value="${E.esc(c.min_level)}" ${lock}>
            ${levelPill(c.min_level)}<i class="fas ${locked ? 'fa-lock' : 'fa-chevron-down'}"></i></button>`;
    }

    function renderSettings() {
        const cfg = S.config;
        const bounds = cfg.bounds || {};
        const alwaysOn = cfg.always_on || [];
        const dis = S.readonly ? 'disabled' : '';
        const rd = bounds.retention_days || [1, 365];
        const me = bounds.max_entries || [1000, 200000];
        const levels = bounds.min_level || LEVEL_LIST;
        S.levels = levels;

        const toggle = $('sl-service-toggle');
        toggle.checked = !!cfg.enabled;
        toggle.disabled = S.readonly;
        setLowerOff(!cfg.enabled);

        const known = CATEGORY_ORDER.filter((n) => cfg.categories && cfg.categories[n]);
        const unknown = Object.keys(cfg.categories || {}).filter((n) => !CATEGORY_ORDER.includes(n));
        const names = known.filter((n) => n !== 'audit').concat(unknown, known.filter((n) => n === 'audit'));

        $('sl-settings-list').innerHTML = names.map((name) => {
            const c = cfg.categories[name];
            const locked = alwaysOn.includes(name);
            const paused = !!c.paused_until;
            return `
            <div class="sl-set-row ${paused ? 'is-paused' : ''}" data-category="${E.esc(name)}" data-pause="">
                <div class="sl-set-top">
                    <div class="sl-set-main" data-act="expand">
                        <span class="sl-set-name"><i class="fas ${E.CATEGORY_ICONS[name] || 'fa-circle'}"></i> ${E.esc(E.categoryLabel(name))}
                            <i class="fas fa-chevron-down sl-chev"></i></span>
                        <div class="sl-sum"><span class="sl-vals">${summaryText(c)}</span><span class="sl-ps">${paused ? '<span class="sl-sep"> · </span><button type="button" class="sl-edit-pause" data-act="edit-pause"></button>' : ''}</span></div>
                    </div>
                    ${locked ? '<span></span>' : `<button type="button" class="sl-pause" data-act="pause" title="Pause" ${dis || (c.enabled ? '' : 'disabled')}><i class="fas fa-pause"></i></button>`}
                    <label class="switch" title="${locked ? 'Always on' : 'Show'}">
                        <input type="checkbox" data-field="enabled" ${c.enabled ? 'checked' : ''} ${locked || S.readonly ? 'disabled' : ''}>
                        <span class="slider"></span>
                        <i class="fas fa-pause sl-sw-pause"></i>
                        ${locked ? '<i class="fas fa-lock sl-sw-lock"></i>' : ''}
                    </label>
                </div>
                <div class="sl-set-edit">
                    <label class="sl-fld">Keep (days)
                        <input type="number" class="sl-input" data-field="retention_days" min="${rd[0]}" max="${rd[1]}" step="1" value="${c.retention_days}" ${dis}>
                    </label>
                    <label class="sl-fld">Max entries
                        <input type="number" class="sl-input" data-field="max_entries" min="${me[0]}" max="${me[1]}" step="1000" value="${c.max_entries}" ${dis}>
                    </label>
                    <div class="sl-fld">Min level ${levelField(c, levels, locked, dis)}</div>
                </div>
                <div class="inline-error-msg sl-set-error" hidden></div>
            </div>`;
        }).join('');

        $('sl-settings-list').querySelectorAll('input').forEach((el) => {
            el.addEventListener('input', onSettingsChange);
            el.addEventListener('change', onSettingsChange);
        });
        $('sl-settings-list').querySelectorAll('.sl-set-row').forEach(syncRow);
        $('sl-settings-list').onclick = onListClick;
        closeMenu();
        syncExpandAll();
        $('sl-settings-warn').hidden = true;
        const save = $('sl-settings-save');
        if (save) save.disabled = true;
    }

    // Paused, with any unsaved change applied over the saved value.
    function rowPaused(row) {
        const p = row.dataset.pause;
        if (p === '0') return false;
        if (p) return true;
        return !!(S.config.categories[row.dataset.category] || {}).paused_until;
    }

    function rowPausedIso(row) {
        if (row.dataset.pause && row.dataset.pause !== '0') return new Date(Number(row.dataset.pauseTs)).toISOString();
        return (S.config.categories[row.dataset.category] || {}).paused_until || '';
    }

    function rowEnabled(row) {
        return row.querySelector('[data-field="enabled"]').checked;
    }

    function syncRow(row) {
        const paused = rowPaused(row);
        row.classList.toggle('is-paused', paused);
        const btn = row.querySelector('.sl-pause');
        if (btn) btn.disabled = S.readonly || S.serviceOff || !rowEnabled(row);
        const ps = row.querySelector('.sl-ps');
        if (paused) {
            if (!ps.firstChild) ps.innerHTML = '<span class="sl-sep"> · </span><button type="button" class="sl-edit-pause" data-act="edit-pause"></button>';
            ps.querySelector('.sl-edit-pause').textContent = pausedLabel(rowPausedIso(row));
        } else {
            ps.innerHTML = '';
        }
        const c = S.config.categories[row.dataset.category];
        const days = row.querySelector('[data-field="retention_days"]').value;
        const max = row.querySelector('[data-field="max_entries"]').value;
        const lv = row.querySelector('[data-field="min_level"]').dataset.value;
        row.querySelector('.sl-vals').innerHTML = summaryText({
            retention_days: days || c.retention_days,
            max_entries: max || c.max_entries,
            min_level: lv,
        });
    }

    // ── Popover menu (pause + min level) ─────────────────────────────────────

    function closeMenu() {
        const m = $('sl-menu');
        if (m) m.remove();
        document.querySelectorAll('.sl-lv-btn.open').forEach((b) => b.classList.remove('open'));
    }

    function openMenu(anchor, html, onPick, align) {
        closeMenu();
        const menu = document.createElement('div');
        menu.id = 'sl-menu';
        menu.className = 'sl-menu';
        menu.innerHTML = html;
        menu.addEventListener('click', (ev) => {
            const opt = ev.target.closest('[data-v]');
            if (!opt) return;
            ev.stopPropagation();
            closeMenu();
            onPick(opt.dataset.v);
        });
        $('sl-settings-modal').appendChild(menu);
        const r = anchor.getBoundingClientRect();
        if (align === 'fit') {
            menu.style.minWidth = `${r.width}px`;
            menu.style.left = `${r.left}px`;
        } else {
            menu.style.right = `${Math.max(8, window.innerWidth - r.right)}px`;
        }
        const h = menu.offsetHeight;
        const below = r.bottom + 6;
        menu.style.top = `${below + h > window.innerHeight - 8 ? Math.max(8, r.top - h - 6) : below}px`;
    }

    function openPauseMenu(btn, row) {
        const items = PAUSE_OPTIONS.filter(([m]) => m <= pauseBounds()[1]).map(([m, l]) => `<div data-v="${m}">${l}</div>`).join('') +
            '<div data-v="custom" class="sl-menu-sep">Custom…</div>';
        openMenu(btn, items, (v) => {
            if (v === 'custom') { openPause(row, false); return; }
            setRowPause(row, Number(v));
        });
    }

    function openLevelMenu(btn, row) {
        const cur = btn.dataset.value;
        const items = (S.levels || LEVEL_LIST).map((l) =>
            `<div data-v="${E.esc(l)}" class="${l === cur ? 'sel' : ''}">${levelPill(l)}</div>`).join('');
        btn.classList.add('open');
        openMenu(btn, items, (v) => {
            btn.dataset.value = v;
            btn.querySelector('.sl-level').outerHTML = levelPill(v);
            syncRow(row);
            onSettingsChange();
        }, 'fit');
    }

    function setRowPause(row, minutes) {
        row.dataset.pause = String(minutes);
        row.dataset.pauseTs = String(Date.now() + minutes * 60000);
        syncRow(row);
        onSettingsChange();
    }

    function onListClick(ev) {
        const t = ev.target;
        const act = t.closest('[data-act]');
        const lv = t.closest('.sl-lv-btn');
        const row = t.closest('.sl-set-row');
        if (!row) return;
        if (lv && !lv.disabled) {
            ev.stopPropagation();
            if (lv.classList.contains('open')) closeMenu(); else openLevelMenu(lv, row);
            return;
        }
        if (!act) return;
        const kind = act.dataset.act;
        if (kind === 'pause') {
            ev.stopPropagation();
            if (act.disabled) return;
            openPauseMenu(act, row);
        } else if (kind === 'edit-pause') {
            ev.stopPropagation();
            openPause(row, true);
        } else if (kind === 'expand') {
            row.classList.toggle('open');
            syncExpandAll();
        }
    }

    // ── Expand all + sticky bar ──────────────────────────────────────────────

    function syncExpandAll() {
        const rows = [...document.querySelectorAll('#sl-settings-list .sl-set-row')];
        const all = rows.length > 0 && rows.every((r) => r.classList.contains('open'));
        const btn = $('sl-expand-all');
        btn.classList.toggle('open', all);
        btn.querySelector('span').textContent = all ? 'Collapse all' : 'Expand all';
    }

    function toggleExpandAll() {
        const rows = [...document.querySelectorAll('#sl-settings-list .sl-set-row')];
        const open = !rows.every((r) => r.classList.contains('open'));
        rows.forEach((r) => r.classList.toggle('open', open));
        syncExpandAll();
    }

    function updateStuck() {
        const body = document.querySelector('#sl-settings-modal .modal-body');
        const bar = $('sl-bar');
        if (!body || !bar) return;
        bar.classList.toggle('stuck', body.scrollTop > 0 &&
            bar.getBoundingClientRect().top <= body.getBoundingClientRect().top + 0.5);
    }

    // ── Main switch off: lower part is shaded and locked ─────────────────────

    function setLowerOff(off) {
        S.serviceOff = off;
        $('sl-settings-modal').classList.toggle('sl-off', off);
        $('sl-lower-in').inert = off;
        closeMenu();
        document.querySelectorAll('#sl-settings-list .sl-set-row').forEach(syncRow);
    }

    // ── Custom pause modal ───────────────────────────────────────────────────

    const PZ = { row: null, mode: 'for', edit: false, clock: null, lastMin: null };

    // [min, max] minutes from the device's bounds; 0 would mean "resume", so min is 1.
    function pauseBounds() {
        const b = (S.config && S.config.bounds && S.config.bounds.pause_minutes) || [1, 10080];
        return [Math.max(1, b[0]), b[1]];
    }

    function fmtSpan(m) {
        if (m % 1440 === 0) return `${m / 1440} day${m === 1440 ? '' : 's'}`;
        if (m % 60 === 0) return `${m / 60} h`;
        return `${m} min`;
    }

    function fmtDur(m) {
        const d = Math.floor(m / 1440);
        const h = Math.floor((m % 1440) / 60);
        const min = m % 60;
        return [d && `${d} d`, h && `${h} h`, (min || (!d && !h)) && `${min} min`].filter(Boolean).join(' ');
    }

    function fmtDT(d) {
        return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
    }

    function pad2(n) { return String(n).padStart(2, '0'); }

    // "Until" is a date plus 24-hour hour/minute fields, so no AM/PM.
    function setUntil(d) {
        $('sl-pz-date').value = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
        syncDateText();
        $('sl-pz-hh').value = pad2(d.getHours());
        $('sl-pz-mm').value = pad2(d.getMinutes());
    }

    function syncDateText() {
        $('sl-pz-date-txt').value = $('sl-pz-date').value;
    }

    // Live clock in the corner while the modal is open.
    function tickClock() {
        const d = new Date();
        $('sl-pz-clock').textContent = `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
        // The earliest allowed time moves with the clock, so re-check once a minute.
        if (PZ.lastMin !== d.getMinutes()) {
            PZ.lastMin = d.getMinutes();
            if ($('sl-pause-modal').classList.contains('active')) pauseUpdate();
        }
    }

    function startClock() {
        stopClock();
        tickClock();
        PZ.clock = setInterval(tickClock, 1000);
    }

    function stopClock() {
        clearInterval(PZ.clock);
        PZ.clock = null;
        PZ.lastMin = null;
    }

    function untilTime() {
        const date = $('sl-pz-date').value;
        const hh = $('sl-pz-hh').value.trim();
        const mm = $('sl-pz-mm').value.trim();
        const h = Number(hh);
        const m = Number(mm);
        if (!date || hh === '' || mm === '' || !Number.isInteger(h) || !Number.isInteger(m) ||
            h < 0 || h > 23 || m < 0 || m > 59) return NaN;
        return new Date(`${date}T${pad2(h)}:${pad2(m)}`).getTime();
    }

    function pauseMinutes() {
        if (PZ.mode === 'for') {
            const v = ['sl-pz-d', 'sl-pz-h', 'sl-pz-m'].map((id) => Number($(id).value));
            if (!v.every((n) => Number.isInteger(n) && n >= 0)) return NaN;
            return v[0] * 1440 + v[1] * 60 + v[2];
        }
        const t = untilTime();
        return isNaN(t) ? NaN : Math.ceil((t - Date.now()) / 60000);
    }

    // Writes the other tab's fields from a valid end time, so both tabs agree.
    function fillOtherTab(mins) {
        if (PZ.mode === 'for') {
            setUntil(new Date(Date.now() + mins * 60000));
        } else {
            $('sl-pz-d').value = Math.floor(mins / 1440);
            $('sl-pz-h').value = Math.floor((mins % 1440) / 60);
            $('sl-pz-m').value = mins % 60;
        }
    }

    function pauseUpdate() {
        applyPauseLimits();
        const [lo, hi] = pauseBounds();
        const mins = pauseMinutes();
        const bad = !(mins >= lo && mins <= hi);
        $('sl-pz-ok').disabled = bad;
        const prev = $('sl-pz-prev');
        if (bad) {
            prev.classList.add('err');
            const { minT, maxT } = untilLimits();
            prev.textContent = PZ.mode === 'until'
                ? `Pick from ${fmtDT(minT)} to ${fmtDT(maxT)}`
                : `${fmtSpan(lo)} – ${fmtSpan(hi)}`;
        } else {
            prev.classList.remove('err');
            fillOtherTab(mins);
            // Each tab shows the other tab's value: For shows the end time, Until shows the duration.
            prev.textContent = PZ.mode === 'for'
                ? `Until ${fmtDT(new Date(Date.now() + mins * 60000))}`
                : `For ${fmtDur(mins)}`;
        }
    }

    // Earliest and latest end time, from the device's bounds (earliest rounded up to the minute).
    function untilLimits() {
        const [lo, hi] = pauseBounds();
        const minT = new Date(Math.ceil((Date.now() + lo * 60000) / 60000) * 60000);
        const maxT = new Date(Math.floor((Date.now() + hi * 60000) / 60000) * 60000);
        return { minT, maxT };
    }

    // The pickers only offer values inside the range; hints and chips follow it.
    function applyPauseLimits() {
        const [lo, hi] = pauseBounds();
        const { minT, maxT } = untilLimits();
        const day = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
        const date = $('sl-pz-date').value;
        const hh = $('sl-pz-hh');
        const mm = $('sl-pz-mm');
        $('sl-pz-date').min = day(minT);
        $('sl-pz-date').max = day(maxT);
        hh.min = date === day(minT) ? minT.getHours() : 0;
        hh.max = date === day(maxT) ? maxT.getHours() : 23;
        const h = Number(hh.value);
        mm.min = date === day(minT) && h === minT.getHours() ? minT.getMinutes() : 0;
        mm.max = date === day(maxT) && h === maxT.getHours() ? maxT.getMinutes() : 59;
        $('sl-pz-range-for').textContent = `${fmtSpan(lo)} – ${fmtSpan(hi)}`;
        document.querySelectorAll('#sl-pause-modal .sl-pz-chips button').forEach((b) => {
            b.disabled = Number(b.dataset.d) * 1440 + Number(b.dataset.h) * 60 + Number(b.dataset.m) > hi;
        });
    }

    // On commit (blur, Enter, spinner), pull a value that is out of range back to the nearest allowed one.
    function clampPause() {
        const [lo, hi] = pauseBounds();
        if (PZ.mode === 'for') {
            const v = ['sl-pz-d', 'sl-pz-h', 'sl-pz-m'].map((id) => Number($(id).value));
            if (!v.every((n) => Number.isInteger(n) && n >= 0)) return;
            const mins = v[0] * 1440 + v[1] * 60 + v[2];
            const fix = mins < lo ? lo : mins > hi ? hi : mins;
            if (fix !== mins) {
                $('sl-pz-d').value = Math.floor(fix / 1440);
                $('sl-pz-h').value = Math.floor((fix % 1440) / 60);
                $('sl-pz-m').value = fix % 60;
            }
        } else {
            const t = untilTime();
            if (isNaN(t)) return;
            const { minT, maxT } = untilLimits();
            if (t < minT.getTime()) setUntil(minT);
            else if (t > maxT.getTime()) setUntil(maxT);
        }
        pauseUpdate();
    }

    // Switching tabs carries the current end time across, so both show the same "Until".
    function pauseMode(mode, sync = true) {
        if (sync && mode !== PZ.mode) {
            const mins = pauseMinutes();
            const [lo, hi] = pauseBounds();
            if (mins >= lo && mins <= hi) fillOtherTab(mins);
        }
        PZ.mode = mode;
        document.querySelectorAll('#sl-pause-modal .sl-seg button').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
        $('sl-pause-for').classList.toggle('off', mode !== 'for');
        $('sl-pause-until').classList.toggle('off', mode !== 'until');
        if (mode === 'until' && !$('sl-pz-date').value) setUntil(new Date(Date.now() + 2 * 3600e3));
        applyPauseLimits();
        pauseUpdate();
    }

    function openPause(row, edit) {
        PZ.row = row;
        PZ.edit = edit;
        const cat = row.dataset.category;
        $('sl-pause-cat').innerHTML = `<i class="fas ${E.CATEGORY_ICONS[cat] || 'fa-circle'}"></i> ${E.esc(E.categoryLabel(cat))}`;
        $('sl-pz-ok').querySelector('span').textContent = edit ? 'Update' : 'Pause';
        openModal('sl-pause-modal');
        startClock();
        if (edit) {
            const iso = rowPausedIso(row);
            if (iso) setUntil(new Date(iso));
            pauseMode('until', false);
            $('sl-pz-date').focus();
        } else {
            pauseMode('for', false);
            $('sl-pz-h').focus();
            $('sl-pz-h').select();
        }
    }

    function closePause() {
        stopClock();
        closeModal('sl-pause-modal');
    }

    function confirmPause() {
        const mins = pauseMinutes();
        const [lo, hi] = pauseBounds();
        if (!(mins >= lo && mins <= hi) || !PZ.row) return;
        setRowPause(PZ.row, mins);
        closePause();
    }

    function bindPauseModal() {
        ['sl-pz-d', 'sl-pz-h', 'sl-pz-m', 'sl-pz-date', 'sl-pz-hh', 'sl-pz-mm'].forEach((id) => $(id).addEventListener('input', pauseUpdate));
        const dateIn = $('sl-pz-date');
        dateIn.addEventListener('change', syncDateText);
        dateIn.addEventListener('input', syncDateText);
        dateIn.addEventListener('click', () => {
            if (dateIn.showPicker) { try { dateIn.showPicker(); } catch (e) { /* needs a user gesture */ } }
        });
        ['sl-pz-d', 'sl-pz-h', 'sl-pz-m', 'sl-pz-date', 'sl-pz-hh', 'sl-pz-mm'].forEach((id) => $(id).addEventListener('change', clampPause));
        document.querySelectorAll('#sl-pause-modal .sl-pz-chips button').forEach((b) => {
            b.addEventListener('click', () => {
                $('sl-pz-d').value = b.dataset.d;
                $('sl-pz-h').value = b.dataset.h;
                $('sl-pz-m').value = b.dataset.m;
                pauseUpdate();
            });
        });
        document.addEventListener('keydown', (ev) => {
            if (ev.key === 'Escape') closeMenu();
            if (ev.key === 'Enter' && $('sl-pause-modal').classList.contains('active') && !$('sl-pz-ok').disabled) confirmPause();
        });
        document.addEventListener('click', (ev) => {
            if (!ev.target.closest('#sl-menu') && !ev.target.closest('.sl-lv-btn') && !ev.target.closest('.sl-pause')) closeMenu();
        });
        const body = document.querySelector('#sl-settings-modal .modal-body');
        if (body) body.addEventListener('scroll', () => { updateStuck(); closeMenu(); }, { passive: true });
    }

    // Changed fields only, per category. Returns {changes, errors, shrinks}.
    function collectSettings() {
        const cfg = S.config;
        const bounds = cfg.bounds || {};
        const changes = {};
        let errors = 0;
        let shrinks = false;
        document.querySelectorAll('#sl-settings-list .sl-set-row').forEach((row) => {
            const name = row.dataset.category;
            const cur = cfg.categories[name];
            const out = {};
            let error = '';
            row.querySelectorAll('[data-field]').forEach((el) => {
                const field = el.dataset.field;
                if (el.disabled) return;
                if (field === 'enabled') {
                    if (el.checked !== !!cur.enabled) out.enabled = el.checked;
                } else if (field === 'retention_days' || field === 'max_entries') {
                    const v = Number(el.value);
                    const [lo, hi] = bounds[field] || [1, Infinity];
                    if (!Number.isInteger(v) || v < lo || v > hi) {
                        error = `${field === 'retention_days' ? 'Days' : 'Max entries'}: ${lo}–${hi}`;
                        el.classList.add('sl-input-error');
                        return;
                    }
                    el.classList.remove('sl-input-error');
                    if (v !== cur[field]) {
                        out[field] = v;
                        if (v < cur[field]) shrinks = true;
                    }
                } else if (field === 'min_level') {
                    if (el.dataset.value !== cur.min_level) out.min_level = el.dataset.value;
                }
            });
            if (row.dataset.pause !== '') out.pause_minutes = Number(row.dataset.pause);
            const errEl = row.querySelector('.sl-set-error');
            errEl.textContent = error;
            errEl.hidden = !error;
            if (error) errors += 1;
            if (Object.keys(out).length) changes[name] = out;
        });
        return { changes, errors, shrinks };
    }

    function onSettingsChange(ev) {
        const t = ev && ev.target;
        if (t && t.dataset && t.dataset.field === 'enabled') {
            const row = t.closest('.sl-set-row');
            // Flipping a paused switch resumes the category instead of turning it off.
            if (rowPaused(row)) {
                row.dataset.pause = '0';
                t.checked = true;
            }
            syncRow(row);
        } else if (t && t.closest) {
            const row = t.closest('.sl-set-row');
            if (row) syncRow(row);
        }
        const { changes, errors, shrinks } = collectSettings();
        $('sl-settings-warn').hidden = !shrinks;
        const save = $('sl-settings-save');
        if (save) save.disabled = errors > 0 || Object.keys(changes).length === 0;
    }

    async function saveSettings() {
        const { changes, errors } = collectSettings();
        if (errors || !Object.keys(changes).length) return;
        const save = $('sl-settings-save');
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
            const ok = await window.nkConfirm('Hide all logs on this device?', 'Turn off system logs?', 'Turn off');
            if (!ok) {
                input.checked = true;
                return;
            }
        }
        input.disabled = true;
        const done = await setService(on);
        input.disabled = S.readonly;
        if (!done) input.checked = !on;
        else {
            if (S.config) S.config.enabled = on;
            setLowerOff(!on);
        }
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
        $('sl-clear-list').innerHTML = names.map((n) => {
            const count = typeof S.counts[n] === 'number' ? `<span class="sl-chip-count">${S.counts[n]}</span>` : '';
            const checked = !S.filters.category || S.filters.category === n ? 'checked' : '';
            return `<label class="sl-clear-item"><input type="checkbox" value="${n}" ${checked}>` +
                `<i class="fas ${E.CATEGORY_ICONS[n]}"></i><span>${E.esc(E.categoryLabel(n))}</span>${count}</label>`;
        }).join('');
        $('sl-clear-list').querySelectorAll('input').forEach((el) => el.addEventListener('change', updateClearButton));
        updateClearButton();
        openModal('sl-clear-modal');
    }

    function closeClear() {
        closeModal('sl-clear-modal');
    }

    function selectedClear() {
        return Array.from($('sl-clear-list').querySelectorAll('input:checked')).map((el) => el.value);
    }

    function updateClearButton() {
        $('sl-clear-confirm').disabled = selectedClear().length === 0;
    }

    async function confirmClear() {
        const cats = selectedClear();
        if (!cats.length) return;
        const btn = $('sl-clear-confirm');
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
        const page = $('system-logs-page');
        if (!page) return;
        S.peerId = page.dataset.peerId;
        S.readonly = page.dataset.readonly === 'true';
        S.detailsUrl = page.dataset.detailsUrl || '';
        renderChips();
        loadCategories();
        refresh();

        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                if (S.es) stopStream('paused');
            } else if (!S.es && $('sl-live').dataset.state === 'paused') {
                startStream();
            }
        });
        window.addEventListener('scroll', () => {
            if (S.pendingNew && !isScrolledAway()) {
                S.pendingNew = 0;
                $('sl-new-pill').hidden = true;
            }
        }, { passive: true });
        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                closeSettings();
                if ($('sl-clear-modal')) closeClear();
            }
        });
    }

    window.SystemLogsPage = {
        setCategory, applyFilters, onSearchInput, loadOlder, showNew,
        openSettings, closeSettings, saveSettings, toggleService,
        toggleExpandAll, pauseMode, closePause, confirmPause,
        openClear, closeClear, confirmClear, overlayClose,
    };

    document.addEventListener('DOMContentLoaded', () => { init(); bindPauseModal(); });
})();
