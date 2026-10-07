/**
 * IDS page: the "Create alias" window, a faithful copy of the firewall page's
 * Add alias modal (templates/firewall.html #listModal + the add branch of
 * static/js/firewall.js). Same markup, classes, validation and API call
 * (POST /api/peers/<id>/aliases). firewall.js itself can't be loaded here: it
 * redirects offline peers and starts its own refresh timers.
 *
 *   IdsAliasCreate.open({ peerId, entries?: [string], onCreated(name) })   (entries pre-fill the rows)
 *   IdsAliasCreate.open({ peerId, alias: {id, slug, name, comment, type, list} | aliasId, onSaved(alias) })
 *
 * The second form is the aliases page's Edit alias window: the name and comment go
 * out with PATCH /api/peers/<id>/aliases/<slug>, the items with PUT on the same path
 * (an agent without alias ids gets the old single PUT, the name stays read-only).
 * The type cannot change. onSaved gets {id, slug, name, oldName, comment, type, list}.
 *
 * The window builds itself on first use and injects its own scoped styles
 * (the firewall modal styles live in firewall.css, which this page doesn't load).
 */
(function () {
    if (window.IdsAliasCreate) return;

    const API = () => (window.API_BASE || '');
    let root = null;
    let cfg = null;
    let resolver = null; // resolver-config, needed to validate hostnames
    let busy = false;
    let edit = null; // { slug, oldName, isNew, type } while editing, else null

    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    const CSS = `
#idsAcModal{z-index:2800}
#idsAcModal .modal-card{max-width:650px;overflow:visible}
#idsAcModal .modal-body{padding:1.5rem;display:flex;flex-direction:column;max-height:70vh;overflow-y:auto}
#idsAcModal .modal-header{padding:1.5rem}
#idsAcModal .modal-header h2{font-size:1.2rem;font-weight:800;color:var(--nk-navy)}
#idsAcModal .modal-close{background:none;border:none;font-size:1.25rem;color:var(--nk-text-muted);cursor:pointer}
#idsAcModal .modal-close:hover{color:var(--nk-text-main)}
#idsAcModal .form-row{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.25rem}
#idsAcModal .form-group label{display:block;font-size:.8rem;font-weight:700;color:var(--nk-text-muted);margin-bottom:.5rem;text-transform:capitalize;letter-spacing:.5px}
#idsAcModal .form-group input{width:100%;padding:.75rem 1rem;border:1px solid var(--nk-border);border-radius:var(--nk-radius-sm);font-family:inherit;font-size:.9rem;outline:none;transition:var(--nk-transition)}
#idsAcModal .form-group input:focus{border-color:var(--nk-blue-primary);box-shadow:0 0 0 3px rgba(2,132,199,.15)}
#idsAcModal input.is-invalid{border-color:#ef4444!important;box-shadow:0 0 0 3px rgba(239,68,68,.15)!important}
#idsAcModal .field-error-msg{color:#dc2626;font-size:.76rem;font-weight:600;margin-top:4px;display:flex;align-items:center;gap:4px;line-height:1.25}
#idsAcModal .char-counter{font-size:.72rem;color:var(--nk-text-muted);font-weight:600;float:right}
#idsAcModal .char-counter.warning{color:#b45309}
#idsAcModal .char-counter.error{color:#dc2626}
#idsAcModal #idsAcRows{max-height:300px;overflow-y:auto;padding-right:5px}
#idsAcModal .btn-action{background:#fff;border:1px solid var(--nk-border);color:var(--nk-text-main);padding:.5rem 1rem;border-radius:var(--nk-radius-sm);font-weight:600;font-size:.88rem;cursor:pointer;display:inline-flex;align-items:center;gap:.5rem;transition:var(--nk-transition)}
#idsAcModal .btn-action:hover:not(:disabled){background:#90d1f2;border-color:#90d1f2;color:#fff}
#idsAcModal .btn-action:disabled{opacity:.5;cursor:not-allowed}
#idsAcModal .btn-action.btn-primary{background:var(--nk-blue-primary);color:#fff;border-color:var(--nk-blue-primary)}
#idsAcModal .btn-action.btn-primary:hover:not(:disabled){background:#90d1f2;border-color:#90d1f2;color:#fff}
#idsAcModal .btn-delete{background:none;border:none;color:var(--nk-text-muted);cursor:pointer;padding:.35rem;border-radius:6px;transition:var(--nk-transition)}
#idsAcModal .btn-delete:hover:not(:disabled){background:#fee2e2;color:#ef4444}
#idsAcModal .modal-footer{padding:1rem 1.5rem;background:#f8fafc;border-top:1px solid var(--nk-border);display:flex;justify-content:flex-end;gap:.75rem;border-radius:0 0 15px 15px}
@media (max-width:560px){#idsAcModal .form-row{grid-template-columns:1fr}#idsAcModal .modal-body,#idsAcModal .modal-header{padding:1rem}}
`;

    const HTML = `
<div class="modal-card" style="max-width: 650px;">
  <div class="modal-header"><h2 id="idsAcTitle">Create alias</h2><button type="button" class="modal-close" data-ac="close" aria-label="Close">&times;</button></div>
  <div class="modal-body" style="max-height: 70vh; overflow-y: auto;">
    <form id="idsAcForm" novalidate>
      <div class="form-row">
        <div class="form-group">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;"><label style="margin-bottom:0;">Name *</label><span class="char-counter" id="idsAcSlug-counter">0 / 200</span></div>
          <input type="text" id="idsAcSlug" placeholder="e.g. sales" required maxlength="200" title="Alias Name. Max 200 characters.">
          <div class="field-error-msg" id="idsAcSlug-error" style="display:none;"></div>
        </div>
        <div class="form-group">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;"><label style="margin-bottom:0;">Comment</label><span class="char-counter" id="idsAcComment-counter">0 / 200</span></div>
          <input type="text" id="idsAcComment" placeholder="e.g. Sales Department" maxlength="200">
          <div class="field-error-msg" id="idsAcComment-error" style="display:none;"></div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group" style="max-width: 320px;">
          <label>Type *</label>
          <select id="idsAcType" style="width:100%;padding:0.5rem 0.75rem;border:1px solid var(--nk-border);border-radius:var(--nk-radius-sm);font-size:0.88rem;">
            <option value="normal">Normal (IP / Hostname)</option>
            <option value="web_domain">Web Domain (for filtering)</option>
          </select>
        </div>
      </div>
      <div style="margin-top:1.5rem;margin-bottom:0.5rem;display:flex;justify-content:space-between;align-items:center;position:sticky;top:-28px;background:white;padding:12px 0 13px 0;z-index:5;">
        <h3 style="font-size:0.8rem;font-weight:700;color:var(--nk-text-muted);text-transform:capitalize;letter-spacing:0.5px;">Items</h3>
        <button type="button" class="btn-action" data-ac="addrow" style="padding:0.35rem 0.75rem;font-size:0.8rem;">${IdsIcon('plus')} Add</button>
      </div>
      <div class="field-error-msg" id="idsAcItems-error" style="display:none;margin-bottom:0.75rem;"></div>
      <div id="idsAcRows"></div>
    </form>
  </div>
  <div class="modal-footer">
    <button type="button" class="btn-action" data-ac="close">Cancel</button>
    <button type="button" class="btn-action btn-primary" data-ac="submit" id="idsAcSubmit">Add alias</button>
  </div>
</div>`;

    // ── Validation (same rules as firewall.js) ──────────────────────────────

    function validateName(name) {
        if (!name || !name.trim()) return { valid: false, error: 'Required' };
        if (name.trim().length > 200) return { valid: false, error: 'Max 200 characters' };
        return { valid: true };
    }

    function validateComment(c) {
        if (c && c.length > 200) return { valid: false, error: 'Max 200 characters' };
        return { valid: true };
    }

    function matchesLocalDomain(hostname) {
        const ups = resolver && resolver.upstream_dns;
        const domains = (ups || []).filter((u) => u.domain && u.domain.trim()).map((u) => u.domain.trim().toLowerCase());
        if (!domains.length) return { valid: false, error: 'No local resolver configured' };
        const h = hostname.toLowerCase();
        if (!domains.some((d) => h === d || h.endsWith('.' + d))) return { valid: false, error: 'Must match a Local Domain Server' };
        return { valid: true };
    }

    function validateEntry(value, type) {
        if (!value || !value.trim()) return { valid: false, error: 'Required' };
        const t = value.trim();
        if (type === 'web_domain') {
            if (t === '*' || t === '*.') return { valid: false, error: 'Invalid domain' };
            if (/^(\d{1,3}\.){3}\d{1,3}(\/\d+)?$/.test(t)) return { valid: false, error: 'Enter domain name' };
            const re = /^(\*\.)?([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z0-9]{2,}$/;
            if (!re.test(t)) return { valid: false, error: 'Invalid domain' };
            return { valid: true, normalized: t, entryType: 'domain' };
        }
        const c = t[0];
        if (/^[0-9]/.test(c)) {
            const ip = window.parseAndValidateIPv4(t, { requireMask: false, allowMask: true, normalizeSubnet: true });
            if (ip.valid) return { valid: true, entryType: 'address', normalized: ip.normalized };
            const hr = window.validateHostname ? window.validateHostname(t) : null;
            if (hr && hr.valid) {
                const l = matchesLocalDomain(t);
                if (!l.valid) return l;
                return { valid: true, entryType: 'hostname', normalized: t };
            }
            return ip;
        }
        if (/^[a-zA-Z]/.test(c)) {
            const hr = window.validateHostname ? window.validateHostname(t) : null;
            if (hr) {
                if (!hr.valid) return { valid: false, error: hr.error || 'Invalid hostname' };
            } else {
                const re = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/;
                if (!re.test(t) || t.length > 253) return { valid: false, error: 'Invalid hostname' };
            }
            const l = matchesLocalDomain(t);
            if (!l.valid) return l;
            return { valid: true, entryType: 'hostname', normalized: t };
        }
        return { valid: false, error: 'Invalid format (enter IPv4, CIDR, or Hostname)' };
    }

    // ── Field errors ────────────────────────────────────────────────────────

    function setErr(id, msg) {
        const input = $(id), d = $(`${id}-error`);
        if (input) input.classList.add('is-invalid');
        if (d) { d.innerHTML = `${IdsIcon('exclamation-circle')} ${msg}`; d.style.display = 'flex'; }
    }

    function clearErr(id) {
        const input = $(id), d = $(`${id}-error`);
        if (input) input.classList.remove('is-invalid');
        if (d) { d.textContent = ''; d.style.display = 'none'; }
    }

    function clearAllErrors() {
        ['idsAcSlug', 'idsAcComment', 'idsAcItems'].forEach(clearErr);
        root.querySelectorAll('.row-error-msg').forEach((el) => { el.textContent = ''; el.style.display = 'none'; });
        root.querySelectorAll('.is-invalid').forEach((el) => el.classList.remove('is-invalid'));
    }

    function counter(inputId, counterId) {
        const len = $(inputId).value.length;
        const c = $(counterId);
        c.textContent = `${len} / 200`;
        c.className = 'char-counter' + (len > 180 ? (len > 200 ? ' error' : ' warning') : '');
    }

    // ── Item rows ───────────────────────────────────────────────────────────

    function placeholder() {
        return $('idsAcType').value === 'web_domain'
            ? 'Domain or pattern (e.g. facebook.com, *.doubleclick.net)'
            : 'IP Address, CIDR or Hostname (e.g. 192.168.10.5, server.local)';
    }

    function addRow() {
        const row = document.createElement('div');
        row.className = 'address-row';
        row.style.cssText = 'display:flex;flex-direction:column;margin-bottom:0.75rem;';
        const inp = 'width:100%;padding:0.5rem 0.75rem;border:1px solid var(--nk-border);border-radius:var(--nk-radius-sm);font-size:0.88rem;';
        row.innerHTML = `
<div style="display:flex;gap:0.75rem;align-items:center;">
  <div style="flex:1.2;"><input type="text" placeholder="${esc(placeholder())}" class="addr-input" required style="${inp}"></div>
  <div style="flex:1;"><input type="text" placeholder="Comment (e.g. Dev Server)" class="addr-comment" style="${inp}" maxlength="200"></div>
  <button type="button" class="btn-delete" data-ac="delrow" aria-label="Remove item" style="padding:0.5rem;display:flex;align-items:center;justify-content:center;height:38px;width:38px;">${IdsIcon('trash-alt')}</button>
</div>
<div class="field-error-msg row-error-msg" style="display:none;"></div>`;
        $('idsAcRows').appendChild(row);
        const a = row.querySelector('.addr-input');
        const err = row.querySelector('.row-error-msg');
        a.addEventListener('input', () => {
            const r = validateEntry(a.value, $('idsAcType').value);
            if (!r.valid) {
                a.classList.add('is-invalid');
                err.innerHTML = `${IdsIcon('exclamation-circle')} ${r.error}`;
                err.style.display = 'flex';
            } else {
                a.classList.remove('is-invalid');
                err.textContent = '';
                err.style.display = 'none';
            }
        });
    }

    function onTypeChange() {
        const ph = placeholder();
        root.querySelectorAll('#idsAcRows .addr-input').forEach((i) => {
            i.placeholder = ph;
            if (i.value.trim()) i.dispatchEvent(new Event('input'));
        });
    }

    // ── Submit ──────────────────────────────────────────────────────────────

    async function submit() {
        if (busy) return;
        clearAllErrors();
        const slug = $('idsAcSlug').value.trim();
        const comment = $('idsAcComment').value.trim();
        const type = $('idsAcType').value;
        let bad = false, first = null;
        const mark = (el) => { bad = true; if (!first) first = el; };

        const n = validateName(slug);
        if (!n.valid) { setErr('idsAcSlug', n.error); mark($('idsAcSlug')); }
        const c = validateComment(comment);
        if (!c.valid) { setErr('idsAcComment', c.error); mark($('idsAcComment')); }

        const entries = [];
        const seen = new Set();
        root.querySelectorAll('#idsAcRows .address-row').forEach((row) => {
            const a = row.querySelector('.addr-input');
            const ci = row.querySelector('.addr-comment');
            const err = row.querySelector('.row-error-msg');
            const val = a ? a.value.trim() : '';
            const rc = (ci ? ci.value.trim() : '') || null;
            const fail = (msg) => {
                if (a) a.classList.add('is-invalid');
                if (err) { err.innerHTML = `${IdsIcon('exclamation-circle')} ${msg}`; err.style.display = 'flex'; }
                mark(a);
            };
            if (!val) return fail('Required');
            const r = validateEntry(val, type);
            if (!r.valid) return fail(r.error);
            const norm = r.normalized || val;
            if (a && a.value !== norm) a.value = norm;
            if (seen.has(norm.toLowerCase())) return fail('Duplicate item');
            seen.add(norm.toLowerCase());
            if (type === 'web_domain') entries.push({ domain: norm, comment: rc });
            else if (r.entryType === 'address') entries.push({ address: norm, comment: rc });
            else entries.push({ hostname: norm, comment: rc });
        });
        if (!entries.length) { setErr('idsAcItems', 'At least 1 item required'); bad = true; }
        else if (entries.length > 256) { setErr('idsAcItems', 'Max 256 items'); bad = true; }
        if (bad) { if (first) first.focus(); return; }

        busy = true;
        $('idsAcSubmit').disabled = true;
        try {
            const send = async (url, method, body) => {
                let res;
                try {
                    res = await fetch(url, {
                        method,
                        credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body),
                    });
                } finally {
                    if (window.NkIds) NkIds.api.bust();   // the alias list changed: windows must re-read it
                }
                let data = null;
                try { data = await res.json(); } catch (e) { /* empty body */ }
                if (!res.ok) throw new Error((data && (data.message || data.error || data.detail)) || 'Failed to save');
                return data;
            };
            const base = `${API()}/api/peers/${encodeURIComponent(cfg.peerId)}/aliases`;
            if (edit) {
                // Same calls as the aliases page.
                const url = `${base}/${encodeURIComponent(edit.slug)}`;
                if (edit.isNew) {
                    await send(url, 'PATCH', { name: slug, comment });
                    await send(url, 'PUT', { list: entries });
                } else {
                    await send(url, 'PUT', { slug: edit.slug, comment, list: entries });
                }
                const saved = { id: edit.id, slug: edit.isNew ? slug : edit.slug, name: edit.isNew ? slug : edit.oldName, oldName: edit.oldName, comment, type: edit.type, list: entries };
                const doneS = cfg.onSaved;
                close();
                if (window.showSuccess) window.showSuccess('Saved');
                if (doneS) doneS(saved);
                return;
            }
            await send(base, 'POST', { name: slug, slug, comment, type, list: entries });
            const done = cfg.onCreated;
            close();
            if (window.showSuccess) window.showSuccess('Saved');
            if (done) done(slug);
        } catch (err) {
            const msg = err.message || 'Failed';
            if (window.showError) window.showError(msg); else alert(msg);
        } finally {
            busy = false;
            $('idsAcSubmit').disabled = false;
        }
    }

    // ── Open / close ────────────────────────────────────────────────────────

    function build() {
        const st = document.createElement('style');
        st.textContent = CSS;
        document.head.appendChild(st);
        root = document.createElement('div');
        root.className = 'modal-overlay';
        root.id = 'idsAcModal';
        root.innerHTML = HTML;
        document.body.appendChild(root);
        root.addEventListener('click', (ev) => {
            if (ev.target === root && root.dataset.down === '1') { close(); return; }
            const b = ev.target.closest('[data-ac]');
            if (!b) return;
            const a = b.dataset.ac;
            if (a === 'close') close();
            else if (a === 'submit') submit();
            else if (a === 'addrow') addRow();
            else if (a === 'delrow') {
                const row = b.closest('.address-row');
                if (row) row.remove();
                if (!$('idsAcRows').children.length) addRow();
            }
        });
        root.addEventListener('mousedown', (ev) => { root.dataset.down = ev.target === root ? '1' : ''; });
        root.addEventListener('submit', (ev) => { ev.preventDefault(); submit(); });
        $('idsAcType').addEventListener('change', onTypeChange);
        $('idsAcSlug').addEventListener('input', () => { counter('idsAcSlug', 'idsAcSlug-counter'); clearErr('idsAcSlug'); });
        $('idsAcComment').addEventListener('input', () => { counter('idsAcComment', 'idsAcComment-counter'); clearErr('idsAcComment'); });
        $('idsAcForm').addEventListener('submit', (ev) => { ev.preventDefault(); submit(); });
        // Escape closes this window only (window capture runs before the shell's handler).
        window.addEventListener('keydown', (ev) => {
            if (ev.key !== 'Escape' || !isOpen()) return;
            ev.stopPropagation();
            ev.preventDefault();
            close();
        }, true);
    }

    const isOpen = () => !!root && root.classList.contains('active');

    function close() {
        if (!root) return;
        root.classList.remove('active');
        clearAllErrors();
    }

    async function loadResolver(peerId) {
        try {
            const res = await fetch(`${API()}/api/peers/${encodeURIComponent(peerId)}/resolver-config`, { credentials: 'same-origin' });
            if (res.ok) resolver = await res.json();
        } catch (e) { /* hostnames then fail with "No local resolver configured" */ }
    }

    async function findAlias(peerId, id) {
        try {
            const res = await fetch(`${API()}/api/peers/${encodeURIComponent(peerId)}/aliases`, { credentials: 'same-origin' });
            const data = await res.json();
            return (data.lists || []).find((a) => a.id === id || a.slug === id) || null;
        } catch (e) { return null; }
    }

    async function open(options) {
        cfg = options;
        let al = cfg.alias || null;
        if (!al && cfg.aliasId) {
            al = await findAlias(cfg.peerId, cfg.aliasId);
            if (!al) { if (window.showError) window.showError('Alias not found'); return; }
        }
        if (!root) build();
        clearAllErrors();
        edit = null;
        $('idsAcRows').innerHTML = '';
        if (al) {
            // Edit: the type is fixed, the name only changes on agents that can rename.
            const nameVal = al.name || al.slug || '';
            edit = { id: al.id, slug: al.slug || al.id, oldName: nameVal, isNew: al.id !== undefined, type: al.type || 'normal' };
            $('idsAcTitle').textContent = 'Edit alias';
            $('idsAcSubmit').textContent = 'Save changes';
            $('idsAcSlug').value = nameVal;
            $('idsAcSlug').disabled = !edit.isNew;
            $('idsAcComment').value = al.comment || '';
            $('idsAcType').value = edit.type;
            $('idsAcType').disabled = true;
            (al.list || []).forEach((it) => {
                addRow();
                const row = $('idsAcRows').lastElementChild;
                row.querySelector('.addr-input').value = it.address || it.hostname || it.domain || '';
                row.querySelector('.addr-comment').value = it.comment || '';
            });
            if (!$('idsAcRows').children.length) addRow();
        } else {
            $('idsAcTitle').textContent = 'Create alias';
            $('idsAcSubmit').textContent = 'Add alias';
            $('idsAcSlug').value = '';
            $('idsAcSlug').disabled = false;
            $('idsAcComment').value = '';
            $('idsAcType').value = 'normal';
            $('idsAcType').disabled = false;
            (cfg.entries || []).forEach((v) => {
                addRow();
                $('idsAcRows').lastElementChild.querySelector('.addr-input').value = v;
            });
            if (!$('idsAcRows').children.length) addRow();
        }
        counter('idsAcSlug', 'idsAcSlug-counter');
        counter('idsAcComment', 'idsAcComment-counter');
        root.classList.add('active');
        if (window.NkIds) NkIds.focusDialog(root);
        loadResolver(cfg.peerId);
    }

    window.IdsAliasCreate = { open, close, isOpen };
})();
