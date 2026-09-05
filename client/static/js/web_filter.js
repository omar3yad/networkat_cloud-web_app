const peerId = window.WEB_FILTER_CONFIG ? window.WEB_FILTER_CONFIG.peerId : "";
    const isPeerOnline = window.WEB_FILTER_CONFIG ? window.WEB_FILTER_CONFIG.isOnline : false;

    let activeTab = 'rules';
    let currentRules = [];
    let cachedAliases = [];
    let editingRuleId = null;
    let initialRulesOrder = [];
    let sortableInstance = null;
    let isTogglingAlias = false;
    let activeMultiInputId = "";

    document.addEventListener('DOMContentLoaded', () => {
        if (!isPeerOnline) {
            document.getElementById('banner-offline').style.display = 'flex';
            document.getElementById('add-rule-btn').disabled = true;
        }

        // Initialize sortable for drag-and-drop rule reordering
        const tbody = document.getElementById('rules-tbody');
        if (tbody && typeof Sortable !== 'undefined') {
            sortableInstance = new Sortable(tbody, {
                animation: 150,
                handle: '.drag-handle',
                ghostClass: 'sortable-ghost',
                onEnd: function () {
                    checkReorderStatus();
                }
            });
        }

        // Initialize autocomplete behaviors on Source input
        initCustomAutocompletes();
        initWebFilterLiveValidation();

        // Fetch initial data
        fetchAliases(true).then(() => {
            fetchWebFilterRules();
        });
    });

    // --------------------------------------------------------------------------
    // Web Filter Rules Logic
    // --------------------------------------------------------------------------

    async function fetchWebFilterRules(silent = false) {
        const loadingView = document.getElementById('loading-rules-view');
        const rulesTable = document.getElementById('rules-table');
        const refreshIcon = document.getElementById('refresh-icon');

        if (refreshIcon) refreshIcon.classList.add('fa-spin');
        if (!silent) {
            loadingView.style.display = 'flex';
            rulesTable.style.display = 'none';
        }

        try {
            const response = await fetch(`/api/peers/${peerId}/web-filter/rules`);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || data.detail || 'Failed to fetch web filter rules');
            }

            currentRules = data.rules || [];
            initialRulesOrder = currentRules.map(r => r.id);
            document.getElementById('banner-reorder').style.display = 'none';

            renderRulesTable(currentRules);
        } catch (err) {
            console.error(err);
            if (!silent) {
                document.getElementById('rules-tbody').innerHTML = `
                    <tr>
                        <td colspan="7" style="text-align: center; padding: 3rem; color: #ef4444; font-weight: 600;">
                            <i class="fas fa-exclamation-triangle fa-2x mb-3"></i><br>
                            Error loading web filter rules: ${err.message}
                        </td>
                    </tr>
                `;
            }
        } finally {
            if (refreshIcon) refreshIcon.classList.remove('fa-spin');
            if (!silent) {
                loadingView.style.display = 'none';
                rulesTable.style.display = 'table';
            }
        }
    }

    function renderRulesTable(rules) {
        const tbody = document.getElementById('rules-tbody');
        tbody.innerHTML = '';

        if (!rules || rules.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" style="text-align: center; padding: 4rem; color: var(--nk-text-muted);">
                        <i class="fas fa-filter fa-3x mb-3" style="opacity: 0.35;"></i>
                        <h3>No Web Filter Rules Configured</h3>
                        <p style="font-size: 0.85rem; margin-top: 0.25rem;">Create a rule to block domains across your network.</p>
                    </td>
                </tr>
            `;
            return;
        }

        rules.forEach((rule, idx) => {
            const tr = document.createElement('tr');
            tr.setAttribute('data-rule-id', rule.id);

            // 1. Checkbox
            const tdCheck = document.createElement('td');
            tdCheck.style.textAlign = 'center';
            tdCheck.innerHTML = `<input type="checkbox" class="rule-row-checkbox" data-rule-id="${rule.id}" onchange="onRuleCheckboxChange()">`;
            tr.appendChild(tdCheck);

            // 2. Drag handle
            const tdDrag = document.createElement('td');
            tdDrag.style.textAlign = 'center';
            tdDrag.innerHTML = `<i class="fas fa-grip-vertical drag-handle" title="Drag to reorder"></i>`;
            tr.appendChild(tdDrag);

            // 3. Source
            const tdSrc = document.createElement('td');
            if (!rule.src || rule.src.length === 0) {
                tdSrc.innerHTML = `<span class="badge-all"><i class="fas fa-network-wired"></i> All Network</span>`;
            } else {
                const srcBadges = rule.src.map(s => {
                    if (s.startsWith('@')) {
                        const aliasName = resolveAliasIdToName(s);
                        return `<span class="badge-alias" title="${s}">${aliasName}</span>`;
                    }
                    return `<span class="badge-ip">${s}</span>`;
                }).join(' ');
                tdSrc.innerHTML = srcBadges;
            }
            tr.appendChild(tdSrc);

            // 5. Blocked Domains
            const tdDomains = document.createElement('td');
            const domainChips = (rule.domains || []).map(d => {
                const aliasName = resolveAliasIdToName(d);
                const tooltipText = getDomainAliasTooltip(d);
                return `<span class="badge-domain" title="${tooltipText}"><i class="fas fa-globe"></i> ${aliasName}</span>`;
            }).join(' ');
            tdDomains.innerHTML = `<div class="domains-chip-list">${domainChips}</div>`;
            tr.appendChild(tdDomains);

            // 6. Comment
            const tdComment = document.createElement('td');
            tdComment.style.fontWeight = '500';
            tdComment.textContent = rule.comment || '-';
            tr.appendChild(tdComment);

            // 7. Enabled Toggle
            const tdEnabled = document.createElement('td');
            tdEnabled.style.textAlign = 'center';
            const isChecked = rule.enabled ? 'checked' : '';
            tdEnabled.innerHTML = `
                <label class="toggle-switch">
                    <input type="checkbox" ${isChecked} onchange="toggleRuleStatus('${rule.id}', this)">
                    <span class="slider"></span>
                </label>
            `;
            tr.appendChild(tdEnabled);

            // 8. Actions
            const tdActions = document.createElement('td');
            tdActions.className = 'cell-actions';
            tdActions.innerHTML = `
                <button class="btn-icon-action" onclick="openEditRuleModal('${rule.id}')" title="Edit rule">
                    <i class="fas fa-edit"></i>
                </button>
                <button class="btn-icon-action btn-delete" onclick="deleteSingleRule('${rule.id}')" title="Delete rule">
                    <i class="fas fa-trash-alt"></i>
                </button>
            `;
            tr.appendChild(tdActions);

            tbody.appendChild(tr);
        });
    }

    // Toggle Single Rule Status
    async function toggleRuleStatus(ruleId, checkbox) {
        const action = checkbox.checked ? 'enable' : 'disable';
        checkbox.disabled = true;

        try {
            const resp = await fetch(`/api/peers/${peerId}/web-filter/rules/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: [ruleId] })
            });
            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.message || data.detail || 'Failed to toggle rule');
            }
            const rule = currentRules.find(r => r.id === ruleId);
            if (rule) rule.enabled = checkbox.checked;
        } catch (err) {
            alert('Error toggling rule: ' + err.message);
            checkbox.checked = !checkbox.checked; // Revert
        } finally {
            checkbox.disabled = false;
        }
    }

    // Delete Single Rule
    async function deleteSingleRule(ruleId) {
        if (!confirm('Are you sure you want to delete this web filter rule?')) return;

        try {
            const resp = await fetch(`/api/peers/${peerId}/web-filter/rules/${ruleId}`, {
                method: 'DELETE'
            });
            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.message || data.detail || 'Failed to delete rule');
            }
            fetchWebFilterRules();
        } catch (err) {
            alert('Error deleting rule: ' + err.message);
        }
    }

    // Reorder rules detection
    function checkReorderStatus() {
        const rows = document.querySelectorAll('#rules-tbody tr[data-rule-id]');
        const currentOrder = Array.from(rows).map(r => r.getAttribute('data-rule-id'));
        const isChanged = currentOrder.some((id, idx) => id !== initialRulesOrder[idx]);

        const banner = document.getElementById('banner-reorder');
        banner.style.display = isChanged ? 'flex' : 'none';
    }

    async function submitReorder() {
        const rows = document.querySelectorAll('#rules-tbody tr[data-rule-id]');
        const items = Array.from(rows).map((r, idx) => ({
            id: r.getAttribute('data-rule-id'),
            order: idx + 1
        }));

        try {
            const resp = await fetch(`/api/peers/${peerId}/web-filter/rules/reorder`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items })
            });
            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.message || data.detail || 'Failed to reorder rules');
            }
            fetchWebFilterRules();
        } catch (err) {
            alert('Error applying rule order: ' + err.message);
        }
    }

    // Bulk Actions
    function toggleSelectAllRules(masterCheckbox) {
        const checkboxes = document.querySelectorAll('.rule-row-checkbox');
        checkboxes.forEach(cb => cb.checked = masterCheckbox.checked);
        onRuleCheckboxChange();
    }

    function onRuleCheckboxChange() {
        const checkboxes = document.querySelectorAll('.rule-row-checkbox');
        const selectedCount = Array.from(checkboxes).filter(cb => cb.checked).length;

        const masterCheckbox = document.getElementById('select-all-rules');
        if (masterCheckbox) {
            masterCheckbox.checked = selectedCount === checkboxes.length && checkboxes.length > 0;
        }

        const floatingBar = document.getElementById('bulk-action-bar');
        const countBadge = document.getElementById('selected-rules-count');
        if (floatingBar && countBadge) {
            countBadge.textContent = `${selectedCount} selected`;
            if (selectedCount > 0) {
                floatingBar.style.display = 'block';
                setTimeout(() => floatingBar.classList.add('show'), 10);
            } else {
                floatingBar.classList.remove('show');
                setTimeout(() => {
                    if (!floatingBar.classList.contains('show')) floatingBar.style.display = 'none';
                }, 300);
            }
        }
    }

    function deselectAllRules() {
        const masterCheckbox = document.getElementById('select-all-rules');
        if (masterCheckbox) masterCheckbox.checked = false;

        const checkboxes = document.querySelectorAll('.rule-row-checkbox');
        checkboxes.forEach(cb => cb.checked = false);
        onRuleCheckboxChange();
    }

    async function applyBulkAction(action) {
        const checkboxes = document.querySelectorAll('.rule-row-checkbox:checked');
        const ids = Array.from(checkboxes).map(cb => cb.getAttribute('data-rule-id'));
        if (ids.length === 0) return;

        let endpoint = `/api/peers/${peerId}/web-filter/rules/remove`;
        if (action === 'enable') endpoint = `/api/peers/${peerId}/web-filter/rules/enable`;
        if (action === 'disable') endpoint = `/api/peers/${peerId}/web-filter/rules/disable`;

        if (action === 'delete' && !confirm(`Are you sure you want to delete ${ids.length} selected rule(s)?`)) {
            return;
        }

        try {
            const resp = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids })
            });
            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.message || data.detail || 'Failed to apply bulk action');
            }
            deselectAllRules();
            fetchWebFilterRules();
        } catch (err) {
            alert('Bulk action error: ' + err.message);
        }
    }

    // Filter rules table
    function filterRulesTable() {
        const query = document.getElementById('search-rules-input').value.toLowerCase();
        const rows = document.querySelectorAll('#rules-tbody tr');

        rows.forEach(row => {
            if (row.cells.length === 1) return;
            const src = row.cells[2].textContent.toLowerCase();
            const domains = row.cells[3].textContent.toLowerCase();
            const comment = row.cells[4].textContent.toLowerCase();

            if (src.includes(query) || domains.includes(query) || comment.includes(query)) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    }

    // --------------------------------------------------------------------------
    // Rule Modal (Add / Edit)
    // --------------------------------------------------------------------------

    // --------------------------------------------------------------------------
    // Rule Modal (Add / Edit) with Live Validation
    // --------------------------------------------------------------------------

    function openAddRuleModal() {
        editingRuleId = null;
        document.getElementById('ruleModalTitle').textContent = 'Add Web Filter Rule';
        document.getElementById('ruleComment').value = '';
        document.getElementById('ruleSrc').value = '';
        document.getElementById('ruleDomains').value = '';
        clearAllFieldErrors();

        const commentCounter = document.getElementById('ruleComment-counter');
        if (commentCounter) {
            commentCounter.textContent = '0 / 200';
            commentCounter.className = 'char-counter';
        }

        updateAddressMultiBtnState('ruleSrc');

        const orderRow = document.getElementById('rule-order-row');
        if (orderRow) {
            orderRow.style.display = 'flex';
            const defaultRadio = document.querySelector('input[name="ruleOrderRadio"][value="bottom"]');
            if (defaultRadio) defaultRadio.checked = true;
            toggleCustomOrderField();
        }

        document.getElementById('ruleModal').classList.add('active');
    }

    function openEditRuleModal(ruleId) {
        const rule = currentRules.find(r => r.id === ruleId);
        if (!rule) return;

        editingRuleId = ruleId;
        clearAllFieldErrors();

        document.getElementById('ruleModalTitle').textContent = 'Edit Web Filter Rule';
        const commentVal = rule.comment || '';
        document.getElementById('ruleComment').value = commentVal;
        const commentCounter = document.getElementById('ruleComment-counter');
        if (commentCounter) {
            commentCounter.textContent = `${commentVal.length} / 200`;
            commentCounter.className = 'char-counter' + (commentVal.length > 180 ? (commentVal.length > 200 ? ' error' : ' warning') : '');
        }

        document.getElementById('ruleSrc').value = (rule.src || []).map(s => resolveAliasIdToName(s)).join(', ');
        document.getElementById('ruleDomains').value = (rule.domains || []).map(d => resolveAliasIdToName(d)).join(', ');
        updateAddressMultiBtnState('ruleSrc');

        const orderRow = document.getElementById('rule-order-row');
        if (orderRow) {
            orderRow.style.display = 'none'; // Order is kept on PUT
        }

        document.getElementById('ruleModal').classList.add('active');
    }

    function closeRuleModal() {
        document.getElementById('ruleModal').classList.remove('active');
        clearAllFieldErrors();
        document.querySelectorAll('.custom-autocomplete-dropdown').forEach(d => d.style.display = 'none');
    }

    function toggleCustomOrderField() {
        const radio = document.querySelector('input[name="ruleOrderRadio"]:checked');
        const customGroup = document.getElementById('custom-order-group');
        if (customGroup) {
            customGroup.style.display = (radio && radio.value === 'custom') ? 'flex' : 'none';
        }
    }

    // =========================================================================
    // Validation Engine (WEB_FILTER_API Specification)
    // =========================================================================

    function validateWebFilterComment(comment) {
        if (!comment || typeof comment !== 'string') return { valid: true };
        if (comment.length > 200) {
            return { valid: false, error: 'Max 200 characters' };
        }
        return { valid: true };
    }

    function validateWebFilterSource(value) {
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
            const matched = cachedAliases.find(l => l.name === searchName || l.slug === searchName || String(l.id) === String(searchName));
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

    function validateWebFilterDomains(value) {
        if (!value || typeof value !== 'string') {
            return { valid: false, error: 'Required' };
        }
        const trimmed = value.trim();
        if (!trimmed) {
            return { valid: false, error: 'Required' };
        }

        const parts = trimmed.split(',').map(p => p.trim()).filter(Boolean);
        if (parts.length === 0) {
            return { valid: false, error: 'Required' };
        }

        const seen = new Set();
        for (const part of parts) {
            let cleanRef = part;
            if (!cleanRef.startsWith('@')) {
                cleanRef = '@' + cleanRef;
            }

            if (seen.has(cleanRef.toLowerCase())) {
                return { valid: false, error: 'Duplicate alias' };
            }
            seen.add(cleanRef.toLowerCase());

            let aliasName = cleanRef.substring(1).trim();
            if (!aliasName || aliasName === 'alias_') {
                return { valid: false, error: 'Invalid alias' };
            }
            let searchName = aliasName.startsWith('alias_') ? aliasName.substring(6) : aliasName;
            const matched = cachedAliases.find(l => l.name === searchName || l.slug === searchName || String(l.id) === String(searchName));
            if (matched) {
                if (matched.type === 'normal') {
                    return { valid: false, error: 'Normal aliases not supported' };
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
        ['ruleComment', 'ruleSrc', 'ruleDomains', 'ruleOrderCustomInput', 'aliasName', 'aliasComment', 'aliasItems'].forEach(id => {
            clearFieldError(id);
        });
        document.querySelectorAll('#alias-items-container .is-invalid').forEach(inp => inp.classList.remove('is-invalid'));
        document.querySelectorAll('#alias-items-container .row-error-msg').forEach(msg => {
            msg.textContent = '';
            msg.style.display = 'none';
        });
    }

    function initWebFilterLiveValidation() {
        const commentInp = document.getElementById('ruleComment');
        const commentCounter = document.getElementById('ruleComment-counter');
        if (commentInp) {
            commentInp.addEventListener('input', () => {
                const len = commentInp.value.length;
                if (commentCounter) {
                    commentCounter.textContent = `${len} / 200`;
                    commentCounter.className = 'char-counter' + (len > 180 ? (len > 200 ? ' error' : ' warning') : '');
                }
                const res = validateWebFilterComment(commentInp.value);
                if (!res.valid) {
                    setFieldError('ruleComment', res.error);
                } else {
                    clearFieldError('ruleComment');
                }
            });
        }

        const srcInp = document.getElementById('ruleSrc');
        if (srcInp) {
            srcInp.addEventListener('input', () => {
                const res = validateWebFilterSource(srcInp.value);
                if (!res.valid) {
                    setFieldError('ruleSrc', res.error);
                } else {
                    clearFieldError('ruleSrc');
                }
            });
        }

        const domainsInp = document.getElementById('ruleDomains');
        if (domainsInp) {
            domainsInp.addEventListener('input', () => {
                const res = validateWebFilterDomains(domainsInp.value);
                if (!res.valid) {
                    setFieldError('ruleDomains', res.error);
                } else {
                    clearFieldError('ruleDomains');
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

        const aliasNameInp = document.getElementById('aliasName');
        const aliasNameCounter = document.getElementById('aliasName-counter');
        if (aliasNameInp) {
            aliasNameInp.addEventListener('input', () => {
                const len = aliasNameInp.value.length;
                if (aliasNameCounter) {
                    aliasNameCounter.textContent = `${len} / 200`;
                    aliasNameCounter.className = 'char-counter' + (len > 180 ? (len > 200 ? ' error' : ' warning') : '');
                }
                if (!aliasNameInp.value.trim()) {
                    setFieldError('aliasName', 'Alias Name is required.');
                } else if (aliasNameInp.value.trim().length > 200) {
                    setFieldError('aliasName', 'Alias Name exceeds 200 characters.');
                } else {
                    clearFieldError('aliasName');
                }
            });
        }

        const aliasCommentInp = document.getElementById('aliasComment');
        const aliasCommentCounter = document.getElementById('aliasComment-counter');
        if (aliasCommentInp) {
            aliasCommentInp.addEventListener('input', () => {
                const len = aliasCommentInp.value.length;
                if (aliasCommentCounter) {
                    aliasCommentCounter.textContent = `${len} / 200`;
                    aliasCommentCounter.className = 'char-counter' + (len > 180 ? (len > 200 ? ' error' : ' warning') : '');
                }
                if (aliasCommentInp.value.length > 200) {
                    setFieldError('aliasComment', 'Comment exceeds 200 characters.');
                } else {
                    clearFieldError('aliasComment');
                }
            });
        }
    }

    async function submitRuleForm(e) {
        e.preventDefault();
        clearAllFieldErrors();

        const btn = document.getElementById('btn-submit-rule');
        const comment = document.getElementById('ruleComment').value.trim();
        const srcRaw = document.getElementById('ruleSrc').value.trim();
        const domainsRaw = document.getElementById('ruleDomains').value.trim();

        let hasError = false;
        let firstInvalidInputId = null;

        // 1. Validate Comment
        const commentRes = validateWebFilterComment(comment);
        if (!commentRes.valid) {
            setFieldError('ruleComment', commentRes.error);
            hasError = true;
            if (!firstInvalidInputId) firstInvalidInputId = 'ruleComment';
        }

        // 2. Validate Source Address
        const srcRes = validateWebFilterSource(srcRaw);
        if (!srcRes.valid) {
            setFieldError('ruleSrc', srcRes.error);
            hasError = true;
            if (!firstInvalidInputId) firstInvalidInputId = 'ruleSrc';
        }

        // 3. Validate Blocked Domains
        const domainsRes = validateWebFilterDomains(domainsRaw);
        if (!domainsRes.valid) {
            setFieldError('ruleDomains', domainsRes.error);
            hasError = true;
            if (!firstInvalidInputId) firstInvalidInputId = 'ruleDomains';
        }

        // 4. Validate Custom Order
        if (editingRuleId === null) {
            const orderRadio = document.querySelector('input[name="ruleOrderRadio"]:checked');
            if (orderRadio && orderRadio.value === 'custom') {
                const customInput = document.getElementById('ruleOrderCustomInput');
                const customOrder = customInput ? parseInt(customInput.value) : NaN;
                if (isNaN(customOrder) || customOrder < 1) {
                    setFieldError('ruleOrderCustomInput', 'Please enter a valid order number (1 or higher).');
                    hasError = true;
                    if (!firstInvalidInputId) firstInvalidInputId = 'ruleOrderCustomInput';
                }
            }
        }

        if (hasError) {
            if (firstInvalidInputId) {
                const el = document.getElementById(firstInvalidInputId);
                if (el) el.focus();
            }
            return;
        }

        btn.disabled = true;

        // Construct payload
        let domainParts = domainsRaw.split(',').map(p => p.trim()).filter(Boolean);
        const domains = domainParts.map(d => {
            let clean = d.startsWith('@') ? d : '@' + d;
            return resolveAliasNameToId(clean);
        });

        // Parse sources
        let src = null;
        if (srcRaw) {
            const srcToProcess = (srcRes && srcRes.normalized) ? srcRes.normalized : srcRaw;
            src = srcToProcess.split(',').map(s => s.trim()).filter(Boolean).map(p => {
                if (p.startsWith('@')) {
                    let aName = p.substring(1).trim();
                    let clean = aName.startsWith('alias_') ? aName.substring(6) : aName;
                    const matched = cachedAliases.find(a => a.name === clean || a.slug === clean || String(a.id) === String(clean));
                    return matched ? (matched.id || matched.slug) : p;
                }
                return p;
            });
        }

        const payload = {
            comment: comment || null,
            src: src,
            domains: domains,
            enabled: true
        };

        if (editingRuleId === null) {
            const orderRadio = document.querySelector('input[name="ruleOrderRadio"]:checked');
            if (orderRadio) {
                const radioVal = orderRadio.value;
                if (radioVal === 'first') {
                    payload.order = 1;
                } else if (radioVal === 'custom') {
                    const customInput = document.getElementById('ruleOrderCustomInput');
                    const customOrder = customInput ? parseInt(customInput.value) : NaN;
                    if (!isNaN(customOrder) && customOrder > 0) {
                        payload.order = customOrder;
                    }
                }
            }
        }

        try {
            let url = `/api/peers/${peerId}/web-filter/rules`;
            let method = 'POST';

            if (editingRuleId !== null) {
                url = `/api/peers/${peerId}/web-filter/rules/${editingRuleId}`;
                method = 'PUT';
            }

            const resp = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await resp.json();

            if (!resp.ok) {
                throw new Error(data.message || data.detail || data.error || 'Failed to save');
            }

            closeRuleModal();
            fetchWebFilterRules();
            alert('Saved successfully');
        } catch (err) {
            alert(err.message || 'Failed to save');
        } finally {
            btn.disabled = false;
        }
    }

    // --------------------------------------------------------------------------
    // Autocomplete & Alias Dropdown Logic (Identical to Firewall)
    // --------------------------------------------------------------------------

    function initCustomAutocompletes() {
        setupAutocompleteForField('ruleSrc');
        setupAutocompleteForField('ruleDomains');
    }

    function setupAutocompleteForField(inputId) {
        const input = document.getElementById(inputId);
        const dropdown = document.getElementById(inputId + '-dropdown');
        if (!input || !dropdown) return;

        // Open on focus if typed @ or domain field
        input.addEventListener('focus', () => {
            if (dropdown.style.display === 'block') return;
            if (isTogglingAlias) return;
            renderAutocompleteOptions(input, dropdown);
        });

        // Filter on typing
        input.addEventListener('input', () => {
            renderAutocompleteOptions(input, dropdown);
            if (inputId === 'ruleSrc') updateAddressMultiBtnState('ruleSrc');
        });

        if (inputId === 'ruleSrc') {
            input.addEventListener('change', () => {
                updateAddressMultiBtnState('ruleSrc');
            });
        }

        // Close on click outside
        document.addEventListener('click', (e) => {
            if (dropdown && !input.contains(e.target) && !dropdown.contains(e.target) && !e.target.classList.contains('alias-trigger-btn')) {
                dropdown.style.display = 'none';
            }
        });
    }

    function toggleAliasList(event, inputId) {
        if (event) event.stopPropagation();
        const input = document.getElementById(inputId);
        const dropdown = document.getElementById(inputId + '-dropdown');
        if (!input || !dropdown) return;

        if (dropdown.style.display === 'block') {
            dropdown.style.display = 'none';
        } else {
            isTogglingAlias = true;
            input.focus();
            renderAutocompleteOptions(input, dropdown, true); // Force show all
            setTimeout(() => {
                isTogglingAlias = false;
            }, 100);
        }
    }

    function renderAutocompleteOptions(input, dropdown, forceShow = false) {
        const val = input.value.trim();
        const isDomainInput = (input.id === 'ruleDomains');

        // Show ONLY if starts with '@' or forceShow is true
        if (!val.startsWith('@') && !forceShow) {
            dropdown.style.display = 'none';
            return;
        }

        const filterText = val.toLowerCase();
        dropdown.innerHTML = '';

        const cleanFilter = filterText.startsWith('@') ? filterText.substring(1) : filterText;

        let count = 0;
        cachedAliases.forEach(list => {
            if (isDomainInput) {
                // Only web_domain aliases for Blocked Domains
                if (list.type !== 'web_domain') return;
            } else {
                // Only normal aliases for Source address
                if (list.type === 'web_domain') return;
            }

            const nameMatch = (list.name || '').toLowerCase().includes(cleanFilter);
            const slugMatch = (list.slug || '').toLowerCase().includes(cleanFilter);
            const commentMatch = list.comment && list.comment.toLowerCase().includes(cleanFilter);
            const isMatch = !filterText || nameMatch || slugMatch || commentMatch || forceShow;

            if (isMatch) {
                count++;
                const item = document.createElement('div');
                item.className = 'custom-autocomplete-item';

                const itemsCount = (list.list || []).length;
                const countBadgeBg = isDomainInput ? '#fef3c7' : '#e0f2fe';
                const countBadgeColor = isDomainInput ? '#b45309' : 'var(--nk-blue-primary)';
                const itemLabel = isDomainInput ? (itemsCount === 1 ? 'domain' : 'domains') : (itemsCount === 1 ? 'ip' : 'ips');

                item.innerHTML = `
                    <span class="alias-title" style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                        <span style="display: inline-flex; align-items: center; gap: 8px;">
                            <span>@${list.name || list.slug}</span>
                            <span style="font-size: 0.6rem; color: ${countBadgeColor}; background: ${countBadgeBg}; padding: 1px 5px; border-radius: 4px; font-weight: 700;">${itemsCount} ${itemLabel}</span>
                        </span>
                        <span class="badge-edit-alias" style="font-size: 0.75rem; color:#0284c7; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; transition: var(--nk-transition);" onmouseover="this.style.background='#e0f2fe'; this.style.color='var(--nk-blue-primary)';" onmouseout="this.style.background='transparent'; this.style.color='var(--nk-text-muted)';" title="Edit Alias">
                            <i class="fas fa-external-link-alt"></i>
                        </span>
                    </span>
                    <span class="alias-desc">${list.comment || ''}</span>
                `;

                // Handle clicking the edit icon on the right
                const editBadge = item.querySelector('.badge-edit-alias');
                if (editBadge) {
                    editBadge.addEventListener('mousedown', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        dropdown.style.display = 'none';
                        openEditAliasModal(list.id || list.slug);
                    });
                }

                // Handle selecting the alias
                item.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    input.value = `@${list.name || list.slug}`;
                    dropdown.style.display = 'none';
                    input.dispatchEvent(new Event('change'));
                });

                dropdown.appendChild(item);
            }
        });

        if (count > 0) {
            dropdown.style.display = 'block';
        } else if (isDomainInput && forceShow) {
            dropdown.innerHTML = `
                <div style="padding: 0.85rem; text-align: center; color: var(--nk-text-muted); font-size: 0.8rem;">
                    No Domain Aliases found.<br>
                    <a href="/peers/${peerId}/aliases?filter=web_domain" style="color: var(--nk-blue-primary); font-weight: 600; margin-top: 4px; display: inline-block;">+ Create Domain Alias</a>
                </div>
            `;
            dropdown.style.display = 'block';
        } else {
            dropdown.style.display = 'none';
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

        if (val === "" || val.startsWith('@')) {
            plusBtn.classList.add('disabled');
        } else {
            plusBtn.classList.remove('disabled');
        }
    }

    // --------------------------------------------------------------------------
    // Multi-Address Helper Dialog Logic (Matching Firewall)
    // --------------------------------------------------------------------------

    function openMultiAddressModal(inputId) {
        if (!isPeerOnline) return;
        activeMultiInputId = inputId;

        document.getElementById('multiAddressModalTitle').textContent = 'Source Addresses';
        const container = document.getElementById('multi-address-rows-container');
        container.innerHTML = '';

        const originalVal = document.getElementById(inputId).value.trim();
        if (originalVal && !originalVal.startsWith('@')) {
            const parts = originalVal.split(',').map(p => p.trim()).filter(Boolean);
            parts.forEach(part => {
                addMultiAddressRow(part);
            });
        }
        // Always append a blank/empty row
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
                <input type="text" placeholder="IP Address or CIDR (e.g. 192.168.10.5, 10.0.0.0/24)" class="multi-addr-input" required value="${address}" style="width: 100%; padding: 0.5rem 0.75rem; border: 1px solid var(--nk-border); border-radius: var(--nk-radius-sm); font-size: 0.88rem;">
            </div>
            <button type="button" class="btn-delete" onclick="removeMultiAddressRow(this)" title="Delete address" style="padding: 0.5rem; display: flex; align-items: center; justify-content: center; height: 38px; width: 38px;">
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
            targetInput.dispatchEvent(new Event('change'));
        }

        closeMultiAddressModal();
    }

    // --------------------------------------------------------------------------
    // Domain Aliases Logic
    // --------------------------------------------------------------------------

    async function fetchAliases(silent = false) {
        const loadingView = document.getElementById('loading-aliases-view');
        const table = document.getElementById('aliases-table');

        if (!silent) {
            loadingView.style.display = 'flex';
            table.style.display = 'none';
        }

        try {
            const resp = await fetch(`/api/peers/${peerId}/aliases`);
            const data = await resp.json();

            if (!resp.ok) {
                throw new Error(data.error || data.detail || 'Failed to fetch aliases');
            }

            cachedAliases = data.lists || [];
            cachedAliases.forEach(a => {
                if (!a.slug && a.id) a.slug = a.id;
            });

            renderAliasesTable(cachedAliases.filter(a => a.type === 'web_domain'));
        } catch (err) {
            console.error(err);
            if (!silent) {
                document.getElementById('aliases-tbody').innerHTML = `
                    <tr>
                        <td colspan="6" style="text-align: center; padding: 3rem; color: #ef4444; font-weight: 600;">
                            <i class="fas fa-exclamation-triangle fa-2x mb-3"></i><br>
                            Error loading aliases: ${err.message}
                        </td>
                    </tr>
                `;
            }
        } finally {
            if (!silent) {
                loadingView.style.display = 'none';
                table.style.display = 'table';
            }
        }
    }

    function renderAliasesTable(aliases) {
        const tbody = document.getElementById('aliases-tbody');
        tbody.innerHTML = '';

        if (!aliases || aliases.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align: center; padding: 4rem; color: var(--nk-text-muted);">
                        <i class="fas fa-globe fa-3x mb-3" style="opacity: 0.35;"></i>
                        <h3>No Aliases Configured</h3>
                        <p style="font-size: 0.85rem; margin-top: 0.25rem;">Create an alias to use in your web filter rules.</p>
                    </td>
                </tr>
            `;
            return;
        }

        aliases.forEach(alias => {
            const tr = document.createElement('tr');
            tr.setAttribute('data-alias-id', alias.id || alias.slug);
            tr.setAttribute('data-alias-type', alias.type || 'normal');

            // Name with count badge next to it
            const tdName = document.createElement('td');
            const itemsCount = (alias.list || []).length;
            tdName.innerHTML = `
                <div style="display: inline-flex; align-items: center; gap: 8px;">
                    <strong>@${alias.name || alias.slug}</strong>
                    <span onclick="openEditAliasModal('${alias.id || alias.slug}')" style="font-weight: 700; color: var(--nk-blue-primary); background: #e0f2fe; padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; cursor: pointer;" title="Click to Edit Alias">${itemsCount}</span>
                </div>
            `;
            tr.appendChild(tdName);

            // Type Column
            const tdType = document.createElement('td');
            tdType.style.textAlign = 'center';
            const isWebDomainType = alias.type === 'web_domain';
            const typeBadgeStyle = isWebDomainType
                ? 'background: #fef3c7; color: #b45309; border: 1px solid #fde68a;'
                : 'background: #e6e6e6; color: #334155; border: 1px solid #e6e6e6;';
            const typeBadgeLabel = isWebDomainType ? 'Web domain' : 'Normal';
            tdType.innerHTML = `<span class="badge-ip" style="font-size: 0.72rem; font-weight: 600; padding: 2px 8px; border-radius: 4px; ${typeBadgeStyle}">${typeBadgeLabel}</span>`;
            tr.appendChild(tdType);

            // Items preview
            const tdDomains = document.createElement('td');
            const previewItems = (alias.list || []).slice(0, 5).map(item => {
                const dom = item.domain || item.address || item.hostname || '';
                const isDomain = !!item.domain || alias.type === 'web_domain';
                const colorClass = isDomain ? 'badge-domain' : 'badge-ip';
                return `<span class="${colorClass}">${dom}</span>`;
            }).join(' ');
            const moreCount = (alias.list || []).length - 5;
            tdDomains.innerHTML = `<div class="domains-chip-list">${previewItems}${moreCount > 0 ? ` <span class="badge-all">+${moreCount} more</span>` : ''}</div>`;
            tr.appendChild(tdDomains);

            // Comment
            const tdComment = document.createElement('td');
            tdComment.textContent = alias.comment || '-';
            tr.appendChild(tdComment);

            // Created
            const tdCreated = document.createElement('td');
            tdCreated.style.fontSize = '0.8rem';
            tdCreated.style.color = 'var(--nk-text-muted)';
            tdCreated.textContent = alias.created ? alias.created.split('T')[0] : '-';
            tr.appendChild(tdCreated);

            // Actions
            const tdActions = document.createElement('td');
            tdActions.className = 'cell-actions';
            tdActions.innerHTML = `
                <button class="btn-icon-action" onclick="openEditAliasModal('${alias.id || alias.slug}')" title="Edit alias">
                    <i class="fas fa-edit"></i>
                </button>
                <button class="btn-icon-action btn-delete" onclick="deleteAlias('${alias.id || alias.slug}')" title="Delete alias">
                    <i class="fas fa-trash-alt"></i>
                </button>
            `;
            tr.appendChild(tdActions);

            tbody.appendChild(tr);
        });
    }

    function filterAliasesTable() {
        const query = document.getElementById('search-aliases-input').value.toLowerCase();
        const rows = document.querySelectorAll('#aliases-tbody tr');

        rows.forEach(row => {
            if (row.cells.length === 1) return;
            const name = row.cells[0].textContent.toLowerCase();
            const items = row.cells[2] ? row.cells[2].textContent.toLowerCase() : '';
            const comment = row.cells[3] ? row.cells[3].textContent.toLowerCase() : '';

            if (name.includes(query) || items.includes(query) || comment.includes(query)) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    }

    // --------------------------------------------------------------------------
    // Alias Modal (Add / Edit for both Normal and Web Domain Aliases)
    // --------------------------------------------------------------------------

    function openAddDomainAliasModal() {
        document.getElementById('aliasActionType').value = 'add';
        document.getElementById('aliasEditId').value = '';
        document.getElementById('aliasType').value = 'web_domain';
        document.getElementById('aliasModalTitle').textContent = 'Create Domain Alias';
        document.getElementById('aliasName').value = '';
        document.getElementById('aliasComment').value = '';
        clearAllFieldErrors();

        const nameCounter = document.getElementById('aliasName-counter');
        if (nameCounter) {
            nameCounter.textContent = '0 / 200';
            nameCounter.className = 'char-counter';
        }
        const commentCounter = document.getElementById('aliasComment-counter');
        if (commentCounter) {
            commentCounter.textContent = '0 / 200';
            commentCounter.className = 'char-counter';
        }

        document.getElementById('alias-items-header').textContent = 'Domain Patterns *';
        document.getElementById('alias-items-hint').innerHTML = 'Use <code>*.facebook.com</code> for all subdomains or <code>tiktok.com</code> for exact match.';
        document.getElementById('btn-add-item-text').textContent = 'Add Domain';

        const container = document.getElementById('alias-items-container');
        container.innerHTML = '';
        addAliasItemRow('web_domain');

        document.getElementById('aliasModal').classList.add('active');
    }

    function openEditAliasModal(aliasId) {
        const alias = cachedAliases.find(a => (a.id || a.slug) === aliasId || a.name === aliasId);
        if (!alias) return;

        const isWebDomain = alias.type === 'web_domain';
        document.getElementById('aliasActionType').value = 'edit';
        document.getElementById('aliasEditId').value = alias.id || alias.slug;
        document.getElementById('aliasType').value = alias.type || 'normal';
        document.getElementById('aliasModalTitle').textContent = isWebDomain ? 'Edit Domain Alias' : 'Edit Alias';
        
        clearAllFieldErrors();

        const nameVal = alias.name || alias.slug;
        document.getElementById('aliasName').value = nameVal;
        const nameCounter = document.getElementById('aliasName-counter');
        if (nameCounter) {
            nameCounter.textContent = `${nameVal.length} / 200`;
            nameCounter.className = 'char-counter' + (nameVal.length > 180 ? (nameVal.length > 200 ? ' error' : ' warning') : '');
        }

        const commentVal = alias.comment || '';
        document.getElementById('aliasComment').value = commentVal;
        const commentCounter = document.getElementById('aliasComment-counter');
        if (commentCounter) {
            commentCounter.textContent = `${commentVal.length} / 200`;
            commentCounter.className = 'char-counter' + (commentVal.length > 180 ? (commentVal.length > 200 ? ' error' : ' warning') : '');
        }

        document.getElementById('alias-items-header').textContent = isWebDomain ? 'Domain Patterns *' : 'Addresses / Subnets *';
        document.getElementById('alias-items-hint').innerHTML = isWebDomain 
            ? 'Use <code>*.facebook.com</code> for all subdomains or <code>tiktok.com</code> for exact match.'
            : 'Enter IP address, CIDR subnet, or local hostname (e.g. <code>192.168.1.10</code>, <code>10.0.0.0/24</code>).';
        document.getElementById('btn-add-item-text').textContent = isWebDomain ? 'Add Domain' : 'Add Address';

        const container = document.getElementById('alias-items-container');
        container.innerHTML = '';

        if (alias.list && alias.list.length > 0) {
            alias.list.forEach(item => {
                const val = item.domain || item.address || item.hostname || '';
                addAliasItemRow(alias.type, val, item.comment || '');
            });
        } else {
            addAliasItemRow(alias.type);
        }

        document.getElementById('aliasModal').classList.add('active');
    }

    function closeAliasModal() {
        document.getElementById('aliasModal').classList.remove('active');
        clearAllFieldErrors();
    }

    function validateAliasModalEntry(value, type) {
        if (!value || typeof value !== 'string' || !value.trim()) {
            return { valid: false, error: 'Required' };
        }
        const trimmed = value.trim();

        if (type === 'web_domain') {
            if (trimmed === '*' || trimmed === '*.') {
                return { valid: false, error: 'Invalid domain' };
            }
            if (/^(\d{1,3}\.){3}\d{1,3}(\/\d+)?$/.test(trimmed)) {
                return { valid: false, error: 'Enter domain name' };
            }
            const domainRegex = /^(\*\.)?([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z0-9]{2,}$/;
            if (!domainRegex.test(trimmed)) {
                return { valid: false, error: 'Invalid domain' };
            }
            return { valid: true, normalized: trimmed, entryType: 'domain' };
        } else {
            const firstChar = trimmed[0];
            if (/^[0-9]/.test(firstChar)) {
                const ipv4Res = parseAndValidateIPv4(trimmed, { requireMask: false, allowMask: true, normalizeSubnet: true });
                if (!ipv4Res.valid) return ipv4Res;
                return { valid: true, normalized: ipv4Res.normalized, entryType: 'address' };
            }
            if (/^[a-zA-Z]/.test(firstChar)) {
                if (trimmed.includes(':') || trimmed.includes('*') || trimmed.includes('/')) return { valid: false, error: 'Invalid hostname' };
                const hostnameRegex = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/;
                if (!hostnameRegex.test(trimmed) || trimmed.length > 253) {
                    return { valid: false, error: 'Invalid hostname' };
                }
                return { valid: true, normalized: trimmed, entryType: 'hostname' };
            }
            return { valid: false, error: 'Invalid format' };
        }
    }

    function addAliasItemRow(type = 'web_domain', val = '', commentVal = '') {
        const isWebDomain = type === 'web_domain';
        const placeholder = isWebDomain ? 'e.g. *.facebook.com or tiktok.com' : 'e.g. 192.168.1.10 or 10.0.0.0/24';

        const container = document.getElementById('alias-items-container');
        const row = document.createElement('div');
        row.className = 'alias-entry-row';
        row.style.flexDirection = 'column';
        row.style.alignItems = 'stretch';
        row.innerHTML = `
            <div style="display: flex; gap: 8px; align-items: center; width: 100%;">
                <input type="text" placeholder="${placeholder}" value="${val}" required class="alias-val-input" style="flex: 1.5;">
                <input type="text" placeholder="Comment (optional)" value="${commentVal}" class="alias-comment-input" maxlength="200" style="flex: 1;">
                <button type="button" class="btn-delete" onclick="removeAliasItemRow(this)" title="Remove item" style="padding: 0.5rem; display: flex; align-items: center; justify-content: center; height: 38px; width: 38px;">
                    <i class="far fa-trash-alt"></i>
                </button>
            </div>
            <div class="field-error-msg row-error-msg" style="display: none;"></div>
        `;
        container.appendChild(row);

        const valInput = row.querySelector('.alias-val-input');
        const errorDiv = row.querySelector('.row-error-msg');
        if (valInput) {
            valInput.addEventListener('input', () => {
                const currentType = document.getElementById('aliasType').value;
                const res = validateAliasModalEntry(valInput.value, currentType);
                if (!res.valid) {
                    valInput.classList.add('is-invalid');
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${res.error}`;
                    errorDiv.style.display = 'flex';
                } else {
                    valInput.classList.remove('is-invalid');
                    errorDiv.textContent = '';
                    errorDiv.style.display = 'none';
                }
            });
        }
    }

    function removeAliasItemRow(btn) {
        const container = document.getElementById('alias-items-container');
        if (container.children.length <= 1) {
            setFieldError('aliasItems', 'An alias must contain at least one item.');
            return;
        }
        btn.closest('.alias-entry-row').remove();
    }

    async function submitAliasForm(e) {
        e.preventDefault();
        clearAllFieldErrors();

        const btn = document.getElementById('btn-submit-alias');
        const actionType = document.getElementById('aliasActionType').value;
        const aliasId = document.getElementById('aliasEditId').value;
        const aliasType = document.getElementById('aliasType').value;
        const name = document.getElementById('aliasName').value.trim();
        const comment = document.getElementById('aliasComment').value.trim();

        let hasError = false;
        let firstInvalidInput = null;

        if (!name) {
            setFieldError('aliasName', 'Alias Name is required.');
            hasError = true;
            if (!firstInvalidInput) firstInvalidInput = document.getElementById('aliasName');
        } else if (name.length > 200) {
            setFieldError('aliasName', 'Alias Name exceeds 200 characters.');
            hasError = true;
            if (!firstInvalidInput) firstInvalidInput = document.getElementById('aliasName');
        }

        if (comment.length > 200) {
            setFieldError('aliasComment', 'Comment exceeds 200 characters.');
            hasError = true;
            if (!firstInvalidInput) firstInvalidInput = document.getElementById('aliasComment');
        }

        const rows = document.querySelectorAll('#alias-items-container .alias-entry-row');
        const list = [];
        const seen = new Set();

        rows.forEach(r => {
            const valInp = r.querySelector('.alias-val-input');
            const cmtInp = r.querySelector('.alias-comment-input');
            const errorDiv = r.querySelector('.row-error-msg');

            const itemVal = valInp ? valInp.value.trim() : '';
            const cmt = (cmtInp ? cmtInp.value.trim() : '') || null;

            if (!itemVal) {
                if (valInp) valInp.classList.add('is-invalid');
                if (errorDiv) {
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> Value cannot be empty.`;
                    errorDiv.style.display = 'flex';
                }
                hasError = true;
                if (!firstInvalidInput) firstInvalidInput = valInp;
                return;
            }

            const itemRes = validateAliasModalEntry(itemVal, aliasType);
            if (!itemRes.valid) {
                if (valInp) valInp.classList.add('is-invalid');
                if (errorDiv) {
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${itemRes.error}`;
                    errorDiv.style.display = 'flex';
                }
                hasError = true;
                if (!firstInvalidInput) firstInvalidInput = valInp;
                return;
            }

            const normalizedItemVal = itemRes.normalized || itemVal;
            if (valInp && valInp.value !== normalizedItemVal) {
                valInp.value = normalizedItemVal;
            }

            const lowerVal = normalizedItemVal.toLowerCase();
            if (seen.has(lowerVal)) {
                if (valInp) valInp.classList.add('is-invalid');
                if (errorDiv) {
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> Duplicate item "${itemVal}".`;
                    errorDiv.style.display = 'flex';
                }
                hasError = true;
                if (!firstInvalidInput) firstInvalidInput = valInp;
                return;
            }
            seen.add(lowerVal);

            if (aliasType === 'web_domain') {
                list.push({ domain: normalizedItemVal, comment: cmt });
            } else {
                if (itemRes.entryType === 'address') {
                    list.push({ address: normalizedItemVal, comment: cmt });
                } else {
                    list.push({ hostname: normalizedItemVal, comment: cmt });
                }
            }
        });

        if (list.length === 0) {
            setFieldError('aliasItems', 'Please add at least one item.');
            hasError = true;
        } else if (list.length > 256) {
            setFieldError('aliasItems', `Maximum 256 items allowed per alias (current: ${list.length}).`);
            hasError = true;
        }

        if (hasError) {
            if (firstInvalidInput) firstInvalidInput.focus();
            return;
        }

        btn.disabled = true;

        try {
            if (actionType === 'add') {
                const payload = {
                    name: name,
                    slug: name,
                    type: aliasType,
                    comment: comment || null,
                    list: list
                };
                const resp = await fetch(`/api/peers/${peerId}/aliases`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (!resp.ok) {
                    throw new Error(data.message || data.detail || 'Failed to create alias');
                }
            } else {
                // Update properties via PATCH and list via PUT
                const patchPayload = { name: name, comment: comment || '' };
                const putPayload = { list: list };

                const patchResp = await fetch(`/api/peers/${peerId}/aliases/${aliasId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(patchPayload)
                });
                if (!patchResp.ok) {
                    const d = await patchResp.json();
                    throw new Error(d.message || d.detail || 'Failed to update alias properties');
                }

                const putResp = await fetch(`/api/peers/${peerId}/aliases/${aliasId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(putPayload)
                });
                if (!putResp.ok) {
                    const d = await putResp.json();
                    throw new Error(d.message || d.detail || 'Failed to update alias items');
                }
            }

            closeAliasModal();
            fetchAliases().then(() => {
                fetchWebFilterRules(true);
            });
            alert('Saved successfully');
        } catch (err) {
            alert(err.message || 'Failed to save');
        } finally {
            btn.disabled = false;
        }
    }

    async function deleteAlias(aliasId) {
        if (!confirm('Delete this alias?')) return;

        try {
            const resp = await fetch(`/api/peers/${peerId}/aliases/${aliasId}`, {
                method: 'DELETE'
            });
            const data = await resp.json();
            if (!resp.ok) {
                throw new Error(data.message || data.detail || 'Failed to delete');
            }
            fetchAliases().then(() => {
                fetchWebFilterRules(true);
            });
            alert('Deleted successfully');
        } catch (err) {
            alert(err.message || 'Failed to delete');
        }
    }

    // --------------------------------------------------------------------------
    // Autocomplete & Helpers
    // --------------------------------------------------------------------------

    function resolveAliasIdToName(aliasRef) {
        if (!aliasRef) return '';
        if (aliasRef.startsWith('@')) {
            let id = aliasRef.substring(1);
            if (id.startsWith('alias_')) id = id.substring(6);
            const found = cachedAliases.find(a => (a.id || a.slug) === id || a.name === id || a.slug === id);
            if (found) return `@${found.name || found.slug}`;
        }
        return aliasRef;
    }

    function resolveAliasNameToId(aliasRef) {
        if (!aliasRef) return '';
        if (aliasRef.startsWith('@')) {
            let name = aliasRef.substring(1);
            if (name.startsWith('alias_')) return aliasRef; // Already @alias_<id>
            const found = cachedAliases.find(a => a.name === name || a.slug === name || (a.id || a.slug) === name);
            if (found) return `@alias_${found.id || found.slug}`;
        }
        return aliasRef;
    }

    function getDomainAliasTooltip(aliasRef) {
        let id = aliasRef.startsWith('@') ? aliasRef.substring(1) : aliasRef;
        if (id.startsWith('alias_')) id = id.substring(6);

        const found = cachedAliases.find(a => (a.id || a.slug) === id || a.name === id);
        if (found && found.list) {
            const domains = found.list.map(i => i.domain || i.address || i.hostname).filter(Boolean);
            return domains.join(', ');
        }
        return aliasRef;
    }
