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
