# Live Terminal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** شاشة عربية مستمرة لإشارات مشروع om من الترمينال.
**Architecture:** فصل جلب Yahoo بلا حفظ عن التنزيل القديم؛ وحدة live.py للتحليل
وإدارة حداثة البيانات والتعافي والعرض؛ main.py يضيف --live و--refresh.
**Tech Stack:** Python 3.11–3.13، pandas/ta/yfinance الحالية وANSI في TTY فقط.
**Spec:** docs/superpowers/specs/2026-10-06-live-terminal-design.md

## Global Constraints
- شموع 1m مغلقة فقط؛ حد التأخر 180 ثانية من نهاية الشمعة.
- refresh الافتراضي 60، والحد الأدنى 30 ثانية؛ أخطاء المصدر تتراجع حتى 900.
- لا CSV بديل، لا أسعار مصطنعة في وضع المستخدم، لا ملفات لكل تحديث.
- لا تغيرات على الموقع الآخر أو MT5 أو الخدمات السابقة.

## Review Focus
- عطلات السوق: لا ادعاء تقويم؛ بيانات متأخرة تعلق التوصية.
- آخر شمعة بلا مؤشرات: لا استخدام أقدم إشارة كتوصية حالية.
- انقطاع ثم رجوع بيانات أقدم: آخر عرض مقبول يبقى كسجل مع خطأ واضح.
- stdout ليس TTY: نص قابل للحفظ دون ANSI أو مسح طرفية.
- Ctrl+C أثناء الجلب أو الانتظار: توقف نظيف.

### Task 1: Fetch without repeated files
**Files:** data/downloader.py، tests/test_live.py
**Interfaces:** YahooDownloader.fetch(symbol, period=None, interval=None) → normalized DataFrame؛ download يحفظ كما كان.
- [ ] كتابة اختبار جلب فعلي المعالجة مع عزل yf.download؛ تحقق UTC وعدم إنشاء ملفات.
- [ ] تشغيله ومشاهدة فشل غياب fetch.
- [ ] فصل fetch وتكرار اختبار التنزيل القديم مع الاختبار الجديد.

### Task 2: Continuous analysis, freshness and terminal display
**Files:** live.py، tests/test_live.py
**Interfaces:** analyze_snapshot(df, now) → LiveSnapshot؛ LiveMonitor(fetch, refresh).step(now)؛ render_screen(monitor, now, rows) → str؛ run_live(args).
- [ ] اختبارات حدود إغلاق الدقيقة، الإشارة الحالية مقابل المتأخرة وخارج الجلسة، غياب مؤشرات آخر شمعة، رجوع المصدر والانقطاع والتعافي والتراجع.
- [ ] تشغيل الاختبارات ومشاهدة غياب الواجهة.
- [ ] تنفيذ الوحدة والعرض العربي وتكرار الاختبارات.

### Task 3: CLI and release
**Files:** main.py، README.md، tests/test_live.py
- [ ] اختبارات تشغيل --live مع مصدر شبكي معزول، تحديث شمعة جديدة ثم انقطاع ثم تعافٍ، ووقف Ctrl+C؛ رفض --input و--live أو فاصل غير 1m أو refresh غير صالح.
- [ ] مشاهدة الفشل، ثم إضافة CLI وتوثيق أمر تشغيل كامل.
- [ ] تشغيل suite كاملة وpip check وshell syntax وdiff check وتجربة شبكة حقيقية.
- [ ] مراجعة الكود ورفع الملفات المختبرة إلى main بمقارنة SHA وشجرة git.
