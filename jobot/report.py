"""Turns the day's new jobs into Telegram messages and an e-mail digest."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from html import escape

from .config import Config
from .models import Job
from .ordering import group_jobs

TELEGRAM_LIMIT = 4000  # Telegram's hard limit is 4096 characters


@dataclass
class SourceResult:
    name: str
    fetched: int = 0
    error: str | None = None
    skipped: str | None = None  # reason the site was deliberately not checked


@dataclass
class Report:
    jobs: list[Job]
    sources: list[SourceResult]
    cfg: Config
    day: date
    ai_note: str | None = None
    stats_line: str | None = None
    weekly: list[str] = field(default_factory=list)  # "your week" summary lines
    tips: list[str] = field(default_factory=list)  # suggestions to show

    # -- shared helpers ---------------------------------------------------

    def groups(self) -> list[tuple[str | None, list[Job]]]:
        """Jobs grouped and sorted as set in notify.group_by / notify.order_by."""
        return group_jobs(self.jobs, self.cfg, self.day)

    def top_picks(self) -> list[Job]:
        score = self.cfg.top_picks_score
        if not score:
            return []
        picks = [j for j in self.jobs if j.ai_score is not None and j.ai_score >= score]
        return sorted(picks, key=lambda j: -j.ai_score)[:5]

    def subfield_labels(self, job: Job) -> str:
        labels = [sf.label for key in job.subfields if (sf := self.cfg.subfield(key))]
        return ", ".join(labels)

    @property
    def title(self) -> str:
        n = len(self.jobs)
        when = self.day.strftime("%d %b %Y")
        if not n:
            return f"No new EEE jobs today ({when})"
        return f"{n} new EEE job{'s' if n != 1 else ''} in Sri Lanka – {when}"

    def source_summary(self) -> list[str]:
        lines = [x for x in (self.stats_line, self.ai_note) if x]
        for s in self.sources:
            if s.skipped:
                lines.append(f"{s.name}: skipped ({s.skipped})")
            elif s.error:
                lines.append(f"{s.name}: failed ({s.error})")
            else:
                lines.append(f"{s.name}: {s.fetched} scanned")
        return lines

    # -- Telegram -----------------------------------------------------------

    def _telegram_job(self, job: Job) -> str:
        lines = [f"<b>{escape(job.title)}</b>"]
        org = " · ".join(escape(x) for x in (job.company, job.location) if x)
        if org:
            lines.append(f"🏢 {org}")
        lines.append(f"🎯 {escape(self.subfield_labels(job))}")
        if job.ai_score is not None:
            lines.append(f"⭐ {job.ai_score}/10 – {escape(job.ai_reason)}")
        if job.salary:
            lines.append(f"💰 {escape(job.salary)}")
        if job.closing:
            lines.append(f"⏳ Closes {escape(job.closing)}")
        links = [f'<a href="{escape(job.url, quote=True)}">{escape(job.source)}</a>']
        links += [f'<a href="{escape(u, quote=True)}">{escape(s)}</a>' for s, u in job.also_on]
        lines.append("🔗 " + " | ".join(links))
        return "\n".join(lines)

    def telegram_messages(self) -> list[str]:
        header = f"🔌 <b>{escape(self.title)}</b>"
        footer = "<i>" + escape(" · ".join(self.source_summary())) + "</i>"
        blocks: list[str] = []
        if picks := self.top_picks():
            blocks.append("⭐ <b>Top picks for you</b>\n" + "\n".join(
                f'• <a href="{escape(j.url, quote=True)}">{escape(j.title)}</a>'
                f'{" – " + escape(j.company) if j.company else ""} ({j.ai_score}/10)' for j in picks))
        for label, jobs in self.groups():
            if label:
                blocks.append(f"📂 <b>{escape(label)}</b> ({len(jobs)})")
            blocks.extend(self._telegram_job(j) for j in jobs)
        if self.weekly:
            blocks.append("📈 <b>Your week</b>\n" + "\n".join(escape(x) for x in self.weekly))
        if self.tips:
            blocks.append("💡 <b>Suggestions</b>\n" + "\n".join("• " + escape(t) for t in self.tips))
        blocks.append(footer)

        messages, current = [], header
        for block in blocks:
            if len(current) + len(block) + 2 > TELEGRAM_LIMIT:
                messages.append(current)
                current = block
            else:
                current += "\n\n" + block
        messages.append(current)
        return messages

    # -- E-mail -------------------------------------------------------------

    def email_text(self) -> str:
        out = [self.title, ""]
        if picks := self.top_picks():
            out.append("== Top picks for you ==")
            out.extend(f"* {j.title}{' – ' + j.company if j.company else ''} ({j.ai_score}/10): {j.url}" for j in picks)
            out.append("")
        for label, jobs in self.groups():
            if label:
                out.append(f"== {label} ({len(jobs)}) ==")
            for j in jobs:
                out.append(f"* {j.title}")
                org = " · ".join(x for x in (j.company, j.location) if x)
                if org:
                    out.append(f"  {org}")
                out.append(f"  Field: {self.subfield_labels(j)}")
                if j.ai_score is not None:
                    out.append(f"  Fit: {j.ai_score}/10 – {j.ai_reason}")
                if j.salary:
                    out.append(f"  Salary: {j.salary}")
                if j.closing:
                    out.append(f"  Closes: {j.closing}")
                out.append(f"  {j.source}: {j.url}")
                out.extend(f"  {s}: {u}" for s, u in j.also_on)
                out.append("")
        if self.weekly:
            out.extend(["== Your week ==", *self.weekly, ""])
        if self.tips:
            out.extend(["== Suggestions ==", *(f"* {t}" for t in self.tips), ""])
        out.append("Sources: " + " · ".join(self.source_summary()))
        return "\n".join(out)

    def email_html(self) -> str:
        parts = [
            '<div style="font-family:Arial,Helvetica,sans-serif;max-width:680px">',
            f'<h2 style="color:#1a3d6d">🔌 {escape(self.title)}</h2>',
        ]
        if picks := self.top_picks():
            items = "".join(
                f'<li><a href="{escape(j.url, quote=True)}">{escape(j.title)}</a>'
                f'{" – " + escape(j.company) if j.company else ""} <b>({j.ai_score}/10)</b></li>' for j in picks)
            parts.append('<div style="background:#fff6d6;border-radius:12px;padding:10px 14px;margin:0 0 16px">'
                         f'<b>⭐ Top picks for you</b><ul style="margin:6px 0 0;padding-left:20px">{items}</ul></div>')
        for label, jobs in self.groups():
            if label:
                parts.append(f'<h3 style="border-bottom:1px solid #ccc;padding-bottom:4px">'
                             f'{escape(label)} ({len(jobs)})</h3>')
            for j in jobs:
                links = [f'<a href="{escape(j.url, quote=True)}">{escape(j.source)}</a>']
                links += [f'<a href="{escape(u, quote=True)}">{escape(s)}</a>' for s, u in j.also_on]
                org = " · ".join(escape(x) for x in (j.company, j.location) if x)
                closing = f" · closes {escape(j.closing)}" if j.closing else ""
                salary = f" · {escape(j.salary)}" if j.salary else ""
                fit = (f'<br><span style="color:#1a6d3d;font-size:13px">⭐ {j.ai_score}/10 – '
                       f'{escape(j.ai_reason)}</span>') if j.ai_score is not None else ""
                parts.append(
                    '<div style="margin:0 0 14px">'
                    f'<a href="{escape(j.url, quote=True)}" style="font-weight:bold;font-size:15px">'
                    f'{escape(j.title)}</a><br>'
                    f'<span style="color:#444">{org}</span><br>'
                    f'<span style="color:#666;font-size:13px">{escape(self.subfield_labels(j))}{salary}{closing}'
                    f' · {" | ".join(links)}</span>{fit}'
                    '</div>'
                )
        if self.weekly:
            parts.append('<h3 style="border-bottom:1px solid #ccc;padding-bottom:4px">📈 Your week</h3>'
                         + "".join(f'<p style="margin:4px 0">{escape(x)}</p>' for x in self.weekly))
        if self.tips:
            parts.append('<h3 style="border-bottom:1px solid #ccc;padding-bottom:4px">💡 Suggestions</h3><ul>'
                         + "".join(f"<li>{escape(t)}</li>" for t in self.tips) + "</ul>")
        summary = escape(" · ".join(self.source_summary()))
        parts.append(f'<p style="color:#888;font-size:12px">Sources: {summary}</p></div>')
        return "\n".join(parts)

