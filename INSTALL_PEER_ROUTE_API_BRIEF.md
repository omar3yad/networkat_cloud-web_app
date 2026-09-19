# بريف: عقد `peer-route` الجديد — إعداد مسار الشبكة (Network Route) أثناء تنصيب الـ Peer

> **الهدف:** إتاحة Endpoint للـ Installer / Engineer لإرسال وتعيين الـ Network Route للـ Peer الجديد فور تنصيبه، محمي بالـ `install_token` المُستلم من خطوة `install-peer`.

---

## 1. تفاصيل الـ Endpoint

| البند | القيمة |
|---|---|
| المسار (Path) | `POST https://api.networkat.cloud/api/v1/auth/peer-route` |
| التوثيق (Auth) | `Authorization: Bearer <install_token>` |
| نوع المحتوى | `application/json` |
| الصلاحية | نفس صلاحية توكن التنزيل (`install_token`) — صالحة لمدة 10 دقائق |

---

## 2. جسم الطلب (Request Body)

```json
{
  "peer_id": "ch8g92xxxxxx",
  "network": "192.168.1.0/24",
  "masquerade": true,
  "metric": 9999,
  "description": "Branch LAN Route"
}
```

### توصيف الحقول

| الحقل | النوع | إجباري / اختياري | الوصف والافتراضي |
|---|---|---|---|
| `network` | `string` | **إجباري** | نطاق الشبكة بصيغة IPv4 CIDR (مثال: `192.168.1.0/24` أو `10.10.0.0/16`) |
| `peer_id` | `string` | *اختياري\** | معرف الـ Peer في NetBird. *(يجب تقديم واحد على الأقل من: `peer_id` أو `peer_ip`)* |
| `peer_ip` | `string` | *اختياري\** | عنوان IP الـ NetBird للـ Peer (يقوم السيرفر بالبحث عن الـ Peer تلقائياً به) |
| `masquerade` | `boolean` | اختياري | تفعيل الـ NAT Masquerade (الافتراضي: `true`) |
| `metric` | `integer` | اختياري | أولوية الـ Route من 1 إلى 9999 (الافتراضي: `9999`) |
| `description` | `string` | اختياري | وصف توضيحي للمسار |

---

## 3. مثال استجابة النجاح (201 Created)

```json
{
  "success": true,
  "route_id": "ch8g92xxxxxx",
  "peer_id": "ch8g92xxxxxx",
  "network": "192.168.1.0/24",
  "network_id": "omar3yad-ch8g9",
  "description": "omar3yad peer route",
  "masquerade": true,
  "metric": 9999
}
```

---

## 4. رموز الأخطاء (Error Responses)

| الحالة | HTTP | الجسم | التفسير |
|---|---|---|---|
| توكن مفقود أو غير صالح أو منتهي | 401 | `{"error":"Unauthorized","message":"Invalid or expired installation token."}` | الـ Bearer token غير متطابق أو انتهت مدته (10 دقائق) |
| صيغة CIDR غير صحيحة | 400 | `{"error":"Bad Request","message":"Invalid IPv4 CIDR network format."}` | تنسيق الـ Subnet خاطئ |
| عدم إرسال أي معرف للـ Peer | 400 | `{"error":"Bad Request","message":"At least one of peer_id, peer_ip, must be provided."}` | لم يتم تحديد `peer_id` أو `peer_ip` |
| الـ Subnet مستخدمة مسبقاً | 400 | `{"error":"Bad Request","message":"Subnet already in use by another peer in your account."}` | تعارض الـ CIDR مع جهاز آخر لنفس العميل |
| اشتراك العميل غير نشط | 403 | `{"error":"Forbidden","message":"Subscription is inactive. Modification not allowed."}` | حالة الحساب تمنع إضافة مسارات |
| الـ Peer غير موجود أو لا يتبع الحساب | 404 | `{"error":"Not Found","message":"Peer not found or does not belong to your account."}` | المعرف المدخل غير مرتبط بحساب العميل |
| تجاوز معدل الطلبات | 429 | `{"error":"Too Many Requests","message":"Too many attempts. Please try again in a minute."}` | تجاوز 5 طلبات / 60 ثانية للـ IP |
| خطأ داخلي / NetBird | 500 | `{"error":"Internal Server Error","message":"Failed to create route in NetBird."}` | تعذر الاتصال بـ NetBird API |

---

## 5. أمثلة الاستخدام من سطر الأوامر (cURL / Bash)

### أ. باستخدام `peer_id` المباشر:
```bash
curl -s -X POST https://api.networkat.cloud/api/v1/auth/peer-route \
  -H "Authorization: Bearer $INSTALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "peer_id": "'"$PEER_ID"'",
    "network": "192.168.1.0/24"
  }'
```

### ب. باستخدام `peer_ip` (عنوان NetBird IP المعطى للجهاز):
```bash
curl -s -X POST https://api.networkat.cloud/api/v1/auth/peer-route \
  -H "Authorization: Bearer $INSTALL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "peer_ip": "'"$NETBIRD_IP"'",
    "network": "192.168.1.0/24",
    "masquerade": true
  }'
```

---

## 6. تسلسل التنصيب الكامل (Installer Workflow)

1. يقوم الـ Installer بإرسال بيانات تسجيل الدخول:
   ```http
   POST /api/v1/auth/install-peer
   {"username": "...", "password": "..."}
   ```
   يستلم رد `200 OK` يحتوي على:
   - `setup_key`
   - `install_token`

2. يقوم الـ Installer بتنزيل حزم التثبيت عبر الـ `install_token`:
   ```bash
   curl -H "Authorization: Bearer $install_token" https://pkgs.networkat.cloud/...
   ```

3. يقوم بتشغيل `netbird up --setup-key $setup_key`.

4. (الخطوة الجديدة) بعد اتصال الـ Peer بنجاح، يرسل الـ Installer مسار الشبكة المحلية (LAN Route) المراد توجيهه عبر هذا الـ Peer:
   ```http
   POST /api/v1/auth/peer-route
   Authorization: Bearer $install_token
   {"peer_id": "$PEER_ID", "network": "192.168.1.0/24"}
   ```
