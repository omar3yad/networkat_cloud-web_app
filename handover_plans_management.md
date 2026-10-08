# وثيقة تسليم المهام وخريطة العمل: إدارة خطط الاشتراك والمراحل التالية

---

## 1. ملخص ما تم إنجازه (Status & Completed Work)

### أ. واجهة خطط الاشتراك (Subscription Plans UI)
* المسار:
  ```
  /opt/networkat_sdwan/core/web_app/templates/plans.html
  ```
* المميزات المنفذة:
  - بطاقات إحصائيات علوية (إجمالي الخطط، الخطط النشطة، إجمالي العملاء، أقصى حد للأجهزة) محسوبة ومُولدة من السيرفر لتفادي أي أخطاء في الـ Rendering.
  - شبكة بطاقات الخطط (Plans Grid) مع أزرار الإجراءات (تعديل، تفعيل/تعطيل، حذف).
  - نافذة منبثقة (Modal) لإنشاء وتعديل الخطط مع توليد تلقائي للاسم التعريفي (Slug) وحقول الأسعار وحدود الأجهزة.
  - نافذة منبثقة لتأكيد الحذف (Custom Delete Modal) بدون أي استخدام لدوال المتصفح الافتراضية.
  - نظام إشعارات سريعة ومختصرة (Toast Notifications).
  - قسم وبطاقة مخصصة لإدارة مدة الفترة التجريبية (Trial Duration).

---

### ب. طبقة الأمان والمصادقة في FastAPI (Phase 0: Admin Security & Session Layer)
* مسارات الملفات المنفذة:
  ```
  fastapi_app/services/admin/session.py
  fastapi_app/dependencies.py
  tests/test_admin_auth.py
  ```
* الآلية المنفذة:
  - تم بناء دالة فحص جلسة المشرف `get_current_admin` لدعم وسيلتين:
    1. ترويسة المصادقة المباشرة `Authorization: Bearer <token>`.
    2. الكوكي الخاص بجلسة الويب الحالية `session` لفك تشفير جلسة Flask والتأكد من `is_admin == True`.
  - تم كتابة اختبارات التحقق الشاملة في `tests/test_admin_auth.py`.

---

### ج. واجهات برمجة التطبيقات للخطط في FastAPI (Phase 1: Plans Management Endpoints)
* مسارات الملفات المنفذة:
  ```
  fastapi_app/services/admin/plans_service.py
  fastapi_app/schemas/admin/plans.py
  fastapi_app/routes/admin/plans.py
  fastapi_app/main.py
  ```
* نقاط النهاية (Endpoints):
  - `GET /api/v2/admin/plans`: جلب كافة الخطط مع عدد المشتركين في كل خطة.
  - `POST /api/v2/admin/plans`: إنشاء خطة اشتراك جديدة.
  - `PUT /api/v2/admin/plans/{plan_id}`: تحديث بيانات خطة قائمة.
  - `DELETE /api/v2/admin/plans/{plan_id}`: حذف خطة (مع التحقق ومنع الحذف إذا كان هناك مشتركون).
  - `POST /api/v2/admin/plans/{plan_id}/toggle`: تبديل حالة التفعيل.
  - `GET /api/v2/admin/plans/trial-duration`: جلب مدة الفترة التجريبية الحالية.
  - `PUT /api/v2/admin/plans/trial-duration`: تعديل وحفظ مدة الفترة التجريبية في جدول `system_settings`.

---

### د. مسارات Flask والوسيط (Flask Admin Proxy & Routes)
* المسار:
  ```
  /opt/networkat_sdwan/core/web_app/admin/routes.py
  ```
* المسارات المنفذة:
  - `GET /plans`: عرض صفحة إدارة الخطط محمية بـ `@admin_required`.
  - مسارات الوكيل (Proxy) التي تحول الطلبات بسلاسة إلى FastAPI مع تمرير الجلسة والبيانات:
    - `GET /api/plans`
    - `POST /api/plans`
    - `PUT /api/plans/<plan_id>`
    - `DELETE /api/plans/<plan_id>`
    - `POST /api/plans/<plan_id>/toggle`
    - `GET /api/plans/trial-duration`
    - `PUT /api/plans/trial-duration`

---

### هـ. تحديث القوائم الجانبية (Sidebar Navigation)
* تم تضمين رابط صفحة خطط الاشتراك `Subscription plans` في جميع القوالب الرئيسية:
  ```
  templates/dashboard.html
  templates/customers.html
  templates/customer_details.html
  templates/settings.html
  ```

---

## 2. ما يجب على النموذج في المحادثة الجديدة تنفيذه بالتفصيل (Next Action Items)

### أولاً: التحقق والاختبار لصفحة الخطط (Verification & Testing)
1. **مزامنة الملفات إلى الحاوية النشطة**:
   ```bash
   docker cp /opt/networkat_sdwan/core/web_app/. web_app:/app/
   ```
2. **اختبار تشغيل FastAPI**:
   - التأكد من عدم وجود أي خطأ استيراد أو تعارض في `main.py` أو `routes/admin/plans.py`.
   - فحص سجلات الحاوية:
     ```bash
     docker logs web_app --tail=50
     ```
3. **تجربة الواجهة في المتصفح**:
   - الرابط:
     ```
     https://admin.networkat.cloud/plans
     ```
   - التحقق من إنشاء خطة جديدة وتعديلها وحذفها وتغيير مدة التجربة التجريبية (Trial).

---

### ثانياً: المهام الأربعة المتبقية من متطلبات المستخدم (Pending Tasks)

#### المهمة 1: إخفاء خيار "System logs enabled" من واجهة الإعدادات
* الملف المستهدف:
  ```
  /opt/networkat_sdwan/core/web_app/templates/settings.html
  ```
* المطلوب:
  - البحث عن العنصر الخاص بـ:
    ```text
    System logs enabled
    ```
  - إخفاؤه تماماً من واجهة المستخدم (حذف أو وضع `style="display: none;"` أو إزالة الكتلة البرمجية الخاصة به) حتى لا يظهر للمشرف في قسم الإعدادات.

---

#### المهمة 2: ضبط وتنسيق عرض معلومات التحديث (Update Release Info Format)
* الملف المستهدف:
  ```
  /opt/networkat_sdwan/core/web_app/templates/settings.html
  ```
  (أو النافذة المنبثقة المسؤولة عن عرض تفاصيل التحديث).
* الصيغة المطلوبة بدقة:
  - العنوان الرئيسي:
    ```text
    New update
    ```
  - حقل الإصدار:
    ```text
    Version:
    ```
  - حقل تاريخ ووقت الإصدار:
    ```text
    Released: DD/MM/YYYY HH:MM
    ```

---

#### المهمة 3: تقييد وقفل التحديث لمستخدمي الإصدار 1.x.x
* الملفات المستهدفة:
  - الكود البرمجي لفحص التحديثات في:
    ```
    /opt/networkat_sdwan/core/web_app/templates/settings.html
    /opt/networkat_sdwan/core/web_app/static/js/
    ```
  - أو نقاط النهاية المسؤولة عن الـ Updates.
* الشروط المطلوبة:
  - إذا كان إصدار العميل يبدأ بـ `v1.` أو يطابق النمط `1.x.x`:
    1. إلغاء وتعطيل استعلام البحث التلقائي عن التحديثات (Disable update query).
    2. قفل وتعطيل زر فحص التحديثات:
       ```text
       Check update
       ```
    3. قفل وتعطيل زر التحديث:
       ```text
       Update now
       ```

---

#### المهمة 4: تحسين رسائل الأخطاء للعملاء (User-Friendly Error Messages)
* الملفات المستهدفة:
  - مسارات وخدمات العميل في:
    ```
    /opt/networkat_sdwan/core/web_app/client/
    /opt/networkat_sdwan/core/web_app/fastapi_app/
    ```
* المطلوب:
  - إخفاء أي تفاصيل تقنية داخلية أو أخطاء خام صادرة من `NetBird` أو قاعدة البيانات.
  - استبدالها برسائل مباشرة، واضحة، ولطيفة للمستخدم النهائي مع الحفاظ على قصر الرسالة.

---

## 3. القواعد والتعليمات الصارمة الواجب اتباعها (Strict Project Rules)

### أ. قواعد التصميم والواجهة (UI & Styling)
1. **منع استخدام الحروف الكبيرة (Strictly NO UPPERCASE)**:
   - يُمنع نهائياً استخدام:
     ```css
     text-transform: uppercase;
     ```
   - يُمنع كتابة أي نص في الواجهة، الأزرار، أو العناوين بحروف كبيرة بالكامل (ALL CAPS).
   - الالتزام بنمط الجملة أو العنوان القياسي:
     ```text
     Sentence case or Title case (e.g. Current version, Save changes, Close)
     ```
2. **منع التنبيهات الافتراضية للمتصفح**:
   - يُمنع تماماً استخدام:
     ```javascript
     alert()
     confirm()
     prompt()
     ```
   - يجب استخدام مكونات الـ Toast والـ Modal المخصصة فقط.

---

### ب. قواعد الرسائل والنصوص (Conciseness & BiDi)
1. **رسائل فائقة الإيجاز (Ultra-Concise Messages)**:
   - جميع الرسائل والإشعارات للمستخدم يجب أن تكون مختصرة جداً:
     ```text
     "Saved"
     "Plan created"
     "Updated successfully"
     ```
2. **قواعد اللغة العربية والتنسيق (BiDi Fix)**:
   - عدم خلط الكلمات الإنجليزية أو المتغيرات أو المصطلحات البرمجية داخل الفقرات العربية إطلاقاً.
   - وضع المصطلحات والمسارات البرمجية في أسطر منفصلة أو داخل كتل برمجية محددة (Code blocks).
   - الاعتماد على النقاط (Bullet points) والتنسيق المنظم بدلاً من الفقرات المختلطة.

---

### ج. المعمارية والبرمجة (Architecture & APIs)
1. **الـ APIs الجديدة في FastAPI حصراً**:
   - جميع نقاط النهاية والخدمات الجديدة يجب أن تُبنى داخل:
     ```
     /opt/networkat_sdwan/core/web_app/fastapi_app/
     ```
   - يقتصر دور Flask على القوالب القديمة والـ Proxy فقط.
2. **عدم كشف المعرفات الداخلية**:
   - عدم إظهار معرّفات قواعد البيانات الداخلية أو تفاصيل الـ Stack Traces للمستخدم.
