/**
 * Networkat SD-WAN Peer Fleet Management Controller
 */
(function () {
    'use strict';

    let peersPollingInterval = null;

    async function fetchAndPopulateRoutes() {
        try {
            const routesRes = await fetch('/api/v2/netbird/routes').catch(() => null);
            const routes = (routesRes && routesRes.ok) ? await routesRes.json() : [];

            const routeInputs = document.querySelectorAll('.inline-route-field');
            for (const input of routeInputs) {
                const peerId = input.getAttribute('data-peer-id');
                const peerRoute = routes.find(r => r.peer === peerId);

                if (document.activeElement !== input) {
                    input.value = peerRoute ? peerRoute.network : '';
                }

                if (peerRoute) {
                    input.setAttribute('data-route-id', peerRoute.id);
                    input.setAttribute('data-route-network-id', peerRoute.network_id);
                } else {
                    input.removeAttribute('data-route-id');
                    input.removeAttribute('data-route-network-id');
                }
            }
        } catch (err) {
            console.error('Error fetching routes:', err);
        }
    }

    function updatePeerStatuses(data) {
        if (!data || !data.peers) return;

        data.peers.forEach(peer => {
            const statusBadge = document.getElementById(`status-badge-${peer.id}`);
            if (!statusBadge) return;

            if (peer.is_online) {
                statusBadge.className = "badge badge-success";
                statusBadge.innerHTML = `<i class="fas fa-circle" style="font-size: 0.5rem; margin-right: 4px;"></i> Connected`;
            } else {
                statusBadge.className = "badge badge-inactive";
                statusBadge.innerHTML = `<i class="fas fa-circle" style="font-size: 0.5rem; margin-right: 4px;"></i> Offline`;
            }

            // Update VPN-Only state
            const vpnToggle = document.getElementById(`vpn-only-toggle-${peer.id}`);
            const vpnText = document.getElementById(`vpn-only-text-${peer.id}`);
            if (vpnToggle && document.activeElement !== vpnToggle) {
                vpnToggle.checked = !!peer.vpn_only;
                vpnToggle.disabled = !peer.is_online;
                if (vpnText) {
                    vpnText.innerText = peer.vpn_only ? 'ON' : 'OFF';
                }
            }

            // Update Control / Filtering button state
            const filterLink = document.getElementById(`filter-link-${peer.id}`);
            if (filterLink) {
                if (peer.is_online) {
                    filterLink.href = `/peers/${peer.id}/filtering`;
                    filterLink.style.backgroundColor = "#00b06f";
                    filterLink.style.borderColor = "#00b06f";
                    filterLink.style.color = "white";
                    filterLink.style.opacity = "1";
                    filterLink.style.pointerEvents = "auto";
                    filterLink.style.cursor = "pointer";
                    filterLink.removeAttribute('onclick');
                } else {
                    filterLink.href = "javascript:void(0)";
                    filterLink.style.backgroundColor = "#6c757d";
                    filterLink.style.borderColor = "#6c757d";
                    filterLink.style.color = "white";
                    filterLink.style.opacity = "0.65";
                    filterLink.style.pointerEvents = "none";
                    filterLink.style.cursor = "not-allowed";
                    filterLink.setAttribute('onclick', 'event.preventDefault()');
                }
            }

            // Update Firewall button state
            const firewallLink = document.getElementById(`firewall-link-${peer.id}`);
            if (firewallLink) {
                if (peer.is_online) {
                    firewallLink.href = `/peers/${peer.id}/firewall`;
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
        if (trimmed.length > 200) {
            return { valid: false, error: 'Max 200 characters' };
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
        return { valid: true };
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
        if (inp) inp.classList.add('is-invalid');
        if (errDiv) {
            errDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${errorMsg}`;
            errDiv.style.display = 'flex';
        }
    }

    function clearInlineError(inputId) {
        const inp = document.getElementById(inputId);
        const errDiv = document.getElementById(`${inputId}-error`);
        if (inp) inp.classList.remove('is-invalid');
        if (errDiv) {
            errDiv.textContent = '';
            errDiv.style.display = 'none';
        }
    }

    function renderPeersTable(peers) {
        const tbody = document.getElementById('peers-table-body');
        if (!tbody) return;

        if (!peers || peers.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align: center; padding: 4rem; color: var(--nk-text-muted);">
                        No Peer devices found in this customer group.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = '';
        peers.forEach(peer => {
            const peerId = peer.id;
            const name = peer.name || '';
            const route = peer.route || '';
            const vpnOnlyChecked = peer.vpn_only ? 'checked' : '';
            const vpnOnlyText = peer.vpn_only ? 'ON' : 'OFF';

            const isDisabled = !peer.is_online ? 'disabled' : '';
            const disabledTitle = !peer.is_online ? 'title="Device is offline"' : '';

            const badgeClass = peer.is_online ? 'badge-success' : 'badge-inactive';
            const statusText = peer.is_online ? 'Connected' : 'Offline';

            const isOffline = !peer.is_online;
            const filterUrl = `/peers/${peerId}/filtering`;
            const controlHref = isOffline ? 'javascript:void(0)' : filterUrl;
            const controlStyle = isOffline
                ? 'background-color: #6c757d; border-color: #6c757d; color: white; opacity: 0.65; cursor: not-allowed; pointer-events: none;'
                : 'background-color: #00b06f; border-color: #00b06f; color: white;';
            const controlAttr = isOffline ? 'onclick="event.preventDefault()"' : '';

            const firewallUrl = `/peers/${peerId}`;
            const firewallHref = isOffline ? 'javascript:void(0)' : firewallUrl;
            const firewallStyle = isOffline
                ? 'background-color: #6c757d; border-color: #6c757d; color: white; opacity: 0.65; cursor: not-allowed; pointer-events: none;'
                : 'background-color: var(--nk-blue-primary); border-color: var(--nk-blue-primary); color: white;';
            const firewallAttr = isOffline ? 'onclick="event.preventDefault()"' : '';

            const tr = document.createElement('tr');
            tr.setAttribute('data-peer-id', peerId);
            tr.onclick = (event) => goToPeerDetails(peerId, name.replace(/'/g, "\\'"), event);

            tr.innerHTML = `
                <td>
                    <input style="min-width: 150px;" type="text" class="table-input" id="inline-name-${peerId}"
                        value="${name}" placeholder="Device Name" maxlength="200">
                    <div class="table-error-msg" id="inline-name-${peerId}-error" style="display: none;"></div>
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
                                   onchange="toggleVpnOnly('${peerId}', this)"
                                   ${vpnOnlyChecked}
                                   ${isDisabled}>
                            <span class="slider"></span>
                        </label>
                        <span class="toggle-status-text" id="vpn-only-text-${peerId}">${vpnOnlyText}</span>
                    </div>
                </td>
                <td>
                    <span class="badge ${badgeClass}"
                        id="status-badge-${peerId}" data-peer-name="${name}"
                        data-last-seen="${peer.last_seen || ''}">
                        <i class="fas fa-circle" style="font-size: 0.5rem; margin-right: 4px;"></i>
                        ${statusText}
                    </span>
                </td>
                <td>
                    <div class="actions-cell">
                        <button class="action-btn btn-save" id="btn-save-${peerId}" onclick="saveInlineChanges('${peerId}')">
                            <i class="fas fa-save"></i> Save
                        </button>

                        <a href="${firewallHref}"
                            id="firewall-link-${peerId}" class="action-btn"
                            style="${firewallStyle}" ${firewallAttr}>
                            <i class="fas fa-shield-alt"></i> Manage
                        </a>
                    </div>
                </td>
            `;

            tbody.appendChild(tr);

            // Bind live validation on name and route inputs
            const nameInput = tr.querySelector(`#inline-name-${peerId}`);
            if (nameInput) {
                nameInput.addEventListener('input', () => {
                    const res = validatePeerDeviceName(nameInput.value, peerId);
                    if (!res.valid) {
                        setInlineError(`inline-name-${peerId}`, res.error);
                    } else {
                        clearInlineError(`inline-name-${peerId}`);
                    }
                });
            }

            const routeInput = tr.querySelector(`#inline-route-${peerId}`);
            if (routeInput) {
                routeInput.addEventListener('input', () => {
                    const res = validatePeerDeviceRoute(routeInput.value, peerId);
                    if (!res.valid) {
                        setInlineError(`inline-route-${peerId}`, res.error);
                    } else {
                        clearInlineError(`inline-route-${peerId}`);
                    }
                });
            }
        });

        fetchAndPopulateRoutes();
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

    async function saveInlineChanges(peerId) {
        clearInlineError(`inline-name-${peerId}`);
        clearInlineError(`inline-route-${peerId}`);

        const nameInput = document.getElementById(`inline-name-${peerId}`);
        const routeInput = document.getElementById(`inline-route-${peerId}`);
        const saveBtn = document.getElementById(`btn-save-${peerId}`);

        const newName = nameInput ? nameInput.value.trim() : '';
        const rawRouteNetwork = routeInput ? routeInput.value.trim() : '';

        // 1. Validate Name
        const nameRes = validatePeerDeviceName(newName, peerId);
        if (!nameRes.valid) {
            setInlineError(`inline-name-${peerId}`, nameRes.error);
            if (nameInput) nameInput.focus();
            return;
        }

        // 2. Validate Route Network
        const routeRes = validatePeerDeviceRoute(rawRouteNetwork, peerId);
        if (!routeRes.valid) {
            setInlineError(`inline-route-${peerId}`, routeRes.error);
            if (routeInput) routeInput.focus();
            return;
        }

        const newRouteNetwork = routeRes.normalized || '';
        if (routeInput && newRouteNetwork && routeInput.value !== newRouteNetwork) {
            routeInput.value = newRouteNetwork;
        }

        if (saveBtn) saveBtn.disabled = true;

        try {
            const nameResponse = await fetch(`/peers/${peerId}/update`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName })
            });

            const nameData = await nameResponse.json();
            if (!nameResponse.ok || nameData.error) {
                throw new Error(nameData.error || 'Failed to save');
            }

            const existingRouteId = routeInput.getAttribute('data-route-id');
            const existingNetworkId = routeInput.getAttribute('data-route-network-id');

            if (newRouteNetwork) {
                const networkId = existingNetworkId || `route-${peerId.substring(0, 8)}`;

                const routeBody = {
                    "description": `Route handled via inline dashboard for peer ${peerId}`,
                    "network_id": networkId,
                    "enabled": true,
                    "peer": peerId,
                    "network": newRouteNetwork,
                    "metric": 9999,
                    "masquerade": false,
                    "keep_route": true,
                    "groups": []
                };

                if (existingRouteId && existingRouteId !== 'null' && existingRouteId !== 'undefined') {
                    const routeRes = await fetch(`/api/v2/netbird/routes/${existingRouteId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(routeBody)
                    });

                    if (!routeRes.ok) {
                        const errData = await routeRes.json().catch(() => ({}));
                        throw new Error(errData.detail || errData.message || errData.error || 'Failed to save');
                    }
                } else {
                    const createRes = await fetch('/api/v2/netbird/routes', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(routeBody)
                    });

                    if (!createRes.ok) {
                        const errData = await createRes.json().catch(() => ({}));
                        throw new Error(errData.detail || errData.message || errData.error || 'Failed to save');
                    }
                }
            } else if (existingRouteId) {
                await fetch(`/api/v2/netbird/routes/${existingRouteId}`, { method: 'DELETE' });
            }

            await fetchAndPopulateRoutes();

            const tbody = document.getElementById('peers-table-body');
            if (tbody) {
                tbody.removeAttribute('data-loaded');
            }
            await fetchPeersStatus();

            if (window.showSuccess) {
                window.showSuccess('Saved');
            } else {
                alert('Saved');
            }
        } catch (error) {
            console.error('Save Error:', error);
            let cleanMessage = error.message;
            try {
                const jsonMatch = cleanMessage.match(/\{.*\}/);
                if (jsonMatch) {
                    const parsed = JSON.parse(jsonMatch[0]);
                    if (parsed.message) cleanMessage = parsed.message;
                    if (parsed.error) cleanMessage = parsed.error;
                }
            } catch (e) { }
            alert(cleanMessage || 'Failed to save');
        } finally {
            if (saveBtn) saveBtn.disabled = false;
        }
    }

    async function toggleVpnOnly(peerId, checkbox) {
        const action = checkbox.checked ? 'on' : 'off';
        const statusText = document.getElementById(`vpn-only-text-${peerId}`);

        checkbox.disabled = true;

        try {
            const response = await fetch(`/api/peers/${peerId}/vpn-only`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ operation: action })
            });

            const data = await response.json();

            if (response.ok && (data.ok === true || data.status === 'success')) {
                if (statusText) statusText.innerText = action.toUpperCase();
            } else {
                alert(data.error || data.detail || 'Failed to set VPN mode');
                checkbox.checked = !checkbox.checked;
            }
        } catch (err) {
            console.error('VPN-Only update error:', err);
            alert('Failed to set VPN mode');
            checkbox.checked = !checkbox.checked;
        } finally {
            checkbox.disabled = false;
        }
    }

    function timeAgo(dateString) {
        if (!dateString) return 'Never';
        const now = new Date();
        const past = new Date(dateString);

        if (isNaN(past.getTime())) return 'Never';

        const msPerMinute = 60 * 1000;
        const msPerHour = msPerMinute * 60;
        const msPerDay = msPerHour * 24;
        const elapsed = now - past;

        if (elapsed < msPerMinute) {
            return 'Just now';
        } else if (elapsed < msPerHour) {
            return 'Since ' + Math.round(elapsed / msPerMinute) + 'm ago';
        } else if (elapsed < msPerDay) {
            return 'Since ' + Math.round(elapsed / msPerHour) + 'h ago';
        } else {
            return 'Since ' + Math.round(elapsed / msPerDay) + 'd ago';
        }
    }

    function goToPeerDetails(peerId, name, event) {
        if (event.target.closest('input') ||
            event.target.closest('button') ||
            event.target.closest('a') ||
            event.target.closest('.switch') ||
            event.target.closest('.actions-cell') ||
            event.target.closest('.toggle-container')) {
            return;
        }
        window.location.href = `/peers/${peerId}`;
    }

    // Expose for HTML event listeners
    window.saveInlineChanges = saveInlineChanges;
    window.toggleVpnOnly = toggleVpnOnly;
    window.goToPeerDetails = goToPeerDetails;

    document.addEventListener("DOMContentLoaded", function () {
        initPeersPolling();
    });
})();
