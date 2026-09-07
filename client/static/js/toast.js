/**
 * Networkat Custom Toast, Alert & Confirmation Modal System
 */
(function () {
    'use strict';

    function toggleMobileSidebar() {
        const sidebar = document.getElementById('app-sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        if (!sidebar || !overlay) return;
        if (sidebar.classList.contains('open')) {
            sidebar.classList.remove('open');
            overlay.classList.remove('active');
        } else {
            sidebar.classList.add('open');
            overlay.classList.add('active');
        }
    }

    function togglePeerSubmenu(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        const group = document.getElementById('nav-group-peers');
        if (group) {
            group.classList.toggle('open');
        }
    }

    function formatFriendlyErrorMessage(rawMsg) {
        if (!rawMsg && rawMsg !== 0) return 'Action failed';
        let msg = typeof rawMsg === 'object' ? (rawMsg.message || rawMsg.detail || rawMsg.error || JSON.stringify(rawMsg)) : String(rawMsg);

        // 1. Connection / Timeout / Network Exceptions & Stacks
        if (/HTTPConnectionPool|NewConnectionError|Connection refused|Max retries exceeded|Failed to establish a new connection|No route to host|ConnectTimeout|ReadTimeout/i.test(msg)) {
            if (/dns|adguard|resolver/i.test(msg)) {
                return 'DNS service is unreachable';
            }
            return 'Device is unreachable';
        }

        // 2. Concise alias reference errors
        msg = msg.replace(/alias\s+'[^']+'\s+\(([^)]+)\)\s+is referenced by web-filter rule\(s\):?.*/i, 'Alias "$1" is used in Web Filter');
        msg = msg.replace(/alias\s+'([^']+)'\s+is referenced by web-filter rule\(s\):?.*/i, 'Alias "$1" is used in Web Filter');

        msg = msg.replace(/alias\s+'[^']+'\s+\(([^)]+)\)\s+is referenced by firewall rule\(s\):?.*/i, 'Alias "$1" is used in Firewall');
        msg = msg.replace(/alias\s+'([^']+)'\s+is referenced by firewall rule\(s\):?.*/i, 'Alias "$1" is used in Firewall');

        msg = msg.replace(/alias\s+'[^']+'\s+\(([^)]+)\)\s+is referenced by\s+(.*)/i, 'Alias "$1" is in use');
        msg = msg.replace(/alias\s+'([^']+)'\s+is referenced by\s+(.*)/i, 'Alias "$1" is in use');

        // 3. Technical backend terms masking
        msg = msg.replace(/failed to push .* to AdGuard/i, 'Failed to update DNS rules');
        msg = msg.replace(/Could not connect to AdGuard.*/i, 'DNS service is unreachable');
        msg = msg.replace(/AdGuard\s+API\s+error.*/i, 'DNS service error');
        msg = msg.replace(/AdGuard\s+service\s+is\s+offline\s+or\s+unreachable/i, 'DNS service is unreachable');
        msg = msg.replace(/AdGuard/gi, 'DNS service');
        msg = msg.replace(/NetBird/gi, 'Network');

        // 4. Clean raw alias IDs
        msg = msg.replace(/@alias_([a-zA-Z0-9_-]+)/g, '$1');
        msg = msg.replace(/alias_([a-zA-Z0-9_-]+)/g, '$1');

        // 5. Strip technical prefixes, status codes & stack details
        msg = msg.replace(/^Error:\s*/i, '');
        msg = msg.replace(/^HTTP\s+\d+:\s*/i, '');
        msg = msg.replace(/^[0-9]{3}\s+Client Error:\s*/i, '');
        msg = msg.replace(/500 Internal Server Error/i, 'Server error');
        msg = msg.replace(/502 Bad Gateway/i, 'Device unreachable');
        msg = msg.replace(/503 Service Unavailable/i, 'Service unavailable');
        msg = msg.replace(/504 Gateway Timeout/i, 'Request timed out');
        msg = msg.replace(/404 Not Found/i, 'Not found');
        msg = msg.replace(/403 Forbidden/i, 'Access denied');
        msg = msg.replace(/401 Unauthorized/i, 'Unauthorized');

        // 6. If message contains raw Python/JSON code or too long stack trace, fallback to clean text
        if (msg.includes('Traceback') || msg.includes('requests.exceptions') || msg.length > 120) {
            if (/dns|resolver|forwarding/i.test(msg)) return 'DNS service is unreachable';
            return 'Action failed';
        }

        msg = msg.trim();
        return msg || 'Action failed';
    }

    function showToast(message, type = 'info', duration = 1800) {
        let container = document.getElementById('nk-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'nk-toast-container';
            document.body.appendChild(container);
        }

        // Clean up and standardize message
        let displayMsg = message || 'Saved';
        if (type === 'error' || type === 'warning') {
            displayMsg = formatFriendlyErrorMessage(displayMsg);
        } else {
            const lower = String(displayMsg).trim().toLowerCase();
            if (lower === 'saved successfully' || lower === 'saved successfully.' || lower === 'saved' || lower === 'success') {
                displayMsg = 'Saved';
            } else if (lower === 'deleted successfully' || lower === 'deleted successfully.' || lower === 'deleted') {
                displayMsg = 'Deleted';
            } else if (lower === 'synced successfully' || lower === 'synced successfully.' || lower === 'synced') {
                displayMsg = 'Synced';
            }
        }

        let iconClass = 'fa-info-circle';
        if (type === 'success') {
            iconClass = 'fa-check-circle';
        } else if (type === 'error') {
            iconClass = 'fa-exclamation-circle';
        } else if (type === 'warning') {
            iconClass = 'fa-exclamation-triangle';
        }

        const toast = document.createElement('div');
        toast.className = `nk-toast toast-${type}`;
        toast.innerHTML = `
            <i class="fas ${iconClass} nk-toast-icon-i"></i>
            <span class="nk-toast-msg">${displayMsg}</span>
        `;

        container.appendChild(toast);

        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        setTimeout(() => {
            dismissToast(toast);
        }, duration);
    }

    function dismissToast(toast) {
        if (!toast || toast.classList.contains('hide')) return;
        toast.classList.remove('show');
        toast.classList.add('hide');
        setTimeout(() => {
            if (toast.parentElement) toast.remove();
        }, 250);
    }

    // Global Alert Dialog (Modal format with OK button)
    function nkAlert(message, type = 'info', title = null) {
        return new Promise((resolve) => {
            const backdrop = document.getElementById('nk-alert-backdrop');
            const iconWrap = document.getElementById('nk-alert-icon-wrap');
            const icon = document.getElementById('nk-alert-icon');
            const titleEl = document.getElementById('nk-alert-title');
            const msgEl = document.getElementById('nk-alert-message');
            const footer = document.getElementById('nk-alert-footer');

            const cleanMsg = formatFriendlyErrorMessage(message);

            if (!backdrop) {
                showToast(cleanMsg, type === 'error' ? 'error' : 'info', 4000);
                resolve();
                return;
            }

            iconWrap.className = `nk-alert-icon-wrap ${type}`;
            let defaultTitle = 'Notification';
            if (type === 'success') {
                icon.className = 'fas fa-check-circle';
                defaultTitle = 'Success';
            } else if (type === 'error') {
                icon.className = 'fas fa-exclamation-circle';
                defaultTitle = 'Error';
            } else if (type === 'warning') {
                icon.className = 'fas fa-exclamation-triangle';
                defaultTitle = 'Warning';
            } else {
                icon.className = 'fas fa-info-circle';
            }

            titleEl.textContent = title || defaultTitle;
            msgEl.textContent = cleanMsg;

            footer.innerHTML = `<button class="nk-alert-btn nk-alert-btn-primary" id="nk-alert-btn-ok">OK</button>`;
            const okBtn = document.getElementById('nk-alert-btn-ok');

            backdrop.style.display = 'flex';
            requestAnimationFrame(() => {
                backdrop.classList.add('show');
                if (okBtn) okBtn.focus();
            });

            function cleanup() {
                backdrop.classList.remove('show');
                setTimeout(() => {
                    backdrop.style.display = 'none';
                    resolve();
                }, 250);
            }

            okBtn.onclick = cleanup;
            backdrop.onclick = (e) => {
                if (e.target === backdrop) cleanup();
            };
        });
    }

    // Global Confirm Dialog (Modal with Cancel / Confirm buttons)
    function nkConfirm(message, title = 'Are you sure?', confirmText = 'Delete', confirmBg = '#dc2626') {
        return new Promise((resolve) => {
            const backdrop = document.getElementById('nk-alert-backdrop');
            const iconWrap = document.getElementById('nk-alert-icon-wrap');
            const icon = document.getElementById('nk-alert-icon');
            const titleEl = document.getElementById('nk-alert-title');
            const msgEl = document.getElementById('nk-alert-message');
            const footer = document.getElementById('nk-alert-footer');

            const cleanMsg = formatFriendlyErrorMessage(message);

            if (!backdrop) {
                const res = window.confirm(cleanMsg);
                resolve(res);
                return;
            }

            iconWrap.className = 'nk-alert-icon-wrap warning';
            icon.className = 'fas fa-question-circle';
            titleEl.textContent = title;
            msgEl.textContent = cleanMsg;

            footer.innerHTML = `
                <button class="nk-alert-btn nk-alert-btn-secondary" id="nk-alert-btn-cancel">Cancel</button>
                <button class="nk-alert-btn nk-alert-btn-primary" id="nk-alert-btn-confirm" style="background: ${confirmBg};">${confirmText}</button>
            `;

            const cancelBtn = document.getElementById('nk-alert-btn-cancel');
            const confirmBtn = document.getElementById('nk-alert-btn-confirm');

            backdrop.style.display = 'flex';
            requestAnimationFrame(() => {
                backdrop.classList.add('show');
                if (confirmBtn) confirmBtn.focus();
            });

            function cleanup(result) {
                backdrop.classList.remove('show');
                setTimeout(() => {
                    backdrop.style.display = 'none';
                    resolve(result);
                }, 250);
            }

            cancelBtn.onclick = () => cleanup(false);
            confirmBtn.onclick = () => cleanup(true);
            backdrop.onclick = (e) => {
                if (e.target === backdrop) cleanup(false);
            };
        });
    }

    // Expose global methods
    window.toggleMobileSidebar = toggleMobileSidebar;
    window.togglePeerSubmenu = togglePeerSubmenu;
    window.formatFriendlyErrorMessage = formatFriendlyErrorMessage;
    window.showToast = showToast;
    window.dismissToast = dismissToast;
    window.showSuccess = (msg, dur) => showToast(msg, 'success', dur || 2200);
    window.showError = (msg, dur) => showToast(msg, 'error', dur || 5000);
    window.showWarning = (msg, dur) => showToast(msg, 'warning', dur || 4500);
    window.showInfo = (msg, dur) => showToast(msg, 'info', dur || 3000);
    window.nkAlert = nkAlert;
    window.nkConfirm = nkConfirm;

    // Global Smart Override for window.alert
    window.alert = function (message) {
        if (!message && message !== 0) return;
        const cleanMsg = formatFriendlyErrorMessage(message);
        const lower = cleanMsg.toLowerCase();

        let type = 'info';
        if (lower.includes('success') || lower.includes('saved') || lower.includes('updated') || lower.includes('applied') || lower.includes('deleted') || lower.includes('synced') || lower.includes('نجاح') || lower.includes('تم')) {
            type = 'success';
        } else if (lower.includes('error') || lower.includes('failed') || lower.includes('fail') || lower.includes('could not') || lower.includes('cannot') || lower.includes('invalid') || lower.includes('فشل') || lower.includes('خطأ')) {
            type = 'error';
        } else if (lower.includes('warning') || lower.includes('please') || lower.includes('required') || lower.includes('يرجى') || lower.includes('تنبيه')) {
            type = 'warning';
        }

        showToast(cleanMsg, type, type === 'error' ? 5500 : 3500);
    };
})();
