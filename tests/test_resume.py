import base64
import io
import zipfile

from jobot import resume
from jobot.vault import Vault

SAMPLE = """Nimal Perera
Electrical & Electronic Engineering graduate
Email: nimal.perera@gmail.com | Mobile: +94 77 123 4567 | linkedin.com/in/nimalperera | github.com/nimal-p
Address: 12 Temple Road, Kandy
NIC: 199912345678
Date of Birth: 12 March 1999

EDUCATION
BSc (Hons) in Electrical and Electronic Engineering, University of Peradeniya, 2019 - 2023
Final-year project: LoRa-based soil moisture sensor network (ESP32, MQTT)

SKILLS
Python, MATLAB, PLC (Siemens TIA Portal), AutoCAD, KiCad
"""


def test_redact_removes_what_identifies_you_and_keeps_the_rest():
    out = resume.redact(SAMPLE)
    for gone in ("Nimal", "Perera", "gmail", "77 123", "linkedin", "github", "Temple Road", "199912345678", "12 March"):
        assert gone not in out
    assert out.startswith("[name]")
    # the useful parts survive, including a year range that looks a bit like a phone number
    for kept in ("University of Peradeniya, 2019 - 2023", "LoRa-based soil moisture sensor network", "PLC (Siemens TIA Portal)", "KiCad"):
        assert kept in out


def test_redact_keeps_a_non_name_first_line():
    assert resume.redact("Curriculum Vitae of an engineer with 5 years\nSkills: PLC").startswith("Curriculum Vitae")


def _docx(paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="x"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_docx_text_without_xml_parsing():
    data = _docx(["BSc in EEE &amp; Physics", "Skills: PLC", ""])
    assert resume.docx_text(data) == "BSc in EEE & Physics\nSkills: PLC"
    assert resume.docx_text(b"not a zip") == ""


def test_extract_text_from_each_kind():
    assert resume.extract_text({"kind": "text", "text": "A  B\r\n\r\n\r\n\r\nC"}) == "A B\n\nC"
    txt = {"kind": "file", "name": "cv.txt", "data": base64.b64encode("Skills: PLC".encode()).decode()}
    assert resume.extract_text(txt) == "Skills: PLC"
    docx = {"kind": "file", "name": "cv.docx", "data": base64.b64encode(_docx(["Hello", "World"])).decode()}
    assert resume.extract_text(docx) == "Hello\nWorld"
    assert resume.extract_text({"kind": "file", "name": "cv.pdf", "data": "!!!"}) == ""


def test_load_from_the_vault(tmp_path, monkeypatch):
    from jobot import vault
    monkeypatch.setattr(vault, "ITERATIONS", 1000)
    v = Vault(tmp_path, "pw")
    assert resume.load(v) is None and resume.load(None) is None
    v.write(resume.NAME, {"kind": "text", "name": "pasted text", "text": SAMPLE, "updated": "2026-10-15"})
    got = resume.load(v)
    assert (got.name, got.kind, got.updated) == ("pasted text", "text", "2026-10-15") and got.chars > 200
    v.write(resume.NAME, {"kind": "text", "text": "   "})
    assert resume.load(v) is None
