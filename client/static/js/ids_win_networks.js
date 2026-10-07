/**
 * IDS page window: Networks (a Settings section). Design Part 14 B: three tabs.
 *
 *   Networks  networks.internal_networks: what counts as inside, besides the LAN (always in).
 *   Servers   networks.servers: which device runs each service (none = any device).
 *   Ports     networks.service_ports: the ports each service uses.
 *
 * Every change is staged and written with one "Save changes": PUT /ids/settings with
 * {networks: {...}} holding only what changed. A list is sent whole (the peer replaces
 * it); ports only for the services that changed. Field, alias menu, rows, edit window
 * and footer are the Excluded devices window's (list-window standard), reusing its
 * ids-we-* styles; the tabs and port rows reuse Inspection's ids-wt-* styles.
 */
(function () {
    if (!window.IdsWin) return;

    const MAX_ADDRS = 64;
    const SERVER_LABEL = {
        web: 'Web', mail: 'Mail', dns: 'Name lookups (DNS)', sql: 'Database (SQL)', ssh: 'SSH', remote_desktop: 'Remote desktop',
    };
    const PORT_LABEL = {
        web: 'Web', tls: 'Secure web (TLS)', ssh: 'SSH', mail: 'Mail', dns: 'Name lookups (DNS)',
        ftp: 'File transfer (FTP)', remote_desktop: 'Remote desktop',
    };
    const TABS = [['nets', 'Networks'], ['srv', 'Servers'], ['ports', 'Ports']];
    const HELP = {
        nets: 'Enter a network or an address, like 10.9.0.0/16.',
        srv: 'Enter an address, like 192.168.100.10.',
    };
    const TIP = {
        nets: 'Most rules look for attacks coming from outside toward the devices inside. A device on a network that is not listed here counts as outside, so attacks on it can go unseen. Add the other networks this router reaches, like a second office behind a router on your LAN.',
        srv: 'Rules for attacks on a service, like a web server, then check only the devices listed for it. With none listed, every device is checked: more is found, but a device that does not run the service can raise threats too.',
        ports: 'Rules for a service look at these ports. Change one only if a server uses an unusual port, like a web server on 8080.',
    };
    const IPRE = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;

    const titled = (k) => String(k).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
    const serverLabel = (k) => SERVER_LABEL[k] || titled(k);
    const portLabel = (k) => PORT_LABEL[k] || titled(k);
    // The peer keeps one address as a /32 and a range as 8000:8100; the page shows 192.168.1.5 and 8000-8100.
    const shownAddr = (v) => String(v || '').replace(/\/32$/, '');
    const shownPorts = (list) => (list || []).map((p) => String(p).replace(':', '-')).join(', ');

    function okAddr(v) {
        const [a, m] = v.split('/');
        return IPRE.test(a || '') && (m === undefined || (/^\d+$/.test(m) && +m >= 8 && +m <= 32));
    }

    // "80, 8000-8100" -> {list: ['80', '8000-8100']} or {err}.
    function checkPorts(v) {
        const parts = v.split(/[\s,]+/).filter(Boolean);
        if (!parts.length) return { err: 'Enter at least one port.' };
        if (parts.length > 20) return { err: 'Up to 20 ports.' };
        for (const p of parts) {
            const m = p.match(/^(\d+)(?:[-:](\d+))?$/);
            if (!m || +m[1] < 1 || +m[1] > 65535 || (m[2] && (+m[2] <= +m[1] || +m[2] > 65535))) return { err: `Invalid port: ${p}.` };
        }
        return { list: parts.map((p) => p.replace(':', '-')) };
    }

    function open(ctx, win) {
        const N = ctx.N;
        const esc = N.esc;
        const S = {
            tab: 'nets', items: { nets: [], srv: [] }, aliases: [], aliasesFailed: false,
            types: Object.keys(SERVER_LABEL), portTypes: Object.keys(PORT_LABEL),
            limits: { nets: 50, srv: 100 },
            ports: {}, savedPorts: {}, defPorts: {}, perr: {}, pwarn: {},
            addL: null, add: { nets: newForm('nets', 'add'), srv: newForm('srv', 'add') },
            ov: null, menu: null, tip: null, tipPin: false,
            saving: false, saved: false, err: '', confirm: false,
        };
        let uidSeq = 0;
        let savedTimer = null;
        let tipTimer = null;

        win.body.innerHTML = '<div class="ids-win-msg">Loading.</div>';
        const ready = load();   // settles when the first load is done (the shell loads the next section after it)

        // ── Data ────────────────────────────────────────────────────────────

        async function putSettings(body) {
            let res;
            try {
                res = await fetch(`/api/v2/client/peers/${encodeURIComponent(ctx.peerId)}/ids/settings`, {
                    method: 'PUT',
                    credentials: 'same-origin',
                    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
            } catch (e) {
                throw new Error('Network error');
            }
            N.api.bust();   // settings changed: other windows must re-read them
            let data = null;
            try { data = await res.json(); } catch (e) { /* empty body */ }
            if (!res.ok) throw new Error(data && typeof data.detail === 'string' ? data.detail : 'Request failed');
            return data;
        }

        // Only address aliases (type normal): the peer refuses any other type here.
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

        function fromServer(it, list) {
            return {
                uid: `s${it.id}`, id: it.id,
                kind: it.alias_id ? 'alias' : 'address',
                value: it.alias_id ? '' : shownAddr(it.value), aliasId: it.alias_id || '',
                type: list === 'srv' ? it.server_type : '', p: null,
            };
        }

        // Takes a GET /ids/settings document into the window's state.
        function takeDoc(doc) {
            const net = ((doc && doc.settings) || {}).networks || {};
            const def = ((doc && doc.defaults) || {}).networks || {};
            const opt = (doc && doc.options) || {};
            S.items.nets = (net.internal_networks || []).map((it) => fromServer(it, 'nets'));
            S.items.srv = (net.servers || []).map((it) => fromServer(it, 'srv'));
            if (Array.isArray(opt['networks.server_types']) && opt['networks.server_types'].length) S.types = opt['networks.server_types'];
            if (Array.isArray(opt['networks.service_port_types']) && opt['networks.service_port_types'].length) S.portTypes = opt['networks.service_port_types'];
            const lim = opt.limits || {};
            if (lim.internal_networks > 0) S.limits.nets = lim.internal_networks;
            if (lim.servers > 0) S.limits.srv = lim.servers;
            S.savedPorts = {};
            S.defPorts = {};
            S.portTypes.forEach((k) => {
                S.savedPorts[k] = shownPorts((net.service_ports || {})[k]);
                S.defPorts[k] = shownPorts((def.service_ports || {})[k]);
            });
            S.ports = Object.assign({}, S.savedPorts);
            S.perr = {};
            S.pwarn = {};
            if (!S.types.includes(S.add.srv.type)) S.add.srv.type = S.types[0];
        }

        async function load() {
            try {
                const [doc, aliases] = await Promise.all([
                    N.api.settings(ctx.peerId),
                    loadAliases().catch(() => null),
                ]);
                takeDoc(doc);
                S.aliases = aliases || [];
                S.aliasesFailed = !aliases;
            } catch (e) {
                win.body.innerHTML = '<div class="ids-win-msg">Couldn\'t load.</div>';
                return;
            }
            build();
        }

        // ── Small helpers ───────────────────────────────────────────────────

        function newForm(list, mode) {
            return { list, mode, value: '', type: 'web', err: '', warn: '', dd: false };
        }

        const aliasById = (id) => S.aliases.find((a) => a.id === id);
        const aliasLabel = (id) => (aliasById(id) || {}).name || id;
        const strip = (e) => { const { p, orig, ...rest } = e; return rest; };
        const itemKey = (e) => JSON.stringify([e.kind, e.kind === 'alias' ? e.aliasId : e.value, e.type]);
        const fsKey = (fs) => JSON.stringify([fs.value.trim().toLowerCase(), fs.type]);
        const isAlias = (fs) => fs.value.trim().startsWith('@');
        const pendingItems = () => S.items.nets.concat(S.items.srv).filter((e) => e.p);
        const pendingPorts = () => S.portTypes.filter((k) => S.ports[k] !== S.savedPorts[k]);
        const pendingCount = () => pendingItems().length + pendingPorts().length;
        const liveCount = (l) => S.items[l].filter((e) => e.p !== 'del').length;

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

        function parse(fs) {
            const parts = fs.value.split(',').map((p) => p.trim()).filter(Boolean);
            if (!parts.length) return { err: HELP[fs.list] };
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
            if (parts.some((p) => !okAddr(p))) return { err: HELP[fs.list] };
            return { addrs: parts.map(shownAddr) };
        }

        // Full check (Add / Update). Returns the parsed value or null with the message set.
        function checkForm(fs) {
            const r = parse(fs);
            fs.err = fs.warn || r.err || (fs.mode === 'edit' && r.addrs && r.addrs.length > 1 ? 'One address when editing.' : '');
            fs.dd = false;
            return fs.err ? null : r;
        }

        // ── Form (the same block for Add and for Edit) ──────────────────────

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

        const multiOff = (fs) => fs.mode === 'edit' || isAlias(fs);
        const formName = (fs) => (fs.mode === 'edit' ? 'edit' : `add-${fs.list}`);

        // The service picker: our own menu (never the browser's select).
        function typeHtml(fs) {
            const key = formName(fs);
            const on = S.menu === key;
            const menu = on ? '<div class="ids-menu ids-wm-menu ids-wn-menu" role="listbox">' + S.types.map((k) =>
                `<button type="button" role="option" class="${fs.type === k ? 'ids-sel' : ''}" data-ty="${k}"><span>${esc(serverLabel(k))}</span>` +
                `${fs.type === k ? '' + IdsIcon('check') + '' : ''}</button>`).join('') + '</div>' : '';
            return '<span class="ids-we-lbl ids-we-first">Service</span>' +
                `<div class="ids-wm-dsel ids-wn-dsel"><button type="button" class="ids-wm-dbtn ids-wn-dbtn${on ? ' ids-wm-open' : ''}" data-menu="${key}" ` +
                `aria-haspopup="listbox" aria-expanded="${on}">${esc(serverLabel(fs.type))}${IdsIcon('chevron-down')}</button>${menu}</div>` +
                '<span class="ids-we-lbl">Device</span>';
        }

        function formHtml(fs) {
            const cls = (fs.err ? ' ids-we-bad' : fs.warn ? ' ids-we-warnb' : '') + (isAlias(fs) ? ' ids-we-inalias' : '');
            const ph = fs.list === 'nets' ? '10.9.0.0/16, 172.16.5.0/24' : '192.168.100.10';
            return `<div data-form="${formName(fs)}">` + (fs.list === 'srv' ? typeHtml(fs) : '') +
                '<div class="ids-we-acwrap">' +
                '<button type="button" class="ids-we-atb" data-x="dd" title="Pick an alias" aria-label="Pick an alias">@</button>' +
                `<input class="ids-we-inp ids-we-main${cls}" data-f="value" value="${esc(fs.value)}" placeholder="${ph}" autocomplete="off" spellcheck="false">` +
                (fs.mode === 'edit' ? '' :   // editing is one address: no "+", no comma
                    `<button type="button" class="ids-we-mlb${multiOff(fs) ? ' ids-we-disabled' : ''}" data-x="multi" title="Add multiple addresses" aria-label="Add multiple addresses">${IdsIcon('plus')}</button>`) +
                `<div data-live="dd">${ddHtml(fs)}</div></div>` +
                `<div data-live="msg">${msgHtml(fs)}</div>` +
                '</div>';
        }

        // Update one form in place (typing must not lose focus or the phone keyboard).
        function liveForm(fe, fs) {
            const inp = fe.querySelector('[data-f="value"]');
            if (inp.value !== fs.value) inp.value = fs.value;
            inp.classList.toggle('ids-we-bad', !!fs.err);
            inp.classList.toggle('ids-we-warnb', !fs.err && !!fs.warn);
            inp.classList.toggle('ids-we-inalias', isAlias(fs));
            const m = fe.querySelector('.ids-we-mlb');
            if (m) m.classList.toggle('ids-we-disabled', multiOff(fs));
            fe.querySelector('[data-live="dd"]').innerHTML = ddHtml(fs);
            fe.querySelector('[data-live="msg"]').innerHTML = msgHtml(fs);
        }

        function formOf(node) {
            const fe = node.closest && node.closest('[data-form]');
            if (!fe) return [null, null];
            const f = fe.dataset.form;
            if (f === 'edit') return [fe, S.ov && S.ov.k === 'edit' ? S.ov.fs : null];
            return [fe, S.add[f.slice(4)]];
        }

        // ── Drawing ─────────────────────────────────────────────────────────

        let pane;

        function tip(k) {
            const on = S.tip === k;
            return `<span class="ids-wt-tip${on ? ' ids-wt-open' : ''}" data-k="${k}">` +
                `<button type="button" class="ids-wt-ib" data-tip="${k}" aria-label="More about this" aria-expanded="${on}">${IdsIcon('circle-info')}</button>` +
                `<span class="ids-wt-bub" role="tooltip">${esc(TIP[k])}</span></span>`;
        }

        function setTip(k) {
            S.tip = k;
            win.body.querySelectorAll('.ids-wt-tip').forEach((t) => {
                t.classList.toggle('ids-wt-open', t.dataset.k === k);
                t.querySelector('.ids-wt-ib').setAttribute('aria-expanded', String(t.dataset.k === k));
            });
        }

        function build() {
            win.body.innerHTML = '<div class="ids-wt-tabs" role="tablist"></div><div class="ids-wn-pane"></div>';
            pane = win.body.querySelector('.ids-wn-pane');
            win.body.addEventListener('click', onClick);
            win.body.addEventListener('input', onInput);
            win.body.addEventListener('focusout', onFocusOut);
            win.body.addEventListener('keydown', onKeydown);
            win.body.addEventListener('mousedown', keepFocus);
            win.body.addEventListener('mouseover', onTipOver);
            win.body.addEventListener('mouseout', onTipOut);
            win.foot.addEventListener('click', onClick);
            document.addEventListener('click', onDocClick);
            document.addEventListener('keydown', onEscape, true);
            if (win.isDirty) win.isDirty(() => S.saving || pendingCount() > 0);
            win.beforeClose(() => {
                if (S.saving) return false;
                if (!pendingCount()) return true;
                S.confirm = true;
                drawFoot();
                return false;
            });
            draw();
        }

        function drawTabs() {
            win.body.querySelector('.ids-wt-tabs').innerHTML = TABS.map(([k, l]) =>
                `<button type="button" role="tab" data-tab="${k}" aria-selected="${S.tab === k}" class="${S.tab === k ? 'ids-wt-on' : ''}">${l}</button>`).join('');
        }

        // Add: a collapsed heading and plus; it opens the Add window.
        function addHtml(l) {
            if (ctx.readonly) return '';
            return '<section class="ids-sec ids-we-add ids-we-shut">' +
                `<button type="button" class="ids-we-toggle" data-x="toggle" data-l="${l}" title="Add">` +
                `<span class="ids-sec-h">Add</span>${IdsIcon('plus')}</button></section>`;
        }

        // The Add window (a page modal, like Edit).
        function drawAddOv() {
            const l = S.addL;
            if (!l || ctx.readonly || S.tab !== l || !win.el.isConnected) {
                if (ova) { ova.remove(); ova = null; }
                return;
            }
            if (!ova) ova = mountOv();
            const help = l === 'nets' ? 'One or more networks separated by commas, or an alias.' : 'The service, then the device that runs it.';
            const old = ova.querySelector('.ids-we-ovb');
            const top = old ? old.scrollTop : 0;
            ova.innerHTML = '<div class="ids-we-ovcard" role="dialog" aria-modal="true">' +
                `<div class="modal-header ids-we-ovh"><h2>${l === 'nets' ? 'Add network' : 'Add server'}</h2><button type="button" class="modal-close" data-x="addclose" aria-label="Close">&times;</button></div>` +
                `<div class="ids-we-ovb"><section class="ids-sec"><h3 class="ids-sec-h">Add</h3><p class="ids-sec-help">${help}</p>` +
                `<div class="ids-sec-body">${formHtml(S.add[l])}</div></section></div>` +
                '<div class="ids-we-ovf"><button type="button" class="ids-btn" data-x="addclose">Cancel</button>' +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="add">${IdsIcon('plus')}Add</button></div></div>`;
            ova.querySelector('.ids-we-ovb').scrollTop = top;
        }

        const BADGE = {
            add: '<span class="ids-we-pend">Not saved</span>',
            edit: '<span class="ids-we-pend">Changed</span>',
            del: '<span class="ids-we-pend ids-we-del">Will be removed</span>',
        };

        function rowHtml(l, e, i) {
            const al = e.kind === 'alias';
            const v = al ? `<span class="ids-we-al">@${esc(aliasLabel(e.aliasId))}</span>` : `<span class="ids-mono">${esc(e.value)}</span>`;
            const tag = l === 'srv' ? `<span class="ids-we-tag ids-wn-svc">${esc(serverLabel(e.type))}</span>`
                : `<span class="ids-we-tag">${al ? 'Alias' : 'Network'}</span>`;
            const ic = (attr, icon, title) =>
                `<button type="button" class="ids-we-ic" data-${attr}="${l}:${i}" title="${title}" aria-label="${title}">${IdsIcon(icon)}</button>`;
            let acts = '';
            if (e.p === 'del') acts = ic('undo', 'rotate-left', 'Keep it');
            else if (!ctx.readonly) {
                acts = (e.p === 'edit' ? ic('revert', 'rotate-left', 'Undo the change') : '') +
                    ic('edit', 'pen', 'Edit') + ic('del', 'trash', 'Remove');
            }
            return `<div class="ids-we-row${e.p === 'del' ? ' ids-we-gone' : ''}">` +
                `<div class="ids-we-main2"><div class="ids-we-t"><span class="ids-we-v">${v}</span>${tag}${BADGE[e.p] || ''}</div></div>` +
                `<div class="ids-we-acts">${acts}</div></div>`;
        }

        function listHtml(l) {
            const title = l === 'nets' ? 'Your networks' : 'Servers';
            const desc = l === 'nets' ? 'Treated as inside your network.' : 'Which device runs each service. None listed means any device.';
            const lan = l === 'nets' ? '<div class="ids-we-row"><div class="ids-we-main2"><div class="ids-we-t"><span class="ids-we-v">Your LAN</span>' +
                '<span class="ids-we-tag">LAN</span></div><div class="ids-we-d">Always included.</div></div><div class="ids-we-acts"></div></div>' : '';
            const rows = S.items[l].map((e, i) => rowHtml(l, e, i)).join('');
            return `<section class="ids-sec"><h3 class="ids-sec-h">${title}</h3>` +
                `<p class="ids-sec-help ids-wn-help">${desc}${tip(l)}</p>` +
                `<p class="ids-sec-help">${liveCount(l)} of ${S.limits[l]}.</p>` +
                `<div class="ids-sec-body">${lan}${rows || (lan ? '' : '<div class="ids-we-empty">None.</div>')}</div></section>`;
        }

        function portsHtml() {
            const ro = ctx.readonly ? ' disabled' : '';
            return '<section class="ids-sec"><h3 class="ids-sec-h">Service ports</h3>' +
                `<p class="ids-sec-help ids-wn-help">Which ports each service uses.${tip('ports')}</p><div class="ids-sec-body">` +
                S.portTypes.map((k) => `<div class="ids-wt-row"><div class="ids-wt-lt"><div class="ids-wt-l">${esc(portLabel(k))}` +
                    `<span class="ids-wt-cdot" data-pdot="${k}" title="Changed from default" hidden></span></div></div>` +
                    `<span class="ids-wt-stt" data-pst="${k}"></span>` +
                    `<span class="ids-wt-fv"><input class="ids-wn-port" data-port="${k}" value="${esc(S.ports[k])}" autocomplete="off" spellcheck="false" aria-label="${esc(portLabel(k))} ports"${ro}></span>` +
                    `<div class="ids-wt-msg" data-pmsg="${k}" hidden></div></div>`).join('') +
                '</div></section>';
        }

        function draw() {
            S.confirm = false;
            drawTabs();
            pane.innerHTML = S.tab === 'ports' ? portsHtml() : addHtml(S.tab) + listHtml(S.tab);
            paintPorts();
            drawFoot();
            drawAddOv();
        }

        // Port rows change in place: a typed value is never redrawn.
        function paintPorts() {
            pane.querySelectorAll('[data-pst]').forEach((el) => {
                const k = el.dataset.pst;
                let h = '';
                if (S.ports[k] !== S.savedPorts[k]) {
                    h = '<span class="ids-wt-badge">Not saved</span>' + (ctx.readonly ? ''
                        : `<button type="button" class="ids-wt-undo" data-pundo="${k}" title="Undo" aria-label="Undo">${IdsIcon('rotate-left')}</button>`);
                } else if (S.ports[k] !== S.defPorts[k] && S.defPorts[k] && !ctx.readonly) {
                    h = `<button type="button" class="ids-wt-lnk" data-preset="${k}" title="Reset to default">Reset</button>`;
                }
                if (el.innerHTML !== h) el.innerHTML = h;
            });
            pane.querySelectorAll('[data-pdot]').forEach((el) => { el.hidden = !S.defPorts[el.dataset.pdot] || S.ports[el.dataset.pdot] === S.defPorts[el.dataset.pdot]; });
            pane.querySelectorAll('[data-pmsg]').forEach((el) => {
                const k = el.dataset.pmsg, e = S.perr[k], a = S.pwarn[k];
                el.hidden = !(e || a);
                el.classList.toggle('ids-wt-amber', !e && !!a);
                el.innerHTML = e ? `${IdsIcon('circle-exclamation')}${esc(e)}` : a ? `${IdsIcon('triangle-exclamation')}${esc(a)}` : '';
            });
            pane.querySelectorAll('[data-port]').forEach((el) => {
                const k = el.dataset.port;
                el.classList.toggle('ids-wn-bad', !!S.perr[k]);
                el.classList.toggle('ids-wn-warnb', !S.perr[k] && !!S.pwarn[k]);
            });
        }

        function drawFoot() {
            const n = pendingCount();
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
                win.foot.innerHTML = '<div class="ids-foot-status"><b class="ids-we-strong">' + IdsIcon('circle-notch', {spin: true}) + ' Saving.</b><small>Takes under a minute.</small></div>' + btns(true);
                return;
            }
            let status;
            if (S.saved && !n) status = '<span class="ids-we-ok">' + IdsIcon('check') + ' Saved.</span>';
            else if (n) status = `<b class="ids-we-strong">${n} unsaved ${n === 1 ? 'change' : 'changes'}.</b><small>Changes take effect in under a minute.</small>`;
            else status = '';
            if (S.err) status += `<span class="ids-we-ferr">${esc(S.err)}</span>`;
            win.foot.innerHTML = `<div class="ids-foot-status">${status}</div>` + btns(!n || ctx.readonly || Object.keys(S.perr).length > 0);
        }

        // ── Sub-windows: edit one item, or paste many addresses ─────────────

        let ov = null;
        let ova = null;   // the Add window

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

        const multiKey = (o) => o.rows.map((r) => r.trim()).filter(Boolean).join(',');
        function ovDirty() {
            if (!S.ov) return false;
            return S.ov.k === 'edit' ? fsKey(S.ov.fs) !== S.ov.base : multiKey(S.ov) !== S.ov.base;
        }

        function ovInner() {
            const o = S.ov;
            if (o.k === 'edit') {
                return `<div class="modal-header ids-we-ovh"><h2>${o.fs.list === 'nets' ? 'Edit network' : 'Edit server'}</h2><button type="button" class="modal-close" data-x="ovclose" aria-label="Close">&times;</button></div>` +
                    '<div class="ids-we-ovb"><section class="ids-sec"><h3 class="ids-sec-h">Edit</h3>' +
                    `<div class="ids-sec-body">${formHtml(o.fs)}</div></section></div>` +
                    '<div class="ids-we-ovf"><button type="button" class="ids-btn" data-x="ovclose">Cancel</button>' +
                    `<button type="button" class="ids-btn ids-btn-primary" data-x="ovsave"${ovDirty() ? '' : ' disabled'}>Update</button></div>`;
            }
            return '<div class="modal-header ids-we-ovh"><h2>Addresses</h2><button type="button" class="modal-close" data-x="ovclose" aria-label="Close">&times;</button></div>' +
                '<div class="ids-we-ovb"><div class="ids-we-rowsh"><span class="ids-we-lbl ids-we-first">Addresses and networks</span>' +
                '<button type="button" class="ids-btn" data-x="rowadd">' + IdsIcon('plus') + 'Add address</button></div>' +
                `<div data-rows>${o.rows.map((r) => '<div class="ids-we-rowx">' +
                    `<input class="ids-we-inp ids-mono" data-ma value="${esc(r)}" placeholder="Like 192.168.10.5 or 192.168.50.0/24" autocomplete="off" spellcheck="false">` +
                    '<button type="button" class="ids-we-ic" data-x="rowdel" title="Remove" aria-label="Remove">' + IdsIcon('trash') + '</button></div>').join('')}</div></div>` +
                '<div class="ids-we-ovf"><button type="button" class="ids-btn" data-x="ovclose">Cancel</button>' +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="ovmulti"${ovDirty() ? '' : ' disabled'}>Save changes</button></div>`;
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

        function readRows() {
            if (!S.ov || S.ov.k !== 'multi' || !ov) return;
            S.ov.rows = [...ov.querySelectorAll('[data-ma]')].map((i) => i.value);
        }

        function openEdit(l, i) {
            const it = S.items[l][i];
            const fs = newForm(l, 'edit');
            fs.value = it.kind === 'alias' ? `@${aliasLabel(it.aliasId)}` : it.value;
            fs.type = it.type || S.types[0];
            S.ov = { k: 'edit', l, i, fs, base: fsKey(fs) };
            S.menu = null;
            drawOv();
            N.focusDialog(ov);
        }

        function openMulti(l) {
            const rows = S.add[l].value.split(',').map((p) => p.trim()).filter(Boolean);
            S.ov = { k: 'multi', l, rows: rows.length ? rows : [''] };
            S.ov.base = multiKey(S.ov);
            drawOv();
        }

        function doMulti() {
            readRows();
            if (!ovDirty()) return;
            const fs = S.add[S.ov.l];
            fs.value = S.ov.rows.map((p) => p.trim()).filter(Boolean).join(', ');
            fs.err = ''; fs.warn = '';
            S.ov = null;
            drawOv();
            draw();
        }

        function doEdit() {
            if (!S.ov || S.ov.k !== 'edit' || !ovDirty()) return;
            const { fs, l, i } = S.ov;
            const r = checkForm(fs);
            if (!r) { drawOv(); return; }
            const old = S.items[l][i];
            const nu = {
                ...strip(old),
                kind: r.alias ? 'alias' : 'address',
                aliasId: r.alias ? r.alias.id : '',
                value: r.addrs ? r.addrs[0] : '',
                type: l === 'srv' ? fs.type : '',
            };
            if (dupOf(l, nu, i)) { fs.err = 'Already in the list.'; drawOv(); return; }
            setItem(l, i, nu);
            S.ov = null;
            S.menu = null;
            drawOv();
            draw();
        }

        // A staged edit; editing back to the saved values drops the badge.
        function setItem(l, i, nu) {
            const old = S.items[l][i];
            S.saved = false;
            S.err = '';
            if (old.p === 'add') { S.items[l][i] = { ...nu, p: 'add' }; return; }
            const orig = old.orig || strip(old);
            S.items[l][i] = itemKey(nu) === itemKey(orig) ? orig : { ...nu, p: 'edit', orig };
        }

        // ── Staging ─────────────────────────────────────────────────────────

        const dupOf = (l, e, skip) => S.items[l].some((x, j) => j !== skip && x.p !== 'del' && itemKey(x) === itemKey(e));

        function doAdd(l) {
            const fs = S.add[l];
            const r = checkForm(fs);
            if (!r) { drawAddOv(); return; }
            const type = l === 'srv' ? fs.type : '';
            const made = (r.alias
                ? [{ kind: 'alias', aliasId: r.alias.id, value: '', type }]
                : r.addrs.map((a) => ({ kind: 'address', value: a, aliasId: '', type })))
                .filter((m, k, all) => !dupOf(l, m, -1) && all.findIndex((o) => itemKey(o) === itemKey(m)) === k);
            if (!made.length) { fs.err = 'Already in the list.'; drawAddOv(); return; }
            if (liveCount(l) + made.length > S.limits[l]) {
                fs.err = `Up to ${S.limits[l]}.`;
                drawAddOv();
                return;
            }
            made.reverse().forEach((m) => S.items[l].unshift({ uid: `n${++uidSeq}`, id: null, ...m, p: 'add' }));
            S.saved = false;
            S.err = '';
            S.add[l] = newForm(l, 'add');
            S.add[l].type = type || S.types[0];
            draw();   // the Add window stays open for the next one
            const inp = ova && ova.querySelector('[data-f="value"]');
            if (inp) inp.focus();
        }

        function discard() {
            ['nets', 'srv'].forEach((l) => {
                S.items[l] = S.items[l].filter((e) => e.p !== 'add').map((e) => e.orig || e);
                S.items[l].forEach((e) => { e.p = null; });
            });
            S.ports = Object.assign({}, S.savedPorts);
            S.perr = {};
            S.pwarn = {};
            S.err = '';
            S.saved = false;
            win.close(true);
        }

        // ── Ports ───────────────────────────────────────────────────────────

        function commitPort(el) {
            const k = el.dataset.port;
            if (S.pwarn[k]) { S.perr[k] = S.pwarn[k]; delete S.pwarn[k]; paintPorts(); drawFoot(); return; }
            const r = checkPorts(el.value);
            if (r.err) { S.perr[k] = r.err; paintPorts(); drawFoot(); return; }
            delete S.perr[k];
            const v = r.list.join(', ');
            el.value = v;
            if (S.ports[k] !== v) { S.ports[k] = v; S.saved = false; S.err = ''; }
            paintPorts();
            drawFoot();
        }

        // ── Save: one PUT with what changed ─────────────────────────────────

        function listBody(l) {
            return S.items[l].filter((e) => e.p !== 'del').map((e) => {
                const b = e.kind === 'alias' ? { alias_id: e.aliasId } : { value: e.value };
                return l === 'srv' ? { server_type: e.type, ...b } : b;
            });
        }

        const terse = (m) => String(m || 'Request failed').replace(/\.?\s*$/, '.');

        async function save() {
            const n = pendingCount();
            if (!n || S.saving || ctx.readonly) return;
            const bad = Object.keys(S.perr);
            if (bad.length) {
                S.tab = 'ports';
                draw();
                const el = pane.querySelector(`[data-port="${bad[0]}"]`);
                if (el) el.focus();
                return;
            }
            const networks = {};
            if (S.items.nets.some((e) => e.p)) networks.internal_networks = listBody('nets');
            if (S.items.srv.some((e) => e.p)) networks.servers = listBody('srv');
            const ports = pendingPorts();
            if (ports.length) networks.service_ports = Object.fromEntries(ports.map((k) => [k, checkPorts(S.ports[k]).list]));
            S.saving = true;
            S.saved = false;
            S.err = '';
            S.confirm = false;
            win.setBusy(true);
            drawFoot();
            let failed = null;
            try {
                await putSettings({ networks });
            } catch (e) {
                failed = terse(e.message);
            }
            let fresh = null;
            if (!failed) {
                try { fresh = await N.api.settings(ctx.peerId); } catch (e) { fresh = null; }
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
                win.body.innerHTML = '<div class="ids-win-msg">Saved. Couldn\'t reload.</div>';
                win.foot.innerHTML = '<div class="ids-foot-status">Saved.</div><div class="ids-foot-btns"><button type="button" class="ids-btn" data-x="leave">Close</button></div>';
                return;
            }
            takeDoc(fresh);
            S.saved = true;
            clearTimeout(savedTimer);
            savedTimer = setTimeout(() => { S.saved = false; if (win.el.isConnected && !S.saving) drawFoot(); }, 2000);
            draw();
        }

        // The same Create alias window as the firewall page; the new alias is picked on success.
        async function reloadAliases() {
            try { S.aliases = await loadAliases(); S.aliasesFailed = false; } catch (e) { /* keep the old list */ }
        }

        function createAlias(fe, fs) {
            if (!window.IdsAliasCreate) { ctx.toast('err', 'Couldn\'t open the window.'); return; }
            fs.dd = false;
            liveForm(fe, fs);
            IdsAliasCreate.open({
                peerId: ctx.peerId,
                entries: isAlias(fs) ? [] : fs.value.split(/[,\s]+/).filter(Boolean),
                onCreated: async (name) => {
                    await reloadAliases();
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
                    await reloadAliases();
                    if (picked) { fs.value = `@${saved.name}`; fs.err = ''; fs.warn = ''; }
                    if (fe.isConnected) {
                        liveForm(fe, fs);
                        if (fs.mode === 'edit') refreshOvBtn();
                    }
                    if (S.tab !== 'ports' && !S.ov) draw();
                },
            });
        }

        // ── Events ──────────────────────────────────────────────────────────

        // Like the firewall page, an alias is picked on mousedown (the field keeps focus).
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
            if (S.menu) {
                const inEdit = S.menu === 'edit';
                S.menu = null;
                if (inEdit) drawOv(); else drawAddOv();
                changed = true;
            }
            [[S.add.nets, ova], [S.add.srv, ova], [S.ov && S.ov.fs, ov]].forEach(([fs, root]) => {
                if (!fs || !fs.dd) return;
                fs.dd = false;
                const fe = root && root.querySelector(`[data-form="${formName(fs)}"]`);
                if (fe) liveForm(fe, fs);
                changed = true;
            });
            return changed;
        }

        function onClick(ev) {
            if (ov && ev.target === ov && ov.dataset.downOut) { S.ov = null; S.menu = null; drawOv(); return; }
            if (ova && ev.target === ova && ova.dataset.downOut) { S.addL = null; S.menu = null; drawAddOv(); return; }
            const b = ev.target.closest('button');
            if (!b) return;
            const d = b.dataset;
            const x = d.x;
            const [fe, fs] = formOf(b);
            if (S.confirm && !['keep', 'leave'].includes(x)) { S.confirm = false; drawFoot(); }
            if (d.tip) {
                clearTimeout(tipTimer);
                if (S.tipPin && S.tip === d.tip) { S.tipPin = false; setTip(null); } else { S.tipPin = true; setTip(d.tip); }
                return;
            }
            if (d.tab) {
                if (S.tab !== d.tab) { S.tab = d.tab; S.menu = null; S.tip = null; S.tipPin = false; draw(); }
                return;
            }
            if (d.menu && fs) {
                S.menu = S.menu === d.menu ? null : d.menu;
                if (fs.mode === 'edit') drawOv(); else drawAddOv();
                return;
            }
            if (d.ty && fs) {
                fs.type = d.ty;
                S.menu = null;
                if (fs.mode === 'edit') { drawOv(); refreshOvBtn(); } else drawAddOv();
                return;
            }
            if (x === 'dd' && fs) {
                fs.dd = !fs.dd;
                liveForm(fe, fs);
            } else if (x === 'mkalias' && fs) createAlias(fe, fs);
            else if (x === 'multi' && fs) { if (!multiOff(fs)) openMulti(fs.list); }
            else if (x === 'add' && fs) doAdd(fs.list);
            else if (x === 'toggle') {
                S.addL = d.l;
                drawAddOv();
                N.focusDialog(ova);
            } else if (x === 'addclose') { S.addL = null; S.menu = null; drawAddOv(); } else if (x === 'ovsave') doEdit();
            else if (x === 'ovmulti') doMulti();
            else if (x === 'rowadd') { readRows(); S.ov.rows.push(''); drawOv(); const l = ov.querySelectorAll('[data-ma]'); l[l.length - 1].focus(); }
            else if (x === 'rowdel') {
                readRows();
                const idx = [...ov.querySelectorAll('.ids-we-rowx')].indexOf(b.closest('.ids-we-rowx'));
                S.ov.rows.splice(idx, 1);
                if (!S.ov.rows.length) S.ov.rows.push('');
                drawOv();
                refreshOvBtn();
            } else if (x === 'ovclose') { S.ov = null; S.menu = null; drawOv(); }
            else if (x === 'save') save();
            else if (x === 'discard') discard();
            else if (x === 'keep') { S.confirm = false; drawFoot(); }
            else if (x === 'leave') win.close(true);
            else if (d.preset) {
                S.ports[d.preset] = S.defPorts[d.preset];
                delete S.perr[d.preset]; delete S.pwarn[d.preset];
                S.saved = false;
                draw();
            } else if (d.pundo) {
                S.ports[d.pundo] = S.savedPorts[d.pundo];
                delete S.perr[d.pundo]; delete S.pwarn[d.pundo];
                draw();
            } else {
                const ref = d.edit || d.del || d.undo || d.revert;
                if (!ref) return;
                const [l, si] = ref.split(':');
                const i = +si;
                const it = S.items[l][i];
                if (d.edit) { openEdit(l, i); return; }
                if (d.del) { if (it.p === 'add') S.items[l].splice(i, 1); else it.p = 'del'; S.saved = false; }
                if (d.undo) it.p = it.orig ? 'edit' : null;
                if (d.revert) S.items[l][i] = it.orig;
                S.err = '';
                draw();
            }
        }

        function onInput(ev) {
            const el = ev.target;
            if (el.hasAttribute('data-ma')) { readRows(); refreshOvBtn(); return; }
            if (el.dataset.port !== undefined) {
                const k = el.dataset.port;
                const bad = el.value.match(/[^\d,\s:-]/);
                delete S.perr[k];
                if (bad) S.pwarn[k] = `"${bad[0] === ' ' ? 'Space' : bad[0]}" not allowed.`; else delete S.pwarn[k];
                paintPorts();
                drawFoot();
                return;
            }
            const [fe, fs] = formOf(el);
            if (el.dataset.f !== 'value' || !fs) return;
            fs.value = el.value;
            if (fs.mode === 'edit' && fs.value.includes(',')) {
                // A comma would start a second address: keep the first one and say why, at once.
                fs.value = el.value = fs.value.slice(0, fs.value.indexOf(','));
                fs.err = '';
                fs.warn = 'One address when editing.';
                fs.dd = false;
            } else {
                fs.err = '';
                fs.warn = badChar(fs.value);
                fs.dd = isAlias(fs) && !fs.warn;
            }
            liveForm(fe, fs);
            if (fs.mode === 'edit') refreshOvBtn();
        }

        function onFocusOut(ev) {
            const el = ev.target;
            if (!el.isConnected) return;   // a redraw removed the focused field: nothing was left by the user
            if (el.dataset && el.dataset.port !== undefined) { commitPort(el); return; }
            const [fe, fs] = formOf(el);
            if (!el.dataset || el.dataset.f !== 'value' || !fs) return;
            const to = ev.relatedTarget;
            if (to && to.closest && to.closest('.ids-we-acwrap, .ids-we-ovf, .ids-wn-dsel')) return;
            if (fs.value.trim() && !fs.warn) {
                const r = parse(fs);
                fs.err = r.err || (fs.mode === 'edit' && r.addrs && r.addrs.length > 1 ? 'One address when editing.' : '');
                fs.dd = false;
                liveForm(fe, fs);
            }
        }

        function onKeydown(ev) {
            if (ev.target.tagName !== 'INPUT' || ev.key !== 'Enter') return;
            ev.preventDefault();
            if (ev.target.hasAttribute('data-ma')) return;
            if (ev.target.dataset.port !== undefined) { ev.target.blur(); return; }
            const [, fs] = formOf(ev.target);
            if (!fs) return;
            if (fs.mode === 'add') doAdd(fs.list); else doEdit();
        }

        // (i): opens after a short hover, pins on click (tooltip rule).
        function onTipOver(ev) {
            const b = ev.target.closest('.ids-wt-ib');
            if (!b || S.tipPin || S.tip === b.dataset.tip) return;
            clearTimeout(tipTimer);
            tipTimer = setTimeout(() => { if (!S.tipPin) setTip(b.dataset.tip); }, 450);
        }

        function onTipOut(ev) {
            const b = ev.target.closest('.ids-wt-ib');
            if (!b || (ev.relatedTarget && b.contains(ev.relatedTarget))) return;
            clearTimeout(tipTimer);
            if (!S.tipPin && S.tip) setTip(null);
        }

        function onDocClick(ev) {
            if (!win.el.isConnected) { document.removeEventListener('click', onDocClick); return; }
            const t = ev.target.closest ? ev.target : null;
            if (S.tip && !(t && t.closest('.ids-wt-tip')) && !(window.getSelection && String(window.getSelection()))) {
                S.tipPin = false;
                setTip(null);
            }
            if (t && (t.closest('.ids-we-acwrap') || t.closest('.ids-wn-dsel'))) return;
            closeMenus();
        }

        // Escape closes the open menu, then the sub-window, before the shell sees it.
        function onEscape(ev) {
            if (!win.el.isConnected) { document.removeEventListener('keydown', onEscape, true); return; }
            if (ev.key !== 'Escape') return;
            if (document.querySelector('#idsAcModal.active')) return;   // Create alias above: Escape is its own
            if (closeMenus()) { ev.stopPropagation(); return; }
            if (S.tip) { ev.stopPropagation(); S.tipPin = false; setTip(null); return; }
            if (S.ov) { ev.stopPropagation(); S.ov = null; drawOv(); return; }
            if (S.addL) { ev.stopPropagation(); S.addL = null; S.menu = null; drawAddOv(); return; }
            if (S.confirm) { ev.stopPropagation(); S.confirm = false; drawFoot(); }
        }
        return ready;
    }

    IdsWin.register('networks', { title: 'Networks', icon: 'network-wired', open });
})();
