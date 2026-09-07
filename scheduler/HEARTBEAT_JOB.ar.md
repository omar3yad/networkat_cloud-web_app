# وظيفة النبضة (Heartbeat Job) — توثيق للـ Backend Dev-Team

> **نطاق هذا المستند:** ما تم إنجازه في هذه الجلسة فقط — إضافة عملية دورية في
> `core/web_app` تُرسل نبضة إلى كل الـ peers. لا يشرح باقي الـ API الموجود مسبقًا.

---

## 1. لماذا؟ (السياق)

على كل **peer** (جهاز SD-WAN عند العميل) توجد خاصية **failsafe / dead-man-switch**:

- لو الـ peer فقد الاتصال بالـ Backend Controller (هذا السيرفر) مدة أطول من
  `failsafe_timeout_seconds` → الـ peer **يهبّط نفسه تلقائيًا** إلى "راوتر إنترنت
  أساسي": AdGuard بدون فلترة، قواعد الـ firewall الخاصة بالعميل متجاوَزة، الـ peer
  معزول تمامًا عن الميش. الإنترنت العادي يفضل شغّال، وقناة تحكّم الـ Controller
  تفضل حية.
- يرجع طبيعي تلقائيًا عند أول نبضة ناجحة.

**"الاتصال" يُقاس بملف واحد على الـ peer:** `/run/networkat-agent/last-contact`.
الـ agent على الـ peer يحدّث `mtime` هذا الملف في حالتين:
1. عند استقبال `POST /heartbeat`.
2. عند أي أمر ناجح يصله من الـ Controller.

**المشكلة قبل هذه الجلسة:** لا يوجد أي شيء يُرسل نبضة دورية. الملف كان يتحدّث فقط
بالمرور العرضي لطلبات `/status` و reachability-checks من داشبورد العميل — وهذا لا
يحدث إلا إذا كان العميل فاتح الداشبورد فعليًا. أي peer لا أحد يفتح داشبورده لساعات
كان يدخل failsafe رغم أنه سليم.

**الحل (هذه الجلسة):** عملية دورية مستقلة في `core/web_app` تنادي `POST /heartbeat`
على كل peer كل ~60 ثانية. إشارة الحياة أصبحت موثوقة ومستقلة عن نشاط الداشبورد.

---

## 2. ما الذي تغيّر؟

| ملف | نوع التغيير |
|---|---|
| `scheduler/peers_heartbeat.py` | **جديد** — اللوب الرئيسي |
| `scheduler/__init__.py` | **جديد** — يجعل `scheduler/` package (كان فيه ملفات لكن بلا `__init__.py`) |
| `supervisord.conf` | **تعديل** — إضافة `[program:heartbeat]` |

> `scheduler/{jobs,monitor,cleanup}.py` ما زالت ملفات فارغة (0 بايت) — لم تُلمس، ليست
> جزءًا من هذا العمل.

### 2.1 العملية الرابعة في `supervisord.conf`

قبل هذه الجلسة كان supervisord يشغّل 3 عمليات: `admin` (gunicorn:5000)،
`client` (gunicorn:8097)، `api` (uvicorn:8098). أضفنا رابعة **بلا بورت**:

```ini
[program:heartbeat]
command=python -u -m scheduler.peers_heartbeat
directory=/app
autostart=true
autorestart=true
startsecs=5
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
```

**لماذا عملية منفصلة وليست `asyncio task` داخل FastAPI؟**
- `uvicorn` يعمل بـ `--reload` → أي حفظ ملف في `fastapi_app/` كان سيقتل اللوب ويعيد
  تشغيله.
- عزل تام: خطأ في اللوب لا يمسّ خدمة الطلبات، والعكس.
- `autorestart=true` يكفل إعادة التشغيل لو انهارت لأي سبب.
- `-u` = مخرجات غير مُخزّنة (unbuffered) حتى تصل أسطر السجل فورًا إلى سجل الحاوية.

**لا يحتاج rebuild للـ image.** `entrypoint.sh` يشغّل
`supervisord -c /app/supervisord.conf` و `/app` مربوط bind-mount. التفعيل على
البيئة الحيّة تم بـ `docker compose restart web_app`. (ملاحظة: هذا السيتب لا يحتوي
قسم `[supervisorctl]`، فلا يوجد `supervisorctl add` — التفعيل الوحيد هو restart
للحاوية.)

---

## 3. كيف يعمل `scheduler/peers_heartbeat.py`

### 3.1 الدورة (round) — كل ~60 ثانية

1. **جلب الـ peers** — نداء مباشر لـ NetBird API الداخلي:
   `GET http://netbird-server/api/peers` بترويسة
   `Authorization: Bearer <NETBIRD_TOKEN>`.
   (نداء مباشر وليس عبر `fastapi_app.services` — حتى لا تعتمد هذه الوظيفة على حزمة
   `fastapi_app`.)
2. **الفلترة** — نُبقي فقط الـ peer الذي:
   - `connected == true`، و
   - له `ip` (عنوان ميش)، و
   - عضو في مجموعة NetBird اسمها **`all-peers`**.

   > كل onboarding لعميل يربط setup-key بمجموعة العميل **+ `all-peers`** (انظر
   > `services/customer_service.py` وتوثيق الـ peer_installer). إذًا `all-peers` هي
   > بالضبط مجموعة البوابات المُدارة. الـ controllers ومتصفحات العملاء وأجهزة
   > المشرفين في مجموعات أخرى وليس عليها agent على البورت 8765 — نداؤها مجرد
   > sockets ضائعة وضجيج في عدّاد الفشل.
3. **الإرسال بالتوازي** — `ThreadPoolExecutor` بعرض 20، كل peer:
   `POST http://<mesh-ip>:8765/heartbeat` — **بلا body، بلا ترويسة auth**
   (حدود الثقة هي الميش نفسه، مثل كل نداءات Controller→agent). timeout لكل نداء = 5 ثوانٍ.
4. **سطر سجل واحد** يلخّص الدورة.

### 3.2 المتانة

- كل الأخطاء **غير قاتلة**: فشل NetBird API → دورة سيئة تُسجَّل تحذيرًا وتُتخطّى، ليست
  توقّفًا. peer غير قابل للوصول (offline / وسط reboot) → يُسجَّل عند `debug` ويُحسب
  `failed`. **اللوب لا يموت أبدًا** (حتى لو bug داخل الدورة — ملفوف بـ try/except يسجّل
  الـ traceback ويكمل).
- **إيقاف نظيف:** `SIGTERM` / `SIGINT` (إيقاف supervisord، `docker stop`) → يخرج
  بـ exit 0 خلال ثوانٍ (النوم بين الدورات ينتظر على `threading.Event` قابل للمقاطعة،
  لا ينتظر دورة كاملة).
- **بلا state، بلا جدول DB.** لا يكتب في `command_logs` ولا أي مكان — مجرد pinger.
  لا يقرأ جسم الرد أبعد من كود الحالة.
- **سقف زمني للدورة** (`_ROUND_DEADLINE = interval - 5`) حتى لا تتجاوز دفعة من الـ
  sockets المعلّقة زمن الفاصل.

### 3.3 الإعدادات (كلها عبر متغيّرات بيئة، لها قيم افتراضية)

| المتغيّر | الافتراضي | المعنى |
|---|---|---|
| `HEARTBEAT_INTERVAL_SECONDS` | `60` | الفاصل بين الدورات — مريح مقارنةً بمهلة الـ failsafe (`DEFAULT_TIMEOUT_SECONDS = 604800` = أسبوع على الأسطول)، فدورة أو اثنتان فائتتان لا تضرّ |
| `HEARTBEAT_PEER_GROUP` | `all-peers` | مجموعة NetBird التي تُعتبر peers مُدارة |
| `HEARTBEAT_WORKERS` | `20` | عرض التوازي |
| `HEARTBEAT_REQUEST_TIMEOUT` | `5` | timeout نداء `/heartbeat` لكل peer (ثوانٍ) |
| `HEARTBEAT_NETBIRD_TIMEOUT` | `10` | timeout نداء قائمة الـ peers (ثوانٍ) |
| `HEARTBEAT_LOG_LEVEL` | `INFO` | ضعه `DEBUG` لرؤية سطر لكل peer |
| `NETBIRD_API_URL` | `http://netbird-server/api` | يُقرأ من `.env` (نفس ما يستخدمه FastAPI) |
| `NETBIRD_TOKEN` | — | يُقرأ من `.env` |

> `.env` تُقرأ بـ `python-dotenv` (`load_dotenv()`) عند import، تمامًا مثل
> `config/settings.py` — لأن `env_file` في compose لا يُمرَّر إلى بيئة العملية على
> هذا الهوست.

---

## 4. عقد الـ API على الـ peer (agent — البورت 8765)

هذه الـ endpoints تعيش على **الـ agent الموجود على كل peer** (FastAPI، تستمع على
`wt0` فقط، من `100.123.0.0/27`). الـ Controller يناديها عبر الميش بلا auth token.
`POST /heartbeat` هو الوحيد الذي تناديه وظيفة النبضة؛ الباقي مذكور هنا لاكتمال
الصورة لأنه نفس الخاصية.

### 4.1 `POST /heartbeat`

نبضة الحياة. لا body، لا auth.

```bash
curl -s -XPOST http://100.123.117.214:8765/heartbeat
```

**رد 200:**
```json
{"ok": true, "timestamp": "2026-09-06T23:41:55+00:00"}
```
يكتب `/run/networkat-agent/last-contact` قبل الرد. لو فشلت الكتابة → **503**.

> **ملاحظة عن البيئة الحالية:** في وقت كتابة هذا المستند، peer واحد فقط
> (`networkat-cloudedge-2` = `100.123.117.214`, وهو vm-3012 المخبري) عليه إصدار
> الـ agent الجديد الذي يحوي `/heartbeat`. باقي الـ peers على agent أقدم فيرجع
> **404** على `/heartbeat` — وهذا يظهر كـ `failed` في سجل الوظيفة، ولا يكسر شيئًا.
> أول ما تُعاد تنصيب الـ peers تأخذ 200.

### 4.2 `GET /failsafe` — حالة الـ failsafe

```bash
curl -s http://100.123.117.214:8765/failsafe | jq
```
```json
{
  "ok": true,
  "action": "status",
  "code": "ok",
  "message": "failsafe off",
  "failsafe": {
    "state": "off",
    "rules_present": false,
    "filtering_enabled": true,
    "timeout_seconds": 604800,
    "last_contact_age_seconds": 12,
    "reason": "reconcile_only"
  }
}
```

| الحقل | المعنى |
|---|---|
| `state` | `off` = طبيعي؛ `on` = تهبيط صريح (لا يُسترجع تلقائيًا)؛ `on_auto` = تهبيط بسبب timeout (يُسترجع عند أول نبضة) |
| `rules_present` | هل قواعد nft الخاصة بالـ failsafe مفروضة الآن |
| `filtering_enabled` | حالة فلترة AdGuard (`null` لو AdGuard غير متاح) |
| `timeout_seconds` | مهلة فقد الاتصال الحالية |
| `last_contact_age_seconds` | عمر آخر نبضة بالثواني (`null` = "غير مُسلَّح" — الملف غير موجود) |
| `reason` | `manual` / `heartbeat_timeout` / `heartbeat_recovered` / `reconcile_only` |

### 4.3 `POST /failsafe` — أمر صريح

body: `{"action": "enable"}` أو `{"action": "disable"}`.

```bash
# تهبيط صريح فوري
curl -s -XPOST http://100.123.117.214:8765/failsafe \
  -H 'content-type: application/json' -d '{"action":"enable"}' | jq

# إلغاء (لازم صريح — enable لا يُسترجع تلقائيًا)
curl -s -XPOST http://100.123.117.214:8765/failsafe \
  -H 'content-type: application/json' -d '{"action":"disable"}' | jq
```
الرد بنفس شكل `GET /failsafe` مع `action: "enable"` / `"disable"` و
`state` محدَّثة.

### 4.4 `PUT /failsafe/config` — ضبط المهلة

body: `{"timeout_seconds": <int>}` — بين `60` و `1209600`.

```bash
curl -s -XPUT http://100.123.117.214:8765/failsafe/config \
  -H 'content-type: application/json' -d '{"timeout_seconds": 604800}' | jq
```
> الافتراضي الحالي في المُنصِّب (`failsafe_engine.py: DEFAULT_TIMEOUT_SECONDS`) =
> `604800` ثانية (أسبوع). هذا الـ endpoint يسمح للـ Controller بضبطها لكل peer على
> حدة. لا يلمس nft — يكتب المفتاح في جدول `setting` فقط.

---

## 5. التحقّق الذي تم (بيئة حيّة)

بعد `docker compose restart web_app`:

```
2026-09-06 23:43:02  [heartbeat] INFO starting: interval=60s timeout=5.0s workers=20
2026-09-06 23:43:03  [heartbeat] INFO round: 4 peers, 1 ok, 3 failed
2026-09-06 23:44:03  [heartbeat] INFO round: 4 peers, 1 ok, 3 failed
2026-09-06 23:45:03  [heartbeat] INFO round: 4 peers, 1 ok, 3 failed
```

- الفاصل دقيق: 60 ثانية بالضبط بين الدورات.
- `4 peers` = الأعضاء في `all-peers` المتصلون ولهم IP (`homeser`,
  `networkat-cloudedge`, `ads`, `networkat-cloudedge-2`).
- `1 ok` = vm-3012 → `HTTP 200 {"ok":true,"timestamp":...}` (عليه الـ agent الجديد).
- `3 failed` = الثلاثة الآخرون → `HTTP 404` (agent أقدم بلا `/heartbeat`).
- الـ 3 apps الأخرى (`admin` / `client` / `api`) اشتغلت طبيعي، بلا أي أخطاء.
- اختبار `SIGTERM` أثناء اللوب → خروج نظيف بـ exit 0 خلال ثوانٍ.

---

## 6. الحالة والخطوات التالية

- **مُفعَّل على البيئة الحيّة** (`docker compose restart web_app` تم).
- **لم يُعمَل commit** — بانتظار مراجعة الفريق. (يوجد شغل غير مُقيَّد في الشجرة من
  جلسة أخرى — الملفات الخاصة بهذا العمل فقط: `scheduler/peers_heartbeat.py`،
  `scheduler/__init__.py`، وأسطر `[program:heartbeat]` في `supervisord.conf`.)
- هذا تغيير في `core/web_app` — **لا يمرّ عبر `peer_installer/dev/release.sh`**
  (ذاك للـ peer_installer فقط).
- لا يوجد اعتماد على قاعدة بيانات ولا migration.

### مقترحات للفريق (اختيارية)

- تحويل الفلترة من "اسم مجموعة `all-peers`" إلى فلترة على مستوى العميل
  (`Client.netbird_group_id`) لو احتيج نطاق أدق لاحقًا.
- إضافة metric/تنبيه لو نسبة `failed` تجاوزت حدًّا (يعني أسطول كبير بلا نبضة).
- الملفات الفارغة `scheduler/{jobs,monitor,cleanup}.py` — لو فيه نية لوظائف دورية
  أخرى، هذا هو المكان ونفس النمط (عملية `[program:...]` مستقلة).
