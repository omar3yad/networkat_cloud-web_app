/**
 * Networkat SD-WAN Peer Details Controller
 */
(function () {
    'use strict';

    let currentPeerName = "";
    let currentPeerNetwork = "";
    let currentRouteId = "";
    let currentRouteNetworkId = "";
    let peerId = "";

    let otherPeers = [];
    let otherRoutes = [];

    function initPage(config) {
        currentPeerName = config.peerName || "";
        currentPeerNetwork = config.peerNetwork || "";
        currentRouteId = config.routeId || "";
        currentRouteNetworkId = config.routeNetworkId || "";
        peerId = config.peerId || "";

        loadFleetContext();
        bindInputListeners();
    }

    async function loadFleetContext() {
        try {
            const [peersRes, routesRes] = await Promise.all([
                fetch('/api/peers').catch(() => null),
                fetch('/api/v2/netbird/routes').catch(() => null)
            ]);
            if (peersRes && peersRes.ok) otherPeers = await peersRes.json();
            if (routesRes && routesRes.ok) otherRoutes = await routesRes.json();
        } catch (e) {
            console.error('Error loading fleet context:', e);
        }
    }

    function validateIpv4Cidr(cidr) {
        if (!cidr || typeof cidr !== 'string' || !cidr.trim()) {
            return { valid: false, error: 'Subnet required' };
        }
        return window.parseAndValidateIPv4(cidr, { requireMask: true, normalizeSubnet: true });
    }

    function validateNameField(name) {
        if (!name || typeof name !== 'string' || !name.trim()) {
            return { valid: false, error: 'Name required' };
        }
        const trimmed = name.trim();
        const dnsRes = window.validateDNSName ? window.validateDNSName(trimmed, { allowDots: false, maxLength: 63 }) : { valid: true };
        if (!dnsRes.valid) {
            return { valid: false, error: dnsRes.error || 'Invalid DNS name' };
        }
        const isDup = otherPeers.some(p => p.id !== peerId && (p.name || '').trim().toLowerCase() === trimmed.toLowerCase());
        if (isDup) {
            return { valid: false, error: 'Name already in use' };
        }
        return { valid: true, normalized: trimmed };
    }

    function validateNetworkField(network) {
        if (!network || typeof network !== 'string' || !network.trim()) {
            return { valid: true, normalized: '' };
        }
        const trimmed = network.trim();
        const cidrRes = validateIpv4Cidr(trimmed);
        if (!cidrRes.valid) return cidrRes;

        const targetNet = cidrRes.normalized.toLowerCase();
        const dupRoute = otherRoutes.find(r => {
            if (r.peer === peerId || !r.network) return false;
            const otherRes = validateIpv4Cidr(r.network);
            const otherNet = otherRes.valid ? otherRes.normalized.toLowerCase() : r.network.trim().toLowerCase();
            return otherNet === targetNet;
        });

        if (dupRoute) {
            return { valid: false, error: 'Subnet already in use' };
        }
        return cidrRes;
    }

    function setFieldInlineError(field, errorMsg) {
        const inp = document.getElementById(`peer-${field}-input`);
        const errDiv = document.getElementById(`peer-${field}-error`);
        if (inp) inp.classList.add('is-invalid');
        if (errDiv) {
            errDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${errorMsg}`;
            errDiv.style.display = 'flex';
        }
    }

    function clearFieldInlineError(field) {
        const inp = document.getElementById(`peer-${field}-input`);
        const errDiv = document.getElementById(`peer-${field}-error`);
        if (inp) inp.classList.remove('is-invalid');
        if (errDiv) {
            errDiv.textContent = '';
            errDiv.style.display = 'none';
        }
    }

    function toggleEditField(field, isEditing) {
        const displayEl = document.getElementById(`peer-${field}-display`);
        const inputEl = document.getElementById(`peer-${field}-input`);
        const editBtn = document.getElementById(`btn-edit-${field}`);
        const actionsGroup = document.getElementById(`actions-${field}`);

        if (!displayEl || !inputEl || !editBtn || !actionsGroup) return;

        clearFieldInlineError(field);

        if (isEditing) {
            displayEl.style.display = 'none';
            editBtn.style.display = 'none';
            inputEl.style.display = 'inline-block';
            actionsGroup.style.display = 'inline-flex';
            inputEl.focus();
            inputEl.select();
        } else {
            if (field === 'name') {
                inputEl.value = currentPeerName;
            } else if (field === 'network') {
                inputEl.value = currentPeerNetwork;
            }
            inputEl.style.display = 'none';
            actionsGroup.style.display = 'none';
            displayEl.style.display = 'inline-block';
            editBtn.style.display = 'inline-flex';
        }
    }

    function bindInputListeners() {
        const nameInput = document.getElementById('peer-name-input');
        if (nameInput) {
            nameInput.addEventListener('input', () => {
                const res = validateNameField(nameInput.value);
                if (!res.valid) {
                    setFieldInlineError('name', res.error);
                } else {
                    clearFieldInlineError('name');
                }
            });
        }

        const networkInput = document.getElementById('peer-network-input');
        if (networkInput) {
            networkInput.addEventListener('input', () => {
                const res = validateNetworkField(networkInput.value);
                if (!res.valid) {
                    setFieldInlineError('network', res.error);
                } else {
                    clearFieldInlineError('network');
                }
            });
        }

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                const activeEl = document.activeElement;
                if (activeEl && activeEl.id === 'peer-name-input') {
                    savePeerField('name');
                } else if (activeEl && activeEl.id === 'peer-network-input') {
                    savePeerField('network');
                }
            } else if (e.key === 'Escape') {
                const activeEl = document.activeElement;
                if (activeEl && activeEl.id === 'peer-name-input') {
                    toggleEditField('name', false);
                } else if (activeEl && activeEl.id === 'peer-network-input') {
                    toggleEditField('network', false);
                }
            }
        });
    }

    async function savePeerField(field) {
        const inputEl = document.getElementById(`peer-${field}-input`);
        const actionsGroup = document.getElementById(`actions-${field}`);
        const saveBtn = actionsGroup ? actionsGroup.querySelector('.btn-badge-save') : null;
        if (!inputEl || !saveBtn) return;

        clearFieldInlineError(field);

        if (field === 'name') {
            const newName = inputEl.value.trim();
            const res = validateNameField(newName);
            if (!res.valid) {
                setFieldInlineError('name', res.error);
                inputEl.focus();
                return;
            }

            const originalHtml = saveBtn.innerHTML;
            saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            saveBtn.disabled = true;

            try {
                const resp = await fetch(`/peers/${peerId}/update`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: newName })
                });

                const data = await resp.json();
                if (!resp.ok || !data.success) {
                    throw new Error(data.error || 'Failed to save');
                }

                currentPeerName = newName;
                document.getElementById('peer-name-display').textContent = newName;
                const titleH1 = document.querySelector('.title-area h1');
                if (titleH1) titleH1.textContent = newName;

                const selfPeer = otherPeers.find(p => p.id === peerId);
                if (selfPeer) selfPeer.name = newName;

                toggleEditField('name', false);
            } catch (err) {
                setFieldInlineError('name', err.message || 'Failed to save');
            } finally {
                saveBtn.innerHTML = originalHtml;
                saveBtn.disabled = false;
            }
        } else if (field === 'network') {
            const rawNetwork = inputEl.value.trim();
            const res = validateNetworkField(rawNetwork);
            if (!res.valid) {
                setFieldInlineError('network', res.error);
                inputEl.focus();
                return;
            }

            const newNetwork = res.normalized || '';
            if (inputEl.value !== newNetwork) {
                inputEl.value = newNetwork;
            }

            const originalHtml = saveBtn.innerHTML;
            saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            saveBtn.disabled = true;

            try {
                const networkId = currentRouteNetworkId || `route-${peerId.substring(0, 8)}`;

                if (newNetwork) {
                    const routeBody = {
                        "description": `Route handled via inline dashboard for peer ${peerId}`,
                        "network_id": networkId,
                        "enabled": true,
                        "peer": peerId,
                        "network": newNetwork,
                        "metric": 9999,
                        "masquerade": false,
                        "keep_route": true,
                        "groups": []
                    };

                    if (currentRouteId && currentRouteId !== 'null' && currentRouteId !== 'undefined') {
                        const routeRes = await fetch(`/api/v2/netbird/routes/${currentRouteId}`, {
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
                        const createdData = await createRes.json().catch(() => ({}));
                        if (createdData.id) {
                            currentRouteId = createdData.id;
                            currentRouteNetworkId = createdData.network_id || networkId;
                        }
                    }

                    currentPeerNetwork = newNetwork;
                    document.getElementById('peer-network-display').innerHTML = `<code>${newNetwork}</code>`;

                    const selfRoute = otherRoutes.find(r => r.peer === peerId);
                    if (selfRoute) {
                        selfRoute.network = newNetwork;
                    } else {
                        otherRoutes.push({ peer: peerId, network: newNetwork });
                    }
                } else if (currentRouteId && currentRouteId !== 'null' && currentRouteId !== 'undefined') {
                    await fetch(`/api/v2/netbird/routes/${currentRouteId}`, { method: 'DELETE' });
                    currentPeerNetwork = "";
                    currentRouteId = "";
                    document.getElementById('peer-network-display').innerHTML = `<span style="color: var(--nk-text-muted); font-style: italic;">Not configured</span>`;
                    otherRoutes = otherRoutes.filter(r => r.peer !== peerId);
                } else {
                    currentPeerNetwork = "";
                    document.getElementById('peer-network-display').innerHTML = `<span style="color: var(--nk-text-muted); font-style: italic;">Not configured</span>`;
                }

                toggleEditField('network', false);
            } catch (err) {
                setFieldInlineError('network', err.message);
            } finally {
                saveBtn.innerHTML = originalHtml;
                saveBtn.disabled = false;
            }
        }
    }

    // Expose for HTML event handlers
    window.toggleEditField = toggleEditField;
    window.savePeerField = savePeerField;
    window.initPeerDetails = initPage;
})();
