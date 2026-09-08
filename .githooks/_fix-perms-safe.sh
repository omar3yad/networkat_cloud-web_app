#!/usr/bin/env bash
# إصلاح صلاحيات بدون sudo: يعالج بس الملفات اللي المستخدم الحالي يملكها.
# بيتنده من post-merge / post-checkout.
set -u
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
GROUP="devteam"
ME="$(id -un)"

cd "$ROOT" || exit 0

# نطاق التغيير: post-merge بيسيب ORIG_HEAD؛ post-checkout بيبعت $1=old $2=new
OLD_REF="${1:-ORIG_HEAD}"
NEW_REF="${2:-HEAD}"
changed() { git diff-tree -r --name-only --no-commit-id "$OLD_REF" "$NEW_REF" 2>/dev/null; }

# الملفات اللي أنشأها/عدّلها التحديث وأنا مالكها → صلّح جروبها وصلاحياتها
changed | while IFS= read -r f; do
  [ -e "$f" ] || continue
  owner="$(stat -c '%U' "$f" 2>/dev/null)"
  [ "$owner" = "$ME" ] || continue
  chgrp "$GROUP" "$f" 2>/dev/null || true
  chmod g+w "$f" 2>/dev/null || true
  setfacl -m g:$GROUP:rwX,m:rwX "$f" 2>/dev/null || true
done

# تنبيه لو فيه ملفات لسه مش قابلة للكتابة (مملوكة لحد تاني)
BAD=""
while IFS= read -r f; do
  [ -e "$f" ] || continue
  [ -w "$f" ] && continue
  BAD="$BAD  $f\n"
done < <(changed)

if [ -n "$BAD" ]; then
  printf '\n\033[33m[perms]\033[0m ملفات مش قابلة للكتابة من %s — شغّل: sudo ./fix-perms.sh\n' "$ME" >&2
  printf "$BAD" >&2
fi
exit 0
