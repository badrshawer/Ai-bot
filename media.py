"""وحدة الوسائط: تحميل الفيديو، تحويل الصيغ، تفريغ الصوت إلى نص."""
import asyncio
import json
import subprocess
from pathlib import Path

import config

# ---------------------------------------------------------------- تحويل الصيغ

AUDIO_EXT = {"mp3", "m4a", "wav", "ogg", "opus", "flac", "aac"}
VIDEO_EXT = {"mp4", "mkv", "webm", "mov", "avi", "gif"}


def _run(cmd: list[str], timeout: int = 900) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        tail = (p.stderr or "")[-400:]
        raise RuntimeError(f"فشل التنفيذ: {tail}")


def convert_media_sync(src: Path, target_ext: str) -> Path:
    """تحويل صوت/فيديو عبر ffmpeg."""
    target_ext = target_ext.lower().lstrip(".")
    out = src.with_name(src.stem + "_converted." + target_ext)
    cmd = ["ffmpeg", "-y", "-i", str(src)]

    if target_ext in AUDIO_EXT:
        cmd += ["-vn"]
        if target_ext == "mp3":
            cmd += ["-codec:a", "libmp3lame", "-q:a", "3"]
        elif target_ext in ("ogg", "opus"):
            cmd += ["-codec:a", "libopus", "-b:a", "96k"]
        elif target_ext == "m4a":
            cmd += ["-codec:a", "aac", "-b:a", "160k"]
    elif target_ext == "gif":
        cmd += ["-vf", "fps=12,scale=480:-1:flags=lanczos", "-t", "15"]
    elif target_ext == "mp4":
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]

    cmd.append(str(out))
    _run(cmd)
    return out


def compress_video_sync(src: Path, crf: int = 30) -> Path:
    """ضغط فيديو مع تصغير الأبعاد إلى 720p كحد أقصى."""
    out = src.with_name(src.stem + "_small.mp4")
    _run([
        "ffmpeg", "-y", "-i", str(src),
        "-vf", "scale='min(1280,iw)':-2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out),
    ])
    return out


def extract_audio_sync(src: Path) -> Path:
    """استخراج المسار الصوتي بصيغة mono 16k — الأنسب للتفريغ."""
    out = src.with_name(src.stem + "_audio.mp3")
    _run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
          "-codec:a", "libmp3lame", "-q:a", "5", str(out)])
    return out


def media_duration(src: Path) -> float:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(src)],
            capture_output=True, text=True, timeout=60,
        )
        return float(json.loads(p.stdout)["format"]["duration"])
    except Exception:
        return 0.0


async def convert_media(src: Path, ext: str) -> Path:
    return await asyncio.to_thread(convert_media_sync, src, ext)


async def compress_video(src: Path) -> Path:
    return await asyncio.to_thread(compress_video_sync, src)


async def extract_audio(src: Path) -> Path:
    return await asyncio.to_thread(extract_audio_sync, src)


# ------------------------------------------------------------ تحميل من المنصات

def download_sync(url: str, workdir: Path, audio_only: bool = False) -> Path:
    """تحميل فيديو أو صوت برابط عبر yt-dlp، مع محاولة البقاء تحت حد تيليجرام."""
    import yt_dlp

    opts = {
        "outtmpl": str(workdir / "%(title).60s.%(ext)s"),
        "restrictfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "concurrent_fragment_downloads": 4,
    }
    if config.COOKIES_FILE and Path(config.COOKIES_FILE).exists():
        opts["cookiefile"] = config.COOKIES_FILE

    if audio_only:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        # نفضّل نسخة أصغر من 45 ميجا، وإلا ننزل لأقل جودة متاحة
        opts["format"] = (
            "bv*[filesize<40M][height<=720]+ba/b[filesize<45M]/"
            "bv*[height<=480]+ba/worst"
        )
        opts["merge_output_format"] = "mp4"

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))

    if audio_only:
        mp3 = path.with_suffix(".mp3")
        if mp3.exists():
            return mp3
    if not path.exists():  # حالات الدمج تغيّر الامتداد
        for cand in workdir.iterdir():
            if cand.is_file() and cand.stat().st_size > 0:
                return cand
    return path


async def download(url: str, workdir: Path, audio_only: bool = False) -> Path:
    return await asyncio.to_thread(download_sync, url, workdir, audio_only)


# -------------------------------------------------------------- تفريغ الصوت

async def transcribe(src: Path, language: str | None = None) -> str:
    """تفريغ صوت إلى نص عبر واجهة متوافقة مع OpenAI (Whisper)."""
    from openai import AsyncOpenAI

    if not config.WHISPER_API_KEY:
        raise RuntimeError("WHISPER_API_KEY غير مضبوط")

    # نحوّل دائمًا إلى mp3 مضغوط لتقليل الحجم وتفادي الصيغ غير المدعومة
    audio = await extract_audio(src)

    client = AsyncOpenAI(api_key=config.WHISPER_API_KEY, base_url=config.WHISPER_BASE_URL)
    with open(audio, "rb") as f:
        kwargs = {"model": config.WHISPER_MODEL, "file": f}
        if language:
            kwargs["language"] = language
        resp = await client.audio.transcriptions.create(**kwargs)
    return (getattr(resp, "text", "") or "").strip()
