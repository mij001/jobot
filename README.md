# jobot – Sri Lankan EEE job hunter 🔌

Every morning jobot checks Sri Lankan job sites for **Electrical & Electronic
Engineering** vacancies and sends the new ones to your **Telegram** and/or
**e-mail**. It runs for free on GitHub Actions, so you don't need a server.

| Site | How it's read |
|---|---|
| [topjobs.lk](https://www.topjobs.lk) | engineering, telecom, R&D, manufacturing … categories |
| [XpressJobs](https://xpress.jobs) | Electronics/Electrical, Engineering, Telecom … sectors (+ the site's career level). **Blocks GitHub's servers**, so the daily run skips it – see [below](#xpressjobs) |
| [ikman.lk](https://ikman.lk/en/ads/sri-lanka/jobs) | engineer, technician, internship, IT jobs |
| [Rooster](https://rooster.jobs) | keyword searches limited to Sri Lanka |
| [Observer Jobs](https://www.observerjobs.lk/vacancies) | all vacancies – many government posts. **Blocks GitHub's servers** too, so the daily run skips it (Gazette.lk covers most of the same notices) |
| [LankaJobs](https://lankajobs.lk) | government, private and foreign jobs, newest first |
| [ITPro.lk](https://itpro.lk) | latest jobs + Hardware & Networking and Internship pages (embedded, IoT, network roles) |
| [TechJobs.lk](https://techjobs.lk) | latest engineering/technical vacancies |
| [FindMyJob.lk](https://findmyjob.lk) | its jobs RSS feed |
| [Gazette.lk](https://www.gazette.lk) + any RSS feed | government job notices; add more feeds in the settings |
| Company careers pages | [CEB](https://www.ceb.lk/careers/en), [SLT-Mobitel](https://careers.slt.lk/) – add any employer's page |
| [LinkedIn](https://www.linkedin.com/jobs) | public job search for Sri Lanka, last 7 days (partly rate-limited) |

jobot **opens each new advert and reads it** – including the many Sri
Lankan adverts that are only a **poster image** (read with free OCR) or a
**PDF** – so a job whose list entry says nothing but "Project Engineer" is
still checked against what the advert actually asks for.

Each job is tagged with an **EEE sub-field**, an **experience level**
(Internship, Entry, Mid, Senior, Management) and the **qualification** the
advert asks for (**Degree**, **Diploma** – HND/NDT/NVQ 5–6, **Vocational** –
NVQ 3–4, or **School** – O/L, A/L), and you choose which ones you want. By
default only degree-level jobs are sent; "Degree or HND" adverts count as
degree level too. Sub-fields included out of the box: Power & Energy · Renewable/Solar ·
Building Services/MEP · Automation & Control · Electronics/Embedded ·
Telecom · Maintenance · General Electrical · Marine/ETO · Aviation/Avionics ·
Biomedical · Electric Vehicles & Batteries · Data Centre & Critical Power ·
Lifts & Escalators · Fire, Security & Low-current · Testing & Commissioning ·
Railway & Signalling · Broadcast/AV · Networking & IT Hardware · Technical
Sales · Teaching & Research. The same vacancy posted on several sites is sent once, with
links to every site it's on.

Optional extras:

* a **free AI reviewer** that scores every new job against a short profile
  of you, explains the score in one line, and hides poor fits;
* a **settings web page** (Material You design, with your own colour)
  where you flip switches instead of editing YAML, with a **statistics
  dashboard** and **suggestions** you can apply in one tap.

Every run also saves **statistics** and every new job to a
**password-protected dashboard** on the settings page: browse past jobs
sorted by importance (Top picks → Good fits → Worth a look → Low priority),
and keep your own **shortlist** (shortlisted / applied / dismissed). Once a
week the message adds a **"Your week"** summary and up to three
**suggestions**, and jobs the AI scores 8/10 or higher appear as **⭐ Top
picks** at the top.

A message looks like this:

```
🔌 3 new EEE jobs in Sri Lanka – 12 Oct 2026

📂 Entry level / Fresh graduate (2)

Graduate / Electrical Engineer - Power Systems & Grid Studies
🏢 Example Energy (Pvt) Ltd · Colombo
🎯 Power & Energy, General Electrical / Electronic
🎓 Degree · 1+ yrs experience · read from poster
📋 BSc in Electrical Engineering · Minimum 1 year experience in power system studies
⏳ Closes 2026-10-26
📧 careers@example.lk
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

### 3. (Optional) Free AI reviewer

1. Open <https://aistudio.google.com/apikey>, sign in with your Google
   account and click **Create API key** (free, no card needed).
2. Add it as a repository secret named `AI_API_KEY`.
3. Edit the `ai.profile` text (in `config.yaml` or the settings page) so it
   describes you.

Each job then shows a line like `⭐ 8/10 – Fresh-graduate power systems
role`, the best matches come first, and jobs scoring under `ai.min_score`
are hidden (the footer says how many). Jobs the keywords couldn't place get
an experience level from the AI too.

Prefer Groq? Get a free key at <https://console.groq.com/keys>, store it as
`AI_API_KEY` and set `ai.provider: groq`. Any other OpenAI-compatible
service works with an `AI_BASE_URL` secret plus `ai.models`.

If the key is missing, the free quota runs out or the AI answers nonsense,
the run carries on with the plain keyword results – nothing is lost.

### 4. (Optional) Settings web page

1. **Settings → Pages**: under *Build and deployment* pick **Deploy from a
   branch**, choose this repository's default branch and the **/docs**
   folder, and save. After a minute the page is at
   `https://<your-user>.github.io/jobot/`.
2. Open it. Anyone can *view* the settings; to **save** or **run now**,
   create a token with the page's *Create a token* link:
   *Only select repositories* → this repo, **Contents: Read and write**,
   **Actions: Read and write**. Paste it in and tick *Remember on this
   device* if it's your own phone or computer.

On the page you can switch sub-fields and experience levels on and off,
edit their keywords (as chips), add your own sub-fields, set filters, turn
sites on and off, add RSS feeds and company careers pages, choose how
messages are grouped and ordered, set up the AI reviewer, and start a run
(or a test run that sends nothing). Saving commits `config.yaml`, keeping
its comments. The palette button picks the page's colour, Material You
style – light, dark or automatic.

### 5. (Optional) Password-protected history

Add one more secret, **`DASHBOARD_PASSWORD`** – a long passphrase of your
own. From then on every run saves each job it found (and the run's
statistics) to `data/history/`, **encrypted** with that password, and the
settings page shows them under **Your jobs** once you type it. See
[Your jobs dashboard](#your-jobs-dashboard) for what that gives you and what
it can't protect.

Without the secret nothing is saved to the repository, because it is public.

### 6. Turn it on

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
* `requires_any` makes a sub-field conditional: *Teaching* only counts a
  "Lecturer" ad when it also mentions electrical, electronics, power …

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

### Qualification (degree / diploma)

```yaml
qualifications:
  degree:     { enabled: true,  keywords: [degree, bsc*, b.sc*, beng, bachelor*, graduate*, nvq level 7, ...] }
  diploma:    { enabled: false, keywords: [diploma*, hnd*, ndt, hnde, nvq level 5, nvq level 6, ...],
                title_hints: [technical officer*, engineering assistant*, ...] }
  vocational: { enabled: false, keywords: [nvq level 3, nvq level 4, trade test*, ...],
                title_hints: [technician*, electrician*, ...] }
  school:     { enabled: false, keywords: [o/l, a/l, g.c.e*, ...] }
include_unknown_qualification: true   # adverts that don't say, or couldn't be read
```

jobot notes **every** qualification an advert accepts, and sends it if any
of them is switched on – so "BSc **or** HND in Electrical Engineering" reaches
a degree holder, while "NDT/HND only" adverts don't. NVQ levels are recognised
however they're written ("NVQ L5", "NVQ Level 05", "NVQ 5/6"). `title_hints`
are used only when the advert itself doesn't say (an unreadable "Technical
Officer" poster is almost always diploma level). Jobs hidden by this filter
aren't marked as sent, so switching on *Diploma* later shows the ones still
open.

### Reading the adverts

```yaml
postings:
  enabled: true
  max_per_run: 60      # new advert pages opened per run (1–3 s each)
  read_posters: true   # OCR poster images (Tesseract)
  ai_vision: true      # let the AI read posters OCR can't (Gemini only)
  max_ai_reads: 5
  skip_titles: [civil, mechanical, software, ...]   # "maybe" ads not worth opening
```

jobot opens the page of every **new** job that matched, plus "maybe" jobs –
a technical title (one of `description_match_titles`) with little or no text
on the list page. From each advert it takes the text (topjobs, ikman,
LankaJobs, ITPro, TechJobs, Gazette.lk and LinkedIn have their own readers;
other sites use the page's main content), runs **Tesseract OCR** on poster
images when there's no text, and reads the English **PDF** of Gazette.lk
notices. It then pulls out:

* the **qualification** and **years of experience** asked for (shown as 🎓),
* the lines of the advert that say so (📋), the **e-mail** to apply to (📧),
  and the **closing date** when the site didn't give one.

The full text then goes through the sub-field, experience and qualification
filters, and to the AI reviewer (which also sums up the requirements). Each
advert is read once and remembered in `data/postings_cache.json`; if there
are more than `max_per_run` (e.g. on the very first run), the rest are read
on the next runs. The GitHub workflow installs Tesseract and poppler-utils
itself; on your own computer install them with
`sudo apt install tesseract-ocr poppler-utils` (Linux) or
`brew install tesseract poppler` (macOS) – without them jobot still reads
text adverts and skips posters.

### Message layout

```yaml
notify:
  group_by: level        # level | qualification | subfield | site | none
  order_by: best_match   # best_match | newest | closing_soon | company | title
```

`best_match` puts the highest AI score first (then newest). Try a one-off
layout with `python -m jobot --dry-run --group-by site --order-by closing_soon`.

### Your jobs dashboard

Open the settings page and type your `DASHBOARD_PASSWORD` under **Your jobs**
(tick *Stay unlocked on this device* on your own phone or computer):

* **Importance** – each job is filed as **Top picks** (AI score ≥
  `notify.top_picks_score`, 8 by default), **Good fits** (6–7), **Worth a
  look** (4–5) or **Low priority** (held back by the AI). Without the AI,
  jobs are filed by how clearly the advert matches: an EEE title plus a
  stated qualification and level is a good fit.
* **Your shortlist** – tap *Shortlist*, *Applied* or *Dismiss* on a job. The
  tabs (*To review · Shortlist · Applied · Dismissed · All*) show what you've
  marked, still grouped by importance. Marks are saved encrypted too, from
  the page, so they follow you between phone and computer. Saving needs the
  GitHub token from step 4, like saving settings does.
* Search by title, company, place or field; filter by how long ago the job
  was seen; hide jobs whose closing date has passed. Each job shows what the
  advert asks for, the AI's one-line reason, the closing date and the e-mail
  to apply to.

How it is protected: the browser derives a key from your password
(PBKDF2-SHA256, 600 000 rounds) and decrypts with AES-256-GCM; the password is
never sent anywhere. The files in `data/history/` are unreadable without it,
so a **long passphrase** matters – anyone can download them and try guesses.
What stays public: this repository, `config.yaml` (including your AI profile)
and the settings page itself, which is just a viewer. Older commits can still
hold the plain-text `data/stats.json` / `data/jobs_log.csv` from before
encryption existed; the first run with the secret moves them into the
encrypted history and deletes the files, but git remembers them. If that
matters, make the repository private (GitHub Pages then needs a paid plan).

Changing the password: set the new secret, then delete the `data/history/`
folder – the old history can't be read with a different password. Lost
password: same thing.

### Statistics & suggestions

Each run adds a record to the encrypted history: jobs scanned per site (or
why a site failed / was skipped), open matches, new jobs, jobs sent, jobs
the AI hid, new jobs by sub-field / level / qualification / site, **open
jobs per sub-field including switched-off ones**, how many matches your
level and qualification filters drop, how many adverts were read (and how
many were posters), and the companies hiring most. Every new job is kept
with its site, title, company, sub-fields, level, qualification, AI score
and reason, what the advert asks for, closing date, apply e-mail and link.

From that history jobot suggests, for example:

* switching on a sub-field, level or qualification that has many open jobs right now,
* switching off a sub-field that hasn't matched anything in 30 days,
* a site that keeps failing,
* lowering the AI cut-off when it hides most jobs,
* which fields and companies are busiest.

The settings page shows all of this as charts (per day, by sub-field, site,
level, top employers), the latest jobs, and the suggestions with an
**Apply** button. In messages, `notify.weekly_summary` (default `monday`;
or `daily` / `off`) adds the "Your week" block and suggestions, and
`notify.top_picks_score` (default 8, `0` = off) sets the AI score for
⭐ Top picks.

### More sites

* **RSS feeds**: add any job feed under `sources.rss.feeds` (WordPress job
  blogs have one at `/feed`).
* **Company careers pages**: add an employer's careers page under
  `sources.company_pages.pages`. Every link that looks like a vacancy is
  picked up; set `subfield` to tag them (e.g. `power` for CEB).

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
python -m jobot --dry-run --no-ai             # skip the AI reviewer
python -m jobot --dry-run --qualifications degree,diploma
python -m jobot --dry-run --no-read           # don't open the adverts (faster)
```

With `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (or the `SMTP_*` variables) set,
`python -m jobot` sends for real and records what it sent in
`data/seen_jobs.json`.

Tests: `pip install -r requirements-dev.txt && python -m pytest`

---

## Good to know

* <a id="xpressjobs"></a>**XpressJobs and Observer Jobs refuse connections
  from cloud servers**, including GitHub Actions, so the daily run skips
  them and the footer says so. It still works when you run jobot on your own computer.
  To cover it anyway, turn on XpressJobs' own free **job alerts** for the
  *Electronics / Electrical* sector in your XpressJobs account.

* **LinkedIn** limits anonymous access. jobot searches slowly (6 s between
  requests) and, when told "429 Too Many Requests", waits a minute and
  tries once more. If it's still refused, the other sites still work and
  the footer says how far LinkedIn got.
* If a site changes its layout, that site shows as *failed* in the footer
  while the rest keep working. A run where *every* site fails is marked
  failed in GitHub Actions, and GitHub e-mails you about it.
* `data/seen_jobs.json` is the bot's memory of what it already sent, and
  `data/postings_cache.json` of the adverts it already read. The workflow
  commits both after each run. Delete them to start fresh.
* OCR isn't perfect: stylised posters can come out garbled. Those adverts
  are kept as "qualification not stated" (unless you switch that off), and
  with the AI reviewer on, up to `postings.max_ai_reads` posters a day are
  read by the AI instead.
* GitHub pauses scheduled workflows in repositories with no activity for 60
  days. If that happens, re-enable it in the Actions tab.
