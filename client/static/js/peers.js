/**
 * Networkat SD-WAN Peer Fleet Management Controller
 */
(function () {
    'use strict';

    let peersPollingInterval = null;
    let originalPeerState = {};
    let filterOnline = false;
    let filterOffline = false;

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

                // Update read-only route label
                const routeLabel = document.getElementById(`peer-route-text-${peerId}`);
                if (routeLabel) {
                    routeLabel.textContent = currentRoute || '—';
                    if (!currentRoute) {
                        routeLabel.classList.add('is-empty');
                    } else {
                        routeLabel.classList.remove('is-empty');
                    }
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

    function isOfflineOver7Days(lastSeenVal, isOnline) {
        if (isOnline) return false;
        if (!lastSeenVal) return true;
        try {
            const dt = new Date(lastSeenVal);
            if (isNaN(dt.getTime())) return true;
            const now = new Date();
            const diffMs = now - dt;
            return diffMs >= (7 * 86400 * 1000);
        } catch (e) {
            return false;
        }
    }

    function updatePeerCountDisplay(peersOrCount) {
        let total = 0;
        let online = 0;
        let offline = 0;

        if (Array.isArray(peersOrCount)) {
            const isInactive = (window.SUBSCRIPTION_STATUS === 'inactive');
            total = peersOrCount.length;
            online = isInactive ? 0 : peersOrCount.filter(p => !!p.is_online).length;
            offline = total - online;
        } else if (typeof peersOrCount === 'number') {
            total = peersOrCount;
        } else {
            return;
        }

        // Update page header elements
        const pageEl = document.getElementById('peers-page-count');
        if (pageEl) pageEl.textContent = total;
        const pageOnlineEl = document.getElementById('peers-online-count');
        if (pageOnlineEl && Array.isArray(peersOrCount)) pageOnlineEl.textContent = online;
        const pageOfflineEl = document.getElementById('peers-offline-count');
        if (pageOfflineEl && Array.isArray(peersOrCount)) pageOfflineEl.textContent = offline;

        // Update sidebar badges
        const sideEl = document.getElementById('sidebar-peers-count');
        if (sideEl) sideEl.textContent = total;
        const sideOnlineEl = document.getElementById('sidebar-online-count');
        if (sideOnlineEl && Array.isArray(peersOrCount)) {
            sideOnlineEl.textContent = online;
            sideOnlineEl.title = `Online Peers (${online})`;
        }
        const sideOfflineEl = document.getElementById('sidebar-offline-count');
        if (sideOfflineEl && Array.isArray(peersOrCount)) {
            sideOfflineEl.textContent = offline;
            sideOfflineEl.title = `Offline Peers (${offline})`;
        }
    }

    function updatePeerStatuses(data) {
        if (!data || !data.peers) return;

        const isInactive = (window.SUBSCRIPTION_STATUS === 'inactive');
        if (isInactive) {
            data.peers.forEach(p => {
                p.is_online = false;
                p.connected = false;
            });
        }

        updatePeerCountDisplay(data.peers);

        const isLocked = !!(window.IS_READONLY_SUBSCRIPTION || window.SUBSCRIPTION_STATUS === 'limit_control' || window.SUBSCRIPTION_STATUS === 'inactive');

        data.peers.forEach(peer => {
            const fwLink = document.getElementById(`firewall-link-${peer.id}`);
            if (fwLink && isLocked) {
                fwLink.className = 'action-btn btn-locked';
                fwLink.removeAttribute('style');
                fwLink.title = 'Account is locked (Read-Only)';
                fwLink.innerHTML = '<i class="fas fa-lock"></i> Lock';
            }

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
                sidebarItem.setAttribute('data-sidebar-online', peer.is_online ? 'true' : 'false');
                const isOver7d = isOfflineOver7Days(peer.last_seen, peer.is_online);
                sidebarItem.setAttribute('data-over-7d', isOver7d ? 'true' : 'false');
                if (isOver7d) {
                    sidebarItem.style.display = 'none';
                } else {
                    sidebarItem.style.display = '';
                    sidebarItem.title = `${peer.name || 'Edge Device'} (${statusTitle})`;
                }
            }

            // Update read-only name label if not currently in edit mode
            const nameLabel = document.getElementById(`peer-name-text-${peer.id}`);
            const nameWrapper = document.getElementById(`name-input-wrapper-${peer.id}`);
            const isEditing = nameWrapper && nameWrapper.style.display !== 'none';
            if (nameLabel && !isEditing && peer.name) {
                nameLabel.textContent = peer.name;
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

            // VPN-Only applies immediately on click, so always mirror server state
            // (unless a toggle request is in flight). When the peer is offline the real
            // value is unknowable, so hide the switch and show "—" instead of ON/OFF.
            const vpnToggle = document.getElementById(`vpn-only-toggle-${peer.id}`);
            const vpnText = document.getElementById(`vpn-only-text-${peer.id}`);
            const vpnContainer = document.getElementById(`vpn-only-container-${peer.id}`);
            if (vpnToggle && document.activeElement !== vpnToggle && vpnToggle.dataset.pending !== 'true') {
                vpnToggle.checked = !!peer.vpn_only;
                vpnToggle.disabled = !peer.is_online;
                if (vpnContainer) {
                    vpnContainer.classList.toggle('vpn-only-unknown', !peer.is_online);
                }
                if (vpnText) {
                    vpnText.innerText = peer.is_online ? (peer.vpn_only ? 'ON' : 'OFF') : '—';
                }
                if (originalPeerState[peer.id]) {
                    originalPeerState[peer.id].vpn_only = !!peer.vpn_only;
                }
            }

            // Manage is always available, regardless of peer online state

            const tr = document.querySelector(`#peers-table-body tr[data-peer-id="${peer.id}"]`);
            if (tr) {
                tr.setAttribute('data-peer-online', peer.is_online ? 'true' : 'false');
            }
        });

        applyPeerStatusFilter();
        if (window.applySidebarSubmenuFilter) {
            window.applySidebarSubmenuFilter();
        }
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

            const currentName = nameInp ? nameInp.value.trim() : '';
            const currentRoute = routeInp ? routeInp.value.trim() : '';

            const nameChanged = currentName !== orig.name;
            const routeChanged = currentRoute !== orig.route;

            if (nameChanged || routeChanged) {
                hasChanges = true;
            }

            // Real-time single input validation & golden aura for Name (only if modified)
            if (nameInp) {
                if (nameChanged) {
                    const nameRes = validatePeerDeviceName(nameInp.value, peerId);
                    if (!nameRes.valid) {
                        hasErrors = true;
                        setInlineError(`inline-name-${peerId}`, nameRes.error);
                    } else {
                        clearInlineError(`inline-name-${peerId}`);
                        nameInp.classList.add('is-modified');
                    }
                } else {
                    clearInlineError(`inline-name-${peerId}`);
                    nameInp.classList.remove('is-modified');
                }
            }

            // Real-time single input validation & golden aura for Route (only if modified)
            if (routeInp) {
                if (routeChanged) {
                    const routeRes = validatePeerDeviceRoute(routeInp.value, peerId);
                    if (!routeRes.valid) {
                        hasErrors = true;
                        setInlineError(`inline-route-${peerId}`, routeRes.error);
                    } else {
                        clearInlineError(`inline-route-${peerId}`);
                        routeInp.classList.add('is-modified');
                    }
                } else {
                    clearInlineError(`inline-route-${peerId}`);
                    routeInp.classList.remove('is-modified');
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

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function setRowEditMode(peerId, isEditing) {
        const tr = document.querySelector(`#peers-table-body tr[data-peer-id="${peerId}"]`);
        const nameView = document.getElementById(`peer-name-view-${peerId}`);
        const nameWrapper = document.getElementById(`name-input-wrapper-${peerId}`);
        const routeView = document.getElementById(`peer-route-view-${peerId}`);
        const routeWrapper = document.getElementById(`route-input-wrapper-${peerId}`);

        if (tr) {
            tr.classList.toggle('row-editing', isEditing);
        }
        if (nameView) {
            nameView.style.display = isEditing ? 'none' : 'flex';
        }
        if (nameWrapper) {
            nameWrapper.style.display = isEditing ? 'flex' : 'none';
        }
        if (routeView) {
            routeView.style.display = isEditing ? 'none' : 'flex';
        }
        if (routeWrapper) {
            routeWrapper.style.display = isEditing ? 'block' : 'none';
        }
    }

    function enablePeerNameEditMode(peerId) {
        const tr = document.querySelector(`#peers-table-body tr[data-peer-id="${peerId}"]`);
        const nameView = document.getElementById(`peer-name-view-${peerId}`);
        const nameWrapper = document.getElementById(`name-input-wrapper-${peerId}`);
        if (tr) tr.classList.add('row-editing');
        if (nameView) nameView.style.display = 'none';
        if (nameWrapper) nameWrapper.style.display = 'flex';

        const nameInp = document.getElementById(`inline-name-${peerId}`);
        if (nameInp) {
            nameInp.focus();
            nameInp.select();
        }
    }

    function cancelPeerNameEditMode(peerId) {
        const orig = originalPeerState[peerId];
        const nameInp = document.getElementById(`inline-name-${peerId}`);
        if (orig && nameInp) {
            nameInp.value = orig.name;
            nameInp.classList.remove('is-modified', 'is-invalid');
        }
        clearInlineError(`inline-name-${peerId}`);

        const nameView = document.getElementById(`peer-name-view-${peerId}`);
        const nameWrapper = document.getElementById(`name-input-wrapper-${peerId}`);
        if (nameView) nameView.style.display = 'flex';
        if (nameWrapper) nameWrapper.style.display = 'none';

        const routeWrapper = document.getElementById(`route-input-wrapper-${peerId}`);
        const isRouteEditing = routeWrapper && routeWrapper.style.display !== 'none';
        const tr = document.querySelector(`#peers-table-body tr[data-peer-id="${peerId}"]`);
        if (tr && !isRouteEditing) {
            tr.classList.remove('row-editing');
        }
        checkDirtyPeerChanges();
    }

    function enablePeerRouteEditMode(peerId) {
        const tr = document.querySelector(`#peers-table-body tr[data-peer-id="${peerId}"]`);
        const routeView = document.getElementById(`peer-route-view-${peerId}`);
        const routeWrapper = document.getElementById(`route-input-wrapper-${peerId}`);
        if (tr) tr.classList.add('row-editing');
        if (routeView) routeView.style.display = 'none';
        if (routeWrapper) routeWrapper.style.display = 'block';

        const routeInp = document.getElementById(`inline-route-${peerId}`);
        if (routeInp) {
            routeInp.focus();
            routeInp.select();
        }
    }

    function cancelPeerRouteEditMode(peerId) {
        const orig = originalPeerState[peerId];
        const routeInp = document.getElementById(`inline-route-${peerId}`);
        if (orig && routeInp) {
            routeInp.value = orig.route;
            routeInp.classList.remove('is-modified', 'is-invalid');
        }
        clearInlineError(`inline-route-${peerId}`);

        const routeView = document.getElementById(`peer-route-view-${peerId}`);
        const routeWrapper = document.getElementById(`route-input-wrapper-${peerId}`);
        if (routeView) routeView.style.display = 'flex';
        if (routeWrapper) routeWrapper.style.display = 'none';

        const nameWrapper = document.getElementById(`name-input-wrapper-${peerId}`);
        const isNameEditing = nameWrapper && nameWrapper.style.display !== 'none';
        const tr = document.querySelector(`#peers-table-body tr[data-peer-id="${peerId}"]`);
        if (tr && !isNameEditing) {
            tr.classList.remove('row-editing');
        }
        checkDirtyPeerChanges();
    }

    function enablePeerEditMode(peerId) {
        enablePeerNameEditMode(peerId);
        enablePeerRouteEditMode(peerId);
    }

    function cancelPeerEditMode(peerId) {
        cancelPeerNameEditMode(peerId);
        cancelPeerRouteEditMode(peerId);
    }

    function discardAllPeerChanges() {
        const rows = document.querySelectorAll('#peers-table-body tr[data-peer-id]');
        rows.forEach(r => {
            const peerId = r.getAttribute('data-peer-id');
            setRowEditMode(peerId, false);
            const orig = originalPeerState[peerId];
            if (!orig) return;

            const nameInp = document.getElementById(`inline-name-${peerId}`);
            const routeInp = document.getElementById(`inline-route-${peerId}`);

            if (nameInp) {
                nameInp.value = orig.name;
                nameInp.classList.remove('is-modified');
            }
            if (routeInp) {
                routeInp.value = orig.route;
                routeInp.classList.remove('is-modified');
            }

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

            const currentName = nameInp ? nameInp.value.trim() : '';
            const currentRoute = routeInp ? routeInp.value.trim() : '';

            const nameChanged = currentName !== orig.name;
            const routeChanged = currentRoute !== orig.route;

            if (nameChanged || routeChanged) {
                clearInlineError(`inline-name-${peerId}`);
                clearInlineError(`inline-route-${peerId}`);

                // Validate Name only if changed
                if (nameChanged) {
                    const nameRes = validatePeerDeviceName(currentName, peerId);
                    if (!nameRes.valid) {
                        setInlineError(`inline-name-${peerId}`, nameRes.error);
                        enablePeerNameEditMode(peerId);
                        if (nameInp) nameInp.focus();
                        if (window.showError) window.showError(nameRes.error);
                        return;
                    }
                }

                // Validate Route only if changed
                let normalizedRoute = currentRoute;
                if (routeChanged) {
                    const routeRes = validatePeerDeviceRoute(currentRoute, peerId);
                    if (!routeRes.valid) {
                        setInlineError(`inline-route-${peerId}`, routeRes.error);
                        enablePeerRouteEditMode(peerId);
                        if (routeInp) routeInp.focus();
                        if (window.showError) window.showError(routeRes.error);
                        return;
                    }
                    normalizedRoute = routeRes.normalized || '';
                    if (routeInp && normalizedRoute && routeInp.value !== normalizedRoute) {
                        routeInp.value = normalizedRoute;
                    }
                }

                dirtyPeers.push({
                    peerId,
                    currentName,
                    currentRoute: normalizedRoute,
                    nameChanged,
                    routeChanged,
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

                // Update original state cache
                if (originalPeerState[item.peerId]) {
                    originalPeerState[item.peerId].name = item.currentName;
                    originalPeerState[item.peerId].route = item.currentRoute;
                }

                // Reset edit modes and clean up modified styling
                setRowEditMode(item.peerId, false);
                const nameLabel = document.getElementById(`peer-name-text-${item.peerId}`);
                if (nameLabel) nameLabel.textContent = item.currentName;
                const routeLabel = document.getElementById(`peer-route-text-${item.peerId}`);
                if (routeLabel) {
                    routeLabel.textContent = item.currentRoute || '—';
                    if (!item.currentRoute) routeLabel.classList.add('is-empty');
                    else routeLabel.classList.remove('is-empty');
                }
                const nameInp = document.getElementById(`inline-name-${item.peerId}`);
                if (nameInp) nameInp.classList.remove('is-modified');
                const routeInp = document.getElementById(`inline-route-${item.peerId}`);
                if (routeInp) routeInp.classList.remove('is-modified');
            }

            await fetchAndPopulateRoutes();
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

        if (window.SUBSCRIPTION_STATUS === 'inactive' && peers) {
            peers.forEach(p => {
                p.is_online = false;
                p.connected = false;
            });
        }

        updatePeerCountDisplay(peers || []);

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
            const vpnOnlyText = peer.is_online ? (peer.vpn_only ? 'ON' : 'OFF') : '—';

            const isDisabled = !peer.is_online ? 'disabled' : '';
            const disabledTitle = !peer.is_online ? 'title="Device is offline"' : '';
            const vpnUnknownCls = !peer.is_online ? ' vpn-only-unknown' : '';

            // Manage is always available, regardless of peer online state
            const firewallHref = `/peers/${peerId}`;

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
            tr.setAttribute('data-peer-online', peer.is_online ? 'true' : 'false');

            const isLocked = !!(window.IS_READONLY_SUBSCRIPTION || window.SUBSCRIPTION_STATUS === 'limit_control' || window.SUBSCRIPTION_STATUS === 'inactive');
            const actionBtnHtml = isLocked ? `
                <a href="${firewallHref}"
                    id="firewall-link-${peerId}" class="action-btn btn-locked"
                    title="Account is locked (Read-Only)">
                    <i class="fas fa-lock"></i> Lock
                </a>
            ` : `
                <a href="${firewallHref}"
                    id="firewall-link-${peerId}" class="action-btn"
                    style="background-color: var(--nk-blue-primary); border-color: var(--nk-blue-primary); color: white;">
                    Open
                </a>
            `;

            tr.innerHTML = `
                <td>
                    <div class="peer-name-cell">
                        <span class="peer-status-bulb ${peer.is_online ? 'online' : 'offline'}"
                            id="status-badge-${peerId}" title="${getPeerStatusTitle(peer)}"></span>

                        <!-- Read-only Name View -->
                        <div class="peer-name-view" id="peer-name-view-${peerId}">
                            <span class="peer-name-text" id="peer-name-text-${peerId}">${escapeHtml(name)}</span>
                            <button type="button" class="btn-edit-peer" id="btn-edit-name-${peerId}"
                                title="Edit device name" onclick="enablePeerNameEditMode('${peerId}')">
                                <i class="bi bi-pencil-square"></i>
                            </button>
                        </div>

                        <!-- Edit Mode Wrapper -->
                        <div class="peer-name-input-wrapper" id="name-input-wrapper-${peerId}" style="display: none;">
                            <div class="peer-input-row">
                                <input style="min-width: 140px;" type="text" class="table-input" id="inline-name-${peerId}"
                                    value="${escapeHtml(name)}" placeholder="Device Name" maxlength="200">
                                <button type="button" class="btn-cancel-edit" title="Cancel edit"
                                    onclick="cancelPeerNameEditMode('${peerId}')">
                                    <i class="fas fa-times"></i>
                                </button>
                            </div>
                            <div class="table-error-msg" id="inline-name-${peerId}-error" style="display: none;"></div>
                        </div>
                    </div>
                </td>
                <td>
                    <!-- Read-only Route View -->
                    <div class="peer-route-view" id="peer-route-view-${peerId}">
                        <span class="peer-route-text ${route ? '' : 'is-empty'}" id="peer-route-text-${peerId}">
                            ${escapeHtml(route) || '—'}
                        </span>
                        <button type="button" class="btn-edit-peer" id="btn-edit-route-${peerId}"
                            title="Edit network route" onclick="enablePeerRouteEditMode('${peerId}')">
                            <i class="bi bi-pencil-square"></i>
                        </button>
                    </div>

                    <!-- Edit Mode Wrapper -->
                    <div class="peer-route-input-wrapper" id="route-input-wrapper-${peerId}" style="display: none;">
                        <div class="peer-input-row">
                            <input style="min-width: 140px;" type="text" class="table-input inline-route-field"
                                id="inline-route-${peerId}" data-peer-id="${peerId}"
                                placeholder="e.g. 192.168.87.0/24" value="${escapeHtml(route)}">
                            <button type="button" class="btn-cancel-edit" title="Cancel edit"
                                onclick="cancelPeerRouteEditMode('${peerId}')">
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                        <div class="table-error-msg" id="inline-route-${peerId}-error" style="display: none;"></div>
                    </div>
                </td>
                <td>
                    <div class="toggle-container${vpnUnknownCls}" id="vpn-only-container-${peerId}" ${disabledTitle}>
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
                        ${actionBtnHtml}
                    </div>
                </td>
            `;

            tbody.appendChild(tr);

            // Bind live validation & dirty tracking + keyboard shortcuts
            const nameInput = tr.querySelector(`#inline-name-${peerId}`);
            if (nameInput) {
                nameInput.addEventListener('input', () => {
                    checkDirtyPeerChanges();
                });
                nameInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Escape') {
                        cancelPeerNameEditMode(peerId);
                    } else if (e.key === 'Enter') {
                        e.preventDefault();
                        enablePeerRouteEditMode(peerId);
                    }
                });
            }

            const routeInput = tr.querySelector(`#inline-route-${peerId}`);
            if (routeInput) {
                routeInput.addEventListener('input', () => {
                    checkDirtyPeerChanges();
                });
                routeInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Escape') {
                        cancelPeerRouteEditMode(peerId);
                    } else if (e.key === 'Enter') {
                        e.preventDefault();
                        applyAllPeerChanges();
                    }
                });
            }
        });

        fetchAndPopulateRoutes();
        applyPeerStatusFilter();
    }

    async function onVpnOnlyToggleChange(peerId, checkbox) {
        const vpnText = document.getElementById(`vpn-only-text-${peerId}`);
        const desired = checkbox.checked;
        const orig = originalPeerState[peerId];

        if (vpnText) vpnText.innerText = desired ? 'ON' : 'OFF';
        checkbox.disabled = true;
        checkbox.dataset.pending = 'true';

        try {
            const resp = await fetch(`/api/peers/${peerId}/vpn-only`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ operation: desired ? 'on' : 'off' })
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || (data.ok !== true && data.status !== 'success')) {
                throw new Error(data.error || data.detail || 'Failed to set VPN mode');
            }
            if (orig) orig.vpn_only = desired;
            if (window.showSuccess) window.showSuccess(desired ? 'VPN-Only on' : 'VPN-Only off');
        } catch (err) {
            console.error('VPN-Only toggle error:', err);
            const revert = orig ? orig.vpn_only : !desired;
            checkbox.checked = revert;
            if (vpnText) vpnText.innerText = revert ? 'ON' : 'OFF';
            if (window.showError) window.showError(err.message || 'Failed to set VPN mode');
        } finally {
            delete checkbox.dataset.pending;
            const row = document.querySelector(`#peers-table-body tr[data-peer-id="${peerId}"]`);
            const isOnline = !row || row.getAttribute('data-peer-online') === 'true';
            checkbox.disabled = !isOnline;
        }
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

    function togglePeerStatusFilter(status) {
        if (status === 'online') {
            if (filterOnline) {
                filterOnline = false;
            } else {
                filterOnline = true;
                filterOffline = false;
            }
        } else if (status === 'offline') {
            if (filterOffline) {
                filterOffline = false;
            } else {
                filterOffline = true;
                filterOnline = false;
            }
        }
        applyPeerStatusFilter();
    }

    function applyPeerStatusFilter() {
        const btnOnline = document.getElementById('filter-btn-online');
        const btnOffline = document.getElementById('filter-btn-offline');

        if (btnOnline) btnOnline.classList.toggle('active', filterOnline);
        if (btnOffline) btnOffline.classList.toggle('active', filterOffline);

        const rows = document.querySelectorAll('#peers-table-body tr[data-peer-id]');
        let visibleCount = 0;

        rows.forEach(tr => {
            const isOnline = tr.getAttribute('data-peer-online') === 'true';
            let show = true;

            if (filterOnline) {
                show = isOnline;
            } else if (filterOffline) {
                show = !isOnline;
            } else {
                show = true;
            }

            tr.style.display = show ? '' : 'none';
            if (show) visibleCount++;
        });

        // Dynamic empty state row for filter results
        let emptyRow = document.getElementById('peers-filter-empty-row');
        if (visibleCount === 0 && rows.length > 0) {
            if (!emptyRow) {
                const tbody = document.getElementById('peers-table-body');
                emptyRow = document.createElement('tr');
                emptyRow.id = 'peers-filter-empty-row';
                tbody.appendChild(emptyRow);
            }
            const label = filterOnline ? 'online' : 'offline';
            emptyRow.innerHTML = `
                <td colspan="4" style="text-align: center; padding: 3.5rem; color: var(--nk-text-muted);">
                    <i class="fas fa-filter" style="font-size: 1.5rem; margin-bottom: 0.5rem; display: block; opacity: 0.4;"></i>
                    No ${label} peers found matching filter.
                </td>
            `;
            emptyRow.style.display = '';
        } else if (emptyRow) {
            emptyRow.style.display = 'none';
        }
    }

    function initPeersPolling() {
        // Read URL query parameter if available
        const urlParams = new URLSearchParams(window.location.search);
        const filterParam = urlParams.get('filter');
        if (filterParam === 'online') {
            filterOnline = true;
            filterOffline = false;
        } else if (filterParam === 'offline') {
            filterOffline = true;
            filterOnline = false;
        }
        applyPeerStatusFilter();

        fetchPeersStatus();
        if (peersPollingInterval) clearInterval(peersPollingInterval);
        peersPollingInterval = setInterval(fetchPeersStatus, 30000);
    }

    // Expose for HTML event listeners
    window.onVpnOnlyToggleChange = onVpnOnlyToggleChange;
    window.discardAllPeerChanges = discardAllPeerChanges;
    window.applyAllPeerChanges = applyAllPeerChanges;
    window.enablePeerEditMode = enablePeerEditMode;
    window.cancelPeerEditMode = cancelPeerEditMode;
    window.enablePeerNameEditMode = enablePeerNameEditMode;
    window.cancelPeerNameEditMode = cancelPeerNameEditMode;
    window.enablePeerRouteEditMode = enablePeerRouteEditMode;
    window.cancelPeerRouteEditMode = cancelPeerRouteEditMode;
    window.togglePeerStatusFilter = togglePeerStatusFilter;

    document.addEventListener("DOMContentLoaded", function () {
        initPeersPolling();
    });
})();
