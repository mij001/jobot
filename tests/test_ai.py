import json
import json as jsonlib

from jobot import ai
from jobot.models import Job


def make_jobs(n):
    return [Job(source="topjobs.lk", source_id=str(i), title=f"Electrical Engineer {i}",
                url=f"https://t/{i}", subfields=["general"]) for i in range(n)]


class FakeResp:
    def __init__(self, status=200, body=None, text="", headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.text = text or json.dumps(body or {})
        self.ok = status < 400

    def json(self):
        return self._body


def reply(rows):
    return FakeResp(body={"choices": [{"message": {"content": "```json\n" + json.dumps({"results": rows}) + "\n```"}}]})


def test_parse_reply_tolerates_fences_and_chatter():
    text = 'Sure! ```json\n{"results": [{"id": "a", "score": 3}]}\n``` Hope that helps.'
    assert ai.parse_reply(text) == [{"id": "a", "score": 3}]


def test_review_scores_hides_and_fills_levels(cfg):
    cfg.ai.batch_size = 2
    jobs = make_jobs(3)
    calls = []

    def post(url, json, headers, timeout):
        calls.append((url, json, headers))
        adverts = json["messages"][1]["content"].split("Job adverts:\n")[1]
        ids = [j["id"] for j in jsonlib.loads(adverts)]
        return reply([{"id": i, "score": 9 if i.endswith("0") else 2, "level": "entry", "reason": "fits"}
                      for i in ids])

    result = ai.review(jobs, cfg, {"AI_API_KEY": "k"}, post=post, sleep=lambda s: None)
    assert len(calls) == 2  # 3 jobs in batches of 2
    assert calls[0][0].startswith("https://generativelanguage.googleapis.com/")
    assert calls[0][2]["Authorization"] == "Bearer k"
    assert "Electrical & Electronic Engineering" in calls[0][1]["messages"][1]["content"]  # profile sent
    assert [j.ai_score for j in jobs] == [9, 2, 2]
    assert all(j.level == "entry" for j in jobs)
    assert [ai.is_hidden(j, cfg) for j in jobs] == [False, True, True]
    assert (result.scored, result.hidden) == (3, 2)


def test_ai_level_can_hide_a_disabled_level(cfg):
    job = make_jobs(1)[0]
    ai.review([job], cfg, {"AI_API_KEY": "k"}, sleep=lambda s: None,
              post=lambda *a, **k: reply([{"id": job.uid, "score": 8, "level": "senior", "reason": "5+ yrs"}]))
    assert job.level == "senior" and ai.is_hidden(job, cfg)  # senior is off by default


def test_falls_back_to_next_model(cfg):
    used = []

    def post(url, json, headers, timeout):
        used.append(json["model"])
        if len(used) == 1:
            return FakeResp(404, text='{"error": "model not found"}')
        return reply([])

    result = ai.review(make_jobs(1), cfg, {"AI_API_KEY": "k"}, post=post, sleep=lambda s: None)
    assert used == ["gemini-flash-latest", "gemini-3.8-flash"]
    assert result.model == "gemini-3.8-flash" and result.error is None


def test_failure_keeps_jobs_unscored(cfg):
    jobs = make_jobs(2)
    result = ai.review(jobs, cfg, {"AI_API_KEY": "bad"}, sleep=lambda s: None,
                       post=lambda *a, **k: FakeResp(401, text="API key not valid"))
    assert result.error and "401" in result.error
    assert all(j.ai_score is None and not ai.is_hidden(j, cfg) for j in jobs)
    assert result.summary.startswith("AI review unavailable")


def test_rate_limit_waits_then_retries(cfg):
    waits, n = [], {"calls": 0}

    def post(url, json, headers, timeout):
        n["calls"] += 1
        return FakeResp(429, headers={"retry-after": "20"}) if n["calls"] == 1 else reply([])

    ai.review(make_jobs(1), cfg, {"AI_API_KEY": "k"}, post=post, sleep=waits.append)
    assert waits == [20] and n["calls"] == 2


def test_groq_and_custom_endpoints(cfg):
    cfg.ai.provider = "groq"
    assert ai.endpoint(cfg, {})[0] == "https://api.groq.com/openai/v1/chat/completions"
    cfg.ai.models = ["my-model"]
    url, models = ai.endpoint(cfg, {"AI_BASE_URL": "https://llm.example.com/v1"})
    assert url == "https://llm.example.com/v1/chat/completions" and models == ["my-model"]


def test_ai_fills_qualification_and_requirements(cfg):
    job, known = make_jobs(2)
    known.qualifications = ["degree"]  # found by keywords already: the AI doesn't override it
    rows = [{"id": job.uid, "score": 8, "level": "entry", "qualification": ["diploma"],
             "requirements": "HND in Electrical + 1 year", "reason": "ok"},
            {"id": known.uid, "score": 8, "level": "entry", "qualification": ["diploma"], "reason": "ok"}]
    ai.review([job, known], cfg, {"AI_API_KEY": "k"}, sleep=lambda s: None, post=lambda *a, **k: reply(rows))
    assert job.qualifications == ["diploma"] and job.requirements == "HND in Electrical + 1 year"
    assert ai.is_hidden(job, cfg)  # diploma-only; degree holders don't see it by default
    assert known.qualifications == ["degree"] and not ai.is_hidden(known, cfg)


def test_poster_reader_sends_image_and_respects_budget(cfg):
    cfg.ai.enabled, cfg.postings.max_ai_reads = True, 2
    sent = []

    def post(url, json, headers, timeout):
        sent.append(json["messages"][0]["content"])
        return FakeResp(body={"choices": [{"message": {"content": "Electrical Engineer\nBSc required"}}]})

    read = ai.poster_reader(cfg, {"AI_API_KEY": "k"}, post=post, sleep=lambda s: None)
    assert read(b"img", "image/png") == "Electrical Engineer\nBSc required"
    assert sent[0][1]["image_url"]["url"] == "data:image/png;base64,aW1n"
    read(b"img", "image/png")
    assert read(b"img", "image/png") == "" and len(sent) == 2  # only max_ai_reads per run
    assert ai.poster_reader(cfg, {}) is None  # no key
    cfg.ai.provider = "groq"
    assert ai.poster_reader(cfg, {"AI_API_KEY": "k"}) is None  # its models can't see images


def test_overloaded_model_falls_back_and_error_is_short(cfg):
    job = make_jobs(1)[0]
    overloaded = FakeResp(503, body=[{"error": {"code": 503, "message": "This model is currently experiencing\n high demand. Spikes in demand are usually temporary."}}])
    models, waits = [], []

    def post(url, json, headers, timeout):
        models.append(json["model"])
        return overloaded if len(models) <= 2 else reply([{"id": job.uid, "score": 7, "level": "entry", "reason": "ok"}])

    result = ai.review([job], cfg, {"AI_API_KEY": "k"}, post=post, sleep=waits.append)
    # A busy model gets one more try after a pause, then the next model is used.
    assert models == ["gemini-flash-latest", "gemini-flash-latest", "gemini-3.8-flash"] and waits == [ai.BUSY_WAIT]
    assert job.ai_score == 7 and not result.error

    # A brief spike: the same model answers on the second try.
    calls = []
    again = make_jobs(1)[0]
    ai.review([again], cfg, {"AI_API_KEY": "k"}, sleep=lambda s: None, post=lambda url, json, headers, timeout:
              calls.append(json["model"]) or (overloaded if len(calls) == 1 else reply(
                  [{"id": again.uid, "score": 6, "level": "mid", "reason": "ok"}])))
    assert calls == ["gemini-flash-latest"] * 2 and again.ai_score == 6

    result = ai.review(make_jobs(1), cfg, {"AI_API_KEY": "k"}, post=lambda *a, **k: overloaded, sleep=lambda s: None)
    assert result.error.startswith("no model available – HTTP 503: This model is currently")
    assert ai._error_text(overloaded) == "HTTP 503: This model is currently experiencing high demand. Spikes in demand are usually temporary."


def test_ask_json_falls_back_and_parses_fenced_replies(cfg):
    used = []

    def post(url, json, headers, timeout):
        used.append(json["model"])
        if len(used) == 1:
            return FakeResp(404, text='{"error": "model not found"}')
        return FakeResp(body={"choices": [{"message": {"content": 'Sure!\n```json\n{"projects": [1, 2]}\n```'}}]})

    data, model, error = ai.ask_json("sys", "user", cfg, {"AI_API_KEY": "k"}, post=post, sleep=lambda s: None)
    assert data == {"projects": [1, 2]} and model == "gemini-3.8-flash" and error is None
    assert used == ["gemini-pro-latest", "gemini-3.8-flash"]  # the stronger list, Pro first

    data, model, error = ai.ask_json("s", "u", cfg, {"AI_API_KEY": "k"}, sleep=lambda s: None,
                                     post=lambda *a, **k: FakeResp(body={"choices": [{"message": {"content": "no json here"}}]}))
    assert data is None and "reply not understood" in error

    cfg.ai.provider = "nowhere"
    assert ai.ask_json("s", "u", cfg, {})[0] is None


def test_review_adds_the_resume_summary_to_the_profile(cfg):
    job = make_jobs(1)[0]
    seen = []

    def post(url, json, headers, timeout):
        seen.append(json["messages"][1]["content"])
        return reply([{"id": job.uid, "score": 7, "level": "entry", "reason": "ok"}])

    ai.review([job], cfg, {"AI_API_KEY": "k"}, post=post, sleep=lambda s: None, profile_extra="Final-year EEE student; PLC and Python")
    assert "Summary of the seeker's resume:\nFinal-year EEE student; PLC and Python" in seen[0]
    ai.review([job], cfg, {"AI_API_KEY": "k"}, post=post, sleep=lambda s: None)
    assert "resume" not in seen[1]


def test_smart_models_are_used_for_hard_tasks_and_fast_ones_for_scoring(cfg):
    _, fast = ai.endpoint(cfg, {})
    _, smart = ai.endpoint(cfg, {}, smart=True)
    assert fast[0] == "gemini-flash-latest" and smart[0] == "gemini-pro-latest"
    cfg.ai.smart_models = ["my-best-model"]
    assert ai.endpoint(cfg, {}, smart=True)[1] == ["my-best-model"] and ai.endpoint(cfg, {})[1] == fast
    cfg.ai.smart_models, cfg.ai.models = [], ["only-model"]
    assert ai.endpoint(cfg, {"AI_BASE_URL": "https://x/v1"}, smart=True)[1] == ["only-model"]  # your own endpoint, your model
    cfg.ai.provider = "groq"
    cfg.ai.models = []
    assert ai.endpoint(cfg, {}, smart=True)[1][0] == "openai/gpt-oss-120b"


def test_pro_without_free_quota_falls_back_without_waiting(cfg):
    waits, used = [], []
    no_quota = FakeResp(429, text='{"error": {"message": "Quota exceeded for metric generate_content_free_tier_requests, limit: 0, model: gemini-pro"}}')

    def post(url, json, headers, timeout):
        used.append(json["model"])
        return no_quota if json["model"] == "gemini-pro-latest" else FakeResp(body={"choices": [{"message": {"content": '{"ok": true}'}}]})

    data, model, error = ai.ask_json("s", "u", cfg, {"AI_API_KEY": "k"}, post=post, sleep=waits.append)
    assert data == {"ok": True} and model == "gemini-3.8-flash" and waits == []  # no 60 s wait for a quota that is zero
    assert used == ["gemini-pro-latest", "gemini-3.8-flash"]

    # the next question in the same run doesn't ask Pro again
    used.clear()
    ai.ask_json("s", "u", cfg, {"AI_API_KEY": "k"}, post=post, sleep=waits.append)
    assert used == ["gemini-3.8-flash"]
    ai._NO_QUOTA.clear()

    # an ordinary rate limit on one model (after its retry) also moves on rather than giving up
    used.clear()
    limited = FakeResp(429, text="slow down", headers={"retry-after": "1"})
    data, model, _ = ai.ask_json("s", "u", cfg, {"AI_API_KEY": "k"}, sleep=waits.append, post=lambda url, json, headers, timeout:
                                 used.append(json["model"]) or (limited if json["model"] == "gemini-pro-latest" else
                                 FakeResp(body={"choices": [{"message": {"content": '{"ok": 1}'}}]})))
    assert data == {"ok": 1} and used == ["gemini-pro-latest", "gemini-pro-latest", "gemini-3.8-flash"]
