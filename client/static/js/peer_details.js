/**
 * Networkat SD-WAN Peer Details Controller
 */
(function () {
    'use strict';
    const _apiBase = (window.API_BASE || '');
    const _adminView = !!(window.ADMIN_VIEW);

    let currentPeerName = "";
    let currentPeerNetwork = "";
    let currentRouteId = "";
    let currentRouteNetworkId = "";
    let peerId = "";

    let otherPeers = [];
    let otherRoutes = [];

    let isPeerOnline = false;

    // Sets a toggle's checked state without animating the slider — used when
    // JS applies a value fetched after the modal/list is already visible.
    function setToggleCheckedNoAnim(input, value) {
        if (!input) return;
        const label = input.closest('.switch');
        if (!label) {
            input.checked = value;
            return;
        }
        label.classList.add('no-anim');
        input.checked = value;
        void label.offsetWidth; // force reflow so the transition is actually suppressed
        label.classList.remove('no-anim');
    }

    function initPage(config) {
        currentPeerName = config.peerName || "";
        currentPeerNetwork = config.peerNetwork || "";
        currentRouteId = config.routeId || "";
        currentRouteNetworkId = config.routeNetworkId || "";
        peerId = config.peerId || "";
        isPeerOnline = !!config.isOnline;

        loadFleetContext();
        bindInputListeners();

        // ?update=1 (the system logs "Update device" link) opens the update window.
        const params = new URLSearchParams(window.location.search);
        if (params.get("update") === "1") {
            params.delete("update");
            const qs = params.toString();
            history.replaceState(null, "", window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash);
            openUpdatesModal();
        }

        // Immediately sync current peer status in the sidebar
        if (peerId) {
            const sidebarDot = document.getElementById(`sidebar-dot-${peerId}`);
            if (sidebarDot) {
                sidebarDot.className = `peer-status-dot ${isPeerOnline ? 'online' : 'offline'}`;
                sidebarDot.title = isPeerOnline ? 'Connected' : 'Offline';
            }
            const sidebarItem = document.getElementById(`sidebar-peer-${peerId}`);
            if (sidebarItem) {
                sidebarItem.setAttribute('data-sidebar-online', isPeerOnline ? 'true' : 'false');
                if (currentPeerName) {
                    const label = sidebarItem.querySelector('.submenu-label');
                    if (label && label.textContent !== currentPeerName) {
                        label.textContent = currentPeerName;
                    }
                    sidebarItem.title = `${currentPeerName} (${isPeerOnline ? 'Connected' : 'Offline'})`;
                }
            }
        }

        if (isPeerOnline) {
            const uptimeEl = document.getElementById("peer-uptime-display");
            const initialUptime = uptimeEl ? uptimeEl.getAttribute("data-uptime-seconds") : "";
            if (initialUptime !== "" && initialUptime !== null) {
                startUptimeStopwatch(Number(initialUptime));
            }
            fetchPeerVersionSilent();
        }
    }

    async function loadFleetContext() {
        try {
            const [peersRes, routesRes] = await Promise.all([
                fetch(`${_apiBase}/api/peers`).catch(() => null),
                fetch(`${_apiBase}/api/v2/netbird/routes`).catch(() => null)
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

    function cleanFriendlyError(err, defaultMsg = 'Failed to save') {
        let msg = err && err.message ? err.message : (err || defaultMsg);
        if (typeof msg !== 'string') {
            try { msg = JSON.stringify(msg); } catch(e) { msg = defaultMsg; }
        }
        
        if (msg.includes('{') && msg.includes('}')) {
            try {
                const start = msg.indexOf('{');
                const end = msg.lastIndexOf('}') + 1;
                const parsed = JSON.parse(msg.substring(start, end));
                msg = parsed.message || parsed.detail || parsed.error || msg;
            } catch(e) {}
        }

        msg = msg.replace(/NetBird\s*Error:\s*/gi, '');
        msg = msg.replace(/NetBird\s*/gi, '');
        msg = msg.replace(/route:\s*[a-zA-Z0-9_-]+\s*not found/gi, 'Route not found or expired');
        msg = msg.replace(/peer:\s*[a-zA-Z0-9_-]+/gi, 'Device');
        msg = msg.replace(/\b[a-zA-Z0-9]{15,}\b/g, '');
        msg = msg.replace(/[:"'{}]/g, ' ').replace(/\s+/g, ' ').trim();

        return msg || defaultMsg;
    }

    function setFieldInlineError(field, errorMsg) {
        const inp = document.getElementById(`peer-${field}-input`);
        const errDiv = document.getElementById(`peer-${field}-error`);
        const friendlyMsg = cleanFriendlyError(errorMsg);
        if (inp) inp.classList.add('is-invalid');
        if (errDiv) {
            errDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${friendlyMsg}`;
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

        document.addEventListener('keydown', function (e) {
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

        setupUpdateIntervalValidation();
    }

    function showIntervalError(msg = "Min 3 hours") {
        const errEl = document.getElementById("auto-update-interval-error");
        const intervalInp = document.getElementById("update-interval-hours");
        if (errEl) {
            errEl.innerHTML = `<i class="fas fa-exclamation-circle"></i> <span>${escapeHtml(msg)}</span>`;
            errEl.style.display = "flex";
            errEl.classList.remove("shake-error");
            void errEl.offsetWidth;
            errEl.classList.add("shake-error");
        }
        if (intervalInp) {
            intervalInp.classList.add("is-invalid");
            intervalInp.classList.remove("shake-error");
            void intervalInp.offsetWidth;
            intervalInp.classList.add("shake-error");
        }
    }

    function hideIntervalError() {
        const errEl = document.getElementById("auto-update-interval-error");
        const intervalInp = document.getElementById("update-interval-hours");
        if (errEl) {
            errEl.style.display = "none";
            errEl.textContent = "";
        }
        if (intervalInp) {
            intervalInp.classList.remove("is-invalid");
        }
    }

    function setupUpdateIntervalValidation() {
        const intervalInp = document.getElementById("update-interval-hours");
        if (!intervalInp) return;

        function handleSpinnerDown(e) {
            const rect = intervalInp.getBoundingClientRect();
            const isSpinnerX = (e.clientX >= rect.right - 28);
            if (!isSpinnerX) return;

            const isDownSpinner = (e.clientY >= rect.top + (rect.height / 2));
            if (isDownSpinner) {
                const val = parseInt(intervalInp.value, 10);
                if (isNaN(val) || val <= 3) {
                    e.preventDefault();
                    e.stopPropagation();
                    intervalInp.value = 3;
                    showIntervalError("Min 3 hours");
                    updateSaveButtonState();
                }
            }
        }

        intervalInp.addEventListener("pointerdown", handleSpinnerDown);
        intervalInp.addEventListener("mousedown", handleSpinnerDown);

        intervalInp.addEventListener("keydown", (e) => {
            if (e.key === "ArrowDown") {
                const val = parseInt(intervalInp.value, 10);
                if (isNaN(val) || val <= 3) {
                    e.preventDefault();
                    intervalInp.value = 3;
                    showIntervalError("Min 3 hours");
                    updateSaveButtonState();
                }
            }
        });

        intervalInp.addEventListener("wheel", (e) => {
            if (e.deltaY > 0) {
                const val = parseInt(intervalInp.value, 10);
                if (isNaN(val) || val <= 3) {
                    e.preventDefault();
                    intervalInp.value = 3;
                    showIntervalError("Min 3 hours");
                    updateSaveButtonState();
                }
            }
        }, { passive: false });

        intervalInp.addEventListener("input", () => {
            const rawVal = intervalInp.value.trim();
            const val = parseInt(rawVal, 10);
            if (rawVal === "" || isNaN(val) || val < 3) {
                showIntervalError("Min 3 hours");
            } else {
                hideIntervalError();
            }
            onAutoUpdateFieldChange();
        });

        intervalInp.addEventListener("blur", () => {
            const rawVal = intervalInp.value.trim();
            const val = parseInt(rawVal, 10);
            if (rawVal === "" || isNaN(val) || val < 3) {
                intervalInp.value = 3;
                hideIntervalError();
                updateSaveButtonState();
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

                const sidebarItem = document.getElementById(`sidebar-peer-${peerId}`);
                if (sidebarItem) {
                    const label = sidebarItem.querySelector('.submenu-label');
                    if (label) label.textContent = newName;
                    sidebarItem.title = `${newName} (${isPeerOnline ? 'Connected' : 'Offline'})`;
                }

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
                        let routeRes = await fetch(`${_apiBase}/api/v2/netbird/routes/${currentRouteId}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(routeBody)
                        });
                        if (routeRes.status === 404) {
                            routeRes = await fetch(`${_apiBase}/api/v2/netbird/routes`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(routeBody)
                            });
                        }
                        if (!routeRes.ok) {
                            const errData = await routeRes.json().catch(() => ({}));
                            throw new Error(errData.detail || errData.message || errData.error || 'Failed to save');
                        }
                        const updatedData = await routeRes.json().catch(() => ({}));
                        if (updatedData.id) {
                            currentRouteId = updatedData.id;
                            currentRouteNetworkId = updatedData.network_id || networkId;
                        }
                    } else {
                        const createRes = await fetch(`${_apiBase}/api/v2/netbird/routes`, {
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
                    await fetch(`${_apiBase}/api/v2/netbird/routes/${currentRouteId}`, { method: 'DELETE' });
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
            const resp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/delete`, {
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

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            const modal = document.getElementById('deletePeerModal');
            if (modal && modal.classList.contains('active')) {
                closeDeletePeerModal();
            }
            const servicesModal = document.getElementById('servicesModal');
            if (servicesModal && servicesModal.classList.contains('active')) {
                closeServicesModal();
            }
            const updatesModal = document.getElementById('updatesModal');
            if (updatesModal && updatesModal.classList.contains('active') && !isApplyingUpdate) {
                closeUpdatesModal();
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
            const [servicesResult] = await Promise.all([
                (async () => {
                    const resp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/services`);
                    const data = await resp.json().catch(() => ({}));
                    if (!resp.ok) {
                        throw new Error(data.error || 'Failed to load service settings');
                    }
                    return data;
                })(),
                loadSystemLogsState()
            ]);

            const services = servicesResult.services || [];
            services.forEach(svc => {
                const toggle = document.querySelector(`.service-toggle[data-service="${svc.name}"]`);
                setToggleCheckedNoAnim(toggle, svc.state === 'enabled');
            });

            loading.style.display = 'none';
            list.style.display = 'flex';
        } catch (err) {
            loading.style.display = 'none';
            errorEl.textContent = err.message || 'Failed to load service settings';
            errorEl.style.display = 'block';
        }
    }

    async function loadSystemLogsState() {
        const toggle = document.getElementById('service-toggle-system-logs');
        if (!toggle || !window.NkSystemLogs) return;
        try {
            const cfg = await window.NkSystemLogs.api.config(peerId);
            setToggleCheckedNoAnim(toggle, !!cfg.enabled);
        } catch (err) {
            // Leave the toggle at its default; the row still opens the system logs page on click.
        }
    }

    async function toggleSystemLogs(checkbox) {
        const on = checkbox.checked;
        if (!window.NkSystemLogs) return;
        if (!on) {
            const ok = window.nkConfirm ? await window.nkConfirm('Hide all logs on this device?', 'Turn off system logs?', 'Turn off') : true;
            if (!ok) {
                checkbox.checked = true;
                return;
            }
        }
        checkbox.disabled = true;
        try {
            await window.NkSystemLogs.api.setService(peerId, on ? 'enabled' : 'disabled');
            if (window.showSuccess) window.showSuccess(on ? 'System logs on' : 'System logs off');
        } catch (err) {
            checkbox.checked = !on;
            if (window.showError) {
                window.showError(err.message || 'Failed to update system logs');
            } else {
                console.error('Failed to update system logs:', err);
            }
        } finally {
            checkbox.disabled = false;
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
            const resp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/services`, {
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
                console.error('Failed to update service:', err);
            }
        } finally {
            checkbox.disabled = false;
        }
    }

    // ==========================================================================
    // Software Updates Feature
    // ==========================================================================

    let isApplyingUpdate = false;
    let manualCheckUsed = false;
    let initialAutoUpdateEnabled = false;
    let initialIntervalHours = 12;
    let initialChannel = 'stable';

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function formatUptime(seconds) {
        seconds = Math.floor(seconds);
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;
        const pad = (n) => String(n).padStart(2, "0");
        const prefix = days ? `${days}d ` : "";
        return `${prefix}${pad(hours)}:${pad(minutes)}:${pad(secs)}`;
    }

    let uptimeBaseSeconds = 0;
    let uptimeBaseTs = 0;
    let uptimeIntervalId = null;

    function renderUptimeTick() {
        const uptimeEl = document.getElementById("peer-uptime-display");
        if (!uptimeEl) return;
        const elapsed = (Date.now() - uptimeBaseTs) / 1000;
        uptimeEl.textContent = formatUptime(uptimeBaseSeconds + elapsed);
    }

    function startUptimeStopwatch(seconds) {
        if (uptimeIntervalId) {
            clearInterval(uptimeIntervalId);
            uptimeIntervalId = null;
        }
        uptimeBaseSeconds = seconds;
        uptimeBaseTs = Date.now();
        renderUptimeTick();
        uptimeIntervalId = setInterval(renderUptimeTick, 1000);
    }

    function stopUptimeStopwatch() {
        if (uptimeIntervalId) {
            clearInterval(uptimeIntervalId);
            uptimeIntervalId = null;
        }
    }

    function isV1Version(versionStr) {
        if (!versionStr) return false;
        const clean = String(versionStr).trim().toLowerCase().replace(/^v/, '');
        return clean.startsWith('1.') || clean === '1';
    }

    function disableUpdatesForV1(ver) {
        const btnCheck = document.getElementById("btn-check-update");
        const btnCheckText = document.getElementById("btn-check-update-text");
        const btnApply = document.getElementById("btn-apply-update");
        const availableCard = document.getElementById("updates-available-card");
        const badgeEl = document.getElementById("peer-version-badge");
        const dotEl = document.getElementById("update-badge-dot");

        if (btnCheck) {
            btnCheck.disabled = true;
            btnCheck.classList.remove("btn-check-updates-done");
            if (btnCheckText) btnCheckText.textContent = "Updates disabled on v1.x";
            const icon = btnCheck.querySelector("i");
            if (icon) icon.className = "fas fa-ban";
        }
        if (btnApply) btnApply.style.display = "none";
        if (availableCard) availableCard.style.display = "none";
        if (badgeEl) badgeEl.style.display = "none";
        if (dotEl) dotEl.style.display = "none";
    }

    async function fetchPeerVersionSilent() {
        if (!peerId || isApplyingUpdate) return;
        let detectedVersion = "";
        // 1. Fetch version directly from agent /health
        try {
            const hResp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/health`);
            if (hResp.ok) {
                const hData = await hResp.json();
                const healthVersion = hData.version || "";
                if (healthVersion) {
                    detectedVersion = healthVersion;
                    const versionEl = document.getElementById("peer-version-display");
                    if (versionEl) versionEl.textContent = healthVersion;
                    const updatesInstalledVal = document.getElementById("updates-installed-val");
                    if (updatesInstalledVal) updatesInstalledVal.textContent = healthVersion;
                }
                if (typeof hData.uptime === "number") {
                    startUptimeStopwatch(hData.uptime);
                } else {
                    stopUptimeStopwatch();
                }
            } else {
                stopUptimeStopwatch();
            }
        } catch (e) {
            // Health check silent fail
            stopUptimeStopwatch();
        }

        if (!detectedVersion) {
            detectedVersion = document.getElementById("updates-installed-val")?.textContent?.trim() || "";
        }

        // If peer is on v1.x, completely skip update query & badges
        if (isV1Version(detectedVersion)) {
            const badgeEl = document.getElementById("peer-version-badge");
            if (badgeEl) badgeEl.style.display = "none";
            const dotEl = document.getElementById("update-badge-dot");
            if (dotEl) dotEl.style.display = "none";
            return;
        }

        // 2. Fetch update discovery status
        try {
            const resp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/update`);
            if (!resp.ok) return;
            const data = await resp.json();
            const update = data.update || {};
            const installedVersion = update.installed_version || "";
            const availableVersion = update.available_version || "";
            if (installedVersion) {
                const versionEl = document.getElementById("peer-version-display");
                if (versionEl) versionEl.textContent = installedVersion;
                const updatesInstalledVal = document.getElementById("updates-installed-val");
                if (updatesInstalledVal) updatesInstalledVal.textContent = installedVersion;
            }
            if (isV1Version(installedVersion)) {
                const badgeEl = document.getElementById("peer-version-badge");
                if (badgeEl) badgeEl.style.display = "none";
                const dotEl = document.getElementById("update-badge-dot");
                if (dotEl) dotEl.style.display = "none";
                return;
            }
            if (update.state === "update-available" && availableVersion && availableVersion !== installedVersion) {
                const badgeEl = document.getElementById("peer-version-badge");
                if (badgeEl) {
                    const titleText = `available update: ${availableVersion}`;
                    badgeEl.title = titleText;
                    badgeEl.setAttribute("aria-label", titleText);
                    const tooltipEl = document.getElementById("peer-version-tooltip");
                    if (tooltipEl) tooltipEl.textContent = titleText;
                    badgeEl.style.display = "inline-flex";
                }
                const dotEl = document.getElementById("update-badge-dot");
                if (dotEl) dotEl.style.display = "inline-block";
            }
        } catch (e) {
            // Background check silent fail
        }
    }

    function openUpdatesModal() {
        const modal = document.getElementById("updatesModal");
        if (modal) modal.classList.add("active");
        hideIntervalError();
        clearUpdatesFeedback();
        manualCheckUsed = false;

        const curVer = document.getElementById("updates-installed-val")?.textContent?.trim() || document.getElementById("peer-version-display")?.textContent?.trim() || "";
        if (isV1Version(curVer)) {
            disableUpdatesForV1(curVer);
            loadAutoUpdateConfig();
            return;
        }

        checkPeerUpdate(false);
        loadAutoUpdateConfig();
    }

    function closeUpdatesModal() {
        if (isApplyingUpdate) return;
        const modal = document.getElementById("updatesModal");
        if (modal) modal.classList.remove("active");
    }

    function handleUpdatesModalOverlayClick(event) {
        if (isApplyingUpdate) return;
        if (event.target && event.target.id === "updatesModal") {
            closeUpdatesModal();
        }
    }

    function showUpdatesFeedback(message, type = "info") {
        const el = document.getElementById("updates-feedback-msg");
        if (!el) return;
        el.className = `updates-feedback-msg feedback-${type}`;
        const icon = type === "success" ? "fa-check-circle" : (type === "error" ? "fa-exclamation-circle" : "fa-info-circle");
        el.innerHTML = `<i class="fas ${icon}"></i> <span>${escapeHtml(message)}</span>`;
        el.style.display = "flex";
    }

    function clearUpdatesFeedback() {
        const el = document.getElementById("updates-feedback-msg");
        if (el) {
            el.textContent = "";
            el.style.display = "none";
        }
    }

    function setChannelChipUI(channel) {
        const chips = document.querySelectorAll("#update-channel-toggle .channel-toggle-chip");
        chips.forEach((chip) => {
            const isActive = chip.getAttribute("data-channel") === channel;
            chip.classList.toggle("active", isActive);
            chip.setAttribute("aria-pressed", isActive ? "true" : "false");
        });
    }

    let isChangingChannel = false;

    async function onChannelChipClick(channel) {
        if (isChangingChannel || channel === initialChannel) return;

        const previousChannel = initialChannel;
        isChangingChannel = true;
        setChannelChipUI(channel);
        setChannelChipsDisabled(true);
        clearUpdatesFeedback();

        try {
            const resp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/update/config`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel: channel })
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                throw new Error(data.error || "Failed to switch channel");
            }

            initialChannel = channel;
            await checkPeerUpdate(false);
        } catch (err) {
            setChannelChipUI(previousChannel);
            showUpdatesFeedback(err.message || "Failed to switch channel", "error");
        } finally {
            isChangingChannel = false;
            setChannelChipsDisabled(false);
            updateSaveButtonState();
        }
    }

    function setChannelChipsDisabled(disabled) {
        document.querySelectorAll("#update-channel-toggle .channel-toggle-chip").forEach((chip) => {
            chip.disabled = disabled;
        });
    }

    function updateSaveButtonState() {
        const btnSave = document.getElementById("btn-save-update-config");
        if (!btnSave) return;
        if (isApplyingUpdate) {
            btnSave.disabled = true;
            return;
        }
        const toggle = document.getElementById("auto-update-toggle");
        const intervalInp = document.getElementById("update-interval-hours");
        const curEnabled = toggle ? toggle.checked : false;
        const curValStr = intervalInp ? intervalInp.value.trim() : "";
        const curHours = parseInt(curValStr, 10);

        if (curEnabled && (curValStr === "" || isNaN(curHours) || curHours < 3)) {
            btnSave.disabled = true;
            return;
        }

        const isDirty = (curEnabled !== initialAutoUpdateEnabled) || (curHours !== initialIntervalHours);
        btnSave.disabled = !isDirty;
    }

    function setCheckButtonUpToDate(isUpToDate) {
        const btnCheck = document.getElementById("btn-check-update");
        const btnCheckText = document.getElementById("btn-check-update-text");
        if (!btnCheck) return;
        btnCheck.classList.toggle("btn-check-updates-done", isUpToDate);
        if (isUpToDate) {
            btnCheck.disabled = true;
            if (btnCheckText) btnCheckText.textContent = "Up to date";
            const icon = btnCheck.querySelector("i");
            if (icon) icon.className = "fas fa-check-circle";
        } else {
            btnCheck.disabled = manualCheckUsed;
            if (btnCheckText) btnCheckText.textContent = "Check for updates";
            const icon = btnCheck.querySelector("i");
            if (icon) icon.className = "fas fa-sync-alt";
        }
    }

    function formatReleaseDate(dateStr) {
        if (!dateStr) return "";
        try {
            const d = new Date(dateStr);
            if (isNaN(d.getTime())) return dateStr;
            const pad = (n) => String(n).padStart(2, '0');
            const year = d.getFullYear();
            const month = pad(d.getMonth() + 1);
            const day = pad(d.getDate());
            const hours = pad(d.getHours());
            const minutes = pad(d.getMinutes());
            const seconds = pad(d.getSeconds());
            return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
        } catch (e) {
            return dateStr;
        }
    }

    async function checkPeerUpdate(isManual) {
        if (isApplyingUpdate) return;
        const curVer = document.getElementById("updates-installed-val")?.textContent?.trim() || document.getElementById("peer-version-display")?.textContent?.trim() || "";
        if (isV1Version(curVer)) {
            disableUpdatesForV1(curVer);
            return;
        }
        if (isManual) manualCheckUsed = true;

        const btnCheck = document.getElementById("btn-check-update");
        const btnCheckText = document.getElementById("btn-check-update-text");
        const btnApply = document.getElementById("btn-apply-update");
        const installedVal = document.getElementById("updates-installed-val");
        const availableCard = document.getElementById("updates-available-card");
        const availableVal = document.getElementById("updates-available-val");
        const metaEl = document.getElementById("updates-available-meta");
        const releaseDateVal = document.getElementById("updates-release-date-val");
        const lastCheckedText = document.getElementById("updates-last-checked-text");

        if (btnCheck) {
            btnCheck.classList.remove("btn-check-updates-done");
            btnCheck.disabled = true;
            if (btnCheckText) btnCheckText.textContent = "Checking...";
            const icon = btnCheck.querySelector("i");
            if (icon) icon.className = "fas fa-spinner fa-spin";
        }
        clearUpdatesFeedback();

        try {
            const resp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/update`);
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                throw new Error(data.error || "Failed to check for updates");
            }

            const update = data.update || {};
            const state = update.state || "unknown";
            const installed = update.installed_version || "—";
            const available = update.available_version || "";
            const releaseDate = update.released_at || update.release_date || update.release_time || "";

            if (installedVal) installedVal.textContent = installed;

            const infoVersion = document.getElementById("peer-version-display");
            if (infoVersion && installed !== "—") infoVersion.textContent = installed;

            if (isV1Version(installed)) {
                disableUpdatesForV1(installed);
                return;
            }

            if (lastCheckedText) {
                const now = new Date();
                const pad = (n) => String(n).padStart(2, '0');
                lastCheckedText.textContent = `Checked at ${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
            }

            const versionBadge = document.getElementById("peer-version-badge");
            const dotBadge = document.getElementById("update-badge-dot");

            if (state === "update-available" && available && available !== installed) {
                if (availableCard) availableCard.style.display = "flex";
                if (availableVal) availableVal.textContent = available;
                const formattedDate = formatReleaseDate(releaseDate) || formatReleaseDate(new Date().toISOString());
                if (releaseDateVal) {
                    releaseDateVal.textContent = formattedDate;
                }
                if (metaEl) {
                    metaEl.style.display = "flex";
                }
                if (btnApply) {
                    btnApply.style.display = "";
                    if (btnCheck) btnCheck.style.display = "none";
                } else if (btnCheck) {
                    btnCheck.style.display = "";
                }
                if (versionBadge) {
                    const titleText = `available update: ${available}`;
                    versionBadge.title = titleText;
                    versionBadge.setAttribute("aria-label", titleText);
                    const tooltipEl = document.getElementById("peer-version-tooltip");
                    if (tooltipEl) tooltipEl.textContent = titleText;
                    versionBadge.style.display = "inline-flex";
                }
                if (dotBadge) dotBadge.style.display = "inline-block";
                setCheckButtonUpToDate(false);
            } else if (state === "up-to-date") {
                if (availableCard) availableCard.style.display = "none";
                if (availableVal) availableVal.textContent = "";
                if (btnApply) btnApply.style.display = "none";
                if (btnCheck) btnCheck.style.display = "";
                if (versionBadge) versionBadge.style.display = "none";
                if (dotBadge) dotBadge.style.display = "none";
                setCheckButtonUpToDate(true);
            } else {
                if (availableCard) availableCard.style.display = "none";
                if (availableVal) availableVal.textContent = "";
                if (btnApply) btnApply.style.display = "none";
                if (btnCheck) btnCheck.style.display = "";
                if (versionBadge) versionBadge.style.display = "none";
                if (dotBadge) dotBadge.style.display = "none";
                setCheckButtonUpToDate(false);
            }
        } catch (err) {
            if (availableCard) availableCard.style.display = "none";
            if (availableVal) availableVal.textContent = "";
            if (btnApply) btnApply.style.display = "none";
            if (btnCheck) btnCheck.style.display = "";
            setCheckButtonUpToDate(false);
            showUpdatesFeedback(err.message || "Failed to check for updates", "error");
        }
    }

    async function applyPeerUpdate() {
        if (isApplyingUpdate) return;
        const curVer = document.getElementById("updates-installed-val")?.textContent?.trim() || "";
        if (isV1Version(curVer)) {
            disableUpdatesForV1(curVer);
            return;
        }

        const availableVal = document.getElementById("updates-available-val");
        const targetVersion = availableVal ? availableVal.textContent.trim() : "";

        isApplyingUpdate = true;

        const btnApply = document.getElementById("btn-apply-update");
        const btnCheck = document.getElementById("btn-check-update");
        const btnSave = document.getElementById("btn-save-update-config");
        const btnCloseModal = document.getElementById("btn-close-updates-modal");
        const btnCancelModal = document.getElementById("btn-cancel-updates-modal");

        if (btnApply) {
            btnApply.disabled = true;
            btnApply.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Installing update...';
        }
        if (btnCheck) btnCheck.disabled = true;
        if (btnSave) btnSave.disabled = true;
        if (btnCloseModal) btnCloseModal.style.visibility = "hidden";
        if (btnCancelModal) btnCancelModal.disabled = true;

        showUpdatesFeedback("Installing update. Please wait...", "info");

        // Shield sidebar & background sync during update
        window.peersPollingActive = true;

        try {
            const resp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/update`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });
            const data = await resp.json().catch(() => ({}));

            if (!resp.ok || data.ok === false) {
                const errorMsg = data.error || data.message || "Failed to apply update";
                throw new Error(errorMsg);
            }

            // Daemon is now applying new binary and restarting services
            if (btnApply) {
                btnApply.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Reconnecting...';
            }
            showUpdatesFeedback("Restarting service and establishing stable connection...", "info");

            // Initial buffer: wait 7 seconds for daemon to cleanly reload
            await new Promise(r => setTimeout(r, 7000));

            // Multi-pass verification: require 3 consecutive successful health checks
            const pollStart = Date.now();
            const maxPollTimeMs = 90000;
            let consecutivePasses = 0;
            const REQUIRED_PASSES = 3;
            let peerIsBack = false;
            let finalVersion = targetVersion || "";

            while (Date.now() - pollStart < maxPollTimeMs) {
                try {
                    const hResp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/health`);
                    if (hResp.ok) {
                        const hData = await hResp.json().catch(() => ({}));
                        if (hData && (hData.status === 'healthy' || hData.status === 'ok' || hData.version)) {
                            consecutivePasses++;
                            if (hData.version) finalVersion = hData.version;
                            if (typeof hData.uptime === 'number') {
                                startUptimeStopwatch(hData.uptime);
                            }
                            if (consecutivePasses >= REQUIRED_PASSES) {
                                peerIsBack = true;
                                break;
                            }
                        } else {
                            consecutivePasses = 0;
                        }
                    } else {
                        consecutivePasses = 0;
                    }
                } catch {
                    consecutivePasses = 0;
                }
                await new Promise(r => setTimeout(r, 2500));
            }

            if (peerIsBack) {
                isPeerOnline = true;

                if (finalVersion) {
                    const versionEl = document.getElementById("peer-version-display");
                    if (versionEl) versionEl.textContent = finalVersion;
                    const updatesInstalledVal = document.getElementById("updates-installed-val");
                    if (updatesInstalledVal) updatesInstalledVal.textContent = finalVersion;
                }

                // Update header status badge and sidebar to Connected
                const headerBadge = document.getElementById("peer-status-badge-header");
                if (headerBadge) {
                    headerBadge.className = "badge-status badge-online";
                    headerBadge.innerHTML = '<i class="fas fa-circle"></i> Connected';
                }
                const sidebarDot = document.getElementById(`sidebar-dot-${peerId}`);
                if (sidebarDot) {
                    sidebarDot.className = "peer-status-dot online";
                    sidebarDot.title = "Connected";
                }
                const sidebarItem = document.getElementById(`sidebar-peer-${peerId}`);
                if (sidebarItem) {
                    sidebarItem.setAttribute("data-sidebar-online", "true");
                }

                // Hide update available card & badges
                const availableCard = document.getElementById("updates-available-card");
                if (availableCard) availableCard.style.display = "none";
                const badgeEl = document.getElementById("peer-version-badge");
                if (badgeEl) badgeEl.style.display = "none";
                const dotEl = document.getElementById("update-badge-dot");
                if (dotEl) dotEl.style.display = "none";

                if (btnApply) btnApply.style.display = "none";
                if (btnCheck) {
                    btnCheck.style.display = "";
                    btnCheck.disabled = false;
                }

                showUpdatesFeedback("Updated successfully! Peer is online and stable.", "success");
                if (window.showSuccess) window.showSuccess("Updated successfully");
            } else {
                showUpdatesFeedback("Update applied. Peer is continuing startup in the background.", "info");
                if (window.showInfo) window.showInfo("Update applied");
            }
        } catch (err) {
            showUpdatesFeedback(err.message || "Failed to apply update", "error");
            if (window.showError) window.showError(err.message || "Failed to apply update");
        } finally {
            isApplyingUpdate = false;
            window.peersPollingActive = false;
            if (btnApply && btnApply.style.display !== "none") {
                btnApply.disabled = false;
                btnApply.innerHTML = '<i class="fas fa-download"></i> Update now';
            }
            if (btnCheck) btnCheck.disabled = manualCheckUsed;
            updateSaveButtonState();
            if (btnCloseModal) btnCloseModal.style.visibility = "visible";
            if (btnCancelModal) btnCancelModal.disabled = false;
        }
    }

    async function loadAutoUpdateConfig() {
        try {
            const resp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/update/config`);
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) return;

            const toggle = document.getElementById("auto-update-toggle");
            const intervalInp = document.getElementById("update-interval-hours");
            const wrapper = document.getElementById("auto-update-interval-wrapper");

            const enabled = !!data.auto_update_enabled;
            setToggleCheckedNoAnim(toggle, enabled);

            let hours = 12;
            if (data.update_check_interval_hours !== undefined) {
                hours = Math.max(3, Math.round(data.update_check_interval_hours));
            } else if (data.update_check_interval_seconds !== undefined) {
                hours = Math.max(3, Math.round(data.update_check_interval_seconds / 3600));
            }
            if (intervalInp) {
                intervalInp.value = hours;
                intervalInp.disabled = !enabled;
            }
            if (wrapper) {
                if (enabled) wrapper.classList.remove("disabled");
                else wrapper.classList.add("disabled");
            }

            const channel = (data.channel === 'beta') ? 'beta' : 'stable';
            setChannelChipUI(channel);

            initialAutoUpdateEnabled = enabled;
            initialIntervalHours = hours;
            initialChannel = channel;
            hideIntervalError();
            updateSaveButtonState();
        } catch (e) {
            console.error("Error loading auto update config:", e);
        }
    }

    function onAutoUpdateFieldChange() {
        const toggle = document.getElementById("auto-update-toggle");
        const intervalInp = document.getElementById("update-interval-hours");
        const wrapper = document.getElementById("auto-update-interval-wrapper");
        const isChecked = toggle ? toggle.checked : false;

        if (intervalInp) intervalInp.disabled = !isChecked;
        if (wrapper) {
            if (isChecked) wrapper.classList.remove("disabled");
            else wrapper.classList.add("disabled");
        }

        if (!isChecked) {
            hideIntervalError();
        }

        updateSaveButtonState();
    }

    async function saveAutoUpdateConfig() {
        if (isApplyingUpdate) return;
        const btnSave = document.getElementById("btn-save-update-config");
        const toggle = document.getElementById("auto-update-toggle");
        const intervalInp = document.getElementById("update-interval-hours");

        const enabled = toggle ? toggle.checked : false;
        let hours = intervalInp ? parseInt(intervalInp.value, 10) : 12;

        if (enabled && (isNaN(hours) || hours < 3)) {
            showIntervalError("Min 3 hours");
            return;
        }

        if (btnSave) {
            btnSave.disabled = true;
            btnSave.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
        }

        try {
            const intervalSeconds = hours * 3600;
            const resp = await fetch(`${_apiBase}/api/peers/${encodeURIComponent(peerId)}/update/config`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    auto_update_enabled: enabled,
                    update_check_interval_seconds: intervalSeconds
                })
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                throw new Error(data.error || "Failed to save auto-update configuration");
            }

            initialAutoUpdateEnabled = enabled;
            initialIntervalHours = hours;
            showUpdatesFeedback("Auto-update saved", "success");
            if (window.showSuccess) window.showSuccess("Settings saved");
        } catch (err) {
            showUpdatesFeedback(err.message || "Failed to save settings", "error");
            if (window.showError) window.showError(err.message || "Failed to save settings");
        } finally {
            if (btnSave) {
                btnSave.innerHTML = '<i class="fas fa-save"></i> Save changes';
            }
            updateSaveButtonState();
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
    window.toggleSystemLogs = toggleSystemLogs;
    window.openUpdatesModal = openUpdatesModal;
    window.closeUpdatesModal = closeUpdatesModal;
    window.handleUpdatesModalOverlayClick = handleUpdatesModalOverlayClick;
    window.checkPeerUpdate = checkPeerUpdate;
    window.applyPeerUpdate = applyPeerUpdate;
    window.onAutoUpdateFieldChange = onAutoUpdateFieldChange;
    window.onAutoUpdateToggleChange = onAutoUpdateFieldChange;
    window.saveAutoUpdateConfig = saveAutoUpdateConfig;
    window.onChannelChipClick = onChannelChipClick;
})();
