# jobot – Sri Lankan EEE job hunter 🔌

Every morning jobot checks Sri Lankan job sites for **Electrical & Electronic
Engineering** vacancies and sends the new ones to your **Telegram** and/or
**e-mail**. It runs for free on GitHub Actions, so you don't need a server.

| Site | How it's read |
|---|---|
| [topjobs.lk](https://www.topjobs.lk) | engineering, telecom, R&D, manufacturing … categories |
| [XpressJobs](https://xpress.jobs) | Electronics/Electrical, Engineering, Telecom … sectors (+ the site's career level) |
| [ikman.lk](https://ikman.lk/en/ads/sri-lanka/jobs) | engineer, technician, internship, IT jobs |
| [Rooster](https://rooster.jobs) | keyword searches limited to Sri Lanka |
| [LinkedIn](https://www.linkedin.com/jobs) | public job search for Sri Lanka, last 7 days |

Each job is tagged with an **EEE sub-field** (Power, Solar, MEP, Automation,
Electronics/Embedded, Telecom, Maintenance, General) and an **experience
level** (Internship, Entry, Mid, Senior, Management), and you choose which
ones you want. The same vacancy posted on several sites is sent once, with
links to every site it's on.

A message looks like this:

```
🔌 3 new EEE jobs in Sri Lanka – 12 Oct 2026

🎓 Entry level / Fresh graduate (2)

Graduate / Electrical Engineer - Power Systems & Grid Studies
🏢 Example Energy (Pvt) Ltd · Colombo
🎯 Power & Energy, General Electrical / Electronic
⏳ Closes 2026-10-26
🔗 topjobs.lk | XpressJobs
...
```

---

## Setup (about 10 minutes)

### 1. Create a Telegram bot

1. In Telegram, open **@BotFather**, send `/newbot` and follow the prompts.
   Copy the **token** it gives you (looks like `123456:ABC-...`).
2. Open your new bot and send it any message (e.g. `hi`).
3. In a browser, open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   and find `"chat":{"id": 123456789 ...` – that number is your **chat id**.

### 2. Add the secrets to GitHub

In this repository: **Settings → Secrets and variables → Actions → New
repository secret**, and add:

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `TELEGRAM_CHAT_ID` | your chat id (several can be given, comma-separated) |

**E-mail (optional, can be used together with Telegram):**

| Secret | Value |
|---|---|
| `SMTP_USERNAME` | your Gmail address |
| `SMTP_PASSWORD` | a Gmail **App password** (Google Account → Security → 2-Step Verification → App passwords), not your normal password |
| `EMAIL_TO` | where to send the digest |
| `SMTP_HOST` / `SMTP_PORT` | only if not Gmail (defaults: `smtp.gmail.com` / `587`) |

### 3. Turn it on

1. Open the **Actions** tab and enable workflows if GitHub asks.
2. Pick **Daily EEE job hunt → Run workflow** to try it right away.

After that it runs **every day at about 8:15 AM Sri Lanka time**. The first
run sends every matching job that's currently open; from then on you get
only new ones. On days with nothing new you get a short "No new EEE jobs
today" message, so you know it ran (turn this off with
`notify.send_when_empty: false`).

> The schedule only runs from the repository's **default branch**, so make
> sure these files are on it.

---

## Customising what you get

Everything is in **[`config.yaml`](config.yaml)**. Edit it on GitHub (pencil
icon) and the next run uses it.

### Sub-fields

```yaml
subfields:
  power:
    enabled: true          # false = ignore this sub-field
    label: Power & Energy
    keywords:
      - power system*      # trailing * = any ending (systems, ...)
      - substation
      - CEB
```

* Turn sub-fields on/off with `enabled`.
* Add or remove keywords. Matching ignores case and works on whole
  words: `PLC` won't match "replica".
* Add a new sub-field by adding a new block with `label` and `keywords`.

A job matches when its **title** contains a keyword. If only its
**description** does, the title must still look technical
(`description_match_titles`: engineer, technician, trainee …) and the
description must mention at least `min_description_hits` (default 2)
different keywords. Titles containing `exclude_title_keywords` are always
dropped, and adding `technician` / `electrician` there gives you
engineer-level roles only.

### Experience levels

```yaml
experience_levels:
  internship: { enabled: true,  keywords: [intern, internship*, trainee, ...] }
  entry:      { enabled: true,  min_years: 0, max_years: 1, keywords: [junior*, graduate, ...] }
  mid:        { enabled: true,  min_years: 2, max_years: 4 }
  senior:     { enabled: false, min_years: 5, max_years: 9, keywords: [senior*, lead, ...] }
  management: { enabled: false, min_years: 10, keywords: [manager, head of, ...] }
include_unknown_level: true   # ads that don't say a level
```

A job's level comes from, in order:
1. **title keywords** (if several match, the most senior wins: "Trainee
   Engineer" → entry, "Senior Manager" → management),
2. **"N years of experience"** in the ad, mapped with `min_years`/`max_years`,
3. the level **the site itself** shows (XpressJobs career level, ikman/Rooster
   internships).

Many ads don't state a level. `include_unknown_level` decides whether you
still get those.

### Other options

* `locations: [Colombo, Gampaha]` sends only jobs in those places.
* `include_overseas: false` skips Gulf, Maldives and other overseas ads,
  which Sri Lankan sites carry a lot of.
* `sources:` turns sites on or off, picks categories/sectors, and sets LinkedIn
  search keywords.

### One-off runs with different filters

**Actions → Daily EEE job hunt → Run workflow** has boxes for this. For
example, `levels = internship` and `resend_all = ✓` sends every open
internship once, without changing `config.yaml`.

---

## Running it on your own computer

```bash
pip install -r requirements.txt
python -m jobot --list                       # show sub-fields, levels, sites
python -m jobot --dry-run                    # print today's new jobs, send nothing
python -m jobot --dry-run --all --levels internship,entry --subfields electronics,automation
```

With `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (or the `SMTP_*` variables) set,
`python -m jobot` sends for real and records what it sent in
`data/seen_jobs.json`.

Tests: `pip install -r requirements-dev.txt && python -m pytest`

---

## Good to know

* **LinkedIn** limits anonymous access and sometimes answers "429 Too Many
  Requests". When that happens the other sites still work, and the message
  footer says LinkedIn failed that day.
* If a site changes its layout, that site shows as *failed* in the footer
  while the rest keep working. A run where *every* site fails is marked
  failed in GitHub Actions, and GitHub e-mails you about it.
* `data/seen_jobs.json` is the bot's memory of what it already sent. The
  workflow commits it after each run. Delete it to start fresh.
* GitHub pauses scheduled workflows in repositories with no activity for 60
  days. If that happens, re-enable it in the Actions tab.
