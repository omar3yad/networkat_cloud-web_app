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

    function showToast(message, type = 'info', duration = 4000) {
        let container = document.getElementById('nk-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'nk-toast-container';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = `nk-toast toast-${type}`;

        let iconClass = 'fa-info-circle';
        let defaultTitle = 'Information';
        if (type === 'success') {
            iconClass = 'fa-check-circle';
            defaultTitle = 'Success';
        } else if (type === 'error') {
            iconClass = 'fa-exclamation-circle';
            defaultTitle = 'Error';
        } else if (type === 'warning') {
            iconClass = 'fa-exclamation-triangle';
            defaultTitle = 'Warning';
        }

        toast.innerHTML = `
            <div class="nk-toast-icon">
                <i class="fas ${iconClass}"></i>
            </div>
            <div class="nk-toast-content">
                <span class="nk-toast-title">${defaultTitle}</span>
                <span class="nk-toast-msg">${message}</span>
            </div>
            <button type="button" class="nk-toast-close" title="Close">
                <i class="fas fa-times"></i>
            </button>
            <div class="nk-toast-progress" style="animation-duration: ${duration}ms;"></div>
        `;

        const closeBtn = toast.querySelector('.nk-toast-close');
        if (closeBtn) {
            closeBtn.onclick = () => dismissToast(toast);
        }

        container.appendChild(toast);

        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        let autoDismissTimer = setTimeout(() => {
            dismissToast(toast);
        }, duration);

        toast.addEventListener('mouseenter', () => {
            const prog = toast.querySelector('.nk-toast-progress');
            if (prog) prog.style.animationPlayState = 'paused';
            clearTimeout(autoDismissTimer);
        });

        toast.addEventListener('mouseleave', () => {
            const prog = toast.querySelector('.nk-toast-progress');
            if (prog) prog.style.animationPlayState = 'running';
            autoDismissTimer = setTimeout(() => {
                dismissToast(toast);
            }, 1500);
        });
    }

    function dismissToast(toast) {
        if (!toast || toast.classList.contains('hide')) return;
        toast.classList.remove('show');
        toast.classList.add('hide');
        setTimeout(() => {
            if (toast.parentElement) toast.remove();
        }, 350);
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

            if (!backdrop) {
                alert(message);
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
            msgEl.textContent = message;

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
    function nkConfirm(message, title = 'Are you sure?') {
        return new Promise((resolve) => {
            const backdrop = document.getElementById('nk-alert-backdrop');
            const iconWrap = document.getElementById('nk-alert-icon-wrap');
            const icon = document.getElementById('nk-alert-icon');
            const titleEl = document.getElementById('nk-alert-title');
            const msgEl = document.getElementById('nk-alert-message');
            const footer = document.getElementById('nk-alert-footer');

            if (!backdrop) {
                const res = window.confirm(message);
                resolve(res);
                return;
            }

            iconWrap.className = 'nk-alert-icon-wrap warning';
            icon.className = 'fas fa-question-circle';
            titleEl.textContent = title;
            msgEl.textContent = message;

            footer.innerHTML = `
                <button class="nk-alert-btn nk-alert-btn-secondary" id="nk-alert-btn-cancel">Cancel</button>
                <button class="nk-alert-btn nk-alert-btn-primary" id="nk-alert-btn-confirm" style="background: #dc2626;">Confirm</button>
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
    window.showToast = showToast;
    window.dismissToast = dismissToast;
    window.showSuccess = (msg, dur) => showToast(msg, 'success', dur);
    window.showError = (msg, dur) => showToast(msg, 'error', dur || 5000);
    window.showWarning = (msg, dur) => showToast(msg, 'warning', dur || 4500);
    window.showInfo = (msg, dur) => showToast(msg, 'info', dur);
    window.nkAlert = nkAlert;
    window.nkConfirm = nkConfirm;

    // Global Smart Override for window.alert
    window.alert = function (message) {
        if (!message && message !== 0) return;
        const msgStr = String(message);
        const lower = msgStr.toLowerCase();

        let type = 'info';
        if (lower.includes('success') || lower.includes('saved') || lower.includes('updated') || lower.includes('applied') || lower.includes('نجاح') || lower.includes('تم')) {
            type = 'success';
        } else if (lower.includes('error') || lower.includes('failed') || lower.includes('fail') || lower.includes('could not') || lower.includes('cannot') || lower.includes('invalid') || lower.includes('فشل') || lower.includes('خطأ')) {
            type = 'error';
        } else if (lower.includes('warning') || lower.includes('please') || lower.includes('required') || lower.includes('يرجى') || lower.includes('تنبيه')) {
            type = 'warning';
        }

        showToast(msgStr, type, type === 'error' ? 5500 : 4000);
    };
})();
