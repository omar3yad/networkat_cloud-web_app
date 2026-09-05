const peerId = window.FILTERING_CONFIG ? window.FILTERING_CONFIG.peerId : "";
    const isOnline = window.FILTERING_CONFIG ? window.FILTERING_CONFIG.isOnline : false;

    // Scope Management Variables
    let currentScope = 'global';
    let selectedAliasSlug = '';
    let peerAliases = [];

    // Parse URL Query Params
    const urlParams = new URLSearchParams(window.location.search);
    const initialScope = urlParams.get('scope') || 'global';
    const initialAlias = urlParams.get('alias') || '';
    const PREDEFINED_CATEGORIES = [
        {
            name: "Artificial Intelligence",
            key: "ai",
            services: [
                { id: "chatgpt", name: "ChatGPT", icon: "fas fa-robot", domains: ["chatgpt.com", "openai.com"] },
                { id: "claude", name: "Claude", icon: "fas fa-brain", domains: ["claude.ai"] },
                { id: "copilot", name: "Copilot", icon: "fas fa-microchip", domains: ["copilot.microsoft.com"] },
                { id: "deepseek", name: "DeepSeek", icon: "fas fa-code", domains: ["deepseek.com"] },
                { id: "gemini", name: "Gemini", icon: "fas fa-wand-magic-sparkles", domains: ["gemini.google.com"] },
                { id: "grok", name: "Grok", icon: "fas fa-bolt", domains: ["grok.com", "x.ai"] },
                { id: "manus", name: "Manus", icon: "fas fa-hand", domains: ["manus.im"] },
                { id: "meta_ai", name: "Meta AI", icon: "fas fa-infinity", domains: ["meta.ai"] },
                { id: "perplexity", name: "Perplexity", icon: "fas fa-magnifying-glass", domains: ["perplexity.ai"] }
            ]
        },
        {
            name: "Content Delivery (CDN)",
            key: "cdn",
            services: [
                { id: "cloudflare", name: "Cloudflare", icon: "fas fa-cloud", domains: ["cloudflare.com"] }
            ]
        },
        {
            name: "Dating Services",
            key: "dating",
            services: [
                { id: "plenty_of_fish", name: "Plenty of Fish", icon: "fas fa-heart", domains: ["pof.com"] },
                { id: "tinder", name: "Tinder", icon: "fas fa-fire", domains: ["tinder.com"] },
                { id: "wizz", name: "Wizz", icon: "fas fa-comments", domains: ["wizzapp.com"] }
            ]
        },
        {
            name: "Gambling & Betting",
            key: "gambling",
            services: [
                { id: "betano", name: "Betano", icon: "fas fa-dice", domains: ["betano.com"] },
                { id: "betfair", name: "Betfair", icon: "fas fa-coins", domains: ["betfair.com"] },
                { id: "betway", name: "Betway", icon: "fas fa-ticket", domains: ["betway.com"] },
                { id: "blaze", name: "Blaze", icon: "fas fa-gem", domains: ["blaze.com"] }
            ]
        },
        {
            name: "Social Networks",
            key: "social",
            services: [
                { id: "facebook", name: "Facebook", icon: "fab fa-facebook", domains: ["facebook.com", "fb.com"] },
                { id: "instagram", name: "Instagram", icon: "fab fa-instagram", domains: ["instagram.com"] },
                { id: "tiktok", name: "TikTok", icon: "fab fa-tiktok", domains: ["tiktok.com"] },
                { id: "twitter", name: "X (Twitter)", icon: "fab fa-x-twitter", domains: ["twitter.com", "x.com"] }
            ]
        },
        {
            name: "Streaming & Media",
            key: "streaming",
            services: [
                { id: "youtube", name: "YouTube", icon: "fab fa-youtube", domains: ["youtube.com", "youtu.be"] },
                { id: "netflix", name: "Netflix", icon: "fas fa-film", domains: ["netflix.com"] },
                { id: "twitch", name: "Twitch", icon: "fab fa-twitch", domains: ["twitch.tv"] }
            ]
        }
    ];

    let blockedState = {};
    let initialState = {};

    function showToast(msg) {
        const toast = document.getElementById('toast-msg');
        toast.innerHTML = `<i class="fas fa-check-circle" style="color:var(--nk-blue-primary)"></i> ${msg}`;
        toast.style.display = 'block';
        setTimeout(() => { toast.style.display = 'none'; }, 3000);
    }

    async function loadFilteringConfig() {
        if (currentScope === 'alias' && !selectedAliasSlug) {
            blockedState = {};
            initialState = {};
            renderCategoryTabs();
            renderCategories();
            checkChanges();
            return;
        }
        try {
            const url = currentScope === 'global'
                ? `/api/peers/${peerId}/adguard/blocked_services`
                : `/api/peers/${peerId}/adguard/clients/${selectedAliasSlug}/blocked_services`;
            const response = await fetch(url);
            if (response.ok) {
                const data = await response.json();
                const blockedIds = Array.isArray(data) ? data : (data.ids || []);

                PREDEFINED_CATEGORIES.forEach(cat => {
                    cat.services.forEach(srv => {
                        blockedState[srv.id] = blockedIds.includes(srv.id);
                    });
                });

                initialState = JSON.parse(JSON.stringify(blockedState));
            }
        } catch (e) {
            console.error("Error loading blocked services:", e);
        } finally {
            renderCategoryTabs();
            renderCategories();
            checkChanges();
        }
    }

    function renderCategoryTabs() {
        const tabsContainer = document.getElementById('category-tabs');
        let tabsHtml = '';

        PREDEFINED_CATEGORIES.forEach((cat, index) => {
            const activeClass = index === 0 ? 'active' : '';
            tabsHtml += `<button class="tab-btn ${activeClass}" onclick="scrollToCategory('${cat.key}', this)">${cat.name}</button>`;
        });

        tabsContainer.innerHTML = tabsHtml;
    }
    function scrollToCategory(categoryKey, btnEl) {
        if (btnEl) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            btnEl.classList.add('active');
        }

        const targetSection = document.getElementById(`cat-section-${categoryKey}`);
        if (targetSection) {
            // احسب المسافة الإضافية للشريط العلوي والتابات (غير الـ 140 لو محتاج مسافة أكبر أو أقل)
            const offset = 140;
            const bodyRect = document.body.getBoundingClientRect().top;
            const elementRect = targetSection.getBoundingClientRect().top;
            const elementPosition = elementRect - bodyRect;
            const offsetPosition = elementPosition - offset;

            window.scrollTo({
                top: offsetPosition,
                behavior: 'smooth'
            });
        }
    }
    function renderCategories() {
        const container = document.getElementById('categories-container');
        let html = '';

        PREDEFINED_CATEGORIES.forEach(cat => {
            html += `
        <div class="category-section" id="cat-section-${cat.key}" data-key="${cat.key}" style="display: block; margin-bottom: 2rem;">
            <div class="category-header">
                <div class="category-title-group">
                    <span class="category-title">${cat.name}</span>
                    <span class="category-badge">${cat.services.length} Apps</span>
                </div>
                <div class="category-controls">
                    <button class="btn-cat-action btn-cat-block" onclick="toggleCategory('${cat.key}', true)">
                        <i class="fas fa-ban"></i> Block All
                    </button>
                    <button class="btn-cat-action btn-cat-allow" onclick="toggleCategory('${cat.key}', false)">
                        <i class="fas fa-check"></i> Allow All
                    </button>
                </div>
            </div>
            <div class="services-grid">
        `;

            cat.services.forEach(srv => {
                const isBlocked = blockedState[srv.id];
                const isChecked = isBlocked ? 'checked' : '';
                const activeClass = isBlocked ? 'blocked-active' : 'allowed-active';
                const badgeText = isBlocked ? 'Blocked' : 'Allowed';
                const badgeClass = isBlocked ? 'blocked' : 'allowed';

                html += `
            <div class="service-card ${activeClass}" id="card-${srv.id}">
                <div class="service-top">
                    <div class="service-info">
                        <div class="service-icon"><i class="${srv.icon}"></i></div>
                        <div class="service-details">
                            <span class="service-name">${srv.name}</span>
                            <span class="status-pill ${badgeClass}" id="badge-${srv.id}">${badgeText}</span>
                        </div>
                    </div>
                    <label class="switch">
                        <input type="checkbox" ${isChecked} onchange="onServiceToggle('${srv.id}', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
            </div>
            `;
            });

            html += `
            </div>
        </div>
        `;
        });

        container.innerHTML = html;
    }
    function checkChanges() {
        const hasChanges = Object.keys(blockedState).some(
            key => blockedState[key] !== initialState[key]
        );

        const bar = document.getElementById('floating-bar');
        const applyBtn = document.getElementById('apply-btn');

        if (hasChanges) {
            bar.classList.add('visible');
            applyBtn.removeAttribute('disabled');
        } else {
            bar.classList.remove('visible');
            applyBtn.setAttribute('disabled', 'true');
        }
    }

    function onServiceToggle(serviceId, isBlocked) {
        blockedState[serviceId] = isBlocked;

        const card = document.getElementById(`card-${serviceId}`);
        const badge = document.getElementById(`badge-${serviceId}`);

        if (card && badge) {
            if (isBlocked) {
                card.classList.remove('allowed-active');
                card.classList.add('blocked-active');
                badge.className = 'status-pill blocked';
                badge.innerText = 'Blocked';
            } else {
                card.classList.remove('blocked-active');
                card.classList.add('allowed-active');
                badge.className = 'status-pill allowed';
                badge.innerText = 'Allowed';
            }
        }

        checkChanges();
    }

    function toggleCategory(catKey, shouldBlock) {
        const category = PREDEFINED_CATEGORIES.find(c => c.key === catKey);
        if (!category) return;

        category.services.forEach(srv => {
            blockedState[srv.id] = shouldBlock;
        });

        renderCategories();
        checkChanges();
    }

    function toggleAllGlobal(shouldBlock) {
        PREDEFINED_CATEGORIES.forEach(cat => {
            cat.services.forEach(srv => {
                blockedState[srv.id] = shouldBlock;
            });
        });

        renderCategories();
        checkChanges();
    }

    function discardChanges() {
        blockedState = JSON.parse(JSON.stringify(initialState));
        renderCategories();
        checkChanges();
    }

    async function saveChangesToServer() {
        const applyBtn = document.getElementById('apply-btn');
        applyBtn.disabled = true;
        applyBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Syncing Node...`;

        let blockedIds = [];
        PREDEFINED_CATEGORIES.forEach(cat => {
            cat.services.forEach(srv => {
                if (blockedState[srv.id]) {
                    blockedIds.push(srv.id);
                }
            });
        });

        const payload = { "ids": blockedIds };

        try {
            const url = currentScope === 'global'
                ? `/api/peers/${peerId}/adguard/blocked_services`
                : `/api/peers/${peerId}/adguard/clients/${selectedAliasSlug}/blocked_services`;
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                showToast("Updated successfully");
                initialState = JSON.parse(JSON.stringify(blockedState));
                checkChanges();
            } else {
                showToast("Failed to sync policies with edge node.");
            }
        } catch (err) {
            console.error("Save error:", err);
            showToast("Connection error while syncing policies.");
        } finally {
            applyBtn.innerHTML = `Apply`;
        }
    }
    let peersLoaded = false;

    // Toggle dropdown visibility
    function togglePeerDropdown(event) {
        event.stopPropagation();
        const dropdown = document.getElementById('peerDropdown');
        dropdown.classList.toggle('open');

        // Fetch peers list when first opened
        if (dropdown.classList.contains('open') && !peersLoaded) {
            fetchCustomerPeers();
        }
    }

    // Close dropdown when clicking outside
    document.addEventListener('click', function (event) {
        const dropdown = document.getElementById('peerDropdown');
        if (dropdown && !dropdown.contains(event.target)) {
            dropdown.classList.remove('open');
        }
    });

    // Fetch peers from API endpoint
    async function fetchCustomerPeers() {
        const container = document.getElementById('peer-list-container');
        try {
            const response = await fetch('/api/peers/status');
            if (response.ok) {
                const data = await response.json();
                renderPeerList(data.peers || []);
                peersLoaded = true;
            } else {
                container.innerHTML = `<div class="dropdown-loading" style="color: #ef4444;">Failed to load devices</div>`;
            }
        } catch (e) {
            console.error("Error fetching peers:", e);
            container.innerHTML = `<div class="dropdown-loading" style="color: #ef4444;">Connection error</div>`;
        }
    }

    // Scope Management Actions
    async function loadPeerAliases() {
        try {
            const response = await fetch(`/api/peers/${peerId}/aliases`);
            if (response.ok) {
                const data = await response.json();
                peerAliases = data.lists || [];
                peerAliases.forEach(alias => {
                    if (!alias.slug && alias.id) {
                        alias.slug = alias.id;
                    }
                });
                populateAliasSelector();
            }
        } catch (e) {
            console.error("Error loading peer aliases:", e);
        }
    }

    function populateAliasSelector() {
        const selector = document.getElementById('alias-selector');
        if (!selector) return;
        if (peerAliases.length === 0) {
            selector.innerHTML = '<option value="" disabled selected>No aliases found</option>';
            selectedAliasSlug = '';
            return;
        }
        selector.innerHTML = peerAliases.map(alias =>
            `<option value="${alias.slug}">${alias.name || alias.slug} (${alias.comment || 'No comment'})</option>`
        ).join('');

        // Auto-select the value if selectedAliasSlug is not set yet
        if (!selectedAliasSlug) {
            selectedAliasSlug = selector.value;
        }
    }

    function setScope(scope) {
        if (currentScope === scope) return;
        currentScope = scope;

        // Update UI buttons styling
        document.getElementById('scope-global-btn').classList.toggle('active', scope === 'global');
        document.getElementById('scope-alias-btn').classList.toggle('active', scope === 'alias');

        // Show/hide alias dropdown
        document.getElementById('alias-selector-wrapper').style.display = scope === 'alias' ? 'flex' : 'none';

        // Reset and load configuration for new scope
        blockedState = {};
        initialState = {};

        // If alias list is loaded, select the first one if selectedAliasSlug is not valid
        if (scope === 'alias' && peerAliases.length > 0) {
            const selector = document.getElementById('alias-selector');
            if (selector) {
                const aliasExists = peerAliases.some(alias => alias.slug === selectedAliasSlug);
                if (!aliasExists) {
                    selector.selectedIndex = 0;
                    selectedAliasSlug = selector.value;
                } else {
                    selector.value = selectedAliasSlug;
                }
            }
        }

        loadFilteringConfig();
    }

    function onAliasChange() {
        const selector = document.getElementById('alias-selector');
        selectedAliasSlug = selector.value;
        blockedState = {};
        initialState = {};
        loadFilteringConfig();
    }

    if (isOnline) {
        document.addEventListener("DOMContentLoaded", async () => {
            // Load aliases list first
            await loadPeerAliases();

            // Check if initial scope parameters are provided via query params
            if (initialScope === 'alias' && initialAlias) {
                currentScope = 'alias';
                selectedAliasSlug = initialAlias;

                // Update UI button and selector wrapper
                document.getElementById('scope-global-btn').classList.remove('active');
                document.getElementById('scope-alias-btn').classList.add('active');
                document.getElementById('alias-selector-wrapper').style.display = 'flex';

                // Set selector value
                const selector = document.getElementById('alias-selector');
                if (selector) {
                    selector.value = initialAlias;
                }
            }

            loadFilteringConfig();
            loadVpnOnlyStatus();
        });
    }

    // Render peers list inside dropdown
    function renderPeerList(peers) {
        const container = document.getElementById('peer-list-container');
        if (!peers || peers.length === 0) {
            container.innerHTML = `<div class="dropdown-loading">No other devices found</div>`;
            return;
        }

        let html = '';
        peers.forEach(p => {
            const pId = p.id || p.peer_id;
            const pName = p.name || p.hostname || pId;
            const isActive = pId === peerId ? 'active' : '';
            const isOnlineDevice = p.is_online;

            if (isOnlineDevice) {
                const targetUrl = `/peers/${encodeURIComponent(pId)}/filtering?name=${encodeURIComponent(pName)}`;
                html += `
                        <a href="${targetUrl}" class="peer-item ${isActive}">
                            <span><i class="fas fa-desktop" style="margin-right: 8px; color: #10b981;"></i>${pName}</span>
                            ${isActive ? '<i class="fas fa-check" style="font-size: 0.8rem;"></i>' : ''}
                        </a>
                    `;
            } else {
                html += `
                        <a href="javascript:void(0)" onclick="event.preventDefault(); event.stopPropagation();" class="peer-item" style="opacity: 0.55; cursor: not-allowed; display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; color: #64748b; font-size: 0.9rem; text-decoration: none;" onmouseover="this.style.background='transparent';" onmouseout="this.style.background='transparent';">
                            <span><i class="fas fa-desktop" style="margin-right: 8px; color: #ef4444;"></i>${pName} <span style="font-size: 0.75rem; color: #ef4444; margin-left: 5px; font-weight: 600;">(Offline)</span></span>
                        </a>
                    `;
            }
        });

        container.innerHTML = html;
    }

    // جلب حالة الـ VPN-Only الحالية عند تحميل الصفحة
    async function loadVpnOnlyStatus() {
        const toggle = document.getElementById('vpn-only-toggle');
        if (!toggle) return;

        try {
            // يمكنك استخدام GET أو POST بـ operation: "status"
            const response = await fetch(`/api/peers/${peerId}/vpn-only`);

            if (response.ok) {
                const data = await response.json();
                // الـ Agent بيرجع field اسمه enabled بياخد true أو false
                toggle.checked = Boolean(data.enabled);
            }
        } catch (e) {
            console.error("Error loading VPN-Only status:", e);
        }
    }

    // تغيير حالة الـ VPN-Only
    async function toggleVpnOnly(enable) {
        const toggle = document.getElementById('vpn-only-toggle');
        const spinner = document.getElementById('vpn-spinner');

        // إظهار التحميل وتعطيل الـ switch مؤقتاً
        toggle.disabled = true;
        if (spinner) spinner.style.display = 'inline-block';

        const operation = enable ? 'on' : 'off';

        try {
            const response = await fetch(`/api/peers/${peerId}/vpn-only`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ operation: operation }) // مطابِق للـ VpnOnlyRequest في Agent FastAPI
            });

            const data = await response.json();

            if (response.ok && (data.ok === true || data.status === 'success')) {
                showToast(`VPN-Only mode turned ${operation.toUpperCase()} successfully`);
            } else {
                toggle.checked = !enable;

                // استخلاص ونقد نص الخطأ لمنع إظهار تفاصيل الـ Python/Network الخام
                const rawErr = data.detail || data.message || '';
                let cleanMsg = "Device is unreachable or offline";

                // لو الخطأ مش مشكلة اتصال بالـ Agent، اعرض النص النظيف المتاح
                if (!rawErr.includes("HTTPConnectionPool") && !rawErr.includes("communication failed") && rawErr) {
                    cleanMsg = rawErr;
                }

                showToast(`Failed: ${cleanMsg}`);
            }
        } catch (err) {
            console.error("VPN-Only error:", err);
            toggle.checked = !enable;
            showToast("Failed: Device is unreachable");
        } finally {
            toggle.disabled = false;
            if (spinner) spinner.style.display = 'none';
        }
    }
