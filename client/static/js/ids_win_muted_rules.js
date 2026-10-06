/**
 * IDS page: the "Muted threats" and "Changed rules" windows (Lists).
 *
 * Both are staged list windows (list-window standard): edits wait in the window,
 * rows carry a badge ("Will be removed", "Changed") with an undo arrow, and
 * "Save changes" sends the needed requests one after another (no batch API yet),
 * stopping at the first failure and keeping the rest pending.
 */
(function () {
    // ctx / win / def -> the shared shell of a staged window.
    // def: { load(), descHtml, sectionHtml(), count(), ops(), discard(), click(btn), afterSave(ctx) }
    function stagedWindow(ctx, win, def) {
        const N = ctx.N;
        const S = { phase: 'loading', error: '', ask: false, menu: null, saving: false, saved: false };
        let timer = null;
        win.card.classList.add('ids-wm-card');

        const pending = () => (S.phase === 'ready' ? def.count() : 0);

        function foot() {
            const n = pending();
            if (S.phase !== 'ready') return '';
            let status;
            if (S.saving) {
                status = '<b class="ids-wm-foot-t">' + IdsIcon('circle-notch',{spin:true}) + ' Saving.</b><small>Takes under a minute.</small>';
            } else if (S.saved) {
                status = '<span class="ids-wm-ok">' + IdsIcon('check') + ' Saved.</span>';
            } else if (n) {
                status = `<b class="ids-wm-foot-t">${n} unsaved ${n === 1 ? 'change' : 'changes'}.</b>` +
                    '<small>Changes take effect in under a minute.</small>';
            } else {
                status = '';
            }
            if (S.error) status += `<span class="ids-wm-err">${N.esc(S.error)}</span>`;
            const off = !n || S.saving || ctx.readonly;
            return `<div class="ids-foot-status">${status}</div><div class="ids-foot-btns">` +
                `<button type="button" class="ids-btn" data-x="drop" ${S.saving ? 'disabled' : ''}>Close</button>` +
                `<button type="button" class="ids-btn ids-btn-primary" data-x="save" ${off ? 'disabled' : ''}>` +
                IdsIcon('floppy-disk') + 'Save changes</button></div>';
        }

        function askHtml() {
            return '<div class="ids-wm-ask"><div class="ids-wm-ask-box"><b>Discard unsaved changes?</b>' +
                '<p>Closing now drops them.</p><div class="ids-wm-ask-btns">' +
                '<button type="button" class="ids-btn" data-x="keep">Keep editing</button>' +
                '<button type="button" class="ids-btn ids-btn-danger" data-x="drop">Discard and close</button></div></div></div>';
        }

        function render() {
            if (S.phase === 'loading') {
                win.body.innerHTML = '<div class="ids-win-msg">' + IdsIcon('circle-notch',{spin:true}) + '</div>';
            } else if (S.phase === 'failed') {
                win.body.innerHTML = '<div class="ids-win-msg">Couldn\'t load.</div>';
            } else {
                win.body.innerHTML = `<p class="ids-win-desc">${def.descHtml}</p>` + def.sectionHtml(S);
            }
            win.foot.innerHTML = foot();
            win.card.querySelectorAll('.ids-wm-ask').forEach((e) => e.remove());
            if (S.ask) win.card.insertAdjacentHTML('beforeend', askHtml());
        }

        async function save() {
            if (!pending() || S.saving || ctx.readonly) return;
            S.saving = true; S.error = ''; S.saved = false; S.menu = null;
            win.setBusy(true);
            render();
            const ops = def.ops();
            let done = 0;
            for (const op of ops) {
                try {
                    await op();
                    done++;
                } catch (e) {
                    const left = ops.length - done;
                    S.error = `Couldn't save. ${left} ${left === 1 ? 'change is' : 'changes are'} still unsaved.`;
                    break;
                }
            }
            S.saving = false;
            win.setBusy(false);
            if (done) def.afterSave(ctx);
            if (!S.error) {
                S.saved = true;
                clearTimeout(timer);
                timer = setTimeout(() => { S.saved = false; render(); }, 2000);
            }
            render();
        }

        win.card.addEventListener('click', (ev) => {
            const b = ev.target.closest('button');
            if (!b) {
                if (S.menu !== null) { S.menu = null; render(); }
                return;
            }
            const x = b.dataset.x;
            if (x === 'save') return save();
            if (x === 'discard') { def.discard(); S.error = ''; S.menu = null; return render(); }
            if (x === 'keep') { S.ask = false; return render(); }
            if (x === 'drop') { win.close(true); return; }
            if (b.dataset.menu !== undefined) {
                S.menu = S.menu === b.dataset.menu ? null : b.dataset.menu;
                return render();
            }
            if (S.saving || ctx.readonly) return;
            S.menu = null;
            if (def.click(b)) { S.error = ''; S.saved = false; }
            render();
        });

        // Escape closes the open menu (the shell already skips closing the window while one is shown).
        document.addEventListener('keydown', function onKey(ev) {
            if (!document.body.contains(win.card)) { document.removeEventListener('keydown', onKey); return; }
            if (ev.key === 'Escape' && S.menu !== null) { S.menu = null; render(); }
        });

        if (win.isDirty) win.isDirty(() => S.saving || !!pending());
        win.beforeClose(() => {
            if (S.saving) return false;
            if (!pending()) return true;
            S.ask = true;
            render();
            return false;
        });

        S.render = render;
        render();
        // ready settles when the first load is done (the window shell waits on it before loading the next section).
        S.ready = def.load().then(() => { S.phase = 'ready'; render(); })
            .catch(() => { S.phase = 'failed'; render(); });
        return S;
    }

    // Rule names: the signature of the latest threat of each rule (no rule lookup API yet).
    const ruleNames = new Map();

    const RULE_NAME_REQUESTS = 3;

    function loadRuleNames(ctx, sids, done) {
        const todo = [...new Set(sids)].filter((sid) => !ruleNames.has(sid));
        if (!todo.length) return;
        // One name per rule, no lookup API: a few requests at a time, so they never crowd out the windows' own loads.
        let next = 0;
        const worker = async () => {
            while (next < todo.length) {
                const sid = todo[next++];
                try {
                    const r = await ctx.api.threats(ctx.peerId, { sid, limit: 1 });
                    const e = ((r && r.entries) || [])[0];
                    if (e && e.signature) ruleNames.set(sid, e.signature);
                } catch (err) { /* the row keeps "Rule <number>" */ }
            }
        };
        Promise.all(Array.from({ length: Math.min(RULE_NAME_REQUESTS, todo.length) }, worker)).then(done);
    }

    const isWatchlistSid = (sid) => +sid >= 9950000 && +sid <= 9999999;

    function ruleTitle(N, sid) {
        const name = ruleNames.get(sid);
        // A watchlist hit has no rule number worth showing: its name, or just "Watchlist".
        if (isWatchlistSid(sid)) return name ? N.esc(name) : 'Watchlist';
        return name ? `${N.esc(name)} <span class="ids-wm-sid ids-mono">${N.esc(sid)}</span>` : `Rule ${N.esc(sid)}`;
    }

    // Alias names for muted items (peer alias id or slug -> name).
    async function loadAliasNames(ctx) {
        const names = new Map();
        try {
            const data = await ctx.api.aliases(ctx.peerId);
            (data.lists || []).forEach((a) => {
                [a.id, a.slug].filter(Boolean).forEach((k) => names.set(String(k), a.name || a.slug || a.id));
            });
        } catch (e) { /* the row falls back to "an alias" */ }
        return names;
    }

    function section(N, helpText, rowsHtml) {
        return '<section class="ids-sec"><h3 class="ids-sec-h">In the list</h3>' +
            `<p class="ids-sec-help">${helpText}</p><div class="ids-sec-body">${rowsHtml}</div></section>`;
    }

    function badge(kind) {
        if (kind === 'del') return '<span class="ids-wm-badge ids-wm-del">Will be removed</span>';
        if (kind === 'edit') return '<span class="ids-wm-badge">Changed</span>';
        return '';
    }

    function undoBtn(i, title) {
        return `<button type="button" class="ids-wm-ic" data-undo="${i}" title="${title}" aria-label="${title}">${IdsIcon('rotate-left')}</button>`;
    }

    // ── Muted threats ─────────────────────────────────────────────────────────
    function openMuted(ctx, win) {
        const N = ctx.N;
        let items = []; // { d: item, del: bool }
        let aliases = new Map();
        let S = null;

        const forTxt = (d) => {
            if (d.device) return `For ${N.esc(d.device)}`;
            if (d.alias_id) return aliases.has(String(d.alias_id)) ? `For @${N.esc(aliases.get(String(d.alias_id)))}` : 'For an alias';
            return 'For every device';
        };
        const untilTxt = (d) => (d.expires ? `Until ${N.esc(N.dateTime(d.expires))}` : 'Always');

        function row(it, i) {
            const d = it.d;
            const tail = [forTxt(d), untilTxt(d)].concat(d.comment ? [N.esc(d.comment)] : []).join(' · ');
            const tools = ctx.readonly ? '' : it.del
                ? undoBtn(i, 'Keep it')
                : `<button type="button" class="ids-wm-ic" data-del="${i}" title="Remove" aria-label="Remove">${IdsIcon('trash')}</button>`;
            return `<div class="ids-wm-row ${it.del ? 'ids-wm-gone' : ''}"><div class="ids-wm-text">` +
                `<div class="ids-wm-l"><span class="ids-wm-v">${ruleTitle(N, d.sid)}</span>${badge(it.del ? 'del' : '')}</div>` +
                `<div class="ids-wm-d">${tail}.</div></div><div class="ids-wm-tools">${tools}</div></div>`;
        }

        S = stagedWindow(ctx, win, {
            descHtml: 'Threats that are still inspected but not recorded. Mute one from its details on the IDS page.',
            load: async () => {
                const [res, names] = await Promise.all([ctx.api.list(ctx.peerId, 'muted'), loadAliasNames(ctx)]);
                aliases = names;
                items = ((res && res.items) || []).map((d) => ({ d, del: false }));
                loadRuleNames(ctx, items.map((it) => it.d.sid), () => S && S.render());
            },
            sectionHtml: () => {
                const live = items.filter((it) => !it.del).length;
                const rows = items.length ? items.map(row).join('') : '<div class="ids-wm-empty">Nothing is muted.</div>';
                return section(N, `${live} muted. Remove one; nothing changes until you save.`, rows);
            },
            count: () => items.filter((it) => it.del).length,
            discard: () => items.forEach((it) => { it.del = false; }),
            click: (b) => {
                if (b.dataset.del !== undefined) { items[+b.dataset.del].del = true; return true; }
                if (b.dataset.undo !== undefined) { items[+b.dataset.undo].del = false; return true; }
                return false;
            },
            ops: () => items.filter((it) => it.del).map((it) => async () => {
                await ctx.api.remove(ctx.peerId, 'muted', it.d.id);
                items = items.filter((x) => x !== it);
            }),
            afterSave: (c) => c.refreshSide(),
        });
        return S.ready;
    }

    // ── Changed rules ─────────────────────────────────────────────────────────
    const SEVS = [['', 'Its own severity'], ['high', 'High'], ['medium', 'Medium'], ['low', 'Low']];

    function openRules(ctx, win) {
        const N = ctx.N;
        let items = []; // { sid, off, sev, orig: {off, sev} }
        let S = null;

        const same = (it) => it.off === it.orig.off && (it.sev || null) === (it.orig.sev || null);
        const empty = (it) => !it.off && !it.sev; // on + its own severity = no override left
        const stage = (it) => (same(it) ? '' : empty(it) ? 'del' : 'edit');

        function sevLabel(k) {
            return (SEVS.find((s) => s[0] === (k || '')) || SEVS[0])[1];
        }

        function sevInner(k) {
            return k ? `<span class="ids-wm-dot ids-wm-${k}"></span>${sevLabel(k)}` : sevLabel(k);
        }

        function menuHtml(i, it) {
            return '<div class="ids-menu ids-wm-menu" role="listbox">' + SEVS.map(([k, l]) =>
                `<button type="button" role="option" class="${(it.sev || '') === k ? 'ids-sel' : ''}" data-pick="${i}" data-v="${k}">` +
                `${k ? `<span class="ids-wm-dot ids-wm-${k}"></span>` : ''}<span>${l}</span>` +
                `${(it.sev || '') === k ? IdsIcon('check') : ''}</button>`).join('') + '</div>';
        }

        function row(it, i) {
            const st = stage(it);
            const ro = ctx.readonly ? 'disabled' : '';
            const open = S && S.menu === String(i);
            const seg = `<div class="ids-wm-seg"><button type="button" data-onoff="${i}" data-v="on" class="${it.off ? '' : 'ids-wm-on'}" ${ro}>On</button>` +
                `<button type="button" data-onoff="${i}" data-v="off" class="${it.off ? 'ids-wm-on' : ''}" ${ro}>Off</button></div>`;
            const dd = `<div class="ids-wm-dsel"><button type="button" class="ids-wm-dbtn ${open ? 'ids-wm-open' : ''}" data-menu="${i}" ` +
                `aria-haspopup="listbox" aria-expanded="${open}" ${ro}>${sevInner(it.sev)}${IdsIcon('chevron-down')}</button>` +
                `${open ? menuHtml(i, it) : ''}</div>`;
            const undo = st ? undoBtn(i, st === 'del' ? 'Keep it' : 'Undo the change') : '';
            const reset = !ctx.readonly && st !== 'del'
                ? `<button type="button" class="ids-wm-ic" data-reset="${i}" title="Reset to default" aria-label="Reset to default">${IdsIcon('trash')}</button>` : '';
            const note = `On every device${st === 'del' ? ' · Back to normal after you save' : ''}.`;
            return `<div class="ids-wm-row ids-wm-r3"><div class="ids-wm-text">` +
                `<div class="ids-wm-l"><span class="ids-wm-v">${ruleTitle(N, it.sid)}</span>${badge(st)}</div>` +
                `<div class="ids-wm-d">${note}</div></div>` +
                `<div class="ids-wm-tools">${ctx.readonly ? '' : undo}${seg}${dd}${reset}</div></div>`;
        }

        function set(i, off, sev) {
            items[i].off = off;
            items[i].sev = sev || null;
        }

        S = stagedWindow(ctx, win, {
            descHtml: 'Rules you turned off or gave another severity. Change one from a threat on the IDS page.',
            load: async () => {
                const res = await ctx.api.settings(ctx.peerId);
                items = ((res && res.rule_overrides) || []).map((o) => {
                    const v = { off: !!o.disabled, sev: o.severity || null };
                    return { sid: o.sid, off: v.off, sev: v.sev, orig: v };
                });
                loadRuleNames(ctx, items.map((it) => it.sid), () => S && S.render());
            },
            sectionHtml: () => {
                const live = items.filter((it) => stage(it) !== 'del').length;
                const rows = items.length ? items.map(row).join('') : '<div class="ids-wm-empty">No rules changed.</div>';
                return section(N, `${live} changed. Change one in its row; nothing changes until you save.`, rows);
            },
            count: () => items.filter((it) => stage(it)).length,
            discard: () => items.forEach((it) => set(items.indexOf(it), it.orig.off, it.orig.sev)),
            click: (b) => {
                const d = b.dataset;
                if (d.onoff !== undefined) { const i = +d.onoff; set(i, d.v === 'off', items[i].sev); return true; }
                if (d.pick !== undefined) { const i = +d.pick; set(i, items[i].off, d.v); return true; }
                if (d.reset !== undefined) { set(+d.reset, false, null); return true; }
                if (d.undo !== undefined) { const i = +d.undo; set(i, items[i].orig.off, items[i].orig.sev); return true; }
                return false;
            },
            ops: () => items.filter((it) => stage(it)).map((it) => async () => {
                if (stage(it) === 'del') {
                    await ctx.api.removeRule(ctx.peerId, it.sid);
                    items = items.filter((x) => x !== it);
                } else {
                    const change = {};
                    if (it.off !== it.orig.off) change.disabled = it.off;
                    if ((it.sev || null) !== (it.orig.sev || null)) change.severity = it.sev || null;
                    await ctx.api.setRule(ctx.peerId, it.sid, change);
                    it.orig = { off: it.off, sev: it.sev || null };
                }
            }),
            afterSave: (c) => { c.refreshSide(); c.refreshStatus(); },
        });
        return S.ready;
    }

    IdsWin.register('muted', { title: 'Muted threats', icon: 'bell-slash', open: openMuted });
    IdsWin.register('rules', { title: 'Changed rules', icon: 'pen-to-square', open: openRules });
})();
