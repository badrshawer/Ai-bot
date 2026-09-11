FROM python:3.12-slim

# ffmpeg للوسائط، LibreOffice لتحويل المستندات، الخطوط لدعم العربية
# ملاحظة: LibreOffice يكبّر حجم الصورة ~500 ميجا.
# إذا ما تحتاج تحويل Word/Excel/PowerPoint، احذف الأسطر الثلاثة الخاصة به.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-noto-core \
    libreoffice-writer-nogui \
    libreoffice-calc-nogui \
    libreoffice-impress-nogui \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]
