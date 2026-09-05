let currentPeerId = window.ALIASES_CONFIG ? window.ALIASES_CONFIG.peerId : "";
    let isPeerOnline = window.ALIASES_CONFIG ? window.ALIASES_CONFIG.isOnline : false;
    let currentPeerName = window.ALIASES_CONFIG ? window.ALIASES_CONFIG.peerName : "";
    let cachedAddressLists = [];
    let originalSlug = "";
    let cachedResolverConfig = null;

    document.addEventListener("DOMContentLoaded", function () {
        const urlParams = new URLSearchParams(window.location.search);
        const filterParam = urlParams.get('filter');

        if (currentPeerId) {
            if (!isPeerOnline) {
                window.location.href = `/peers/${currentPeerId}`;
                return;
            }
            updateNavTabLinks(currentPeerId);
            document.getElementById("aliases-workspace").style.display = "block";

            fetchAddressLists();
            fetchResolverConfig();
        } else {
            document.getElementById("aliases-workspace").style.display = "none";
        }

        if (filterParam === 'web_domain' || filterParam === 'normal') {
            setTypeFilter(filterParam);
        }

        initAliasesLiveValidation();
    });

    function updateNavTabLinks(peerId) {
        const webFilterTab = document.getElementById('nav-tab-web-filter');
        const firewallTab = document.getElementById('nav-tab-firewall');
        const aliasesTab = document.getElementById('nav-tab-aliases');

        if (webFilterTab && peerId) {
            webFilterTab.href = `/peers/${peerId}/web-filter`;
        }
        if (firewallTab && peerId) {
            firewallTab.href = `/peers/${peerId}/firewall`;
        }
        if (aliasesTab && peerId) {
            aliasesTab.href = `/peers/${peerId}/aliases`;
        }
    }

    let lastAliasesSignature = null;

    // Fetch Address Lists/Aliases from backend
    async function fetchAddressLists(silent = false) {
        try {
            const response = await fetch(`/api/peers/${currentPeerId}/aliases`);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || data.detail || 'Failed to fetch address lists');
            }

            cachedAddressLists = data.lists || [];
            cachedAddressLists.forEach(l => {
                if (!l.slug && l.id) {
                    l.slug = l.id;
                }
            });

            const signature = JSON.stringify(cachedAddressLists);
            if (signature !== lastAliasesSignature) {
                lastAliasesSignature = signature;
                renderAddressListsTable(cachedAddressLists);
            }
        } catch (err) {
            console.error('Error loading address lists:', err);
            if (lastAliasesSignature === null) {
                const tbody = document.getElementById('lists-tbody');
                if (tbody) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="6" class="text-center" style="text-align: center; padding: 3rem; color: #ef4444; font-weight: 600;">
                                <i class="fas fa-exclamation-triangle fa-2x mb-3"></i><br>
                                Error loading address lists: ${err.message}
                            </td>
                        </tr>
                    `;
                }
            }
        }
    }

    // Render Aliases Table
    function renderAddressListsTable(lists) {
        const tbody = document.getElementById('lists-tbody');
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

            // Name/Slug with count badge positioned top-right
            const tdSlug = document.createElement('td');
            tdSlug.className = 'cell-name';
            tdSlug.style.fontWeight = '700';
            const items = list.list || [];
            tdSlug.innerHTML = `
                <div class="alias-name-wrapper">
                    <span class="alias-name-text">${list.name || list.slug}</span>
                    <span onclick="openEditListModal('${list.slug}')" class="alias-count-badge" title="Click to Edit Alias">${items.length}</span>
                </div>
            `;
            tr.appendChild(tdSlug);

            // Type Column (Unified Box)
            const tdType = document.createElement('td');
            tdType.className = 'cell-type';
            const isWebDomainType = list.type === 'web_domain';
            const typeBadgeClass = isWebDomainType ? 'alias-tag alias-tag-domain' : 'alias-tag alias-tag-normal';
            const typeBadgeLabel = isWebDomainType ? 'Web domain' : 'Normal';
            tdType.innerHTML = `<span class="${typeBadgeClass}">${typeBadgeLabel}</span>`;
            tr.appendChild(tdType);

            // Addresses Preview (Unified Boxes: Normal is Gray, Web Domain is Amber)
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

                // Hostnames & IPs in Normal aliases are Gray; only Web domains are Amber
                const itemTagClass = isDomain ? 'alias-tag alias-tag-domain' : 'alias-tag alias-tag-normal';
                return `<span class="${itemTagClass}" title="${hoverTitle}" style="margin: 2px;">${val}</span>`;
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

            const peerName = currentPeerName;

            tdActions.innerHTML = `
                <div style="display: flex; gap: 0.5rem; justify-content: center; align-items: center;">
                    <a href="/peers/${currentPeerId}/filtering?name=${encodeURIComponent(peerName)}&scope=alias&alias=${list.slug}" class="btn-delete btn-edit-action" title="DNS Filter" style="display: flex;align-items: center;justify-content: center;text-decoration: none;display: none;">
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

        // Re-apply active filter and search query immediately after rendering
        filterListsTable();
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

        clearAllFieldErrors();

        const slugCounter = document.getElementById('listSlug-counter');
        if (slugCounter) {
            slugCounter.textContent = '0 / 200';
            slugCounter.className = 'char-counter';
        }
        const commentCounter = document.getElementById('listComment-counter');
        if (commentCounter) {
            commentCounter.textContent = '0 / 200';
            commentCounter.className = 'char-counter';
        }

        // Default type based on current active filter
        const defaultType = (currentTypeFilter === 'web_domain') ? 'web_domain' : 'normal';
        document.getElementById('listType').value = defaultType;
        document.getElementById('listType').disabled = false;
        onListTypeChange();

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

        document.getElementById('listModalTitle').textContent = 'Edit Alias';
        document.getElementById('listActionType').value = 'edit';
        document.getElementById('btn-submit-list').textContent = 'Save Changes';
        originalSlug = slug;

        clearAllFieldErrors();

        const nameVal = listObj.name || slug;
        document.getElementById('listSlug').value = nameVal;
        document.getElementById('listSlug').disabled = !isNewAgent; // Disabled for old agents that don't support renaming
        const slugCounter = document.getElementById('listSlug-counter');
        if (slugCounter) {
            slugCounter.textContent = `${nameVal.length} / 200`;
            slugCounter.className = 'char-counter' + (nameVal.length > 180 ? (nameVal.length > 200 ? ' error' : ' warning') : '');
        }

        const commentVal = listObj.comment || '';
        document.getElementById('listComment').value = commentVal;
        const commentCounter = document.getElementById('listComment-counter');
        if (commentCounter) {
            commentCounter.textContent = `${commentVal.length} / 200`;
            commentCounter.className = 'char-counter' + (commentVal.length > 180 ? (commentVal.length > 200 ? ' error' : ' warning') : '');
        }

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
            // re-validate on type change
            if (input.value.trim()) {
                input.dispatchEvent(new Event('input'));
            }
        });
    }

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
        rowDiv.style.flexDirection = 'column';
        rowDiv.style.marginBottom = '0.75rem';

        rowDiv.innerHTML = `
            <div style="display: flex; gap: 0.75rem; align-items: center;">
                <div style="flex: 1.2;">
                    <input type="text" placeholder="${placeholder}" class="addr-input" required value="${address}" style="width: 100%; padding: 0.5rem 0.75rem; border: 1px solid var(--nk-border); border-radius: var(--nk-radius-sm); font-size: 0.88rem;">
                </div>
                <div style="flex: 1;">
                    <input type="text" placeholder="Comment (e.g. Dev Server)" class="addr-comment" value="${safeComment}" style="width: 100%; padding: 0.5rem 0.75rem; border: 1px solid var(--nk-border); border-radius: var(--nk-radius-sm); font-size: 0.88rem;" maxlength="200">
                </div>
                <button type="button" class="btn-delete" onclick="removeAddressRow(this)" style="padding: 0.5rem; display: flex; align-items: center; justify-content: center; height: 38px; width: 38px;">
                    <i class="far fa-trash-alt"></i>
                </button>
            </div>
            <div class="field-error-msg row-error-msg" style="display: none;"></div>
        `;
        container.appendChild(rowDiv);

        // Bind live input validation for the new row
        const addrInput = rowDiv.querySelector('.addr-input');
        const errorDiv = rowDiv.querySelector('.row-error-msg');
        if (addrInput) {
            addrInput.addEventListener('input', () => {
                const listType = document.getElementById('listType').value;
                const res = validateAliasEntry(addrInput.value, listType);
                if (!res.valid) {
                    addrInput.classList.add('is-invalid');
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${res.error}`;
                    errorDiv.style.display = 'flex';
                } else {
                    addrInput.classList.remove('is-invalid');
                    errorDiv.textContent = '';
                    errorDiv.style.display = 'none';
                }
            });
        }
    }

    function removeAddressRow(button) {
        const row = button.closest('.address-row');
        if (row) row.remove();
        const container = document.getElementById('address-rows-container');
        if (container.children.length === 0) {
            addAddressRow();
        }
    }

    function closeListModal() {
        document.getElementById('listModal').classList.remove('active');
        clearAllFieldErrors();
    }

    // =========================================================================
    // Real-Time Validation Functions (Simplified & First-Char Detection)
    // =========================================================================

    function ip_address_validator(val) {
        if (!val || typeof val !== 'string') return false;
        const trimmed = val.trim();
        if (trimmed.includes(':')) return false;

        const cidrMatch = trimmed.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\/(\d{1,2}))?$/);
        if (!cidrMatch) return false;

        for (let i = 1; i <= 4; i++) {
            const octetStr = cidrMatch[i];
            if (octetStr.length > 1 && octetStr.startsWith('0')) return false;
            const num = parseInt(octetStr, 10);
            if (num < 0 || num > 255) return false;
        }

        if (cidrMatch[5] !== undefined) {
            const maskStr = cidrMatch[5];
            if (maskStr.length > 1 && maskStr.startsWith('0')) return false;
            const mask = parseInt(maskStr, 10);
            if (mask < 0 || mask > 32) return false;
        }

        return true;
    }

    function getLocalForwardingDomains() {
        const domains = [];
        const upstreams = (cachedResolverConfig && cachedResolverConfig.upstream_dns) || [];
        upstreams.forEach(upstream => {
            const match = upstream.match(/^\[\/([a-zA-Z0-9._-]+)\/\](.+)$/);
            if (match) {
                domains.push(match[1].toLowerCase());
            }
        });
        return domains;
    }

    function isHostnameMatchingLocalDomain(trimmed) {
        const localDomains = getLocalForwardingDomains();
        if (!localDomains || localDomains.length === 0) {
            return {
                valid: false,
                error: 'No Local Domain Server in Resolver Settings'
            };
        }

        const lowerHost = trimmed.toLowerCase();
        const matchesLocalDomain = localDomains.some(d => {
            return lowerHost === d || lowerHost.endsWith('.' + d);
        });

        if (!matchesLocalDomain) {
            return {
                valid: false,
                error: `Must match a Local Domain Server`
                // error: `Must match a Local Domain Server (${localDomains.join(', ')})`
            };
        }

        return { valid: true };
    }

    function hostname_validator(val) {
        if (!val || typeof val !== 'string') return false;
        const trimmed = val.trim();
        if (window.validateHostname) {
            const res = window.validateHostname(trimmed);
            return res.valid;
        }
        const hostnameRegex = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/;
        return hostnameRegex.test(trimmed);
    }

    function validateAliasName(name) {
        if (!name || typeof name !== 'string' || !name.trim()) {
            return { valid: false, error: 'Required' };
        }
        const trimmed = name.trim();
        if (trimmed.length > 200) {
            return { valid: false, error: 'Max 200 characters' };
        }
        return { valid: true };
    }

    function validateAliasComment(comment) {
        if (!comment || typeof comment !== 'string') return { valid: true };
        if (comment.length > 200) {
            return { valid: false, error: 'Max 200 characters' };
        }
        return { valid: true };
    }

    function validateAliasEntry(value, type) {
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
            // Normal alias: IPv4 or Hostname matching local domain servers
            const firstChar = trimmed[0];

            // Digit (0-9): IPv4 Format or Hostname starting with digit
            if (/^[0-9]/.test(firstChar)) {
                const ipv4Res = parseAndValidateIPv4(trimmed, { requireMask: false, allowMask: true, normalizeSubnet: true });
                if (ipv4Res.valid) {
                    return { valid: true, entryType: 'address', normalized: ipv4Res.normalized, ipData: ipv4Res };
                }
                // Check if valid hostname starting with digit
                const hostRes = window.validateHostname ? window.validateHostname(trimmed) : null;
                if (hostRes && hostRes.valid) {
                    const localRes = isHostnameMatchingLocalDomain(trimmed);
                    if (!localRes.valid) {
                        return localRes;
                    }
                    return { valid: true, entryType: 'hostname', normalized: trimmed };
                }
                return ipv4Res;
            }

            // Letter (a-zA-Z): Hostname must match configured local domain servers
            if (/^[a-zA-Z]/.test(firstChar)) {
                const hostRes = window.validateHostname ? window.validateHostname(trimmed) : null;
                if (hostRes) {
                    if (!hostRes.valid) {
                        return { valid: false, error: hostRes.error || 'Invalid hostname' };
                    }
                } else if (!hostname_validator(trimmed)) {
                    return { valid: false, error: 'Invalid hostname' };
                }

                // Strictly verify against Local Domain Servers (Resolver Settings)
                const localRes = isHostnameMatchingLocalDomain(trimmed);
                if (!localRes.valid) {
                    return localRes;
                }

                return { valid: true, entryType: 'hostname', normalized: trimmed };
            }

            return { valid: false, error: 'Invalid format' };
        }
    }

    function setFieldError(inputId, errorMsg) {
        const input = document.getElementById(inputId);
        const errorDiv = document.getElementById(`${inputId}-error`);
        if (input) input.classList.add('is-invalid');
        if (errorDiv) {
            errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${errorMsg}`;
            errorDiv.style.display = 'flex';
        }
    }

    function clearFieldError(inputId) {
        const input = document.getElementById(inputId);
        const errorDiv = document.getElementById(`${inputId}-error`);
        if (input) input.classList.remove('is-invalid');
        if (errorDiv) {
            errorDiv.textContent = '';
            errorDiv.style.display = 'none';
        }
    }

    function clearAllFieldErrors() {
        ['listSlug', 'listComment', 'listItems'].forEach(id => clearFieldError(id));
        document.querySelectorAll('#address-rows-container .addr-input').forEach(inp => {
            inp.classList.remove('is-invalid');
        });
        document.querySelectorAll('#address-rows-container .row-error-msg').forEach(msg => {
            msg.textContent = '';
            msg.style.display = 'none';
        });
        document.querySelectorAll('#local-dns-rows-container .is-invalid').forEach(inp => {
            inp.classList.remove('is-invalid');
        });
        document.querySelectorAll('#local-dns-rows-container .row-error-msg').forEach(msg => {
            msg.textContent = '';
            msg.style.display = 'none';
        });
    }

    function initAliasesLiveValidation() {
        const listSlug = document.getElementById('listSlug');
        const slugCounter = document.getElementById('listSlug-counter');
        if (listSlug) {
            listSlug.addEventListener('input', () => {
                const len = listSlug.value.length;
                if (slugCounter) {
                    slugCounter.textContent = `${len} / 200`;
                    slugCounter.className = 'char-counter' + (len > 180 ? (len > 200 ? ' error' : ' warning') : '');
                }
                const res = validateAliasName(listSlug.value);
                if (!res.valid) {
                    setFieldError('listSlug', res.error);
                } else {
                    clearFieldError('listSlug');
                }
            });
        }

        const listComment = document.getElementById('listComment');
        const commentCounter = document.getElementById('listComment-counter');
        if (listComment) {
            listComment.addEventListener('input', () => {
                const len = listComment.value.length;
                if (commentCounter) {
                    commentCounter.textContent = `${len} / 200`;
                    commentCounter.className = 'char-counter' + (len > 180 ? (len > 200 ? ' error' : ' warning') : '');
                }
                const res = validateAliasComment(listComment.value);
                if (!res.valid) {
                    setFieldError('listComment', res.error);
                } else {
                    clearFieldError('listComment');
                }
            });
        }
    }

    // Save/Update Alias List
    async function submitAddressList(e) {
        if (e) e.preventDefault();
        clearAllFieldErrors();

        const btnSubmit = document.getElementById('btn-submit-list');
        const actionType = document.getElementById('listActionType').value;
        const slug = document.getElementById('listSlug').value.trim();
        const comment = document.getElementById('listComment').value.trim();
        const listType = document.getElementById('listType').value;

        let hasError = false;
        let firstInvalidElement = null;

        // 1. Validate Name
        const nameRes = validateAliasName(slug);
        if (!nameRes.valid) {
            setFieldError('listSlug', nameRes.error);
            hasError = true;
            if (!firstInvalidElement) firstInvalidElement = document.getElementById('listSlug');
        }

        // 2. Validate Comment
        const commentRes = validateAliasComment(comment);
        if (!commentRes.valid) {
            setFieldError('listComment', commentRes.error);
            hasError = true;
            if (!firstInvalidElement) firstInvalidElement = document.getElementById('listComment');
        }

        // 3. Validate Items List
        const rowDivs = document.querySelectorAll('#address-rows-container .address-row');
        const entries = [];
        const seenValues = new Set();

        rowDivs.forEach(row => {
            const addrInput = row.querySelector('.addr-input');
            const commentInput = row.querySelector('.addr-comment');
            const errorDiv = row.querySelector('.row-error-msg');
            const val = addrInput ? addrInput.value.trim() : '';
            const addrComment = (commentInput ? commentInput.value.trim() : '') || null;

            if (!val) {
                if (addrInput) addrInput.classList.add('is-invalid');
                if (errorDiv) {
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> Required`;
                    errorDiv.style.display = 'flex';
                }
                hasError = true;
                if (!firstInvalidElement) firstInvalidElement = addrInput;
                return;
            }

            const itemRes = validateAliasEntry(val, listType);
            if (!itemRes.valid) {
                if (addrInput) addrInput.classList.add('is-invalid');
                if (errorDiv) {
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${itemRes.error}`;
                    errorDiv.style.display = 'flex';
                }
                hasError = true;
                if (!firstInvalidElement) firstInvalidElement = addrInput;
                return;
            }

            const normalizedVal = itemRes.normalized || val;
            if (addrInput && addrInput.value !== normalizedVal) {
                addrInput.value = normalizedVal;
            }

            // Check for duplicate items
            const lowerVal = normalizedVal.toLowerCase();
            if (seenValues.has(lowerVal)) {
                if (addrInput) addrInput.classList.add('is-invalid');
                if (errorDiv) {
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> Duplicate item`;
                    errorDiv.style.display = 'flex';
                }
                hasError = true;
                if (!firstInvalidElement) firstInvalidElement = addrInput;
                return;
            }
            seenValues.add(lowerVal);

            // Construct valid entry based on type and first char
            if (listType === 'web_domain') {
                entries.push({ domain: normalizedVal, comment: addrComment });
            } else {
                if (itemRes.entryType === 'address') {
                    entries.push({ address: normalizedVal, comment: addrComment });
                } else {
                    entries.push({ hostname: normalizedVal, comment: addrComment });
                }
            }
        });

        if (entries.length === 0) {
            setFieldError('listItems', 'At least 1 item required');
            hasError = true;
        } else if (entries.length > 256) {
            setFieldError('listItems', 'Max 256 items');
            hasError = true;
        }

        if (hasError) {
            if (firstInvalidElement) firstInvalidElement.focus();
            return;
        }

        btnSubmit.disabled = true;

        const isNewAgent = cachedAddressLists.length > 0 && cachedAddressLists.some(l => l.id !== undefined);

        if (actionType === 'edit') {
            if (isNewAgent) {
                try {
                    // 1. Update name/comment via PATCH
                    const patchResp = await fetch(`/api/peers/${currentPeerId}/aliases/${originalSlug}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: slug, comment: comment })
                    });
                    if (!patchResp.ok) {
                        const data = await patchResp.json();
                        throw new Error(data.message || data.error || data.detail || 'Failed to save');
                    }

                    // 2. Update address list via PUT
                    const putResp = await fetch(`/api/peers/${currentPeerId}/aliases/${originalSlug}`, {
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
                    if (window.showSuccess) window.showSuccess('Saved');
                    else alert('Saved successfully');
                } catch (err) {
                    if (window.showError) window.showError(err.message || 'Failed to save');
                    else alert(err.message || 'Failed to save');
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
                    const response = await fetch(`/api/peers/${currentPeerId}/aliases/${originalSlug}`, {
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
                    if (window.showSuccess) window.showSuccess('Saved');
                    else alert('Saved successfully');
                } catch (err) {
                    if (window.showError) window.showError(err.message || 'Failed to save');
                    else alert(err.message || 'Failed to save');
                } finally {
                    btnSubmit.disabled = false;
                }
            }
        } else {
            // Create New Alias
            const payload = {
                name: slug,
                slug: slug,
                comment: comment,
                type: listType,
                list: entries
            };

            try {
                const response = await fetch(`/api/peers/${currentPeerId}/aliases`, {
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
                if (window.showSuccess) window.showSuccess('Saved');
                else alert('Saved successfully');
            } catch (err) {
                if (window.showError) window.showError(err.message || 'Failed to save');
                else alert(err.message || 'Failed to save');
            } finally {
                btnSubmit.disabled = false;
            }
        }
    }

    // Delete Alias
    async function deleteAddressList(slug) {
        const listObj = cachedAddressLists.find(l => l.slug === slug);
        const displayName = listObj ? (listObj.name || slug) : slug;
        if (!confirm(`Delete alias "${displayName}"?`)) {
            return;
        }

        try {
            const response = await fetch(`/api/peers/${currentPeerId}/aliases/${slug}`, {
                method: 'DELETE'
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || data.error || data.detail || 'Failed to delete');
            }

            fetchAddressLists();
            if (window.showSuccess) window.showSuccess('Deleted');
            else alert('Deleted successfully');
        } catch (err) {
            if (window.showError) window.showError(err.message || 'Failed to delete');
            else alert(err.message || 'Failed to delete');
        }
    }

    // Sync address lists to config
    async function syncAddressLists() {
        const btnSync = document.getElementById('sync-lists-btn');
        if (btnSync) btnSync.disabled = true;

        try {
            const response = await fetch(`/api/peers/${currentPeerId}/aliases/sync`, {
                method: 'POST'
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || data.error || data.detail || 'Failed to sync');
            }

            if (window.showSuccess) window.showSuccess('Synced');
            else alert('Synced successfully');
            fetchAddressLists();
        } catch (err) {
            if (window.showError) window.showError(err.message || 'Failed to sync');
            else alert(err.message || 'Failed to sync');
        } finally {
            if (btnSync) btnSync.disabled = false;
        }
    }

    // Resolver Configuration Settings
    let originalUpstreams = [];

    async function fetchResolverConfig() {
        try {
            const response = await fetch(`/api/peers/${currentPeerId}/resolver-config`);
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
            const originalContent = resolverBtn.innerHTML;
            resolverBtn.disabled = true;
            resolverBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Loading...`;

            fetchResolverConfig().then(() => {
                resolverBtn.disabled = false;
                resolverBtn.innerHTML = originalContent;
                populateResolverModal();
            });
        }
    }

    function validateDnsDomain(domain) {
        if (!domain || !domain.trim()) {
            return { valid: false, error: 'Required' };
        }
        const trimmed = domain.trim();
        if (trimmed.includes('*')) {
            return { valid: false, error: 'Wildcards not allowed' };
        }
        const parts = trimmed.split('.');
        if (parts.length < 2) {
            return { valid: false, error: 'Invalid domain' };
        }
        const domainRegex = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/;
        if (!domainRegex.test(trimmed)) {
            return { valid: false, error: 'Invalid domain' };
        }
        return { valid: true };
    }

    function validateDnsResolvers(dnsIp) {
        if (!dnsIp || !dnsIp.trim()) {
            return { valid: false, error: 'Required' };
        }
        const trimmed = dnsIp.trim();
        if (trimmed.includes('/') || trimmed.includes(':')) {
            return { valid: false, error: 'Invalid IP address' };
        }
        const octets = trimmed.split('.');
        if (octets.length !== 4 || !octets.every(o => /^\d+$/.test(o))) {
            return { valid: false, error: 'Invalid IP address' };
        }
        for (const octet of octets) {
            if (octet.length > 1 && octet.startsWith('0')) return { valid: false, error: 'Invalid IP address' };
            const num = parseInt(octet, 10);
            if (num < 0 || num > 255) {
                return { valid: false, error: 'Invalid IP address' };
            }
        }
        return { valid: true };
    }

    function addLocalDnsRow(domain = '', dnsIp = '') {
        const container = document.getElementById('local-dns-rows-container');
        const rowDiv = document.createElement('div');
        rowDiv.className = 'local-dns-row';
        rowDiv.style.display = 'flex';
        rowDiv.style.flexDirection = 'column';
        rowDiv.style.marginBottom = '0.75rem';

        rowDiv.innerHTML = `
            <div style="display: flex; gap: 0.75rem; align-items: center;">
                <div style="flex: 1;">
                    <input type="text" placeholder="Domain / Zone (e.g. company.local)" class="local-domain-input" required value="${domain}" style="width: 100%; padding: 0.5rem 0.75rem; border: 1px solid var(--nk-border); border-radius: var(--nk-radius-sm); font-size: 0.88rem;">
                </div>
                <div style="flex: 1;">
                    <input type="text" placeholder="Resolver IP (e.g. 192.168.2.34)" class="local-dns-input" required value="${dnsIp}" style="width: 100%; padding: 0.5rem 0.75rem; border: 1px solid var(--nk-border); border-radius: var(--nk-radius-sm); font-size: 0.88rem;">
                </div>
                <button type="button" class="btn-delete" onclick="removeLocalDnsRow(this)" style="padding: 0.5rem; display: flex; align-items: center; justify-content: center; height: 38px; width: 38px;">
                    <i class="far fa-trash-alt"></i>
                </button>
            </div>
            <div class="field-error-msg row-error-msg" style="display: none;"></div>
        `;
        container.appendChild(rowDiv);

        // Bind live input validation for DNS rows
        const domainInput = rowDiv.querySelector('.local-domain-input');
        const ipInput = rowDiv.querySelector('.local-dns-input');
        const errorDiv = rowDiv.querySelector('.row-error-msg');

        const validateRow = () => {
            const dVal = domainInput ? domainInput.value.trim() : '';
            const ipVal = ipInput ? ipInput.value.trim() : '';

            if (dVal) {
                const dRes = validateDnsDomain(dVal);
                if (!dRes.valid) {
                    domainInput.classList.add('is-invalid');
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${dRes.error}`;
                    errorDiv.style.display = 'flex';
                    return;
                } else {
                    domainInput.classList.remove('is-invalid');
                }
            } else {
                domainInput.classList.remove('is-invalid');
            }

            if (ipVal) {
                const ipRes = validateDnsResolvers(ipVal);
                if (!ipRes.valid) {
                    ipInput.classList.add('is-invalid');
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${ipRes.error}`;
                    errorDiv.style.display = 'flex';
                    return;
                } else {
                    ipInput.classList.remove('is-invalid');
                }
            } else {
                ipInput.classList.remove('is-invalid');
            }

            errorDiv.textContent = '';
            errorDiv.style.display = 'none';
        };

        if (domainInput) domainInput.addEventListener('input', validateRow);
        if (ipInput) ipInput.addEventListener('input', validateRow);
    }

    function removeLocalDnsRow(button) {
        button.closest('.local-dns-row').remove();
    }

    function populateResolverModal() {
        const container = document.getElementById('local-dns-rows-container');
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
        clearAllFieldErrors();
    }

    async function submitResolverConfig(e) {
        e.preventDefault();
        clearAllFieldErrors();

        const btnSubmit = document.getElementById('btn-submit-resolver');
        const domainInputs = document.querySelectorAll('#local-dns-rows-container .local-domain-input');
        const dnsInputs = document.querySelectorAll('#local-dns-rows-container .local-dns-input');

        const localUpstreams = [];
        let hasError = false;
        let firstInvalidInput = null;

        for (let i = 0; i < domainInputs.length; i++) {
            const dInput = domainInputs[i];
            const ipInput = dnsInputs[i];
            const rowDiv = dInput.closest('.local-dns-row');
            const errorDiv = rowDiv ? rowDiv.querySelector('.row-error-msg') : null;

            const domain = dInput.value.trim();
            const dnsIp = ipInput.value.trim();

            if (!domain && !dnsIp && domainInputs.length > 1) {
                continue;
            }

            if (!domain) {
                dInput.classList.add('is-invalid');
                if (errorDiv) {
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> Required`;
                    errorDiv.style.display = 'flex';
                }
                hasError = true;
                if (!firstInvalidInput) firstInvalidInput = dInput;
                continue;
            }

            const dRes = validateDnsDomain(domain);
            if (!dRes.valid) {
                dInput.classList.add('is-invalid');
                if (errorDiv) {
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${dRes.error}`;
                    errorDiv.style.display = 'flex';
                }
                hasError = true;
                if (!firstInvalidInput) firstInvalidInput = dInput;
                continue;
            }

            if (!dnsIp) {
                ipInput.classList.add('is-invalid');
                if (errorDiv) {
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> Required`;
                    errorDiv.style.display = 'flex';
                }
                hasError = true;
                if (!firstInvalidInput) firstInvalidInput = ipInput;
                continue;
            }

            const ipRes = validateDnsResolvers(dnsIp);
            if (!ipRes.valid) {
                ipInput.classList.add('is-invalid');
                if (errorDiv) {
                    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${ipRes.error}`;
                    errorDiv.style.display = 'flex';
                }
                hasError = true;
                if (!firstInvalidInput) firstInvalidInput = ipInput;
                continue;
            }

            localUpstreams.push(`[/${domain}/]${dnsIp}`);
        }

        if (hasError) {
            if (firstInvalidInput) firstInvalidInput.focus();
            return;
        }

        btnSubmit.disabled = true;
        btnSubmit.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Saving...`;

        const finalUpstreams = [...originalUpstreams, ...localUpstreams];

        const payload = {
            upstream_dns: finalUpstreams,
            bootstrap_dns: (cachedResolverConfig && cachedResolverConfig.bootstrap_dns) || ["9.9.9.9"],
            all_servers: (cachedResolverConfig && cachedResolverConfig.all_servers) || false,
            fastest_addr: (cachedResolverConfig && cachedResolverConfig.fastest_addr) || false
        };

        try {
            const response = await fetch(`/api/peers/${currentPeerId}/resolver-config`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || data.error || 'Failed to save');
            }

            if (window.showSuccess) window.showSuccess('Saved');
            else alert("Saved successfully");
            await fetchResolverConfig();
            closeResolverModal();
        } catch (err) {
            if (window.showError) window.showError(err.message || 'Failed to save');
            else alert(err.message || 'Failed to save');
        } finally {
            btnSubmit.disabled = false;
            btnSubmit.innerHTML = "Save Settings";
        }
    }

    let currentTypeFilter = 'all';

    function setTypeFilter(type) {
        currentTypeFilter = type;
        document.querySelectorAll('.type-filter-chip').forEach(btn => {
            if (btn.getAttribute('data-filter') === type) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
        filterListsTable();
    }

    // Filter table rows based on input and type filter
    function filterListsTable() {
        const searchInput = document.getElementById('search-lists-input');
        const searchVal = searchInput ? searchInput.value.toLowerCase().trim() : '';
        const rows = document.querySelectorAll('#lists-tbody tr');

        rows.forEach(row => {
            if (row.cells.length <= 1) return; // Skip empty row colspan
            const rowType = row.getAttribute('data-list-type') || 'normal';
            const rowText = row.textContent.toLowerCase();

            const matchesSearch = !searchVal || rowText.includes(searchVal);
            const matchesType = (currentTypeFilter === 'all') || (rowType === currentTypeFilter);

            if (matchesSearch && matchesType) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    }
