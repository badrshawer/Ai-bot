"""وحدة الذكاء الاصطناعي: سؤال وجواب، تلخيص، ترجمة، كتابة محتوى."""
import anthropic
import config

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY غير مضبوط")
        _client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


SYSTEMS = {
    "ask": (
        "أنت مساعد ذكي داخل بوت تيليجرام. أجب بدقة وباختصار مناسب لشاشة الجوال. "
        "استخدم لغة السائل نفسها. إذا كنت غير متأكد قل ذلك بدل التخمين."
    ),
    "summarize": (
        "أنت مختص تلخيص. لخّص النص التالي بنقاط واضحة تحفظ المعلومات الأساسية والأرقام والأسماء، "
        "بنفس لغة النص الأصلي، وبما لا يتجاوز ثلث الطول الأصلي. لا تضف معلومات من عندك."
    ),
    "translate": (
        "أنت مترجم محترف. ترجم النص ترجمة طبيعية سليمة لا حرفية، مع الحفاظ على المعنى والنبرة "
        "وتنسيق الفقرات. أخرج الترجمة فقط بدون أي شرح أو مقدمة."
    ),
    "write": (
        "أنت كاتب محتوى تسويقي وتحريري محترف بالعربية والإنجليزية. اكتب محتوى أصليًا جاهزًا للنشر "
        "حسب طلب المستخدم: احترم الجمهور والمنصة والطول المطلوب، وابتعد عن الحشو والعبارات المستهلكة."
    ),
    "transcript": (
        "أنت محرّر تفريغات. نظّف النص المفرّغ التالي: أضف الترقيم والفقرات، واحذف التكرار والحشو، "
        "دون تغيير المعنى أو حذف معلومات. أخرج النص المنقّح فقط."
    ),
}


async def run(task: str, user_text: str, extra: str = "", max_tokens: int = 2000) -> str:
    """ينفّذ مهمة نصية واحدة ويرجّع النص الناتج."""
    text = user_text[: config.MAX_TEXT_CHARS]
    system = SYSTEMS.get(task, SYSTEMS["ask"])
    if extra:
        system += "\n" + extra

    resp = await client().messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": text}],
    )
    out = "".join(b.text for b in resp.content if b.type == "text").strip()
    return out or "ما قدرت أطلّع نتيجة، جرّب تعيد الصياغة."


async def chat(history: list[dict], max_tokens: int = 1500) -> str:
    """محادثة متعددة الأدوار — history عبارة عن [{'role':'user','content':'...'}, ...]"""
    resp = await client().messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=SYSTEMS["ask"],
        messages=history[-12:],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
