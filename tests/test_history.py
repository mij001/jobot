"""The encrypted vault and history files the settings page reads."""

import gzip
import json
from datetime import date

import pytest

from jobot import history, vault
from jobot.models import Job

PASSWORD = "correct horse battery staple ✓"
TODAY = date(2026, 10, 15)


def job(title, **kw):
    return Job(source="topjobs.lk", source_id=title, title=title, url="https://t/" + title.replace(" ", "-"), **kw)


@pytest.fixture
def fast_vault(monkeypatch):
    monkeypatch.setattr(vault, "ITERATIONS", 1000)  # the real 600 000 rounds take a moment


def test_roundtrip_and_wrong_password(tmp_path, fast_vault):
    v = vault.Vault(tmp_path, PASSWORD)
    v.write("sample", {"title": "Électrical Engineer", "n": [1, 2, 3]})
    v.save_meta(["sample"])
    assert vault.Vault(tmp_path, PASSWORD).read("sample") == {"title": "Électrical Engineer", "n": [1, 2, 3]}
    with pytest.raises(vault.WrongPassword):
        vault.Vault(tmp_path, "wrong")
    with pytest.raises(vault.WrongPassword):
        vault.Vault(tmp_path, "")
    assert "Engineer" not in (tmp_path / "sample.enc.json").read_text()  # nothing readable in the file


def test_file_format_is_what_the_browser_expects(tmp_path, fast_vault):
    """AES-256-GCM over gzip(JSON), key = PBKDF2-SHA256: the page decrypts this with Web Crypto."""
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    v = vault.Vault(tmp_path, PASSWORD)
    v.write("a", {"x": 1})
    v.save_meta(["a"])
    meta = json.loads((tmp_path / "vault.json").read_text())
    key = vault.derive_key(PASSWORD, base64.b64decode(meta["salt"]), meta["iter"])
    blob = json.loads((tmp_path / "a.enc.json").read_text())
    raw = AESGCM(key).decrypt(base64.b64decode(blob["iv"]), base64.b64decode(blob["ct"]), None)
    assert json.loads(gzip.decompress(raw)) == {"x": 1} and blob["v"] == 1
    assert vault.unseal(key, meta["check"]) == vault.CHECK_TEXT
    # Every write uses a fresh IV, so equal data never encrypts to equal bytes.
    v.write("b", {"x": 1})
    assert (tmp_path / "a.enc.json").read_text() != (tmp_path / "b.enc.json").read_text()


def test_vault_json_is_only_rewritten_when_it_changes(tmp_path, fast_vault):
    v = vault.Vault(tmp_path, PASSWORD)
    v.save_meta(["a"])
    first = (tmp_path / "vault.json").stat().st_mtime_ns
    vault.Vault(tmp_path, PASSWORD).save_meta(["a"])
    assert (tmp_path / "vault.json").stat().st_mtime_ns == first


def test_importance_tiers(cfg):
    def tier(score=None, hidden=False, title="Electrical Engineer", subfields=("general",), level=None, quals=()):
        return history.tier(score, hidden, title, list(subfields), level, list(quals), cfg)

    assert tier(9) == "top" and tier(8) == "top" and tier(7) == "good" and tier(6) == "good"
    assert tier(5) == "maybe" and tier(4) == "maybe"
    assert tier(10, hidden=True) == "low"
    # Without the AI: title match + stated qualification/level -> good; otherwise worth a look.
    assert tier(title="Electrical Engineer", subfields=["general"], quals=["degree"]) == "good"
    assert tier(title="Project Engineer", subfields=["general"], level="entry", quals=["degree"]) == "good"
    assert tier(title="Project Engineer", subfields=["general"]) == "maybe"
    cfg.top_picks_score = 0
    assert tier(8) == "top"  # "off" in messages still leaves a sensible top tier here


def test_history_shards_by_month_and_keeps_entries(tmp_path, cfg, fast_vault):
    h = history.History.open(tmp_path, {"DASHBOARD_PASSWORD": PASSWORD})
    assert h.enabled and not h.has_stats
    a = job("Electrical Engineer", subfields=["general"], level="entry", qualifications=["degree"],
            ai_score=9, ai_reason="fits", requirements="BSc in EEE", contact="hr@acme.lk", also_on=[("ikman.lk", "https://i/1")])
    b = job("Sales Engineer", subfields=["technical_sales"], ai_score=2)
    h.add_jobs(date(2026, 9, 30), [b], {b.uid}, cfg)
    h.add_jobs(TODAY, [a], set(), cfg)
    h.add_run({"date": TODAY.isoformat(), "new": 1})
    h.suggestions = [{"id": "x"}]
    h.save()

    again = history.History.open(tmp_path, {"DASHBOARD_PASSWORD": PASSWORD})
    assert again.has_stats and again.runs == [{"date": "2026-10-15", "new": 1}] and again.suggestions == [{"id": "x"}]
    assert set(again.vault.meta["shards"]) == {"stats", "jobs-2026-09", "jobs-2026-10"}
    [entry] = again.vault.read("jobs-2026-10")
    assert entry["importance"] == "top" and entry["also_on"] == [["ikman.lk", "https://i/1"]]
    assert entry["requirements"] == "BSc in EEE" and "salary" not in entry  # empty values aren't stored
    [old] = again.vault.read("jobs-2026-09")
    assert old["status"] == "hidden" and old["importance"] == "low"

    # A second job in October adds to that month's file; the September file is untouched.
    sept = (tmp_path / "history" / "jobs-2026-09.enc.json").read_text()
    again.add_jobs(TODAY, [job("Network Engineer", subfields=["networking"])], set(), cfg)
    again.save()
    assert len(again.vault.read("jobs-2026-10")) == 2
    assert (tmp_path / "history" / "jobs-2026-09.enc.json").read_text() == sept


def test_old_months_fall_away(tmp_path, cfg, fast_vault, monkeypatch):
    monkeypatch.setattr(history, "MAX_MONTHS", 2)
    h = history.History.open(tmp_path, {"DASHBOARD_PASSWORD": PASSWORD})
    for month in (7, 8, 9):
        h.add_jobs(date(2026, month, 1), [job(f"Engineer {month}")], set(), cfg)
    h.save()
    names = sorted(p.name for p in (tmp_path / "history").glob("jobs-*"))
    assert names == ["jobs-2026-08.enc.json", "jobs-2026-09.enc.json"]
    assert "jobs-2026-07" not in h.vault.meta["shards"]


def test_without_a_password_nothing_is_kept(tmp_path, cfg):
    h = history.History.open(tmp_path, {})
    assert not h.enabled and "DASHBOARD_PASSWORD" in h.note
    h.add_jobs(TODAY, [job("Electrical Engineer")], set(), cfg)
    h.add_run({"date": "2026-10-15"})
    h.save()
    assert not (tmp_path / "history").exists()
