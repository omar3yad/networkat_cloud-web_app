/**
 * Networkat SD-WAN - Client Profile Controller
 */
(function () {
    'use strict';

    function notify(msg, type = 'success') {
        if (typeof showToast === 'function') {
            showToast(msg, type);
        } else if (typeof Toast !== 'undefined' && Toast.show) {
            Toast.show(msg, type);
        }
    }

    // Copy to clipboard helper
    window.copyGroupId = function (text, btn) {
        if (!text) return;

        navigator.clipboard.writeText(text).then(function () {
            notify('NetBird Group ID copied to clipboard!', 'success');
        }).catch(function (err) {
            console.error('Copy failed:', err);
        });
    };

    // ========== 2FA Management ==========
    let currentRecoveryCodes = [];

    window.openSetup2faModal = function () {
        const modal = document.getElementById('modal-setup-2fa');
        if (!modal) return;

        document.getElementById('setup-step-verify').style.display = 'block';
        document.getElementById('setup-step-recovery').style.display = 'none';
        document.getElementById('setup-qr-loading').style.display = 'block';
        document.getElementById('setup-qr-image').style.display = 'none';
        document.getElementById('setup-verify-code').value = '';
        modal.style.display = 'flex';

        fetch('/profile/2fa/setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                document.getElementById('setup-qr-loading').style.display = 'none';
                const img = document.getElementById('setup-qr-image');
                img.src = data.qr_code;
                img.style.display = 'block';
                document.getElementById('setup-secret-key').textContent = data.secret;
                document.getElementById('setup-verify-code').focus();
            } else {
                notify(data.message || 'Failed to start 2FA setup', 'error');
                closeSetup2faModal();
            }
        })
        .catch(err => {
            console.error('2FA setup error:', err);
            notify('Network error', 'error');
            closeSetup2faModal();
        });
    };

    window.closeSetup2faModal = function () {
        const modal = document.getElementById('modal-setup-2fa');
        if (modal) modal.style.display = 'none';
    };

    window.copySetupSecret = function () {
        const secret = document.getElementById('setup-secret-key').textContent;
        if (!secret) return;
        navigator.clipboard.writeText(secret).then(() => {
            notify('Secret key copied', 'success');
        });
    };

    window.confirmSetup2fa = function () {
        const code = document.getElementById('setup-verify-code').value.trim();
        if (!code || code.length !== 6) {
            notify('Please enter a valid 6-digit code', 'error');
            return;
        }

        const btn = document.getElementById('btn-confirm-setup-2fa');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verifying...';

        fetch('/profile/2fa/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: code })
        })
        .then(res => res.json())
        .then(data => {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-check"></i> Confirm and Enable';

            if (data.success) {
                currentRecoveryCodes = data.recovery_codes || [];
                const grid = document.getElementById('recovery-codes-grid');
                grid.innerHTML = '';
                currentRecoveryCodes.forEach(c => {
                    const div = document.createElement('div');
                    div.style.padding = '6px';
                    div.style.background = '#ffffff';
                    div.style.borderRadius = '4px';
                    div.style.border = '1px solid var(--nk-border)';
                    div.textContent = c;
                    grid.appendChild(div);
                });

                document.getElementById('setup-step-verify').style.display = 'none';
                document.getElementById('setup-step-recovery').style.display = 'block';
            } else {
                notify(data.message || 'Invalid verification code', 'error');
            }
        })
        .catch(err => {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-check"></i> Confirm and Enable';
            notify('Network error', 'error');
        });
    };

    window.copyRecoveryCodes = function () {
        if (!currentRecoveryCodes.length) return;
        const text = currentRecoveryCodes.join('\n');
        navigator.clipboard.writeText(text).then(() => {
            notify('Recovery codes copied', 'success');
        });
    };

    window.downloadRecoveryCodes = function () {
        if (!currentRecoveryCodes.length) return;
        const content = "Networkat SD-WAN - Emergency Recovery Codes\n" +
                        "Generated on: " + new Date().toISOString() + "\n\n" +
                        currentRecoveryCodes.join('\n') + "\n\n" +
                        "Each code can be used once if you lose access to your authenticator app.\n";
        const blob = new Blob([content], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'networkat-recovery-codes.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    window.finish2faSetup = function () {
        closeSetup2faModal();
        window.location.reload();
    };

    window.openDisable2faModal = function () {
        const modal = document.getElementById('modal-disable-2fa');
        if (!modal) return;
        document.getElementById('disable-2fa-password').value = '';
        modal.style.display = 'flex';
    };

    window.closeDisable2faModal = function () {
        const modal = document.getElementById('modal-disable-2fa');
        if (modal) modal.style.display = 'none';
    };

    window.confirmDisable2fa = function () {
        const pwd = document.getElementById('disable-2fa-password').value;
        if (!pwd) {
            notify('Password is required', 'error');
            return;
        }

        const btn = document.getElementById('btn-confirm-disable-2fa');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Disabling...';

        fetch('/profile/2fa/disable', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pwd })
        })
        .then(res => res.json())
        .then(data => {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-trash-alt"></i> Disable 2FA';
            if (data.success) {
                closeDisable2faModal();
                window.location.reload();
            } else {
                notify(data.message || 'Incorrect password', 'error');
            }
        })
        .catch(err => {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-trash-alt"></i> Disable 2FA';
            notify('Network error', 'error');
        });
    };

    document.addEventListener('DOMContentLoaded', function () {
        // Show flash message toasts if present
        const flashItems = document.querySelectorAll('.flash-msg-item');
        flashItems.forEach(function (item) {
            const cat = item.getAttribute('data-category');
            const msg = item.getAttribute('data-message');
            if (msg) {
                notify(msg, cat === 'error' ? 'error' : 'success');
            }
        });

        // Initialize quota progress bars
        document.querySelectorAll('.quota-progress-fill[data-width]').forEach(function (el) {
            const w = el.getAttribute('data-width');
            if (w !== null && w !== '') {
                setTimeout(function () {
                    el.style.width = w + '%';
                }, 100);
            }
        });
    });
})();
