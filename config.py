"""إعدادات البوت — كل القيم تُقرأ من متغيّرات البيئة (Environment Variables)."""
import os
from datetime import date
from collections import defaultdict

# ---------- المفاتيح ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# الذكاء الاصطناعي للنصوص (Anthropic)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

# تفريغ الصوت (أي مزوّد متوافق مع OpenAI — الافتراضي Groq لأنه سريع ورخيص)
WHISPER_API_KEY = os.environ.get("WHISPER_API_KEY", "")
WHISPER_BASE_URL = os.environ.get("WHISPER_BASE_URL", "https://api.groq.com/openai/v1")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "whisper-large-v3")

# ---------- الحدود ----------
# حدود تيليجرام نفسها (لا يمكن تجاوزها ببوت عادي)
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024   # أكبر ملف يقدر البوت يستقبله
MAX_UPLOAD_BYTES = 50 * 1024 * 1024     # أكبر ملف يقدر البوت يرسله

DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "30"))          # عدد العمليات لكل مستخدم يوميًا
MAX_TEXT_CHARS = int(os.environ.get("MAX_TEXT_CHARS", "60000"))  # سقف النص المرسل للنموذج

# تحميل الفيديو من المنصات: أطفئه بوضع القيمة 0 إذا ما تبي تفعّله
ALLOW_VIDEO_DOWNLOAD = os.environ.get("ALLOW_VIDEO_DOWNLOAD", "1") == "1"
# ملف كوكيز yt-dlp (اختياري) — يساعد لما يطلب يوتيوب تحقّق من السيرفر
COOKIES_FILE = os.environ.get("COOKIES_FILE", "")

# معرّفات المشرفين (مفصولة بفواصل) — معفيون من الحد اليومي
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()
}

# قائمة بيضاء اختيارية: إذا تركتها فاضية، البوت مفتوح للجميع
ALLOWED_USERS = {
    int(x) for x in os.environ.get("ALLOWED_USERS", "").replace(" ", "").split(",") if x.isdigit()
}

# ---------- عدّاد الاستخدام اليومي ----------
_usage: dict[int, list] = defaultdict(lambda: [date.today(), 0])


def check_and_count(user_id: int) -> tuple[bool, int]:
    """يرجّع (مسموح؟، المتبقي). يصفّر العدّاد تلقائيًا كل يوم."""
    if user_id in ADMIN_IDS:
        return True, 9999
    rec = _usage[user_id]
    if rec[0] != date.today():
        rec[0], rec[1] = date.today(), 0
    if rec[1] >= DAILY_LIMIT:
        return False, 0
    rec[1] += 1
    return True, DAILY_LIMIT - rec[1]


def is_allowed(user_id: int) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS or user_id in ADMIN_IDS
