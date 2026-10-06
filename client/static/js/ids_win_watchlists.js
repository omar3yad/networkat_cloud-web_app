/**
 * IDS page window: Watchlists (website or address aliases whose hits raise a threat).
 *
 * Design WL3 (ids-part10-watchlists.html) with ids-part10b severity chips.
 * Changes are staged in memory and written on "Save changes", one request after
 * another (no batch API): DELETE for removals, PUT for edits, POST for adds. The
 * first failure stops the run; whatever was not written stays pending.
 *
 * Peer contract: docs "Watchlists — /ids-ips/watchlists". A watchlist points at an
 * alias (`alias_id`) of the right type: web_domain for `names`, a normal address
 * alias for `addresses`. Clients only ever see the kinds `names` and `addresses`.
 */
(function () {
    if (!window.IdsWin) return;

    const SEVS = [['high', 'High'], ['medium', 'Medium'], ['low', 'Low']];
    const DEFAULT_LIMIT = 20;
    const NAME_MAX = 100;
    const PICK = 'Pick an alias.';

    function open(ctx, win) {
        const N = ctx.N;
        const esc = N.esc;
        const S = {
            items: [], aliases: [], aliasesFailed: false, limit: DEFAULT_LIMIT,
            add: newForm('add'), open: false, edit: null,
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

        async function loadAliases() {
            const data = await N.api.aliases(ctx.peerId);
            return (data.lists || []).map((a) => ({
                id: a.id || a.slug,
                name: a.name || a.slug || a.id,
                web: a.type === 'web_domain',
                raw: a,
                n: (a.list || []).length,
                c: a.comment || '',
            })).filter((a) => a.id);
        }

        function fromServer(it) {
            return {
                uid: `s${it.id}`, id: it.id, wk: it.kind, aliasId: it.alias_id,
                name: it.name || '', sev: it.severity || 'high', on: it.enabled !== false, p: null,
            };
        }

        async function load() {
            try {
                const [list, aliases, doc] = await Promise.all([
                    call('GET', '/watchlists'),
                    loadAliases().catch(() => null),
                    N.api.settings(ctx.peerId).catch(() => null),
                ]);
                S.items = (list.items || []).map(fromServer);
                S.aliases = aliases || [];
                S.aliasesFailed = !aliases;
                const lim = doc && doc.options && doc.options.limits && doc.options.limits.watchlists;
                if (lim > 0) S.limit = lim;
            } catch (e) {
                win.body.innerHTML = '<div class="ids-win-msg">Couldn\'t load.</div>';
                return;
            }
            build();
        }

        // ── Small helpers ───────────────────────────────────────────────────

        function newForm(mode) {
            return { mode, wk: 'names', value: '', name: '', sev: 'high', err: '', warn: '', nwarn: '', dd: false };
        }

        const aliasById = (id) => S.aliases.find((a) => a.id === id);
        const aliasLabel = (id) => (aliasById(id) || {}).name || id;
        const strip = (e) => { const { p, orig, ...rest } = e; return rest; };
        const itemKey = (e) => JSON.stringify([e.wk, e.aliasId, e.name, e.sev, e.on]);
        const fsKey = (fs) => JSON.stringify([bare(fs.value).toLowerCase(), fs.sev, fs.name.trim()]);
        const bare = (v) => v.trim().replace(/^@/, '').trim();
        // Like Excluded devices: an alias starts with @; anything else is an address or a site typed by hand.
        const isAlias = (fs) => fs.value.trim().startsWith('@');
        const pending = () => S.items.filter((e) => e.p);
        const liveCount = () => S.items.filter((e) => e.p !== 'del').length;
        // The kind follows the alias: a web_domain alias is a website watchlist, any other an address one.
        const kindOf = (a) => (a.web ? 'names' : 'addresses');

        // ── Checks: nothing while typing except a never-valid character ─────

        function badAlias(v) {
            if (v.trim() && !v.trim().startsWith('@')) return PICK;
            if (v.includes(',')) return 'One alias only.';
            for (const ch of bare(v)) if (!/[\p{L}\p{N}_\- .]/u.test(ch)) return `"${ch}" not allowed.`;
            return '';
        }

        function badName(v) {
            for (const ch of v) if (/["';\\<>]|[\u0000-\u001f]/.test(ch)) return `"${ch.trim() ? ch : ' '}" not allowed.`;
            return '';
        }

        function resolveAlias(fs) {
            const n = bare(fs.value);
            if (!n || !isAlias(fs)) return { err: PICK };
            let a = S.aliases.find((x) => x.name === n) || S.aliases.find((x) => x.name.toLowerCase() === n.toLowerCase());
            if (!a) return { err: S.aliasesFailed ? 'Aliases not available.' : `Unknown alias: ${n}.` };
            return { alias: a };
        }

        // The form's value or null (with the message shown under the field).
        function checkForm(fs) {
            const r = resolveAlias(fs);
            fs.err = fs.warn || r.err || '';
            fs.dd = false;
            if (fs.err || fs.nwarn) return null;
            return { aliasId: r.alias.id, wk: kindOf(r.alias), name: fs.name.trim() || r.alias.name };
        }

        // ── Form (the same block for Add and for Edit) ──────────────────────

        // Same list as the firewall rule page's alias field, plus the type the Aliases page shows.
        const typeName = (a) => (a.web ? 'Web domain' : 'Normal');

        function ddHtml(fs) {
            if (!fs.dd) return '';
            const q = isAlias(fs) ? bare(fs.value).toLowerCase() : '';
            const m = S.aliases.map((a, i) => [a, i]).filter(([a]) =>
                !q || a.name.toLowerCase().includes(q) || a.c.toLowerCase().includes(q));
            if (!m.length) {
                const none = S.aliasesFailed ? 'Couldn\'t load aliases.' : 'No aliases found.';
                return `<div class="ids-ww-acdd"><div class="ids-ww-acnone">${none}<br>` +
                    '<button type="button" class="ids-ww-acl2" data-x="mkalias">+ Create alias</button></div></div>';
            }
            const make = '<button type="button" class="ids-ww-acf" data-x="mkalias">' + IdsIcon('plus-circle') + ' Create alias</button>';
            return '<div class="ids-ww-acdd">' + m.map(([a, i]) =>
                `<div class="ids-ww-aci" data-ai="${i}"><span class="ids-ww-acn"><span class="ids-ww-acl"><span>@${esc(a.name)}</span>` +
                `<span class="ids-ww-acc">${a.n}</span><span class="ids-ww-actype">${typeName(a)}</span></span>` +
                '<span class="ids-ww-ace" data-ae title="Edit alias" aria-label="Edit alias">' + IdsIcon('external-link-alt') + '</span></span>' +
                `<span class="ids-ww-acd">${esc(a.c)}</span></div>`).join('') + make + '</div>';
        }

        function warnHtml(t) {
            return `<div class="ids-ww-warn">${IdsIcon('triangle-exclamation')}<span>${esc(t)}</span></div>`;
        }

        const mkBtn = (t) => (t === PICK && !ctx.readonly
            ? ' <button type="button" class="ids-ww-acl2" data-x="mkalias">Create alias</button>' : '');

        function msgHtml(fs) {
            if (fs.err) return `<div class="ids-ww-err">${esc(fs.err)}${mkBtn(fs.err)}</div>`;
            if (fs.warn) return `<div class="ids-ww-warn">${IdsIcon('triangle-exclamation')}<span>${esc(fs.warn)}${mkBtn(fs.warn)}</span></div>`;
            const r = bare(fs.value) ? resolveAlias(fs) : null;
            if (r && r.alias) return `<div class="ids-ww-hint">Type: ${typeName(r.alias)}.</div>`;
            return '<div class="ids-ww-hint">Type @ or press @ to pick an alias.</div>';
        }

        function nmsgHtml(fs) {
            return fs.nwarn ? warnHtml(fs.nwarn) : '<div class="ids-ww-hint">Shown on its threats. Empty uses the alias name.</div>';
        }

        function formHtml(fs, withAdd) {
            const inCls = (fs.err ? ' ids-ww-bad' : fs.warn ? ' ids-ww-warnb' : '') + (isAlias(fs) ? ' ids-ww-inalias' : '');
            const ph = 'Banned sites';
            return `<div data-form="${fs.mode}">` +
                '<span class="ids-ww-lbl ids-ww-first">Alias</span>' +
                `<div class="ids-ww-acwrap"><button type="button" class="ids-ww-atb" data-x="dd" title="Pick an alias" aria-label="Pick an alias">@</button>` +
                `<input class="ids-ww-inp ids-ww-alias${inCls}" data-f="value" value="${esc(fs.value)}" placeholder="@${ph}" autocomplete="off" spellcheck="false">` +
                `<div data-live="dd">${ddHtml(fs)}</div></div><div data-live="msg">${msgHtml(fs)}</div>` +
                '<span class="ids-ww-lbl">Severity</span>' +
                `<div class="ids-chips">${SEVS.map(([k, l]) =>
                    `<button type="button" class="ids-chip ids-sev-${k}${fs.sev === k ? ' ids-on' : ''}" data-sv="${k}"><span class="ids-dot"></span>${l}</button>`).join('')}</div>` +
                '<span class="ids-ww-lbl">Name</span>' +
                `<input class="ids-ww-inp${fs.nwarn ? ' ids-ww-warnb' : ''}" data-f="name" value="${esc(fs.name)}" placeholder="Like Known bad servers" maxlength="${NAME_MAX}" autocomplete="off">` +
                `<div data-live="nmsg">${nmsgHtml(fs)}</div>` +
                (withAdd ? '<div class="ids-ww-addbar"><button type="button" class="ids-btn ids-btn-primary" data-x="add">' + IdsIcon('plus') + 'Add</button></div>' : '') +
                '</div>';
        }

        // Update one form in place (typing must not lose focus or the phone keyboard).
        function liveForm(fe, fs) {
            const inp = fe.querySelector('[data-f="value"]');
            // The pick (or a created alias) changes fs.value without typing: write it into the field.
            if (inp.value !== fs.value) inp.value = fs.value;
            inp.classList.toggle('ids-ww-bad', !!fs.err);
            inp.classList.toggle('ids-ww-warnb', !fs.err && !!fs.warn);
            inp.classList.toggle('ids-ww-inalias', isAlias(fs));
            fe.querySelector('[data-live="dd"]').innerHTML = ddHtml(fs);
            fe.querySelector('[data-live="msg"]').innerHTML = msgHtml(fs);
            const n = fe.querySelector('[data-f="name"]');
            n.classList.toggle('ids-ww-warnb', !!fs.nwarn);
            fe.querySelector('[data-live="nmsg"]').innerHTML = nmsgHtml(fs);
        }

        function formOf(node) {
            const fe = node.closest && node.closest('[data-form]');
            if (!fe) return [null, null];
            return [fe, fe.dataset.form === 'edit' ? (S.edit && S.edit.fs) : S.add];
        }

        // ── Drawing ─────────────────────────────────────────────────────────

        let hostAdd, hostList;

        function build() {
            win.body.innerHTML =
                '<p class="ids-win-desc">Websites or addresses that raise a threat whenever a device reaches one.</p>' +
                '<div data-host="add"></div><div data-host="list"></div>';
            hostAdd = win.body.querySelector('[data-host="add"]');
            hostList = win.body.querySelector('[data-host="list"]');
            win.body.addEventListener('click', onClick);
            win.body.addEventListener('change', onChange);
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
            hostAdd.innerHTML = '<section class="ids-sec ids-ww-add ids-ww-shut">' +
                '<button type="button" class="ids-ww-toggle" data-x="toggle" title="Add">' +
                `<span class="ids-sec-h">Add</span>${IdsIcon('plus')}</button></section>`;
            drawAddOv();
        }

        // The Add window (a page modal, like Edit).
        function drawAddOv() {
            if (!S.open || ctx.readonly || !win.el.isConnected) {
                if (ova) { ova.remove(); ova = null; }
                return;
            }
            if (!ova) ova = mountOv();
            ova.innerHTML = '<div class="ids-ww-ovcard" role="dialog" aria-modal="true">' +
                '<div class="modal-header ids-ww-ovh"><h2>Add watchlist</h2><button type="button" class="modal-close" data-x="addclose" aria-label="Close">&times;</button></div>' +
                `<div class="ids-ww-ovb">${formHtml(S.add, false)}</div>` +
                '<div class="ids-ww-ovf"><button type="button" class="ids-btn" data-x="addclose">Cancel</button>' +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="add">${IdsIcon('plus')}Add</button></div></div>`;
        }

        const BADGE = {
            add: '<span class="ids-ww-pend">Not saved</span>',
            edit: '<span class="ids-ww-pend">Changed</span>',
            del: '<span class="ids-ww-pend ids-ww-del">Will be removed</span>',
        };

        function rowHtml(e, i) {
            const a = aliasById(e.aliasId);
            const cnt = a ? ` (${a.n})` : '';
            const sev = `<span class="ids-ww-sv ${N.sevClass(e.sev)}">${esc(N.sevLabel(e.sev))}</span>`;
            const d = `<span class="ids-ww-al">@${esc(aliasLabel(e.aliasId))}</span>${cnt} · ${sev}`;
            const ic = (attr, icon, title) =>
                `<button type="button" class="ids-ww-ic" data-${attr}="${i}" title="${title}" aria-label="${title}">${IdsIcon(icon)}</button>`;
            let acts;
            if (e.p === 'del') acts = ic('undo', 'rotate-left', 'Keep it');
            else if (ctx.readonly) acts = '';
            else {
                acts = (e.p === 'edit' ? ic('revert', 'rotate-left', 'Undo the change') : '') +
                    `<label class="switch ids-ww-sw" title="${e.on ? 'Turn off' : 'Turn on'}"><input type="checkbox" data-tog="${i}" aria-label="Enabled"${e.on ? ' checked' : ''}${S.saving ? ' disabled' : ''}><span class="slider"></span></label>` +
                    (e.id || e.p === 'add' ? ic('edit', 'pen', 'Edit') + ic('del', 'trash', 'Remove') : '');
            }
            return `<div class="ids-ww-row${e.p === 'del' ? ' ids-ww-gone' : ''}${e.on ? '' : ' ids-ww-isoff'}">` +
                `<div class="ids-ww-main"><div class="ids-ww-t"><span class="ids-ww-n">${esc(e.name)}</span>${BADGE[e.p] || ''}</div>` +
                `<div class="ids-ww-d">${d}</div></div><div class="ids-ww-acts">${acts}</div></div>`;
        }

        function drawList() {
            const live = liveCount();
            const sec = (wk, title, help) => {
                const rs = S.items.map((e, i) => [e, i]).filter(([e]) => e.wk === wk);
                return `<section class="ids-sec"><h3 class="ids-sec-h">${title}</h3>${help}` +
                    `<div class="ids-sec-body">${rs.length ? rs.map(([e, i]) => rowHtml(e, i)).join('') : '<div class="ids-ww-empty">None.</div>'}</div></section>`;
            };
            const help = `<p class="ids-sec-help">${live} of ${S.limit}. ${ctx.readonly ? '' : 'Edit or remove one; nothing changes until you save.'}</p>`;
            hostList.innerHTML = sec('names', 'Websites', help) + sec('addresses', 'Addresses', '');
        }

        function drawFoot() {
            const pend = pending();
            const n = pend.length;
            const dis = (v) => (v ? ' disabled' : '');
            const btns = (dDisc, dSave) =>
                `<div class="ids-foot-btns"><button type="button" class="ids-btn" data-x="discard"${dis(dDisc)}>Close</button>` +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="save"${dis(dSave)}>${IdsIcon('floppy-disk')}Save changes</button></div>`;
            if (S.confirm && n) {
                win.foot.innerHTML = `<div class="ids-foot-status"><b class="ids-ww-strong">${n} unsaved ${n === 1 ? 'change' : 'changes'}.</b> Close without saving?</div>` +
                    '<div class="ids-foot-btns"><button type="button" class="ids-btn" data-x="keep">Keep editing</button>' +
                    '<button type="button" class="ids-btn ids-btn-danger" data-x="leave">Close without saving</button></div>';
                return;
            }
            if (S.saving) {
                win.foot.innerHTML = '<div class="ids-foot-status"><b class="ids-ww-strong">' + IdsIcon('circle-notch',{spin:true}) + ' Saving.</b><small>Takes under a minute.</small></div>' + btns(true, true);
                return;
            }
            let status;
            if (S.saved && !n) status = '<span class="ids-ww-ok">' + IdsIcon('check') + ' Saved.</span>';
            else if (n) {
                status = `<b class="ids-ww-strong">${n} unsaved ${n === 1 ? 'change' : 'changes'}.</b><small>Changes take effect in under a minute.</small>`;
            } else status = '';
            if (S.err) status += `<span class="ids-ww-ferr">${esc(S.err)}</span>`;
            win.foot.innerHTML = `<div class="ids-foot-status">${status}</div>` + btns(false, !n || ctx.readonly);
        }

        function redraw() {
            S.confirm = false;
            drawAdd();
            drawList();
            drawFoot();
        }

        // ── Edit window (a copy of the Add section) ─────────────────────────

        let ov = null;
        let ova = null;   // the Add window

        // A page modal, one layer above the Lists window.
        function mountOv() {
            const el = document.createElement('div');
            el.className = 'ids-win ids-ww-ov';
            document.body.appendChild(el);
            el.addEventListener('click', onClick);
            el.addEventListener('input', onInput);
            el.addEventListener('focusout', onFocusOut);
            el.addEventListener('keydown', onKeydown);
            el.addEventListener('mousedown', keepFocus);
            el.addEventListener('mousedown', (ev) => { el.dataset.downOut = ev.target === el ? '1' : ''; });
            return el;
        }

        function ovDirty() {
            return !!S.edit && fsKey(S.edit.fs) !== S.edit.base;
        }

        function drawEdit() {
            if (!S.edit || !win.el.isConnected) {
                if (ov) { ov.remove(); ov = null; }
                return;
            }
            if (!ov) ov = mountOv();
            ov.innerHTML = '<div class="ids-ww-ovcard" role="dialog" aria-modal="true">' +
                '<div class="modal-header ids-ww-ovh"><h2>Edit watchlist</h2><button type="button" class="modal-close" data-x="ovclose" aria-label="Close">&times;</button></div>' +
                `<div class="ids-ww-ovb">${formHtml(S.edit.fs, false)}</div>` +
                '<div class="ids-ww-ovf"><button type="button" class="ids-btn" data-x="ovclose">Cancel</button>' +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="ovsave"${ovDirty() ? '' : ' disabled'}>Update</button></div></div>`;
        }

        function refreshEditBtn() {
            const b = ov && ov.querySelector('[data-x="ovsave"]');
            if (b) b.disabled = !ovDirty();
        }

        function openEdit(i) {
            const it = S.items[i];
            const fs = newForm('edit');
            fs.wk = it.wk;
            fs.value = `@${aliasLabel(it.aliasId)}`;
            fs.sev = it.sev;
            fs.name = it.name === aliasLabel(it.aliasId) ? '' : it.name;
            S.edit = { i, fs, base: fsKey(fs) };
            drawEdit();
            const f = ov.querySelector('[data-f="value"]');
            if (f) f.focus();
        }

        function doEdit() {
            if (!S.edit || !ovDirty()) return;
            const r = checkForm(S.edit.fs);
            if (!r) { drawEdit(); return; }
            const it = S.items[S.edit.i];
            setItem(S.edit.i, { ...strip(it), wk: r.wk, aliasId: r.aliasId, name: r.name, sev: S.edit.fs.sev });
            S.edit = null;
            drawEdit();
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
            const r = checkForm(fs);
            if (!r) { drawAdd(); return; }
            if (liveCount() >= S.limit) { fs.err = `Up to ${S.limit} watchlists.`; drawAdd(); return; }
            S.items.unshift({ uid: `n${++uidSeq}`, id: null, wk: r.wk, aliasId: r.aliasId, name: r.name, sev: fs.sev, on: true, p: 'add' });
            S.saved = false;
            S.err = '';
            S.add = newForm('add');
            S.open = false;
            redraw();
        }

        function discard() {
            S.items = S.items.filter((e) => e.p !== 'add').map((e) => e.orig || e);
            S.items.forEach((e) => { e.p = null; });
            S.err = '';
            S.saved = false;
            win.close(true);
        }

        // ── Save: one request after another, stop at the first failure ──────

        function bodyOf(e) {
            return { kind: e.wk, alias_id: e.aliasId, name: e.name, severity: e.sev, enabled: e.on };
        }

        async function save() {
            const staged = S.items.slice();
            const pend = staged.filter((e) => e.p);
            if (!pend.length || S.saving || ctx.readonly) return;
            const order = { del: 0, edit: 1, add: 2 }; // removals first so the limit never blocks an add
            pend.sort((a, b) => order[a.p] - order[b.p]);
            S.saving = true;
            S.saved = false;
            S.err = '';
            S.confirm = false;
            win.setBusy(true);
            drawFoot();
            const done = new Map(); // uid -> new id (adds)
            let failed = null;
            for (const e of pend) {
                try {
                    if (e.p === 'del') await call('DELETE', `/watchlists/${encodeURIComponent(e.id)}`);
                    else if (e.p === 'edit') await call('PUT', `/watchlists/${encodeURIComponent(e.id)}`, bodyOf(e));
                    else {
                        const r = await call('POST', '/watchlists', bodyOf(e));
                        done.set(e.uid, (r && r.item && r.item.id) || null);
                        continue;
                    }
                    done.set(e.uid, e.id);
                } catch (err) {
                    failed = { e, msg: err.message };
                    break;
                }
            }
            await finishSave(staged, done, failed);
        }

        async function finishSave(staged, done, failed) {
            let fresh = null;
            if (done.size) {
                try { fresh = (await call('GET', '/watchlists')).items || []; } catch (e) { fresh = null; }
            }
            if (fresh) S.items = rebuild(fresh, staged, done);
            else if (done.size) S.items = localRebuild(staged, done);
            S.saving = false;
            win.setBusy(false);
            if (failed) {
                const detail = String(failed.msg || 'Request failed').replace(/\.?\s*$/, '.');
                S.err = `Couldn't save "${failed.e.name}". ${detail}`;
                ctx.toast('err', `Couldn't save "${failed.e.name}". ${detail}`);
            } else {
                S.saved = true;
                clearTimeout(savedTimer);
                savedTimer = setTimeout(() => { S.saved = false; if (win.el.isConnected && !S.saving) drawFoot(); }, 2000);
            }
            if (done.size) ctx.refreshSide();
            drawAdd();
            drawList();
            drawFoot();
        }

        // Server list + whatever is still staged (not written).
        function rebuild(fresh, staged, done) {
            const out = fresh.map(fromServer);
            const adds = [];
            staged.forEach((e) => {
                if (!e.p || done.has(e.uid)) return;
                if (e.p === 'add') { adds.push(e); return; }
                const i = out.findIndex((o) => o.id === e.id);
                if (i < 0) return;
                if (e.p === 'del') out[i].p = 'del';
                else if (itemKey(e) !== itemKey(out[i])) out[i] = { ...strip(e), uid: out[i].uid, id: out[i].id, p: 'edit', orig: out[i] };
            });
            return adds.concat(out);
        }

        // Fallback when the list can't be read back right after saving.
        function localRebuild(staged, done) {
            const out = [];
            staged.forEach((e) => {
                if (!done.has(e.uid)) { out.push(e); return; }
                if (e.p === 'del') return;
                out.push({ ...strip(e), id: done.get(e.uid) || e.id, p: null });
            });
            return out;
        }

        // The same Create alias window as the firewall page; the new alias is picked on success.
        function createAlias(fe, fs) {
            if (!window.IdsAliasCreate) { ctx.toast('err', 'Couldn\'t open the window.'); return; }
            fs.dd = false;
            liveForm(fe, fs);
            // What was typed by hand (not an alias) becomes the new alias's first entries.
            const entries = isAlias(fs) ? [] : fs.value.split(/[,\s]+/).filter(Boolean);
            IdsAliasCreate.open({
                peerId: ctx.peerId,
                entries,
                onCreated: async (name) => {
                    try { S.aliases = await loadAliases(); S.aliasesFailed = false; } catch (e) { /* keep the old list */ }
                    fs.value = `@${name}`;
                    fs.err = ''; fs.warn = '';
                    if (fe.isConnected) {
                        liveForm(fe, fs);
                        if (fs.mode === 'edit') refreshEditBtn();
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
                    const picked = bare(fs.value).toLowerCase() === a.name.toLowerCase();
                    try { S.aliases = await loadAliases(); S.aliasesFailed = false; } catch (e) { /* keep the old list */ }
                    if (picked) { fs.value = `@${saved.name}`; fs.err = ''; fs.warn = ''; }
                    if (fe.isConnected) {
                        liveForm(fe, fs);
                        if (fs.mode === 'edit') refreshEditBtn();
                    }
                    drawList();
                },
            });
        }

        // ── Events ──────────────────────────────────────────────────────────

        // Like the firewall page, a row is picked on mousedown (the field keeps focus).
        function keepFocus(ev) {
            const row = ev.target.closest('.ids-ww-aci');
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
            if (fs.mode === 'edit') refreshEditBtn();
        }

        function closeMenus() {
            let changed = false;
            const forms = [[S.add, ova], [S.edit && S.edit.fs, ov]];
            forms.forEach(([fs, root]) => {
                if (!fs || !fs.dd) return;
                fs.dd = false;
                const fe = root && root.querySelector('[data-form]');
                if (fe) liveForm(fe, fs);
                changed = true;
            });
            return changed;
        }

        function onClick(ev) {
            const b = ev.target.closest('button');
            if (ov && ev.target === ov && ov.dataset.downOut) { S.edit = null; drawEdit(); return; }
            if (ova && ev.target === ova && ova.dataset.downOut) { S.open = false; drawAddOv(); return; }
            if (!b) return;
            const x = b.dataset.x;
            const [fe, fs] = formOf(b);
            if (S.confirm && !['keep', 'leave'].includes(x)) { S.confirm = false; drawFoot(); }
            if (x === 'dd' && fs) {
                fs.dd = !fs.dd;
                liveForm(fe, fs);
            } else if (x === 'mkalias' && fs) {
                createAlias(fe, fs);
            } else if (b.dataset.sv && fs) {
                fs.sev = b.dataset.sv;
                fe.querySelectorAll('[data-sv]').forEach((c) => c.classList.toggle('ids-on', c.dataset.sv === fs.sev));
                if (fs.mode === 'edit') refreshEditBtn();
            } else if (x === 'add') doAdd();
            else if (x === 'toggle') {
                S.open = true;
                drawAddOv();
                const inp = ova && ova.querySelector('[data-f="value"]');
                if (inp) inp.focus();
            } else if (x === 'addclose') { S.open = false; drawAddOv(); }
            else if (x === 'ovsave') doEdit();
            else if (x === 'ovclose') { S.edit = null; drawEdit(); }
            else if (x === 'save') save();
            else if (x === 'discard') discard();
            else if (x === 'keep') { S.confirm = false; drawFoot(); }
            else if (x === 'leave') win.close(true);
            else if (b.dataset.edit !== undefined) openEdit(+b.dataset.edit);
            else if (b.dataset.del !== undefined) {
                const it = S.items[+b.dataset.del];
                if (it.p === 'add') S.items.splice(+b.dataset.del, 1); else it.p = 'del';
                S.saved = false; S.err = '';
                redraw();
            } else if (b.dataset.revert !== undefined) {
                const i = +b.dataset.revert;
                S.items[i] = S.items[i].orig;
                redraw();
            } else if (b.dataset.undo !== undefined) {
                const it = S.items[+b.dataset.undo];
                it.p = it.orig ? 'edit' : null;
                redraw();
            }
        }

        function onChange(ev) {
            const t = ev.target;
            if (t.dataset.tog === undefined) return;
            const i = +t.dataset.tog;
            setItem(i, { ...strip(S.items[i]), on: t.checked });
            redraw();
        }

        function onInput(ev) {
            const f = ev.target.dataset.f;
            const [fe, fs] = formOf(ev.target);
            if (!f || !fs) return;
            fs[f] = ev.target.value;
            if (f === 'value') {
                fs.err = '';
                fs.warn = badAlias(fs.value);
                fs.dd = isAlias(fs) && !fs.warn;
            } else fs.nwarn = badName(fs.name);
            liveForm(fe, fs);
            if (fs.mode === 'edit') refreshEditBtn();
        }

        function onFocusOut(ev) {
            const f = ev.target.dataset && ev.target.dataset.f;
            const [fe, fs] = formOf(ev.target);
            if (f !== 'value' || !fs) return;
            const to = ev.relatedTarget;
            if (to && to.closest && to.closest('.ids-ww-acwrap, .ids-ww-ovf')) return;
            if (fs.value.trim() && !fs.warn) {
                fs.err = resolveAlias(fs).err || '';
                fs.dd = false;
                liveForm(fe, fs);
            }
        }

        function onKeydown(ev) {
            const [, fs] = formOf(ev.target);
            if (!fs || ev.target.tagName !== 'INPUT' || ev.key !== 'Enter') return;
            ev.preventDefault();
            if (fs.mode === 'add') doAdd(); else doEdit();
        }

        function onDocClick(ev) {
            if (!win.el.isConnected) { document.removeEventListener('click', onDocClick); return; }
            if (ev.target.closest && ev.target.closest('.ids-ww-acwrap')) return;
            closeMenus();
        }

        // Escape closes the open menu, then the edit window, before the shell sees it.
        function onEscape(ev) {
            if (!win.el.isConnected) { document.removeEventListener('keydown', onEscape, true); return; }
            if (ev.key !== 'Escape') return;
            if (document.querySelector('#idsAcModal.active')) return;   // Create alias above: Escape is its own
            if (closeMenus()) { ev.stopPropagation(); return; }
            if (S.edit) { ev.stopPropagation(); S.edit = null; drawEdit(); return; }
            if (S.open) { ev.stopPropagation(); S.open = false; drawAddOv(); return; }
            if (S.confirm) { ev.stopPropagation(); S.confirm = false; drawFoot(); }
        }
        return ready;
    }

    IdsWin.register('watchlists', { title: 'Watchlists', icon: 'list-check', open });
})();
