/**
 * IDS page windows: Detection and Threat recording (staged save).
 *
 * Both read GET /ids/settings once. Edits stay in the window (a changed row shows
 * "Not saved"); "Save changes" sends one PUT /ids/settings with only the changed
 * fields, then refreshSide() + refreshStatus(). "Close" drops unsaved edits.
 * Designs: ids-part4l-settings.html (Detection), ids-part11-recording.html option A.
 */
(function () {
    const esc = (s) => window.NkIds.esc(s);
    const fmt = (n) => Number(n).toLocaleString('en-US');
    const json = (v) => JSON.stringify(v === undefined ? null : v);

    // ── Detection: wording from the approved design ────────────────────────────
    const GROUPS = {
        malware: ['Malware', 'Infected devices talking to attackers.'],
        exploit: ['Exploits', 'Attacks on weak software.'],
        scan: ['Scans', 'Someone mapping your network.'],
        phishing: ['Phishing', 'Fake login and payment pages.'],
        hostile_addresses: ['Known bad addresses', 'Traffic with known attack sources.'],
        services: ['Exposed services', 'Attacks on remote desktop, file sharing and mail.'],
        policy: ['Company policy', 'Remote tools, cloud storage and games.'],
        p2p: ['Peer-to-peer', 'Torrents and file-sharing apps.'],
        info: ['Information', 'Low-value notices. Noisy.'],
        protocol_anomalies: ['Protocol anomalies', 'Network problems, not attacks. Very noisy.'],
    };
    const GROUP_ORDER = Object.keys(GROUPS);
    const FEEDS = {
        malicious_certificates: ['Bad certificates', 'Sites that use a certificate known to be bad.'],
        botnet_servers: ['Botnet servers', 'Servers that control infected devices.'],
        malicious_links: ['Malicious links', 'Links known to spread harm.'],
        aggressive_addresses: ['Aggressive addresses', 'Addresses known for attacks.'],
    };
    // Presets cover the nine ordinary groups; protocol_anomalies is Advanced only.
    const LEVELS = {
        essential: ['malware', 'exploit', 'phishing', 'hostile_addresses'],
        recommended: ['malware', 'exploit', 'scan', 'phishing', 'hostile_addresses', 'services'],
        strict: ['malware', 'exploit', 'scan', 'phishing', 'hostile_addresses', 'services', 'policy', 'p2p'],
    };
    const LEVEL_NAME = { essential: 'Essential', recommended: 'Recommended', strict: 'Strict', custom: 'Custom' };
    const LEVEL_TEXT = {
        essential: 'Clear attacks only. Fewest alerts.',
        recommended: 'Best for most networks.',
        strict: 'Also company policy and peer-to-peer.',
        custom: 'Your own mix.',
    };
    const RECORD = [
        ['high', 'High only', 'Only serious threats. Fewest records.'],
        ['medium', 'Medium and high', 'Skips low threats. Less noise.'],
        ['low', 'All threats', 'Everything, low included. Most records.'],
    ];
    const TIP_RECORD = 'This only decides what is recorded, so your list doesn\'t fill with threats you don\'t need. ' +
        'Level decides what is looked for.';
    const TIP_KEEP = 'When any limit is reached, the oldest threats are removed first.';
    const TIP_INFO = 'Some of these come from the device itself, from its normal background traffic such as updates and name lookups. ' +
        'They are not a problem.';
    const TIP_HTTP = 'The site name is always kept. This adds the full page address and the browser name.';

    const P_GROUP = (n) => `rules.rule_groups.${n}`;
    const P_FEED = (n) => `rules.rule_feeds.${n}`;
    const P_SEV = 'suppression.minimum_severity';
    const P_REPEAT = 'suppression.repeat_window_seconds';
    const P_TIME = 'rules.rules_update_time';

    // ── Small helpers ──────────────────────────────────────────────────────────
    function getP(obj, path) {
        return path.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), obj);
    }

    function setP(obj, path, value) {
        const keys = path.split('.');
        let o = obj;
        keys.slice(0, -1).forEach((k) => {
            if (!o[k] || typeof o[k] !== 'object') o[k] = {};
            o = o[k];
        });
        o[keys[keys.length - 1]] = value;
    }

    // [min, max] from an options entry shaped {min, max}; the documented bounds otherwise.
    function bounds(opt, lo, hi) {
        const ok = opt && typeof opt === 'object' && !Array.isArray(opt);
        return [ok && typeof opt.min === 'number' ? opt.min : lo, ok && typeof opt.max === 'number' ? opt.max : hi];
    }

    async function putSettings(ctx, body) {
        let res;
        try {
            res = await fetch(`/api/v2/client/peers/${encodeURIComponent(ctx.peerId)}/ids/settings`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
                body: JSON.stringify(body),
            });
        } catch (e) {
            throw new Error('Couldn\'t save.');
        }
        let data = null;
        try { data = await res.json(); } catch (e) { /* empty body */ }
        if (!res.ok) {
            const msg = data && typeof data.detail === 'string' ? data.detail : 'Couldn\'t save.';
            throw new Error(msg);
        }
        return data || {};
    }

    const switchHtml = (path, on, off, label) =>
        `<label class="switch"><input type="checkbox" data-sw="${path}" data-fk="sw:${path}" aria-label="${esc(label)}"` +
        `${on ? ' checked' : ''}${off ? ' disabled' : ''}><span class="slider"></span></label>`;

    const tipHtml = (key, text) =>
        `<span class="ids-ws-tip" data-tk="${key}"><button type="button" class="ids-ws-ib" data-tip="${key}" ` +
        `aria-label="More about this" aria-expanded="false">${IdsIcon('circle-info')}</button>` +
        `<span class="ids-ws-bub" role="tooltip">${esc(text)}</span></span>`;

    // ── The store: draft settings, staged save, footer, tips ───────────────────
    function createStore(ctx, win, doc, root, onDraw, tracked) {
        const S = doc.settings || {};   // the draft the controls show
        const D = doc.defaults || {};
        const O = doc.options || {};
        const err = {};     // path -> red text (not saved)
        const warn = {};    // path -> amber text (typing)
        const readonly = !!ctx.readonly;
        let base = JSON.parse(json(S));  // what is saved
        let saving = false;
        let done = false;
        let doneTimer = null;
        let fail = '';
        let confirmEl = null;
        let tip = null;
        let pinned = false;
        let tipTimer = null;

        const store = { S, D, O, err, warn, readonly };
        store.get = (p) => getP(S, p);
        store.def = (p) => getP(D, p);
        store.isCust = (p) => json(getP(S, p)) !== json(getP(D, p));
        store.pending = () => tracked.filter((p) => json(getP(S, p)) !== json(getP(base, p)));
        store.isPending = (p) => json(getP(S, p)) !== json(getP(base, p));
        store.anyPending = (paths) => paths.some(store.isPending);

        // Redraw the window, keeping the keyboard focus on the same control.
        store.draw = function () {
            const fk = document.activeElement && root.contains(document.activeElement)
                ? document.activeElement.dataset.fk : null;
            tip = null;
            pinned = false;
            onDraw();
            if (fk) {
                const el = root.querySelector(`[data-fk="${fk}"]`);
                if (el) el.focus();
            }
        };

        store.statusHtml = function (key, noReset) {
            if (store.isPending(key)) return '<span class="ids-ws-badge">Not saved</span>';
            if (!noReset && !readonly && store.isCust(key)) return `<button type="button" class="ids-ws-lnk" data-reset="${key}" title="Reset to default" aria-label="Reset to default">Reset</button>`;
            return '';
        };

        // The footer is built once and only updated, so a blur never swallows the Save click.
        function renderFoot() {
            const n = store.pending().length;
            const foot = win.foot;
            if (!foot.querySelector('[data-foot]')) {
                foot.innerHTML = '<div class="ids-foot-status"></div><div class="ids-foot-btns">' +
                    '<button type="button" class="ids-btn" data-foot="close">Close</button>' +
                    '<button type="button" class="ids-btn ids-btn-primary" data-foot="save">' + IdsIcon('floppy-disk') + ' Save changes</button></div>';
            }
            let html;
            if (saving) html = '<b>' + IdsIcon('circle-notch', {spin: true}) + ' Saving.</b><small>Takes under a minute.</small>';
            else if (done) html = '<span class="ids-ws-okt">' + IdsIcon('check') + ' Saved.</span>';
            else if (n) html = `<b>${n} unsaved ${n === 1 ? 'change' : 'changes'}.</b><small>Changes take effect in under a minute.</small>`;
            else html = '';
            if (fail && !saving) html += `<span class="ids-ws-fail">${IdsIcon('circle-exclamation')} ${esc(fail)}</span>`;
            const st = foot.querySelector('.ids-foot-status');
            if (st.innerHTML !== html) st.innerHTML = html;
            const sv = foot.querySelector('[data-foot="save"]');
            sv.disabled = saving || done || !n || readonly;
            foot.querySelector('[data-foot="close"]').disabled = saving;
        }

        // Update only what a change touches: row marks, dots, messages, footer.
        store.paint = function () {
            root.querySelectorAll('[data-st]').forEach((el) => {
                const k = el.dataset.st;
                el.innerHTML = el.dataset.resetonly
                    ? (!readonly && store.isCust(k) ? `<button type="button" class="ids-ws-lnk" data-reset="${k}" title="Reset to default" aria-label="Reset to default">Reset</button>` : '')
                    : store.statusHtml(k, !!el.dataset.noreset);
            });
            root.querySelectorAll('[data-dot]').forEach((el) => { el.hidden = !store.isCust(el.dataset.dot); });
            root.querySelectorAll('[data-msg]').forEach((el) => {
                const k = el.dataset.msg;
                const e = err[k];
                const a = warn[k];
                el.hidden = !(e || a);
                el.classList.toggle('amber', !e && !!a);
                el.innerHTML = e ? `${IdsIcon('circle-exclamation')}${esc(e)}`
                    : a ? `${IdsIcon('triangle-exclamation')}${esc(a)}` : '';
            });
            root.querySelectorAll('[data-n]').forEach((el) => {
                el.classList.toggle('bad', !!(err[el.dataset.n] || warn[el.dataset.n]));
            });
            root.querySelectorAll('[data-show]').forEach((el) => { el.hidden = !store.cond(el.dataset.show); });
            renderFoot();
        };
        store.cond = () => true;

        // Stage values: {path: value, …}. `redraw` repaints the whole window.
        store.stage = function (changes, redraw) {
            if (readonly || saving) return;
            Object.keys(changes).forEach((p) => { setP(S, p, changes[p]); delete err[p]; delete warn[p]; });
            done = false;
            fail = '';
            if (redraw) store.draw(); else store.paint();
        };
        store.setField = (path, value, redraw) => store.stage({ [path]: value }, redraw);

        async function save() {
            const paths = store.pending();
            if (readonly || saving || !paths.length) return;
            const bad = Object.keys(err);
            if (bad.length) {
                const el = root.querySelector(`[data-n="${bad[0]}"]`);
                if (el) el.focus();
                return;
            }
            const body = {};
            paths.forEach((p) => setP(body, p, getP(S, p)));
            saving = true;
            fail = '';
            win.setBusy(true);
            renderFoot();
            try {
                await putSettings(ctx, body);
                base = JSON.parse(json(S));
                done = true;
                clearTimeout(doneTimer);
                doneTimer = setTimeout(() => { done = false; if (root.isConnected) store.paint(); }, 2000);
                ctx.refreshSide();
                ctx.refreshStatus();
            } catch (e) {
                fail = e.message || 'Couldn\'t save.';
            }
            saving = false;
            win.setBusy(false);
            if (root.isConnected) store.draw();
        }

        // ── Unsaved-changes confirm (x, Escape, backdrop) ──
        function hideConfirm() {
            if (confirmEl) { confirmEl.remove(); confirmEl = null; }
        }
        function showConfirm() {
            const el = document.createElement('div');
            el.className = 'ids-ws-confirm';
            el.innerHTML = '<div class="ids-ws-confirm-box" role="alertdialog" aria-label="Unsaved changes">' +
                '<b>Discard unsaved changes?</b><p>They will be lost.</p>' +
                '<div class="ids-ws-confirm-btns"><button type="button" class="ids-btn" data-cf="keep">Keep editing</button>' +
                '<button type="button" class="ids-btn ids-btn-danger" data-cf="drop">Discard changes</button></div></div>';
            el.addEventListener('click', (ev) => {
                const b = ev.target.closest('[data-cf]');
                if (!b) return;
                hideConfirm();
                if (b.dataset.cf === 'drop') win.close(true);
            });
            win.card.style.position = 'relative';
            win.card.appendChild(el);
            confirmEl = el;
            el.querySelector('[data-cf="keep"]').focus();
        }
        win.foot.addEventListener('click', (ev) => {
            const b = ev.target.closest('[data-foot]');
            if (!b || b.disabled) return;
            if (b.dataset.foot === 'close') win.close(true); else save();
        });
        if (win.isDirty) win.isDirty(() => saving || store.pending().length > 0);
        win.beforeClose(() => {
            if (saving) return false;
            if (confirmEl) { hideConfirm(); return false; }
            if (!store.pending().length) return true;
            showConfirm();
            return false;
        });

        // A number field: typing warns only for a character that can never be valid;
        // leaving the field runs the full check and saves when the value really changed.
        store.typing = function (el) {
            const k = el.dataset.n;
            const bad = el.value.match(/[^\d,]/);
            delete err[k];
            if (bad) warn[k] = `"${bad[0]}" not allowed.`; else delete warn[k];
            store.paint();
        };

        store.commitNumber = function (el, lo, hi) {
            const k = el.dataset.n;
            const raw = el.value.replace(/,/g, '').trim();
            delete warn[k];
            if (!/^\d+$/.test(raw) || +raw < lo || +raw > hi) {
                err[k] = `Use ${fmt(lo)} to ${fmt(hi)}.`;
                store.paint();
                return;
            }
            delete err[k];
            el.value = fmt(+raw);
            if (+raw !== store.get(k)) store.setField(k, +raw, false); else store.paint();
        };

        // ── (i) bubbles: open after a pause, pin on click, stay while text is selected ──
        function setTip(k) {
            tip = k;
            root.querySelectorAll('.ids-ws-tip').forEach((t) => {
                const open = t.dataset.tk === k;
                t.classList.toggle('open', open);
                t.querySelector('.ids-ws-ib').setAttribute('aria-expanded', String(open));
            });
        }

        root.addEventListener('click', (ev) => {
            const b = ev.target.closest('[data-tip]');
            if (!b) return;
            clearTimeout(tipTimer);
            const k = b.dataset.tip;
            if (pinned && tip === k) { pinned = false; setTip(null); } else { pinned = true; setTip(k); }
        });
        root.addEventListener('mouseover', (ev) => {
            const b = ev.target.closest('[data-tip]');
            if (!b || pinned || tip === b.dataset.tip) return;
            clearTimeout(tipTimer);
            tipTimer = setTimeout(() => { if (!pinned) setTip(b.dataset.tip); }, 450);
        });
        root.addEventListener('mouseout', (ev) => {
            const b = ev.target.closest('[data-tip]');
            if (!b || (ev.relatedTarget && b.contains(ev.relatedTarget))) return;
            clearTimeout(tipTimer);
            if (!pinned && tip) setTip(null);
        });
        let downInBub = false;
        function outside(ev) {
            if (!root.isConnected) {
                document.removeEventListener('click', outside, true);
                document.removeEventListener('mousedown', down, true);
                document.removeEventListener('keydown', esc2, true);
                return;
            }
            const sel = window.getSelection();
            const node = sel && !sel.isCollapsed && sel.anchorNode
                ? (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement) : null;
            const selecting = downInBub || (node && node.closest && node.closest('.ids-ws-bub'));
            downInBub = false;
            if (selecting || !tip) return;
            const t = ev.target.closest && ev.target.closest('.ids-ws-tip');
            if (t && root.contains(t) && t.dataset.tk === tip) return;
            pinned = false;
            setTip(null);
        }
        function down(ev) { downInBub = !!(ev.target.closest && ev.target.closest('.ids-ws-bub')); }
        function esc2(ev) {
            if (ev.key === 'Escape' && tip) { pinned = false; setTip(null); ev.stopPropagation(); }
        }
        document.addEventListener('click', outside, true);
        document.addEventListener('mousedown', down, true);
        document.addEventListener('keydown', esc2, true);

        // ── Shared input wiring ──
        root.addEventListener('input', (ev) => { if (ev.target.dataset.n && ev.target.type !== 'time') store.typing(ev.target); });
        root.addEventListener('click', (ev) => {
            const r = ev.target.closest('[data-reset]');
            if (!r || readonly) return;
            const p = r.dataset.reset;
            delete err[p];
            delete warn[p];
            store.setField(p, store.def(p), true);
        });

        // The bubble wording's host row clips nothing: mark the paragraph that holds it.
        store.tipHtml = tipHtml;
        return store;
    }

    function numBox(path, value, unit, label, off) {
        return `<label class="ids-ws-ig"><input class="ids-ws-num" data-n="${path}" data-fk="n:${path}" inputmode="numeric" ` +
            `autocomplete="off" spellcheck="false" value="${esc(fmt(value))}" aria-label="${esc(label)}"${off ? ' disabled' : ''}>` +
            `${unit ? `<span class="ids-ws-un">${unit}</span>` : ''}</label>`;
    }

    // One settings row: label + description left, status, control, message line.
    function rowHtml(path, label, desc, control, noReset, extra) {
        return `<div class="ids-ws-row"><div class="ids-ws-lt"><div class="ids-ws-l">${esc(label)}${extra || ''}` +
            `<span class="ids-ws-dot" data-dot="${path}" title="Changed from default" hidden></span></div>` +
            `<div class="ids-ws-d">${esc(desc)}</div></div>` +
            `<span class="ids-ws-stt" data-st="${path}"${noReset ? ' data-noreset="1"' : ''}></span>` +
            `<span class="ids-ws-fv">${control}</span><div class="ids-ws-msg" data-msg="${path}" hidden></div></div>`;
    }

    async function loadDoc(ctx, win) {
        win.body.innerHTML = '<div class="ids-win-msg">' + IdsIcon('circle-notch', {spin: true}) + ' Loading…</div>';
        try {
            return await ctx.api.settings(ctx.peerId);
        } catch (e) {
            win.body.innerHTML = '<div class="ids-win-msg">Couldn\'t load.</div>';
            return null;
        }
    }

    // ── Window: Detection ──────────────────────────────────────────────────────
    async function openDetection(ctx, win) {
        const doc = await loadDoc(ctx, win);
        if (!doc) return;
        const root = document.createElement('div');
        root.className = 'ids-ws';
        win.body.innerHTML = '';
        win.body.appendChild(root);
        const view = { tab: 'basic', open: false };
        const tracked = [];
        const store = createStore(ctx, win, doc, root, draw, tracked);
        const off = store.readonly;

        // Group names from the peer, in the design's order; unknown names go last.
        const optGroups = (store.O['rules.rule_groups'] || []).map((g) => g.name);
        const names = optGroups.length ? optGroups : GROUP_ORDER;
        const ordered = GROUP_ORDER.filter((n) => names.includes(n)).concat(names.filter((n) => !GROUP_ORDER.includes(n)));
        const optMeta = {};
        (store.O['rules.rule_groups'] || []).forEach((g) => { optMeta[g.name] = g; });
        const isAdv = (n) => (optMeta[n] ? !!optMeta[n].advanced : n === 'protocol_anomalies');
        const basic = ordered.filter((n) => !isAdv(n));
        const adv = ordered.filter(isAdv);
        const feedNames = (store.O['rules.rule_feeds'] || []).map((f) => f.name);
        const feeds = feedNames.length ? feedNames : Object.keys(FEEDS);
        ordered.forEach((n) => tracked.push(P_GROUP(n)));
        feeds.forEach((f) => tracked.push(P_FEED(f)));
        tracked.push(P_SEV, P_REPEAT, P_TIME);
        const meta = (n) => GROUPS[n] || [(optMeta[n] && optMeta[n].label) || n, ''];

        function level() {
            const on = basic.filter((n) => store.get(P_GROUP(n))).sort().join();
            for (const k of Object.keys(LEVELS)) {
                if (LEVELS[k].filter((n) => basic.includes(n)).sort().join() === on) return k;
            }
            return 'custom';
        }

        const groupRow = (n) => rowHtml(P_GROUP(n), meta(n)[0], meta(n)[1], switchHtml(P_GROUP(n), store.get(P_GROUP(n)), off, meta(n)[0]),
            false, n === 'info' ? tipHtml('info', TIP_INFO) : '');

        function drawBasic() {
            const lv = level();
            const stt = store.anyPending(basic.map(P_GROUP)) ? '<span class="ids-ws-badge">Not saved</span>' : '';
            const keys = ['essential', 'recommended', 'strict'].concat(lv === 'custom' ? ['custom'] : []);
            const defLevel = (() => {
                const on = basic.filter((n) => store.def(P_GROUP(n))).sort().join();
                return Object.keys(LEVELS).find((k) => LEVELS[k].filter((n) => basic.includes(n)).sort().join() === on);
            })();
            const presets = keys.map((k) => presetRow({
                attr: `data-lv="${k}"`, fk: `lv:${k}`, on: lv === k, name: LEVEL_NAME[k], def: k === defLevel,
                text: LEVEL_TEXT[k], stt: lv === k ? stt : '', dis: off || k === 'custom',
            })).join('');
            const n = basic.filter((g) => store.get(P_GROUP(g))).length;
            let h = '<section class="ids-sec"><h3 class="ids-sec-h">Level</h3>' +
                '<p class="ids-sec-help">How much to look for. Each level turns a set of threat kinds on or off.</p>' +
                `<div class="ids-sec-body"><div class="ids-ws-pre" role="radiogroup" aria-label="Level">${presets}</div>` +
                `<button type="button" class="ids-ws-drop${view.open ? ' open' : ''}" data-fk="drop" data-drop="1" aria-expanded="${view.open}">` +
                '' + IdsIcon('list-check') + 'What to look for' +
                `<span class="ids-ws-dc">${n} of ${basic.length} on ${IdsIcon('chevron-' + (view.open ? 'up' : 'down'))}</span></button>`;
            if (view.open) h += `<div class="ids-ws-dropbody">${basic.map(groupRow).join('')}</div>`;
            h += '</div></section>';

            const sevStt = store.isPending(P_SEV) ? '<span class="ids-ws-badge">Not saved</span>' : '';
            const curSev = store.get(P_SEV);
            const defSev = store.def(P_SEV);
            const recs = RECORD.map(([k, l, d]) => presetRow({
                attr: `data-sev="${k}"`, fk: `sev:${k}`, on: curSev === k, name: l, def: k === defSev, text: d,
                stt: curSev === k ? sevStt : '', dis: off,
            })).join('');
            h += '<section class="ids-sec"><h3 class="ids-sec-h">Record' +
                `<span data-st="${P_SEV}" data-resetonly="1" class="ids-ws-hreset"></span></h3>` +
                `<p class="ids-sec-help ids-ws-rel">Which threats are recorded.${tipHtml('record', TIP_RECORD)}</p>` +
                `<div class="ids-sec-body"><div class="ids-ws-pre" role="radiogroup" aria-label="Record">${recs}</div></div></section>`;
            return h;
        }

        function drawAdvanced() {
            let h = '';
            if (adv.length) h += `<section class="ids-sec ids-ws-solo"><div class="ids-sec-body">${adv.map(groupRow).join('')}</div></section>`;
            h += '<section class="ids-sec"><h3 class="ids-sec-h">Extra rule feeds</h3>' +
                '<p class="ids-sec-help">Extra lists of known threats. Turning one on downloads its rules (1–2 min).</p>' +
                `<div class="ids-sec-body">${feeds.map((f) => {
                    const m = FEEDS[f] || [f, ''];
                    const o = (store.O['rules.rule_feeds'] || []).find((x) => x.name === f);
                    return rowHtml(P_FEED(f), (o && o.label) || m[0], m[1], switchHtml(P_FEED(f), store.get(P_FEED(f)), off, m[0]));
                }).join('')}</div></section>`;
            const [lo, hi] = bounds(store.O[P_REPEAT], 10, 600);
            h += '<section class="ids-sec"><h3 class="ids-sec-h">Timing</h3>' +
                '<p class="ids-sec-help">How repeats are grouped, and when rules update.</p><div class="ids-sec-body">' +
                rowHtml(P_REPEAT, 'Group repeats within', `Same threat again in this time adds to one row. ${lo} to ${hi} seconds.`,
                    numBox(P_REPEAT, store.get(P_REPEAT), 's', 'Group repeats within', off)) +
                rowHtml(P_TIME, 'Daily rules update', 'Device local time.',
                    `<input class="ids-ws-time" type="time" data-n="${P_TIME}" data-fk="t:${P_TIME}" value="${esc(store.get(P_TIME) || '')}" ` +
                    `aria-label="Daily rules update"${off ? ' disabled' : ''}>`) + '</div></section>';
            return h;
        }

        function draw() {
            root.innerHTML =
                `<div class="ids-ws-tabs" role="tablist"><button type="button" role="tab" data-tab="basic" data-fk="tab:basic" class="${view.tab === 'basic' ? 'on' : ''}">Basic</button>` +
                `<button type="button" role="tab" data-tab="adv" data-fk="tab:adv" class="${view.tab === 'adv' ? 'on' : ''}">Advanced</button></div>` +
                (view.tab === 'basic' ? drawBasic() : drawAdvanced());
            store.paint();
        }

        root.addEventListener('click', (ev) => {
            const b = ev.target.closest('button');
            if (!b || b.disabled) return;
            if (b.dataset.tab) { view.tab = b.dataset.tab; draw(); return; }
            if (b.dataset.drop) { view.open = !view.open; draw(); return; }
            if (b.dataset.sev) { store.setField(P_SEV, b.dataset.sev, true); return; }
            if (b.dataset.lv && LEVELS[b.dataset.lv]) {
                const changes = {};
                basic.forEach((n) => { changes[P_GROUP(n)] = LEVELS[b.dataset.lv].includes(n); });
                store.stage(changes, true);
            }
        });
        root.addEventListener('change', (ev) => {
            const el = ev.target;
            if (el.dataset.sw) { store.setField(el.dataset.sw, el.checked, !el.dataset.sw.startsWith('rules.rule_feeds')); return; }
            if (el.dataset.n === P_REPEAT) {
                const [lo, hi] = bounds(store.O[P_REPEAT], 10, 600);
                store.commitNumber(el, lo, hi);
            } else if (el.dataset.n === P_TIME) {
                if (/^\d{2}:\d{2}$/.test(el.value)) { delete store.err[P_TIME]; store.setField(P_TIME, el.value, false); } else { store.err[P_TIME] = 'Enter a time.'; store.paint(); }
            }
        });
        root.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter' && ev.target.dataset.n === P_REPEAT) ev.target.blur();
        });
        // Leaving a number field with a typing warning runs the full check.
        root.addEventListener('focusout', (ev) => {
            if (ev.target.dataset.n === P_REPEAT && store.warn[P_REPEAT]) {
                const [lo, hi] = bounds(store.O[P_REPEAT], 10, 600);
                store.commitNumber(ev.target, lo, hi);
            }
        });
        draw();
    }

    // A radio-style row (Level and Record): name + description left, status right.
    function presetRow(o) {
        return `<button type="button" role="radio" aria-checked="${o.on}" ${o.attr} data-fk="${o.fk}" ` +
            `class="ids-ws-pi${o.on ? ' on' : ''}${o.name === 'Custom' ? ' cu' : ''}"${o.dis ? ' disabled' : ''}>` +
            '<span class="ids-ws-rd"></span><span class="ids-ws-pt"><span class="ids-ws-pn">' + esc(o.name) + '</span>' +
            (o.def ? ' <span class="ids-ws-tag">Default</span>' : '') +
            `<span class="ids-ws-d">${esc(o.text)}</span></span>` +
            `<span class="ids-ws-pstt">${o.stt}</span></button>`;
    }

    // ── Window: Threat recording ───────────────────────────────────────────────
    async function openRecording(ctx, win) {
        const doc = await loadDoc(ctx, win);
        if (!doc) return;
        const root = document.createElement('div');
        root.className = 'ids-ws';
        win.body.innerHTML = '';
        win.body.appendChild(root);
        const tracked = ['retention_days', 'retention_max_rows', 'retention_max_mb', 'http_details'].map((k) => `events.${k}`);
        const store = createStore(ctx, win, doc, root, draw, tracked);
        const off = store.readonly;
        const E = (k) => `events.${k}`;
        const LIM = {
            [E('retention_days')]: bounds(store.O['events.retention_days'], 1, 90),
            [E('retention_max_rows')]: bounds(store.O['events.retention_max_rows'], 10000, 5000000),
            [E('retention_max_mb')]: bounds(store.O['events.retention_max_mb'], 50, 4000),
        };
        const mbMax = LIM[E('retention_max_mb')][1];
        store.cond = (what) => {
            if (what !== 'raised') return true;
            return store.get(E('retention_max_rows')) > store.def(E('retention_max_rows')) ||
                store.get(E('retention_max_mb')) > store.def(E('retention_max_mb'));
        };

        function draw() {
            const num = (k, label, desc, unit) => rowHtml(E(k), label, desc, numBox(E(k), store.get(E(k)), unit, label, off));
            root.innerHTML =
                '<section class="ids-sec"><h3 class="ids-sec-h">Keep</h3>' +
                `<p class="ids-sec-help ids-ws-rel">How long threats are kept, and how many.${tipHtml('keep', TIP_KEEP)}</p><div class="ids-sec-body">` +
                num('retention_days', 'Days', 'Older threats are removed.', 'days') +
                num('retention_max_rows', 'Threats', 'The most kept at once.', '') +
                num('retention_max_mb', 'Disk space', `Up to ${fmt(mbMax)} MB on this device.`, 'MB') +
                '<div class="ids-ws-warnbox" data-show="raised" hidden>' + IdsIcon('triangle-exclamation') + '' +
                '<span>Higher limits use more of the router\'s disk.</span></div></div></section>' +
                '<section class="ids-sec"><h3 class="ids-sec-h">Details</h3>' +
                '<p class="ids-sec-help">What each threat keeps besides the site name.</p><div class="ids-sec-body">' +
                rowHtml(E('http_details'), 'Full address and browser', 'Addresses can hold personal data.',
                    switchHtml(E('http_details'), store.get(E('http_details')), off, 'Full address and browser'), true,
                    tipHtml('http', TIP_HTTP)) + '</div></section>';
            store.paint();
        }

        root.addEventListener('change', (ev) => {
            const el = ev.target;
            if (el.dataset.sw) { store.setField(el.dataset.sw, el.checked, false); return; }
            const lim = LIM[el.dataset.n];
            if (lim) store.commitNumber(el, lim[0], lim[1]);
        });
        root.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter' && LIM[ev.target.dataset.n]) ev.target.blur();
        });
        root.addEventListener('focusout', (ev) => {
            const lim = LIM[ev.target.dataset.n];
            if (lim && store.warn[ev.target.dataset.n]) store.commitNumber(ev.target, lim[0], lim[1]);
        });
        draw();
    }

    window.IdsWin.register('detection', { title: 'Detection', icon: 'sliders', open: openDetection });
    window.IdsWin.register('recording', { title: 'Threat recording', icon: 'box-archive', open: openRecording });
})();
