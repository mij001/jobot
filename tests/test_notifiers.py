from datetime import date

from jobot import notifiers
from jobot.models import Job
from jobot.notifiers import email, telegram
from jobot.report import Report, SourceResult


def report(cfg):
    job = Job(source="topjobs.lk", source_id="1", title="Embedded Engineer", url="https://t/1",
              company="ChipWorks", subfields=["electronics"], level="entry", salary="Rs 150,000")
    return Report([job], [SourceResult("topjobs.lk", 10)], cfg, date(2026, 10, 12))


def test_channels_enabled_by_env():
    assert notifiers.configured_channels({}) == {}
    env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
           "SMTP_USERNAME": "u", "SMTP_PASSWORD": "p", "EMAIL_TO": "me@example.com"}
    assert set(notifiers.configured_channels(env)) == {"telegram", "email"}


def test_telegram_send(cfg, monkeypatch):
    calls = []

    class Resp:
        ok, status_code, text = True, 200, "{}"

    monkeypatch.setattr(telegram.requests, "post", lambda url, json, timeout: calls.append((url, json)) or Resp())
    monkeypatch.setattr(telegram.time, "sleep", lambda s: None)
    telegram.send(report(cfg), {"TELEGRAM_BOT_TOKEN": "TOKEN", "TELEGRAM_CHAT_ID": "11, 22"})
    assert [c[1]["chat_id"] for c in calls] == ["11", "22"]
    assert calls[0][0] == "https://api.telegram.org/botTOKEN/sendMessage"
    assert calls[0][1]["parse_mode"] == "HTML"
    assert "Embedded Engineer" in calls[0][1]["text"] and "Rs 150,000" in calls[0][1]["text"]


def test_email_send(cfg, monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["server"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr(email.smtplib, "SMTP", FakeSMTP)
    email.send(report(cfg), {"SMTP_USERNAME": "bot@gmail.com", "SMTP_PASSWORD": "pw", "EMAIL_TO": "me@example.com"})
    assert sent["server"] == ("smtp.gmail.com", 587) and sent["tls"]
    msg = sent["msg"]
    assert msg["To"] == "me@example.com" and "1 new EEE job" in msg["Subject"]
    html = msg.get_body(("html",)).get_content()
    assert 'href="https://t/1"' in html and "ChipWorks" in html
