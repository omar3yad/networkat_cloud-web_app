#!/usr/bin/env bash
# إصلاح صلاحيات ملفات web_app بحيث devteam دايماً عنده كتابة.
# شغّله من جذر repo: sudo ./fix-perms.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GROUP="devteam"

echo ">> جذر: $ROOT"
echo ">> ضبط الملكية الجماعية + setgid + ACL على كل الشجرة (ما عدا .git)"

# 1) الجروب لكل حاجة = devteam
find "$ROOT" -not -path "$ROOT/.git/*" -exec chgrp "$GROUP" {} +

# 2) setgid على كل المجلدات → الملفات الجديدة ترث الجروب
find "$ROOT" -type d -not -path "$ROOT/.git/*" -exec chmod g+s {} +

# 3) ACL: الجروب rwx + إصلاح الـ mask المكسور، و default ACL للملفات الجديدة
setfacl -R -m   g:$GROUP:rwX,m:rwX "$ROOT" --exclude=".git" 2>/dev/null || \
  find "$ROOT" -not -path "$ROOT/.git/*" -exec setfacl -m g:$GROUP:rwX,m:rwX {} +
find "$ROOT" -type d -not -path "$ROOT/.git/*" -exec setfacl -d -m g:$GROUP:rwX,m:rwX {} +

# 4) ضمان g+w صريح كـ fallback لو ACL مش مدعوم
find "$ROOT" -not -path "$ROOT/.git/*" -exec chmod g+w {} +

echo ">> تمام. تأكد:"
BROKEN=0
while IFS= read -r f; do
  eff=$(getfacl -p "$f" 2>/dev/null | grep 'group:'"$GROUP" | grep -o 'effective:...' | tail -1 || true)
  if [ "$eff" = "effective:r--" ] || [ "$eff" = "effective:---" ]; then
    echo "   لسه مكسور: $f"; BROKEN=1
  fi
done < <(find "$ROOT" -not -path "$ROOT/.git/*" -not -path '*/__pycache__/*')
[ "$BROKEN" = 0 ] && echo "   كل الملفات قابلة للكتابة من $GROUP ✓"
