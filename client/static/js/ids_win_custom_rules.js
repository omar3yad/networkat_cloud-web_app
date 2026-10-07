/**
 * IDS page window: Custom rules (the customer's own alerts).
 *
 * Design D2 (ids-part15e-custom-add.html): Name first with common rules that fill the whole rule,
 * Severity, "Alert when a device …" (one activity: a website or app, an address, a port), an Optional
 * box that narrows it down, a "You'll see" preview, and the live hint sentence above the window's buttons.
 * "+ Add" opens the form in its own window; Edit opens the same window with Update instead of Add.
 *
 * Changes are staged in memory and written on "Save changes" in ONE request
 * (POST /ids/custom-rules/batch: all or nothing).
 *
 * A rule is 1..5 conditions (AND): one app-layer condition (domain, tls_name, http_host,
 * http_user_agent), source, destination, port, protocol (agent docs/agent-api/ids-ips.md).
 */
(function () {
    if (!window.IdsWin) return;

    const DEFAULT_LIMIT = 200;
    const BATCH_MAX = 100;
    const NAME_MAX = 100;
    const SEVS = [['high', 'High'], ['medium', 'Medium'], ['low', 'Low']];
    const APP = ['domain', 'tls_name', 'http_host', 'http_user_agent'];
    // What the rule looks at (the API's app-layer types), in customer words.
    const LOOK = [
        ['domain', 'Website name', 'Any app that looks the name up.'],
        ['tls_name', 'Secure website', 'HTTPS connections.'],
        ['http_host', 'Plain website', 'HTTP, not encrypted.'],
        ['http_user_agent', 'Browser or app', 'The name a browser or app sends.'],
    ];
    const OPS = [['equals', 'Is'], ['ends_with', 'Ends with'], ['contains', 'Contains']];
    const PROTO = [['any', 'Any'], ['tcp', 'TCP'], ['udp', 'UDP']];
    const TO_OPTS = [['addr', 'Address'], ['internet', 'The internet'], ['lan', 'Your network']];
    const KINDS = [
        ['site', 'Visits a website or uses an app', 'For sites or apps you don\'t allow, like gambling or a fake login page. You get an alert each time a device reaches one, even over HTTPS.'],
        ['addr', 'Connects to an address or network', 'For a server, a range of addresses, or the internet as a whole. You get an alert when a device connects to it.'],
        ['port', 'Uses a port or service', 'For services like remote desktop (3389) or SSH (22). You get an alert when a device opens a connection on that port.'],
    ];
    // Every narrowing option is always shown; the one the activity already sets is greyed out.
    const MORE_ALL = [['from', 'These devices'], ['to', 'Address'], ['port', 'Port'], ['site', 'Website']];
    const TAKEN = { site: 'site', addr: 'to', port: 'port' };
    const TAKEN_WHY = {
        site: 'The activity above already sets the website.',
        to: 'The activity above already sets the address.',
        port: 'The activity above already sets the port.',
    };
    // Common rules: picking one fills the whole rule; the customer edits after.
    const SUGG = [
        ['Websites', [
            ['Gambling sites', { sev: 'medium', site: 'bet365.com', op: 'ends_with' }],
            ['Phishing login page', { sev: 'high', site: 'evil-login.com', op: 'ends_with' }],
            ['Crypto mining pool', { sev: 'high', site: 'nanopool.org', op: 'ends_with' }],
            ['File sharing upload', { sev: 'low', site: 'wetransfer.com', op: 'ends_with' }],
        ]],
        ['Remote access', [
            ['Remote desktop to the internet', { sev: 'high', proto: 'tcp', port: '3389', to: 'internet' }],
            ['SSH to the internet', { sev: 'medium', proto: 'tcp', port: '22', to: 'internet' }],
            ['TeamViewer or AnyDesk', { sev: 'medium', site: 'teamviewer.com', op: 'ends_with' }],
        ]],
        ['Network', [
            ['Tor network', { sev: 'high', proto: 'tcp', port: '9001', to: 'internet' }],
            ['Unapproved VPN', { sev: 'medium', proto: 'udp', port: '1194', to: 'internet' }],
            ['Camera calling home', { sev: 'low', from: 'addr', to: 'internet' }],
            ['Outside DNS server', { sev: 'medium', proto: 'udp', port: '53', to: 'internet' }],
            ['Direct mail sending', { sev: 'medium', proto: 'tcp', port: '25', to: 'internet' }],
        ]],
    ];
    // Common services: picking one fills the protocol and the port.
    const SERVICES = [
        ['Remote access', [['Remote desktop (RDP)', 'tcp', '3389'], ['SSH', 'tcp', '22'], ['Telnet', 'tcp', '23'], ['VNC screen sharing', 'tcp', '5900']]],
        ['File sharing', [['Windows file sharing (SMB)', 'tcp', '445'], ['FTP', 'tcp', '21']]],
        ['Mail', [['Mail sending (SMTP)', 'tcp', '25']]],
        ['Network', [['DNS', 'udp', '53'], ['OpenVPN', 'udp', '1194'], ['WireGuard VPN', 'udp', '51820'], ['Tor', 'tcp', '9001']]],
        ['Databases', [['MySQL', 'tcp', '3306'], ['SQL Server', 'tcp', '1433']]],
    ];
    const CAT_ICON = { 'Websites': 'globe', 'Remote access': 'desktop', 'Network': 'network-wired', 'File sharing': 'folder-open', 'Mail': 'envelope', 'Databases': 'database' };
    const ADDR_HELP = 'Enter an address like 192.168.100.23, a network, or pick an alias.';
    const IPRE = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;

    function okAddr(v) {
        const [a, m] = v.split('/');
        return IPRE.test(a || '') && (m === undefined || (/^\d+$/.test(m) && +m >= 8 && +m <= 32));
    }

    const blank = () => ({ name: '', sev: 'medium', on: true, look: 'domain', op: 'equals', site: '', from: '', fromV: '', to: '', toV: '', proto: 'any', port: '' });
    const label = (opts, k) => (opts.find(([x]) => x === k) || opts[0])[1];

    function open(ctx, win) {
        const N = ctx.N;
        const esc = N.esc;
        const S = {
            items: [], aliases: [], aliasesFailed: false, limit: DEFAULT_LIMIT,
            ov: null,
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

        // Only address aliases (type normal), like Excluded devices.
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

        const aliasById = (id) => S.aliases.find((a) => a.id === id);
        const aliasLabel = (id) => (aliasById(id) || {}).name || id;

        // Server item -> rule fields + which activity and which optional conditions it uses.
        function fromServer(it) {
            const r = blank();
            r.name = it.name || '';
            r.sev = it.severity || 'medium';
            r.on = it.enabled !== false;
            let app = false; let dest = false; let port = false; let src = false;
            const side = (c) => (c.alias_id ? `@${aliasLabel(c.alias_id)}` : (c.value || ''));
            (it.conditions || []).forEach((c) => {
                if (APP.includes(c.type)) {
                    app = true; r.look = c.type; r.op = c.operator || 'equals'; r.site = c.value || '';
                } else if (c.type === 'source') {
                    src = true; r.from = 'addr'; r.fromV = side(c);
                } else if (c.type === 'destination' || c.type === 'ip') {
                    dest = true;
                    if (!c.alias_id && (c.value === 'internet' || c.value === 'lan')) r.to = c.value;
                    else { r.to = 'addr'; r.toV = side(c); }
                } else if (c.type === 'port') {
                    port = true; r.port = String(c.value || '');
                } else if (c.type === 'protocol') {
                    r.proto = c.value || 'any';
                }
            });
            const kind = app ? 'site' : port ? 'port' : 'addr';
            if (kind === 'addr' && !dest) r.to = 'addr';
            const more = [];
            if (src) more.push('from');
            if (dest && kind !== 'addr') more.push('to');
            if (port && kind !== 'port') more.push('port');
            return { uid: `s${it.id}`, id: it.id, r, kind, more, p: null };
        }

        async function fetchList() {
            return ((await call('GET', '/custom-rules')).items || []).map(fromServer);
        }

        async function load() {
            try {
                const [aliases, doc] = await Promise.all([
                    loadAliases().catch(() => null),
                    N.api.settings(ctx.peerId).catch(() => null),
                ]);
                S.aliases = aliases || [];
                S.aliasesFailed = !aliases;
                const lim = doc && doc.options && doc.options.limits && doc.options.limits.custom_rules;
                if (lim > 0) S.limit = lim;
                S.items = await fetchList();   // after the aliases: rows show alias names
            } catch (e) {
                win.body.innerHTML = '<div class="ids-win-msg">Couldn\'t load.</div>';
                return;
            }
            build();
        }

        // ── Small helpers ───────────────────────────────────────────────────

        function newForm(mode) {
            return { mode, r: blank(), kind: 'site', more: [], e: {}, w: {}, menu: null, sopen: null, dd: null, prevB: null };
        }

        const clone = (v) => JSON.parse(JSON.stringify(v));
        const siteOn = (fs) => fs.kind === 'site' || fs.more.includes('site');
        const fromOn = (fs) => fs.more.includes('from');
        const toOn = (fs) => fs.kind === 'addr' || fs.more.includes('to');
        const portOn = (fs) => fs.kind === 'port' || fs.more.includes('port');
        // What a form would save, said as a key: only the parts that are on count.
        function fsKey(fs) {
            const r = fs.r;
            return JSON.stringify([r.name.trim(), r.sev, r.on,
                siteOn(fs) ? [r.look, r.op, r.site.trim().toLowerCase()] : null,
                fromOn(fs) ? r.fromV.trim() : null,
                toOn(fs) ? [r.to, r.to === 'addr' ? r.toV.trim() : ''] : null,
                portOn(fs) ? [r.proto, r.port.trim()] : null]);
        }
        const itemKey = (e) => fsKey(e);
        const strip = (e) => { const { p, orig, ...rest } = e; return clone(rest); };
        const pending = () => S.items.filter((e) => e.p);
        const liveCount = () => S.items.filter((e) => e.p !== 'del').length;

        function clearCond(r, c) {
            if (c === 'site') r.site = '';
            else if (c === 'from') { r.from = ''; r.fromV = ''; }
            else if (c === 'to') { r.to = ''; r.toV = ''; }
            else if (c === 'port') { r.port = ''; r.proto = 'any'; }
        }

        // ── Checks: nothing while typing except a never-valid character ─────

        function badChar(f, v, fs) {
            let m = null;
            if (f === 'name') m = v.match(/["';\\]/);
            else if (f === 'port') m = v.match(/[^\d:-]/);
            else if (f === 'site') m = fs.r.look === 'http_user_agent' ? v.match(/[";\\|]/) : v.match(/[^A-Za-z0-9._*-]/);
            else if (f === 'fromV' || f === 'toV') {
                const t = v.trim();
                if (t.startsWith('@')) {
                    for (const ch of t.slice(1)) if (!/[\p{L}\p{N}_\- .]/u.test(ch)) return `"${ch === ' ' ? 'Space' : ch}" not allowed.`;
                    return '';
                }
                if (v.includes(',')) return 'One address or one alias.';
                if (v.includes('@')) return 'An alias starts with @.';
                m = v.match(/[^0-9./\s]/);
            }
            return m ? `"${m[0] === ' ' ? 'Space' : m[0]}" not allowed.` : '';
        }

        // An address field: an address or network, or one alias. Returns {value} | {alias_id} | {err}.
        function resolve(v) {
            const t = v.trim();
            if (!t) return { err: ADDR_HELP };
            if (t.startsWith('@')) {
                const n = t.slice(1).trim();
                const a = S.aliases.find((x) => x.name === n) || S.aliases.find((x) => x.name.toLowerCase() === n.toLowerCase());
                if (a) return { alias_id: a.id };
                return { err: S.aliasesFailed ? 'Aliases not available.' : `Unknown alias: ${n || '@'}.` };
            }
            if (t === 'lan' || t === 'internet') return { value: t };   // kept as the API sent it
            return okAddr(t) ? { value: t } : { err: ADDR_HELP };
        }

        function checkPort(p) {
            const m = p.trim().match(/^(\d+)(?:[-:](\d+))?$/);
            return (!m || +m[1] < 1 || +m[1] > 65535 || (m[2] && (+m[2] <= +m[1] || +m[2] > 65535)))
                ? 'One port or a range, like 8000-8100.' : '';
        }

        // The checks the peer makes, said briefly. Returns {field: message}.
        function check(fs) {
            const r = fs.r;
            const e = {};
            const n = r.name.trim();
            if (!n) e.name = 'Enter a name.';
            else if (n.length > NAME_MAX) e.name = `Up to ${NAME_MAX} characters.`;
            else if (badChar('name', n, fs)) e.name = badChar('name', n, fs);
            if (siteOn(fs)) {
                const s = r.site.trim().toLowerCase();
                if (r.look === 'http_user_agent') {
                    if (!s) e.site = 'Enter a browser or app name.';
                    else if (/[";\\|]/.test(s) || s.length > 200) e.site = 'Up to 200 characters, without quotes, ; \\ or |.';
                } else if (!s || s.length > 253 || (r.op === 'contains'
                    ? !/^[a-z0-9._-]+$/.test(s)
                    : !/^(\*?\.)?([a-z0-9_-]+\.)*[a-z0-9_-]+$/.test(s))) e.site = 'Enter a name like example.com.';
            }
            if (fromOn(fs)) {
                const x = resolve(r.fromV);
                if (x.err) e.from = x.err;
            }
            if (toOn(fs) && r.to === 'addr') {
                const x = resolve(r.toV);
                if (x.err) e.to = x.err;
            }
            if (portOn(fs)) {
                if (!r.port.trim()) e.port = 'Enter a port.';
                else if (checkPort(r.port)) e.port = checkPort(r.port);
                else if (!siteOn(fs) && r.proto === 'any') e.port = 'A port needs TCP or UDP.';
                if (siteOn(fs) && r.look !== 'domain' && r.proto === 'udp') e.proto = 'Websites and apps use TCP here.';
            }
            return e;
        }

        // Which message slot a field fills.
        const slotOf = (f) => ({ name: 'name', site: 'site', fromV: 'from', toV: 'to', port: 'port' }[f] || f);

        // Form -> API conditions (only after check() passed).
        function conditions(fs) {
            const r = fs.r;
            const out = [];
            const side = (type, v) => { const x = resolve(v); out.push(x.alias_id ? { type, alias_id: x.alias_id } : { type, value: x.value }); };
            if (siteOn(fs)) {
                let v = r.site.trim().toLowerCase();
                if (r.look === 'http_user_agent') v = r.site.trim();
                out.push({ type: r.look, operator: r.op, value: v });
            }
            if (fromOn(fs)) side('source', r.fromV);
            if (toOn(fs)) {
                if (r.to === 'addr') side('destination', r.toV);
                else out.push({ type: 'destination', value: r.to });
            }
            if (portOn(fs)) {
                out.push({ type: 'port', value: r.port.trim() });
                if (r.proto !== 'any') out.push({ type: 'protocol', value: r.proto });
            }
            return out;
        }

        // ── Pieces of the form ──────────────────────────────────────────────

        const msgHtml = (fs, k) => (fs.e[k] ? `<div class="ids-we-err">${esc(fs.e[k])}</div>`
            : fs.w[k] ? `<div class="ids-we-warn">${IdsIcon('triangle-exclamation')}<span>${esc(fs.w[k])}</span></div>` : '');
        const slot = (fs, k) => `<div data-m="${k}">${msgHtml(fs, k)}</div>`;

        function inp(fs, f, ph, cls, max) {
            const v = fs.r[f];
            const k = slotOf(f);
            const st = fs.e[k] ? ' ids-we-bad' : fs.w[k] ? ' ids-we-warnb' : '';
            return `<input class="ids-we-inp${cls ? ' ' + cls : ''}${st}" data-f="${f}" value="${esc(v)}" placeholder="${ph}"` +
                `${max ? ` maxlength="${max}"` : ''} autocomplete="off" spellcheck="false">`;
        }

        // Our own dropdown (never a native select).
        function dd(fs, id, cur, opts, cls) {
            const op = fs.menu === id;
            return `<div class="ids-wm-dsel ids-wc-dsel${cls ? ' ' + cls : ''}"><button type="button" class="ids-wm-dbtn${op ? ' ids-wm-open' : ''}" data-menu="${id}" ` +
                `aria-haspopup="listbox" aria-expanded="${op}">${esc(label(opts, cur))}${IdsIcon('chevron-down')}</button>` +
                (op ? '<div class="ids-menu ids-wm-menu ids-wc-menu" role="listbox">' + opts.map(([k, l, d]) =>
                    `<button type="button" role="option" class="${k === cur ? 'ids-sel' : ''}" data-pick="${id}" data-v="${k}">` +
                    `<span>${esc(l)}${d ? `<small>${esc(d)}</small>` : ''}</span>${k === cur ? IdsIcon('check') : ''}</button>`).join('') + '</div>' : '') +
                '</div>';
        }

        const catHead = (g) => `<div class="ids-wc-cat">${IdsIcon(CAT_ICON[g] || 'tag')}<span>${esc(g)}</span></div>`;

        function suggList(q) {
            const t = (q || '').trim().toLowerCase();
            const groups = SUGG.map(([g, items]) => [g, items.filter(([n]) => !t || n.toLowerCase().includes(t))]).filter(([, it]) => it.length);
            if (!groups.length) return '';
            return groups.map(([g, it]) => catHead(g) + it.map(([n]) =>
                `<button type="button" role="option" class="ids-wc-sub" data-sugg="${esc(n)}"><span>${esc(n)}</span></button>`).join('')).join('');
        }

        function suggMenu(fs) {
            if (!fs.sopen) return '';
            const html = suggList(fs.sopen === 'all' ? '' : fs.r.name);
            return html ? `<div class="ids-menu ids-wc-menu ids-wc-smenu" role="listbox">${html}</div>` : '';
        }

        function applySugg(fs, name) {
            let tpl = null;
            SUGG.forEach(([, it]) => it.forEach(([n, v]) => { if (n === name) tpl = v; }));
            if (!tpl) return;
            fs.r = Object.assign(blank(), { name, on: fs.r.on }, tpl);
            fs.e = {}; fs.w = {};
            fs.kind = tpl.site ? 'site' : tpl.port ? 'port' : 'addr';
            fs.more = [];
            if (tpl.from) fs.more.push('from');
            if (tpl.to && fs.kind !== 'addr') fs.more.push('to');
        }

        // The alias list, the same as Excluded devices (and the firewall rule page).
        function aliasDd(fs, side) {
            if (fs.dd !== side) return '';
            const v = fs.r[side + 'V'].trim();
            const q = v.startsWith('@') ? v.slice(1).toLowerCase() : '';
            const m = S.aliases.map((a, i) => [a, i]).filter(([a]) =>
                !q || a.name.toLowerCase().includes(q) || a.c.toLowerCase().includes(q));
            if (!m.length) {
                const none = S.aliasesFailed ? 'Couldn\'t load aliases.' : 'No aliases found.';
                return `<div class="ids-we-acdd"><div class="ids-we-acnone">${none}<br>` +
                    '<button type="button" class="ids-we-acl2" data-x="mkalias">+ Create alias</button></div></div>';
            }
            return '<div class="ids-we-acdd">' + m.map(([a, i]) =>
                `<div class="ids-we-aci" data-ai="${i}"><span class="ids-we-acn"><span class="ids-we-acl"><span>@${esc(a.name)}</span>` +
                `<span class="ids-we-acc">${a.n}</span><span class="ids-we-actype">Normal</span></span>` +
                '<span class="ids-we-ace" data-ae title="Edit alias" aria-label="Edit alias">' + IdsIcon('external-link-alt') + '</span></span>' +
                `<span class="ids-we-acd">${esc(a.c)}</span></div>`).join('') +
                '<button type="button" class="ids-we-acf" data-x="mkalias">' + IdsIcon('plus-circle') + ' Create alias</button></div>';
        }

        function aliasField(fs, side, ph) {
            const al = fs.r[side + 'V'].trim().startsWith('@') ? ' ids-we-inalias' : '';
            return `<div class="ids-we-acwrap" data-side="${side}">` +
                `<button type="button" class="ids-we-atb" data-at="${side}" title="Pick an alias" aria-label="Pick an alias">@</button>` +
                inp(fs, side + 'V', ph, 'ids-we-main ids-wc-al' + al) +
                `<div data-live="dd-${side}">${aliasDd(fs, side)}</div></div>`;
        }

        const protoSeg = (fs) => `<div class="ids-we-seg ids-we-narrow">${PROTO.map(([k, l]) =>
            `<button type="button" data-proto="${k}" class="${fs.r.proto === k ? 'ids-we-on' : ''}">${l}</button>`).join('')}</div>`;

        function siteField(fs) {
            const r = fs.r;
            const ops = r.look === 'http_user_agent' ? OPS.filter(([k]) => k !== 'ends_with') : OPS;
            return dd(fs, 'look', r.look, LOOK, 'ids-wc-wide') +
                `<div class="ids-wc-pair">${dd(fs, 'op', r.op, ops)}${inp(fs, 'site', r.look === 'http_user_agent' ? 'Like TeamViewer' : 'Like example.com', '', 253)}</div>` +
                slot(fs, 'site');
        }

        function addrField(fs) {
            const r = fs.r;
            return `<div class="ids-wc-pair">${dd(fs, 'to', r.to || 'addr', TO_OPTS)}` +
                (r.to === 'addr' || !r.to ? aliasField(fs, 'to', '1.2.3.4 or @alias') : '') + '</div>' + slot(fs, 'to');
        }

        function svcField(fs) {
            const r = fs.r;
            let cur = null;
            SERVICES.forEach(([, it]) => it.forEach(([n, p, port]) => { if (p === r.proto && port === r.port.trim()) cur = n; }));
            const op = fs.menu === 'svc';
            const menu = op ? '<div class="ids-menu ids-wm-menu ids-wc-menu ids-wc-smenu" role="listbox">' + SERVICES.map(([g, it]) => catHead(g) + it.map(([n, p, port]) =>
                `<button type="button" role="option" class="ids-wc-sub${cur === n ? ' ids-sel' : ''}" data-pick="svc" data-v="${p}:${port}">` +
                `<span>${esc(n)}<small>${p.toUpperCase()} ${port}</small></span>${cur === n ? IdsIcon('check') : ''}</button>`).join('')).join('') + '</div>' : '';
            return `<div class="ids-wm-dsel ids-wc-dsel ids-wc-wide"><button type="button" class="ids-wm-dbtn${op ? ' ids-wm-open' : ''}${cur ? '' : ' ids-wc-ph'}" data-menu="svc" ` +
                `aria-haspopup="listbox" aria-expanded="${op}">${cur ? esc(cur) : 'Pick a common service'}${IdsIcon('chevron-down')}</button>${menu}</div>` +
                '<div class="ids-wc-or">Or set the protocol and port yourself.</div>' +
                `<div class="ids-wc-pp"><div>${protoSeg(fs)}${slot(fs, 'proto')}</div>` +
                `<div>${inp(fs, 'port', 'Port', 'ids-wc-port', 11)}${slot(fs, 'port')}</div></div>`;
        }

        function nameBlock(fs) {
            const r = fs.r;
            return '<span class="ids-we-lbl ids-we-first ids-wc-nlbl">Name' +
                '<span class="ids-wt-tip"><button type="button" class="ids-wt-ib" data-nametip="1" aria-label="More about this" aria-expanded="false">' + IdsIcon('circle-info') + '</button>' +
                '<span class="ids-wt-bub" role="tooltip">The alert shows up in your threats list under this name. A common one fills in the whole rule for you.</span></span></span>' +
                `<div class="ids-wc-nmw">${inp(fs, 'name', 'Type a name or pick a common one', 'ids-wc-name', NAME_MAX)}` +
                `<button type="button" class="ids-wc-nmarrow" data-sopen="1" title="Common rules" aria-label="Common rules">${IdsIcon('chevron-down')}</button>` +
                `<div data-live="sugg">${suggMenu(fs)}</div></div>` + slot(fs, 'name') +
                '<span class="ids-we-lbl">Severity</span>' +
                `<div class="ids-chips">${SEVS.map(([k, l]) =>
                    `<button type="button" class="ids-chip ids-sev-${k}${r.sev === k ? ' ids-on' : ''}" data-sv="${k}"><span class="ids-dot"></span>${l}</button>`).join('')}</div>`;
        }

        function formHtml(fs) {
            const cards = KINDS.map(([k, n, d]) => {
                const on = fs.kind === k;
                const body = !on ? '' : k === 'site' ? siteField(fs) : k === 'addr' ? addrField(fs) : svcField(fs);
                return `<div class="ids-wc-pi${on ? ' ids-on' : ''}" role="radio" aria-checked="${on}" tabindex="0" data-kind="${k}">` +
                    '<span class="ids-wc-rd"></span><span class="ids-wc-pt">' +
                    `<span class="ids-wc-pn">${esc(n)}</span><span class="ids-wc-pd">${esc(d)}</span>` +
                    (on ? `<div class="ids-wc-cin">${body}</div>` : '') + '</span></div>';
            }).join('');
            const chips = MORE_ALL.map(([k, l]) => {
                if (TAKEN[fs.kind] === k) return `<button type="button" class="ids-wc-mchip" disabled title="${TAKEN_WHY[k]}">${IdsIcon('plus')}${l}</button>`;
                const on = fs.more.includes(k);
                return `<button type="button" class="ids-wc-mchip${on ? ' ids-on' : ''}" data-more="${k}" aria-pressed="${on}">${IdsIcon(on ? 'check' : 'plus')}${l}</button>`;
            }).join('');
            const fields = MORE_ALL.filter(([k]) => TAKEN[fs.kind] !== k && fs.more.includes(k)).map(([k]) => {
                if (k === 'from') return '<span class="ids-we-lbl">These devices</span><div class="ids-wc-fh">Only devices at this address or in this alias raise the alert.</div>' +
                    aliasField(fs, 'from', '192.168.100.23 or @alias') + slot(fs, 'from');
                if (k === 'to') return `<span class="ids-we-lbl">Address</span><div class="ids-wc-fh">Only connections to this place raise the alert.</div>${addrField(fs)}`;
                if (k === 'port') return `<span class="ids-we-lbl">Port</span><div class="ids-wc-fh">Only connections on this port raise the alert.</div>${svcField(fs)}`;
                return `<span class="ids-we-lbl">Website</span><div class="ids-wc-fh">Only connections to this site raise the alert.</div>${siteField(fs)}`;
            }).join('');
            const kn = KINDS.find(([k]) => k === fs.kind)[1];
            return `<div class="ids-wc-form" data-form="${fs.mode}">` + nameBlock(fs) +
                `<span class="ids-we-lbl ids-wc-sec">Alert when a device <button type="button" class="ids-wc-hk" data-gokind="1" title="Set by your choice below. Click to see it.">${esc(kn[0].toLowerCase() + kn.slice(1))}</button></span>` +
                '<div class="ids-wc-fh">Choose the activity that raises this alert.</div>' +
                `<div class="ids-wc-pre" role="radiogroup" aria-label="Alert when a device">${cards}</div>` +
                '<div class="ids-wc-optbox"><span class="ids-wc-optag">Optional</span><div class="ids-wc-optt">Narrow it down</div>' +
                '<div class="ids-wc-fh">Add conditions to alert less often. The alert is raised only when everything you add here matches too.</div>' +
                `<div class="ids-wc-mchips">${chips}</div>${fields}</div>` +
                `<div data-live="pv">${previewHtml(fs)}</div></div>`;
        }

        // The hint: what all the settings do together, in one sentence.
        function explain(fs) {
            const r = fs.r;
            const s = siteOn(fs) ? r.site.trim() : '';
            const fv = fromOn(fs) ? r.fromV.trim() : '';
            const tv = r.toV.trim();
            const port = portOn(fs) ? r.port.trim() : '';
            const opw = { equals: 'is', ends_with: 'ends with', contains: 'has' }[r.op];
            const acts = [];
            if (s) {
                acts.push(r.look === 'http_user_agent' ? `uses a browser or app whose name ${opw} <b>${esc(s)}</b>`
                    : `opens a ${r.look === 'tls_name' ? 'secure ' : r.look === 'http_host' ? 'plain ' : ''}website whose name ${opw} <b>${esc(s)}</b>`);
            }
            if (toOn(fs)) {
                if (r.to === 'internet') acts.push('talks to <b>the internet</b>');
                else if (r.to === 'lan') acts.push('talks to <b>a device in your network</b>');
                else if (tv) acts.push(`talks to <b>${esc(tv)}</b>`);
            }
            if (port) acts.push(`uses ${r.proto !== 'any' ? r.proto.toUpperCase() + ' ' : ''}port <b>${esc(port)}</b>`);
            if (!acts.length) return 'Choose an activity above, and this tells you what the rule will do.';
            const who = fv ? (fv.startsWith('@') ? `a device in <b>${esc(fv)}</b>` : `the device <b>${esc(fv)}</b>`) : 'any device';
            const sev = label(SEVS, r.sev);
            const nm = r.name.trim();
            return `When ${who} ${acts.join(' and ')}, a <b>${sev}</b> threat ${nm ? `named <b>“${esc(nm)}”</b>` : 'with your rule\'s name'} is added to your threats list. Nothing is blocked.`;
        }

        // The threat row as the threats list will show it: the last part of the form.
        function previewHtml(fs) {
            const r = fs.r;
            const s = siteOn(fs) ? r.site.trim() : '';
            const fv = fromOn(fs) ? r.fromV.trim() : '';
            const tv = r.toV.trim();
            const dev = fv ? (fv.startsWith('@') ? 'A device in ' + fv : fv) : 'A device';
            const host = s && r.look !== 'http_user_agent' ? (r.op === 'ends_with' ? 'www.' + s.replace(/^\*?\./, '') : r.op === 'contains' ? 'www.' + s + '.com' : s) : '';
            const rem = host || (!toOn(fs) ? 'Any address' : r.to === 'internet' ? 'An internet address' : r.to === 'lan' ? 'A device in your network' : tv || 'Any address');
            const port = portOn(fs) ? r.port.trim() : '';
            const svc = port ? `${r.proto !== 'any' ? r.proto.toUpperCase() + ' ' : ''}${port}` : s ? (r.look === 'domain' ? 'DNS' : r.look === 'tls_name' ? 'HTTPS' : r.look === 'http_host' ? 'HTTP' : '') : '';
            const nm = r.name.trim();
            return '<div class="ids-wc-pv"><span class="ids-we-lbl ids-wc-sec">You\'ll see</span><div class="ids-wc-fh">How this alert looks in your threats list.</div>' +
                `<div class="ids-wc-pvbox ids-sev-${r.sev}"><div class="ids-wc-pvr"><span class="ids-dot"></span>` +
                `<span class="ids-wc-pvt${nm ? '' : ' ids-wc-ph'}">${esc(nm || 'Your rule name')}</span><span class="ids-sev-pill">${label(SEVS, r.sev)}</span></div>` +
                `<div class="ids-wc-pvd">Custom · ${esc(dev)} → ${esc(rem)}${svc ? ' : ' + esc(svc) : ''}</div></div></div>`;
        }

        const xplHtml = (fs) => `<div class="ids-wc-xpl">${IdsIcon('circle-info')}<span>${explain(fs)}</span></div>`;

        // ── Live updates while typing (no redraw: focus and the phone keyboard stay) ──

        // The form lives in the Add / Edit window.
        const rootOf = () => ov;
        const scroller = () => ov && ov.querySelector('.ids-we-ovb');

        function liveSlots(fs) {
            const root = rootOf(fs);
            if (!root) return;
            root.querySelectorAll('[data-m]').forEach((m) => { m.innerHTML = msgHtml(fs, m.dataset.m); });
            root.querySelectorAll('[data-f]').forEach((el) => {
                const k = slotOf(el.dataset.f);
                el.classList.toggle('ids-we-bad', !!fs.e[k]);
                el.classList.toggle('ids-we-warnb', !fs.e[k] && !!fs.w[k]);
                if (el.dataset.f === 'fromV' || el.dataset.f === 'toV') el.classList.toggle('ids-we-inalias', el.value.trim().startsWith('@'));
            });
        }

        function liveText(fs) {
            const root = rootOf(fs);
            if (!root) return;
            const pv = root.querySelector('[data-live="pv"]');
            if (pv) pv.innerHTML = previewHtml(fs);
            const x = root.querySelector('[data-live="xpl"]');
            if (x) { x.innerHTML = xplHtml(fs); glowHint(fs); }
            if (fs.mode === 'edit') refreshOvBtn();
        }

        function liveSugg(fs) {
            const root = rootOf(fs);
            const s = root && root.querySelector('[data-live="sugg"]');
            if (s) s.innerHTML = suggMenu(fs);
        }

        function liveDd(fs) {
            const root = rootOf(fs);
            if (!root) return;
            ['from', 'to'].forEach((side) => {
                const d = root.querySelector(`[data-live="dd-${side}"]`);
                if (d) d.innerHTML = aliasDd(fs, side);
            });
        }

        // The words of the hint that just changed glow for a moment.
        function glowHint(fs) {
            const root = rootOf(fs);
            const x = root && root.querySelector('[data-live="xpl"]');
            if (!x) { fs.prevB = null; return; }   // closed: the first sentence shown never glows
            const bs = [...x.querySelectorAll('b')];
            const now = bs.map((b) => b.textContent);
            if (fs.prevB) bs.forEach((b) => { if (!fs.prevB.includes(b.textContent)) b.classList.add('ids-wc-tglow'); });
            fs.prevB = now;
        }

        function glow(el, cls) {
            if (!el) return;
            el.classList.remove(cls);
            void el.offsetWidth;
            el.classList.add(cls);
            setTimeout(() => el.classList.remove(cls), 1600);
        }

        // An opened menu near the bottom scrolls the window body so it is not cut off.
        function showMenu(fs) {
            const root = rootOf(fs);
            const sc = scroller(fs);
            const m = root && root.querySelector('.ids-wc-form .ids-menu, .ids-wc-form .ids-we-acdd');
            if (!m || !sc) return;
            const over = m.getBoundingClientRect().bottom - sc.getBoundingClientRect().bottom + 8;
            if (over > 0) sc.scrollTop += over;
        }

        // ── Drawing ─────────────────────────────────────────────────────────

        let hostList;

        function build() {
            win.body.innerHTML =
                '<p class="ids-win-desc">Alerts you set up yourself.</p>' +
                '<div data-host="list"></div>';
            hostList = win.body.querySelector('[data-host="list"]');
            win.body.addEventListener('click', onClick);
            win.body.addEventListener('change', onChange);
            win.body.addEventListener('input', onInput);
            win.body.addEventListener('focusin', onFocusIn);
            win.body.addEventListener('focusout', onFocusOut);
            win.body.addEventListener('keydown', onKeydown);
            win.body.addEventListener('mousedown', onMouseDown);
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
            drawList();
            drawFoot();
        }

        const BADGE = {
            add: '<span class="ids-we-pend">Not saved</span>',
            edit: '<span class="ids-we-pend">Changed</span>',
            del: '<span class="ids-we-pend ids-we-del">Will be removed</span>',
        };

        function descOf(e) {
            const r = e.r;
            const out = [];
            const side = (k, v) => (k === 'lan' ? 'your network' : k === 'internet' ? 'the internet' : v);
            if (siteOn(e)) out.push(`${label(LOOK, r.look)} ${label(OPS, r.op).toLowerCase()} ${esc(r.site)}`);
            if (fromOn(e)) out.push(`from ${esc(r.fromV)}`);
            if (toOn(e) && r.to) out.push(`to ${esc(side(r.to, r.toV))}`);
            if (portOn(e)) out.push(`${r.proto !== 'any' ? r.proto.toUpperCase() + ' ' : ''}port ${esc(r.port)}`);
            const s = out.join(', ');
            return s ? s[0].toUpperCase() + s.slice(1) + '.' : '';
        }

        function rowHtml(e, i) {
            const r = e.r;
            const ic = (attr, icon, title) =>
                `<button type="button" class="ids-we-ic" data-${attr}="${i}" title="${title}" aria-label="${title}">${IdsIcon(icon)}</button>`;
            let acts = '';
            if (e.p === 'del') acts = ic('undo', 'rotate-left', 'Keep it');
            else if (!ctx.readonly) {
                acts = (e.p === 'edit' ? ic('revert', 'rotate-left', 'Undo the change') : '') +
                    `<label class="switch ids-ww-sw" title="${r.on ? 'Turn off' : 'Turn on'}"><input type="checkbox" data-tog="${i}" aria-label="Enabled"${r.on ? ' checked' : ''}${S.saving ? ' disabled' : ''}><span class="slider"></span></label>` +
                    ic('edit', 'pen', 'Edit') + ic('del', 'trash', 'Remove');
            }
            return `<div class="ids-we-row ids-wc-row${e.p === 'del' ? ' ids-we-gone' : ''}${r.on ? '' : ' ids-wc-isoff'}">` +
                `<div class="ids-we-main2"><div class="ids-we-t"><span class="ids-we-v">${esc(r.name)}</span>` +
                `<span class="ids-ww-sv ids-sev-${r.sev}">${label(SEVS, r.sev)}</span>${BADGE[e.p] || ''}</div>` +
                `<div class="ids-we-d">${descOf(e)}</div></div><div class="ids-we-acts">${acts}</div></div>`;
        }

        function drawList() {
            const live = liveCount();
            // Add: the collapsed heading and plus of the other lists; it opens the Add window.
            const add = ctx.readonly ? '' : '<section class="ids-sec ids-we-add ids-we-shut">' +
                `<button type="button" class="ids-we-toggle" data-x="openadd" title="Add">` +
                `<span class="ids-sec-h">Add</span>${IdsIcon('plus')}</button></section>`;
            hostList.innerHTML = add + '<section class="ids-sec"><h3 class="ids-sec-h">In the list</h3>' +
                `<p class="ids-sec-help">${live} of ${S.limit}.${ctx.readonly ? '' : ' Edit or remove one; nothing changes until you save.'}</p>` +
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
                win.foot.innerHTML = '<div class="ids-foot-status"><b class="ids-we-strong">' + IdsIcon('circle-notch', { spin: true }) + ' Saving.</b><small>Takes under a minute.</small></div>' + btns(true);
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
            drawList();
            drawFoot();
        }

        // Re-draw the form a click changed (it holds all its state in fs).
        function reform() {
            drawOv();
        }

        // ── Add / Edit window: one form, Add or Update ──────────────────────

        let ov = null;

        const ovDirty = () => !!S.ov && S.ov.fs.mode === 'edit' && fsKey(S.ov.fs) !== S.ov.base;

        function drawOv() {
            if (!S.ov || !win.el.isConnected) {
                if (ov) { ov.remove(); ov = null; }
                return;
            }
            if (!ov) {
                ov = document.createElement('div');
                ov.className = 'ids-win ids-we-ov ids-wc-ov';
                document.body.appendChild(ov);   // a page modal, one layer above the Lists window (like Create alias)
                ov.addEventListener('click', onClick);
                ov.addEventListener('change', onChange);
                ov.addEventListener('input', onInput);
                ov.addEventListener('focusin', onFocusIn);
                ov.addEventListener('focusout', onFocusOut);
                ov.addEventListener('keydown', onKeydown);
                ov.addEventListener('mousedown', onMouseDown);
                ov.addEventListener('mousedown', (ev) => { ov.dataset.downOut = ev.target === ov ? '1' : ''; });
            }
            const old = ov.querySelector('.ids-we-ovb');
            const top = old ? old.scrollTop : 0;
            const fs = S.ov.fs;
            const add = fs.mode === 'add';
            ov.innerHTML = '<div class="ids-we-ovcard ids-wc-ovcard" role="dialog" aria-modal="true">' +
                `<div class="modal-header ids-we-ovh"><h2>${IdsIcon('file-shield')} ${add ? 'Add' : 'Edit'} custom rule</h2>` +
                '<button type="button" class="modal-close" data-x="ovclose" aria-label="Close">&times;</button></div>' +
                `<div class="ids-we-ovb"><section class="ids-sec"><h3 class="ids-sec-h">${add ? 'Add' : 'Edit'}</h3>` +
                (add ? '<p class="ids-sec-help">Get an alert when a device on your network does something you want to know about. Nothing is blocked; the alert shows up in your threats list.</p>' : '') +
                `<div class="ids-sec-body">${formHtml(fs)}</div></section></div>` +
                `<div class="ids-we-ovf ids-wc-ovf"><div class="ids-wc-dk" data-live="xpl">${xplHtml(fs)}</div>` +
                '<div class="ids-wc-ovbtns"><button type="button" class="ids-btn" data-x="ovclose">Cancel</button>' +
                (add ? `<button type="button" class="ids-btn ids-btn-primary" data-x="add">${IdsIcon('plus')}Add</button>`
                    : `<button type="button" class="ids-btn ids-btn-primary" data-x="ovsave"${ovDirty() ? '' : ' disabled'}>Update</button>`) +
                '</div></div></div>';
            ov.querySelector('.ids-we-ovb').scrollTop = top;
            glowHint(fs);
        }

        function refreshOvBtn() {
            const b = ov && ov.querySelector('[data-x="ovsave"]');
            if (b) b.disabled = !ovDirty();
        }

        function openAdd() {
            S.ov = { fs: newForm('add') };
            drawOv();
            N.focusDialog(ov);
        }

        function openEdit(i) {
            const it = S.items[i];
            const fs = newForm('edit');
            fs.r = clone(it.r);
            fs.kind = it.kind;
            fs.more = it.more.slice();
            S.ov = { i, fs, base: fsKey(fs) };
            drawOv();
            N.focusDialog(ov);
        }

        // ── Staging ─────────────────────────────────────────────────────────

        // The form's checks; with errors, the form shows them and nothing is staged.
        function checked(fs) {
            fs.menu = null; fs.sopen = null; fs.dd = null;
            fs.e = check(fs);
            Object.keys(fs.w).forEach((k) => { if (fs.w[k]) fs.e[k] = fs.e[k] || fs.w[k]; });
            fs.w = {};
            if (Object.keys(fs.e).length) {
                reform(fs);
                const first = rootOf(fs).querySelector('.ids-we-err');
                if (first) first.scrollIntoView({ block: 'center', behavior: 'smooth' });
                return false;
            }
            return true;
        }

        // The rule as staged: only the parts that are on are kept.
        function staged(fs) {
            const r = clone(fs.r);
            if (!siteOn(fs)) { r.site = ''; r.look = 'domain'; r.op = 'equals'; }
            if (!fromOn(fs)) { r.from = ''; r.fromV = ''; }
            if (!toOn(fs)) { r.to = ''; r.toV = ''; } else if (r.to !== 'addr') r.toV = '';
            if (!portOn(fs)) { r.port = ''; r.proto = 'any'; }
            r.name = r.name.trim(); r.site = r.site.trim(); r.fromV = r.fromV.trim(); r.toV = r.toV.trim(); r.port = r.port.trim();
            return { r, kind: fs.kind, more: fs.more.filter((k) => k !== TAKEN[fs.kind]), conds: conditions(fs) };
        }

        function doAdd() {
            if (!S.ov || S.ov.fs.mode !== 'add') return;
            const fs = S.ov.fs;
            if (!checked(fs)) return;
            if (liveCount() >= S.limit) {
                fs.e = { name: `Up to ${S.limit} custom rules.` };
                drawOv();
                return;
            }
            S.items.unshift({ uid: `n${++uidSeq}`, id: null, ...staged(fs), p: 'add' });
            S.saved = false;
            S.err = '';
            S.ov = null;
            drawOv();
            redraw();
        }

        function doEdit() {
            if (!S.ov || !ovDirty()) return;
            const fs = S.ov.fs;
            if (!checked(fs)) return;
            setItem(S.ov.i, { ...strip(S.items[S.ov.i]), ...staged(fs) });
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

        // Close drops every unsaved change and closes, no confirm.
        function discard() {
            S.items = S.items.filter((e) => e.p !== 'add').map((e) => e.orig || e);
            S.items.forEach((e) => { e.p = null; });
            S.err = '';
            S.saved = false;
            win.close(true);
        }

        // ── Save: one request, all or nothing ───────────────────────────────

        // A rule read from the peer has no conds yet: they are built from its fields.
        function condsOf(e) {
            if (e.conds) return e.conds;
            const fs = newForm('edit');
            fs.r = clone(e.r); fs.kind = e.kind; fs.more = e.more.slice();
            return conditions(fs);
        }

        const bodyOf = (e) => ({ name: e.r.name, severity: e.r.sev, enabled: e.r.on, conditions: condsOf(e) });
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
                add: pend.filter((e) => e.p === 'add').reverse().map(bodyOf),   // the list order: oldest first
                update: pend.filter((e) => e.p === 'edit').map((e) => ({ id: e.id, ...bodyOf(e) })),
                remove: pend.filter((e) => e.p === 'del').map((e) => e.id),
            };
            S.saving = true;
            S.saved = false;
            S.err = '';
            S.confirm = false;
            win.setBusy(true);
            drawFoot();
            drawList();
            let failed = null;
            try {
                await call('POST', '/custom-rules/batch', body);
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
                drawList();
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
            drawList();
            drawFoot();
        }

        // ── Aliases: the same windows as Excluded devices ───────────────────

        function createAlias(fs, side) {
            if (!window.IdsAliasCreate) { ctx.toast('err', 'Couldn\'t open the window.'); return; }
            fs.dd = null;
            liveDd(fs);
            IdsAliasCreate.open({
                peerId: ctx.peerId,
                onCreated: async (name) => {
                    try { S.aliases = await loadAliases(); S.aliasesFailed = false; } catch (e) { /* keep the old list */ }
                    fs.r[side + 'V'] = `@${name}`;
                    delete fs.e[side]; delete fs.w[side];
                    reform(fs);
                },
            });
        }

        function editAlias(fs, a) {
            if (!window.IdsAliasCreate) { ctx.toast('err', 'Couldn\'t open the window.'); return; }
            fs.dd = null;
            liveDd(fs);
            IdsAliasCreate.open({
                peerId: ctx.peerId,
                alias: a.raw,
                onSaved: async (saved) => {
                    try { S.aliases = await loadAliases(); S.aliasesFailed = false; } catch (e) { /* keep the old list */ }
                    ['fromV', 'toV'].forEach((f) => {
                        if (fs.r[f].trim().replace(/^@/, '').toLowerCase() === a.name.toLowerCase()) fs.r[f] = `@${saved.name}`;
                    });
                    reform(fs);
                    drawList();
                },
            });
        }

        // ── Events ──────────────────────────────────────────────────────────

        function formOf(node) {
            const fe = node && node.closest && node.closest('.ids-wc-ov');
            return fe && S.ov ? S.ov.fs : null;
        }

        // Alias rows and menus are picked on mousedown, so the field keeps focus.
        function onMouseDown(ev) {
            if (ev.target.closest('.ids-wc-smenu, .ids-wc-nmarrow')) ev.preventDefault();
            const row = ev.target.closest('.ids-we-aci');
            if (!row) return;
            ev.preventDefault();
            const fs = formOf(row);
            if (!fs) return;
            const side = row.closest('[data-side]').dataset.side;
            const a = S.aliases[+row.dataset.ai];
            if (ev.target.closest('[data-ae]')) { ev.stopPropagation(); editAlias(fs, a); return; }
            fs.r[side + 'V'] = `@${a.name}`;
            delete fs.e[side]; delete fs.w[side];
            fs.dd = null;
            const f = rootOf(fs).querySelector(`[data-f="${side}V"]`);
            if (f) f.value = fs.r[side + 'V'];
            liveDd(fs);
            liveSlots(fs);
            liveText(fs);
        }

        function closeMenus() {
            let changed = false;
            [S.ov && S.ov.fs].forEach((fs) => {
                if (!fs) return;
                if (fs.dd) { fs.dd = null; liveDd(fs); changed = true; }
                if (fs.sopen) { fs.sopen = null; liveSugg(fs); changed = true; }
                if (fs.menu) { fs.menu = null; if (rootOf(fs)) reform(fs); changed = true; }
            });
            return changed;
        }

        function setKind(fs, k) {
            if (fs.kind === k) return;
            const r = fs.r;
            const old = fs.kind;
            fs.kind = k;
            fs.e = {}; fs.w = {};
            if (old === 'site' && !fs.more.includes('site')) clearCond(r, 'site');
            else if (old === 'addr' && !fs.more.includes('to')) clearCond(r, 'to');
            else if (old === 'port' && !fs.more.includes('port')) clearCond(r, 'port');
            fs.more = fs.more.filter((x) => x !== TAKEN[k]);   // the activity now holds it (its values stay)
            if (k === 'addr' && !r.to) r.to = 'addr';
            if (k === 'port' && r.proto === 'any') r.proto = 'tcp';
            reform(fs);
            const root = rootOf(fs);
            glow(root.querySelector('.ids-wc-hk'), 'ids-wc-glow');   // the heading changed: show it
        }

        function onClick(ev) {
            const tipB = ev.target.closest('[data-nametip]');
            const openTip = (ov || document).querySelector('.ids-wc-nlbl .ids-wt-tip.ids-wt-open');
            if (openTip && openTip !== (tipB && tipB.parentElement)) {
                openTip.classList.remove('ids-wt-open');
                openTip.querySelector('.ids-wt-ib').setAttribute('aria-expanded', 'false');
            }
            if (tipB) {
                const t = tipB.parentElement, on = !t.classList.contains('ids-wt-open');
                t.classList.toggle('ids-wt-open', on);
                tipB.setAttribute('aria-expanded', String(on));
                return;
            }
            if (ov && ev.target === ov && ov.dataset.downOut) { S.ov = null; drawOv(); return; }
            const fs = formOf(ev.target);
            if (fs && fs.sopen && !ev.target.closest('.ids-wc-nmw')) { fs.sopen = null; liveSugg(fs); }
            const b = ev.target.closest('button');
            if (!b || b.disabled) {
                if (fs && fs.menu && !ev.target.closest('.ids-wm-dsel')) { fs.menu = null; reform(fs); return; }
                const kd = ev.target.closest('[data-kind]');
                if (fs && kd && !ev.target.closest('.ids-wc-cin')) setKind(fs, kd.dataset.kind);
                return;
            }
            const d = b.dataset;
            const x = d.x;
            if (S.confirm && !['keep', 'leave'].includes(x)) { S.confirm = false; drawFoot(); }
            if (fs && d.menu === undefined && d.pick === undefined && fs.menu) fs.menu = null;
            if (fs && d.gokind) {   // the blue words: show the choice that set them, with a short glow
                const c = rootOf(fs).querySelector('.ids-wc-pi.ids-on');
                if (c) { c.scrollIntoView({ block: 'nearest' }); glow(c, 'ids-wc-glow'); }   // already in view: no movement
            } else if (fs && d.sugg) {
                applySugg(fs, d.sugg);
                fs.sopen = null;
                reform(fs);
            } else if (fs && d.sopen) {
                fs.sopen = fs.sopen ? null : 'all';
                liveSugg(fs);
                showMenu(fs);
            } else if (fs && d.menu) {
                fs.menu = fs.menu === d.menu ? null : d.menu;
                fs.dd = null;
                reform(fs);
                showMenu(fs);
            } else if (fs && d.pick) {
                const r = fs.r;
                if (d.pick === 'op') r.op = d.v;
                else if (d.pick === 'look') {
                    r.look = d.v;
                    if (d.v === 'http_user_agent' && r.op === 'ends_with') r.op = 'equals';
                    delete fs.e.site; delete fs.e.proto; delete fs.w.site;
                } else if (d.pick === 'svc') {
                    const [p, port] = d.v.split(':');
                    r.proto = p; r.port = port;
                    delete fs.e.proto; delete fs.e.port; delete fs.w.port;
                } else if (d.pick === 'to') {
                    r.to = d.v;
                    if (d.v !== 'addr') r.toV = '';
                    delete fs.e.to; delete fs.w.to;
                }
                fs.menu = null;
                reform(fs);
            } else if (fs && d.sv) {
                fs.r.sev = d.sv;
                reform(fs);
            } else if (fs && d.proto) {
                fs.r.proto = d.proto;
                delete fs.e.proto; delete fs.e.port;
                reform(fs);
            } else if (fs && d.at) {
                fs.dd = fs.dd === d.at ? null : d.at;
                fs.sopen = null;
                liveDd(fs);
                showMenu(fs);
            } else if (fs && x === 'mkalias') {
                createAlias(fs, b.closest('[data-side]').dataset.side);
            } else if (fs && d.more) {
                const k = d.more;
                if (fs.more.includes(k)) {
                    fs.more = fs.more.filter((y) => y !== k);
                    clearCond(fs.r, k);
                    delete fs.e[k]; delete fs.w[k];
                } else {
                    fs.more.push(k);
                    if (k === 'port' && fs.r.proto === 'any') fs.r.proto = 'tcp';
                    if (k === 'from') fs.r.from = 'addr';
                    if (k === 'to' && !fs.r.to) fs.r.to = 'addr';
                }
                reform(fs);
            } else if (x === 'add') doAdd();
            else if (x === 'openadd') openAdd();
            else if (x === 'ovsave') doEdit();
            else if (x === 'ovclose') { S.ov = null; drawOv(); }
            else if (x === 'save') save();
            else if (x === 'discard') discard();
            else if (x === 'keep') { S.confirm = false; drawFoot(); }
            else if (x === 'leave') win.close(true);
            else if (d.edit !== undefined) openEdit(+d.edit);
            else if (d.del !== undefined) {
                const i = +d.del;
                if (S.items[i].p === 'add') S.items.splice(i, 1); else S.items[i].p = 'del';
                S.saved = false; S.err = '';
                redraw();
            } else if (d.revert !== undefined) {
                const i = +d.revert;
                S.items[i] = S.items[i].orig;
                S.err = '';
                redraw();
            } else if (d.undo !== undefined) {
                const it = S.items[+d.undo];
                it.p = it.orig ? 'edit' : null;
                S.err = '';
                redraw();
            }
        }

        // The row switch stages an edit like any other change.
        function onChange(ev) {
            const t = ev.target;
            if (t.dataset.tog === undefined) return;
            const i = +t.dataset.tog;
            const it = S.items[i];
            const nu = strip(it);
            nu.r.on = t.checked;
            setItem(i, nu);
            redraw();
        }

        function onInput(ev) {
            const el = ev.target;
            const f = el.dataset && el.dataset.f;
            const fs = formOf(el);
            if (!f || !fs) return;
            fs.r[f] = el.value;
            const k = slotOf(f);
            delete fs.e[k];
            fs.w[k] = badChar(f, el.value, fs);
            if (f === 'name') { fs.sopen = 'filter'; liveSugg(fs); }
            if (f === 'fromV' || f === 'toV') {
                const side = f.slice(0, -1);
                fs.dd = el.value.trim().startsWith('@') && !fs.w[k] ? side : null;
                liveDd(fs);
            }
            liveSlots(fs);
            liveText(fs);
        }

        function onFocusIn(ev) {
            const fs = formOf(ev.target);
            if (fs && ev.target.dataset && ev.target.dataset.f === 'name' && !fs.sopen && !fs.r.name.trim()) {
                fs.sopen = 'filter';
                liveSugg(fs);
            }
        }

        // Leaving a field shows its own problem (never while typing).
        function onFocusOut(ev) {
            const f = ev.target.dataset && ev.target.dataset.f;
            const fs = formOf(ev.target);
            if (!f || !fs) return;
            const to = ev.relatedTarget;
            if (to && to.closest && to.closest('.ids-we-acwrap, .ids-wc-nmw, .ids-we-ovf')) return;
            if (f === 'name' && fs.sopen) { fs.sopen = null; liveSugg(fs); }
            const k = slotOf(f);
            if (!String(fs.r[f]).trim() || fs.w[k]) return;
            const e = check(fs)[k];
            if (e) fs.e[k] = e; else delete fs.e[k];
            if ((f === 'fromV' || f === 'toV') && fs.dd) { fs.dd = null; liveDd(fs); }
            liveSlots(fs);
        }

        function onKeydown(ev) {
            const t = ev.target;
            const fs = formOf(t);
            if (!fs) return;
            if ((ev.key === 'Enter' || ev.key === ' ') && t.matches && t.matches('[data-kind]')) {
                ev.preventDefault();
                setKind(fs, t.dataset.kind);
                return;
            }
            if (ev.key === 'Tab' && fs.sopen) { fs.sopen = null; liveSugg(fs); }
            if (t.tagName !== 'INPUT' || ev.key !== 'Enter' || !t.dataset.f) return;
            ev.preventDefault();
            if (fs.mode === 'add') doAdd(); else doEdit();
        }

        function onDocClick(ev) {
            if (!win.el.isConnected) { document.removeEventListener('click', onDocClick); return; }
            const t = ev.target;
            // The click that opened the Add window must not close the common rules it just showed.
            if (t.closest && t.closest('.ids-we-acwrap, .ids-wc-nmw, .ids-wm-dsel, [data-x="openadd"]')) return;
            [S.ov && S.ov.fs].forEach((fs) => {
                if (!fs) return;
                if (fs.dd) { fs.dd = null; liveDd(fs); }
                if (fs.sopen && !(t.closest && t.closest('.ids-wc-ov'))) { fs.sopen = null; liveSugg(fs); }
            });
        }

        // Escape closes the open menu, then the edit window, before the shell sees it.
        function onEscape(ev) {
            if (!win.el.isConnected) { document.removeEventListener('keydown', onEscape, true); return; }
            if (ev.key !== 'Escape') return;
            if (document.querySelector('#idsAcModal.active')) return;   // Create alias above: Escape is its own
            if (closeMenus()) { ev.stopPropagation(); return; }
            if (S.ov) { ev.stopPropagation(); S.ov = null; drawOv(); return; }
            if (S.confirm) { ev.stopPropagation(); S.confirm = false; drawFoot(); }
        }
        return ready;
    }

    IdsWin.register('custom', { title: 'Custom rules', icon: 'file-shield', open });
})();
