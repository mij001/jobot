"""Reads text out of poster images and PDF adverts with free command-line tools.

* images: Tesseract OCR (`tesseract`)
* PDFs:   `pdftotext`; scanned PDFs are rendered with `pdftoppm` and OCR'd

The GitHub workflow installs both (tesseract-ocr, poppler-utils). When they
aren't installed these functions just return "" and jobot carries on.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)
TIMEOUT = 60


def available() -> bool:
    return shutil.which("tesseract") is not None


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, check=False)
        return out.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.debug("%s failed: %s", cmd[0], exc)
        return ""


def image_text(data: bytes) -> str:
    if not data or not available():
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "poster"
        path.write_bytes(data)
        return _run(["tesseract", str(path), "stdout", "-l", "eng", "--psm", "3"])


def pdf_text(data: bytes, max_pages: int = 3) -> str:
    if not data or shutil.which("pdftotext") is None:
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "advert.pdf"
        pdf.write_bytes(data)
        text = _run(["pdftotext", "-layout", "-l", str(max_pages), str(pdf), "-"])
        if len(text.strip()) >= 200 or not available() or shutil.which("pdftoppm") is None:
            return text
        # Probably a scanned advert: render the first pages and OCR them.
        _run(["pdftoppm", "-r", "150", "-png", "-l", str(max_pages), str(pdf), str(Path(tmp) / "page")])
        pages = sorted(Path(tmp).glob("page*.png"))
        return "\n".join(_run(["tesseract", str(p), "stdout", "-l", "eng"]) for p in pages) or text
