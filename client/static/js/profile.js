/**
 * Networkat SD-WAN - Client Profile Controller
 */
(function () {
    'use strict';

    // Copy to clipboard helper
    window.copyGroupId = function (text, btn) {
        if (!text) return;

        navigator.clipboard.writeText(text).then(function () {
            if (typeof Toast !== 'undefined' && Toast.show) {
                Toast.show('NetBird Group ID copied to clipboard!', 'success');
            } else {
                const origHtml = btn.innerHTML;
                btn.innerHTML = '<i class="fas fa-check"></i>';
                setTimeout(() => {
                    btn.innerHTML = origHtml;
                }, 2000);
            }
        }).catch(function (err) {
            console.error('Copy failed:', err);
        });
    };

    document.addEventListener('DOMContentLoaded', function () {
        // Show flash message toasts if present
        const flashItems = document.querySelectorAll('.flash-msg-item');
        flashItems.forEach(function (item) {
            const cat = item.getAttribute('data-category');
            const msg = item.getAttribute('data-message');
            if (msg && typeof Toast !== 'undefined' && Toast.show) {
                Toast.show(msg, cat === 'error' ? 'error' : 'success');
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
