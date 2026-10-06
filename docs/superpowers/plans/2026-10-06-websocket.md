# WebSocket Prices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Use checkbox steps.

**Goal:** اتصال أسعار مفتوح بنبضات لشاشة om نفسها.
**Architecture:** data/streamer.py لنقل Yahoo وفك الرسائل وحالة السعر؛ websocket_live.py
لمزامنة الشاشة وhistory الخلفي؛ live.py يعرض السعر وحالته مع توصية الشمعة المغلقة.
**Tech Stack:** Python3.11–3.13، websockets17.2 مثبت مباشرة، yfinance1.7.0 PricingData.
**Spec:** docs/superpowers/specs/2026-10-06-websocket-design.md

## Global Constraints
- Ping/Pong20s، timeout20s؛ subscribe heartbeat15s؛ reconnect1→60s.
- سعر المصدر يصبح متأخرًا بعد30s؛ المستقبل>5s مرفوض؛ لا أسعار/أحجام مصطنعة.
- history daemon مستقل؛ بيانات السعر لا تنتج مؤشرات حجم أو شموعًا وهمية.
- --live يستخدم WebSocket افتراضيًا؛ الوضع القديم --transport poll.

## Review Focus
- Pong دون quote لا يسمح بتوصية أو ادعاء سعر حي.
- انقطاع أو إغلاق طبيعي يعيد الاشتراك ويعلّق التوصية فورًا.
- history المحجوب لا يحجب tick/heartbeat أو خروج Ctrl+C.
- futures/الرسائل غير الصحيحة/out-of-order لا تستبدل آخر quote صالح.
- كل مهمة دورية تلغى مع الاتصال؛ لا heartbeat قديم على socket جديد.

### Task 1: Stream transport and quote validation
**Files:** data/streamer.py، tests/test_websocket.py، requirements.txt
**Interfaces:** Quote؛ QuoteFeed.accept(raw, now)، QuoteFeed.status(now)، YahooPriceStream.run(feed, notify).
- [ ] كتابة اختبارات protobuf/التوقيت ثم رؤية RED لغياب الوحدة.
- [ ] تنفيذ التحقق من quote وحالته.
- [ ] اختبار خادم WS محلي فعلي للاشتراك والheartbeat وإغلاق/إعادة الاتصال والإلغاء.
- [ ] تنفيذ الاتصال والمقارنة مع البروتوكول المثبت؛ GREEN.

### Task 2: Display, background history and entry point
**Files:** websocket_live.py، live.py، main.py، README.md، tests/test_websocket.py، tests/test_live.py
**Interfaces:** run_websocket_async(args, stream=None, clock=None, ws_url=Yahoo)؛ run_websocket(args).
- [ ] RED: تحديث السعر مع history بطيء، تعليق التوصية عند فقد quote، CLI transport.
- [ ] تنفيذ runner async والشاشة مع quote/history مستقلين؛ الإلغاء يغلق المهام.
- [ ] GREEN: suite كاملة وpip check وshell syntax وdiff check.
- [ ] مراجعة مستقلة؛ probe خارجي مع نتيجة مصافحة/Pong/quote محددة.
- [ ] نشر الشجرة المختبرة على main بمقارنة SHA وتقديم أمر التشغيل.
