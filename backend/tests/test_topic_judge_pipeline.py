"""run_radio_pipeline の topic_judge 周辺の回帰テスト。

フェーズは実装のまま動かし、外部へ出る部分（取り込み・要約・LLM・エピソードDB）だけ差し替える。
generate_script は選定結果を記録して 0 行を返し、パイプラインを NO_CONTENT で終わらせる。
"""
import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.batch import radio_pipeline
from app.services import article_service as article_service_module
from app.services.article_service import ArticleService
from app.services.settings_service import ProgramSettings, TopicSetting

JST_TODAY = datetime.now(article_service_module.JST).date().isoformat()
TOPIC = TopicSetting(1, "ローカルLLM", "", "high")


class _FakeEpisodeService:
    def get_episode(self, _episode_id):
        return {}

    def update_episode_status(self, *_args, **_kwargs):
        return None

    def delete_episode(self, _episode_id):
        return None


class _FakeJudgeLLM:
    """判定プロンプトの article_id に対し、article 2 だけ主題（3）と判定する。"""

    def __init__(self, response_mode):
        self.response_mode = response_mode
        self.prompts = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def generate_json(self, prompt):
        self.prompts.append(prompt)
        if self.response_mode == "invalid":
            return None
        article_ids = [int(x) for x in re.findall(r'"article_id": (\d+)', prompt)]
        topic_ids = [int(x) for x in re.findall(r'"topic_id": (\d+)', prompt)]
        return {
            "results": [
                {
                    "article_id": article_id,
                    "relevance": {str(t): (3 if article_id == 2 else 0) for t in topic_ids},
                }
                for article_id in article_ids
            ]
        }


def _add_article(article_id, title, importance, category):
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO articles (id, title, source, url, summary, category, importance_score, status, published_at) "
            "VALUES (?, ?, 'src1', ?, ?, ?, ?, 'summarized', ?)",
            (article_id, title, f"https://example.com/{article_id}", f"要約{article_id}",
             category, importance, JST_TODAY),
        )


def _judge_stored_rows():
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT article_id, topic_id, relevance FROM article_topic_matches ORDER BY article_id"
        )]


@pytest.fixture
def pipeline_env(monkeypatch, tmp_path):
    """要約・取り込み・LLM・エピソードDB以外は実装のまま動かし、呼ばれたフェーズを記録する。"""
    # 通常の運用設定（min_importance は normal の 3）で、重要度2の記事は一般枠に入らない前提。
    _add_article(1, "社会ニュース", 3, "society")
    _add_article(2, "量子化の話", 2, "technology")

    stages = []
    selections = []
    judge_clients = []
    judge_response = {"mode": "relevant"}
    summarize_mode = {"mode": "ok"}

    def run_with_dgx_busy(stage, operation, *args, **kwargs):
        stages.append(stage)
        return operation(*args, **kwargs)

    def summarize_stub(_output_path, **_kwargs):
        if summarize_mode["mode"] == "failed":
            raise RuntimeError("summarize boom")
        return 0 if summarize_mode["mode"] == "empty" else 1

    def generate_script_stub(_script_path, **kwargs):
        profile = kwargs["program_settings"]
        selected = ArticleService().fetch_summaries_for_script(
            max_articles=kwargs["max_articles"],
            min_importance_score=kwargs["min_importance_score"],
            source=kwargs["news_source"],
            priority_themes=profile.priority_themes,
            excluded_themes=profile.excluded_themes,
            topics=profile.topics,
        )
        selections.append([item["id"] for item in selected])
        return 0

    def create_llm_client(_provider, _model):
        client = _FakeJudgeLLM(judge_response["mode"])
        judge_clients.append(client)
        return client

    monkeypatch.setattr(radio_pipeline, "EpisodeService", _FakeEpisodeService)
    monkeypatch.setattr(radio_pipeline, "import_articles_by_source", lambda _source: (1, 0))
    monkeypatch.setattr(radio_pipeline, "run_with_dgx_busy", run_with_dgx_busy)
    monkeypatch.setattr(radio_pipeline, "summarize_articles", summarize_stub)
    monkeypatch.setattr(radio_pipeline, "generate_script", generate_script_stub)
    monkeypatch.setattr(radio_pipeline, "notify_failure", lambda **_kwargs: None)
    monkeypatch.setattr("app.batch.judge_topics.create_llm_client", create_llm_client)
    monkeypatch.setattr(
        "app.services.llm_provider.validate_provider_model",
        lambda _provider, _model: SimpleNamespace(name="ollama", model="test-model"),
    )

    def run(topics, summarize, judge):
        summarize_mode["mode"] = summarize
        judge_response["mode"] = judge
        profile = ProgramSettings(topics=tuple(topics))
        return radio_pipeline.run_radio_pipeline(
            1,
            episode_date="2099-01-01",
            news_source="src1",
            max_articles=2,
            program_settings=profile,
            default_episodes_dir=str(tmp_path / "episodes"),
        )

    return SimpleNamespace(
        run=run, stages=stages, selections=selections, judge_clients=judge_clients,
        episodes_dir=tmp_path / "episodes",
    )


@pytest.mark.parametrize("summarize", ["empty", "failed"])
def test_fallback_review_summaries_match_post_judge_selection(pipeline_env, summarize):
    result = pipeline_env.run([TOPIC], summarize=summarize, judge="relevant")

    assert result == radio_pipeline.PipelineResult.NO_CONTENT
    assert "topic_judge" in pipeline_env.stages
    # 判定で「量子化の話」（重要度2）が高比重として選ばれる。台本の選定もこの結果になる。
    assert pipeline_env.selections == [[2, 1]]
    summaries_path = pipeline_env.episodes_dir / "1" / "summaries.json"
    written = json.loads(summaries_path.read_text(encoding="utf-8"))
    assert [item["article_id"] for item in written] == [2, 1]
    assert _judge_stored_rows() == [(1, 1, 0), (2, 1, 3)]


def test_invalid_judge_response_continues_and_treats_unjudged_as_general(pipeline_env):
    result = pipeline_env.run([TOPIC], summarize="ok", judge="invalid")

    assert result == radio_pipeline.PipelineResult.NO_CONTENT
    assert "generate_script" in pipeline_env.stages
    assert pipeline_env.selections == [[1]]
    assert _judge_stored_rows() == []


def test_no_topics_skips_topic_judge_and_keeps_current_selection(pipeline_env):
    result = pipeline_env.run([], summarize="ok", judge="relevant")

    assert result == radio_pipeline.PipelineResult.NO_CONTENT
    assert "topic_judge" not in pipeline_env.stages
    assert pipeline_env.judge_clients == []
    assert pipeline_env.selections == [[1]]
