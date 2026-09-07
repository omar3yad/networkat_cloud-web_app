/**
 * Networkat SD-WAN Peer Fleet Management Controller
 */
(function () {
    'use strict';

    let peersPollingInterval = null;
    let originalPeerState = {};

    async function fetchAndPopulateRoutes() {
        try {
            const routesRes = await fetch('/api/v2/netbird/routes').catch(() => null);
            const routes = (routesRes && routesRes.ok) ? await routesRes.json() : [];

            const routeInputs = document.querySelectorAll('.inline-route-field');
            for (const input of routeInputs) {
                const peerId = input.getAttribute('data-peer-id');
                const peerRoute = routes.find(r => r.peer === peerId);
                const currentRoute = peerRoute ? peerRoute.network : '';

                if (document.activeElement !== input) {
                    input.value = currentRoute;
                }

                if (peerRoute) {
                    input.setAttribute('data-route-id', peerRoute.id);
                    input.setAttribute('data-route-network-id', peerRoute.network_id);
                } else {
                    input.removeAttribute('data-route-id');
                    input.removeAttribute('data-route-network-id');
                }

                if (originalPeerState[peerId]) {
                    originalPeerState[peerId].route = currentRoute;
                    originalPeerState[peerId].route_id = peerRoute ? peerRoute.id : null;
                    originalPeerState[peerId].route_network_id = peerRoute ? peerRoute.network_id : null;
                }
            }
        } catch (err) {
            console.error('Error fetching routes:', err);
        }
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

    function updatePeerStatuses(data) {
        if (!data || !data.peers) return;

        data.peers.forEach(peer => {
            const statusTitle = getPeerStatusTitle(peer);
            const statusBadge = document.getElementById(`status-badge-${peer.id}`);
            if (statusBadge) {
                statusBadge.className = `peer-status-bulb ${peer.is_online ? 'online' : 'offline'}`;
                statusBadge.title = statusTitle;
            }

            const sidebarDot = document.getElementById(`sidebar-dot-${peer.id}`);
            if (sidebarDot) {
                sidebarDot.className = `peer-status-dot ${peer.is_online ? 'online' : 'offline'}`;
                sidebarDot.title = statusTitle;
            }

            const sidebarItem = document.getElementById(`sidebar-peer-${peer.id}`);
            if (sidebarItem) {
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

            // Update VPN-Only state if not currently modified by user
            const vpnToggle = document.getElementById(`vpn-only-toggle-${peer.id}`);
            const vpnText = document.getElementById(`vpn-only-text-${peer.id}`);
            if (vpnToggle && document.activeElement !== vpnToggle) {
                const isDirty = originalPeerState[peer.id] && vpnToggle.checked !== originalPeerState[peer.id].vpn_only;
                if (!isDirty) {
                    vpnToggle.checked = !!peer.vpn_only;
                    vpnToggle.disabled = !peer.is_online;
                    if (vpnText) {
                        vpnText.innerText = peer.vpn_only ? 'ON' : 'OFF';
                    }
                    if (originalPeerState[peer.id]) {
                        originalPeerState[peer.id].vpn_only = !!peer.vpn_only;
                    }
                }
            }

            // Update Manage button state
            const firewallLink = document.getElementById(`firewall-link-${peer.id}`);
            if (firewallLink) {
                if (peer.is_online) {
                    firewallLink.href = `/peers/${peer.id}`;
                    firewallLink.style.backgroundColor = "var(--nk-blue-primary)";
                    firewallLink.style.borderColor = "var(--nk-blue-primary)";
                    firewallLink.style.color = "white";
                    firewallLink.style.opacity = "1";
                    firewallLink.style.pointerEvents = "auto";
                    firewallLink.style.cursor = "pointer";
                    firewallLink.removeAttribute('onclick');
                } else {
                    firewallLink.href = "javascript:void(0)";
                    firewallLink.style.backgroundColor = "#6c757d";
                    firewallLink.style.borderColor = "#6c757d";
                    firewallLink.style.color = "white";
                    firewallLink.style.opacity = "0.65";
                    firewallLink.style.pointerEvents = "none";
                    firewallLink.style.cursor = "not-allowed";
                    firewallLink.setAttribute('onclick', 'event.preventDefault()');
                }
            }
        });
    }

    function validateIpv4Cidr(cidr) {
        if (!cidr || typeof cidr !== 'string' || !cidr.trim()) {
            return { valid: false, error: 'Subnet required' };
        }
        return window.parseAndValidateIPv4(cidr, { requireMask: true, normalizeSubnet: true });
    }

    function validatePeerDeviceName(name, peerId) {
        if (!name || typeof name !== 'string' || !name.trim()) {
            return { valid: false, error: 'Name required' };
        }
        const trimmed = name.trim();
        
        // Match backend DNS name validation: only letters, numbers, hyphens, max 63 chars
        if (window.validateDNSName) {
            const dnsRes = window.validateDNSName(trimmed, { allowDots: false, maxLength: 63 });
            if (!dnsRes.valid) {
                return dnsRes;
            }
        } else {
            if (trimmed.length > 63) {
                return { valid: false, error: 'Max 63 characters' };
            }
            if (!/^[a-zA-Z0-9-]+$/.test(trimmed)) {
                return { valid: false, error: 'Only letters, numbers, and hyphens (-) allowed' };
            }
            if (trimmed.startsWith('-') || trimmed.endsWith('-')) {
                return { valid: false, error: 'Cannot start or end with hyphen (-)' };
            }
        }

        const rows = document.querySelectorAll('#peers-table-body tr[data-peer-id]');
        for (const r of rows) {
            const otherId = r.getAttribute('data-peer-id');
            if (otherId && otherId !== peerId) {
                const inp = document.getElementById(`inline-name-${otherId}`);
                const otherName = inp ? inp.value.trim() : '';
                if (otherName && otherName.toLowerCase() === trimmed.toLowerCase()) {
                    return { valid: false, error: 'Name already in use' };
                }
            }
        }
        return { valid: true, normalized: trimmed };
    }

    function validatePeerDeviceRoute(route, peerId) {
        if (!route || typeof route !== 'string' || !route.trim()) {
            return { valid: true, normalized: '' };
        }
        const trimmed = route.trim();
        const cidrRes = validateIpv4Cidr(trimmed);
        if (!cidrRes.valid) return cidrRes;

        const targetNet = cidrRes.normalized.toLowerCase();
        const rows = document.querySelectorAll('#peers-table-body tr[data-peer-id]');
        for (const r of rows) {
            const otherId = r.getAttribute('data-peer-id');
            if (otherId && otherId !== peerId) {
                const inp = document.getElementById(`inline-route-${otherId}`);
                const otherRoute = inp ? inp.value.trim() : '';
                if (otherRoute) {
                    const otherRes = validateIpv4Cidr(otherRoute);
                    const otherNet = otherRes.valid ? otherRes.normalized.toLowerCase() : otherRoute.toLowerCase();
                    if (otherNet === targetNet) {
                        return { valid: false, error: 'Subnet already in use' };
                    }
                }
            }
        }
        return cidrRes;
    }

    function setInlineError(inputId, errorMsg) {
        const inp = document.getElementById(inputId);
        const errDiv = document.getElementById(`${inputId}-error`);
        if (inp) {
            inp.classList.add('is-invalid');
            inp.classList.remove('is-modified');
        }
        if (errDiv) {
            errDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${errorMsg}`;
            errDiv.style.display = 'flex';
        }
    }

    function clearInlineError(inputId) {
        const inp = document.getElementById(inputId);
        const errDiv = document.getElementById(`${inputId}-error`);
        if (inp) {
            inp.classList.remove('is-invalid');
        }
        if (errDiv) {
            errDiv.textContent = '';
            errDiv.style.display = 'none';
        }
    }

    function checkDirtyPeerChanges() {
        let hasChanges = false;
        let hasErrors = false;
        const rows = document.querySelectorAll('#peers-table-body tr[data-peer-id]');

        rows.forEach(r => {
            const peerId = r.getAttribute('data-peer-id');
            const orig = originalPeerState[peerId];
            if (!orig) return;

            const nameInp = document.getElementById(`inline-name-${peerId}`);
            const routeInp = document.getElementById(`inline-route-${peerId}`);
            const vpnToggle = document.getElementById(`vpn-only-toggle-${peerId}`);
            const toggleContainer = vpnToggle ? vpnToggle.closest('.toggle-container') : null;

            const currentName = nameInp ? nameInp.value.trim() : '';
            const currentRoute = routeInp ? routeInp.value.trim() : '';
            const currentVpn = vpnToggle ? vpnToggle.checked : false;

            const nameChanged = currentName !== orig.name;
            const routeChanged = currentRoute !== orig.route;
            const vpnChanged = currentVpn !== orig.vpn_only;

            if (nameChanged || routeChanged || vpnChanged) {
                hasChanges = true;
            }

            // Real-time single input validation & golden aura for Name
            if (nameInp) {
                const nameRes = validatePeerDeviceName(nameInp.value, peerId);
                if (!nameRes.valid) {
                    hasErrors = true;
                    setInlineError(`inline-name-${peerId}`, nameRes.error);
                } else {
                    clearInlineError(`inline-name-${peerId}`);
                    if (nameChanged) {
                        nameInp.classList.add('is-modified');
                    } else {
                        nameInp.classList.remove('is-modified');
                    }
                }
            }

            // Real-time single input validation & golden aura for Route
            if (routeInp) {
                const routeRes = validatePeerDeviceRoute(routeInp.value, peerId);
                if (!routeRes.valid) {
                    hasErrors = true;
                    setInlineError(`inline-route-${peerId}`, routeRes.error);
                } else {
                    clearInlineError(`inline-route-${peerId}`);
                    if (routeChanged) {
                        routeInp.classList.add('is-modified');
                    } else {
                        routeInp.classList.remove('is-modified');
                    }
                }
            }

            // Golden aura for VPN toggle
            if (toggleContainer) {
                if (vpnChanged) {
                    toggleContainer.classList.add('is-modified');
                } else {
                    toggleContainer.classList.remove('is-modified');
                }
            }
        });

        const bar = document.getElementById('peers-apply-bar');
        const applyBtn = document.getElementById('btn-apply-peers');
        if (bar) {
            bar.style.display = hasChanges ? 'flex' : 'none';
        }
        if (applyBtn) {
            applyBtn.disabled = hasErrors;
            applyBtn.style.opacity = hasErrors ? '0.5' : '1';
            applyBtn.style.cursor = hasErrors ? 'not-allowed' : 'pointer';
        }
    }

    function discardAllPeerChanges() {
        const rows = document.querySelectorAll('#peers-table-body tr[data-peer-id]');
        rows.forEach(r => {
            const peerId = r.getAttribute('data-peer-id');
            const orig = originalPeerState[peerId];
            if (!orig) return;

            const nameInp = document.getElementById(`inline-name-${peerId}`);
            const routeInp = document.getElementById(`inline-route-${peerId}`);
            const vpnToggle = document.getElementById(`vpn-only-toggle-${peerId}`);
            const vpnText = document.getElementById(`vpn-only-text-${peerId}`);
            const toggleContainer = vpnToggle ? vpnToggle.closest('.toggle-container') : null;

            if (nameInp) {
                nameInp.value = orig.name;
                nameInp.classList.remove('is-modified');
            }
            if (routeInp) {
                routeInp.value = orig.route;
                routeInp.classList.remove('is-modified');
            }
            if (vpnToggle) {
                vpnToggle.checked = orig.vpn_only;
            }
            if (toggleContainer) {
                toggleContainer.classList.remove('is-modified');
            }
            if (vpnText) vpnText.innerText = orig.vpn_only ? 'ON' : 'OFF';

            clearInlineError(`inline-name-${peerId}`);
            clearInlineError(`inline-route-${peerId}`);
        });

        const bar = document.getElementById('peers-apply-bar');
        if (bar) {
            bar.style.display = 'none';
        }
    }

    async function applyAllPeerChanges() {
        const rows = document.querySelectorAll('#peers-table-body tr[data-peer-id]');
        const dirtyPeers = [];

        // 1. Validation check across all modified rows
        for (const r of rows) {
            const peerId = r.getAttribute('data-peer-id');
            const orig = originalPeerState[peerId];
            if (!orig) continue;

            const nameInp = document.getElementById(`inline-name-${peerId}`);
            const routeInp = document.getElementById(`inline-route-${peerId}`);
            const vpnToggle = document.getElementById(`vpn-only-toggle-${peerId}`);

            const currentName = nameInp ? nameInp.value.trim() : '';
            const currentRoute = routeInp ? routeInp.value.trim() : '';
            const currentVpn = vpnToggle ? vpnToggle.checked : false;

            const nameChanged = currentName !== orig.name;
            const routeChanged = currentRoute !== orig.route;
            const vpnChanged = currentVpn !== orig.vpn_only;

            if (nameChanged || routeChanged || vpnChanged) {
                clearInlineError(`inline-name-${peerId}`);
                clearInlineError(`inline-route-${peerId}`);

                // Validate Name
                const nameRes = validatePeerDeviceName(currentName, peerId);
                if (!nameRes.valid) {
                    setInlineError(`inline-name-${peerId}`, nameRes.error);
                    if (nameInp) nameInp.focus();
                    if (window.showError) window.showError(nameRes.error);
                    return;
                }

                // Validate Route
                const routeRes = validatePeerDeviceRoute(currentRoute, peerId);
                if (!routeRes.valid) {
                    setInlineError(`inline-route-${peerId}`, routeRes.error);
                    if (routeInp) routeInp.focus();
                    if (window.showError) window.showError(routeRes.error);
                    return;
                }

                const normalizedRoute = routeRes.normalized || '';
                if (routeInp && normalizedRoute && routeInp.value !== normalizedRoute) {
                    routeInp.value = normalizedRoute;
                }

                dirtyPeers.push({
                    peerId,
                    currentName,
                    currentRoute: normalizedRoute,
                    currentVpn,
                    nameChanged,
                    routeChanged,
                    vpnChanged,
                    existingRouteId: routeInp ? routeInp.getAttribute('data-route-id') : null,
                    existingNetworkId: routeInp ? routeInp.getAttribute('data-route-network-id') : null
                });
            }
        }

        if (dirtyPeers.length === 0) {
            const bar = document.getElementById('peers-apply-bar');
            if (bar) bar.style.display = 'none';
            return;
        }

        const applyBtn = document.getElementById('btn-apply-peers');
        if (applyBtn) {
            applyBtn.disabled = true;
            applyBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Applying...`;
        }

        try {
            for (const item of dirtyPeers) {
                // 1. Save Name
                if (item.nameChanged) {
                    const nameResp = await fetch(`/peers/${item.peerId}/update`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: item.currentName })
                    });
                    const nameData = await nameResp.json();
                    if (!nameResp.ok || nameData.error) {
                        throw new Error(nameData.error || `Failed to update name for ${item.currentName}`);
                    }
                }

                // 2. Save Route
                if (item.routeChanged) {
                    if (item.currentRoute) {
                        const networkId = item.existingNetworkId || `route-${item.peerId.substring(0, 8)}`;
                        const routeBody = {
                            "description": `Route handled via inline dashboard for peer ${item.peerId}`,
                            "network_id": networkId,
                            "enabled": true,
                            "peer": item.peerId,
                            "network": item.currentRoute,
                            "metric": 9999,
                            "masquerade": false,
                            "keep_route": true,
                            "groups": []
                        };

                        if (item.existingRouteId && item.existingRouteId !== 'null' && item.existingRouteId !== 'undefined') {
                            const routeRes = await fetch(`/api/v2/netbird/routes/${item.existingRouteId}`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(routeBody)
                            });
                            if (!routeRes.ok) {
                                const errData = await routeRes.json().catch(() => ({}));
                                throw new Error(errData.detail || errData.message || errData.error || 'Failed to update route');
                            }
                        } else {
                            const createRes = await fetch('/api/v2/netbird/routes', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(routeBody)
                            });
                            if (!createRes.ok) {
                                const errData = await createRes.json().catch(() => ({}));
                                throw new Error(errData.detail || errData.message || errData.error || 'Failed to create route');
                            }
                        }
                    } else if (item.existingRouteId) {
                        await fetch(`/api/v2/netbird/routes/${item.existingRouteId}`, { method: 'DELETE' });
                    }
                }

                // 3. Save VPN-Only mode
                if (item.vpnChanged) {
                    const action = item.currentVpn ? 'on' : 'off';
                    const vpnResp = await fetch(`/api/peers/${item.peerId}/vpn-only`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ operation: action })
                    });
                    const vpnData = await vpnResp.json();
                    if (!vpnResp.ok || (vpnData.ok !== true && vpnData.status !== 'success')) {
                        throw new Error(vpnData.error || vpnData.detail || 'Failed to set VPN mode');
                    }
                }

                // Update original state cache
                if (originalPeerState[item.peerId]) {
                    originalPeerState[item.peerId].name = item.currentName;
                    originalPeerState[item.peerId].route = item.currentRoute;
                    originalPeerState[item.peerId].vpn_only = item.currentVpn;
                }
            }

            await fetchAndPopulateRoutes();

            const tbody = document.getElementById('peers-table-body');
            if (tbody) {
                tbody.removeAttribute('data-loaded');
            }
            await fetchPeersStatus();

            const bar = document.getElementById('peers-apply-bar');
            if (bar) bar.style.display = 'none';

            if (window.showSuccess) {
                window.showSuccess('Changes applied successfully');
            }
        } catch (err) {
            console.error('Apply changes error:', err);
            if (window.showError) {
                window.showError(err.message || 'Failed to apply changes');
            }
        } finally {
            if (applyBtn) {
                applyBtn.disabled = false;
                applyBtn.innerHTML = `Apply changes`;
            }
        }
    }

    function renderPeersTable(peers) {
        const tbody = document.getElementById('peers-table-body');
        if (!tbody) return;

        if (!peers || peers.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="4" style="text-align: center; padding: 4rem; color: var(--nk-text-muted);">
                        No Peer devices found in this customer group.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = '';
        originalPeerState = {};

        peers.forEach(peer => {
            const peerId = peer.id;
            const name = peer.name || '';
            const route = peer.route || '';
            const vpnOnlyChecked = peer.vpn_only ? 'checked' : '';
            const vpnOnlyText = peer.vpn_only ? 'ON' : 'OFF';

            const isDisabled = !peer.is_online ? 'disabled' : '';
            const disabledTitle = !peer.is_online ? 'title="Device is offline"' : '';

            const isOffline = !peer.is_online;
            const firewallUrl = `/peers/${peerId}`;
            const firewallHref = isOffline ? 'javascript:void(0)' : firewallUrl;
            const firewallStyle = isOffline
                ? 'background-color: #6c757d; border-color: #6c757d; color: white; opacity: 0.65; cursor: not-allowed; pointer-events: none;'
                : 'background-color: var(--nk-blue-primary); border-color: var(--nk-blue-primary); color: white;';
            const firewallAttr = isOffline ? 'onclick="event.preventDefault()"' : '';

            // Store initial state
            originalPeerState[peerId] = {
                name: name,
                route: route,
                vpn_only: !!peer.vpn_only,
                route_id: null,
                route_network_id: null
            };

            const tr = document.createElement('tr');
            tr.setAttribute('data-peer-id', peerId);

            tr.innerHTML = `
                <td>
                    <div class="peer-name-cell">
                        <span class="peer-status-bulb ${peer.is_online ? 'online' : 'offline'}"
                            id="status-badge-${peerId}" title="${getPeerStatusTitle(peer)}"></span>
                        <div class="peer-name-input-wrapper">
                            <input style="min-width: 150px;" type="text" class="table-input" id="inline-name-${peerId}"
                                value="${name}" placeholder="Device Name" maxlength="200">
                            <div class="table-error-msg" id="inline-name-${peerId}-error" style="display: none;"></div>
                        </div>
                    </div>
                </td>
                <td>
                    <input style="min-width: 153px;" type="text" class="table-input inline-route-field"
                        id="inline-route-${peerId}" data-peer-id="${peerId}"
                        placeholder="e.g. 192.168.87.0/24" value="${route}">
                    <div class="table-error-msg" id="inline-route-${peerId}-error" style="display: none;"></div>
                </td>
                <td>
                    <div class="toggle-container" ${disabledTitle}>
                        <label class="switch">
                            <input type="checkbox" 
                                   id="vpn-only-toggle-${peerId}" 
                                   onchange="onVpnOnlyToggleChange('${peerId}', this)"
                                   ${vpnOnlyChecked}
                                   ${isDisabled}>
                            <span class="slider"></span>
                        </label>
                        <span class="toggle-status-text" id="vpn-only-text-${peerId}">${vpnOnlyText}</span>
                    </div>
                </td>
                <td>
                    <div class="actions-cell">
                        <a href="${firewallHref}"
                            id="firewall-link-${peerId}" class="action-btn"
                            style="${firewallStyle}" ${firewallAttr}>
                            Manage
                        </a>
                    </div>
                </td>
            `;

            tbody.appendChild(tr);

            // Bind live validation & dirty tracking
            const nameInput = tr.querySelector(`#inline-name-${peerId}`);
            if (nameInput) {
                nameInput.addEventListener('input', () => {
                    checkDirtyPeerChanges();
                });
            }

            const routeInput = tr.querySelector(`#inline-route-${peerId}`);
            if (routeInput) {
                routeInput.addEventListener('input', () => {
                    checkDirtyPeerChanges();
                });
            }
        });

        fetchAndPopulateRoutes();
    }

    function onVpnOnlyToggleChange(peerId, checkbox) {
        const vpnText = document.getElementById(`vpn-only-text-${peerId}`);
        if (vpnText) {
            vpnText.innerText = checkbox.checked ? 'ON' : 'OFF';
        }
        checkDirtyPeerChanges();
    }

    async function fetchPeersStatus() {
        try {
            const response = await fetch(`/api/peers/status?refresh=true&t=${Date.now()}`);
            if (!response.ok) {
                if (response.status === 401) {
                    window.location.href = '/login';
                    return;
                }
                throw new Error('Fetch failed');
            }
            const data = await response.json();
            if (data.error === 'fetch_failed') return;

            const tbody = document.getElementById('peers-table-body');
            const isLoaded = tbody && tbody.getAttribute('data-loaded') === 'true';

            if (tbody && !isLoaded) {
                renderPeersTable(data.peers);
                tbody.setAttribute('data-loaded', 'true');
            } else {
                updatePeerStatuses(data);
            }
        } catch (err) {
            console.error("Error polling peers:", err);
        }
    }

    function initPeersPolling() {
        fetchPeersStatus();
        if (peersPollingInterval) clearInterval(peersPollingInterval);
        peersPollingInterval = setInterval(fetchPeersStatus, 30000);
    }

    // Expose for HTML event listeners
    window.onVpnOnlyToggleChange = onVpnOnlyToggleChange;
    window.discardAllPeerChanges = discardAllPeerChanges;
    window.applyAllPeerChanges = applyAllPeerChanges;

    document.addEventListener("DOMContentLoaded", function () {
        initPeersPolling();
    });
})();
