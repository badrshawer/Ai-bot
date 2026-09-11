"""
بوت تيليجرام — مساعد ذكي متكامل
سؤال وجواب · تلخيص · ترجمة · كتابة محتوى · تفريغ صوت
تحميل فيديوهات · تحويل صيغ · ضغط صور · أدوات PDF
"""
import asyncio
import logging
import re
import tempfile
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    constants,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import ai
import config
import filetools
import media

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

URL_RE = re.compile(r"https?://\S+")

HELP = """<b>المساعد الذكي — الأوامر</b>

<b>النصوص</b>
/ask سؤالك — سؤال وجواب (أو اكتب مباشرة بدون أمر)
/sum + نص أو ردّ على رسالة — تلخيص
/tr [اللغة] + نص — ترجمة (مثال: <code>/tr انجليزي</code>)
/write وصف المحتوى — كتابة منشور أو إعلان أو مقال
/reset — مسح سياق المحادثة

<b>الوسائط</b>
/dl رابط — تحميل فيديو من المنصات
/mp3 رابط — تحميل الصوت فقط
أرسل مقطع صوتي أو فيديو → تفريغ، ضغط، استخراج صوت، تحويل

<b>الملفات</b>
أرسل صورة → ضغط أو تحويل أو PDF
أرسل PDF → نص، تلخيص، تقسيم، ضغط، صور
أرسل Word أو Excel أو PowerPoint → تحويل إلى PDF
/merge ثم أرسل عدة ملفات ثم /done — دمج PDF أو صور

/limits — رصيدك اليومي"""


# ------------------------------------------------------------------ مساعدات

async def guard(update: Update) -> bool:
    """تحقّق من الصلاحية والحد اليومي."""
    uid = update.effective_user.id
    if not config.is_allowed(uid):
        await update.effective_message.reply_text("هذا البوت خاص. تواصل مع المشرف للسماح لك.")
        return False
    ok, left = config.check_and_count(uid)
    if not ok:
        await update.effective_message.reply_text(
            f"وصلت الحد اليومي ({config.DAILY_LIMIT} عملية). يتجدد بعد منتصف الليل."
        )
        return False
    return True


async def send_text(update: Update, text: str, title: str = "result") -> None:
    """يرسل نصًا طويلًا مقسّمًا، وإن كان ضخمًا يرسله كملف."""
    msg = update.effective_message
    if not text:
        await msg.reply_text("النتيجة فاضية.")
        return
    if len(text) <= 3500:
        await msg.reply_text(text)
        return
    if len(text) > 12000:
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / f"{title}.txt"
            fp.write_text(text, encoding="utf-8")
            with open(fp, "rb") as f:
                await msg.reply_document(f, filename=fp.name, caption="النتيجة كاملة بالملف")
        return
    for i in range(0, len(text), 3500):
        await msg.reply_text(text[i:i + 3500])


async def fetch_tg_file(context: ContextTypes.DEFAULT_TYPE, file_id: str,
                        dest: Path, name: str) -> Path:
    """تنزيل ملف من تيليجرام إلى مجلد مؤقت."""
    tg_file = await context.bot.get_file(file_id)
    if tg_file.file_size and tg_file.file_size > config.MAX_DOWNLOAD_BYTES:
        raise RuntimeError("الملف أكبر من ٢٠ ميجا — هذا حد تيليجرام لاستقبال البوتات.")
    out = dest / name
    await tg_file.download_to_drive(custom_path=out)
    return out


async def send_file(update: Update, path: Path, caption: str = "") -> None:
    size = path.stat().st_size
    if size > config.MAX_UPLOAD_BYTES:
        await update.effective_message.reply_text(
            f"الناتج {size / 1048576:.1f} ميجا، وتيليجرام يسمح للبوت بـ ٥٠ ميجا فقط.\n"
            "جرّب خيار الضغط أو استخراج الصوت فقط."
        )
        return
    with open(path, "rb") as f:
        await update.effective_message.reply_document(f, filename=path.name, caption=caption)


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows]
    )


async def typing(update: Update) -> None:
    await update.effective_chat.send_action(constants.ChatAction.TYPING)


# ------------------------------------------------------------------- الأوامر

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "أهلًا 👋 أنا مساعدك الذكي.\n"
        "اكتب سؤالك مباشرة، أو أرسل لي ملفًا أو رابطًا وأعطيك الخيارات المتاحة.\n\n"
        "/help لكل الأوامر"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP, parse_mode=constants.ParseMode.HTML)


async def cmd_limits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    used = config._usage[uid][1] if uid in config._usage else 0
    await update.message.reply_text(
        f"استخدمت {used} من {config.DAILY_LIMIT} عملية اليوم."
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("history", None)
    context.user_data.pop("pending", None)
    context.user_data.pop("merge", None)
    await update.message.reply_text("تم مسح السياق. نبدأ من جديد.")


def _arg_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """نص الأمر، أو نص الرسالة المردود عليها."""
    text = " ".join(context.args) if context.args else ""
    reply = update.message.reply_to_message
    if reply and (reply.text or reply.caption):
        text = ((reply.text or reply.caption) + "\n\n" + text).strip()
    return text.strip()


async def cmd_sum(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    text = _arg_text(update, context)
    if not text:
        context.user_data["pending"] = "summarize"
        await update.message.reply_text("أرسل النص المراد تلخيصه.")
        return
    await typing(update)
    await send_text(update, await ai.run("summarize", text), "summary")


async def cmd_tr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    lang = context.args[0] if context.args else "العربية"
    rest = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    reply = update.message.reply_to_message
    if reply and (reply.text or reply.caption):
        rest = (reply.text or reply.caption)
    if not rest:
        context.user_data["pending"] = "translate"
        context.user_data["lang"] = lang
        await update.message.reply_text(f"أرسل النص المراد ترجمته إلى {lang}.")
        return
    await typing(update)
    out = await ai.run("translate", rest, extra=f"اللغة الهدف: {lang}.")
    await send_text(update, out, "translation")


async def cmd_write(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    brief = _arg_text(update, context)
    if not brief:
        context.user_data["pending"] = "write"
        await update.message.reply_text(
            "وش تبي أكتب؟ حدّد النوع والجمهور والطول.\n"
            "مثال: منشور إنستقرام عن عرض تمور سكري، نبرة ودودة، ٤ أسطر."
        )
        return
    await typing(update)
    await send_text(update, await ai.run("write", brief, max_tokens=3000), "content")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    q = _arg_text(update, context)
    if not q:
        await update.message.reply_text("اكتب سؤالك بعد الأمر، أو أرسله مباشرة بدون أمر.")
        return
    await typing(update)
    await send_text(update, await ai.run("ask", q), "answer")


async def cmd_dl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _download_flow(update, context, audio_only=False)


async def cmd_mp3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _download_flow(update, context, audio_only=True)


async def _download_flow(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         audio_only: bool) -> None:
    if not config.ALLOW_VIDEO_DOWNLOAD:
        await update.message.reply_text("ميزة التحميل معطّلة في هذا البوت.")
        return
    if not await guard(update):
        return
    text = " ".join(context.args) if context.args else (update.message.text or "")
    m = URL_RE.search(text)
    if not m:
        await update.message.reply_text("أرسل الرابط بعد الأمر.")
        return
    url = m.group(0)
    status = await update.message.reply_text("جارٍ التحميل… قد يأخذ دقيقة.")
    with tempfile.TemporaryDirectory() as d:
        try:
            path = await media.download(url, Path(d), audio_only=audio_only)
            if path.stat().st_size > config.MAX_UPLOAD_BYTES and not audio_only:
                await status.edit_text("الملف كبير، جارٍ ضغطه…")
                path = await media.compress_video(path)
            await send_file(update, path, caption=path.stem)
            await status.delete()
        except Exception as e:  # noqa: BLE001
            log.exception("download failed")
            await status.edit_text(
                "ما قدرت أحمّل الرابط.\n"
                "غالب الأسباب: المنصة تطلب تسجيل دخول، أو المحتوى محمي، أو عنوان السيرفر محظور.\n"
                f"التفاصيل: {str(e)[:200]}"
            )


async def cmd_merge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["merge"] = []
    await update.message.reply_text(
        "وضع الدمج شغّال. أرسل ملفات PDF أو صور بالترتيب، وبعدها أرسل /done"
    )


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = context.user_data.get("merge")
    if not items:
        await update.message.reply_text("ما فيه ملفات مجمّعة. ابدأ بـ /merge")
        return
    if not await guard(update):
        return
    status = await update.message.reply_text(f"جارٍ دمج {len(items)} ملفات…")
    with tempfile.TemporaryDirectory() as d:
        try:
            paths = []
            for i, (fid, name) in enumerate(items):
                paths.append(await fetch_tg_file(context, fid, Path(d), f"{i:02d}_{name}"))
            pdfs = [p for p in paths if p.suffix.lower() == ".pdf"]
            out = await (filetools.pdf_merge(paths) if len(pdfs) == len(paths)
                         else filetools.images_to_pdf(paths))
            await send_file(update, out, "الملف المدموج")
            await status.delete()
        except Exception as e:  # noqa: BLE001
            log.exception("merge failed")
            await status.edit_text(f"فشل الدمج: {str(e)[:200]}")
    context.user_data.pop("merge", None)


# ------------------------------------------------------------ رسائل النصوص

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    text = (msg.text or "").strip()
    if not text:
        return

    pending = context.user_data.pop("pending", None)
    if pending:
        if not await guard(update):
            return
        await typing(update)
        extra = ""
        if pending == "translate":
            extra = f"اللغة الهدف: {context.user_data.get('lang', 'العربية')}."
        await send_text(update, await ai.run(pending, text, extra=extra, max_tokens=3000))
        return

    # رابط بدون أمر
    if URL_RE.fullmatch(text) and config.ALLOW_VIDEO_DOWNLOAD:
        context.user_data["url"] = text
        await msg.reply_text(
            "رابط. وش تبي أسوي فيه؟",
            reply_markup=kb([
                [("⬇️ فيديو", "url:video"), ("🎵 صوت MP3", "url:audio")],
                [("📝 تفريغ نص", "url:transcribe")],
            ]),
        )
        return

    # سؤال وجواب عادي مع سياق قصير
    if not await guard(update):
        return
    await typing(update)
    history = context.user_data.setdefault("history", [])
    history.append({"role": "user", "content": text})
    try:
        answer = await ai.chat(history)
    except Exception as e:  # noqa: BLE001
        log.exception("chat failed")
        history.pop()
        await msg.reply_text(f"صار خطأ في الذكاء الاصطناعي: {str(e)[:200]}")
        return
    history.append({"role": "assistant", "content": answer})
    del history[:-12]
    await send_text(update, answer, "answer")


# ------------------------------------------------------------- استقبال ملفات

def _remember(context: ContextTypes.DEFAULT_TYPE, file_id: str, name: str) -> None:
    context.user_data["file"] = {"id": file_id, "name": name}


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]
    if context.user_data.get("merge") is not None:
        context.user_data["merge"].append((photo.file_id, f"img{len(context.user_data['merge'])}.jpg"))
        await update.message.reply_text(f"أُضيفت ({len(context.user_data['merge'])}). /done للدمج")
        return
    _remember(context, photo.file_id, "image.jpg")
    await update.message.reply_text(
        "صورة. الخيارات:",
        reply_markup=kb([
            [("🗜 ضغط", "img:compress"), ("🗜 ضغط قوي", "img:compress_hard")],
            [("📄 تحويل PDF", "img:pdf"), ("🖼 PNG", "img:png"), ("🖼 WEBP", "img:webp")],
        ]),
    )


async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    m = update.message
    obj = m.voice or m.audio
    name = getattr(obj, "file_name", None) or "audio.ogg"
    _remember(context, obj.file_id, name)
    await m.reply_text(
        "مقطع صوتي. الخيارات:",
        reply_markup=kb([
            [("📝 تفريغ نص", "aud:transcribe")],
            [("📝 تفريغ + تلخيص", "aud:transcribe_sum"),
             ("📝 تفريغ + ترجمة", "aud:transcribe_tr")],
            [("🎵 تحويل MP3", "aud:mp3")],
        ]),
    )


async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    m = update.message
    obj = m.video or m.video_note or m.animation
    name = getattr(obj, "file_name", None) or "video.mp4"
    _remember(context, obj.file_id, name)
    await m.reply_text(
        "فيديو. الخيارات:",
        reply_markup=kb([
            [("🗜 ضغط", "vid:compress"), ("🎵 استخراج MP3", "vid:mp3")],
            [("📝 تفريغ نص", "vid:transcribe"), ("🎞 تحويل GIF", "vid:gif")],
        ]),
    )


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    name = doc.file_name or "file"
    ext = Path(name).suffix.lower().lstrip(".")

    if context.user_data.get("merge") is not None:
        context.user_data["merge"].append((doc.file_id, name))
        await update.message.reply_text(f"أُضيف ({len(context.user_data['merge'])}). /done للدمج")
        return

    _remember(context, doc.file_id, name)

    if ext == "pdf":
        await update.message.reply_text(
            "ملف PDF. الخيارات:",
            reply_markup=kb([
                [("📃 استخراج النص", "pdf:text"), ("📌 تلخيص", "pdf:sum")],
                [("🗜 ضغط", "pdf:compress"), ("✂️ تقسيم صفحات", "pdf:split")],
                [("🖼 تحويل صور", "pdf:images"), ("🌐 ترجمة", "pdf:tr")],
            ]),
        )
    elif ext in filetools.OFFICE_EXT:
        await update.message.reply_text(
            "مستند. الخيارات:",
            reply_markup=kb([
                [("📄 تحويل PDF", "off:pdf")],
                [("📌 تلخيص المحتوى", "off:sum")],
            ]),
        )
    elif ext in {"jpg", "jpeg", "png", "webp", "bmp", "tiff", "heic"}:
        await update.message.reply_text(
            "صورة. الخيارات:",
            reply_markup=kb([
                [("🗜 ضغط", "img:compress"), ("🗜 ضغط قوي", "img:compress_hard")],
                [("📄 PDF", "img:pdf"), ("🖼 JPG", "img:jpg"), ("🖼 PNG", "img:png")],
            ]),
        )
    elif ext in media.AUDIO_EXT:
        await on_audio_doc(update, context, doc.file_id, name)
    elif ext in media.VIDEO_EXT:
        _remember(context, doc.file_id, name)
        await update.message.reply_text(
            "فيديو. الخيارات:",
            reply_markup=kb([
                [("🗜 ضغط", "vid:compress"), ("🎵 MP3", "vid:mp3")],
                [("📝 تفريغ نص", "vid:transcribe")],
            ]),
        )
    else:
        await update.message.reply_text(
            f"صيغة .{ext} غير مدعومة حاليًا.\n"
            "المدعوم: صور، صوت، فيديو، PDF، Word، Excel، PowerPoint."
        )


async def on_audio_doc(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       fid: str, name: str) -> None:
    _remember(context, fid, name)
    await update.message.reply_text(
        "ملف صوتي. الخيارات:",
        reply_markup=kb([
            [("📝 تفريغ نص", "aud:transcribe")],
            [("📝 تفريغ + تلخيص", "aud:transcribe_sum"), ("🎵 MP3", "aud:mp3")],
        ]),
    )


# ------------------------------------------------------------ تنفيذ الأزرار

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    group, _, action = q.data.partition(":")

    if group == "url":
        await _handle_url_button(update, context, action)
        return

    info = context.user_data.get("file")
    if not info:
        await q.edit_message_text("انتهت صلاحية الملف. أعد إرساله من فضلك.")
        return
    if not await guard(update):
        return

    await q.edit_message_text("جارٍ التنفيذ…")
    with tempfile.TemporaryDirectory() as d:
        try:
            src = await fetch_tg_file(context, info["id"], Path(d), info["name"])
            await _dispatch(update, context, group, action, src)
        except Exception as e:  # noqa: BLE001
            log.exception("action failed: %s:%s", group, action)
            await update.effective_message.reply_text(f"صار خطأ: {str(e)[:300]}")


async def _dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE,
                    group: str, action: str, src: Path) -> None:
    msg = update.effective_message

    # ---------- صور ----------
    if group == "img":
        if action in ("compress", "compress_hard"):
            before = src.stat().st_size
            out = await filetools.compress_image(src, quality=45 if action.endswith("hard") else 72)
            after = out.stat().st_size
            await send_file(update, out,
                            f"{before / 1024:.0f}KB ← {after / 1024:.0f}KB "
                            f"(توفير {100 - after * 100 // max(before, 1)}%)")
        elif action == "pdf":
            await send_file(update, await filetools.images_to_pdf([src]))
        else:
            await send_file(update, await filetools.convert_image(src, action))
        return

    # ---------- صوت ----------
    if group == "aud":
        if action == "mp3":
            await send_file(update, await media.convert_media(src, "mp3"))
            return
        await msg.reply_text("جارٍ التفريغ…")
        text = await media.transcribe(src)
        if not text:
            await msg.reply_text("ما طلع نص من المقطع.")
            return
        await send_text(update, text, "transcript")
        if action == "transcribe_sum":
            await send_text(update, await ai.run("summarize", text), "summary")
        elif action == "transcribe_tr":
            await send_text(update, await ai.run("translate", text,
                                                 extra="اللغة الهدف: العربية."), "translation")
        return

    # ---------- فيديو ----------
    if group == "vid":
        if action == "compress":
            before = src.stat().st_size
            out = await media.compress_video(src)
            await send_file(update, out,
                            f"{before / 1048576:.1f}MB ← {out.stat().st_size / 1048576:.1f}MB")
        elif action == "mp3":
            await send_file(update, await media.extract_audio(src))
        elif action == "gif":
            await send_file(update, await media.convert_media(src, "gif"))
        elif action == "transcribe":
            await msg.reply_text("جارٍ التفريغ…")
            await send_text(update, await media.transcribe(src), "transcript")
        return

    # ---------- PDF ----------
    if group == "pdf":
        if action in ("text", "sum", "tr"):
            text = await filetools.pdf_extract_text(src)
            if not text.strip():
                await msg.reply_text(
                    "الملف يبدو صورًا ممسوحة بدون طبقة نص. "
                    "حوّله إلى صور ثم أرسل الصور للتفريغ."
                )
                return
            if action == "text":
                await send_text(update, text, "pdf_text")
            elif action == "sum":
                await send_text(update, await ai.run("summarize", text, max_tokens=3000), "summary")
            else:
                await send_text(update, await ai.run("translate", text,
                                                     extra="اللغة الهدف: العربية.",
                                                     max_tokens=4000), "translation")
        elif action == "compress":
            before = src.stat().st_size
            out = await filetools.pdf_compress(src)
            await send_file(update, out,
                            f"{before / 1048576:.2f}MB ← {out.stat().st_size / 1048576:.2f}MB")
        elif action == "split":
            pages = await filetools.pdf_split(src)
            await msg.reply_text(f"عدد الصفحات المرسلة: {len(pages)}")
            for p in pages:
                await send_file(update, p)
                await asyncio.sleep(0.4)
        elif action == "images":
            imgs = await filetools.pdf_to_images(src)
            for p in imgs:
                with open(p, "rb") as f:
                    await msg.reply_photo(f)
                await asyncio.sleep(0.4)
        return

    # ---------- مستندات ----------
    if group == "off":
        pdf = await filetools.office_convert(src, "pdf")
        if action == "pdf":
            await send_file(update, pdf)
        else:
            text = await filetools.pdf_extract_text(pdf)
            await send_text(update, await ai.run("summarize", text, max_tokens=3000), "summary")
        return


async def _handle_url_button(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             action: str) -> None:
    url = context.user_data.get("url")
    q = update.callback_query
    if not url:
        await q.edit_message_text("انتهت صلاحية الرابط، أرسله مرة ثانية.")
        return
    if not await guard(update):
        return
    await q.edit_message_text("جارٍ المعالجة…")
    with tempfile.TemporaryDirectory() as d:
        try:
            path = await media.download(url, Path(d), audio_only=(action != "video"))
            if action == "transcribe":
                text = await media.transcribe(path)
                await send_text(update, text, "transcript")
            else:
                if path.stat().st_size > config.MAX_UPLOAD_BYTES:
                    path = await media.compress_video(path)
                await send_file(update, path, caption=path.stem)
        except Exception as e:  # noqa: BLE001
            log.exception("url action failed")
            await update.effective_message.reply_text(
                f"ما قدرت أعالج الرابط: {str(e)[:250]}"
            )


# ---------------------------------------------------------------- التشغيل

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled error", exc_info=context.error)


def build() -> Application:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN غير مضبوط في متغيّرات البيئة")

    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .read_timeout(90)
        .write_timeout(180)
        .connect_timeout(30)
        .concurrent_updates(True)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("limits", cmd_limits))
    app.add_handler(CommandHandler(["reset", "cancel"], cmd_reset))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler(["sum", "summarize"], cmd_sum))
    app.add_handler(CommandHandler(["tr", "translate"], cmd_tr))
    app.add_handler(CommandHandler("write", cmd_write))
    app.add_handler(CommandHandler(["dl", "download"], cmd_dl))
    app.add_handler(CommandHandler("mp3", cmd_mp3))
    app.add_handler(CommandHandler("merge", cmd_merge))
    app.add_handler(CommandHandler("done", cmd_done))

    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_audio))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE | filters.ANIMATION, on_video))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)
    return app


if __name__ == "__main__":
    log.info("Bot starting…")
    build().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
