/**
 * Networkat SD-WAN Dashboard Client Controller
 */
(function () {
    'use strict';

    function fetchSetupKeys() {
        fetch('/api/customer/setup-keys')
            .then(response => response.json())
            .then(data => {
                const tbody = document.getElementById('setup-keys-table-body');
                if (!tbody) return;
                tbody.innerHTML = '';

                if (data.tokens && data.tokens.length > 0) {
                    data.tokens.forEach(tokenObj => {
                        const statusClass = tokenObj.is_active ? 'badge-active' : 'badge-inactive';
                        const statusText = tokenObj.is_active ? 'Active' : 'Inactive';
                        
                        const limitText = tokenObj.usage_limit === 0 ? 'Unlimited' : tokenObj.usage_limit;
                        const remainingText = tokenObj.remaining_uses === null ? 'Unlimited' : tokenObj.remaining_uses;

                        const row = `
                            <tr>
                                <td>
                                    <div class="token-container">
                                        <span class="token-value">${tokenObj.token}</span>
                                        <button class="copy-btn" onclick="copySetupKey('${tokenObj.token}', this)" title="Copy setup key">
                                            <i class="far fa-copy"></i>
                                        </button>
                                    </div>
                                </td>
                                <td><span class="badge ${statusClass}">${statusText}</span></td>
                                <td>${tokenObj.used_times}</td>
                                <td>${limitText}</td>
                                <td>${remainingText}</td>
                                <td>${tokenObj.created_at}</td>
                            </tr>
                        `;
                        tbody.innerHTML += row;
                    });
                } else {
                    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 3rem; color: var(--nk-text-muted);">No setup keys found.</td></tr>`;
                }
            }).catch(err => console.error('Error fetching setup keys:', err));
    }

    function copySetupKey(token, buttonElement) {
        navigator.clipboard.writeText(token).then(() => {
            const icon = buttonElement.querySelector('i');
            if (icon) icon.className = 'fas fa-check';
            buttonElement.classList.add('copied');
            setTimeout(() => {
                if (icon) icon.className = 'far fa-copy';
                buttonElement.classList.remove('copied');
            }, 2000);
        });
    }

    function copyInstallCommand(buttonElement) {
        const cmd = "curl -fsSL https://pkgs.networkat.cloud/install.sh | sudo bash";
        navigator.clipboard.writeText(cmd).then(() => {
            const icon = buttonElement.querySelector('i');
            const span = buttonElement.querySelector('span');
            if (icon) icon.className = 'fas fa-check';
            if (span) span.textContent = '';
            buttonElement.classList.add('copied');
            setTimeout(() => {
                if (icon) icon.className = 'far fa-copy';
                if (span) span.textContent = 'Copy';
                buttonElement.classList.remove('copied');
            }, 2000);
        });
    }

    function formatOfflineDuration(lastSeenVal) {
        if (!lastSeenVal) return "";
        try {
            const dt = new Date(lastSeenVal);
            if (isNaN(dt.getTime())) return "";
            const now = new Date();
            const diffMs = now - dt;
            const secs = Math.max(0, Math.floor(diffMs / 1000));
            if (secs < 60) return "1m";
            if (secs < 3600) return `${Math.floor(secs / 60)}m`;
            if (secs < 86400) return `${Math.floor(secs / 3600)}h`;
            return `${Math.floor(secs / 86400)}d`;
        } catch (e) {
            return "";
        }
    }

    function getPeerStatusTitle(peer) {
        if (peer.is_online) return 'Connected';
        const dur = formatOfflineDuration(peer.last_seen);
        return dur ? `Offline for ${dur}` : 'Offline';
    }

    async function fetchDashboardStats() {
        try {
            const response = await fetch('/api/peers/status');
            if (response.ok) {
                const data = await response.json();
                if (window.SUBSCRIPTION_STATUS === 'inactive') {
                    if (data.peers) {
                        data.peers.forEach(p => {
                            p.is_online = false;
                            p.connected = false;
                        });
                    }
                    if (data.summary) {
                        data.summary.online = 0;
                        data.summary.offline = data.summary.total;
                    }
                }

                if (data.summary) {
                    const totalEl = document.getElementById('total-edges-val');
                    const onlineEl = document.getElementById('online-edges-val');
                    const offlineEl = document.getElementById('offline-edges-val');

                    if (totalEl) totalEl.innerText = data.summary.total;
                    if (onlineEl) onlineEl.innerText = data.summary.online;
                    if (offlineEl) offlineEl.innerText = data.summary.offline;
                }

                if (data.peers) {
                    data.peers.forEach(peer => {
                        const statusTitle = getPeerStatusTitle(peer);
                        const sidebarDot = document.getElementById(`sidebar-dot-${peer.id}`);
                        if (sidebarDot) {
                            sidebarDot.className = `peer-status-dot ${peer.is_online ? 'online' : 'offline'}`;
                            sidebarDot.title = statusTitle;
                        }

                        const sidebarItem = document.getElementById(`sidebar-peer-${peer.id}`);
                        if (sidebarItem) {
                            sidebarItem.setAttribute('data-sidebar-online', peer.is_online ? 'true' : 'false');
                            sidebarItem.title = `${peer.name || 'Edge Device'} (${statusTitle})`;
                        }

                        const sidebarSeen = document.getElementById(`sidebar-seen-${peer.id}`);
                        if (sidebarSeen) {
                            if (peer.is_online) {
                                sidebarSeen.textContent = '';
                                sidebarSeen.style.display = 'none';
                            } else {
                                const dur = formatOfflineDuration(peer.last_seen);
                                sidebarSeen.textContent = dur ? `${dur} ago` : '';
                                sidebarSeen.style.display = dur ? '' : 'none';
                            }
                        }
                    });

                    if (window.applySidebarSubmenuFilter) {
                        window.applySidebarSubmenuFilter();
                    }
                }
            }
        } catch (err) {
            console.error("Error polling dashboard stats:", err);
        }
    }

    // Expose for HTML onclick handlers
    window.copySetupKey = copySetupKey;
    window.copyInstallCommand = copyInstallCommand;

    document.addEventListener("DOMContentLoaded", function () {
        // Initialize quota progress bars
        document.querySelectorAll('.quota-progress-fill[data-width]').forEach(function (el) {
            const w = el.getAttribute('data-width');
            if (w !== null && w !== '') {
                setTimeout(function () {
                    el.style.width = w + '%';
                }, 100);
            }
        });

        fetchSetupKeys();
        fetchDashboardStats();
        setInterval(fetchDashboardStats, 30000);
    });
})();
