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
                if (window.showSuccess) window.showSuccess('Saved');
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
                if (window.showSuccess) window.showSuccess('Saved');
            } catch (err) {
                setFieldInlineError('network', err.message);
            } finally {
                saveBtn.innerHTML = originalHtml;
                saveBtn.disabled = false;
            }
        }
    }

    function openDeletePeerModal() {
        const modal = document.getElementById('deletePeerModal');
        const input = document.getElementById('delete-confirm-input');
        const confirmBtn = document.getElementById('btn-confirm-delete-peer');
        if (input) {
            input.value = '';
            input.classList.remove('is-invalid');
        }
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.innerHTML = '<i class="fas fa-trash-alt"></i> Delete Peer';
        }
        if (modal) {
            modal.classList.add('active');
            setTimeout(() => {
                if (input) input.focus();
            }, 50);
        }
    }

    function closeDeletePeerModal() {
        const modal = document.getElementById('deletePeerModal');
        if (modal) {
            modal.classList.remove('active');
        }
    }

    function handleDeleteModalOverlayClick(event) {
        if (event.target && event.target.id === 'deletePeerModal') {
            closeDeletePeerModal();
        }
    }

    function onDeleteConfirmInput(event) {
        const value = (event.target.value || '').trim();
        const confirmBtn = document.getElementById('btn-confirm-delete-peer');
        if (confirmBtn) {
            confirmBtn.disabled = (value !== 'delete');
        }
    }

    function onDeleteConfirmKeydown(event) {
        if (event.key === 'Enter') {
            const value = (event.target.value || '').trim();
            if (value === 'delete') {
                event.preventDefault();
                confirmDeletePeer();
            }
        } else if (event.key === 'Escape') {
            closeDeletePeerModal();
        }
    }

    async function confirmDeletePeer() {
        const input = document.getElementById('delete-confirm-input');
        const confirmBtn = document.getElementById('btn-confirm-delete-peer');

        if (!input || input.value.trim() !== 'delete') {
            return;
        }

        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Deleting...';
        }

        try {
            const resp = await fetch(`/api/peers/${encodeURIComponent(peerId)}/delete`, {
                method: 'DELETE',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                }
            });

            const data = await resp.json().catch(() => ({}));

            if (!resp.ok) {
                const errorMsg = data.message || data.error || data.detail || 'Failed to delete peer';
                throw new Error(errorMsg);
            }

            closeDeletePeerModal();

            if (window.showSuccess) {
                window.showSuccess(data.message || 'Peer deleted successfully');
            }

            // Redirect back to peers list page after short delay
            setTimeout(() => {
                window.location.href = '/peers';
            }, 800);

        } catch (err) {
            if (window.showError) {
                window.showError(err.message || 'Failed to delete peer');
            } else {
                alert(err.message || 'Failed to delete peer');
            }
            if (confirmBtn) {
                confirmBtn.disabled = false;
                confirmBtn.innerHTML = '<i class="fas fa-trash-alt"></i> Delete Peer';
            }
        }
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const modal = document.getElementById('deletePeerModal');
            if (modal && modal.classList.contains('active')) {
                closeDeletePeerModal();
            }
            const servicesModal = document.getElementById('servicesModal');
            if (servicesModal && servicesModal.classList.contains('active')) {
                closeServicesModal();
            }
        }
    });

    async function openServicesModal() {
        const modal = document.getElementById('servicesModal');
        const loading = document.getElementById('services-loading');
        const errorEl = document.getElementById('services-error');
        const list = document.getElementById('services-list');
        if (!modal) return;

        modal.classList.add('active');
        loading.style.display = 'block';
        errorEl.style.display = 'none';
        list.style.display = 'none';

        try {
            const resp = await fetch(`/api/peers/${encodeURIComponent(peerId)}/services`);
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                throw new Error(data.error || 'Failed to load service settings');
            }

            const services = data.services || [];
            services.forEach(svc => {
                const toggle = document.querySelector(`.service-toggle[data-service="${svc.name}"]`);
                if (toggle) toggle.checked = svc.state === 'enabled';
            });

            loading.style.display = 'none';
            list.style.display = 'flex';
        } catch (err) {
            loading.style.display = 'none';
            errorEl.textContent = err.message || 'Failed to load service settings';
            errorEl.style.display = 'block';
        }
    }

    function closeServicesModal() {
        const modal = document.getElementById('servicesModal');
        if (modal) modal.classList.remove('active');
    }

    function handleServicesModalOverlayClick(event) {
        if (event.target && event.target.id === 'servicesModal') {
            closeServicesModal();
        }
    }

    async function toggleService(checkbox) {
        const serviceName = checkbox.getAttribute('data-service');
        const newState = checkbox.checked ? 'enabled' : 'disabled';
        checkbox.disabled = true;

        try {
            const resp = await fetch(`/api/peers/${encodeURIComponent(peerId)}/services`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ services: { [serviceName]: newState } })
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                throw new Error(data.error || 'Failed to update service');
            }
            if (window.showSuccess) window.showSuccess('Saved');
        } catch (err) {
            checkbox.checked = !checkbox.checked;
            if (window.showError) {
                window.showError(err.message || 'Failed to update service');
            } else {
                alert(err.message || 'Failed to update service');
            }
        } finally {
            checkbox.disabled = false;
        }
    }

    // Expose for HTML event handlers
    window.toggleEditField = toggleEditField;
    window.savePeerField = savePeerField;
    window.initPeerDetails = initPage;
    window.openDeletePeerModal = openDeletePeerModal;
    window.closeDeletePeerModal = closeDeletePeerModal;
    window.handleDeleteModalOverlayClick = handleDeleteModalOverlayClick;
    window.onDeleteConfirmInput = onDeleteConfirmInput;
    window.onDeleteConfirmKeydown = onDeleteConfirmKeydown;
    window.confirmDeletePeer = confirmDeletePeer;
    window.openServicesModal = openServicesModal;
    window.closeServicesModal = closeServicesModal;
    window.handleServicesModalOverlayClick = handleServicesModalOverlayClick;
    window.toggleService = toggleService;
})();
