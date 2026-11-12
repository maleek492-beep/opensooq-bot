"""
OpenSooq Oman rental hunter
- يسحب إعلانات الإيجار من السوق المفتوح عُمان
- يفلتر المكاتب/الوسطاء ويخلي الملّاك فقط
- يرسل الجديد على Discord
- يحفظ الإعلانات اللي شافها في seen.json
"""

import json
import os
import re
import sys
import time
from urllib.parse import quote

# curl_cffi يقلّد بصمة Chrome الحقيقية — بدونه السوق المفتوح يحظر الطلبات
try:
    from curl_cffi import requests as http
    IMPERSONATE = {"impersonate": "chrome"}
except ImportError:  # احتياط فقط، غالباً بينحظر
    import requests as http
    IMPERSONATE = {}

# ========================= الإعدادات =========================

BASE = "https://om.opensooq.com"

# الأقسام اللي يراقبها (عدّل حسب حاجتك)
# مسقط فقط — الموقع نفسه يفلتر المدينة من الرابط
CATEGORIES = [
    "/ar/مسقط/عقارات/عقارات-للإيجار",      # كل عقارات الإيجار في مسقط
    # "/ar/مسقط/عقارات/شقق-للايجار",        # شقق فقط
    # "/ar/مسقط/عقارات/فلل-قصور-للايجار",   # فلل فقط
]

MAX_PAGES = int(os.getenv("MAX_PAGES", "3"))       # كم صفحة لكل قسم
CITY_FILTER = os.getenv("CITY_FILTER", "مسقط")     # فاضي = كل عُمان
MIN_PRICE = float(os.getenv("MIN_PRICE", "0"))
MAX_PRICE = float(os.getenv("MAX_PRICE", "0"))     # 0 = بدون حد
EXCLUDE_DAILY = os.getenv("EXCLUDE_DAILY", "1") == "1"  # استبعد الإيجار اليومي/الفندقي
OWNERS_ONLY = os.getenv("OWNERS_ONLY", "1") == "1"  # يستبعد حسابات "نشاط تجاري" فقط

WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "")
STATE_FILE = "seen.json"
DEBUG = "--debug" in sys.argv

# كلمات تُفحص في اسم المعلن فقط (مو العنوان) — احتياط لو علامة النشاط التجاري ما ظهرت
AGENT_NAME_WORDS = [
    "عقارات", "العقارية", "للتسويق العقاري", "للاستثمار", "شركة", "مؤسسة", "ش.م.م",
    "real estate", "realestate", "properties", "realty", "broker", "agency", "llc", "l.l.c",
]
DAILY_WORDS = ["يومي", "اليومي", "بالساعات", "شاليه", "فندقي", "فندقية", "daily", "per night"]

HEADERS = {
    "Accept-Language": "ar,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ========================= الحالة =========================

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
    else:
        s = {}
    s.setdefault("seen", [])
    s.pop("members", None)
    return s


def save_state(s):
    s["seen"] = s["seen"][-5000:]  # لا يكبر الملف للأبد
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)

# ========================= الجلب =========================

def fetch(url):
    for attempt in range(3):
        try:
            r = http.get(url, headers=HEADERS, timeout=30, **IMPERSONATE)
            if r.status_code == 200:
                return r.text
            print(f"  ⚠️ {r.status_code} على {url}")
        except Exception as e:
            print(f"  ⚠️ خطأ: {e}")
        time.sleep(3 * (attempt + 1))
    return None


def next_data(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


def find_listing_lists(obj, out):
    """يدوّر داخل JSON على أي قائمة عناصر شكلها إعلانات (فيها id + title)."""
    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if len(dicts) >= 3 and sum(1 for d in dicts if "id" in d and pick(d, TITLE_KEYS)) >= 3:
            out.append(dicts)
        for x in obj:
            find_listing_lists(x, out)
    elif isinstance(obj, dict):
        for v in obj.values():
            find_listing_lists(v, out)


TITLE_KEYS = ["title", "post_title", "postTitle", "name"]
PRICE_KEYS = ["price_amount", "priceAmount", "price", "price_value", "priceValue"]
CITY_KEYS = ["city_label", "cityLabel", "city", "city_name"]
HOOD_KEYS = ["nhood_label", "neighborhood_label", "neighborhoodLabel", "nhood", "neighborhood"]
MEMBER_ID_KEYS = ["member_id", "memberId", "user_id", "userId", "seller_id"]
MEMBER_NAME_KEYS = ["member_display_name", "memberDisplayName", "member_name", "full_name", "seller_name"]
IMAGE_KEYS = ["first_image_uri", "image_uri", "imageUri", "image", "main_image", "first_image"]
DATE_KEYS = ["posted_at", "postedAt", "inserted_date", "insertedDate", "published_at", "date"]
HIGHLIGHT_KEYS = ["highlights", "cps_highlights", "subtitle", "description", "masked_description"]


def pick(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            if isinstance(v, dict):  # مثل {"label": "..."} أو {"name": "..."}
                v = v.get("label") or v.get("name") or v.get("value") or v.get("amount")
            return v
    return None


def normalize(d):
    lid = str(d.get("id"))
    price = pick(d, PRICE_KEYS)
    try:
        price_num = float(re.sub(r"[^\d.]", "", str(price))) if price is not None else None
    except ValueError:
        price_num = None
    img = pick(d, IMAGE_KEYS)
    hl = pick(d, HIGHLIGHT_KEYS)
    if isinstance(hl, list):
        hl = " , ".join(str(x.get("label", x) if isinstance(x, dict) else x) for x in hl)
    return {
        "id": lid,
        "title": str(pick(d, TITLE_KEYS) or "").strip(),
        "price": price_num,
        "city": str(pick(d, CITY_KEYS) or ""),
        "hood": str(pick(d, HOOD_KEYS) or ""),
        "member_id": str(pick(d, MEMBER_ID_KEYS) or ""),
        "member_name": str(pick(d, MEMBER_NAME_KEYS) or ""),
        "image": img if isinstance(img, str) and img.startswith("http") else None,
        "date": str(pick(d, DATE_KEYS) or ""),
        "highlights": str(hl or ""),
        "url": f"{BASE}/ar/search/{lid}",
        "raw": json.dumps(d, ensure_ascii=False).lower(),
    }


def parse_page(html):
    data = next_data(html)
    if data:
        lists = []
        find_listing_lists(data, lists)
        if lists:
            biggest = max(lists, key=len)
            return [normalize(d) for d in biggest if d.get("id")]
    # احتياط: نطلع روابط الإعلانات من الـ HTML مباشرة
    ids = list(dict.fromkeys(re.findall(r"/search/(\d{6,})", html)))
    return [{"id": i, "title": "", "price": None, "city": "", "hood": "", "member_id": "",
             "member_name": "", "image": None, "date": "", "highlights": "",
             "url": f"{BASE}/ar/search/{i}", "raw": ""} for i in ids]

# ========================= الفلترة =========================

def is_agent(item):
    """مكتب = حساب نشاط تجاري فقط. المستخدم الموثق (فرد) يعتبر مالك."""
    raw = item["raw"]
    if "نشاط تجاري" in raw:
        return True
    if re.search(r'"(is_shop|isshop|is_business|isbusiness|has_shop)":\s*(true|1)', raw):
        return True
    if re.search(r'"shop_id":\s*"?[1-9]', raw):
        return True
    name = item["member_name"].lower()
    return any(w in name for w in AGENT_NAME_WORDS)


def passes_filters(item):
    if CITY_FILTER:
        loc = f"{item['city']} {item['hood']}"
        if item["city"] and CITY_FILTER not in loc:
            return False
        if not item["city"] and item["raw"] and CITY_FILTER not in item["raw"]:
            return False
    if EXCLUDE_DAILY:
        t = f"{item['title']} {item['highlights']}".lower()
        if any(w in t for w in DAILY_WORDS):
            return False
    if item["price"] is not None:
        if MIN_PRICE and item["price"] < MIN_PRICE:
            return False
        if MAX_PRICE and item["price"] > MAX_PRICE:
            return False
    return True

# ========================= Discord =========================

def send_discord(item):
    if not WEBHOOK:
        print("  (لا يوجد webhook) ", item["title"], item["url"])
        return
    loc = " - ".join(x for x in [item["city"], item["hood"]] if x)
    fields = []
    if item["price"] is not None:
        fields.append({"name": "💰 السعر", "value": f"{item['price']:,.0f} ر.ع", "inline": True})
    if loc:
        fields.append({"name": "📍 الموقع", "value": loc, "inline": True})
    if item["member_name"]:
        fields.append({"name": "👤 المعلن", "value": item["member_name"], "inline": True})
    if item["highlights"]:
        fields.append({"name": "📝 التفاصيل", "value": item["highlights"][:1000], "inline": False})
    embed = {
        "title": (item["title"] or "إعلان إيجار جديد")[:250],
        "url": item["url"],
        "color": 0x00A884,
        "fields": fields,
        "footer": {"text": "السوق المفتوح • مالك مباشر"},
    }
    if item["image"]:
        embed["thumbnail"] = {"url": item["image"]}
    payload = {"embeds": [embed]}
    for _ in range(3):
        r = http.post(WEBHOOK, json=payload, timeout=20)
        if r.status_code == 429:
            wait = float(r.json().get("retry_after", 2))
            time.sleep(wait if wait < 60 else wait / 1000)
            continue
        if r.status_code >= 400:
            print(f"  ⚠️ Discord {r.status_code}: {r.text[:200]}")
        break
    time.sleep(1.2)

# ========================= التشغيل =========================

def main():
    state = load_state()
    seen = set(state["seen"])
    first_run = not state["seen"]
    new_items = []

    for cat in CATEGORIES:
        for page in range(1, MAX_PAGES + 1):
            url = BASE + quote(cat) + (f"?page={page}" if page > 1 else "")
            print(f"📄 {url}")
            html = fetch(url)
            if not html:
                continue
            if DEBUG and page == 1:
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(html)
                nd = next_data(html)
                with open("debug_next_data.json", "w", encoding="utf-8") as f:
                    json.dump(nd, f, ensure_ascii=False, indent=1)
                print("  🐞 حُفظ debug_page.html و debug_next_data.json")
            items = parse_page(html)
            print(f"  ✅ {len(items)} إعلان")
            if not items:
                break
            for it in items:
                if it["id"] in seen:
                    continue
                seen.add(it["id"])
                state["seen"].append(it["id"])
                new_items.append(it)
            time.sleep(2)

    if first_run:
        print(f"🌱 أول تشغيل: تم حفظ {len(new_items)} إعلان كمُشاهد بدون إرسال (عشان ما يغرق القناة)")
        save_state(state)
        return

    sent = 0
    for it in reversed(new_items):  # الأقدم أولاً
        if not passes_filters(it):
            continue
        if OWNERS_ONLY and is_agent(it):
            print(f"  🏢 وسيط/مكتب: {it['title'][:60]}")
            continue
        send_discord(it)
        sent += 1

    print(f"📨 أُرسل {sent} إعلان جديد من أصل {len(new_items)} جديد")
    save_state(state)


if __name__ == "__main__":
    main()
