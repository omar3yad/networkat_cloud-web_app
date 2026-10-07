/**
 * IDS page window: Excluded devices (devices the IDS does not inspect).
 *
 * Design 5e (ids-part5e-final.html). Changes are staged in memory and written on
 * "Save changes" in ONE request (POST /ids/excluded/batch: all or nothing).
 *
 * An item is an address (host or network, the backend tells them apart) or an
 * alias of the normal (address list) type, with optional protocol, port,
 * direction and comment. One typed address list becomes one item per address.
 */
(function () {
    if (!window.IdsWin) return;

    const DEFAULT_LIMIT = 100;
    const BATCH_MAX = 100;
    const MAX_ADDRS = 64;
    const PROTO = [['any', 'Any'], ['tcp', 'TCP'], ['udp', 'UDP']];
    const DIR = [['any', 'Either way'], ['from', 'When it sends'], ['to', 'When it receives']];
    const ADDR_HELP = 'Enter an address or a network, like 192.168.100.60 or 192.168.50.0/24.';
    const IPRE = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;

    function okAddr(v) {
        const [a, m] = v.split('/');
        return IPRE.test(a || '') && (m === undefined || (/^\d+$/.test(m) && +m >= 8 && +m <= 32));
    }

    function checkPort(p) {
        p = (p || '').trim();
        if (!p) return '';
        const m = p.match(/^(\d+)(?:-(\d+))?$/);
        return (!m || +m[1] < 1 || +m[1] > 65535 || (m[2] && (+m[2] <= +m[1] || +m[2] > 65535))) ? `Invalid port: ${p}.` : '';
    }

    function open(ctx, win) {
        const N = ctx.N;
        const esc = N.esc;
        const S = {
            items: [], aliases: [], aliasesFailed: false, limit: DEFAULT_LIMIT,
            add: newForm('add'), open: false, ov: null,
            saving: false, saved: false, err: '', confirm: false,
        };
        let uidSeq = 0;
        let savedTimer = null;

        win.body.innerHTML = '<div class="ids-win-msg">Loading.</div>';
        const ready = load();   // settles when the first load is done (the shell loads the next section after it)

        // ── Data ────────────────────────────────────────────────────────────

        async function call(method, path, body) {
            const init = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
            if (body !== undefined) {
                init.headers['Content-Type'] = 'application/json';
                init.body = JSON.stringify(body);
            }
            let res;
            try {
                res = await fetch(`/api/v2/client/peers/${encodeURIComponent(ctx.peerId)}/ids${path}`, init);
            } catch (e) {
                throw new Error('Network error');
            }
            if (method !== 'GET') N.api.bust();   // a write: shared reads must be fetched again
            let data = null;
            try { data = await res.json(); } catch (e) { /* empty body */ }
            if (!res.ok) throw new Error(data && typeof data.detail === 'string' ? data.detail : 'Request failed');
            return data;
        }

        // Only address aliases (type normal); website aliases never show.
        async function loadAliases() {
            const data = await N.api.aliases(ctx.peerId);
            return (data.lists || []).filter((a) => a.type === 'normal').map((a) => ({
                id: a.id || a.slug,
                name: a.name || a.slug || a.id,
                n: (a.list || []).length,
                c: a.comment || '',
                raw: a,
            })).filter((a) => a.id);
        }

        function fromServer(it) {
            return {
                uid: `s${it.id}`, id: it.id,
                kind: it.target === 'alias' ? 'alias' : 'address',
                value: it.value || '', aliasId: it.alias_id || '',
                proto: it.protocol || 'any', port: it.port ? String(it.port) : '', dir: it.direction || 'any',
                comment: it.comment || '', p: null,
            };
        }

        async function fetchList() {
            return ((await call('GET', '/excluded')).items || []).map(fromServer);
        }

        async function load() {
            try {
                const [items, aliases, doc] = await Promise.all([
                    fetchList(),
                    loadAliases().catch(() => null),
                    N.api.settings(ctx.peerId).catch(() => null),
                ]);
                S.items = items;
                S.aliases = aliases || [];
                S.aliasesFailed = !aliases;
                const lim = doc && doc.options && doc.options.limits && doc.options.limits.exclusions;
                if (lim > 0) S.limit = lim;
            } catch (e) {
                win.body.innerHTML = '<div class="ids-win-msg">Couldn\'t load.</div>';
                return;
            }
            build();
        }

        // ── Small helpers ───────────────────────────────────────────────────

        function newForm(mode) {
            return {
                mode, value: '', comment: '', proto: 'any', port: '', dir: 'any', adv: false,
                err: '', warn: '', perr: '', pwarn: '', dd: false, kind: 'address',
            };
        }

        const aliasById = (id) => S.aliases.find((a) => a.id === id);
        const aliasLabel = (id) => (aliasById(id) || {}).name || id;
        const strip = (e) => { const { p, orig, ...rest } = e; return rest; };
        const itemKey = (e) => JSON.stringify([e.kind, e.kind === 'alias' ? e.aliasId : e.value, e.comment, e.proto, e.port, e.dir]);
        // A form is "changed" by what it would save: advanced values count only while the box is open.
        const fsKey = (fs) => JSON.stringify([fs.value.trim(), fs.comment.trim(), ...(fs.adv ? [fs.proto, fs.port.trim(), fs.dir] : ['any', '', 'any'])]);
        const pending = () => S.items.filter((e) => e.p);
        const liveCount = () => S.items.filter((e) => e.p !== 'del').length;
        const isAlias = (fs) => fs.value.trim().startsWith('@');

        // ── Checks: nothing while typing except a never-valid character ─────

        function badChar(v) {
            const t = v.trim();
            if (t.startsWith('@')) {
                if (v.includes(',')) return 'One alias only.';
                for (const ch of t.slice(1)) if (!/[\p{L}\p{N}_\- .]/u.test(ch)) return `"${ch === ' ' ? 'Space' : ch}" not allowed.`;
                return '';
            }
            if (v.includes('@')) return 'Can\'t mix addresses and an alias.';
            for (const ch of v) if (!/[0-9./,\s]/.test(ch)) return `"${ch}" not allowed.`;
            return '';
        }

        function badPortChar(v) {
            for (const ch of v) if (!/[0-9-]/.test(ch)) return `"${ch === ' ' ? 'Space' : ch}" not allowed.`;
            return '';
        }

        function parse(v) {
            const parts = v.split(',').map((p) => p.trim()).filter(Boolean);
            if (!parts.length) return { err: ADDR_HELP };
            const al = parts.filter((p) => p.startsWith('@'));
            if (al.length > 1) return { err: 'One alias only.' };
            if (al.length && parts.length > 1) return { err: 'Can\'t mix addresses and an alias.' };
            if (al.length) {
                const n = al[0].slice(1).trim();
                const a = S.aliases.find((x) => x.name === n) || S.aliases.find((x) => x.name.toLowerCase() === n.toLowerCase());
                if (a) return { alias: a };
                return { err: S.aliasesFailed ? 'Aliases not available.' : `Unknown alias: ${n || '@'}.` };
            }
            if (parts.length > MAX_ADDRS) return { err: `Up to ${MAX_ADDRS} addresses.` };
            if (parts.some((p) => !okAddr(p))) return { err: ADDR_HELP };
            return { addrs: parts };
        }

        // Full check (Add / Update). Returns the parsed value or null with the messages set.
        function checkForm(fs, single) {
            if (!fs.adv) { fs.proto = 'any'; fs.port = ''; fs.dir = 'any'; }
            const r = parse(fs.value);
            fs.err = fs.warn || r.err || (single && r.addrs && r.addrs.length > 1 ? 'One address when editing.' : '');
            fs.perr = fs.pwarn || checkPort(fs.port) || (fs.port.trim() && fs.proto === 'any' ? 'A port needs TCP or UDP.' : '');
            fs.dd = false;
            return fs.err || fs.perr ? null : r;
        }

        // ── Form (the same block for Add and for Edit) ──────────────────────

        // Same list as the firewall rule page's alias field, plus the type the Aliases page shows.
        // Like the firewall (which also hides web_domain), only normal aliases are listed.
        function ddHtml(fs) {
            if (!fs.dd) return '';
            const v = fs.value.trim();
            const q = v.startsWith('@') ? v.slice(1).toLowerCase() : '';
            const m = S.aliases.map((a, i) => [a, i]).filter(([a]) =>
                !q || a.name.toLowerCase().includes(q) || a.c.toLowerCase().includes(q));
            if (!m.length) {
                const none = S.aliasesFailed ? 'Couldn\'t load aliases.' : 'No aliases found.';
                return `<div class="ids-we-acdd"><div class="ids-we-acnone">${none}<br>` +
                    '<button type="button" class="ids-we-acl2" data-x="mkalias">+ Create alias</button></div></div>';
            }
            const make = '<button type="button" class="ids-we-acf" data-x="mkalias">' + IdsIcon('plus-circle') + ' Create alias</button>';
            return '<div class="ids-we-acdd">' + m.map(([a, i]) =>
                `<div class="ids-we-aci" data-ai="${i}"><span class="ids-we-acn"><span class="ids-we-acl"><span>@${esc(a.name)}</span>` +
                `<span class="ids-we-acc">${a.n}</span><span class="ids-we-actype">Normal</span></span>` +
                '<span class="ids-we-ace" data-ae title="Edit alias" aria-label="Edit alias">' + IdsIcon('external-link-alt') + '</span></span>' +
                `<span class="ids-we-acd">${esc(a.c)}</span></div>`).join('') + make + '</div>';
        }

        function warnHtml(t) {
            return `<div class="ids-we-warn">${IdsIcon('triangle-exclamation')}<span>${esc(t)}</span></div>`;
        }

        function msgHtml(fs) {
            if (fs.err) return `<div class="ids-we-err">${esc(fs.err)}</div>`;
            if (fs.warn) return warnHtml(fs.warn);
            return fs.mode === 'edit' ? '' : '<div class="ids-we-hint">Type @ or press @ to pick an alias. Press + to paste many addresses.</div>';
        }

        function pmsgHtml(fs) {
            if (fs.perr) return `<div class="ids-we-err">${esc(fs.perr)}</div>`;
            if (fs.pwarn) return warnHtml(fs.pwarn);
            return '<div class="ids-we-hint">One port or a range, like 8000-8100.</div>';
        }

        const infoHtml = (fs) => (isAlias(fs)
            ? '<div class="ids-we-info">' + IdsIcon('circle-info') + '<span>An alias is still inspected but never raises a threat.</span></div>'
            : '');

        const multiOff = (fs) => fs.mode === 'edit' || isAlias(fs);

        function segHtml(opts, cur, attr, extra) {
            return `<div class="ids-we-seg${extra || ''}">${opts.map(([k, l]) =>
                `<button type="button" data-${attr}="${k}" class="${cur === k ? 'ids-we-on' : ''}">${l}</button>`).join('')}</div>`;
        }

        function formHtml(fs) {
            const cls = (fs.err ? ' ids-we-bad' : fs.warn ? ' ids-we-warnb' : '') + (isAlias(fs) ? ' ids-we-inalias' : '');
            let h = `<div data-form="${fs.mode}"><div class="ids-we-acwrap">` +
                '<button type="button" class="ids-we-atb" data-x="dd" title="Pick an alias" aria-label="Pick an alias">@</button>' +
                `<input class="ids-we-inp ids-we-main${cls}" data-f="value" value="${esc(fs.value)}" placeholder="192.168.100.60, 192.168.50.0/24" autocomplete="off" spellcheck="false">` +
                (fs.mode === 'edit' ? '' :   // editing is one address: no "+", no comma
                    `<button type="button" class="ids-we-mlb${multiOff(fs) ? ' ids-we-disabled' : ''}" data-x="multi" title="Add multiple addresses" aria-label="Add multiple addresses">${IdsIcon('plus')}</button>`) +
                `<div data-live="dd">${ddHtml(fs)}</div></div>` +
                `<div data-live="msg">${msgHtml(fs)}</div>` +
                `<button type="button" class="ids-we-more" data-x="more">${IdsIcon(fs.adv ? 'chevron-up' : 'chevron-down')}${fs.adv ? 'Fewer options' : 'More options'}</button>`;
            if (fs.adv) {
                h += '<div class="ids-we-adv"><span class="ids-we-lbl ids-we-first">Comment</span>' +
                    `<input class="ids-we-inp" data-f="comment" value="${esc(fs.comment)}" placeholder="Optional, like Camera." maxlength="200" autocomplete="off">` +
                    '<div class="ids-we-advh">Advanced</div>' +
                    `<span class="ids-we-lbl ids-we-first">Protocol</span>${segHtml(PROTO, fs.proto, 'p', ' ids-we-narrow')}` +
                    '<span class="ids-we-lbl">Port</span>' +
                    `<input class="ids-we-inp ids-we-narrow${fs.perr ? ' ids-we-bad' : fs.pwarn ? ' ids-we-warnb' : ''}" data-f="port" value="${esc(fs.port)}" placeholder="Any port" autocomplete="off">` +
                    `<div data-live="pmsg">${pmsgHtml(fs)}</div>` +
                    `<span class="ids-we-lbl">Direction</span>${segHtml(DIR, fs.dir, 'd')}` +
                    '<div class="ids-we-hint">The port is the remote port when it sends, otherwise the device\'s own port.</div></div>';
            }
            return h + `<div data-live="info">${infoHtml(fs)}</div></div>`;
        }

        // Update one form in place (typing must not lose focus or the phone keyboard).
        function liveForm(fe, fs) {
            const inp = fe.querySelector('[data-f="value"]');
            // A pick (or a created alias) changes fs.value without typing: write it into the field.
            if (inp.value !== fs.value) inp.value = fs.value;
            inp.classList.toggle('ids-we-bad', !!fs.err);
            inp.classList.toggle('ids-we-warnb', !fs.err && !!fs.warn);
            inp.classList.toggle('ids-we-inalias', isAlias(fs));
            fe.querySelector('.ids-we-mlb').classList.toggle('ids-we-disabled', multiOff(fs));
            fe.querySelector('[data-live="dd"]').innerHTML = ddHtml(fs);
            fe.querySelector('[data-live="msg"]').innerHTML = msgHtml(fs);
            fe.querySelector('[data-live="info"]').innerHTML = infoHtml(fs);
            const p = fe.querySelector('[data-f="port"]');
            if (p) {
                p.classList.toggle('ids-we-bad', !!fs.perr);
                p.classList.toggle('ids-we-warnb', !fs.perr && !!fs.pwarn);
                fe.querySelector('[data-live="pmsg"]').innerHTML = pmsgHtml(fs);
            }
        }

        function formOf(node) {
            const fe = node.closest && node.closest('[data-form]');
            if (!fe) return [null, null];
            return [fe, fe.dataset.form === 'edit' ? (S.ov && S.ov.k === 'edit' ? S.ov.fs : null) : S.add];
        }

        // ── Drawing ─────────────────────────────────────────────────────────

        let hostAdd, hostList;

        function build() {
            win.body.innerHTML =
                '<p class="ids-win-desc">Devices the IDS does not inspect.</p>' +
                '<div data-host="add"></div><div data-host="list"></div>';
            hostAdd = win.body.querySelector('[data-host="add"]');
            hostList = win.body.querySelector('[data-host="list"]');
            win.body.addEventListener('click', onClick);
            win.body.addEventListener('input', onInput);
            win.body.addEventListener('focusout', onFocusOut);
            win.body.addEventListener('keydown', onKeydown);
            win.body.addEventListener('mousedown', keepFocus);
            win.foot.addEventListener('click', onClick);
            document.addEventListener('click', onDocClick);
            document.addEventListener('keydown', onEscape, true);
            if (win.isDirty) win.isDirty(() => S.saving || pending().length > 0);
            win.beforeClose(() => {
                if (S.saving) return false;
                if (!pending().length) return true;
                S.confirm = true;
                drawFoot();
                return false;
            });
            drawAdd();
            drawList();
            drawFoot();
        }

        // Add: a collapsed heading and plus; it opens the Add window.
        function drawAdd() {
            if (ctx.readonly) { hostAdd.innerHTML = ''; drawAddOv(); return; }
            hostAdd.innerHTML = '<section class="ids-sec ids-we-add ids-we-shut">' +
                '<button type="button" class="ids-we-toggle" data-x="toggle" title="Add">' +
                `<span class="ids-sec-h">Add</span>${IdsIcon('plus')}</button></section>`;
            drawAddOv();
        }

        // The Add window (a page modal, like Edit).
        function drawAddOv() {
            if (!S.open || ctx.readonly) {
                if (ova) { ova.remove(); ova = null; }
                return;
            }
            if (!ova) ova = mountOv();
            const old = ova.querySelector('.ids-we-ovb');
            const top = old ? old.scrollTop : 0;
            ova.innerHTML = '<div class="ids-we-ovcard" role="dialog" aria-modal="true">' +
                '<div class="modal-header ids-we-ovh"><h2>Add excluded device</h2><button type="button" class="modal-close" data-x="addclose" aria-label="Close">&times;</button></div>' +
                '<div class="ids-we-ovb"><section class="ids-sec"><h3 class="ids-sec-h">Add</h3>' +
                '<p class="ids-sec-help">One or more addresses separated by commas, or an alias.</p>' +
                `<div class="ids-sec-body">${formHtml(S.add)}</div></section></div>` +
                '<div class="ids-we-ovf"><button type="button" class="ids-btn" data-x="addclose">Cancel</button>' +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="add">${IdsIcon('plus')}Add</button></div></div>`;
            ova.querySelector('.ids-we-ovb').scrollTop = top;
        }

        const BADGE = {
            add: '<span class="ids-we-pend">Not saved</span>',
            edit: '<span class="ids-we-pend">Changed</span>',
            del: '<span class="ids-we-pend ids-we-del">Will be removed</span>',
        };

        function descOf(e) {
            const parts = [];
            if (e.proto !== 'any') parts.push(e.proto.toUpperCase());
            if (e.port) parts.push(`port ${e.port}`);
            if (e.dir !== 'any') parts.push(e.dir === 'from' ? 'when it sends' : 'when it receives');
            let how = parts.length ? parts.join(', ') : 'All traffic';
            if (parts.length) how = how[0].toUpperCase() + how.slice(1);
            return how + (e.comment ? ` · ${esc(e.comment)}` : '') + '.';
        }

        function rowHtml(e, i) {
            const al = e.kind === 'alias';
            const v = al ? `<span class="ids-we-al">@${esc(aliasLabel(e.aliasId))}</span>` : `<span class="ids-mono">${esc(e.value)}</span>`;
            const ic = (attr, icon, title) =>
                `<button type="button" class="ids-we-ic" data-${attr}="${i}" title="${title}" aria-label="${title}">${IdsIcon(icon)}</button>`;
            let acts = '';
            if (e.p === 'del') acts = ic('undo', 'rotate-left', 'Keep it');
            else if (!ctx.readonly) {
                acts = (e.p === 'edit' ? ic('revert', 'rotate-left', 'Undo the change') : '') +
                    ic('edit', 'pen', 'Edit') + ic('del', 'trash', 'Remove');
            }
            return `<div class="ids-we-row${e.p === 'del' ? ' ids-we-gone' : ''}">` +
                `<div class="ids-we-main2"><div class="ids-we-t"><span class="ids-we-v">${v}</span><span class="ids-we-tag">${al ? 'Alias' : 'Address'}</span>${BADGE[e.p] || ''}</div>` +
                `<div class="ids-we-d">${descOf(e)}</div></div><div class="ids-we-acts">${acts}</div></div>`;
        }

        function drawList() {
            const live = S.items.filter((e) => e.p !== 'del' && e.p !== 'add').length;
            hostList.innerHTML = '<section class="ids-sec"><h3 class="ids-sec-h">In the list</h3>' +
                `<p class="ids-sec-help">${live} excluded.${ctx.readonly ? '' : ' Edit or remove one; nothing changes until you save.'}</p>` +
                `<div class="ids-sec-body">${S.items.length ? S.items.map(rowHtml).join('') : '<div class="ids-we-empty">None.</div>'}</div></section>`;
        }

        function drawFoot() {
            const n = pending().length;
            const dis = (v) => (v ? ' disabled' : '');
            const btns = (dSave) =>
                '<div class="ids-foot-btns"><button type="button" class="ids-btn" data-x="discard">Close</button>' +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="save"${dis(dSave)}>${IdsIcon('floppy-disk')}Save changes</button></div>`;
            if (S.confirm && n) {
                win.foot.innerHTML = `<div class="ids-foot-status"><b class="ids-we-strong">${n} unsaved ${n === 1 ? 'change' : 'changes'}.</b> Close without saving?</div>` +
                    '<div class="ids-foot-btns"><button type="button" class="ids-btn" data-x="keep">Keep editing</button>' +
                    '<button type="button" class="ids-btn ids-btn-danger" data-x="leave">Close without saving</button></div>';
                return;
            }
            if (S.saving) {
                win.foot.innerHTML = '<div class="ids-foot-status"><b class="ids-we-strong">' + IdsIcon('circle-notch',{spin:true}) + ' Saving.</b><small>Takes under a minute.</small></div>' + btns(true);
                return;
            }
            let status;
            if (S.saved && !n) status = '<span class="ids-we-ok">' + IdsIcon('check') + ' Saved.</span>';
            else if (n) status = `<b class="ids-we-strong">${n} unsaved ${n === 1 ? 'change' : 'changes'}.</b><small>Changes take effect in under a minute.</small>`;
            else status = '';
            if (S.err) status += `<span class="ids-we-ferr">${esc(S.err)}</span>`;
            win.foot.innerHTML = `<div class="ids-foot-status">${status}</div>` + btns(!n || ctx.readonly);
        }

        function redraw() {
            S.confirm = false;
            drawAdd();
            drawList();
            drawFoot();
        }

        // ── Sub-windows: edit one item, or paste many addresses ─────────────

        let ov = null;
        let ova = null;   // the Add window

        const multiKey = (o) => o.rows.map((r) => r.trim()).filter(Boolean).join(',');
        function ovDirty() {
            if (!S.ov) return false;
            return S.ov.k === 'edit' ? fsKey(S.ov.fs) !== S.ov.base : multiKey(S.ov) !== S.ov.base;
        }

        function ovInner() {
            const o = S.ov;
            if (o.k === 'edit') {
                return '<div class="modal-header ids-we-ovh"><h2>Edit excluded device</h2><button type="button" class="modal-close" data-x="ovclose" aria-label="Close">&times;</button></div>' +
                    '<div class="ids-we-ovb"><section class="ids-sec"><h3 class="ids-sec-h">Edit</h3>' +
                    `<div class="ids-sec-body">${formHtml(o.fs)}</div></section></div>` +
                    '<div class="ids-we-ovf"><button type="button" class="ids-btn" data-x="ovclose">Cancel</button>' +
                    `<button type="button" class="ids-btn ids-btn-primary" data-x="ovsave"${ovDirty() ? '' : ' disabled'}>Update</button></div>`;
            }
            return '<div class="modal-header ids-we-ovh"><h2>Addresses</h2><button type="button" class="modal-close" data-x="ovclose" aria-label="Close">&times;</button></div>' +
                '<div class="ids-we-ovb"><div class="ids-we-rowsh"><span class="ids-we-lbl ids-we-first">Addresses and networks</span>' +
                '<button type="button" class="ids-btn" data-x="rowadd">' + IdsIcon('plus') + 'Add address</button></div>' +
                `<div data-rows>${o.rows.map((r) => '<div class="ids-we-rowx">' +
                    `<input class="ids-we-inp" data-ma value="${esc(r)}" placeholder="Like 192.168.10.5 or 192.168.50.0/24" autocomplete="off" spellcheck="false">` +
                    '<button type="button" class="ids-we-ic" data-x="rowdel" title="Remove" aria-label="Remove">' + IdsIcon('trash') + '</button></div>').join('')}</div></div>` +
                '<div class="ids-we-ovf"><button type="button" class="ids-btn" data-x="ovclose">Cancel</button>' +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="ovmulti"${ovDirty() ? '' : ' disabled'}>Save changes</button></div>`;
        }

        // A page modal, one layer above the Lists window.
        function mountOv() {
            const el = document.createElement('div');
            el.className = 'ids-win ids-we-ov';
            document.body.appendChild(el);
            el.addEventListener('click', onClick);
            el.addEventListener('input', onInput);
            el.addEventListener('focusout', onFocusOut);
            el.addEventListener('keydown', onKeydown);
            el.addEventListener('mousedown', keepFocus);
            el.addEventListener('mousedown', (ev) => { el.dataset.downOut = ev.target === el ? '1' : ''; });
            return el;
        }

        function drawOv() {
            if (!S.ov || !win.el.isConnected) {
                if (ov) { ov.remove(); ov = null; }
                return;
            }
            if (!ov) {
                ov = mountOv();
                ov.classList.add('ids-we-ov-top');   // many addresses opens over Add
            }
            ov.innerHTML = `<div class="ids-we-ovcard" role="dialog" aria-modal="true">${ovInner()}</div>`;
        }

        function refreshOvBtn() {
            const b = ov && ov.querySelector('[data-x="ovsave"], [data-x="ovmulti"]');
            if (b) b.disabled = !ovDirty();
        }

        // The rows' typed values live in the inputs until a button needs them.
        function readRows() {
            if (!S.ov || S.ov.k !== 'multi' || !ov) return;
            S.ov.rows = [...ov.querySelectorAll('[data-ma]')].map((i) => i.value);
        }

        function openEdit(i) {
            const it = S.items[i];
            const fs = newForm('edit');
            fs.kind = it.kind;
            fs.value = it.kind === 'alias' ? `@${aliasLabel(it.aliasId)}` : it.value;
            fs.comment = it.comment; fs.proto = it.proto; fs.port = it.port; fs.dir = it.dir;
            fs.adv = !!(it.comment || it.port || it.proto !== 'any' || it.dir !== 'any');
            S.ov = { k: 'edit', i, fs, base: fsKey(fs) };
            drawOv();
            N.focusDialog(ov);
        }

        function openMulti() {
            const rows = S.add.value.split(',').map((p) => p.trim()).filter(Boolean);
            S.ov = { k: 'multi', rows: rows.length ? rows : [''] };
            S.ov.base = multiKey(S.ov);
            drawOv();
        }

        function doMulti() {
            readRows();
            if (!ovDirty()) return;
            S.add.value = S.ov.rows.map((p) => p.trim()).filter(Boolean).join(', ');
            S.add.err = ''; S.add.warn = '';
            S.ov = null;
            drawOv();
            drawAdd();
        }

        function doEdit() {
            if (!S.ov || S.ov.k !== 'edit' || !ovDirty()) return;
            const fs = S.ov.fs;
            const r = checkForm(fs, true);
            if (!r) { drawOv(); return; }
            const old = S.items[S.ov.i];
            if (r.alias && old.kind !== 'alias') { fs.err = 'Can\'t change an address to an alias.'; drawOv(); return; }
            if (r.addrs && old.kind === 'alias') { fs.err = 'Can\'t change an alias to an address.'; drawOv(); return; }
            const nu = {
                ...strip(old),
                aliasId: r.alias ? r.alias.id : old.aliasId,
                value: r.addrs ? r.addrs[0] : old.value,
                proto: fs.proto, port: fs.port.trim(), dir: fs.dir, comment: fs.comment.trim(),
            };
            setItem(S.ov.i, nu);
            S.ov = null;
            drawOv();
            redraw();
        }

        // A staged edit; editing back to the saved values drops the badge.
        function setItem(i, nu) {
            const old = S.items[i];
            S.saved = false;
            S.err = '';
            if (old.p === 'add') { S.items[i] = { ...nu, p: 'add' }; return; }
            const orig = old.orig || strip(old);
            S.items[i] = itemKey(nu) === itemKey(orig) ? orig : { ...nu, p: 'edit', orig };
        }

        // ── Staging ─────────────────────────────────────────────────────────

        function doAdd() {
            const fs = S.add;
            const r = checkForm(fs, false);
            if (!r) { drawAdd(); return; }
            const base = { proto: fs.proto, port: fs.port.trim(), dir: fs.dir, comment: fs.comment.trim() };
            const made = r.alias
                ? [{ kind: 'alias', aliasId: r.alias.id, value: '', ...base }]
                : r.addrs.map((a) => ({ kind: 'address', value: a, aliasId: '', ...base }));
            if (liveCount() + made.length > S.limit) {
                fs.err = `Up to ${S.limit} excluded devices.`;
                drawAdd();
                return;
            }
            made.reverse().forEach((m) => S.items.unshift({ uid: `n${++uidSeq}`, id: null, ...m, p: 'add' }));
            S.saved = false;
            S.err = '';
            S.add = newForm('add');
            redraw();   // the Add window stays open for the next one
            const inp = ova && ova.querySelector('[data-f="value"]');
            if (inp) inp.focus();
        }

        // Close drops every unsaved change and closes, no confirm.
        function discard() {
            S.items = S.items.filter((e) => e.p !== 'add').map((e) => e.orig || e);
            S.items.forEach((e) => { e.p = null; });
            S.err = '';
            S.saved = false;
            win.close(true);
        }

        // ── Save: one request, all or nothing ───────────────────────────────

        function bodyOf(e) {
            const b = { protocol: e.proto, port: e.port, direction: e.dir, comment: e.comment };
            return e.kind === 'alias'
                ? { target: 'alias', alias_id: e.aliasId, ...b }
                : { target: 'address', value: e.value, ...b };
        }

        const terse = (m) => String(m || 'Request failed').replace(/\.?\s*$/, '.');

        async function save() {
            const pend = pending();
            if (!pend.length || S.saving || ctx.readonly) return;
            if (pend.length > BATCH_MAX) {
                S.err = `Up to ${BATCH_MAX} changes at once.`;
                drawFoot();
                return;
            }
            const body = {
                add: pend.filter((e) => e.p === 'add').map(bodyOf),
                update: pend.filter((e) => e.p === 'edit').map((e) => ({ id: e.id, ...bodyOf(e) })),
                remove: pend.filter((e) => e.p === 'del').map((e) => e.id),
            };
            S.saving = true;
            S.saved = false;
            S.err = '';
            S.confirm = false;
            win.setBusy(true);
            drawFoot();
            let failed = null;
            try {
                await call('POST', '/excluded/batch', body);
            } catch (e) {
                failed = terse(e.message);
            }
            let fresh = null;
            if (!failed) {
                try { fresh = await fetchList(); } catch (e) { fresh = null; }
            }
            S.saving = false;
            win.setBusy(false);
            if (failed) {
                S.err = failed;
                ctx.toast('err', failed);
                drawFoot();
                return;
            }
            ctx.refreshSide();
            ctx.refreshStatus();
            ctx.toast('ok', 'Saved.');
            if (!fresh) {
                win.body.innerHTML = '<div class="ids-win-msg">Saved. Couldn\'t reload the list.</div>';
                win.foot.innerHTML = '<div class="ids-foot-status">Saved.</div><div class="ids-foot-btns"><button type="button" class="ids-btn" data-x="leave">Close</button></div>';
                return;
            }
            S.items = fresh;
            S.saved = true;
            clearTimeout(savedTimer);
            savedTimer = setTimeout(() => { S.saved = false; if (win.el.isConnected && !S.saving) drawFoot(); }, 2000);
            drawAdd();
            drawList();
            drawFoot();
        }

        // The same Create alias window as the firewall page; the new alias is picked on success.
        function createAlias(fe, fs) {
            if (!window.IdsAliasCreate) { ctx.toast('err', 'Couldn\'t open the window.'); return; }
            fs.dd = false;
            liveForm(fe, fs);
            IdsAliasCreate.open({
                peerId: ctx.peerId,
                onCreated: async (name) => {
                    try { S.aliases = await loadAliases(); S.aliasesFailed = false; } catch (e) { /* keep the old list */ }
                    fs.value = `@${name}`;
                    fs.err = ''; fs.warn = '';
                    if (fe.isConnected) {
                        liveForm(fe, fs);
                        if (fs.mode === 'edit') refreshOvBtn();
                    }
                },
            });
        }

        // The aliases page's Edit alias window; the list reloads and the pick follows a rename.
        function editAlias(fe, fs, a) {
            if (!window.IdsAliasCreate) { ctx.toast('err', 'Couldn\'t open the window.'); return; }
            fs.dd = false;
            liveForm(fe, fs);
            IdsAliasCreate.open({
                peerId: ctx.peerId,
                alias: a.raw,
                onSaved: async (saved) => {
                    const picked = fs.value.trim().replace(/^@/, '').toLowerCase() === a.name.toLowerCase();
                    try { S.aliases = await loadAliases(); S.aliasesFailed = false; } catch (e) { /* keep the old list */ }
                    if (picked) { fs.value = `@${saved.name}`; fs.err = ''; fs.warn = ''; }
                    if (fe.isConnected) {
                        liveForm(fe, fs);
                        if (fs.mode === 'edit') refreshOvBtn();
                    }
                    drawList();
                },
            });
        }

        // ── Events ──────────────────────────────────────────────────────────

        // Like the firewall page, a row is picked on mousedown (the field keeps focus).
        function keepFocus(ev) {
            const row = ev.target.closest('.ids-we-aci');
            if (!row) return;
            ev.preventDefault();
            const [fe, fs] = formOf(row);
            if (!fs) return;
            const a = S.aliases[+row.dataset.ai];
            if (ev.target.closest('[data-ae]')) {
                ev.stopPropagation();
                editAlias(fe, fs, a);
                return;
            }
            fs.value = `@${a.name}`;
            fs.err = ''; fs.warn = ''; fs.dd = false;
            liveForm(fe, fs);
            if (fs.mode === 'edit') refreshOvBtn();
        }

        function closeMenus() {
            let changed = false;
            [[S.add, ova], [S.ov && S.ov.fs, ov]].forEach(([fs, root]) => {
                if (!fs || !fs.dd) return;
                fs.dd = false;
                const fe = root && root.querySelector('[data-form]');
                if (fe) liveForm(fe, fs);
                changed = true;
            });
            return changed;
        }

        // Re-draw the form a click changed (it holds all its state in fs).
        function reform(fs) {
            if (fs.mode === 'edit') { drawOv(); refreshOvBtn(); } else drawAdd();
        }

        function onClick(ev) {
            const b = ev.target.closest('button');
            if (ov && ev.target === ov && ov.dataset.downOut) { S.ov = null; drawOv(); return; }
            if (ova && ev.target === ova && ova.dataset.downOut) { S.open = false; drawAddOv(); return; }
            if (!b) return;
            const x = b.dataset.x;
            const [fe, fs] = formOf(b);
            if (S.confirm && !['keep', 'leave'].includes(x)) { S.confirm = false; drawFoot(); }
            if (x === 'dd' && fs) {
                fs.dd = !fs.dd;
                liveForm(fe, fs);
            } else if (x === 'mkalias' && fs) createAlias(fe, fs);
            else if (x === 'multi' && fs) { if (!multiOff(fs)) openMulti(); }
            else if (x === 'more' && fs) { fs.adv = !fs.adv; reform(fs); }
            else if (b.dataset.p && fs) { fs.proto = b.dataset.p; reform(fs); }
            else if (b.dataset.d && fs) { fs.dir = b.dataset.d; reform(fs); }
            else if (x === 'add') doAdd();
            else if (x === 'toggle') {
                S.open = true;
                drawAddOv();
                N.focusDialog(ova);
            } else if (x === 'addclose') { S.open = false; drawAddOv(); }
            else if (x === 'ovsave') doEdit();
            else if (x === 'ovmulti') doMulti();
            else if (x === 'rowadd') { readRows(); S.ov.rows.push(''); drawOv(); const l = ov.querySelectorAll('[data-ma]'); l[l.length - 1].focus(); }
            else if (x === 'rowdel') {
                readRows();
                const idx = [...ov.querySelectorAll('.ids-we-rowx')].indexOf(b.closest('.ids-we-rowx'));
                S.ov.rows.splice(idx, 1);
                if (!S.ov.rows.length) S.ov.rows.push('');
                drawOv();
                refreshOvBtn();
            } else if (x === 'ovclose') { S.ov = null; drawOv(); }
            else if (x === 'save') save();
            else if (x === 'discard') discard();
            else if (x === 'keep') { S.confirm = false; drawFoot(); }
            else if (x === 'leave') win.close(true);
            else if (b.dataset.edit !== undefined) openEdit(+b.dataset.edit);
            else if (b.dataset.del !== undefined) {
                const i = +b.dataset.del;
                if (S.items[i].p === 'add') S.items.splice(i, 1); else S.items[i].p = 'del';
                S.saved = false; S.err = '';
                redraw();
            } else if (b.dataset.revert !== undefined) {
                const i = +b.dataset.revert;
                S.items[i] = S.items[i].orig;
                S.err = '';
                redraw();
            } else if (b.dataset.undo !== undefined) {
                const it = S.items[+b.dataset.undo];
                it.p = it.orig ? 'edit' : null;
                S.err = '';
                redraw();
            }
        }

        function onInput(ev) {
            if (ev.target.hasAttribute('data-ma')) { readRows(); refreshOvBtn(); return; }
            const f = ev.target.dataset.f;
            const [fe, fs] = formOf(ev.target);
            if (!f || !fs) return;
            fs[f] = ev.target.value;
            if (f === 'value' && fs.mode === 'edit' && fs.value.includes(',')) {
                // A comma would start a second address: keep the first one and say why, at once.
                fs.value = ev.target.value = fs.value.slice(0, fs.value.indexOf(','));
                fs.err = '';
                fs.warn = 'One address when editing.';
                fs.dd = false;
            } else if (f === 'value') {
                fs.err = '';
                fs.warn = badChar(fs.value);
                fs.dd = isAlias(fs) && !fs.warn;
            } else if (f === 'port') {
                fs.perr = '';
                fs.pwarn = badPortChar(fs.port);
            }
            liveForm(fe, fs);
            if (fs.mode === 'edit') refreshOvBtn();
        }

        function onFocusOut(ev) {
            const f = ev.target.dataset && ev.target.dataset.f;
            const [fe, fs] = formOf(ev.target);
            if (!f || !fs) return;
            const to = ev.relatedTarget;
            if (to && to.closest && to.closest('.ids-we-acwrap, .ids-we-ovf')) return;
            if (f === 'value' && fs.value.trim() && !fs.warn) {
                const r = parse(fs.value);
                fs.err = r.err || (fs.mode === 'edit' && r.addrs && r.addrs.length > 1 ? 'One address when editing.' : '');
                fs.dd = false;
                liveForm(fe, fs);
            } else if (f === 'port' && fs.port.trim() && !fs.pwarn) {
                fs.perr = checkPort(fs.port);
                liveForm(fe, fs);
            }
        }

        function onKeydown(ev) {
            if (ev.target.tagName !== 'INPUT' || ev.key !== 'Enter') return;
            if (ev.target.hasAttribute('data-ma')) { ev.preventDefault(); return; }
            const [, fs] = formOf(ev.target);
            if (!fs) return;
            ev.preventDefault();
            if (fs.mode === 'add') doAdd(); else doEdit();
        }

        function onDocClick(ev) {
            if (!win.el.isConnected) { document.removeEventListener('click', onDocClick); return; }
            if (ev.target.closest && ev.target.closest('.ids-we-acwrap')) return;
            closeMenus();
        }

        // Escape closes the open menu, then the sub-window, before the shell sees it.
        function onEscape(ev) {
            if (!win.el.isConnected) { document.removeEventListener('keydown', onEscape, true); return; }
            if (ev.key !== 'Escape') return;
            if (document.querySelector('#idsAcModal.active')) return;   // Create alias above: Escape is its own
            if (closeMenus()) { ev.stopPropagation(); return; }
            if (S.ov) { ev.stopPropagation(); S.ov = null; drawOv(); return; }
            if (S.open) { ev.stopPropagation(); S.open = false; drawAddOv(); return; }
            if (S.confirm) { ev.stopPropagation(); S.confirm = false; drawFoot(); }
        }
        return ready;
    }

    IdsWin.register('excluded', { title: 'Excluded devices', icon: 'eye-slash', open });
})();
