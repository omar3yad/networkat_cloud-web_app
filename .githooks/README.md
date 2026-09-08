# .githooks

صلاحيات الملفات في الـ repo دي لازم تفضل **قابلة للكتابة من جروب `devteam`**
(`chmod g+w` + ACL). كل الفريق في الجروب، فأي حد يقدر يعدّل شغل أي حد.

## تفعيل الـ hooks (مرة واحدة لكل نسخة repo)

```bash
git config core.hooksPath .githooks
```

بعدها `post-merge` و `post-checkout` بيشغّلوا `_fix-perms-safe.sh` تلقائياً بعد
كل `git pull` / تبديل فرع، ويصلّحوا صلاحيات الملفات الجديدة (بدون `sudo`).

## لو ظهر تحذير `[perms] ملفات مش قابلة للكتابة`

يعني فيه ملفات مملوكة لمستخدم تاني ومحتاجة إصلاح إداري:

```bash
sudo ./fix-perms.sh
```

## الوقاية على مستوى النظام (متعملة على السيرفر)

- `umask=0002` عبر `pam_umask` في `/etc/pam.d/common-session*`
- `setgid` + default ACL لجروب `devteam` على كل مجلدات الشجرة
- كل مطوّر لازم يكون `umask 0002` في `~/.bashrc` — خصوصاً لو بيحرر من Windows
  عبر VS Code Remote أو SFTP (اضبط `file_mode 0664` / `dir_mode 0775` في إعداد الـ sync).
