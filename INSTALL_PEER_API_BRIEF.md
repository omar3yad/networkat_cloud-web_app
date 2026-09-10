# بريف: عقد `install-peer` الجديد — لوكيل `core/peer_installer/dev`

> **الحالة:** تغييرات `web_app` جاهزة في الكود، لم تُنشر للإنتاج بعد.
> **لا** يوجد backward-compat alias على السيرفر — المسار القديم `/api/v1/auth/setup-key`
> سيُرجع `404` فور النشر. الريبوان يتحدّثان معًا؛ **لا تُصدر `install.sh` للإنتاج قبل نشر `web_app`.**

---

## 1. العقد الجديد

| | القديم | الجديد |
|---|---|---|
| المسار | `POST https://api.networkat.cloud/api/v1/auth/setup-key` | `POST https://api.networkat.cloud/api/v1/auth/install-peer` |
| الطلب | `{"username","password"}` | **بدون تغيير** — `{"username","password"}` |
| صلاحية المفتاح | 24 ساعة (`expires_in: 86400`) | **20 دقيقة** (`expires_in: 1200`)، one-off، `usage_limit: 1` |

المعنى الدلالي: الطلب الآن *يُنصّب peer* ويُصدر مفتاحًا واحدًا مخصّصًا لجهاز واحد — ليس "جلب مفاتيح".

---

## 2. مثال استجابة 200 (الشكل الكامل الجديد)

```json
{
  "username": "omar3yad",
  "account": {
    "full_name": "Omar Ahmed",
    "company_name": "3yad",
    "country": "Egypt",
    "subscription": {
      "plan": "pro",
      "allowed_peers_count": 5,
      "remaining_peers_count": 3,
      "installed_peers_count": 2
    }
  },
  "setup_key": "CC7D51F4-4F6F-4D8F-B542-51891E5F2CC4",
  "install_token": "b21hcjN5YWQ..."
}
```

`remaining_peers_count = max(0, allowed_peers_count - installed_peers_count)` (لا يُطرح منه الـ peer الجاري تنصيبه).

---

## 3. التغييرات مقابل القديم (بالتفصيل)

### حقول اختفت من جسم الـ 200
- من `account`: `email`، `member_since`، `active_keys`.
- من الجذر: `expires_in`، `subscription_status`، `peer_limit`، `current_peers`، `remaining_peers`.

### حقول تغيّر اسمها / شكلها
| القديم | الجديد |
|---|---|
| `setup_keys[]` (مصفوفة كائنات `{valid,used_times,usage_limit,remaining_uses,key}`) | `setup_key` (سلسلة نصية واحدة — المفتاح مباشرة) |
| `download_token` | `install_token` (نفس آلية التوقيع؛ يُقدَّم كـ `Authorization: Bearer` على طلب التنزيل) |
| `account.subscription` (سلسلة: `"pro"`) | `account.subscription` (كائن؛ الاسم في `account.subscription.plan`) |
| `peer_limit` (جذر) | `account.subscription.allowed_peers_count` |
| `current_peers` (جذر) | `account.subscription.installed_peers_count` |
| `remaining_peers` (جذر) | `account.subscription.remaining_peers_count` |

### أمثلة تحويل jq
```
.setup_keys[0].key          →  .setup_key
.setup_keys[] | select(...)  →  (لم يعد ينطبق — مفتاح واحد فقط)
.download_token             →  .install_token
.account.subscription       →  .account.subscription.plan
.peer_limit                 →  .account.subscription.allowed_peers_count
.current_peers              →  .account.subscription.installed_peers_count
.remaining_peers            →  .account.subscription.remaining_peers_count
```

---

## 4. الأخطاء

| الحالة | HTTP | الجسم |
|---|---|---|
| بيانات اعتماد خاطئة / حساب معطّل | 401 | `{"error":"Unauthorized","message":"Invalid credentials or account is not active."}` |
| اشتراك غير نشط أو في فترة السماح (`grace_period`/`limit_control`/`inactive`) | 403 | `{"error":"Forbidden","message":"Adding new peers is not allowed during the grace period... / Subscription is currently restricted...","account":{…}}` |
| تجاوز حصة الأجهزة | 403 | `{"error":"Forbidden","message":"Cannot add more peers, limit exceeded (N/M).\nUpgrade plan to connect more.","account":{…}}` |
| تجاوز معدّل الطلبات (5 / 60 ث لكل IP) | 429 | `{"error":"Too Many Requests","message":"Too many attempts. Please try again in a minute."}` |
| خطأ داخلي / فشل NetBird | 500 | `{"error":"Internal Server Error","message":"..."}` |

- **`404` لم يعد يحدث** لهذا المسار (كان يُرجَع سابقًا عند "لا مفتاح نشط"). أي فرع يتعامل مع `404` كـ "لا مفتاح" يجب حذفه؛ الآن `404` = المسار القديم فقط.
- أجسام أخطاء `403` (تجاوز الحصة + الاشتراك المقيّد) تحمل الآن كتلة `account` بنفس شكل رد الـ 200 (بدون `setup_key`/`install_token`) — بقية الأخطاء `{error, message}` فقط. رسالة تجاوز الحصة تحوي `\n` (سطران): "Cannot add more peers, limit exceeded (N/M)." ثم "Upgrade plan to connect more.". الإنستولر يعرض `⚠` واحدة على السطر الأول فقط.

---

## 5. المواضع المعروفة في ريبو B للفحص (إرشاد، لا تنفيذ من هنا)

- **`install.sh`:**
  - `LOGIN_URL="$BASE_URL/api/v1/auth/setup-key"` → `/install-peer`.
  - `_reuse_portal_session` / منطق إعادة استخدام الجلسة.
  - قراءات `.setup_keys[]` / `_valid` jq → `.setup_key`.
  - `.download_token` (موضعان) → `.install_token`.
  - `.account.full_name` / `.account.company_name` / `.account.subscription` → `.account.subscription.plan` للخطة.
  - فرع معالجة `404`.
- **`lib/common.sh`:**
  - `NETWORKAT_LOGIN_URL` (~1218).
  - `NK_KEYS_TSV_JQ` (~1226–1234) يُسقِط `.setup_keys[]` → يصبح قراءة `.setup_key` مفردة.
  - `networkat_fetch_setup_key()`.
  - `.account.subscription` (~1417).
  - خريطة الحالة→الرسالة (~1363–1381) — النصوص الجديدة أعلاه.
  - النسخة المزدوجة على `/opt/networkat/sdwan/lib/common.sh`.
- **`phase-0-pre_initial.sh`:** `_load_portal_session` (~265) يقرأ `.account.subscription`.
- **الوثائق/الإصدار:** `docs/login-api.md`، `CLAUDE.md`، `VERSION` + `changelog/`.

---

## 6. تسلسل التنزيل (لم يتغيّر جوهريًا)

1. `POST /api/v1/auth/install-peer` بـ `{username,password}` → 200 يحمل `install_token`.
2. `curl -H "Authorization: Bearer <install_token>" https://pkgs.networkat.cloud/stable/<v>/peer-installer-<v>.tar.gz`
   — nginx `auth_request` → `GET /api/v1/auth/verify-download` (204 = اسمح، 403 = ارفض).
3. استخدم `setup_key` (المفرد) مع `netbird up --setup-key ...`.

TTL توكن التنزيل ما زال ~10 دقائق؛ TTL مفتاح الإعداد الآن 20 دقيقة (كان 24 ساعة) — نافذة التنصيب يجب أن تكتمل ضمنها، وإعادة تشغيل `curl | bash` تُنشئ طلبًا جديدًا ومفتاحًا جديدًا كالمعتاد.
