/**
 * System logs — shared by the System logs page (system_logs.js) and the peer details
 * widget (peer_system_logs_widget.js).
 *
 * Data comes from FastAPI, not Flask: /api/v2/client/peers/<id>/logs/system/...
 * (fastapi_app/routes/client/system_logs.py), authenticated by the session cookie.
 * Errors come back as {"detail": "...", "code": "..."}; `code` picks the state.
 */
(function () {
    const CATEGORY_LABELS = {
        wan: 'Internet links',
        vpn: 'Private network',
        firewall: 'Firewall',
        web_filter: 'Web filter',
        system: 'Device',
        audit: 'Changes',
    };
    const CATEGORY_ICONS = {
        wan: 'fa-globe',
        vpn: 'fa-project-diagram',
        firewall: 'fa-shield-alt',
        web_filter: 'fa-filter',
        system: 'fa-microchip',
        audit: 'fa-user-edit',
    };
    const ACTOR_LABELS = {
        client: 'You',
        controller: 'Networkat',
        subscription: 'Subscription',
        system: 'Device',
        'auto-update': 'Auto-update',
    };
    const LEVELS = ['info', 'notice', 'warning', 'error', 'critical'];
    const LEVEL_LABELS = { info: 'Info', notice: 'Notice', warning: 'Warning', error: 'Error', critical: 'Critical' };

    // Page states per error code; `detail` from the API is used when not listed.
    const STATES = {
        offline: { icon: 'fa-plug', title: 'Device offline' },
        logs_disabled: { icon: 'fa-eye-slash', title: 'System logs off' },
        unsupported: { icon: 'fa-arrow-alt-circle-up', title: 'Update device' },
        not_found: { icon: 'fa-question-circle', title: 'Device not found' },
        signed_out: { icon: 'fa-lock', title: 'Signed out' },
        error: { icon: 'fa-exclamation-triangle', title: 'Couldn\'t load' },
    };

    class ApiError extends Error {
        constructor(status, detail, code) {
            super(detail || 'Request failed');
            this.status = status;
            this.code = code || (status === 401 ? 'signed_out' : status === 404 ? 'not_found' : 'error');
        }
    }

    function base(peerId) {
        return `/api/v2/client/peers/${encodeURIComponent(peerId)}/logs/system`;
    }

    async function request(peerId, path, { method = 'GET', params, body } = {}) {
        const qs = params ? new URLSearchParams(
            Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== '')
        ).toString() : '';
        const init = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
        if (body !== undefined) {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(body);
        }
        let res;
        try {
            res = await fetch(base(peerId) + path + (qs ? `?${qs}` : ''), init);
        } catch (e) {
            throw new ApiError(0, 'Network error', 'error');
        }
        let data = null;
        try { data = await res.json(); } catch (e) { /* empty body */ }
        if (!res.ok) {
            const detail = data && typeof data.detail === 'string' ? data.detail : null;
            throw new ApiError(res.status, detail, data && data.code);
        }
        return data;
    }

    const api = {
        list: (peerId, params) => request(peerId, '', { params }),
        categories: (peerId) => request(peerId, '/categories'),
        config: (peerId) => request(peerId, '/config'),
        saveConfig: (peerId, categories) => request(peerId, '/config', { method: 'PUT', body: { categories } }),
        clear: (peerId, categories) => request(peerId, '', {
            method: 'DELETE', params: { category: (categories || []).join(',') },
        }),
        setService: (peerId, state) => request(peerId, '/service', { method: 'PUT', body: { state } }),
        streamUrl: (peerId, params) => {
            const qs = new URLSearchParams(
                Object.entries(params || {}).filter(([, v]) => v !== null && v !== undefined && v !== '')
            ).toString();
            return base(peerId) + '/stream' + (qs ? `?${qs}` : '');
        },
    };

    function esc(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    function categoryLabel(name) {
        return CATEGORY_LABELS[name] || name;
    }

    function actorLabel(actor) {
        return ACTOR_LABELS[actor] || '—';
    }

    function levelLabel(level) {
        return LEVEL_LABELS[level] || level;
    }

    function pad(n) {
        return String(n).padStart(2, '0');
    }

    // Local time: "14:05:09" today, "Sep 25, 14:05" this year, else "Sep 25, 2025".
    function shortTime(iso) {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        const now = new Date();
        const clock = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        if (d.toDateString() === now.toDateString()) return clock;
        const month = d.toLocaleString('en-US', { month: 'short' });
        if (d.getFullYear() === now.getFullYear()) {
            return `${month} ${d.getDate()}, ${pad(d.getHours())}:${pad(d.getMinutes())}`;
        }
        return `${month} ${d.getDate()}, ${d.getFullYear()}`;
    }

    // Full local time for hover.
    function fullTime(iso) {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        return d.toLocaleString('en-US', {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
        });
    }

    function levelBadge(level) {
        const lv = LEVELS.includes(level) ? level : 'info';
        return `<span class="sl-level sl-level-${lv}">${esc(levelLabel(lv))}</span>`;
    }

    function stateFor(err) {
        const code = err && err.code;
        const s = STATES[code] || STATES.error;
        return { code: STATES[code] ? code : 'error', icon: s.icon, title: s.title };
    }

    window.NkSystemLogs = {
        CATEGORY_LABELS, CATEGORY_ICONS, LEVELS, ApiError, api, esc,
        categoryLabel, actorLabel, levelLabel, levelBadge, shortTime, fullTime, stateFor,
    };
})();
