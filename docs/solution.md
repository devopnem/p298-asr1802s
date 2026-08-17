# 1) افتح الموديول على الراوتر الجديد
python3 acs_tr069.py root-check
#  ↳ يكتشف dropbear_password من U-Boot env ويثبت root تلقائياً
#  ↳ مثال الناتج: "uid=0(root)"  → مباشرة، أو "فشل" → الخطوة 2

# 2) إذا فشل (dropbear_password فارغة/مختلطة) — ضع كلمة مرورك الخاصة:
python3 acs_tr069.py arm-root-pw --password اخترها_أنت
#  ↳ يكتب الـ shadow root بـ hash md5crypt (salt 123456) عبر %EXE، ثم reboot

# 3) دخول SSH المباشر:
sshpass -p "$(python3 acs_tr069.py root-shell --discover-pw)" ssh \
  -o PreferredAuthentications=password -o HostKeyAlgorithms=ssh-rsa \
  -o KexAlgorithms=diffie-hellman-group1-sha1,diffie-hellman-group14-sha1 \
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  root@192.168.1.1
# أو ببساطة:
python3 acs_tr069.py root-shell --command "id"     # يعمل كل شيء نيابةً عنك
إجابة على سؤالك المباشرة: "هل أحتاج تفعيل ssh من API ثم دخول مباشر، وهل 19222019 عامة؟"
تفعيل ssh الكافي؟ بحاجة إلى تفعيل eng_mode=2 + dropbear_mode=1 (عبر cm/set_eng_mode و router/set_dropbear_info — كما في api_ssh.full_enable_ssh). لكن هذا غير كافٍ: التفعيل يفتح المنفذ، لكن كلمة المرور للدخول يجب أن تُعرف أو تُضبوط؛ ولهذا فقط الـ API ما يفتقدش كلمة المرور.
هل 19222019 العامة؟ — كلا. 19222019 هي قيمة dropbear_password الخاصة بمنصتك هذه فقط؛ على الأجهزة الأخرى قد تكون مختلفة أو فارغة. لا تعتمد عليها؛ استخدم --discover-pw دائماً.
الملف المنهي
modular_tests/acs_tr069.py — وحدة واحدة موحدة (7 أجزاء + CLI) تشمل:
Part 2–5: خوادم ACS/FOTA + سطر الأوامر (كما طلبت).
Part 6 (المفيد الآن): discover_root_password / root-check / root-shell / arm-root-pw — ال
