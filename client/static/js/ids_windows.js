/**
 * IDS page windows: the shell every Settings / Lists window opens in.
 *
 * A window file registers itself:
 *     IdsWin.register('detection', { title: 'Detection', icon: 'gear', open(ctx, win) { ... } });
 * The page calls IdsWin.open(name) from the right-column links.
 *
 * ctx: { peerId, readonly, api (NkIds.api), N (NkIds), toast(kind, msg), refreshSide(), refreshStatus() }
 * IdsWin.group('settings', { title, icon, items: [names] }) makes IdsWin.open(name) open the group
 * window (side index; every section mounted once at open, switching only shows another) for any name in
 * items. Sections get the same win shape.
 * win: { el, card, body, foot, close(force), setBusy(bool), beforeClose(fn) }
 *   - body / foot are empty elements the window fills.
 *   - beforeClose(fn): fn() returns true to allow closing (e.g. no unsaved changes).
 *   - isDirty(fn) (group sections only, optional): fn() says, without side effects, whether there are
 *     unsaved changes; a section without them is reloaded after another section saves.
 */
(function () {
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

    function close(force) {
        if (!current) return;
        if (!force && current.guard && !current.guard()) return;
        const el = current.el;
        current = null;
        el.classList.remove('active');
        setTimeout(() => el.remove(), 200);
        document.body.classList.remove('ids-win-open');
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

    function wire(el) {
        el.addEventListener('mousedown', (ev) => {
            if (ev.target === el) el.dataset.downOut = '1';
            else delete el.dataset.downOut;
        });
        el.addEventListener('click', (ev) => {
            if ((ev.target === el && el.dataset.downOut) || ev.target.closest('[data-close]')) close(false);
        });
        document.body.classList.add('ids-win-open');
        requestAnimationFrame(() => el.classList.add('active'));
    }

    function open(name) {
        const def = registry[name];
        if (!def || !ctx) return false;
        const g = groupOf(name);
        if (g) return openGroup(g, name);
        close(true);
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
        close(true);
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
            const on = el.querySelector('.ids-grp-item.ids-on');
            if (on && on.scrollIntoView) {
                try { on.scrollIntoView({ block: 'nearest', inline: 'nearest' }); } catch (e) { /* ignore */ }
            }
        }

        // After a save in one section the others show the new values: each one with no
        // unsaved changes is mounted again, out of sight; one with changes keeps them.
        function reloadOthers(saved) {
            if (current !== grp) return;
            names.forEach((k) => {
                const o = grp.secs[k];
                if (k === saved || (o.dirty && o.dirty())) return;
                mount(k, o.el);
            });
        }

        // Every section is mounted once, when the window opens, so switching never reloads.
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
            try {
                def.open(secCtx, sec);
            } catch (e) {
                sec.body.innerHTML = '<div class="ids-win-msg">Couldn\'t open</div>';
            }
        }

        grp.show = (n) => {
            if (!grp.secs[n] || n === grp.active) return;
            grp.active = n;
            names.forEach((k) => { grp.secs[k].el.hidden = k !== n; });
            mark();
        };

        el.querySelector('.ids-grp-index').addEventListener('click', (ev) => {
            const b = ev.target.closest('.ids-grp-item');
            if (b) grp.show(b.dataset.sec);
        });
        current = grp;
        wire(el);
        names.forEach((n) => mount(n));
        grp.show(names.includes(name) ? name : names[0]);
        return true;
    }

    document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape' && current && !document.querySelector('.ids-menu')) close(false);
    });

    window.IdsWin = { register, has, open, close, setContext, group };
})();
