/**
 * IDS page windows: Inspection and Performance (staged save).
 *
 * Both windows collect changes and write them with one "Save changes":
 *   PUT /ids/settings with only the changed fields, then refreshSide() + refreshStatus().
 * Values and bounds come from GET /ids/settings (settings, defaults, options); nothing is hard-coded
 * except the display names of the protocols.
 *
 * A small engine (mount) owns what both windows share: loading, tabs, (i) bubbles, number fields,
 * the footer, the save call and the "unsaved changes" confirm on close. Each window is a spec.
 */
(function () {
    const N = window.NkIds;
    const esc = N.esc;
    const fmt = (n) => Number(n).toLocaleString('en-US');
    const clone = (v) => JSON.parse(JSON.stringify(v));

    /* ---------- API ---------- */

    async function putSettings(peerId, body) {
        let res;
        try {
            res = await fetch(`/api/v2/client/peers/${encodeURIComponent(peerId)}/ids/settings`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
        } catch (e) {
            throw new Error('Network error.');
        }
        let data = null;
        try { data = await res.json(); } catch (e) { /* empty body */ }
        if (!res.ok) {
            const msg = data && (typeof data.detail === 'string' ? data.detail : typeof data.message === 'string' ? data.message : '');
            throw new Error(msg || 'Request failed.');
        }
        return data;
    }

    /* ---------- small html pieces ---------- */

    function tip(w, k, text) {
        const open = w.tip === k;
        return `<span class="ids-wt-tip${open ? ' ids-wt-open' : ''}" data-k="${k}">` +
            `<button type="button" class="ids-wt-ib" data-tip="${k}" aria-label="More about this" aria-expanded="${open}">${IdsIcon('circle-info')}</button>` +
            `<span class="ids-wt-bub" role="tooltip">${esc(text)}</span></span>`;
    }

    function section(title, help, inner, tipHtml) {
        return `<section class="ids-sec"><div class="ids-sec-h">${esc(title)}</div>` +
            `<p class="ids-sec-help">${esc(help)}${tipHtml || ''}</p><div class="ids-sec-body">${inner}</div></section>`;
    }

    const stt = (k, undo) => `<span class="ids-wt-stt" data-st="${k}"${undo ? ' data-undo="1"' : ''}></span>`;
    const dot = (k) => `<span class="ids-wt-cdot" data-dot="${k}" title="Changed from default" hidden></span>`;

    function sw(w, arg, on, label) {
        return `<button type="button" class="ids-wt-sw${on ? ' ids-wt-on' : ''}" data-do="proto" data-arg="${arg}" role="switch" aria-checked="${on}" aria-label="${esc(label)}"${w.ro ? ' disabled' : ''}></button>`;
    }

    function numField(w, k, label, unit, cls) {
        const v = w.spec.numValue(w, k);
        return `<label class="ids-wt-ig ${cls || ''}"><input class="ids-wt-num" data-n="${k}" inputmode="numeric" autocomplete="off" spellcheck="false" ` +
            `value="${fmt(v)}" aria-label="${esc(label)}"${w.ro ? ' disabled' : ''}>${unit ? `<span class="ids-wt-un">${unit}</span>` : ''}</label>`;
    }

    // One radio row: name, optional Default tag, description, optional extra line.
    function choice(w, doVerb, arg, on, name, desc, o) {
        o = o || {};
        const off = !!o.off;
        return `<div class="ids-wt-pi${on ? ' ids-wt-sel' : ''}${off ? ' ids-wt-offrow' : ''}" role="radio" aria-checked="${on}" aria-disabled="${off || w.ro}" ` +
            `tabindex="${off || w.ro ? -1 : 0}" data-do="${doVerb}" data-arg="${arg}"><span class="ids-wt-rd"></span>` +
            `<span class="ids-wt-pi-t"><span class="ids-wt-n">${esc(name)}</span>` +
            (o.isDefault ? ' <span class="ids-wt-tag">Default</span>' : '') +
            `<br><span class="ids-wt-d">${esc(desc)}</span>` +
            (o.why ? `<span class="ids-wt-why">${esc(o.why)}</span>` : '') + '</span>' +
            (on && o.stt ? stt(o.stt, false) : '<span class="ids-wt-stt"></span>') + '</div>';
    }

    /* ---------- the engine ---------- */

    function footStatus(w, n) {
        let status;
        if (w.saving) status = '<b>' + IdsIcon('circle-notch', {spin: true}) + ' Saving.</b><small>Takes under a minute.</small>';
        else if (w.done) status = '<span class="ids-wt-ok">' + IdsIcon('check') + ' Saved.</span>';
        else if (n) status = `<b>${n} unsaved ${n === 1 ? 'change' : 'changes'}.</b><small>Changes take effect in under a minute.</small>`;
        else status = '';
        if (w.fail && !w.saving) status += `<span class="ids-wt-fail">${IdsIcon('circle-exclamation')} ${esc(w.fail)}</span>`;
        return status;
    }

    function pendingCount(w) {
        return w.saved ? w.spec.pending(w).length : 0;
    }

    // The buttons are built once and only updated: a blur that repaints must not swallow the click on Save.
    function renderFoot(w, loading) {
        const foot = w.win.foot, n = pendingCount(w);
        if (!foot.querySelector('[data-foot]')) {
            foot.innerHTML = '<div class="ids-foot-status"></div><div class="ids-foot-btns">' +
                '<button type="button" class="ids-btn" data-foot="discard">Close</button>' +
                '<button type="button" class="ids-btn ids-btn-primary" data-foot="apply">' + IdsIcon('floppy-disk') + ' Save changes</button></div>';
        }
        const html = footStatus(w, n);
        const st = foot.querySelector('.ids-foot-status');
        if (st.innerHTML !== html) st.innerHTML = html;
        const off = loading || w.saving || w.done || !n || w.ro;
        foot.querySelectorAll('[data-foot]').forEach((b) => { b.disabled = b.dataset.foot === 'discard' ? false : off; });
    }

    function tabsHtml(w) {
        return '<div class="ids-wt-tabs" role="tablist">' + w.spec.tabs.map(([id, label]) =>
            `<button type="button" role="tab" data-tab="${id}" aria-selected="${w.tab === id}" class="${w.tab === id ? 'ids-wt-on' : ''}">${label}</button>`).join('') + '</div>';
    }

    function draw(w) {
        const top = w.win.body.scrollTop;
        w.root.innerHTML = tabsHtml(w) + `<div class="ids-wt-pane">${w.spec.render(w)}</div>`;
        paint(w);
        w.win.body.scrollTop = top;
    }

    function paint(w) {
        const pend = w.spec.pending(w);
        w.root.querySelectorAll('[data-st]').forEach((el) => {
            const k = el.dataset.st;
            if (pend.includes(k)) {
                el.innerHTML = '<span class="ids-wt-badge">Not saved</span>' + (el.dataset.undo && !w.ro
                    ? `<button type="button" class="ids-wt-undo" data-do="undo" data-arg="${k}" title="Undo" aria-label="Undo">${IdsIcon('rotate-left')}</button>` : '');
            } else {
                el.innerHTML = w.ro ? '' : w.spec.idle(w, k);
            }
        });
        w.root.querySelectorAll('[data-dot]').forEach((el) => { el.hidden = !w.spec.isCustom(w, el.dataset.dot); });
        w.root.querySelectorAll('[data-msg]').forEach((el) => {
            const k = el.dataset.msg, e = w.err[k], a = w.warn[k];
            el.hidden = !(e || a);
            el.classList.toggle('ids-wt-amber', !e && !!a);
            el.innerHTML = e ? `${IdsIcon('circle-exclamation')}${esc(e)}`
                : a ? `${IdsIcon('triangle-exclamation')}${esc(a)}` : '';
        });
        w.root.querySelectorAll('[data-n]').forEach((el) => {
            el.classList.toggle('ids-wt-bad', !!(w.err[el.dataset.n] || w.warn[el.dataset.n]));
        });
        renderFoot(w);
    }

    function touch(w, redraw) {
        w.done = false;
        w.fail = '';
        if (redraw) draw(w); else paint(w);
    }

    function setTip(w, k) {
        w.tip = k;
        w.root.querySelectorAll('.ids-wt-tip').forEach((t) => {
            const on = t.dataset.k === k;
            t.classList.toggle('ids-wt-open', on);
            t.querySelector('.ids-wt-ib').setAttribute('aria-expanded', String(on));
        });
    }

    // Number fields: no error while typing (only an amber note for a character that is never valid).
    function onType(w, el) {
        const k = el.dataset.n, bad = el.value.match(/[^\d,]/);
        delete w.err[k];
        if (bad) w.warn[k] = `"${bad[0]}" not allowed.`; else delete w.warn[k];
        paint(w);
    }

    function commit(w, el) {
        const k = el.dataset.n, raw = el.value.replace(/,/g, '').trim();
        const [lo, hi] = w.spec.bounds(w, k);
        delete w.warn[k];
        if (!/^\d+$/.test(raw) || +raw < lo || +raw > hi) {
            w.err[k] = `Use ${fmt(lo)} to ${fmt(hi)}.`;
            paint(w);
            return;
        }
        delete w.err[k];
        const n = +raw;
        if (n !== w.spec.numValue(w, k)) w.spec.setNum(w, k, n);
        el.value = fmt(w.spec.numValue(w, k));
        touch(w, false);
    }

    function discard(w) {
        w.draft = clone(w.saved);
        w.err = {};
        w.warn = {};
        touch(w, true);
    }

    async function save(w) {
        if (w.ro || w.saving || !pendingCount(w)) return;
        const bad = Object.keys(w.err);
        if (bad.length) {
            const el = w.root.querySelector(`[data-n="${bad[0]}"]`);
            if (el) el.focus();
            return;
        }
        const body = w.spec.payload(w);
        w.saving = true;
        w.fail = '';
        w.win.setBusy(true);
        renderFoot(w);
        try {
            await putSettings(w.ctx.peerId, body);
            try {
                w.spec.init(w, await w.ctx.api.settings(w.ctx.peerId));
            } catch (e) {
                w.saved = clone(w.draft); // saved, but could not re-read: keep what was sent
            }
            w.err = {};
            w.warn = {};
            w.done = true;
            clearTimeout(w.doneTimer);
            w.doneTimer = setTimeout(() => { w.done = false; if (w.root.isConnected) renderFoot(w); }, 2000);
            w.ctx.refreshSide();
            w.ctx.refreshStatus();
        } catch (e) {
            w.fail = e.message || 'Couldn\'t save.';
        }
        w.saving = false;
        w.win.setBusy(false);
        if (w.root.isConnected) draw(w);
    }

    /* ---- close guard: a small confirm inside the window ---- */

    function hideConfirm(w) {
        if (w.confirmEl) { w.confirmEl.remove(); w.confirmEl = null; }
    }

    function showConfirm(w) {
        const el = document.createElement('div');
        el.className = 'ids-wt-confirm';
        el.innerHTML = '<div class="ids-wt-confirm-box" role="alertdialog" aria-label="Unsaved changes">' +
            '<b>Discard unsaved changes?</b><p>They will be lost.</p>' +
            '<div class="ids-wt-confirm-btns"><button type="button" class="ids-btn" data-cf="keep">Keep editing</button>' +
            '<button type="button" class="ids-btn ids-btn-danger" data-cf="drop">Discard changes</button></div></div>';
        el.addEventListener('click', (ev) => {
            const b = ev.target.closest('[data-cf]');
            if (!b) return;
            if (b.dataset.cf === 'keep') hideConfirm(w);
            else { hideConfirm(w); w.win.close(true); }
        });
        w.win.card.style.position = 'relative';
        w.win.card.appendChild(el);
        w.confirmEl = el;
        const keep = el.querySelector('[data-cf="keep"]');
        if (keep) keep.focus();
    }

    function bind(w) {
        const R = w.root;
        R.addEventListener('click', (e) => {
            if (e.target.closest('input')) return;
            const t = e.target.closest('[data-tip],[data-tab],[data-do]');
            if (!t || t.disabled) return;
            const d = t.dataset;
            if (d.tip) {
                clearTimeout(w.timer);
                if (w.pin && w.tip === d.tip) { w.pin = false; setTip(w, null); } else { w.pin = true; setTip(w, d.tip); }
                return;
            }
            if (d.tab) {
                if (w.tab !== d.tab) { w.tab = d.tab; draw(w); }
                return;
            }
            if (w.ro || t.getAttribute('aria-disabled') === 'true') return;
            if (w.spec.act(w, d.do, d.arg)) touch(w, true);
        });
        R.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.target.dataset.n) { commit(w, e.target); e.target.blur(); return; }
            if ((e.key === 'Enter' || e.key === ' ') && e.target.getAttribute('role') === 'radio') {
                e.preventDefault();
                e.target.click();
            }
        });
        R.addEventListener('input', (e) => { if (e.target.dataset.n) onType(w, e.target); });
        R.addEventListener('change', (e) => { if (e.target.dataset.n) commit(w, e.target); });
        R.addEventListener('focusout', (e) => { if (e.target.dataset && e.target.dataset.n && R.isConnected) commit(w, e.target); });
        // (i): opens after ~450 ms hover, pins on click.
        R.addEventListener('mouseover', (e) => {
            const b = e.target.closest('.ids-wt-ib');
            if (!b || w.pin || w.tip === b.dataset.tip) return;
            clearTimeout(w.timer);
            w.timer = setTimeout(() => { if (!w.pin) setTip(w, b.dataset.tip); }, 450);
        });
        R.addEventListener('mouseout', (e) => {
            const b = e.target.closest('.ids-wt-ib');
            if (!b || (e.relatedTarget && b.contains(e.relatedTarget))) return;
            clearTimeout(w.timer);
            if (!w.pin && w.tip) setTip(w, null);
        });
        // A pinned bubble stays while its text is being selected; any other click closes it.
        let downInBub = false;
        const onDown = (e) => { downInBub = !!(e.target.closest && e.target.closest('.ids-wt-bub')); };
        const onClick = (e) => {
            if (!R.isConnected) {
                document.removeEventListener('mousedown', onDown, true);
                document.removeEventListener('click', onClick, true);
                return;
            }
            const sel = window.getSelection();
            const node = sel && !sel.isCollapsed && sel.anchorNode
                ? (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement) : null;
            const selecting = downInBub || (node && node.closest('.ids-wt-bub'));
            downInBub = false;
            if (selecting || !w.tip) return;
            const t = e.target.closest('.ids-wt-tip');
            if (t && R.contains(t) && t.dataset.k === w.tip) return;
            w.pin = false;
            setTip(w, null);
        };
        document.addEventListener('mousedown', onDown, true);
        document.addEventListener('click', onClick, true);

        w.win.foot.addEventListener('click', (e) => {
            const b = e.target.closest('[data-foot]');
            if (!b || b.disabled) return;
            if (b.dataset.foot === 'discard') { if (w.saving) return; discard(w); w.win.close(true); } else save(w);
        });
        if (w.win.isDirty) w.win.isDirty(() => w.saving || pendingCount(w) > 0);
        w.win.beforeClose(() => {
            if (w.saving) return false;
            if (w.confirmEl) { hideConfirm(w); return false; }
            if (!pendingCount(w)) return true;
            showConfirm(w);
            return false;
        });
    }

    function mount(ctx, win, spec) {
        const w = {
            ctx, win, spec, root: null, saved: null, draft: null, err: {}, warn: {}, tab: 'basic',
            tip: null, pin: false, timer: null, saving: false, done: false, fail: '', ro: !!ctx.readonly,
            confirmEl: null, doneTimer: null,
        };
        win.body.innerHTML = '<div class="ids-win-msg">Loading…</div>';
        renderFoot(w, true);
        ctx.api.settings(ctx.peerId).then((data) => {
            spec.init(w, data);
            win.body.innerHTML = '<div class="ids-wt"></div>';
            w.root = win.body.firstChild;
            bind(w);
            draw(w);
        }).catch(() => {
            win.body.innerHTML = '<div class="ids-win-msg">Couldn\'t load.</div>';
            win.foot.innerHTML = '';
        });
    }

    /* ---------- Inspection ---------- */

    const PROTO = [
        ['http', 'Web (HTTP)'], ['tls', 'Secure web (TLS)'], ['dns', 'Name lookups (DNS)'], ['smb', 'File sharing (SMB)'],
        ['ssh', 'SSH'], ['ftp', 'File transfer (FTP)'], ['smtp', 'Mail (SMTP)'], ['rdp', 'Remote desktop (RDP)'],
        ['quic', 'QUIC'], ['sip', 'Voice calls (SIP)'],
    ];
    const IND = [['modbus', 'Modbus'], ['dnp3', 'DNP3'], ['enip', 'EtherNet/IP']];
    const ALLP = PROTO.concat(IND);
    const TIP_WAN = 'Normally only the traffic inside your network (LAN) is inspected. This also inspects the traffic on the WAN interfaces, before the firewall. You then see attacks from the internet that the firewall already blocked, so expect many more threats. A threat seen only on a WAN shows that WAN as its place.';
    const TIP_P = 'Each protocol lets the IDS understand one kind of traffic, such as web pages, shared folders or mail, and run the rules written for it. Turning one off saves processor and memory, but every rule for it stops. For example, with File sharing (SMB) off, a worm spreading between your computers over shared folders goes unseen. Turn one off only if your network never uses it.';

    const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

    const inspection = {
        tabs: [['basic', 'Basic'], ['adv', 'Advanced']],

        init(w, data) {
            const s = data.settings || {}, d = data.defaults || {}, o = data.options || {};
            const sc = s.scope || {}, pr = s.protocols || {}, dpr = d.protocols || {};
            const wans = (o['scope.inspected_wans'] || []).map((x) => ({ id: x.wan_id, label: N.placeLabel(x.label) || x.wan_id }));
            const ids = wans.map((x) => x.id);
            const mode = sc.inspect_internet_links;
            const on = mode === 'all' ? ids : mode === 'selected' ? (sc.inspected_wans || []).filter((x) => ids.includes(x)) : [];
            const bo = o['protocols.http_body_limit_kb'] || {};
            w.meta = {
                wans,
                defEnc: (d.scope && d.scope.encrypted_traffic) || 'handshake',
                defBody: dpr.http_body_limit_kb != null ? dpr.http_body_limit_kb : 100,
                defP: Object.fromEntries(ALLP.map(([k]) => [k, dpr[k] != null ? !!dpr[k] : !IND.some(([i]) => i === k)])),
                lo: Math.max(1, Number(bo.min) || 1), // 0 means unlimited on the engine: never offered
                hi: Number(bo.max) > 0 ? Number(bo.max) : 1024,
            };
            w.saved = {
                wans: on,
                enc: sc.encrypted_traffic || w.meta.defEnc,
                body: pr.http_body_limit_kb != null ? Number(pr.http_body_limit_kb) : w.meta.defBody,
                p: Object.fromEntries(ALLP.map(([k]) => [k, pr[k] != null ? !!pr[k] : w.meta.defP[k]])),
            };
            w.draft = clone(w.saved);
        },

        pending(w) {
            const d = w.draft, s = w.saved, out = [];
            w.meta.wans.forEach(({ id }) => { if (d.wans.includes(id) !== s.wans.includes(id)) out.push('wan.' + id); });
            if (d.enc !== s.enc) out.push('enc');
            if (d.body !== s.body) out.push('body');
            ALLP.forEach(([k]) => { if (d.p[k] !== s.p[k]) out.push('p.' + k); });
            return out;
        },

        idle(w, k) {
            return k === 'body' && w.draft.body !== w.meta.defBody ? '<button type="button" class="ids-wt-lnk" data-do="reset" data-arg="body" title="Reset to default" aria-label="Reset to default">Reset</button>' : '';
        },

        isCustom(w, k) {
            if (k === 'body') return w.draft.body !== w.meta.defBody;
            return w.draft.p[k.slice(2)] !== w.meta.defP[k.slice(2)];
        },

        bounds: (w) => [w.meta.lo, w.meta.hi],
        numValue: (w) => w.draft.body,
        setNum(w, k, n) { w.draft.body = n; },

        act(w, verb, arg) {
            const d = w.draft;
            if (verb === 'link') {
                d.wans = d.wans.includes(arg) ? d.wans.filter((x) => x !== arg) : d.wans.concat(arg);
                return true;
            }
            if (verb === 'enc') {
                if (d.enc === arg) return false;
                d.enc = arg;
                return true;
            }
            if (verb === 'proto') { d.p[arg] = !d.p[arg]; return true; }
            if (verb === 'reset') { d.body = w.meta.defBody; delete w.err.body; delete w.warn.body; return true; }
            if (verb === 'undo') { d.body = w.saved.body; delete w.err.body; delete w.warn.body; return true; }
            return false;
        },

        payload(w) {
            const d = w.draft, s = w.saved, out = {}, sc = {}, pr = {};
            if (!sameSet(d.wans, s.wans)) {
                const n = d.wans.length;
                sc.inspect_internet_links = n === 0 ? 'off' : n === w.meta.wans.length ? 'all' : 'selected';
                sc.inspected_wans = sc.inspect_internet_links === 'selected' ? d.wans : [];
            }
            if (d.enc !== s.enc) sc.encrypted_traffic = d.enc;
            ALLP.forEach(([k]) => { if (d.p[k] !== s.p[k]) pr[k] = d.p[k]; });
            if (d.body !== s.body) pr.http_body_limit_kb = d.body;
            if (Object.keys(sc).length) out.scope = sc;
            if (Object.keys(pr).length) out.protocols = pr;
            return out;
        },

        render(w) {
            return w.tab === 'basic' ? inspectionBasic(w) : inspectionAdvanced(w);
        },
    };

    function inspectionBasic(w) {
        const d = w.draft, m = w.meta;
        const links = m.wans.length
            ? m.wans.map(({ id, label }) => {
                const on = d.wans.includes(id);
                return `<div class="ids-wt-ckrow"><button type="button" class="ids-wt-ck${on ? ' ids-wt-on' : ''}" data-do="link" data-arg="${esc(id)}" role="checkbox" aria-checked="${on}"${w.ro ? ' disabled' : ''}>` +
                    `<span class="ids-wt-box">${IdsIcon('check')}</span>${esc(label)}</button>${stt('wan.' + id, false)}</div>`;
            }).join('')
            : '<p class="ids-wt-none">No WAN interfaces on this device.</p>';
        const enc = [['handshake', 'Handshake only', 'Checks who each encrypted connection is with.'],
            ['full', 'Whole connection', 'Keeps following it after the handshake. Uses more processor.']];
        return section('WAN interfaces', 'Tick the ones to inspect too. None ticked means only your network is inspected.',
            `<div role="group" aria-label="WAN interfaces">${links}</div>`, tip(w, 'wan', TIP_WAN)) +
            section('Encrypted traffic', 'How far encrypted connections are followed.',
                '<div class="ids-wt-pre" role="radiogroup" aria-label="Encrypted traffic">' +
                enc.map(([v, n, desc]) => choice(w, 'enc', v, d.enc === v, n, desc, { isDefault: v === m.defEnc, stt: 'enc' })).join('') + '</div>');
    }

    function protoRow(w, k, label) {
        const on = w.draft.p[k];
        return `<div class="ids-wt-row${on ? '' : ' ids-wt-offlbl'}"><div class="ids-wt-lt"><div class="ids-wt-l">${esc(label)}${dot('p.' + k)}</div></div>` +
            `${stt('p.' + k, false)}${sw(w, k, on, label)}</div>`;
    }

    function inspectionAdvanced(w) {
        const rows = (list) => `<div class="ids-wt-cols">${list.map(([k, l]) => protoRow(w, k, l)).join('')}</div>`;
        const body = `<div class="ids-wt-row"><div class="ids-wt-lt"><div class="ids-wt-l">Web check size${dot('body')}</div>` +
            '<div class="ids-wt-d">How much of each web page or upload is checked.</div></div>' +
            `${stt('body', true)}<span class="ids-wt-fv">${numField(w, 'body', 'Web check size', 'KB', 'ids-wt-ig-c')}</span>` +
            '<div class="ids-wt-msg" data-msg="body" hidden></div></div>';
        return section('Protocols', 'Turning one off stops every rule for it.', rows(PROTO), tip(w, 'p', TIP_P)) +
            section('Industrial', 'For factories and plants only.', rows(IND)) +
            section('Limits', 'How much is checked in each connection.', body);
    }

    /* ---------- Performance ---------- */

    const LV = ['low', 'medium', 'high'];
    const LVN = { low: 'Low', medium: 'Medium', high: 'High' };
    const PN = { light: 'Light', balanced: 'Balanced', thorough: 'Thorough' };
    const PD = {
        light: 'Least memory and processor. For small devices.',
        balanced: 'Best for most networks.',
        thorough: 'Inspects deeper and checks faster.',
    };
    const KEYS = ['mem', 'cores', 'depth', 'lvl'];
    const FIELD = { mem: 'memory_limit_mb', cores: 'worker_threads', depth: 'stream_depth_mb', lvl: 'detection_profile' };
    const NAME = { mem: 'Memory', cores: 'Processor cores', depth: 'Inspection depth', lvl: 'Rule matching' };
    const DESC = {
        mem: 'The most the inspection may use.',
        cores: 'Cores that inspect traffic.',
        depth: 'How much of each connection is inspected.',
        lvl: 'Higher checks faster but uses more memory.',
    };
    const UNIT = { mem: 'MB', cores: '', depth: 'MB' };
    const TIP_PERF = 'A profile is a ceiling. The limits can only lower what it uses, never raise it.';
    const REASONS = { needs_8gb_memory: 'Needs 8 GB of memory.' };

    const gb = (mb) => (mb / 1024).toFixed(1).replace(/\.0$/, '') + ' GB';
    const cmpv = (k, a, b) => (k === 'lvl' ? LV.indexOf(a) - LV.indexOf(b) : a - b);
    const top = (w, k, p) => w.meta.P[p || w.draft.profile][k];

    // Effective value: a stored (lowered) value wins, never above the profile.
    function eff(w, st, k) {
        const t = top(w, k, st.profile), s = st.stored[k];
        return s == null || cmpv(k, s, t) > 0 ? t : s;
    }

    function setProfile(w, p) {
        const st = w.draft;
        st.profile = p;
        Object.keys(st.stored).forEach((k) => { if (cmpv(k, st.stored[k], top(w, k, p)) >= 0) delete st.stored[k]; });
    }

    function setVal(w, k, v) {
        const st = w.draft;
        if (cmpv(k, v, top(w, k)) >= 0) delete st.stored[k]; else st.stored[k] = v;
    }

    const showDepth = (w) => top(w, 'depth') > 1;

    const performance = {
        tabs: [['basic', 'Basic'], ['adv', 'Advanced']],

        init(w, data) {
            const s = (data.settings && data.settings.performance) || {};
            const o = data.options || {};
            const list = o['performance.profile'] || [];
            const P = {};
            list.forEach((it) => {
                const l = it.limits || {};
                P[it.value] = {
                    mem: l.memory_limit_mb, cores: l.worker_threads, depth: l.stream_depth_mb, lvl: l.detection_profile,
                    ok: it.selectable !== false, reason: it.reason || '',
                };
            });
            const cur = s.profile || 'balanced';
            if (!P[cur]) P[cur] = { ok: true, reason: '' };
            // The profile in force defines its own ceiling when the list lacks its limits.
            const lim = { mem: s.memory_limit_mb, cores: s.worker_threads, depth: s.stream_depth_mb, lvl: s.detection_profile };
            KEYS.forEach((k) => { if (P[cur][k] == null) P[cur][k] = lim[k]; });
            const mo = o['performance.memory_limit_mb'] || {};
            w.meta = { P, order: Object.keys(PN).filter((p) => P[p]), memMin: Math.max(1, Number(mo.min) || 512), defProfile: (data.defaults && data.defaults.performance && data.defaults.performance.profile) || 'balanced' };
            const st = { profile: cur, stored: {} };
            KEYS.forEach((k) => {
                if (lim[k] != null && cmpv(k, lim[k], P[cur][k]) < 0) st.stored[k] = lim[k];
            });
            w.saved = st;
            w.draft = clone(st);
        },

        pending(w) {
            const out = [];
            if (w.draft.profile !== w.saved.profile) out.push('profile');
            KEYS.forEach((k) => { if ((w.draft.stored[k] ?? null) !== (w.saved.stored[k] ?? null)) out.push(k); });
            return out;
        },

        idle(w, k) {
            if (k === 'profile') return '';
            return eff(w, w.draft, k) !== top(w, k)
                ? `<button type="button" class="ids-wt-lnk" data-do="reset" data-arg="${k}" title="Reset to default" aria-label="Reset to default">Reset</button>` : '';
        },

        isCustom: (w, k) => eff(w, w.draft, k) !== top(w, k),

        bounds(w, k) {
            return [k === 'mem' ? w.meta.memMin : 1, top(w, k)];
        },
        numValue: (w, k) => eff(w, w.draft, k),
        setNum: (w, k, n) => setVal(w, k, n),

        act(w, verb, arg) {
            if (verb === 'prof') {
                const p = w.meta.P[arg];
                if (!p || !p.ok || w.draft.profile === arg) return false;
                setProfile(w, arg);
                KEYS.forEach((k) => { delete w.err[k]; delete w.warn[k]; });
                return true;
            }
            if (verb === 'lvl') {
                if (eff(w, w.draft, 'lvl') === arg) return false;
                setVal(w, 'lvl', arg);
                return true;
            }
            if (verb === 'reset') { delete w.draft.stored[arg]; delete w.err[arg]; delete w.warn[arg]; return true; }
            if (verb === 'undo') {
                if (arg === 'profile') { w.draft = clone(w.saved); w.err = {}; w.warn = {}; return true; }
                if (w.saved.stored[arg] == null) delete w.draft.stored[arg]; else setVal(w, arg, w.saved.stored[arg]);
                delete w.err[arg];
                delete w.warn[arg];
                return true;
            }
            return false;
        },

        payload(w) {
            const out = {};
            if (w.draft.profile !== w.saved.profile) out.profile = w.draft.profile;
            // A lowered value is sent as is; going back to the profile's own value sends null.
            KEYS.forEach((k) => {
                const a = w.draft.stored[k] ?? null, b = w.saved.stored[k] ?? null;
                if (a !== b) out[FIELD[k]] = a;
            });
            return { performance: out };
        },

        render(w) {
            if (w.tab === 'basic') {
                return section('Profile', 'How much of this device the inspection may use.', profileList(w), tip(w, 'p', TIP_PERF));
            }
            return section('Limits', 'Lower these to leave more for the rest of the device.', limitRows(w), tip(w, 'l', TIP_PERF));
        },
    };

    function profileList(w) {
        return '<div class="ids-wt-pre" role="radiogroup" aria-label="Profile">' + w.meta.order.map((p) => {
            const it = w.meta.P[p], on = w.draft.profile === p;
            const why = it.ok ? '' : (REASONS[it.reason] || 'Not available on this device.');
            const uses = it.mem != null ? ` Uses up to ${gb(it.mem)}.` : '';
            return choice(w, 'prof', p, on, PN[p], PD[p] + uses, { off: !it.ok, why, isDefault: p === w.meta.defProfile, stt: 'profile' });
        }).join('') + '</div>';
    }

    function upTo(w, k) {
        const v = top(w, k);
        return `Up to ${k === 'lvl' ? LVN[v] : fmt(v) + (UNIT[k] ? ' ' + UNIT[k] : '')} with ${PN[w.draft.profile]}.`;
    }

    function numRow(w, k) {
        return `<div class="ids-wt-row"><div class="ids-wt-lt"><div class="ids-wt-l">${NAME[k]}${dot(k)}</div>` +
            `<div class="ids-wt-d">${DESC[k]} ${upTo(w, k)}</div></div>${stt(k, true)}` +
            `<span class="ids-wt-fv">${numField(w, k, NAME[k], UNIT[k], 'ids-wt-ig-' + k)}</span><div class="ids-wt-msg" data-msg="${k}" hidden></div></div>`;
    }

    function lvlRow(w) {
        const ceil = top(w, 'lvl'), cur = eff(w, w.draft, 'lvl');
        const chips = LV.map((l) => {
            const above = cmpv('lvl', l, ceil) > 0;
            return `<button type="button" class="ids-chip${cur === l ? ' ids-on' : ''}" data-do="lvl" data-arg="${l}"${above || w.ro ? ' disabled' : ''}${above ? ' title="Above the profile."' : ''}>${LVN[l]}</button>`;
        }).join('');
        return `<div class="ids-wt-row ids-wt-rowch"><div class="ids-wt-lt"><div class="ids-wt-l">${NAME.lvl}${dot('lvl')}</div>` +
            `<div class="ids-wt-d">${DESC.lvl} ${upTo(w, 'lvl')}</div></div>${stt('lvl', true)}<div class="ids-chips ids-wt-lvl">${chips}</div></div>`;
    }

    function limitRows(w) {
        return numRow(w, 'mem') + numRow(w, 'cores') + lvlRow(w) + (showDepth(w) ? numRow(w, 'depth') : '');
    }

    /* ---------- register ---------- */

    IdsWin.register('inspection', {
        title: 'Inspection',
        icon: 'magnifying-glass',
        wide: true,
        open(ctx, win) { mount(ctx, win, inspection); },
    });

    IdsWin.register('performance', {
        title: 'Performance',
        icon: 'gauge',
        open(ctx, win) { mount(ctx, win, performance); },
    });
})();
