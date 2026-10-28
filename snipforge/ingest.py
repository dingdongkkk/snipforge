"""Requirement upload: extract plain text from documents so they can be analysed like typed requirements.

Supported: .txt .md .py .json .csv .yaml (decode), .docx (stdlib zip/XML), .pdf (pypdf, optional),
images (Tesseract OCR, optional; it is on the TCS software list). Nothing here executes uploaded content.
"""
from __future__ import annotations

import html
import importlib.util
import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
MAX_CHARS = 4000  # same limit as a typed requirement
TEXT_EXT = {".txt", ".md", ".markdown", ".py", ".json", ".csv", ".yaml", ".yml", ".rst"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}


class IngestError(ValueError):
    pass


def capabilities() -> dict:
    return {"pdf": importlib.util.find_spec("pypdf") is not None, "ocr": shutil.which("tesseract") is not None}


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError) as e:
        raise IngestError("not a valid .docx file") from e
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _pdf(data: bytes) -> str:
    if importlib.util.find_spec("pypdf") is None:
        raise IngestError("PDF support needs pypdf (pip install -r requirements.txt)")
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:20])
    except Exception as e:  # malformed / encrypted PDFs
        raise IngestError(f"could not read PDF: {e}") from e


def _ocr(data: bytes, suffix: str) -> str:
    exe = shutil.which("tesseract")
    if not exe:
        raise IngestError("image upload needs Tesseract OCR installed (on the TCS software list; macOS: brew install tesseract)")
    with tempfile.TemporaryDirectory(prefix="snipforge_ocr_") as tmp:
        img = Path(tmp, "upload" + suffix)
        img.write_bytes(data)
        try:
            p = subprocess.run([exe, str(img), "stdout"], capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired as e:
            raise IngestError("OCR timed out") from e
    if p.returncode != 0:
        raise IngestError("OCR failed: " + (p.stderr.strip().splitlines() or ["unknown error"])[-1])
    return p.stdout


def extract_text(filename: str, data: bytes) -> dict:
    """Return {"text", "kind", "chars", "truncated"} or raise IngestError."""
    if not data:
        raise IngestError("the file is empty")
    if len(data) > MAX_BYTES:
        raise IngestError(f"file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    ext = Path(filename or "").suffix.lower()
    if ext in TEXT_EXT:
        kind, text = "text", data.decode("utf-8", "replace")
    elif ext == ".docx":
        kind, text = "word", _docx(data)
    elif ext == ".pdf":
        kind, text = "pdf", _pdf(data)
    elif ext in IMAGE_EXT:
        kind, text = "image (OCR)", _ocr(data, ext)
    else:
        raise IngestError(f"unsupported file type {ext or '(none)'}: use .txt, .md, .docx, .pdf or an image")
    text = _clean(text)
    if not text:
        raise IngestError("no text found in the file" + (" (is the image readable?)" if kind.startswith("image") else ""))
    truncated = len(text) > MAX_CHARS
    return {"text": text[:MAX_CHARS], "kind": kind, "chars": len(text), "truncated": truncated}
