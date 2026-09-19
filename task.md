# Admin "View As Client" — Task List

## Phase 1: Backend Routes
- [x] قراءة باقي client routes (peer_api, web_filter, aliases) لفهم كل الـ API endpoints المحتاجة
- [x] إضافة admin view routes في `admin/routes.py`
  - [x] helper function: `_admin_verify_peer(customer_id, peer_id)`
  - [x] Page route: Peer Details
  - [x] Page route: Firewall
  - [x] Page route: Web Filter
  - [x] Page route: Aliases
  - [x] API proxy: `/api/peers` (GET)
  - [x] API proxy: `/api/peers/<pid>/handshake` (GET)
  - [x] API proxy: `/api/v2/netbird/routes` (GET)
  - [x] API proxy: `/api/peers/<pid>/firewall/rules` (GET)
  - [x] API proxy: web-filter rules + adguard endpoints (GET)
  - [x] API proxy: aliases endpoint (GET)

## Phase 2: Templates — Admin Banner + Read-Only Mode
- [x] `peer_details.html` — add admin_view banner + hide write buttons
- [x] `firewall.html` — add admin_view banner + hide write buttons
- [x] `web_filter.html` — add admin_view banner + hide write buttons
- [x] `aliases.html` — add admin_view banner + hide write buttons
- [x] `client_base.html` — safe sidebar links for admin_view avoiding url_for BuildErrors

## Phase 3: JS Files — window.API_BASE
- [x] `peer_details.js` — استخدام window.API_BASE
- [x] `firewall.js` — استخدام window.API_BASE
- [x] `web_filter.js` — استخدام window.API_BASE
- [x] `aliases.js` — استخدام window.API_BASE

## Phase 4: Customer Details Page
- [x] إضافة "View peer as client" button جنب كل peer في `customer_details.html` مع الحماية ضد القيم الفارغة

## Phase 5: Static Asset Fallback
- [x] دعم تقديم ملفات CSS/JS الخاصة بالعميل من خلال تطبيق الأدمن عند التصفح بوضع الأدمن

## Verification
- [x] اختبار الوصول بدون login → redirect
- [x] اختبار peer لا ينتمي للـ customer → 403
- [x] اختبار قوالب صفحات العميل والأدمن (رندر سليم 100%)
- [x] تشغيل كامل اختبارات pytest (49 passed) بنجاح تام
