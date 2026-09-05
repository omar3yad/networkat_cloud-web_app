const peerId = window.FIREWALL_CONFIG ? window.FIREWALL_CONFIG.peerId : "";
    const peerName = window.FIREWALL_CONFIG ? window.FIREWALL_CONFIG.peerName : "";
    let isPeerOnline = window.FIREWALL_CONFIG ? window.FIREWALL_CONFIG.isOnline : false;
    let activeTab = 'rules';
    let cachedAddressLists = [];
    let cachedResolverConfig = null;
    let originalUpstreams = [];
    let originalSlug = "";

    function showFriendlyError(err, prefix = "Error") {
        let msg = err.message || err || 'Failed';
        if (typeof msg === 'string') {
            msg = msg.replace(/@alias_([a-zA-Z0-9_-]+)/g, (match, id) => {
                const matched = cachedAddressLists.find(l => String(l.id) === String(id) || String(l.slug) === String(id));
                return matched ? `@${matched.name || matched.slug}` : `@${id}`;
            });
            msg = msg.replace(/alias_([a-zA-Z0-9_-]+)/g, (match, id) => {
                const matched = cachedAddressLists.find(l => String(l.id) === String(id) || String(l.slug) === String(id));
                return matched ? (matched.name || matched.slug) : id;
            });
        }
        alert(msg);
    }

    document.addEventListener('DOMContentLoaded', () => {
        // Auto-refresh periodically if peer is online
        if (isPeerOnline) {
            setInterval(() => {
                // Silent background refresh: no loading view, no table hide,
                // no spinner, and the table only re-renders if data changed.
                fetchRules(true, true);
            }, 10000);
        }

        fetchAddressLists(true).then(() => {
            fetchRules();
        });
        initCustomAutocompletes();
        initFirewallLiveValidation();
    });

    // Toggle ports fields depending on protocol select
    function toggleProtocolFields() {
        const protocol = document.getElementById('ruleProtocol').value;
        const srcPort = document.getElementById('srcPort');
        const dstPort = document.getElementById('dstPort');

        if (protocol === 'any' || protocol === 'icmp') {
            srcPort.value = '';
            srcPort.disabled = true;
            dstPort.value = '';
            dstPort.disabled = true;
            clearFieldError('srcPort');
            clearFieldError('dstPort');
        } else {
            srcPort.disabled = false;
            dstPort.disabled = false;
        }
    }

    let editingRuleId = null;

    // Open/Close modal functions
    function openAddModal() {
        if (!isPeerOnline) return;
        editingRuleId = null;
        document.getElementById('addRuleForm').reset();
        clearAllFieldErrors();
        toggleProtocolFields();

        const charCounter = document.getElementById('ruleName-counter');
        if (charCounter) {
            charCounter.textContent = '0 / 200';
            charCounter.className = 'char-counter';
        }

        updateAddressMultiBtnState('srcIp');
        updateAddressMultiBtnState('dstIp');

        // Update modal title and buttons
        document.querySelector('#addModal h2').textContent = 'Add rule';
        document.getElementById('btn-submit-rule').textContent = 'Add rule';

        // Show Place Before row
        const orderRow = document.getElementById('place-before-row');
        if (orderRow) orderRow.style.display = '';

        // Reset Place Before value to default 'bottom'
        const defaultRadio = document.querySelector('input[name="ruleOrderRadio"][value="bottom"]');
        if (defaultRadio) {
            defaultRadio.checked = true;
            toggleCustomOrderField();
        }

        document.getElementById('addModal').classList.add('active');
    }

    function openEditModal(ruleId) {
        if (!isPeerOnline) return;
        const rule = currentRules.find(r => r.id === ruleId);
        if (!rule) return;

        editingRuleId = ruleId;
        document.getElementById('addRuleForm').reset();
        clearAllFieldErrors();

        // Populate form
        const commentVal = rule.rule_name || '';
        document.getElementById('ruleName').value = commentVal;
        const charCounter = document.getElementById('ruleName-counter');
        if (charCounter) {
            const len = commentVal.length;
            charCounter.textContent = `${len} / 200`;
            charCounter.className = 'char-counter' + (len > 180 ? (len > 200 ? ' error' : ' warning') : '');
        }

        const actLower = (rule.action || '').toLowerCase();
        document.getElementById('ruleAction').value = (actLower === 'accept' || actLower === 'allow') ? 'accept' : 'drop';
        document.getElementById('ruleProtocol').value = rule.protocol || 'any';
        document.getElementById('ruleInterface').value = rule.interface || 'lan';
        document.getElementById('srcIp').value = rule.src_ip === 'Any' ? '' : resolveAliasIdToName(rule.src_ip || '');
        document.getElementById('dstIp').value = rule.dst_ip === 'Any' ? '' : resolveAliasIdToName(rule.dst_ip || '');
        document.getElementById('srcPort').value = rule.src_port || '';
        document.getElementById('dstPort').value = rule.dst_port || '';

        toggleProtocolFields();

        updateAddressMultiBtnState('srcIp');
        updateAddressMultiBtnState('dstIp');

        // Update modal title and buttons
        document.querySelector('#addModal h2').textContent = 'Edit Rule';
        document.getElementById('btn-submit-rule').textContent = 'Save Changes';

        // Hide Place Before row for edit mode
        const orderRow = document.getElementById('place-before-row');
        if (orderRow) orderRow.style.display = 'none';

        document.getElementById('addModal').classList.add('active');
    }

    function closeAddModal() {
        document.getElementById('addModal').classList.remove('active');
        editingRuleId = null;
        clearAllFieldErrors();
    }

    // Fetch rules from backend
    let currentRules = [];
    let initialRulesOrder = '';

    async function fetchRules(forceRefresh = false, silent = false) {
        const loadingView = document.getElementById('loading-view');
        const rulesTable = document.getElementById('rules-table');
        const bannerReorder = document.getElementById('banner-reorder');
        const refreshIcon = document.getElementById('refresh-icon');

        // Silent refresh: table already has rows, so update data in the background
        // without flashing the loading view, hiding the table, or spinning the icon.
        const tbodyEl = document.getElementById('rules-tbody');
        const hasRenderedRows = !!tbodyEl && tbodyEl.querySelector('tr[data-rule-id]');
        const isSilent = silent && hasRenderedRows;
        console.log('[fetchRules]', { forceRefresh, silent, hasRenderedRows: !!hasRenderedRows, isSilent, tbodyChildren: tbodyEl ? tbodyEl.children.length : 'no-tbody' });

        if (!isSilent) {
            if (forceRefresh && refreshIcon) {
                refreshIcon.classList.add('fa-spin');
            }
            loadingView.style.display = 'flex';
            rulesTable.style.display = 'none';
            bannerReorder.style.display = 'none';
        }

        try {
            const url = `/api/peers/${peerId}/firewall/rules` + (forceRefresh ? '?refresh=true' : '');
            const response = await fetch(url);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to fetch firewall rules');
            }

            // Update online status UI dynamically from rules check
            isPeerOnline = data.agent_online;
            const bannerOffline = document.getElementById('banner-offline');
            const addBtn = document.getElementById('add-rule-btn');

            if (!isPeerOnline) {
                bannerOffline.style.display = 'flex';
                addBtn.disabled = true;
            } else {
                bannerOffline.style.display = 'none';
                addBtn.disabled = false;
            }

            currentRules = data.rules || [];
            initialRulesOrder = currentRules.map(r => r.id).join(',');
            renderRulesTable(currentRules, data.agent_online, { diffOnly: isSilent });
            if (!isSilent) {
                deselectAllRules();
            }
        } catch (err) {
            console.error(err);
            // On a silent background refresh, keep the current table intact
            // and just log — don't replace it with an error row.
            if (!isSilent) {
                document.getElementById('rules-tbody').innerHTML = `
                    <tr>
                        <td colspan="13" class="text-center" style="text-align: center; padding: 3rem; color: #ef4444; font-weight: 600;">
                            <i class="fas fa-exclamation-triangle fa-2x mb-3"></i><br>
                            Error loading firewall configuration: ${err.message}
                        </td>
                    </tr>
                `;
            }
        } finally {
            if (!isSilent) {
                loadingView.style.display = 'none';
                const refreshIcon = document.getElementById('refresh-icon');
                if (refreshIcon) {
                    refreshIcon.classList.remove('fa-spin');
                }
                rulesTable.style.display = 'table';
            }
        }
    }

    // Tracks the currently rendered table state so a silent refresh that
    // produced identical data doesn't touch the DOM at all (no flicker).
    let lastRenderedSignature = null;

    // Render rules list dynamically
    function renderRulesTable(rules, isAgentOnline, options = {}) {
        const tbody = document.getElementById('rules-tbody');

        // If nothing visible changed, skip the DOM swap entirely.
        const signature = JSON.stringify({
            agent: isAgentOnline,
            peer: isPeerOnline,
            rules: rules.map(r => [
                r.id, r.order, r.enabled, r.active_on_agent, r.rule_name,
                r.interface, r.src_ip, r.src_port, r.dst_ip, r.dst_port,
                r.protocol, r.action, r.packets, r.bytes
            ])
        });
        if (options.diffOnly && signature === lastRenderedSignature) {
            return;
        }
        lastRenderedSignature = signature;

        if (rules.length === 0) {
            tbody.innerHTML = `
                    <tr>
                        <td colspan="13" style="text-align: center; padding: 4rem; color: var(--nk-text-muted);">
                            <i class="fas fa-shield-alt fa-3x mb-3" style="opacity: 0.35;"></i>
                            <h3>No Rules Configured</h3>
                            <p style="font-size: 0.85rem; margin-top: 0.25rem;">It looks like you don't have any rules</p>
                        </td>
                    </tr>
                `;
            return;
        }

        // Build all rows off-DOM, then swap in one shot so the table never
        // appears empty mid-render.
        const frag = document.createDocumentFragment();
        const tbody_append_target = frag;

        rules.forEach(rule => {
            const tr = document.createElement('tr');
            tr.setAttribute('data-rule-id', rule.id);

            // checkbox column
            const tdCheck = document.createElement('td');
            tdCheck.className = 'cell-check';
            tdCheck.style.textAlign = 'center';
            tdCheck.innerHTML = `<input type="checkbox" class="rule-row-checkbox" data-rule-idx="${rule.id}" onchange="onRuleCheckboxChange()">`;
            tr.appendChild(tdCheck);

            // Drag handle column
            const tdDrag = document.createElement('td');
            tdDrag.className = 'cell-drag';
            tdDrag.style.textAlign = 'center';
            tdDrag.innerHTML = (isPeerOnline && isAgentOnline) ? `<i class="fas fa-grip-vertical drag-handle" title="Drag to reorder"></i>` : '';
            tr.appendChild(tdDrag);

            // Order column
            const tdOrder = document.createElement('td');
            tdOrder.className = 'cell-order';
            tdOrder.style.textAlign = 'center';
            tdOrder.style.fontWeight = '700';
            tdOrder.style.color = 'var(--nk-blue-primary)';
            tdOrder.style.padding = '2px';

            const isOrderEditable = isPeerOnline && isAgentOnline;
            if (isOrderEditable) {
                const ruleIdx = rules.findIndex(r => r.id === rule.id);
                const isFirst = ruleIdx === 0;
                const isLast = ruleIdx === rules.length - 1;
                const displayOrder = rule.order && rule.order !== 9999 ? rule.order : (ruleIdx + 1);

                tdOrder.innerHTML = `
                    <div class="order-controller">
                        <button class="order-arrow-btn up" onclick="moveRuleUp(${rule.id})" title="Move Up" ${isFirst ? 'disabled style="opacity: 0.35; cursor: not-allowed;"' : ''}><i class="fas fa-chevron-up"></i></button>
                        <input type="number" class="order-input" value="${displayOrder}" min="1" max="${rules.length}" onchange="changeRuleOrderDirectly(${rule.id}, this.value)" onkeydown="if(event.key === 'Enter') this.blur();">
                        <button class="order-arrow-btn down" onclick="moveRuleDown(${rule.id})" title="Move Down" ${isLast ? 'disabled style="opacity: 0.35; cursor: not-allowed;"' : ''}><i class="fas fa-chevron-down"></i></button>
                    </div>
                `;
            } else {
                tdOrder.textContent = rule.order && rule.order !== 9999 ? rule.order : '-';
            }
            tr.appendChild(tdOrder);

            // rule comment
            const tdComment = document.createElement('td');
            tdComment.className = 'rule-comment-cell';
            tdComment.style.margin = '0 0 0 -136px';
            tdComment.innerHTML = `<span style="opacity: 0.9;margin: 13px;">${rule.rule_name}</span>`;
            tr.appendChild(tdComment);

            // In Interface (LAN / VPN)
            const tdInterface = document.createElement('td');
            tdInterface.className = 'cell-interface';
            tdInterface.innerHTML = `<span class="badge-ip">${(rule.interface || 'lan').toUpperCase()}</span>`;
            tr.appendChild(tdInterface);

            // Sources
            const tdSources = document.createElement('td');
            tdSources.className = 'cell-sources';
            if (rule.src_ip === 'Any' || !rule.src_ip) {
                tdSources.innerHTML = `<span class="badge-any">Any</span>`;
            } else {
                const displayName = resolveAliasIdToName(rule.src_ip);
                const tooltipText = getAliasTooltip(rule.src_ip);
                tdSources.innerHTML = `<span class="badge-ip" title="${tooltipText}">${displayName}</span>`;
            }
            tr.appendChild(tdSources);

            // Src Port
            const tdSrcPort = document.createElement('td');
            tdSrcPort.className = 'cell-src-port';
            if (rule.src_port === 'Any' || !rule.src_port) {
                tdSrcPort.innerHTML = `<span class="badge-any">Any</span>`;
            } else {
                tdSrcPort.innerHTML = `<span class="badge-ip" title="${rule.src_port}">${rule.src_port}</span>`;
            }
            tr.appendChild(tdSrcPort);

            // Destinations
            const tdDestinations = document.createElement('td');
            tdDestinations.className = 'cell-destinations';
            if (rule.dst_ip === 'Any' || !rule.dst_ip) {
                tdDestinations.innerHTML = `<span class="badge-any">Any</span>`;
            } else {
                const displayName = resolveAliasIdToName(rule.dst_ip);
                const tooltipText = getAliasTooltip(rule.dst_ip);
                tdDestinations.innerHTML = `<span class="badge-ip" title="${tooltipText}">${displayName}</span>`;
            }
            tr.appendChild(tdDestinations);

            // Dst Port
            const tdDstPort = document.createElement('td');
            tdDstPort.className = 'cell-dst-port';
            if (rule.dst_port === 'Any' || !rule.dst_port) {
                tdDstPort.innerHTML = `<span class="badge-any">Any</span>`;
            } else {
                tdDstPort.innerHTML = `<span class="badge-ip" title="${rule.dst_port}">${rule.dst_port}</span>`;
            }
            tr.appendChild(tdDstPort);

            // Services / Protocol & Ports
            const tdServices = document.createElement('td');
            tdServices.className = 'cell-services';
            tdServices.innerHTML = `<span class="badge-ip">${rule.protocol}</span>`;
            tr.appendChild(tdServices);

            // Action (Allow/Drop)
            const tdAction = document.createElement('td');
            tdAction.className = 'cell-action';
            const actionLower = (rule.action || 'accept').toLowerCase();
            if (actionLower === 'accept' || actionLower === 'allow') {
                tdAction.innerHTML = `<span class="badge-action allow">Allow</span>`;
            } else {
                tdAction.innerHTML = `<span class="badge-action drop">Drop</span>`;
            }
            tr.appendChild(tdAction);

            // Traffic Counters
            const tdCounters = document.createElement('td');
            tdCounters.className = 'cell-counters';
            tdCounters.style.fontSize = '0.85rem';
            tdCounters.style.color = 'var(--nk-text-muted)';
            tdCounters.style.fontWeight = '500';

            if (rule.packets !== undefined && rule.packets !== null) {
                const formattedBytes = formatBytes(rule.bytes);
                tdCounters.innerHTML = `<span class="badge-counter"><i class="" style="margin-right: 4px;"></i>${rule.packets} p / ${formattedBytes}</span>`;
            } else {
                tdCounters.innerHTML = `<span style="opacity: 0.5;">-</span>`;
            }
            tr.appendChild(tdCounters);

            // Status Toggle Switch
            const tdStatus = document.createElement('td');
            tdStatus.className = 'cell-enabled';
            const disabledAttr = (!isPeerOnline || !isAgentOnline) ? 'disabled' : '';
            const checkedAttr = rule.enabled ? 'checked' : '';

            // Show warning icon if DB states it's enabled but agent says it's not active
            const syncWarning = (rule.enabled && isAgentOnline && !rule.active_on_agent)
                ? `<i class="fas fa-exclamation-circle sync-warning" title="Rule is enabled in DB but not active on Gateway agent! Toggling will trigger synchronization." style="display: none;"></i>`
                : '';

            tdStatus.innerHTML = `
                    <div class="toggle-wrapper">
                        <label class="switch">
                            <input type="checkbox" onchange="toggleRule(${rule.id}, this)" ${checkedAttr} ${disabledAttr}>
                            <span class="slider"></span>
                        </label>
                        <div class="toggle-spinner" id="spinner-${rule.id}"></div>
                        ${syncWarning}
                    </div>
                `;
            tr.appendChild(tdStatus);

            // Actions Column
            const tdActions = document.createElement('td');
            tdActions.className = 'cell-actions';
            tdActions.style.textAlign = 'center';

            tdActions.innerHTML = `
                    <div style="display: inline-flex; align-items: center; justify-content: center;">
                       <button class="btn-delete" onclick="openEditModal(${rule.id})" ${disabledAttr} title="Edit rule" style="color: var(--nk-text-muted); margin-right: 4px;">
                            <i class="far fa-edit" style="font-size: 16px;"></i>
                        </button>
                        <button class="btn-delete" onclick="deleteRule(${rule.id})" ${disabledAttr} title="Delete rule">
                            <i class="far fa-trash-alt" style="font-size: 16px;"></i>
                        </button>
                    </div>
                `;
            tr.appendChild(tdActions);

            tbody_append_target.appendChild(tr);
        });

        // Atomic swap: clear + insert the fully-built fragment in one paint.
        tbody.replaceChildren(frag);

        // Initialize Drag and Drop hooks
        initDragAndDrop();
    }

    // Move Rule Up locally
    function moveRuleUp(ruleId) {
        const index = currentRules.findIndex(r => r.id === ruleId);
        if (index > 0) {
            const temp = currentRules[index];
            currentRules[index] = currentRules[index - 1];
            currentRules[index - 1] = temp;

            currentRules.forEach((r, i) => r.order = i + 1);
            renderRulesTable(currentRules, isPeerOnline);
            checkOrderChanges();
        }
    }

    // Move Rule Down locally
    function moveRuleDown(ruleId) {
        const index = currentRules.findIndex(r => r.id === ruleId);
        if (index < currentRules.length - 1) {
            const temp = currentRules[index];
            currentRules[index] = currentRules[index + 1];
            currentRules[index + 1] = temp;

            currentRules.forEach((r, i) => r.order = i + 1);
            renderRulesTable(currentRules, isPeerOnline);
            checkOrderChanges();
        }
    }

    // Change rule order directly via input
    function changeRuleOrderDirectly(ruleId, newOrderVal) {
        let newOrder = parseInt(newOrderVal);
        if (isNaN(newOrder) || newOrder < 1) {
            newOrder = 1;
        }
        if (newOrder > currentRules.length) {
            newOrder = currentRules.length;
        }

        const oldIndex = currentRules.findIndex(r => r.id === ruleId);
        if (oldIndex === -1) return;

        const newIndex = newOrder - 1;
        if (oldIndex === newIndex) {
            renderRulesTable(currentRules, isPeerOnline);
            return;
        }

        // Remove from old index and insert at new index
        const [movedRule] = currentRules.splice(oldIndex, 1);
        currentRules.splice(newIndex, 0, movedRule);

        // Update orders contiguous 1..N
        currentRules.forEach((r, i) => r.order = i + 1);

        renderRulesTable(currentRules, isPeerOnline);
        checkOrderChanges();
    }

    // Check if current rules order differs from the initial fetched order
    function checkOrderChanges() {
        const currentOrderStr = currentRules.map(r => r.id).join(',');
        const banner = document.getElementById('banner-reorder');
        if (currentOrderStr !== initialRulesOrder) {
            banner.style.display = 'flex';
        } else {
            banner.style.display = 'none';
        }
    }

    // Submit the reordered rules as a bulk POST
    async function submitReorder() {
        const banner = document.getElementById('banner-reorder');
        const items = currentRules.map((rule, idx) => ({
            id: rule.id,
            order: idx + 1
        }));

        try {
            const response = await fetch(`/api/peers/${peerId}/firewall/rules/reorder`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: items })
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || data.error || data.detail || 'Failed to apply reordering');
            }

            banner.style.display = 'none';
            fetchRules();
        } catch (err) {
            showFriendlyError(err);
        }
    }

    // Drag & Drop Rules handlers
    let dragSrcEl = null;
    let dragStartTarget = null;

    // Track the clicked target element before drag starts
    document.addEventListener('mousedown', function (e) {
        dragStartTarget = e.target;
    }, true);

    function initDragAndDrop() {
        if (!isPeerOnline) return;

        const rows = document.querySelectorAll('#rules-tbody tr');
        rows.forEach(row => {
            if (row.querySelector('.drag-handle')) {
                row.setAttribute('draggable', 'true');

                row.addEventListener('dragstart', handleDragStart, false);
                row.addEventListener('dragenter', handleDragEnter, false);
                row.addEventListener('dragover', handleDragOver, false);
                row.addEventListener('dragleave', handleDragLeave, false);
                row.addEventListener('drop', handleDrop, false);
                row.addEventListener('dragend', handleDragEnd, false);
            }
        });
    }

    function handleDragStart(e) {
        // Only allow dragging if initiated directly from the drag-handle icon
        if (!dragStartTarget || (!dragStartTarget.classList.contains('drag-handle') && !dragStartTarget.closest('.drag-handle'))) {
            e.preventDefault();
            return;
        }
        this.classList.add('dragging');
        dragSrcEl = this;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/html', this.innerHTML);
    }

    function handleDragOver(e) {
        if (e.preventDefault) {
            e.preventDefault();
        }
        e.dataTransfer.dropEffect = 'move';

        const draggingRow = document.querySelector('.dragging');
        const tbody = document.getElementById('rules-tbody');
        const targetRow = this;

        if (targetRow !== draggingRow && targetRow.parentNode === tbody) {
            const rect = targetRow.getBoundingClientRect();
            const next = (e.clientY - rect.top) / (rect.bottom - rect.top) > 0.5;
            tbody.insertBefore(draggingRow, next ? targetRow.nextSibling : targetRow);
        }
        return false;
    }

    function handleDragEnter(e) {
        this.classList.add('over');
    }

    // Remove CSS classes when drag leaves element boundary
    function handleDragLeave(e) {
        this.classList.remove('over');
    }

    function handleDrop(e) {
        if (e.stopPropagation) {
            e.stopPropagation();
        }
        return false;
    }

    function handleDragEnd(e) {
        this.classList.remove('dragging');

        const rows = document.querySelectorAll('#rules-tbody tr');
        rows.forEach(row => {
            row.classList.remove('over');
        });

        const newOrderedRules = [];
        rows.forEach((row, idx) => {
            const ruleId = parseInt(row.getAttribute('data-rule-id'));
            const originalRule = currentRules.find(r => r.id === ruleId);
            if (originalRule) {
                originalRule.order = idx + 1;
                newOrderedRules.push(originalRule);
            }
        });

        currentRules = newOrderedRules;
        renderRulesTable(currentRules, isPeerOnline);
        checkOrderChanges();
    }

    function resolveAliasNamesToIds(value) {
        if (!value) return value;
        const parts = value.split(',').map(p => p.trim()).filter(Boolean);
        const mappedParts = parts.map(part => {
            if (part.startsWith('@')) {
                let name = part.substring(1);
                if (name.startsWith('alias_')) {
                    name = name.substring(6);
                }
                const matched = cachedAddressLists.find(l => l.name === name || l.slug === name || String(l.id) === String(name));
                if (matched) {
                    return `@alias_${matched.id || matched.slug}`;
                }
            }
            return part;
        });
        return mappedParts.join(',');
    }

    function resolveAliasIdToName(value) {
        if (!value) return value;
        const parts = value.split(',').map(p => p.trim()).filter(Boolean);
        const mappedParts = parts.map(part => {
            if (part.startsWith('@')) {
                let id = part.substring(1);
                if (id.startsWith('alias_')) {
                    id = id.substring(6);
                }
                const matched = cachedAddressLists.find(l => String(l.id) === String(id) || String(l.slug) === String(id));
                if (matched) {
                    return `@${matched.name || matched.slug}`;
                }
            }
            return part;
        });
        return mappedParts.join(', ');
    }

    function getAliasTooltip(value) {
        if (!value) return '';
        const parts = value.split(',').map(p => p.trim()).filter(Boolean);
        const tooltipParts = parts.map(part => {
            if (part.startsWith('@')) {
                let id = part.substring(1);
                if (id.startsWith('alias_')) {
                    id = id.substring(6);
                }
                const matched = cachedAddressLists.find(l => String(l.id) === String(id) || String(l.slug) === String(id));
                if (matched) {
                    const addresses = (matched.list || []).map(item => item.address || item.hostname || item.domain || '').filter(Boolean);
                    const desc = matched.comment ? `${matched.comment}` : '';
                    const addrStr = addresses.length > 0 ? `(${addresses.join(', ')})` : '';
                    return desc && addrStr ? `${desc} ${addrStr}` : (desc || addrStr || `@${matched.name || matched.slug}`);
                }
            }
            return part;
        });
        return tooltipParts.join('\n');
    }


    // =========================================================================
    // Real-Time Client-Side Validation Engine (FIREWALL_API Specification)
    // =========================================================================

    function validateCommentInput(value) {
        if (!value || typeof value !== 'string') return { valid: true };
        if (value.length > 200) {
            return { valid: false, error: 'Max 200 characters' };
        }
        return { valid: true };
    }

    function validateAddressInput(value, fieldLabel = 'Address') {
        if (!value || typeof value !== 'string') return { valid: true };
        const trimmed = value.trim();
        if (!trimmed) return { valid: true };

        const parts = trimmed.split(',').map(p => p.trim()).filter(Boolean);
        if (parts.length === 0) return { valid: true };

        if (parts.length > 64) {
            return { valid: false, error: 'Max 64 addresses' };
        }

        const aliasParts = parts.filter(p => p.startsWith('@'));
        if (aliasParts.length > 0) {
            if (parts.length > 1) {
                return { valid: false, error: 'Cannot mix IPs and @alias' };
            }
            if (aliasParts.length > 1) {
                return { valid: false, error: 'Only one alias allowed' };
            }
            const aliasRaw = parts[0];
            let aliasName = aliasRaw.substring(1).trim();
            if (!aliasName || aliasName === 'alias_') {
                return { valid: false, error: 'Invalid alias' };
            }
            let searchName = aliasName.startsWith('alias_') ? aliasName.substring(6) : aliasName;
            const matched = cachedAddressLists.find(l => l.name === searchName || l.slug === searchName || String(l.id) === String(searchName));
            if (matched) {
                if (matched.type === 'web_domain') {
                    return { valid: false, error: 'Web Domain aliases not supported' };
                }
            }
            return { valid: true, normalized: aliasRaw };
        }

        const seen = new Set();
        const normalizedParts = [];
        for (const part of parts) {
            const ipv4Res = parseAndValidateIPv4(part, { requireMask: false, allowMask: true, normalizeSubnet: true });
            if (!ipv4Res.valid) {
                return ipv4Res;
            }

            const lowerVal = ipv4Res.normalized.toLowerCase();
            if (seen.has(lowerVal)) {
                return { valid: false, error: 'Duplicate address' };
            }
            seen.add(lowerVal);
            normalizedParts.push(ipv4Res.normalized);
        }

        return { valid: true, normalized: normalizedParts.join(', ') };
    }

    function validatePortInput(value, fieldLabel = 'Port') {
        if (!value || typeof value !== 'string') return { valid: true };
        const trimmed = value.trim();
        if (!trimmed) return { valid: true };

        if (/\s/.test(value)) {
            return { valid: false, error: 'No spaces allowed' };
        }
        if (value.startsWith(',') || value.endsWith(',') || value.includes(',,')) {
            return { valid: false, error: 'Invalid port format' };
        }

        const parts = value.split(',');
        if (parts.length > 64) {
            return { valid: false, error: 'Max 64 ports' };
        }

        const ranges = [];
        for (const part of parts) {
            if (!part) {
                return { valid: false, error: 'Invalid port' };
            }
            if (part.includes('-')) {
                const rangeParts = part.split('-');
                if (rangeParts.length !== 2 || !rangeParts[0] || !rangeParts[1]) {
                    return { valid: false, error: 'Invalid port range' };
                }
                if (!/^\d+$/.test(rangeParts[0]) || !/^\d+$/.test(rangeParts[1])) {
                    return { valid: false, error: 'Invalid port range' };
                }
                const lo = parseInt(rangeParts[0], 10);
                const hi = parseInt(rangeParts[1], 10);
                if (lo < 1 || lo > 65535 || hi < 1 || hi > 65535 || lo >= hi) {
                    return { valid: false, error: 'Invalid port range (1-65535)' };
                }
                ranges.push({ lo, hi, raw: part });
            } else {
                if (!/^\d+$/.test(part)) {
                    return { valid: false, error: 'Invalid port' };
                }
                const port = parseInt(part, 10);
                if (port < 1 || port > 65535) {
                    return { valid: false, error: 'Invalid port (1-65535)' };
                }
                ranges.push({ lo: port, hi: port, raw: part });
            }
        }

        // Check for overlaps and duplicates
        for (let i = 0; i < ranges.length; i++) {
            for (let j = i + 1; j < ranges.length; j++) {
                const r1 = ranges[i];
                const r2 = ranges[j];
                if (Math.max(r1.lo, r2.lo) <= Math.min(r1.hi, r2.hi)) {
                    return { valid: false, error: 'Duplicate or overlapping port' };
                }
            }
        }

        return { valid: true };
    }

    function setFieldError(inputId, errorMsg) {
        const input = document.getElementById(inputId);
        const errorDiv = document.getElementById(`${inputId}-error`);
        const wrapper = document.getElementById(`${inputId}-wrapper`);

        if (wrapper) {
            wrapper.classList.add('is-invalid');
        } else if (input) {
            input.classList.add('is-invalid');
        }

        if (errorDiv) {
            errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${errorMsg}`;
            errorDiv.style.display = 'flex';
        }
    }

    function clearFieldError(inputId) {
        const input = document.getElementById(inputId);
        const errorDiv = document.getElementById(`${inputId}-error`);
        const wrapper = document.getElementById(`${inputId}-wrapper`);

        if (wrapper) {
            wrapper.classList.remove('is-invalid');
        }
        if (input) {
            input.classList.remove('is-invalid');
        }
        if (errorDiv) {
            errorDiv.textContent = '';
            errorDiv.style.display = 'none';
        }
    }

    function clearAllFieldErrors() {
        ['ruleName', 'srcIp', 'dstIp', 'srcPort', 'dstPort', 'ruleOrderCustomInput'].forEach(id => {
            clearFieldError(id);
        });
    }

    function initFirewallLiveValidation() {
        const ruleName = document.getElementById('ruleName');
        const charCounter = document.getElementById('ruleName-counter');
        if (ruleName) {
            ruleName.addEventListener('input', () => {
                const len = ruleName.value.length;
                if (charCounter) {
                    charCounter.textContent = `${len} / 200`;
                    charCounter.className = 'char-counter' + (len > 180 ? (len > 200 ? ' error' : ' warning') : '');
                }
                const res = validateCommentInput(ruleName.value);
                if (!res.valid) {
                    setFieldError('ruleName', res.error);
                } else {
                    clearFieldError('ruleName');
                }
            });
        }

        const srcIp = document.getElementById('srcIp');
        if (srcIp) {
            srcIp.addEventListener('input', () => {
                const res = validateAddressInput(srcIp.value, 'Source Address');
                if (!res.valid) {
                    setFieldError('srcIp', res.error);
                } else {
                    clearFieldError('srcIp');
                }
            });
        }

        const dstIp = document.getElementById('dstIp');
        if (dstIp) {
            dstIp.addEventListener('input', () => {
                const res = validateAddressInput(dstIp.value, 'Destination Address');
                if (!res.valid) {
                    setFieldError('dstIp', res.error);
                } else {
                    clearFieldError('dstIp');
                }
            });
        }

        const srcPort = document.getElementById('srcPort');
        if (srcPort) {
            srcPort.addEventListener('input', () => {
                const protocol = document.getElementById('ruleProtocol').value;
                if (protocol === 'any' || protocol === 'icmp') {
                    clearFieldError('srcPort');
                    return;
                }
                const res = validatePortInput(srcPort.value, 'Source Port');
                if (!res.valid) {
                    setFieldError('srcPort', res.error);
                } else {
                    clearFieldError('srcPort');
                }
            });
        }

        const dstPort = document.getElementById('dstPort');
        if (dstPort) {
            dstPort.addEventListener('input', () => {
                const protocol = document.getElementById('ruleProtocol').value;
                if (protocol === 'any' || protocol === 'icmp') {
                    clearFieldError('dstPort');
                    return;
                }
                const res = validatePortInput(dstPort.value, 'Destination Port');
                if (!res.valid) {
                    setFieldError('dstPort', res.error);
                } else {
                    clearFieldError('dstPort');
                }
            });
        }

        const customOrderInput = document.getElementById('ruleOrderCustomInput');
        if (customOrderInput) {
            customOrderInput.addEventListener('input', () => {
                const val = parseInt(customOrderInput.value);
                if (isNaN(val) || val < 1) {
                    setFieldError('ruleOrderCustomInput', 'Order position must be at least 1.');
                } else {
                    clearFieldError('ruleOrderCustomInput');
                }
            });
        }
    }

    // Add Rule Form Submit with Comprehensive Frontend Guard
    async function submitAddRule(e) {
        e.preventDefault();
        clearAllFieldErrors();

        const btnSubmit = document.getElementById('btn-submit-rule');

        const rule_name = document.getElementById('ruleName').value.trim();
        const action = document.getElementById('ruleAction').value;
        const protocol = document.getElementById('ruleProtocol').value;
        const iface = document.getElementById('ruleInterface').value;
        const src_ip = document.getElementById('srcIp').value.trim();
        const dst_ip = document.getElementById('dstIp').value.trim();
        const src_port = document.getElementById('srcPort').value.trim();
        const dst_port = document.getElementById('dstPort').value.trim();

        let hasError = false;
        let firstInvalidInputId = null;

        // 1. Validate Comment / Name
        const nameRes = validateCommentInput(rule_name);
        if (!nameRes.valid) {
            setFieldError('ruleName', nameRes.error);
            hasError = true;
            if (!firstInvalidInputId) firstInvalidInputId = 'ruleName';
        }

        // 2. Validate Source Address
        const srcRes = validateAddressInput(src_ip, 'Source Address');
        if (!srcRes.valid) {
            setFieldError('srcIp', srcRes.error);
            hasError = true;
            if (!firstInvalidInputId) firstInvalidInputId = 'srcIp';
        }

        // 3. Validate Destination Address
        const dstRes = validateAddressInput(dst_ip, 'Destination Address');
        if (!dstRes.valid) {
            setFieldError('dstIp', dstRes.error);
            hasError = true;
            if (!firstInvalidInputId) firstInvalidInputId = 'dstIp';
        }

        // 4. Validate Ports (only if protocol is not ICMP/ANY)
        if (protocol !== 'any' && protocol !== 'icmp') {
            const srcPortRes = validatePortInput(src_port, 'Source Port');
            if (!srcPortRes.valid) {
                setFieldError('srcPort', srcPortRes.error);
                hasError = true;
                if (!firstInvalidInputId) firstInvalidInputId = 'srcPort';
            }

            const dstPortRes = validatePortInput(dst_port, 'Destination Port');
            if (!dstPortRes.valid) {
                setFieldError('dstPort', dstPortRes.error);
                hasError = true;
                if (!firstInvalidInputId) firstInvalidInputId = 'dstPort';
            }
        } else {
            if (src_port || dst_port) {
                setFieldError('srcPort', 'Ports are not allowed with protocol ICMP or ANY');
                setFieldError('dstPort', 'Ports are not allowed with protocol ICMP or ANY');
                hasError = true;
                if (!firstInvalidInputId) firstInvalidInputId = 'srcPort';
            }
        }

        // 5. Validate Custom Order
        const radioElem = document.querySelector('input[name="ruleOrderRadio"]:checked');
        const selectVal = radioElem ? radioElem.value : 'bottom';
        if (selectVal === 'custom' && editingRuleId === null) {
            const customOrderVal = parseInt(document.getElementById('ruleOrderCustomInput').value);
            if (isNaN(customOrderVal) || customOrderVal < 1) {
                setFieldError('ruleOrderCustomInput', 'Please enter a valid order number (1 or higher).');
                hasError = true;
                if (!firstInvalidInputId) firstInvalidInputId = 'ruleOrderCustomInput';
            }
        }

        if (hasError) {
            if (firstInvalidInputId) {
                const el = document.getElementById(firstInvalidInputId);
                if (el) el.focus();
            }
            return;
        }

        btnSubmit.disabled = true;

        try {
            let url = `/api/peers/${peerId}/firewall/rules`;
            let method = 'POST';

            const normalizedSrc = (srcRes && srcRes.normalized !== undefined) ? srcRes.normalized : src_ip;
            const normalizedDst = (dstRes && dstRes.normalized !== undefined) ? dstRes.normalized : dst_ip;

            const payload = {
                rule_name,
                action,
                protocol,
                interface: iface,
                src_ip: resolveAliasNamesToIds(normalizedSrc) || null,
                dst_ip: resolveAliasNamesToIds(normalizedDst) || null,
                src_port: (protocol === 'any' || protocol === 'icmp') ? null : (src_port || null),
                dst_port: (protocol === 'any' || protocol === 'icmp') ? null : (dst_port || null)
            };

            if (editingRuleId !== null) {
                url = `/api/peers/${peerId}/firewall/rules/${editingRuleId}`;
                method = 'PUT';
            } else {
                let orderVal = selectVal;
                if (selectVal === 'custom') {
                    orderVal = document.getElementById('ruleOrderCustomInput').value.trim();
                }
                orderVal = orderVal.toLowerCase();
                let finalOrder = null;
                if (orderVal === 'first') {
                    finalOrder = 1;
                } else if (orderVal === 'bottom' || orderVal === '') {
                    finalOrder = null;
                } else {
                    const num = parseInt(orderVal);
                    if (!isNaN(num)) {
                        if (num > currentRules.length) {
                            finalOrder = null; // bottom
                        } else {
                            finalOrder = num;
                        }
                    } else {
                        finalOrder = null;
                    }
                }
                payload.order = finalOrder;
            }

            const response = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || 'Failed to apply firewall rule');
            }

            closeAddModal();
            fetchRules();
        } catch (err) {
            showFriendlyError(err);
        } finally {
            btnSubmit.disabled = false;
        }
    }

    // Toggle VPN-Only Mode
    async function toggleVpnOnly(checkbox) {
        const action = checkbox.checked ? 'on' : 'off';
        const statusText = document.getElementById('vpn-only-text');

        checkbox.disabled = true;

        try {
            const response = await fetch(`/api/peers/${peerId}/vpn-only`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ operation: action })
            });

            const data = await response.json();

            if (response.ok && (data.ok === true || data.status === 'success')) {
                if (statusText) {
                    statusText.innerText = action.toUpperCase();
                    if (action === 'on') {
                        statusText.style.color = '#107c10';
                    } else {
                        statusText.style.color = 'var(--nk-text-muted)';
                    }
                }
            } else {
                alert(`Failed to set VPN-Only mode: ${data.error || data.detail || 'Unknown error'}`);
                checkbox.checked = !checkbox.checked;
            }
        } catch (err) {
            console.error('VPN-Only update error:', err);
            alert('Network error while toggling VPN-Only mode.');
            checkbox.checked = !checkbox.checked;
        } finally {
            checkbox.disabled = false;
        }
    }

    // Toggle rule active status
    async function toggleRule(ruleId, checkbox) {
        const spinner = document.getElementById(`spinner-${ruleId}`);
        checkbox.disabled = true;
        spinner.style.display = 'block';

        try {
            const response = await fetch(`/api/peers/${peerId}/firewall/rules/${ruleId}/toggle`, {
                method: 'POST'
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to toggle rule state');
            }

            checkbox.checked = data.enabled;

            // Update the local cached rules list in-place
            const rule = currentRules.find(r => r.id === ruleId);
            if (rule) {
                rule.enabled = data.enabled;
            }
        } catch (err) {
            showFriendlyError(err, "Toggle Error");
            checkbox.checked = !checkbox.checked; // revert
        } finally {
            checkbox.disabled = false;
            spinner.style.display = 'none';
        }
    }

    // Delete Rule
    async function deleteRule(ruleId) {
        if (!confirm('Are you sure you want to delete this firewall rule permanently?')) {
            return;
        }

        const row = document.querySelector(`tr[data-rule-id="${ruleId}"]`);
        const btnDel = row ? row.querySelector('.btn-delete') : null;
        if (btnDel) btnDel.disabled = true;

        try {
            const response = await fetch(`/api/peers/${peerId}/firewall/rules/${ruleId}`, {
                method: 'DELETE'
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to delete rule');
            }

            fetchRules();
        } catch (err) {
            showFriendlyError(err, "Delete Error");
            if (btnDel) btnDel.disabled = false;
        }
    }

    // Toggle all rule checkboxes
    function toggleSelectAllRules(masterCheckbox) {
        const checkboxes = document.querySelectorAll('.rule-row-checkbox');
        checkboxes.forEach(cb => {
            cb.checked = masterCheckbox.checked;
        });
        onRuleCheckboxChange();
    }

    // Handle single row checkbox state change
    function onRuleCheckboxChange() {
        const checkboxes = document.querySelectorAll('.rule-row-checkbox');
        const selectedCount = Array.from(checkboxes).filter(cb => cb.checked).length;

        // Update master checkbox state
        const masterCheckbox = document.getElementById('select-all-rules');
        if (masterCheckbox) {
            masterCheckbox.checked = selectedCount === checkboxes.length && checkboxes.length > 0;
        }

        // Show/hide floating actions bar
        const floatingBar = document.getElementById('bulk-action-bar');
        const countBadge = document.getElementById('selected-rules-count');
        if (floatingBar && countBadge) {
            countBadge.textContent = `${selectedCount} selected`;
            if (selectedCount > 0) {
                floatingBar.style.display = 'block';
                // Wait a tick for display:block to register, then trigger animation class
                setTimeout(() => floatingBar.classList.add('show'), 10);
            } else {
                floatingBar.classList.remove('show');
                // Wait for animation to finish before setting display none
                setTimeout(() => {
                    if (!floatingBar.classList.contains('show')) {
                        floatingBar.style.display = 'none';
                    }
                }, 300);
            }
        }
    }

    // Deselect all checkboxes and hide bulk actions bar
    function deselectAllRules() {
        const masterCheckbox = document.getElementById('select-all-rules');
        if (masterCheckbox) masterCheckbox.checked = false;

        const checkboxes = document.querySelectorAll('.rule-row-checkbox');
        checkboxes.forEach(cb => cb.checked = false);

        onRuleCheckboxChange();
    }

    // Send bulk action POST request to backend
    async function applyBulkAction(action) {
        const checkboxes = document.querySelectorAll('.rule-row-checkbox');
        const selectedIds = Array.from(checkboxes)
            .filter(cb => cb.checked)
            .map(cb => parseInt(cb.getAttribute('data-rule-idx')));

        if (selectedIds.length === 0) return;

        if (action === 'delete') {
            if (!confirm(`Are you sure you want to delete these ${selectedIds.length} selected rules permanently?`)) {
                return;
            }
        }

        // Disable buttons inside floating bar while processing
        const buttons = document.querySelectorAll('.bulk-floating-bar .bulk-btn');
        buttons.forEach(btn => btn.disabled = true);

        try {
            const response = await fetch(`/api/peers/${peerId}/firewall/rules/bulk`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action, rule_ids: selectedIds })
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `Failed to perform bulk ${action} action`);
            }

            // Reload rules to reflect updates
            fetchRules();
        } catch (err) {
            showFriendlyError(err, "Bulk Action Error");
        } finally {
            buttons.forEach(btn => btn.disabled = false);
        }
    }

    // Reset Traffic Counter
    async function resetCounter(ruleId) {
        if (!confirm('Are you sure you want to reset the traffic counter for this rule?')) {
            return;
        }

        try {
            const response = await fetch(`/api/peers/${peerId}/firewall/rules/${ruleId}/reset-counter`, {
                method: 'POST'
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || 'Failed to reset counter');
            }

            fetchRules();
        } catch (err) {
            showFriendlyError(err, "Error resetting counter");
        }
    }

    // Helper to format bytes
    function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        if (!bytes) return '-';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    // Client-side rule filtering
    function filterRulesTable() {
        const searchVal = document.getElementById('search-input').value.toLowerCase();
        const rows = document.querySelectorAll('#rules-tbody tr');

        rows.forEach(row => {
            // If it is a full width loading/error column
            if (row.cells.length === 1) return;

            const name = row.cells[3].textContent.toLowerCase();
            const src = row.cells[5].textContent.toLowerCase();
            const dst = row.cells[6].textContent.toLowerCase();
            const svc = row.cells[7].textContent.toLowerCase();

            if (name.includes(searchVal) || src.includes(searchVal) || dst.includes(searchVal) || svc.includes(searchVal)) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    }
    // Tab Navigation
    function switchTab(tab) {
        activeTab = tab;
        localStorage.setItem('firewall_active_tab', tab);
        const tabRules = document.getElementById('tab-rules');
        const tabLists = document.getElementById('tab-lists');
        const rulesContent = document.getElementById('rules-tab-content');
        const listsContent = document.getElementById('lists-tab-content');

        if (tab === 'rules') {
            tabRules.classList.add('active');
            tabLists.classList.remove('active');
            rulesContent.style.display = 'block';
            listsContent.style.display = 'none';
            fetchRules();
        } else {
            tabRules.classList.remove('active');
            tabLists.classList.add('active');
            rulesContent.style.display = 'none';
            listsContent.style.display = 'block';
            fetchAddressLists();
        }
    }

    // Fetch Aliases from backend proxy
    async function fetchAddressLists(silent = false) {
        const loadingView = document.getElementById('loading-lists-view');
        const listsTable = document.getElementById('lists-table');

        if (!silent) {
            loadingView.style.display = 'flex';
            listsTable.style.display = 'none';
        }

        try {
            const response = await fetch(`/api/peers/${peerId}/aliases`);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || data.detail || 'Failed to fetch address lists');
            }

            cachedAddressLists = data.lists || [];
            cachedAddressLists.forEach(alias => {
                if (!alias.slug && alias.id) {
                    alias.slug = alias.id;
                }
            });
            renderAddressListsTable(cachedAddressLists);
            populateAliasDropdowns();

            // Re-render rules to map raw IDs to friendly names if rules are already loaded
            if (typeof currentRules !== 'undefined' && currentRules && currentRules.length > 0) {
                renderRulesTable(currentRules, isPeerOnline);
            }
        } catch (err) {
            console.error(err);
            if (!silent) {
                document.getElementById('lists-tbody').innerHTML = `
                        <tr>
                            <td colspan="6" class="text-center" style="text-align: center; padding: 3rem; color: #ef4444; font-weight: 600;">
                                <i class="fas fa-exclamation-triangle fa-2x mb-3"></i><br>
                                Error loading address lists: ${err.message}
                            </td>
                        </tr>
                    `;
            }
        } finally {
            if (!silent) {
                loadingView.style.display = 'none';
                listsTable.style.display = 'table';
            }
        }
    }

    // Render Aliases Table
    function renderAddressListsTable(lists) {
        const tbody = document.getElementById('lists-tbody');
        if (!tbody) return;   // Aliases tab table not present on this page
        tbody.innerHTML = '';

        if (lists.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align: center; padding: 4rem; color: var(--nk-text-muted);">
                        <i class="fas fa-list fa-3x mb-3" style="opacity: 0.35;"></i>
                        <h3>No Aliases Configured</h3>
                        <p style="font-size: 0.85rem; margin-top: 0.25rem;">Create an alias to begin.</p>
                    </td>
                </tr>
            `;
            return;
        }

        lists.forEach(list => {
            const tr = document.createElement('tr');
            tr.setAttribute('data-list-slug', list.slug);
            tr.setAttribute('data-list-type', list.type || 'normal');

            // Comment (above the row)
            const tdComment = document.createElement('td');
            tdComment.className = 'alias-comment-cell';
            tdComment.innerHTML = `<span style="opacity: 0.9;">${list.comment || ''}</span>`;
            tr.appendChild(tdComment);

            // Name/Slug with count badge next to it
            const tdSlug = document.createElement('td');
            tdSlug.className = 'cell-name';
            tdSlug.style.fontWeight = '700';
            const items = list.list || [];
            tdSlug.innerHTML = `
                <div style="display: inline-flex; align-items: center; gap: 8px;">
                    <span>${list.name || list.slug}</span>
                    <span onclick="openEditListModal('${list.slug}')" style="font-weight: 700; color: var(--nk-blue-primary); background: #e0f2fe; padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; cursor: pointer;" title="Click to Edit Alias">${items.length}</span>
                </div>
            `;
            tr.appendChild(tdSlug);

            // Type Column
            const tdType = document.createElement('td');
            tdType.className = 'cell-type';
            const isWebDomainType = list.type === 'web_domain';
            const typeBadgeStyle = isWebDomainType
                ? 'background: #fef3c7; color: #b45309; border: 1px solid #fde68a;'
                : 'background: #e6e6e6; color: #334155; border: 1px solid #e6e6e6;';
            const typeBadgeLabel = isWebDomainType ? 'Web domain' : 'Normal';
            tdType.innerHTML = `<span class="badge-ip" style="font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 4px; ${typeBadgeStyle}">${typeBadgeLabel}</span>`;
            tr.appendChild(tdType);

            // Addresses Preview
            const tdAddresses = document.createElement('td');
            tdAddresses.className = 'cell-addresses';
            const maxPreview = 2;
            const previewHtml = items.slice(0, maxPreview).map(item => {
                const val = item.hostname || item.domain || item.address;
                const isDomain = !!item.domain;
                const commentText = item.comment ? item.comment : '';
                const resolvedText = item.resolved_addresses && item.resolved_addresses.length > 0
                    ? `Resolved IPs: ${item.resolved_addresses.join(', ')}`
                    : 'unresolved';

                const hoverTitle = commentText && resolvedText
                    ? `${commentText}\n${resolvedText}`
                    : (commentText || resolvedText);

                if (item.hostname || item.domain) {
                    const colorStyle = isDomain
                        ? 'background: #fef3c7; color: #b45309; border: 1px solid #fde68a;'
                        : 'background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd;';
                    return `<span class="badge-ip" title="${hoverTitle}" style="margin: 2px; ${colorStyle}">${val}</span>`;
                }
                return `<span class="badge-ip" title="${commentText}" style="margin: 2px;">${item.address}</span>`;
            }).join(' ');

            const remaining = items.length - maxPreview;
            const moreHtml = remaining > 0 ? `<span class="badge-any" style="font-size: 0.8rem; margin-left: 6px;">+${remaining} more</span>` : '';

            tdAddresses.innerHTML = `<div style="display: flex; flex-wrap: wrap; align-items: center;">${previewHtml}${moreHtml}</div>`;
            tr.appendChild(tdAddresses);

            // Created
            const tdCreated = document.createElement('td');
            tdCreated.className = 'cell-created';
            tdCreated.style.color = 'var(--nk-text-muted)';
            tdCreated.style.fontSize = '0.85rem';
            tdCreated.textContent = list.created ? new Date(list.created).toLocaleString('en-GB') : '-';
            tr.appendChild(tdCreated);

            // Updated
            const tdUpdated = document.createElement('td');
            tdUpdated.className = 'cell-updated';
            tdUpdated.style.color = 'var(--nk-text-muted)';
            tdUpdated.style.fontSize = '0.85rem';
            tdUpdated.textContent = list.updated ? new Date(list.updated).toLocaleString('en-GB') : '-';
            tr.appendChild(tdUpdated);

            // Actions Column
            const tdActions = document.createElement('td');
            tdActions.className = 'cell-actions';
            tdActions.style.textAlign = 'center';
            const disabledAttr = !isPeerOnline ? 'disabled' : '';

            tdActions.innerHTML = `
                <div style="display: flex; gap: 0.5rem; justify-content: center; align-items: center;">
                    <a href="/peers/${peerId}/filtering?name=${encodeURIComponent(peerName)}&scope=alias&alias=${list.slug}" class="btn-delete btn-edit-action" title="DNS Filter" style="display: flex; align-items: center; justify-content: center; text-decoration: none;">
                        <i class="fas fa-filter"></i>
                    </a>
                    <button class="btn-delete btn-edit-action" onclick="openEditListModal('${list.slug}')" ${disabledAttr} title="Edit alias">
                        <i class="far fa-edit"></i>
                    </button>
                    <button class="btn-delete" onclick="deleteAddressList('${list.slug}')" ${disabledAttr} title="Delete alias">
                        <i class="far fa-trash-alt"></i>
                    </button>
                </div>
            `;
            tr.appendChild(tdActions);

            tbody.appendChild(tr);
        });
    }

    // Open Add Alias Modal
    function openAddListModal() {
        if (!isPeerOnline) return;
        document.getElementById('listModalTitle').textContent = 'Add alias';
        document.getElementById('listActionType').value = 'add';
        document.getElementById('btn-submit-list').textContent = 'Add alias';
        document.getElementById('listSlug').value = '';
        document.getElementById('listSlug').disabled = false;
        document.getElementById('listComment').value = '';
        document.getElementById('listType').value = 'normal';
        document.getElementById('listType').disabled = false;
        document.getElementById('address-rows-container').innerHTML = '';
        addAddressRow();
        document.getElementById('listModal').classList.add('active');
    }

    // Open Edit Alias Modal
    function openEditListModal(slug) {
        if (!isPeerOnline) return;
        const listObj = cachedAddressLists.find(l => l.slug === slug);
        if (!listObj) return;

        const isNewAgent = cachedAddressLists.length > 0 && cachedAddressLists.some(l => l.id !== undefined);

        document.getElementById('listModalTitle').textContent = `Edit Alias`
        document.getElementById('listActionType').value = 'edit';
        document.getElementById('btn-submit-list').textContent = 'Save Changes';
        originalSlug = slug;
        document.getElementById('listSlug').value = listObj.name || slug;
        document.getElementById('listSlug').disabled = !isNewAgent; // Disabled for old agents that don't support renaming
        document.getElementById('listComment').value = listObj.comment || '';
        // type is immutable after creation - show it, but disabled
        document.getElementById('listType').value = listObj.type || 'normal';
        document.getElementById('listType').disabled = true;

        const container = document.getElementById('address-rows-container');
        container.innerHTML = '';

        if (listObj.list && listObj.list.length > 0) {
            listObj.list.forEach(item => {
                const val = item.address || item.hostname || item.domain || '';
                addAddressRow(val, item.comment || '');
            });
        } else {
            addAddressRow();
        }

        document.getElementById('listModal').classList.add('active');
    }

    // Reflect selected type in the address-row placeholder
    function onListTypeChange() {
        const type = document.getElementById('listType').value;
        const placeholder = type === 'web_domain'
            ? 'Domain or pattern (e.g. facebook.com, *.doubleclick.net)'
            : 'IP Address, CIDR or Hostname (e.g. 192.168.10.5, server.local)';
        document.querySelectorAll('#address-rows-container .addr-input').forEach(input => {
            input.placeholder = placeholder;
        });
    }

    // Add dynamically a row of inputs for addresses
    function addAddressRow(address = '', comment = '') {
        const safeComment = comment || '';
        const typeSelect = document.getElementById('listType');
        const currentType = typeSelect ? typeSelect.value : 'normal';
        const placeholder = currentType === 'web_domain'
            ? 'Domain or pattern (e.g. facebook.com, *.doubleclick.net)'
            : 'IP Address, CIDR or Hostname (e.g. 192.168.10.5, server.local)';
        const container = document.getElementById('address-rows-container');
        const rowDiv = document.createElement('div');
        rowDiv.className = 'address-row';
        rowDiv.style.display = 'flex';
        rowDiv.style.gap = '0.75rem';
        rowDiv.style.marginBottom = '0.75rem';
        rowDiv.style.alignItems = 'center';

        rowDiv.innerHTML = `
                <div style="flex: 1;">
                    <input type="text" placeholder="${placeholder}" class="addr-input" required value="${address}" style="width: 100%; padding: 0.5rem 0.75rem; border: 1px solid var(--nk-border); border-radius: var(--nk-radius-sm); font-size: 0.88rem;">
                </div>
                <div style="flex: 1;">
                    <input type="text" placeholder="Comment (e.g. Dev Server)" class="addr-comment" value="${safeComment}" style="width: 100%; padding: 0.5rem 0.75rem; border: 1px solid var(--nk-border); border-radius: var(--nk-radius-sm); font-size: 0.88rem;" maxlength="200">
                </div>
                <button type="button" class="btn-delete" onclick="removeAddressRow(this)" style="padding: 0.5rem; display: flex; align-items: center; justify-content: center; height: 38px; width: 38px;">
                    <i class="far fa-trash-alt"></i>
                </button>
            `;
        container.appendChild(rowDiv);
    }

    function removeAddressRow(button) {
        const row = button.closest('.address-row');
        if (row) row.remove();
    }

    function closeListModal() {
        document.getElementById('listModal').classList.remove('active');
    }

    // Submit Alias
    async function submitAddressList(e) {
        e.preventDefault();
        const btnSubmit = document.getElementById('btn-submit-list');
        btnSubmit.disabled = true;

        const actionType = document.getElementById('listActionType').value;
        const slug = document.getElementById('listSlug').value.trim();
        const comment = document.getElementById('listComment').value.trim();
        const listType = document.getElementById('listType').value;

        const addrInputs = document.querySelectorAll('#address-rows-container .addr-input');
        const commentInputs = document.querySelectorAll('#address-rows-container .addr-comment');

        const entries = [];
        for (let i = 0; i < addrInputs.length; i++) {
            const val = addrInputs[i].value.trim();
            const addrComment = commentInputs[i].value.trim() || null;
            if (val) {
                if (listType === 'web_domain') {
                    entries.push({
                        domain: val,
                        comment: addrComment
                    });
                } else {
                    if (/^[0-9]/.test(val[0])) {
                        const ipv4Res = parseAndValidateIPv4(val, { requireMask: false, allowMask: true, normalizeSubnet: true });
                        entries.push({
                            address: ipv4Res.valid ? ipv4Res.normalized : val,
                            comment: addrComment
                        });
                    } else {
                        entries.push({
                            hostname: val,
                            comment: addrComment
                        });
                    }
                }
            }
        }

        if (entries.length === 0) {
            alert("At least 1 item required");
            btnSubmit.disabled = false;
            return;
        }

        const isNewAgent = cachedAddressLists.length > 0 && cachedAddressLists.some(l => l.id !== undefined);

        if (actionType === 'edit') {
            if (isNewAgent) {
                try {
                    // 1. Update name/comment via PATCH
                    const patchResp = await fetch(`/api/peers/${peerId}/aliases/${originalSlug}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: slug, comment: comment })
                    });
                    if (!patchResp.ok) {
                        const data = await patchResp.json();
                        throw new Error(data.message || data.error || data.detail || 'Failed to save');
                    }

                    // 2. Update address list via PUT
                    const putResp = await fetch(`/api/peers/${peerId}/aliases/${originalSlug}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ list: entries })
                    });
                    if (!putResp.ok) {
                        const data = await putResp.json();
                        throw new Error(data.message || data.error || data.detail || 'Failed to save');
                    }

                    closeListModal();
                    fetchAddressLists();
                    alert("Saved successfully");
                } catch (err) {
                    showFriendlyError(err);
                } finally {
                    btnSubmit.disabled = false;
                }
            } else {
                // Backward compatibility: Old Agent PUT structure
                const payload = {
                    slug: originalSlug,
                    comment: comment,
                    list: entries
                };
                try {
                    const response = await fetch(`/api/peers/${peerId}/aliases/${originalSlug}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await response.json();
                    if (!response.ok) {
                        throw new Error(data.message || data.error || data.detail || 'Failed to save');
                    }
                    closeListModal();
                    fetchAddressLists();
                    alert("Saved successfully");
                } catch (err) {
                    showFriendlyError(err);
                } finally {
                    btnSubmit.disabled = false;
                }
            }
            return;
        }

        // POST /aliases (add list) - Send both name and slug to support both old and new agent schemas
        const payload = {
            name: slug,
            slug: slug,
            comment: comment,
            type: listType,
            list: entries
        };

        try {
            const response = await fetch(`/api/peers/${peerId}/aliases`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || data.error || data.detail || 'Failed to save');
            }

            closeListModal();
            fetchAddressLists();
            alert("Saved successfully");
        } catch (err) {
            showFriendlyError(err);
        } finally {
            btnSubmit.disabled = false;
        }
    }

    // Delete Alias
    async function deleteAddressList(slug) {
        if (!confirm(`Delete alias "${slug}"?`)) {
            return;
        }

        try {
            const response = await fetch(`/api/peers/${peerId}/aliases/${slug}`, {
                method: 'DELETE'
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || data.error || data.detail || 'Failed to delete');
            }

            fetchAddressLists();
            alert("Deleted successfully");
        } catch (err) {
            showFriendlyError(err);
        }
    }

    // Sync Aliases with Gateway config
    async function syncAddressLists() {
        const btnSync = document.getElementById('sync-lists-btn');
        btnSync.disabled = true;

        try {
            const response = await fetch(`/api/peers/${peerId}/aliases/sync`, {
                method: 'POST'
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || data.error || data.detail || 'Failed to sync');
            }

            alert("Synced successfully");
            fetchAddressLists();
        } catch (err) {
            showFriendlyError(err);
        } finally {
            btnSync.disabled = false;
        }
    }

    // Filter address lists table
    function filterListsTable() {
        const searchVal = document.getElementById('search-lists-input').value.toLowerCase();
        const rows = document.querySelectorAll('#lists-tbody tr');

        rows.forEach(row => {
            if (row.cells.length === 1) return;

            const slug = row.cells[0].textContent.toLowerCase();
            const comment = row.cells[1] ? row.cells[1].textContent.toLowerCase() : '';

            if (slug.includes(searchVal) || comment.includes(searchVal)) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    }

    // Populate alias autocomplete options
    function populateAliasDropdowns() {
        // No-op: using custom styled dropdown autocomplete instead of native datalist
    }

    let isTogglingAlias = false;

    // Toggle alias list on clicking the @ button
    function toggleAliasList(event, inputId) {
        if (event) event.stopPropagation();
        const input = document.getElementById(inputId);
        const dropdown = document.getElementById(inputId + '-dropdown');
        if (!input || !dropdown) return;

        if (dropdown.style.display === 'block') {
            dropdown.style.display = 'none';
        } else {
            const configs = [
                { inputId: 'srcIp', dropdownId: 'srcIp-dropdown' },
                { inputId: 'dstIp', dropdownId: 'dstIp-dropdown' }
            ];
            configs.forEach(c => {
                const otherDd = document.getElementById(c.dropdownId);
                if (otherDd) otherDd.style.display = 'none';
            });
            isTogglingAlias = true;
            input.focus();
            renderAutocompleteOptions(input, dropdown, true); // Force show all
            setTimeout(() => {
                isTogglingAlias = false;
            }, 100);
        }
    }

    function updateAddressMultiBtnState(inputId) {
        const input = document.getElementById(inputId);
        if (!input) return;
        const val = input.value.trim();
        const wrapper = input.closest('.input-dropdown-wrapper');
        if (!wrapper) return;
        const plusBtn = wrapper.querySelector('.address-multi-btn');
        if (!plusBtn) return;

        // Disabled by default (when empty, or if it starts with @)
        if (val === "" || val.startsWith('@')) {
            plusBtn.classList.add('disabled');
        } else {
            plusBtn.classList.remove('disabled');
        }
    }

    function toggleCustomOrderField() {
        const selectedRadio = document.querySelector('input[name="ruleOrderRadio"]:checked');
        const customGroup = document.getElementById('custom-order-group');
        if (selectedRadio && customGroup) {
            if (selectedRadio.value === 'custom') {
                customGroup.style.display = 'block';
                document.getElementById('ruleOrderCustomInput').focus();
            } else {
                customGroup.style.display = 'none';
                document.getElementById('ruleOrderCustomInput').value = '';
            }
        }
    }

    // Initialize custom dropdown autocompletes
    function initCustomAutocompletes() {
        const configs = [
            { inputId: 'srcIp', dropdownId: 'srcIp-dropdown' },
            { inputId: 'dstIp', dropdownId: 'dstIp-dropdown' }
        ];

        configs.forEach(({ inputId, dropdownId }) => {
            const input = document.getElementById(inputId);
            const dropdown = document.getElementById(dropdownId);
            if (!input || !dropdown) return;

            // Open on focus
            input.addEventListener('focus', () => {
                if (dropdown.style.display === 'block') return; // Skip if already opened
                if (isTogglingAlias) return;
                configs.forEach(c => {
                    if (c.inputId !== inputId) {
                        const otherDd = document.getElementById(c.dropdownId);
                        if (otherDd) otherDd.style.display = 'none';
                    }
                });
                renderAutocompleteOptions(input, dropdown);
            });

            // Filter on typing
            input.addEventListener('input', () => {
                renderAutocompleteOptions(input, dropdown);
                updateAddressMultiBtnState(inputId);
            });

            // Also check on change
            input.addEventListener('change', () => {
                updateAddressMultiBtnState(inputId);
            });

            // Click arrow icon to toggle dropdown
            const wrapper = input.closest('.input-dropdown-wrapper');
            const arrow = wrapper ? wrapper.querySelector('.dropdown-arrow') : null;
            if (arrow) {
                arrow.style.pointerEvents = 'auto';
                arrow.style.cursor = 'pointer';
                arrow.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (dropdown.style.display === 'block') {
                        dropdown.style.display = 'none';
                    } else {
                        configs.forEach(c => {
                            const otherDd = document.getElementById(c.dropdownId);
                            if (otherDd) otherDd.style.display = 'none';
                        });
                        isTogglingAlias = true;
                        input.focus();
                        renderAutocompleteOptions(input, dropdown, true); // Force show
                        setTimeout(() => {
                            isTogglingAlias = false;
                        }, 100);
                    }
                });
            }
        });

        // Close on click outside
        document.addEventListener('click', (e) => {
            configs.forEach(({ inputId, dropdownId }) => {
                const input = document.getElementById(inputId);
                const dropdown = document.getElementById(dropdownId);
                if (dropdown && !input.contains(e.target) && !dropdown.contains(e.target) && !e.target.classList.contains('alias-trigger-btn')) {
                    dropdown.style.display = 'none';
                }
            });
        });
    }

    // Render autocomplete options
    function renderAutocompleteOptions(input, dropdown, forceShow = false) {
        const val = input.value.trim();

        // Show ONLY if starts with '@' or forceShow is true
        if (!val.startsWith('@') && !forceShow) {
            dropdown.style.display = 'none';
            return;
        }

        const filterText = val.toLowerCase();
        dropdown.innerHTML = '';

        const cleanFilter = filterText.startsWith('@') ? filterText.substring(1) : filterText;

        let count = 0;
        cachedAddressLists.forEach(list => {
            // web_domain aliases have no nft set - not valid as a firewall rule src/dst
            if (list.type === 'web_domain') return;
            const slugMatch = list.slug.toLowerCase().includes(cleanFilter);
            const commentMatch = list.comment && list.comment.toLowerCase().includes(cleanFilter);
            const isMatch = !filterText || slugMatch || commentMatch || forceShow;

            if (isMatch) {
                count++;
                const item = document.createElement('div');
                item.className = 'custom-autocomplete-item';
                
                const itemsCount = (list.list || []).length;
                item.innerHTML = `
                    <span class="alias-title" style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                        <span style="display: inline-flex; align-items: center; gap: 8px;">
                            <span>@${list.name || list.slug}</span>
                            <span style="font-size: 0.6rem; color: var(--nk-blue-primary); background: #e0f2fe; padding: 1px 3px; border-radius: 4px; font-weight: 700;">${itemsCount}</span>
                        </span>
                        <span class="badge-edit-alias" style="font-size: 0.75rem; color:#0284c7; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; transition: var(--nk-transition);" onmouseover="this.style.background='#e0f2fe'; this.style.color='var(--nk-blue-primary)';" onmouseout="this.style.background='transparent'; this.style.color='var(--nk-text-muted)';" title="Edit Alias">
                            <i class="fas fa-external-link-alt"></i>
                        </span>
                    </span>
                    <span class="alias-desc">${list.comment || ''}</span>
                `;

                // Handle mousedown on the items count badge to edit alias directly without selecting it
                const badge = item.querySelector('.badge-edit-alias');
                if (badge) {
                    badge.addEventListener('mousedown', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        openEditListModal(list.slug);
                    });
                }

                item.addEventListener('mousedown', (e) => {
                    e.preventDefault(); // prevent blur
                    input.value = `@${list.name || list.slug}`; // Store as friendly name
                    dropdown.style.display = 'none';
                    input.dispatchEvent(new Event('change'));
                });
                dropdown.appendChild(item);
            }
        });

        if (count > 0) {
            dropdown.style.display = 'block';
        } else {
            dropdown.style.display = 'none';
        }
    }

    // --- Multi-Address Helper Dialog Logic ---
    let activeMultiInputId = "";

    function openMultiAddressModal(inputId) {
        if (!isPeerOnline) return;
        activeMultiInputId = inputId;

        const inputLabel = inputId === 'srcIp' ? 'Source Addresses' : 'Destination Addresses';
        document.getElementById('multiAddressModalTitle').textContent = inputLabel;

        const container = document.getElementById('multi-address-rows-container');
        container.innerHTML = '';

        const originalVal = document.getElementById(inputId).value.trim();
        if (originalVal) {
            const parts = originalVal.split(',').map(p => p.trim()).filter(Boolean);
            parts.forEach(part => {
                addMultiAddressRow(part);
            });
        }
        // Always append a blank/empty row at the bottom
        addMultiAddressRow();

        document.getElementById('multiAddressModal').classList.add('active');
    }

    function closeMultiAddressModal() {
        document.getElementById('multiAddressModal').classList.remove('active');
    }

    function addMultiAddressRow(address = '') {
        const container = document.getElementById('multi-address-rows-container');
        const rowDiv = document.createElement('div');
        rowDiv.className = 'multi-address-row';
        rowDiv.style.display = 'flex';
        rowDiv.style.gap = '0.75rem';
        rowDiv.style.marginBottom = '0.75rem';
        rowDiv.style.alignItems = 'center';

        rowDiv.innerHTML = `
            <div style="flex: 1;">
                <input type="text" placeholder="IP Address, CIDR or Hostname (e.g. 192.168.10.5, server.local)" class="multi-addr-input" required value="${address}" style="width: 100%; padding: 0.5rem 0.75rem; border: 1px solid var(--nk-border); border-radius: var(--nk-radius-sm); font-size: 0.88rem;">
            </div>
            <button type="button" class="btn-delete" onclick="removeMultiAddressRow(this)" style="padding: 0.5rem; display: flex; align-items: center; justify-content: center; height: 38px; width: 38px;">
                <i class="far fa-trash-alt"></i>
            </button>
        `;
        container.appendChild(rowDiv);
    }

    function removeMultiAddressRow(button) {
        const row = button.closest('.multi-address-row');
        if (row) row.remove();
    }

    function saveMultiAddresses() {
        const inputs = document.querySelectorAll('#multi-address-rows-container .multi-addr-input');
        const addresses = [];
        inputs.forEach(input => {
            const val = input.value.trim();
            if (val) addresses.push(val);
        });

        const targetInput = document.getElementById(activeMultiInputId);
        if (targetInput) {
            targetInput.value = addresses.join(', ');
            targetInput.dispatchEvent(new Event('input'));
            targetInput.dispatchEvent(new Event('change'));
        }

        closeMultiAddressModal();
    }

    // Resolver Configuration Settings
    async function fetchResolverConfig() {
        try {
            const response = await fetch(`/api/peers/${peerId}/resolver-config`);
            const data = await response.json();
            if (response.ok) {
                cachedResolverConfig = data;
            }
        } catch (err) {
            console.error("Failed to fetch resolver config:", err);
        }
    }

    function openResolverConfigModal() {
        if (!isPeerOnline) return;

        if (cachedResolverConfig) {
            populateResolverModal();
        } else {
            const resolverBtn = document.getElementById("resolver-settings-btn");
            const originalContent = resolverBtn ? resolverBtn.innerHTML : "Resolver Settings";
            if (resolverBtn) {
                resolverBtn.disabled = true;
                resolverBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Loading...`;
            }

            fetchResolverConfig().then(() => {
                if (resolverBtn) {
                    resolverBtn.disabled = false;
                    resolverBtn.innerHTML = originalContent;
                }
                populateResolverModal();
            });
        }
    }

    function addLocalDnsRow(domain = '', dnsIp = '') {
        const container = document.getElementById('local-dns-rows-container');
        if (!container) return;
        const rowDiv = document.createElement('div');
        rowDiv.className = 'local-dns-row';
        rowDiv.style.display = 'flex';
        rowDiv.style.gap = '0.75rem';
        rowDiv.style.marginBottom = '0.75rem';
        rowDiv.style.alignItems = 'center';

        rowDiv.innerHTML = `
            <div style="flex: 1;">
                <input type="text" placeholder="Domain / Zone (e.g. company.local)" class="local-domain-input" required value="${domain}" style="width: 100%; padding: 0.5rem 0.75rem; border: 1px solid var(--nk-border); border-radius: var(--nk-radius-sm); font-size: 0.88rem;">
            </div>
            <div style="flex: 1;">
                <input type="text" placeholder="Resolver IP (e.g. 192.168.2.34)" class="local-dns-input" required value="${dnsIp}" pattern="^([0-9]{1,3}\\.){3}[0-9]{1,3}$" title="Must be a valid IPv4 address" style="width: 100%; padding: 0.5rem 0.75rem; border: 1px solid var(--nk-border); border-radius: var(--nk-radius-sm); font-size: 0.88rem;">
            </div>
            <button type="button" class="btn-delete" onclick="removeLocalDnsRow(this)" style="padding: 0.5rem; display: flex; align-items: center; justify-content: center; height: 38px; width: 38px;">
                <i class="far fa-trash-alt"></i>
            </button>
        `;
        container.appendChild(rowDiv);
    }

    function removeLocalDnsRow(button) {
        button.closest('.local-dns-row').remove();
    }

    function populateResolverModal() {
        const container = document.getElementById('local-dns-rows-container');
        if (!container) return;
        container.innerHTML = '';
        originalUpstreams = [];

        const upstreams = (cachedResolverConfig && cachedResolverConfig.upstream_dns) || [];
        let hasLocalDns = false;

        upstreams.forEach(upstream => {
            const match = upstream.match(/^\[\/([a-zA-Z0-9._-]+)\/\](.+)$/);
            if (match) {
                const domain = match[1];
                const ip = match[2];
                addLocalDnsRow(domain, ip);
                hasLocalDns = true;
            } else {
                originalUpstreams.push(upstream);
            }
        });

        if (!hasLocalDns) {
            addLocalDnsRow();
        }

        document.getElementById('resolverModal').classList.add('active');
    }

    function closeResolverModal() {
        document.getElementById('resolverModal').classList.remove('active');
    }

    async function submitResolverConfig(e) {
        e.preventDefault();
        const btnSubmit = document.getElementById('btn-submit-resolver');
        if (btnSubmit) {
            btnSubmit.disabled = true;
            btnSubmit.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Saving...`;
        }

        const domainInputs = document.querySelectorAll('#local-dns-rows-container .local-domain-input');
        const dnsInputs = document.querySelectorAll('#local-dns-rows-container .local-dns-input');

        const localUpstreams = [];
        for (let i = 0; i < domainInputs.length; i++) {
            const domain = domainInputs[i].value.trim();
            const dnsIp = dnsInputs[i].value.trim();
            if (domain || dnsIp) {
                if (!domain) {
                    alert('Domain is required');
                    if (btnSubmit) { btnSubmit.disabled = false; btnSubmit.innerHTML = 'Save Changes'; }
                    domainInputs[i].focus();
                    return;
                }
                const dnsRes = parseAndValidateIPv4(dnsIp, { requireMask: false, allowMask: false });
                if (!dnsRes.valid) {
                    alert(`Resolver IP: ${dnsRes.error}`);
                    if (btnSubmit) { btnSubmit.disabled = false; btnSubmit.innerHTML = 'Save Changes'; }
                    dnsInputs[i].focus();
                    return;
                }
                localUpstreams.push(`[/${domain}/]${dnsRes.normalized || dnsIp}`);
            }
        }

        const finalUpstreams = [...originalUpstreams, ...localUpstreams];

        const payload = {
            upstream_dns: finalUpstreams,
            bootstrap_dns: (cachedResolverConfig && cachedResolverConfig.bootstrap_dns) || ["9.9.9.9"],
            all_servers: (cachedResolverConfig && cachedResolverConfig.all_servers) || false,
            fastest_addr: (cachedResolverConfig && cachedResolverConfig.fastest_addr) || false
        };

        try {
            const response = await fetch(`/api/peers/${peerId}/resolver-config`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || data.error || 'Failed to save resolver config');
            }

            alert("Saved successfully");
            await fetchResolverConfig();
            closeResolverModal();
        } catch (err) {
            showFriendlyError(err);
        } finally {
            if (btnSubmit) {
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = "Save Settings";
            }
        }
    }
