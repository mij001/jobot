"""Your resume, as stored by the dashboard (encrypted: data/history/resume.enc.json).

The settings page saves what you paste or upload; jobot reads it back here
(PDF with pdftotext / OCR, DOCX, or plain text) and strips contact details
before any text can reach the AI.
"""

from __future__ import annotations

import base64
import html
import io
import re
import zipfile
from dataclasses import dataclass

from . import ocr
from .vault import Vault

NAME = "resume"  # vault file: resume.enc.json
MAX_CHARS = 12_000  # plenty for a resume; keeps prompts small
_MAX_XML = 8_000_000  # refuse absurd (zip-bomb) documents


@dataclass
class Resume:
    name: str  # file name, or "pasted text"
    kind: str  # "text" | "file"
    updated: str
    text: str  # as extracted, before redaction

    @property
    def chars(self) -> int:
        return len(self.text)


def load(vault: Vault | None) -> Resume | None:
    """The stored resume, or None when there isn't one (or nothing readable in it)."""
    if vault is None:
        return None
    doc = vault.read(NAME)
    if not isinstance(doc, dict):
        return None
    text = extract_text(doc)
    if not text.strip():
        return None
    return Resume(name=str(doc.get("name") or "resume"), kind=str(doc.get("kind") or "text"),
                  updated=str(doc.get("updated") or ""), text=text)


def extract_text(doc: dict) -> str:
    if doc.get("kind") != "file":
        return _tidy(str(doc.get("text") or ""))
    try:
        data = base64.b64decode(doc.get("data") or "")
    except ValueError:
        return ""
    name = str(doc.get("name") or "").lower()
    mime = str(doc.get("mime") or "").lower()
    if data[:4] == b"%PDF" or name.endswith(".pdf") or mime == "application/pdf":
        return _tidy(ocr.pdf_text(data, max_pages=6))
    if data[:2] == b"PK" or name.endswith(".docx"):
        return _tidy(docx_text(data))
    return _tidy(data.decode("utf-8", "replace"))


def docx_text(data: bytes) -> str:
    """Text of a .docx without parsing XML from an untrusted file: paragraphs are the
    <w:p> blocks of word/document.xml, text is whatever sits in <w:t>."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            info = zf.getinfo("word/document.xml")
            if info.file_size > _MAX_XML:
                return ""
            xml = zf.read(info).decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""
    lines = []
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        para = re.sub(r"<w:tab\s*/>", "\t", para)
        parts = re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>|(<w:br\s*/>)", para, re.S)
        line = "".join(html.unescape(t) if t else "\n" for t, br in parts)
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def _tidy(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\r", "\n").split("\n")]
    out, blank = [], 0
    for line in lines:
        blank = 0 if line else blank + 1
        if blank <= 1:
            out.append(line)
    return "\n".join(out).strip()[: MAX_CHARS * 2]


# -- redaction ---------------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b(?:linkedin|github|gitlab|behance|facebook|twitter|x)\.com/\S*", re.I)
_PHONE = re.compile(r"\+?\(?\d[\d\s().\-/]{7,}\d")
_NIC = re.compile(r"\b\d{9}[VvXx]\b|\b\d{12}\b")
_PERSONAL_LINE = re.compile(
    r"^\W*(?:date of birth|d\.?o\.?b\.?|born|nationality|citizenship|civil status|marital status|gender|sex|"
    r"religion|age|nic(?: no\.?| number)?|passport(?: no\.?)?|address|permanent address|home address|"
    r"telephone|tel|mobile|phone|contact)\b\s*[:\-–]", re.I)


def redact(text: str) -> str:
    """Remove what identifies you (name line, e-mail, phone, NIC, links, address and
    personal-detail lines); keeps skills, education, experience and projects."""
    lines = text.split("\n")
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is not None and re.fullmatch(r"[A-Za-z][A-Za-z.\- ']{1,40}", lines[first].strip()) \
            and 1 < len(lines[first].split()) <= 4:
        lines[first] = "[name]"  # the name is almost always the first line
    out = []
    for line in lines:
        if _PERSONAL_LINE.match(line):
            continue
        line = _EMAIL.sub("", line)
        line = _URL.sub("[link]", line)
        line = _NIC.sub("", line)
        line = _PHONE.sub(lambda m: "" if 9 <= sum(c.isdigit() for c in m.group()) <= 15 else m.group(), line)
        out.append(line.strip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()[:MAX_CHARS]
