"""وحدة الملفات: ضغط الصور، عمليات PDF، تحويل المستندات."""
import asyncio
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

# ------------------------------------------------------------------- الصور

def compress_image_sync(src: Path, quality: int = 72, max_side: int = 2000) -> Path:
    """ضغط صورة مع تصغير الأبعاد الكبيرة والحفاظ على اتجاه الصورة."""
    out = src.with_name(src.stem + "_compressed.jpg")
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        im.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out


def convert_image_sync(src: Path, target_ext: str) -> Path:
    """تحويل صيغة صورة (png/jpg/webp/pdf...)."""
    target_ext = target_ext.lower().lstrip(".")
    out = src.with_name(src.stem + "." + target_ext)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if target_ext in ("jpg", "jpeg", "pdf"):
            im = im.convert("RGB")
        im.save(out)
    return out


async def compress_image(src: Path, quality: int = 72) -> Path:
    return await asyncio.to_thread(compress_image_sync, src, quality)


async def convert_image(src: Path, ext: str) -> Path:
    return await asyncio.to_thread(convert_image_sync, src, ext)


# --------------------------------------------------------------------- PDF

def pdf_extract_text_sync(src: Path) -> str:
    import pdfplumber
    chunks = []
    with pdfplumber.open(src) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n\n".join(c for c in chunks if c.strip())


def pdf_split_sync(src: Path) -> list[Path]:
    """يفصل كل صفحة في ملف مستقل (بحد 30 صفحة لتفادي إغراق المحادثة)."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(str(src))
    outs = []
    for i, page in enumerate(reader.pages[:30]):
        writer = PdfWriter()
        writer.add_page(page)
        out = src.with_name(f"{src.stem}_page{i + 1}.pdf")
        with open(out, "wb") as f:
            writer.write(f)
        outs.append(out)
    return outs


def pdf_merge_sync(files: list[Path]) -> Path:
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for fp in files:
        for page in PdfReader(str(fp)).pages:
            writer.add_page(page)
    out = files[0].with_name("merged.pdf")
    with open(out, "wb") as f:
        writer.write(f)
    return out


def pdf_compress_sync(src: Path, dpi: int = 110) -> Path:
    """ضغط PDF: تنظيف الملف أولًا، وإن بقي كبيرًا يُعاد بناؤه كصور مضغوطة."""
    import pymupdf

    out = src.with_name(src.stem + "_compressed.pdf")
    doc = pymupdf.open(src)
    doc.save(out, garbage=4, deflate=True, clean=True)
    doc.close()

    if out.stat().st_size > src.stat().st_size * 0.8:
        rebuilt = src.with_name(src.stem + "_compressed2.pdf")
        doc = pymupdf.open(src)
        new = pymupdf.open()
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            jpg = pix.tobytes("jpeg", jpg_quality=60)
            npage = new.new_page(width=page.rect.width, height=page.rect.height)
            npage.insert_image(npage.rect, stream=jpg)
        new.save(rebuilt, garbage=4, deflate=True)
        new.close()
        doc.close()
        if rebuilt.stat().st_size < out.stat().st_size:
            return rebuilt
    return out


def pdf_to_images_sync(src: Path, dpi: int = 140, limit: int = 20) -> list[Path]:
    import pymupdf
    doc = pymupdf.open(src)
    outs = []
    for i, page in enumerate(doc):
        if i >= limit:
            break
        pix = page.get_pixmap(dpi=dpi)
        out = src.with_name(f"{src.stem}_p{i + 1}.jpg")
        pix.save(out)
        outs.append(out)
    doc.close()
    return outs


def images_to_pdf_sync(files: list[Path]) -> Path:
    imgs = []
    for fp in files:
        im = Image.open(fp)
        im = ImageOps.exif_transpose(im).convert("RGB")
        imgs.append(im)
    out = files[0].with_name("images.pdf")
    imgs[0].save(out, "PDF", save_all=True, append_images=imgs[1:])
    return out


async def pdf_extract_text(src: Path) -> str:
    return await asyncio.to_thread(pdf_extract_text_sync, src)


async def pdf_split(src: Path) -> list[Path]:
    return await asyncio.to_thread(pdf_split_sync, src)


async def pdf_merge(files: list[Path]) -> Path:
    return await asyncio.to_thread(pdf_merge_sync, files)


async def pdf_compress(src: Path) -> Path:
    return await asyncio.to_thread(pdf_compress_sync, src)


async def pdf_to_images(src: Path) -> list[Path]:
    return await asyncio.to_thread(pdf_to_images_sync, src)


async def images_to_pdf(files: list[Path]) -> Path:
    return await asyncio.to_thread(images_to_pdf_sync, files)


# --------------------------------------------------------------- المستندات

OFFICE_EXT = {"doc", "docx", "odt", "rtf", "xls", "xlsx", "ods", "ppt", "pptx", "odp", "txt", "csv"}


def office_convert_sync(src: Path, target_ext: str = "pdf") -> Path:
    """تحويل مستندات Office عبر LibreOffice بدون واجهة."""
    outdir = src.parent
    p = subprocess.run(
        ["soffice", "--headless", "--norestore", "--convert-to", target_ext,
         "--outdir", str(outdir), str(src)],
        capture_output=True, text=True, timeout=600,
    )
    out = outdir / (src.stem + "." + target_ext)
    if not out.exists():
        raise RuntimeError(f"فشل التحويل: {(p.stderr or p.stdout)[-300:]}")
    return out


async def office_convert(src: Path, ext: str = "pdf") -> Path:
    return await asyncio.to_thread(office_convert_sync, src, ext)
