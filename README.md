# بوت السوق المفتوح — إعلانات الإيجار (ملّاك فقط)

## التركيب
1. ارفع الملفات لريبو جديد على GitHub بنفس الترتيب:
   ```
   opensooq_bot.py
   requirements.txt
   .github/workflows/opensooq.yml
   ```
2. Settings → Secrets and variables → Actions → New secret
   - الاسم: `OPENSOOQ_WEBHOOK_URL`
   - القيمة: رابط Webhook قناة Discord
3. Settings → Actions → General → Workflow permissions → **Read and write**
4. Actions → OpenSooq Rental Hunter → Run workflow (مع تفعيل debug أول مرة)

## أول تشغيل
- يحفظ كل الإعلانات الموجودة كـ"مُشاهدة" بدون إرسال، عشان القناة ما تغرق.
- من التشغيل الثاني يرسل الجديد فقط.
- إذا طلع `✅ 0 إعلان` أو بيانات ناقصة: نزّل ملف `opensooq-debug` من صفحة التشغيل وأرسله، وأعدّل المفاتيح.

## الإعدادات (في opensooq.yml)
| المتغير | الافتراضي | الوظيفة |
|---|---|---|
| CITY_FILTER | مسقط | فاضي = كل عُمان |
| MAX_PAGES | 3 | عدد الصفحات لكل قسم |
| EXCLUDE_DAILY | 1 | يستبعد الإيجار اليومي والفندقي |
| OWNERS_ONLY | 1 | يستبعد حسابات النشاط التجاري |
| MIN_PRICE / MAX_PRICE | 0 | حدود السعر (0 = بدون حد) |

## كشف المكاتب
- **حساب نشاط تجاري موثق = مكتب** ← يُستبعد
- **مستخدم موثق = فرد/مالك** ← يُرسل
- احتياط: اسم المعلن فيه (عقارات، شركة، Real Estate، LLC…)
