# jobot – Sri Lankan EEE job hunter 🔌

jobot checks Sri Lankan job sites – **every 30 minutes** – for **Electrical &
Electronic Engineering** vacancies, plus **fully remote jobs you can do from
Sri Lanka**, and sends the new ones to your **Telegram** and/or **e-mail**
the moment they appear. It runs for free on GitHub Actions, so you don't need
a server.

| Site | How it's read |
|---|---|
| [topjobs.lk](https://www.topjobs.lk) | 16 functional areas: engineering, telecom, R&D, manufacturing – and the ones EEE work hides in (building services, marine/airline, education, technical sales, medical) |
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
| [LinkedIn](https://www.linkedin.com/jobs) | public job search for Sri Lanka, last 7 days (partly rate-limited), plus its "remote" filter |
| University vacancy pages | Moratuwa, Colombo, Jaffna & Peradeniya engineering faculties, Sri Jayewardenepura, Open University and more – lecturer, instructor, technical-officer posts |
| Remote job boards | [Remote OK](https://remoteok.com), [We Work Remotely](https://weworkremotely.com), [Jobicy](https://jobicy.com), [Himalayas](https://himalayas.app), [Working Nomads](https://www.workingnomads.com), [Remotive](https://remotive.com) – only jobs open to Sri Lanka, see [below](#fully-remote-jobs) |

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
* **AI helpers** for the judgment calls keywords can't make: is this remote
  job really open to someone in Sri Lanka, is "Technical Officer" EEE work,
  what is in this alert e-mail ([details](#ai-helpers));
* a **settings web page** (Material You design, or an **Apple-style**
  look, with your own colour; installable on your phone's home screen)
  where you flip switches instead of editing YAML, with a **dashboard** and
  **suggestions** you can apply in one tap;
* an **AI career coach** that reads your resume, shows which skills
  employers ask for that you lack, suggests portfolio projects and tells you
  how well each job fits your resume.

Every run also saves **statistics** and every new job to a
**password-protected dashboard** on the settings page, with four views:
**Focus** (what needs you today), **Jobs** (everything, by importance, with
your own shortlist), **Data** (charts and tables) and **Coach** (resume
analysis, skills to build, portfolio projects). Once a week the message adds
a **"Your week"** summary and up to three **suggestions**, and jobs the AI
scores 8/10 or higher appear as **⭐ Top picks** at the top.

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

Two kinds of work use two kinds of model: the **daily scoring** uses a fast
model (`ai.models`), while the heavier **career coach** work (resume analysis,
project ideas, preparing for a job) uses `ai.smart_models` – left blank it
tries Gemini's best free model (`gemini-pro-latest`) first and falls back to
the best Flash model if Pro isn't free on your key. The report names the
model that answered. A busy model (503) is retried once after 20 seconds.

The same key also powers the [AI helpers](#ai-helpers) (remote-job eligibility,
triage of generic job titles, unknown alert e-mails), which share a small daily
budget of requests.

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
its comments.

Change a setting and a small **Save** pill appears at the bottom (with
*Discard*); it is hidden the rest of the time. The ▶ button in the top bar
opens the **Run** menu: *Run now*, *Test run* (sends nothing) and *Refresh
career report*. The palette button picks light / dark / automatic, the
colour, and the **style** – *Material You* or *Apple* (system fonts, frosted
bars, rounded grouped cards, iOS-style switches).

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

After that it runs **every 30 minutes** (see [How often, and how hard](#how-often-and-how-hard)).
The first run sends every matching job that's currently open; from then on you
get only new ones, as soon as they are found. The first run after 8 AM Sri
Lanka time each day is the **daily run**: it also sends the summary (and, on
days with nothing new, a short "No new EEE jobs today" message, so you know it
ran – turn this off with `notify.send_when_empty: false`). The runs in between
only message you when they find something.

> The schedule only runs from the repository's **default branch**, so make
> sure these files are on it. GitHub starts scheduled runs when it has room,
> which can be tens of minutes late – every run reads **all** open listings, so
> a late or skipped run loses nothing.
>
> **Free minutes:** runs are free on a *public* repository (this one). On a
> private repository GitHub gives 2 000 free minutes a month, which a 30-minute
> schedule would use up – change the `cron:` line in
> `.github/workflows/daily.yml` to something like `"13 */3 * * *"` there.

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
are used only when the advert itself doesn't say, and then only as a **guess**:
the job is shown as "Diploma (guessed from the title)" and counts as *not
stated*, so it is not dropped. (A LinkedIn card has nothing but a title, and
"Technical Officer telecom projects" is not necessarily a diploma job.) Only
what the advert really says – "HND only" – hides a job. With
`include_unknown_qualification: false` a guess does count. Jobs hidden by this
filter aren't marked as sent, so switching on *Diploma* later shows the ones
still open.

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

Open the settings page and type your `DASHBOARD_PASSWORD` under **Dashboard**
(tick *Stay unlocked on this device* on your own phone or computer). Press
**Lock** to wipe everything from the page again.

**Focus** – the page to open each morning: how many jobs are waiting for a
decision, jobs **closing soon**, **Top picks**, your **shortlist**, what you
**applied** to, the **skills to build** and **suggestions**. *Review one by
one* walks through the list with the keyboard: **S** shortlist, **D**
dismiss, **N** next, **←/→** move, **Esc** leave.

**Jobs** – every job ever sent, filed by importance: **Top picks** (AI score ≥
`notify.top_picks_score`, 8 by default), **Good fits** (6–7), **Worth a look**
(4–5) or **Low priority** (held back by the AI). Without the AI, jobs are
filed by how clearly the advert matches. A job from a company on your
`watch_companies` list moves up one tier. Tap *Shortlist*, *Applied* or
*Dismiss*, and add a private **note**; the tabs (*To review · Shortlist ·
Applied · Dismissed · All*) show what you've marked. Search by title, company,
place, field or skill; filter by period or by a skill; sort by importance,
newest, closing date or **resume match**. Marks and notes are saved encrypted
too, from the page (batched into one commit a couple of seconds after your
last tap), so they follow you between phone and computer. Saving needs the
GitHub token from step 4. **Prepare** on a job asks the AI for a tailored cover
letter, resume bullets, likely interview questions and a study plan (the
result shows up under the job and under *Coach*).

**Data** – the numbers, with a period switch (7 / 30 / 90 days / all): six KPI
tiles with the change against the previous period, jobs per day stacked by
importance, your pipeline (found → sent → reviewed → shortlisted → applied),
the AI score distribution, jobs by weekday, by site, sub-field, level,
qualification, employer and place, **skills employers ask for**, jobs by
closing date, open jobs per sub-field (including switched-off ones), what
your filters hide, **site health** over the last runs, and how the adverts
were read. Every chart has a *Table* toggle with the same numbers. At the
bottom is a sortable table of all jobs with **Download CSV** (for a
spreadsheet) and **Download everything (JSON)**.

**Coach** – see [Career coach](#career-coach).

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

**On your phone:** open the page in Safari / Chrome and choose *Add to Home
Screen* – it opens full-screen with its own icon.

### Career coach

Dashboard → **Coach**. Paste your resume (or upload a PDF, DOCX or text file,
up to 1 MB) and press **Save encrypted**; it is stored in
`data/history/resume.enc.json`, readable only with your password. Then:

* **Analyse** (needs the token from step 4 and the AI key): asks the daily
  workflow to build a **career report** in about two minutes; press *Refresh*
  afterwards. The same report is rebuilt automatically every week
  (`coach.weekly_report`, Sunday by default).
* The report shows **how your resume reads** (level, strengths, gaps, what to
  change, a suggested headline), the **skills employers ask for** in the last
  90 days with the ones your resume shows and the ones it doesn't,
  **portfolio projects** to build (why, steps, what to publish, how to show
  it on your resume), and your **best-fit jobs** with what's missing and how to
  tailor the application. The AI's one-line summary of you is also used when it
  scores each day's jobs.
* Every job card shows a **resume match %** (the skills it asks for that your
  resume mentions). That is computed locally, with no AI.

```yaml
coach:
  enabled: true
  weekly_report: sunday   # monday … sunday | daily | off
  window_days: 90         # how many days of adverts the skill demand covers
  projects: 4             # how many project ideas
  extra_skills: []        # skills of your own to look for
  send_resume: true       # false = the resume never goes to the AI
```

**Privacy:** the text sent to the AI has your name, e-mail, phone, NIC,
links and address stripped first. The AI is Google's free Gemini tier (or
Groq), and Google may use what is sent on the free tier to improve its
products – set `coach.send_resume: false` to keep the resume text out of the
AI entirely; you still get skill demand, gaps and resume match, which are
computed here. Resume and adverts are treated as data, never as instructions.

**Free limits:** Gemini's free tier allows only a small number of requests per
model per day, and Pro often has no free allowance at all. A coach report uses
3 requests, *Prepare* 1, and the daily review 1 per 20 new jobs (`ai.batch_size`) – so pressing
*Analyse* over and over can use the day's allowance up. When that happens the
report says so ("the AI's free daily limit is used up"), the counted parts are
still refreshed, and the last good analysis, project ideas and tips are kept
(for the same resume) instead of being replaced by nothing. It resets overnight
(Pacific time, about midday in Sri Lanka).

One-off from the command line: `python -m jobot --career` (rebuild the
report) and `python -m jobot --prepare <job id>` (the id is shown on the
job card). In GitHub Actions use *Run workflow* → `career` or `prepare`.

### Companies, reminders and the weekly skills line

* `watch_companies: [CEB, Dialog, "SLT*"]` marks jobs from those employers
  with 👀 and moves them up one importance tier; `avoid_companies: [...]`
  drops jobs from employers you never want. Both are in the *Filters* card.
* Messages (Telegram, e-mail) add a **⏰ Closing soon – your shortlist** block
  for jobs you shortlisted that close within 3 days – even on days with no new
  jobs.
* When you have a coach report, the weekly summary adds the **skills worth
  building** and one **project idea** from it.

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

### How often, and how hard

* **Every 30 minutes.** The workflow's `cron: "13,43 * * * *"` line sets this.
  Change it there if you want it less (or more) often.
* **All sites at once.** The sites are read at the same time (`schedule.workers`,
  6 by default), and inside a site several categories or searches are read side
  by side – never more than a few connections per site, and always with the
  site's usual pause between requests. A whole run takes about a minute or two
  instead of seven. A part of a site that times out is shown as a warning
  ("partly failed") instead of losing the whole site, and a site that fails is
  asked once more.
* **Daily run vs quick runs.** The first run after `schedule.digest_hour` (8)
  sends the daily summary, closing reminders and the weekly summary. The
  runs in between only message you when there are new jobs, with the time in the
  title, and skip a slow site until it is due again.
* **Several entries per site.** A site can be listed more than once, each with
  its own timetable: `type:` names the site's code, `name:` what to call it and
  `every_hours:` how often to ask. The fast entry (for the pages that change all
  day) runs every time; `ikman_more`, `rooster_more` and `topjobs_more` cover
  the long tail every one to two hours, and LinkedIn – which limits anonymous
  searches – every three.
* **What it covers** (turn any off in the Sites card): topjobs – 16 functional
  areas, including the ones EEE work hides in (civil/building services, airline &
  marine, education, sales, medical); ikman – 11 job categories **plus 20
  keyword searches across all ads**, which finds jobs filed under the wrong
  category; Rooster – 31 searches; LinkedIn – 20 searches plus 6 generic titles read two pages deep; ITPro.lk, TechJobs.lk,
  LankaJobs, FindMyJob.lk, Gazette.lk; CEB and SLT-Mobitel; twelve **university
  vacancy pages** (lecturer, instructor, technical-officer posts); and
  [fully remote jobs](#fully-remote-jobs) (ten feeds and hardware employers' boards).
* **Adverts are read in parallel too.** Many Sri Lankan adverts are poster
  images, which are read with OCR; `postings.workers` (4) of them are read at
  once and `postings.max_seconds` (240) caps the time, so a run stays quick even
  right after new sites were added – anything not read yet waits for the next run
  (the message footer says "N left for next run").
* **What got dropped, and why.** Once a week the message lists open jobs that
  match an EEE sub-field but were left out by **your own settings** (a switched-off
  sub-field or level), with the reason for each (`notify.dropped_list`, 8 by
  default, 0 = off). That is the quickest way to notice a setting that is hiding jobs.
* **Finding more sites.** `python -m jobot --probe` (or **Actions → Run workflow →
  probe**) tries every address in `candidates.txt` *from GitHub's own servers*
  and reports which ones answer, are feeds, hold vacancy links, or ask robots
  not to visit (`robots.txt`). Pages you add under `sources.company_pages.pages`
  are only visited when their `robots.txt` allows it.

### How a job is judged

A keyword match only gets a job *considered*. Before anything is sent, each new
job is read against your **requirements** – four plain sentences (qualification,
work, level, place), worded from your settings and editable as `ai.requirements`
in `config.yaml` – in this order:

1. **Plain rules** (free, always on): a sales role, software or IT-desk work, a
   job whose long posting mentions nothing electrical / electronic / telecom,
   a trade title ("Electrician", "Technician") – turned away without asking the AI.
2. **The AI reads the posting.** LinkedIn adverts are opened through its public
   posting page (up to `postings.linkedin_max` = 15 a run), other sites' pages and
   posters are read as before, and the AI gets up to `ai.read_chars` (2500)
   characters of the real text, ten jobs at a time, with the requirements. It
   answers **match / maybe / no** and the one-line reason it found in the text
   ("Windows server administration, no electrical work"). A **no** is held back
   whatever the score, and `ai.min_score` (5) holds back weak "maybes". It is not
   asked to judge experience: your levels (Entry 0-1 years, Mid 2-4 …) are applied
   by the program from the years the advert names.
3. **Waiting.** A job whose posting couldn't be opened yet (LinkedIn limits, a slow
   site), or that the AI couldn't be asked about (quota, outage), is **not sent
   half-checked**: it waits and is judged on a later run – up to `ai.defer_runs`
   (8) runs, about four hours – and then the plain rules decide. The message
   footer says how many are waiting.

The last dry run showed what this fixes: jobs in Texas, Taiwan and Singapore
scored 8/10 because nothing checked the place; "Sales Engineer – Industrial
Automation" passed on the word *automation*; IT-support and Microsoft 365 roles
got in as "engineer" titles. Jobs the keywords never matched can still be found
(the AI triage) – but only reach you if their posting meets the requirements.

### A posting you saw never arrived

Every site goes through the same checks, so one question finds the cause:

```
python -m jobot --explain "Technical Officer telecom projects | Luminex PLC | Jaffna"
```

It prints what each step decided – excluded word or employer, sub-field (and
which switched-off sub-field it would match), level, qualification (stated or
only guessed from the title) – and ends with KEPT, DROPPED or NOT MATCHED. Three
things used to lose postings, and are fixed:

* **A guess hid a match.** "Technical Officer" made a telecom job a diploma job,
  which is switched off; see [Qualification](#qualification-degree--diploma).
* **Titles that name no field** ("Associate Engineer - TechOps", "Associate
  Engineer – Platform SRE") match no keyword. They go to the AI triage, which
  asks about engineer roles first (a long queue of technician and executive titles
  used to starve them), so that their posting gets **read and judged** (see
  [How a job is judged](#how-a-job-is-judged)) instead of the title deciding.
* **The review held them back.** Whatever fails your requirements is held back;
  the message footer names the closest ones ("Held back (not matching your
  requirements), closest first: …"), the run log lists every one with its reason,
  and they stay on the dashboard tagged *held back*.
* **The same job twice.** A LinkedIn job found by the search and again in an alert
  e-mail is sent once, under the site's own listing.
* **The search never asked for them.** LinkedIn only searched EEE titles; it now
  also reads generic ones (`linkedin.broad_keywords`, two pages each), and
  Rooster and ikman search "associate / assistant / junior engineer" too.

### Fully remote jobs

`sources.remote_jobs` reads ten free remote-job feeds at once – Remote OK (ten
category tags), We Work Remotely, Jobicy, Himalayas, Working Nomads, Jobspresso,
NoDesk, the monthly "Who is hiring" thread on Hacker News and the careers pages
of ten hardware employers (Cerebras, Skydio, Wayve, ChargePoint, Samsara, Oura,
Rigetti, Voltus … – add more under `boards:` with the name from their
Greenhouse / Lever / Ashby address) – plus Remotive as its own, slower entry and
`linkedin_remote`, which asks LinkedIn's "remote" filter for jobs listed in Sri
Lanka. Most remote jobs are open only to people in the US or Europe, so each one
is judged twice:

1. **Plain rules** read what the employer says about where candidates may live.
   **Worldwide / anywhere / APAC / Asia / Sri Lanka** (or no restriction at all)
   pass; "US only", "EU", "must overlap US hours", "CET ± 3 hours" and the like
   are dropped; anything the rules can't settle is left *unsure*.
2. **The AI reads the advert** for the new ones (see [AI helpers](#ai-helpers)):
   is it open to someone in Sri Lanka with no work permit elsewhere, and is it
   *fully* remote? "Closed" and "hybrid" ones are dropped; the rest carry a
   one-line note ("Remote, open to Sri Lanka (checked by the AI): worldwide,
   contractors welcome" or "Remote – check eligibility"). Without an AI key the
   plain rules alone decide, and unsure jobs say "Eligibility not checked".

What is kept is marked 🌍 **Remote**, skips the `locations` /
`include_overseas` filters, and then goes through your usual sub-field, level and
qualification settings – so with sub-fields switched off you will see fewer. The
dashboard's Jobs tab has a **Remote only** filter. Each board asks for a link
back, which the job links give. Remote boards don't publish much EEE work
(hardware, firmware, PCB, FPGA, IoT, network and test engineering are what turns
up), and "senior" jobs are dropped by the default levels.

### AI helpers

Besides scoring the day's jobs, the AI key is used where keywords can't decide
(`ai.helpers`, on by default). Each is **one batched request for dozens of jobs**,
answers are remembered in `data/ai_decisions.json`, and a small daily budget
(`ai.daily_budget`, 30 requests) stops the lot for the day – Gemini's free tier is
small. Without a key, or once the budget is used, the plain rules apply instead
and nothing breaks.

* **Triage.** Titles like "Technical Officer", "Project Engineer" or "Assistant
  Engineer" don't say what field they are in, so keyword matching misses them. The
  unmatched engineering-looking jobs are shown to the AI (title, company, site,
  a short snippet), which says whether an EEE graduate would plausibly apply and
  for which sub-field. The ones it picks carry a "Picked by the AI" note and then go
  through your usual level and qualification settings. The ones it turns down are
  not opened for OCR any more, which also keeps the advert backlog short.
* **Remote eligibility.** As described above.
* **Job-alert e-mails** in a layout jobot doesn't know (see the next section): the
  AI lists the vacancies in them, once per e-mail.

The message footer says what the AI did ("AI triage: looked at 40 jobs … picked
3", "AI remote check: 12 jobs checked, 7 dropped"), and the dashboard's job card
shows the note. A busy AI can't hold a run up: each request gives up after
40 seconds, the helpers stop after two unanswered requests in a row and after
`ai.helper_seconds` (180) of waiting, and `schedule.total_seconds` (900) cuts the
helpers, advert reading and AI review short so a run always finishes inside
GitHub's 20-minute limit. Everything in an advert is treated as untrusted text. Tune it
under `ai:` in `config.yaml` (`daily_budget`, `triage_batch`, `triage_calls`,
`vet_batch`, `alert_calls`; `helpers: false` turns the lot off).

### Optional extra channels

These two are **switched on, but say "skipped" in the report until you set them
up** (so nothing fails, and nothing needs turning on later):

* **Job-alert e-mails** (`email_alerts`). XpressJobs, Observer Jobs and a few
  others refuse GitHub's servers, but they will happily e-mail you new jobs. Subscribe
  to their alerts, pointed at a mailbox of yours, and jobot reads those e-mails
  over IMAP and turns the vacancy links into jobs. It is **read-only**: only
  messages from the senders you list (`senders:`), nothing is marked read,
  moved or deleted. Add `IMAP_USERNAME` / `IMAP_PASSWORD` secrets (or it reuses
  `SMTP_USERNAME` / `SMTP_PASSWORD`; a Gmail app password works for both, with
  IMAP switched on in Gmail's settings). LinkedIn, XpressJobs, Rooster, Jobsnet,
  Indeed and TopJobs e-mails are understood directly; **any other alert is read by
  the AI** (once per e-mail, remembered). A refused login shows as "skipped (the
  mailbox refused the login …)".
* **Jooble** (`jooble`). A job search engine that gathers adverts from many sites.
  Its official API is free: get a key at <https://jooble.org/api/about> and add it as
  the `JOOBLE_API_KEY` secret. Skipped until the key is there (or if it is rejected).

One more can't be switched on from here, because it needs a computer of yours:

* **Sites that block GitHub, from your own computer.** `.github/workflows/local.yml`
  runs only XpressJobs and Observer Jobs on a computer of yours, where they see an
  ordinary home connection. Register your computer as a runner (repository
  *Settings → Actions → Runners → New self-hosted runner*), then add a repository
  **variable** `LOCAL_RUNNER` = `true` (*Settings → Secrets and variables → Actions →
  Variables*). The workflow only ever runs on a timer or by hand, never for pull
  requests, so nobody else's code can reach your computer through it – keep
  *Fork pull request workflows* on "require approval". Until you do, the workflow
  does nothing. This one has not been tried on a real runner yet.

### More sites

* **RSS feeds**: add any job feed under `sources.rss.feeds` (WordPress job
  blogs have one at `/feed`).
* **Company careers pages**: add an employer's careers page under
  `sources.company_pages.pages`. Every link that looks like a vacancy is
  picked up; set `subfield` to tag them (e.g. `power` for CEB).

### Other options

* `locations: [Colombo, Gampaha]` sends only jobs in those places.
* `include_overseas: false` (the default) skips every job located outside Sri
  Lanka: the Gulf, Maldives, and any country or city named in the title, location
  or employer line ("Hsinchu", "Singapore", "Austin, TX" …) – LinkedIn and its
  alert e-mails list jobs from all over the world. Fully remote jobs open to Sri
  Lanka are handled separately and kept. Set it to `true` to see jobs abroad too.
* `sources:` turns sites on or off, picks categories/sectors, and sets the searches
  (LinkedIn, ikman, Rooster, Jobicy …).
* `schedule:` sets the hour of the daily run and how many sites are read at once.

### One-off runs with different filters

**Actions → Daily EEE job hunt → Run workflow** has boxes for this. For
example, `levels = internship` and `resend_all = ✓` sends every open
internship once, without changing `config.yaml`. Other boxes: `dry_run` (look,
send nothing), `auto` (behave like a scheduled run: the daily summary if it's
the day's first, otherwise a quick check), `probe` (try the addresses in
`candidates.txt`, or the file named in `probe_file`, from GitHub's servers) and
`career` / `prepare` (the career coach).

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
python -m jobot --career                      # rebuild the career report (needs DASHBOARD_PASSWORD + AI_API_KEY)
python -m jobot --prepare <job id>           # cover letter, bullets, interview questions for one job
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
