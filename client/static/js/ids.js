/**
 * IDS page: the status band (state pill + switch), the threats table with its
 * details pane (Mute / Change severity / Turn rule off), the last 24 hours and
 * the links to the settings and lists windows. Threats stay live over SSE.
 *
 * Deep links: ?threat=<id> opens that threat; ?severity=high&range=24h filters.
 */
(function () {
    const N = window.NkIds;
    const PAGE = 50;
    const RETRY_MS = 30000;
    const STATUS_MS = 30000;
    const BUSY_MS = 4000;
    const NARROW = 900;   // below this the pane replaces the table (beside it the table gets too narrow)

    const KINDS = ['Malware', 'Exploit', 'Scan', 'Phishing', 'Hostile address', 'Suspicious', 'Policy', 'P2P',
        'Denial of service', 'Unwanted software', 'Attack response', 'Information', 'Protocol anomaly',
        'Custom', 'Watchlist', 'Other'];
    const DIRECTIONS = { outbound: 'Outbound', inbound: 'Inbound', internal: 'Internal', external: 'External' };
    const RANGES = { '1h': ['Last hour', 3600e3], '24h': ['Last 24 hours', 86400e3], '7d': ['Last 7 days', 7 * 86400e3], '30d': ['Last 30 days', 30 * 86400e3] };
    const DURATIONS = [['day', 'A day'], ['week', 'A week'], ['month', 'A month'], ['permanent', 'Always']];
    const PRESETS = {
        essential: ['malware', 'exploit', 'phishing', 'hostile_addresses'],
        recommended: ['malware', 'exploit', 'scan', 'phishing', 'hostile_addresses', 'services'],
        strict: ['malware', 'exploit', 'scan', 'phishing', 'hostile_addresses', 'services', 'policy', 'p2p'],
    };
    const PRESET_GROUPS = ['malware', 'exploit', 'scan', 'phishing', 'hostile_addresses', 'services', 'policy', 'p2p', 'info'];
    const PROTOCOLS = ['http', 'tls', 'dns', 'smb', 'ssh', 'ftp', 'smtp', 'rdp', 'quic', 'sip'];
    const PROFILES = { light: 'Light', balanced: 'Balanced', thorough: 'Thorough' };
    const CUSTOM_SIDS = [9000000, 9899999];
    const WATCHLIST_SIDS = [9950000, 9999999];

    const S = {
        peerId: null,
        detailsUrl: '',
        readonly: false,
        status: null,
        state: 'loading',
        filters: { severity: '', kind: '', device: '', direction: '', range: '', q: '' },
        rows: [],
        byId: new Map(),
        devices: new Map(),   // ip -> name, from the rows seen
        nextBefore: null,
        hasMore: false,
        loading: false,
        openId: null,
        panel: null,          // {act, who, dur, comment, sev}
        done: null,           // {id, msg}
        busyAct: false,
        es: null,
        fails: 0,
        timer: null,
        statusTimer: null,
        menu: null,
        loadSeq: 0,
    };

    const $ = (id) => document.getElementById(id);
    const esc = (s) => N.esc(s);
    const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : '');
    const inSids = (sid, r) => sid >= r[0] && sid <= r[1];
    const isWatchlist = (e) => e.rule_group === 'watchlist' || inSids(e.sid, WATCHLIST_SIDS);
    const isCustom = (e) => e.rule_group === 'custom' || inSids(e.sid, CUSTOM_SIDS);

    function toast(kind, msg) {
        const fn = { ok: window.showSuccess, err: window.showError, info: window.showInfo }[kind];
        if (fn) fn(msg);
    }

    // ── Status band ─────────────────────────────────────────────────────────

    function renderStatus() {
        const key = S.state;
        const s = N.STATES[key] || N.STATES.failed;
        const st = S.status || {};
        const d = st.detection || {};
        const rules = st.rules || {};
        $('ids-pill').innerHTML = N.pillHtml(key);

        let msg = s.text || '';
        if (key === 'running' || key === 'dropping') msg = rules.updated_at ? `Rules updated ${N.dateTime(rules.updated_at)}` : 'Watching your network';
        if (key === 'applying') {
            const gap = st.engine && st.engine.inspection_gap_seconds;
            msg = gap ? `Inspection pauses ~${gap} s` : 'Applying change…';
        }
        const msgEl = $('ids-status-msg');
        msgEl.textContent = msg;
        msgEl.className = `ids-status-msg${s.tone === 'warn' || s.tone === 'err' ? ` ids-tone-${s.tone} ids-msg-tone` : ''}`;

        let bar = '';
        if (key === 'dropping') bar = 'Missing some traffic: too much for this device';
        if (key === 'error') bar = N.startError(st);
        const barEl = $('ids-status-bar');
        barEl.hidden = !bar;
        barEl.className = `ids-status-bar ids-tone-${s.tone}`;
        barEl.innerHTML = bar ? `${IdsIcon(key === 'error' ? 'circle-exclamation' : 'triangle-exclamation')}<span>${esc(bar)}</span>` : '';

        // Switch: shown when the IDS can be turned on/off; locked = visible, off, with a lock.
        const wrap = $('ids-switch-wrap');
        const sw = $('ids-switch');
        wrap.hidden = !s.sw;
        wrap.classList.toggle('ids-locked', !!s.lock);
        wrap.classList.add('no-anim');
        sw.checked = s.sw === 'on';
        sw.disabled = !!s.lock || S.readonly || !!S.switching;
        requestAnimationFrame(() => wrap.classList.remove('no-anim'));

        // Facts: only when there are values (no switch or a locked one = none).
        const facts = !!s.sw && !s.lock && (rules.count || rules.updated_at);
        $('ids-facts').hidden = !facts;
        if (facts) {
            $('ids-fact-rules').textContent = rules.count ? Number(rules.count).toLocaleString('en-US') : '—';
            $('ids-fact-updated').textContent = rules.updated_at ? N.dateTime(rules.updated_at) : '—';
            $('ids-fact-next').textContent = rules.next_update_at ? N.dateTime(rules.next_update_at) : '—';
            const gap = st.engine && st.engine.inspection_gap_seconds;
            $('ids-fact-gap').textContent = gap ? `~${gap} s` : '—';
        }
        renderVeil();
    }

    // A state with no live IDS veils the threats and the 24 h card (frosted, inert).
    function renderVeil() {
        const s = N.STATES[S.state] || N.STATES.failed;
        const veiled = !!s.veil;
        document.querySelectorAll('.ids-veil-target').forEach((el) => {
            el.classList.toggle('ids-veiled', veiled);
            el.inert = veiled;
            let v = el.querySelector(':scope > .ids-veil');
            if (!veiled) {
                if (v) v.remove();
                return;
            }
            if (!v) {
                v = document.createElement('div');
                v.className = 'ids-veil';
                el.appendChild(v);
            }
            v.className = `ids-veil ids-tone-${s.tone}`;
            v.innerHTML = `<span>${N.stateIcon(s)}${esc(s.veil)}</span>`;
            if (S.state === 'unsupported') v.querySelector('span').appendChild(N.updateLink(S.detailsUrl));
        });
    }

    async function refreshStatus() {
        try {
            S.status = await N.api.status(S.peerId);
            S.state = N.stateFromStatus(S.status);
        } catch (err) {
            S.status = null;
            S.state = N.stateFromError(err);
        }
        renderStatus();
        schedulePoll();
        return S.state;
    }

    // Poll fast while starting/applying, slowly otherwise.
    function schedulePoll() {
        clearTimeout(S.statusTimer);
        const s = N.STATES[S.state] || {};
        S.statusTimer = setTimeout(refreshStatus, s.busy ? BUSY_MS : STATUS_MS);
    }

    async function onSwitch() {
        const sw = $('ids-switch');
        const want = sw.checked;
        S.switching = true;
        sw.disabled = true;
        try {
            S.status = await N.api.setEnabled(S.peerId, want);
            S.state = N.stateFromStatus(S.status);
            if (want && S.state === 'off') S.state = 'starting';
        } catch (err) {
            sw.checked = !want;
            if (err.code === 'insufficient_memory') S.state = 'memory';
            else if (err.code === 'unavailable' || err.code === 'upgrade' || err.code === 'offline') S.state = err.code;
            toast('err', err.message || 'Couldn\'t save');
        } finally {
            S.switching = false;
        }
        renderStatus();
        schedulePoll();
        if (want) {
            loadSide();
            startStream();
        } else {
            stopStream('off');
        }
    }

    // ── Threats ─────────────────────────────────────────────────────────────

    function apiFilters() {
        const f = S.filters;
        const out = { severity: f.severity, kind: f.kind, device: f.device, direction: f.direction, q: f.q.trim() };
        if (f.range && RANGES[f.range]) out.since = new Date(Date.now() - RANGES[f.range][1]).toISOString();
        return out;
    }

    function streamFilters() {
        const { since, ...rest } = apiFilters();
        return rest;
    }

    function remember(e) {
        S.byId.set(e.id, e);
        const d = e.lan_device || {};
        if (d.ip && !S.devices.has(d.ip)) S.devices.set(d.ip, d.name || '');
    }

    async function loadThreats(more) {
        if (S.loading && more) return;
        const seq = ++S.loadSeq;
        S.loading = true;
        if (!more) {
            S.rows = [];
            S.byId = new Map();
            S.nextBefore = null;
            setThreatsState('spinner', 'Loading', undefined, true);
        } else {
            $('ids-more').hidden = false;
            $('ids-more').textContent = 'Loading…';
        }
        try {
            const params = { ...apiFilters(), limit: PAGE };
            if (more && S.nextBefore) params.before_id = S.nextBefore;
            const data = await N.api.threats(S.peerId, params);
            if (seq !== S.loadSeq) return;
            (data.entries || []).forEach((e) => {
                if (S.byId.has(e.id)) return;
                remember(e);
                S.rows.push(e);
            });
            S.hasMore = !!(data.page && data.page.has_more);
            S.nextBefore = data.page ? data.page.next_before_id : null;
            if (!more) {
                await openFromUrl();
                // Wide screens show the first threat in the pane (T2); phones start with the list.
                if (!S.openId && S.rows.length && !isNarrow()) S.openId = S.rows[0].id;
            }
            renderThreats();
            if (!more) startStream();
        } catch (err) {
            if (seq !== S.loadSeq) return;
            const key = N.stateFromError(err);
            if (key !== 'failed') {
                S.state = key;
                renderStatus();
            }
            setThreatsState('triangle-exclamation', 'Couldn\'t load', err.message);
            stopStream('off');
            if (key === 'offline' || key === 'failed') S.timer = setTimeout(() => loadThreats(false), RETRY_MS);
        } finally {
            if (seq === S.loadSeq) S.loading = false;
        }
    }

    // ?threat=<id>: open it, fetching it when it is not on the first page.
    async function openFromUrl() {
        const id = Number(new URLSearchParams(location.search).get('threat'));
        if (!id || S.openId) return;
        if (!S.byId.has(id)) {
            try {
                const data = await N.api.threats(S.peerId, { after_id: id - 1, limit: 1 });
                const e = (data.entries || [])[0];
                if (e && e.id === id) {
                    remember(e);
                    S.rows.push(e);
                    S.rows.sort((a, b) => b.id - a.id);
                }
            } catch (e) { /* the list still shows */ }
        }
        if (S.byId.has(id)) S.openId = id;
    }

    function setThreatsState(icon, title, text, spin) {
        $('ids-t2').hidden = true;
        const el = $('ids-threats-state');
        el.innerHTML = `${IdsIcon(icon, { spin: !!spin })}<span class="sl-state-title">${esc(title)}</span>` +
            (text ? `<span class="sl-state-text">${esc(text)}</span>` : '');
        el.hidden = false;
        $('ids-shown').textContent = '';
    }

    function isNarrow() {
        return $('ids-threats-body').clientWidth < NARROW;
    }

    function rowHtml(e, fresh) {
        const cur = e.id === S.openId ? ' ids-cur' : '';
        return `<tr class="${N.sevClass(e.severity)}${cur}${fresh ? ' ids-row-new' : ''}" data-id="${Number(e.id)}" tabindex="0">` +
            `<td><span class="ids-sev-dot"><span>${N.sevLabel(e.severity)}</span></span></td>` +
            `<td title="${esc(N.fullTime(e.last_seen || e.time))}">${esc(N.shortTime(e.last_seen || e.time))}</td>` +
            `<td class="ids-c-kind" title="${esc(e.kind)}">${esc(e.kind || '')}</td>` +
            `<td title="${esc(N.deviceLabel(e))}">${esc(N.deviceLabel(e))}</td>` +
            `<td class="ids-c-rem" title="${esc(N.remoteLabel(e))}">${esc(N.remoteLabel(e))}</td>` +
            `<td class="ids-c-svc" title="${esc(e.service || '')}">${esc(e.service || '—')}</td>` +
            `<td title="Seen ${esc(N.timesLabel(e.repeat_count))}">${(Number(e.repeat_count) || 1).toLocaleString('en-US')}</td></tr>`;
    }

    function renderThreats(freshId) {
        const anyFilter = Object.values(S.filters).some((v) => v);
        if (!S.rows.length) {
            stopMore();
            setThreatsState(anyFilter ? 'filter' : 'circle-check', anyFilter ? 'No matches' : 'No threats',
                anyFilter ? 'Nothing matches these filters.' : 'Nothing found yet.');
            if (anyFilter) $('ids-threats-state').classList.remove('ids-tone-ok');
            return;
        }
        $('ids-threats-state').hidden = true;
        const t2 = $('ids-t2');
        t2.hidden = false;
        const narrow = isNarrow();
        t2.classList.toggle('ids-narrow', narrow);
        t2.classList.toggle('ids-detail', narrow && !!S.openId);
        $('ids-rows').innerHTML = S.rows.map((e) => rowHtml(e, e.id === freshId)).join('');
        $('ids-shown').textContent = `${S.rows.length.toLocaleString('en-US')} shown`;
        const more = $('ids-more');
        more.hidden = !S.hasMore;
        more.textContent = S.hasMore ? 'Loading more as you scroll.' : '';
        renderPane();
    }

    function stopMore() {
        $('ids-more').hidden = true;
    }

    // ── Details pane + its three actions ─────────────────────────────────────

    function seenText(e) {
        const first = N.dateTime(e.time);
        const last = N.dateTime(e.last_seen || e.time);
        return first === last ? first : `${first} – ${last}`;
    }

    function withAddr(name, ip) {
        if (name && ip && name !== ip) return `${esc(name)} (${esc(ip)})`;
        return esc(name || ip || '—');
    }

    function paneActions(e) {
        const wl = isWatchlist(e);
        const own = isCustom(e);
        const muteOff = wl ? 'disabled title="Watchlist threats can\'t be muted. Edit the watchlist instead."' : '';
        const ruleOff = wl ? 'disabled title="Edit the watchlist instead."'
            : own ? 'disabled title="Change it in its custom rule."' : '';
        const ro = S.readonly ? 'disabled' : '';
        return `<div class="ids-pane-btns">` +
            `<button type="button" class="ids-btn" data-a="mute" ${muteOff || ro}>${IdsIcon('bell-slash')}Mute</button>` +
            `<button type="button" class="ids-btn" data-a="sev" ${ruleOff || ro}>${IdsIcon('signal')}Change severity</button>` +
            `<button type="button" class="ids-btn ids-btn-redo" data-a="off" ${ruleOff || ro}>${IdsIcon('ban')}Turn rule off</button></div>`;
    }

    function chips(name, opts, current, sevColours) {
        return `<div class="ids-chips">${opts.map(([v, l]) =>
            `<button type="button" class="ids-chip${sevColours ? ` ${N.sevClass(v)}` : ''}${v === current ? ' ids-on' : ''}" data-${name}="${v}">` +
            `${sevColours ? '<span class="ids-dot"></span>' : ''}${esc(l)}</button>`).join('')}</div>`;
    }

    function panelHtml(e) {
        if (S.done && S.done.id === e.id) {
            return `<div class="ids-done">${IdsIcon('circle-check')}${esc(S.done.msg)}</div>`;
        }
        const p = S.panel;
        if (!p) return '';
        const wait = S.busyAct ? 'disabled' : '';
        if (p.act === 'mute') {
            const dev = e.lan_device && e.lan_device.ip;
            const who = dev ? [['dev', `This device (${N.deviceLabel(e)})`], ['all', 'Every device']] : [['all', 'Every device']];
            return `<div class="ids-act"><div class="ids-act-h">${IdsIcon('bell-slash')}Mute this threat</div>` +
                `<div class="ids-f"><span>For</span>${chips('who', who, p.who)}</div>` +
                `<div class="ids-f"><span>How long</span>${chips('dur', DURATIONS, p.dur)}</div>` +
                `<div class="ids-f"><span>Comment</span><input type="text" class="ids-input" id="ids-mute-comment" maxlength="200" placeholder="Optional" value="${esc(p.comment || '')}"></div>` +
                `<div class="ids-note">Still inspected, just not recorded.</div>` +
                `<div class="ids-act-btns"><button type="button" class="ids-btn" data-x="cancel">Cancel</button>` +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="mute" ${wait}>Mute</button></div></div>`;
        }
        if (p.act === 'sev') {
            const opts = N.SEVERITIES.map((k) => [k, N.sevLabel(k)]);
            return `<div class="ids-act"><div class="ids-act-h">${IdsIcon('signal')}Severity of rule ${Number(e.sid)}</div>` +
                `<div class="ids-f"><span>Severity</span>${chips('sev', opts, p.sev, true)}</div>` +
                `<div class="ids-note">Applies to new threats from this rule.</div>` +
                `<div class="ids-act-btns"><button type="button" class="ids-btn" data-x="cancel">Cancel</button>` +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="sev" ${p.sev === e.severity || S.busyAct ? 'disabled' : ''}>Save</button></div></div>`;
        }
        return `<div class="ids-act"><div class="ids-act-h ids-act-red">${IdsIcon('ban')}Turn rule ${Number(e.sid)} off?</div>` +
            `<div class="ids-note">It stops on every device. Turn it back on in Lists › Changed rules.</div>` +
            `<div class="ids-act-btns"><button type="button" class="ids-btn" data-x="cancel">Cancel</button>` +
            `<button type="button" class="ids-btn ids-btn-danger" data-x="off" ${wait}>Turn off</button></div></div>`;
    }

    function renderPane() {
        const pane = $('ids-pane');
        const e = S.openId ? S.byId.get(S.openId) : null;
        if (!e) {
            pane.className = 'ids-pane ids-pane-empty';
            pane.innerHTML = 'Pick a threat to see details.';
            return;
        }
        const r = e.remote || {};
        const d = e.lan_device || {};
        const remote = withAddr(r.name, r.ip) + (r.port ? ` · port ${Number(r.port)}` : '');
        pane.className = `ids-pane ${N.sevClass(e.severity)}`;
        pane.innerHTML =
            `<button type="button" class="ids-back" data-back="1">${IdsIcon('chevron-left')}Threats</button>` +
            `<div class="ids-pane-title">${esc(e.signature || 'Threat')}</div>` +
            `<div class="ids-pane-tags"><span class="ids-sev-pill">${N.sevLabel(e.severity)}</span>` +
            `<span class="ids-times" title="Seen ${esc(N.timesLabel(e.repeat_count))}">${esc(N.timesLabel(e.repeat_count))}</span></div>` +
            `<div class="ids-kv">` +
            `<span>Kind</span><span>${esc(e.kind || '—')}</span>` +
            `<span>Device</span><span>${d.ip ? withAddr(d.name, d.ip) : '—'}</span>` +
            `<span>Remote</span><span>${remote}</span>` +
            `<span>Service</span><span>${esc(e.service || '—')}</span>` +
            `<span>Direction</span><span>${esc(DIRECTIONS[e.direction] || cap(e.direction) || '—')}</span>` +
            `<span>Where</span><span>${esc(N.placeLabel(e.interface_label) || '—')}</span>` +
            `<span>Seen</span><span>${esc(seenText(e))}</span>` +
            (isWatchlist(e) ? '' : `<span>Rule</span><span class="ids-mono">${Number(e.sid) || '—'}</span>`) +
            `</div>` + paneActions(e) + panelHtml(e);
    }

    async function runAction(e) {
        const p = S.panel;
        S.busyAct = true;
        renderPane();
        try {
            let msg;
            if (p.act === 'mute') {
                const comment = ($('ids-mute-comment') || {}).value || '';
                const body = { sid: e.sid, duration: p.dur };
                if (p.who === 'dev' && e.lan_device && e.lan_device.ip) body.device = e.lan_device.ip;
                if (comment.trim()) body.comment = comment.trim();
                await N.api.add(S.peerId, 'muted', body);
                const when = { day: ' for a day', week: ' for a week', month: ' for a month', permanent: '' }[p.dur];
                msg = `Muted ${body.device ? `for ${N.deviceLabel(e)}` : 'for every device'}${when}.`;
            } else if (p.act === 'sev') {
                await N.api.setRule(S.peerId, e.sid, { severity: p.sev });
                msg = `Rule ${e.sid} set to ${N.sevLabel(p.sev).toLowerCase()}.`;
            } else {
                await N.api.setRule(S.peerId, e.sid, { disabled: true });
                msg = `Rule ${e.sid} turned off.`;
            }
            S.panel = null;
            S.done = { id: e.id, msg };
            loadSide();
        } catch (err) {
            toast('err', err.message || 'Couldn\'t save');
        } finally {
            S.busyAct = false;
            renderPane();
        }
    }

    function onPaneClick(ev) {
        const b = ev.target.closest('button');
        if (!b || b.disabled) return;
        const e = S.byId.get(S.openId);
        if (!e) return;
        if (b.dataset.back) {
            S.openId = null;
            S.panel = null;
            renderThreats();
            return;
        }
        if (b.dataset.a) {
            const dev = e.lan_device && e.lan_device.ip;
            S.done = null;
            S.panel = { act: b.dataset.a, who: dev ? 'dev' : 'all', dur: 'week', comment: '', sev: e.severity };
        } else if (b.dataset.who) {
            S.panel.who = b.dataset.who;
        } else if (b.dataset.dur) {
            S.panel.dur = b.dataset.dur;
        } else if (b.dataset.sev) {
            S.panel.sev = b.dataset.sev;
        } else if (b.dataset.x === 'cancel') {
            S.panel = null;
        } else if (b.dataset.x) {
            runAction(e);
            return;
        } else {
            return;
        }
        // Keep what was typed in the comment across a chip click.
        const c = $('ids-mute-comment');
        if (c && S.panel) S.panel.comment = c.value;
        renderPane();
    }

    function openRow(tr) {
        if (!tr) return;
        const id = Number(tr.dataset.id);
        if (S.openId === id && !isNarrow()) return;
        S.openId = id;
        S.panel = null;
        S.done = null;
        document.querySelectorAll('#ids-rows tr.ids-cur').forEach((x) => x.classList.remove('ids-cur'));
        tr.classList.add('ids-cur');
        const t2 = $('ids-t2');
        t2.classList.toggle('ids-detail', isNarrow());
        renderPane();
        if (isNarrow()) $('ids-threats-body').scrollIntoView({ block: 'start', behavior: 'smooth' });
    }

    // ── Filters (our own menus, never a native select) ──────────────────────

    function filterOptions(name) {
        if (name === 'severity') return [['', 'All severities'], ...N.SEVERITIES.map((k) => [k, N.sevLabel(k)])];
        if (name === 'kind') return [['', 'All kinds'], ...KINDS.map((k) => [k, k])];
        if (name === 'device') {
            const list = [...S.devices.entries()].sort((a, b) => (a[1] || a[0]).localeCompare(b[1] || b[0]));
            return [['', 'All devices'], ...list.map(([ip, name]) => [ip, name ? `${name} (${ip})` : ip])];
        }
        if (name === 'direction') return [['', 'Any direction'], ...Object.entries(DIRECTIONS)];
        return [['', 'Any time'], ...Object.entries(RANGES).map(([k, v]) => [k, v[0]])];
    }

    function filterLabel(name) {
        const v = S.filters[name];
        const opt = filterOptions(name).find(([k]) => k === v);
        if (opt) return opt[1];
        return name === 'device' && v ? v : filterOptions(name)[0][1];
    }

    function paintFilters() {
        document.querySelectorAll('#ids-filters .ids-drop').forEach((b) => {
            const name = b.dataset.filter;
            b.querySelector('span').textContent = filterLabel(name);
            b.classList.toggle('ids-set', !!S.filters[name]);
        });
        $('ids-reset').hidden = !Object.values(S.filters).some((v) => v && String(v).trim());
    }

    // Clear every filter and the search, and drop their params from the URL.
    function resetFilters() {
        Object.keys(S.filters).forEach((k) => { S.filters[k] = ''; });
        $('ids-q').value = '';
        clearTimeout(S.qTimer);
        const url = new URL(location.href);
        ['severity', 'kind', 'device', 'direction', 'range', 'since', 'q', 'threat'].forEach((k) => url.searchParams.delete(k));
        history.replaceState(null, '', url.pathname + url.search + url.hash);
        applyFilters();
    }

    function closeMenu() {
        if (S.menu) {
            S.menu.remove();
            S.menu = null;
        }
    }

    function openMenu(btn) {
        const name = btn.dataset.filter;
        const was = S.menu && S.menu.dataset.for === name;
        closeMenu();
        if (was) return;
        const m = document.createElement('div');
        m.className = 'ids-menu';
        m.dataset.for = name;
        m.innerHTML = filterOptions(name).map(([v, l]) =>
            `<button type="button" data-v="${esc(v)}" class="${v === S.filters[name] ? 'ids-sel' : ''}${name === 'severity' && v ? ` ${N.sevClass(v)}` : ''}">` +
            `${name === 'severity' && v ? '<span class="ids-dot"></span>' : ''}<span>${esc(l)}</span>` +
            `${v === S.filters[name] ? IdsIcon('check') : ''}</button>`).join('');
        document.body.appendChild(m);
        const r = btn.getBoundingClientRect();
        const w = Math.max(r.width, 180);
        m.style.minWidth = `${w}px`;
        m.style.top = `${r.bottom + window.scrollY + 4}px`;
        m.style.left = `${Math.min(r.left + window.scrollX, window.scrollX + document.documentElement.clientWidth - m.offsetWidth - 8)}px`;
        m.addEventListener('click', (ev) => {
            const b = ev.target.closest('button');
            if (!b) return;
            S.filters[name] = b.dataset.v;
            closeMenu();
            applyFilters();
        });
        S.menu = m;
    }

    function applyFilters() {
        paintFilters();
        S.openId = null;
        S.panel = null;
        S.done = null;
        loadThreats(false);
    }

    // ── Live stream ─────────────────────────────────────────────────────────

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
        if ((N.STATES[S.state] || {}).veil) {
            return;      // nothing new arrives while the IDS is not watching
        }
        if (document.hidden) {
            S.paused = true;
            return;
        }
        const es = new EventSource(N.api.streamUrl(S.peerId, streamFilters()));
        S.es = es;
        es.onopen = () => {
            if (S.es !== es) return;
            S.fails = 0;
        };
        es.addEventListener('threat', (msg) => {
            if (S.es !== es) return;
            let e;
            try { e = JSON.parse(msg.data); } catch (x) { return; }
            if (!e || typeof e.id !== 'number' || S.byId.has(e.id)) return;
            remember(e);
            S.rows.unshift(e);
            renderThreats(e.id);
            bumpCounts(e.severity, Number(e.repeat_count) || 1);
        });
        es.addEventListener('repeat', (msg) => {
            if (S.es !== es) return;
            let d;
            try { d = JSON.parse(msg.data); } catch (x) { return; }
            const e = S.byId.get(d.id);
            if (!e) return;
            const added = Math.max(0, (Number(d.repeat_count) || 0) - (Number(e.repeat_count) || 0));
            e.repeat_count = d.repeat_count;
            e.last_seen = d.last_seen;
            const tr = document.querySelector(`#ids-rows tr[data-id="${d.id}"]`);
            if (tr) tr.outerHTML = rowHtml(e, false);
            if (S.openId === d.id && !S.panel) renderPane();
            bumpCounts(e.severity, added);
        });
        es.onerror = () => {
            if (S.es !== es) return;
            if (es.readyState === EventSource.CLOSED) {
                stopStream('offline');
                S.fails += 1;
                const delay = Math.min(RETRY_MS, 5000 * 2 ** (S.fails - 1));
                S.timer = setTimeout(S.fails >= 2 ? () => loadThreats(false) : startStream, delay);
            }
        };
    }

    // ── Right column ────────────────────────────────────────────────────────

    let counts = null;

    function bumpCounts(sev, n) {
        if (!counts || !n || !(sev in counts)) return;
        counts[sev] += n;
        renderBars();
    }

    function renderBars() {
        const c = counts || { high: 0, medium: 0, low: 0 };
        const max = Math.max(1, ...N.SEVERITIES.map((k) => Number(c[k]) || 0));
        $('ids-bars').innerHTML = N.SEVERITIES.map((k) => {
            const n = Number(c[k]) || 0;
            return `<button type="button" class="ids-bar ${N.sevClass(k)}" data-sev="${k}" title="Show ${N.sevLabel(k).toLowerCase()} threats from the last 24 hours">` +
                `<span>${N.sevLabel(k)}</span><span class="ids-bar-track"><i style="width:${n ? Math.max(3, Math.round((n / max) * 100)) : 0}%"></i></span>` +
                `<b>${n.toLocaleString('en-US')}</b></button>`;
        }).join('');
    }

    function detectionLabel(groups) {
        const on = PRESET_GROUPS.filter((g) => groups && groups[g]).sort().join(',');
        const hit = Object.entries(PRESETS).find(([, list]) => [...list].sort().join(',') === on);
        return hit ? cap(hit[0]) : 'Custom';
    }

    function setV(id, text) {
        const el = $(id);
        if (el) el.textContent = text;
    }

    async function loadSide() {
        N.api.summary(S.peerId).then((sum) => {
            counts = sum.counts || null;
            renderBars();
        }).catch(() => renderBars());
        N.api.settings(S.peerId).then((doc) => {
            const s = doc.settings || {};
            const rules = s.rules || {};
            setV('ids-v-detection', detectionLabel(rules.rule_groups));
            const protocols = s.protocols || {};
            const on = PROTOCOLS.filter((p) => protocols[p]).length;
            setV('ids-v-inspection', `${on} of ${PROTOCOLS.length} protocols`);
            const net = s.networks || {};
            const nets = 1 + (net.internal_networks || []).length;   // the LAN is always one
            setV('ids-v-networks', `${nets} ${nets === 1 ? 'network' : 'networks'}`);
            setV('ids-v-performance', PROFILES[(s.performance || {}).profile] || '');
            const days = (s.events || {}).retention_days;
            setV('ids-v-recording', days ? `${days} ${days === 1 ? 'day' : 'days'}` : '');
            setV('ids-v-rules', String((doc.rule_overrides || []).length));
        }).catch(() => { /* the links still open */ });
        [['muted', 'ids-v-muted'], ['excluded', 'ids-v-excluded'], ['watchlists', 'ids-v-watchlists']].forEach(([name, id]) => {
            N.api.list(S.peerId, name).then((d) => setV(id, String((d.items || []).length))).catch(() => {});
        });
    }

    // ── Clear ───────────────────────────────────────────────────────────────

    function openClear() {
        $('ids-clear-modal').classList.add('active');
    }

    function closeClear() {
        $('ids-clear-modal').classList.remove('active');
    }

    async function confirmClear() {
        const b = $('ids-clear-confirm');
        b.disabled = true;
        try {
            await N.api.clear(S.peerId);
            closeClear();
            toast('ok', 'Cleared');
            S.openId = null;
            S.panel = null;
            loadThreats(false);
            loadSide();
        } catch (err) {
            toast('err', err.message || 'Couldn\'t clear');
        } finally {
            b.disabled = false;
        }
    }

    // ── Start ───────────────────────────────────────────────────────────────

    function readUrl() {
        const q = new URLSearchParams(location.search);
        const sev = q.get('severity');
        if (N.SEVERITIES.includes(sev)) S.filters.severity = sev;
        const range = q.get('range');
        if (RANGES[range]) S.filters.range = range;
    }

    document.addEventListener('DOMContentLoaded', async () => {
        const page = $('ids-page');
        if (!page || !N) return;
        S.peerId = page.dataset.peerId;
        S.detailsUrl = page.dataset.detailsUrl;
        S.readonly = page.dataset.readonly === 'true';
        document.querySelector('.ids-threats').classList.add('ids-veil-target');
        document.querySelector('.ids-side-card').classList.add('ids-veil-target');
        readUrl();
        paintFilters();
        renderStatus();
        renderBars();

        $('ids-switch').addEventListener('change', onSwitch);
        $('ids-filters').addEventListener('click', (ev) => {
            const b = ev.target.closest('.ids-drop');
            if (b) {
                ev.stopPropagation();
                openMenu(b);
            }
        });
        $('ids-reset').addEventListener('click', resetFilters);
        $('ids-q').addEventListener('input', () => {
            clearTimeout(S.qTimer);
            S.qTimer = setTimeout(() => {
                S.filters.q = $('ids-q').value;
                applyFilters();
            }, 400);
        });
        document.addEventListener('click', (ev) => {
            if (S.menu && !S.menu.contains(ev.target)) closeMenu();
        });
        document.addEventListener('keydown', (ev) => {
            if (ev.key === 'Escape') {
                closeMenu();
                closeClear();
            }
        });
        window.addEventListener('scroll', closeMenu, { passive: true });
        $('ids-rows').addEventListener('click', (ev) => openRow(ev.target.closest('tr[data-id]')));
        $('ids-rows').addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter') openRow(ev.target.closest('tr[data-id]'));
        });
        $('ids-pane').addEventListener('click', onPaneClick);
        $('ids-bars').addEventListener('click', (ev) => {
            const b = ev.target.closest('[data-sev]');
            if (!b) return;
            S.filters.severity = b.dataset.sev;
            S.filters.range = '24h';
            applyFilters();
        });
        if (window.IdsWin) {
            IdsWin.group('settings', { title: 'Settings', icon: 'gear', items: ['detection', 'inspection', 'networks', 'performance', 'recording'] });
            IdsWin.group('lists', { title: 'Lists', icon: 'list', items: ['muted', 'excluded', 'watchlists', 'rules'] });
            IdsWin.setContext({
                peerId: S.peerId, readonly: S.readonly, api: N.api, N, toast,
                refreshSide: loadSide, refreshStatus,
            });
        }
        document.querySelectorAll('.ids-link').forEach((b) => b.addEventListener('click', () => {
            if (!window.IdsWin || !IdsWin.open(b.dataset.open)) toast('info', 'Coming soon');
        }));
        const clear = $('ids-clear');
        if (clear) clear.addEventListener('click', openClear);
        $('ids-clear-confirm').addEventListener('click', confirmClear);
        $('ids-clear-modal').addEventListener('click', (ev) => {
            if (ev.target === ev.currentTarget || ev.target.closest('[data-close]')) closeClear();
        });

        // Infinite scroll: load the next page when the end of the table shows.
        new IntersectionObserver((entries) => {
            if (entries.some((x) => x.isIntersecting) && S.hasMore && !S.loading) loadThreats(true);
        }).observe($('ids-more'));

        let lastNarrow = null;
        window.addEventListener('resize', () => {
            const n = isNarrow();
            if (n !== lastNarrow) {
                lastNarrow = n;
                if (S.rows.length) renderThreats();
            }
        });
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                if (S.es) stopStream('paused');
            } else if (!S.es && S.paused) {
                loadThreats(false);
                refreshStatus();
            }
        });

        const state = await refreshStatus();
        if (state === 'offline' || state === 'unsupported' || state === 'upgrade') {
            setThreatsState(N.STATES[state].icon, N.STATES[state].title, undefined, N.STATES[state].spin);
            return;
        }
        loadSide();
        loadThreats(false);
    });

    window.IdsPage = { _state: S, refreshStatus, loadThreats };
})();
