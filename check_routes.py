import re
import os
import subprocess

ROUTES_FILE = 'admin/routes.py'

with open(ROUTES_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# استخراج كل الـ Routes المسجلة تحت admin_bp
routes = re.findall(r"@admin_bp\.route\(['\"]([^'\"]+)['\"]", content)

print(f"=== جاري فحص {len(set(routes))} Route خاص بـ Admin ===\n")

for route in sorted(set(routes)):
    # تنظيف الـ Route من الـ Dynamic Parameters (مثلاً <uuid:customer_id> -> '')
    clean_route = re.sub(r'/<[^>]+>', '', route)
    
    if clean_route == '' or clean_route == '/':
        print(f"  [شغال - Root/Auth]: {route}")
        continue

    # البحث في الـ HTML والـ JS وباقي السكربتات
    cmd = [
        "grep", "-rnw", 
        "--exclude-dir={venv,.venv,__pycache__,lib,.git}",
        "admin/", "templates/", "static/", "fastapi_app/", "services/", "client/",
        "-e", clean_route
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    matches = [line for line in result.stdout.splitlines() if ROUTES_FILE not in line]
    
    if matches:
        print(f"  [مستدعى/مستخدم]: {route} (وجد {len(matches)} إشارة)")
    else:
        print(f"🚨 [متروك / Unused Potential]: {route}")