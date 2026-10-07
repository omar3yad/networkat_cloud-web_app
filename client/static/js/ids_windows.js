/**
 * IDS page windows: the shell every Settings / Lists window opens in.
 *
 * A window file registers itself:
 *     IdsWin.register('detection', { title: 'Detection', icon: 'gear', open(ctx, win) { ... } });
 * The page calls IdsWin.open(name) from the right-column links.
 *
 * ctx: { peerId, readonly, api (NkIds.api), N (NkIds), toast(kind, msg), refreshSide(), refreshStatus() }
 * IdsWin.group('settings', { title, icon, items: [names] }) makes IdsWin.open(name) open the group
 * window (side index) for any name in items. Sections get the same win shape. The section asked for
 * mounts (and loads) first; the others mount one after another behind it, each when the one before
 * has loaded, and one the user picks early jumps the queue. A section's open() may return a promise
 * that settles when its first load is done; without one, the next section follows right away.
 * win: { el, card, body, foot, close(force), setBusy(bool), beforeClose(fn) }
 *   - body / foot are empty elements the window fills.
 *   - beforeClose(fn): fn() returns true to allow closing (e.g. no unsaved changes).
 *   - isDirty(fn) (group sections only, optional): fn() says, without side effects, whether there are
 *     unsaved changes; a section without them is reloaded after another section saves.
 */
(function () {
    const LOAD_LIMIT_MS = 8000;
    const registry = {};
    let ctx = null;
    let current = null;

    function register(name, def) {
        registry[name] = def;
    }

    function has(name) {
        return !!registry[name];
    }

    function setContext(c) {
        ctx = c;
    }

    /* Back (phone gesture or button) closes the window instead of leaving the page: an open window owns
       one history entry. Back acts like Escape, so the top layer closes first (a menu, an edit window,
       Create alias, then the window itself); while the window stays open the entry is put back. */
    let pushed = false;   // our entry is the current one
    let ownPops = 0;      // popstates caused by our own history.back()

    function pushEntry() {
        if (pushed) return;
        try { history.pushState({ idsWin: 1 }, ''); pushed = true; } catch (e) { /* no history: Back just leaves */ }
    }

    function dropEntry() {
        if (!pushed) return;
        pushed = false;
        if (history.state && history.state.idsWin) { ownPops++; history.back(); }
    }

    window.addEventListener('popstate', () => {
        if (ownPops) { ownPops--; return; }
        if (!pushed) return;
        pushed = false;   // the browser already took it
        if (!current) return;
        const alias = document.querySelector('#idsAcModal.active');
        if (alias && window.IdsAliasCreate) window.IdsAliasCreate.close();
        else document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        if (current) pushEntry();
    });

    // keep: another window opens right after (it reuses the entry).
    function close(force, keep) {
        if (!current) return;
        if (!force && current.guard && !current.guard()) return;
        const el = current.el;
        current = null;
        el.classList.remove('active');
        setTimeout(() => el.remove(), 200);
        document.body.classList.remove('ids-win-open');
        if (!keep) dropEntry();
    }

    /* A group = one wide window with a side index; each item is a registered window mounted as a section. */
    const groups = {};

    function group(name, def) {
        groups[name] = { name, title: def.title, icon: def.icon, items: def.items || [] };
    }

    function groupOf(name) {
        return Object.keys(groups).map((k) => groups[k]).find((g) => g.items.includes(name)) || null;
    }

    function shell(cls, wide, icon, title) {
        const el = document.createElement('div');
        el.className = `modal-overlay ids-win ${cls}`;
        el.innerHTML =
            `<div class="modal-card ids-win-card${wide}" role="dialog" aria-modal="true">` +
            `<div class="modal-header ids-win-head"><h2>${IdsIcon(icon || 'gear')} ${ctx.N.esc(title || '')}</h2>` +
            '<button type="button" class="modal-close" data-close="1" aria-label="Close">&times;</button></div>' +
            '</div>';
        return el;
    }

    function wire(el, onShown) {
        el.addEventListener('mousedown', (ev) => {
            if (ev.target === el) el.dataset.downOut = '1';
            else delete el.dataset.downOut;
        });
        el.addEventListener('click', (ev) => {
            if ((ev.target === el && el.dataset.downOut) || ev.target.closest('[data-close]')) close(false);
        });
        document.body.classList.add('ids-win-open');
        pushEntry();
        requestAnimationFrame(() => {
            el.classList.add('active');
            if (onShown) onShown();   // now it has a layout (before this it is display:none)
        });
    }

    function open(name) {
        const def = registry[name];
        if (!def || !ctx) return false;
        const g = groupOf(name);
        if (g) return openGroup(g, name);
        close(true, true);
        const el = shell(`ids-win-${name}`, def.wide ? ' ids-win-wide' : '', def.icon, def.title);
        const card = el.querySelector('.ids-win-card');
        card.insertAdjacentHTML('beforeend', '<div class="ids-win-body"></div><div class="ids-win-foot"></div>');
        document.body.appendChild(el);
        const win = {
            el,
            card,
            body: el.querySelector('.ids-win-body'),
            foot: el.querySelector('.ids-win-foot'),
            guard: null,
            close: (force) => close(force),
            beforeClose: (fn) => { win.guard = fn; },
            setBusy: (on) => el.classList.toggle('ids-win-busy', !!on),
        };
        current = win;
        wire(el);
        try {
            def.open(ctx, win);
        } catch (e) {
            win.body.innerHTML = '<div class="ids-win-msg">Couldn\'t open</div>';
        }
        return true;
    }

    function openGroup(g, name) {
        const names = g.items.filter((n) => registry[n]);
        if (!names.length) return false;
        if (current && current.grp === g) { current.show(name); return true; }
        close(true, true);
        const el = shell('ids-win-group', ' ids-win-grp', g.icon, g.title);
        const card = el.querySelector('.ids-win-card');
        card.insertAdjacentHTML('beforeend',
            '<div class="ids-grp"><nav class="ids-grp-index" aria-label="Sections">' +
            names.map((n) => `<button type="button" class="ids-grp-item" data-sec="${n}">` +
                `${IdsIcon(registry[n].icon || 'gear')}<span>${ctx.N.esc(registry[n].title || n)}</span></button>`).join('') +
            '</nav><div class="ids-grp-main"></div></div>');
        document.body.appendChild(el);
        const main = el.querySelector('.ids-grp-main');
        const grp = { el, grp: g, active: null, secs: {} };
        // Closing the window: every section with unsaved changes asks in turn (shown first).
        grp.guard = () => {
            for (const n of names) {
                const sec = grp.secs[n];
                if (sec.released || !sec.guard) continue;
                const back = grp.active;
                if (n !== back) grp.show(n);   // a guard may show its confirm: let it be seen
                if (sec.guard()) { grp.show(back); continue; }
                return false;
            }
            return true;
        };

        function mark() {
            el.querySelectorAll('.ids-grp-item').forEach((b) => {
                const on = b.dataset.sec === grp.active;
                b.classList.toggle('ids-on', on);
                if (on) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current');
            });
            reveal(true);
        }

        // Scrolls the index (a strip on phones, a column on wide screens) so the chosen section is in
        // its middle. Needs a layout: at open the window is still hidden, so open() calls it again once shown.
        function reveal(smooth) {
            const nav = el.querySelector('.ids-grp-index');
            const on = nav && nav.querySelector('.ids-grp-item.ids-on');
            if (!on || !nav.offsetParent) return;
            const left = on.offsetLeft - nav.offsetLeft - (nav.clientWidth - on.offsetWidth) / 2;
            const top = on.offsetTop - nav.offsetTop - (nav.clientHeight - on.offsetHeight) / 2;
            const to = {};
            if (nav.scrollWidth > nav.clientWidth) to.left = Math.max(0, left);
            if (nav.scrollHeight > nav.clientHeight) to.top = Math.max(0, top);
            if (!('left' in to) && !('top' in to)) return;
            try { nav.scrollTo(Object.assign(to, { behavior: smooth ? 'smooth' : 'auto' })); } catch (e) { /* ignore */ }
        }

        // After a save in one section the others show the new values: each one with no
        // unsaved changes is mounted again, out of sight; one with changes keeps them.
        function reloadOthers(saved) {
            if (current !== grp) return;
            names.forEach((k) => {
                const o = grp.secs[k];
                if (k === saved || o.pending || (o.dirty && o.dirty())) return;   // a held one loads fresh at its turn
                mount(k, o.el);
            });
        }

        // A section waiting its turn: a loading placeholder in its place, no requests yet.
        function hold(n) {
            const wrap = document.createElement('div');
            wrap.className = `ids-grp-sec ids-win-${n}`;
            wrap.hidden = true;
            wrap.innerHTML = '<div class="ids-win-body"><div class="ids-win-msg">' +
                IdsIcon('circle-notch', { spin: true }) + ' Loading…</div></div><div class="ids-win-foot"></div>';
            main.appendChild(wrap);
            grp.secs[n] = { el: wrap, pending: true, guard: null, released: false, dirty: null };
        }

        // Mounts one section (a held one takes its placeholder's place). Returns a promise that
        // settles once the section has loaded, or after a limit so one slow section never stalls the queue.
        function mount(n, old) {
            const def = registry[n];
            const wrap = document.createElement('div');
            wrap.className = `ids-grp-sec ids-win-${n}`;
            wrap.hidden = old ? old.hidden : true;
            wrap.innerHTML = '<div class="ids-win-body"></div><div class="ids-win-foot"></div>';
            if (old) old.replaceWith(wrap); else main.appendChild(wrap);
            const secCtx = Object.assign({}, ctx, {
                refreshSide: () => { ctx.refreshSide(); reloadOthers(n); },
            });
            const sec = {
                el: wrap,
                card: wrap,
                body: wrap.firstChild,
                foot: wrap.lastChild,
                guard: null,
                released: false,
                // close(true) after the section dropped its changes: the window closes once no other section objects.
                close(force) {
                    if (current !== grp) return;
                    if (force) sec.released = true;
                    if (!grp.guard()) { sec.released = false; return; }
                    close(true);
                },
                beforeClose: (fn) => { sec.guard = fn; },
                isDirty: (fn) => { sec.dirty = fn; },   // no side effects: true while it has unsaved changes
                setBusy: (on) => wrap.classList.toggle('ids-win-busy', !!on),
            };
            grp.secs[n] = sec;
            let loaded;
            try {
                loaded = def.open(secCtx, sec);
            } catch (e) {
                sec.body.innerHTML = '<div class="ids-win-msg">Couldn\'t open</div>';
            }
            return Promise.race([
                Promise.resolve(loaded).catch(() => {}),
                new Promise((resolve) => setTimeout(resolve, LOAD_LIMIT_MS)),
            ]);
        }

        // The rest of the sections, in order, one at a time; stops when the window closes.
        let draining = false;
        function drain() {
            if (draining) return;
            draining = true;
            const step = () => {
                const next = current === grp ? names.find((k) => grp.secs[k].pending) : null;
                if (!next) { draining = false; return; }
                mount(next, grp.secs[next].el).then(step);
            };
            step();
        }

        grp.show = (n) => {
            if (!grp.secs[n] || n === grp.active) return;
            if (grp.secs[n].pending) mount(n, grp.secs[n].el);   // picked early: jumps the queue
            grp.active = n;
            names.forEach((k) => { grp.secs[k].el.hidden = k !== n; });
            mark();
        };

        el.querySelector('.ids-grp-index').addEventListener('click', (ev) => {
            const b = ev.target.closest('.ids-grp-item');
            if (b) grp.show(b.dataset.sec);
        });
        current = grp;
        wire(el, () => reveal(false));
        const first = names.includes(name) ? name : names[0];
        names.forEach(hold);
        const firstLoaded = mount(first, grp.secs[first].el);
        grp.show(first);
        firstLoaded.then(drain);
        return true;
    }

    document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape' && current && !document.querySelector('.ids-menu')) close(false);
    });

    window.IdsWin = { register, has, open, close, setContext, group };
})();
