# 管理者向け運用ダッシュボード集計 API

## エンドポイント

`GET /admin/dashboard/stats?range=7d|30d`（`range` 既定値 `7d`）

管理者セッション Cookie（`admin_session`）が必須（`require_owner_session`、`/admin/audit-logs` と同じ）。Cookie なし・Bearer のみは `401 {"detail":"Admin session required"}`、無効・期限切れは `401 {"detail":"Invalid or expired session"}`。`range` が `7d` / `30d` 以外は `422`。読み取り専用で、新規テーブル・キャッシュはありません。

期間は「現在時刻（UTC）− 7日 / 30日」以降（境界を含む）です。

## 応答

```json
{
  "range": "7d",
  "since": "ISO8601", "generated_at": "ISO8601",
  "episodes": {"completed": 0, "failed": 0, "in_progress": 0, "success_rate": null},
  "phase_durations": [{"phase": "synthesize|wav_combine|mp3_encode", "count": 0, "avg_ms": null, "max_ms": null}],
  "failures": {
    "by_reason": {"script_missing": 0, "tts_no_lines_succeeded": 0, "tts_synthesis_exception": 0,
                  "wav_combine_failed": 0, "mp3_encode_failed": 0, "build_exception": 0},
    "llm_error_count": 0,
    "recent": [{"occurred_at": "ISO8601", "episode_id": 1, "phase": "synthesize", "reason": "build_exception"}]
  },
  "llm": {
    "latency_by_phase": [{"phase": "script", "call_count": 0, "avg_latency_ms": null, "max_latency_ms": null}],
    "retry_count": 0, "json_parse_failed_count": 0,
    "anomalies_by_phase": [{"phase": "script", "retry_count": 0, "json_parse_failed_count": 0}]
  },
  "pending": {"unapproved_misreading_reports": 0, "awaiting_review_episodes": 0}
}
```

## 集計定義

- `episodes`: `episodes.created_at` 基準。`success_rate = completed / (completed + failed)`、母数 0 件は `null`。`in_progress` は `pending` / `generating` / `synthesizing` / `awaiting_review` の合計。`discarded` は除外。日次自動生成・手動生成を区別しません。
- `phase_durations`: `episode_generation_phase_logs.duration_ms` の平均（小数1桁）・最大。`started_at` 基準、`duration_ms` NULL は除外。3 phase は 0 件でも常に返却（`avg_ms` / `max_ms` は `null`）。
- `failures.by_reason`: `failure_reason` 別件数（6種は 0 件でも返却）。`llm_error_count`: `llm_call_logs.status = 'error'` 件数（`created_at` 基準）。
- `failures.recent`: `failure_reason` を持つ phase ログを `started_at` 降順（同時刻は id 降順）で最大20件。`occurred_at` は `started_at`。詳細は `/admin/episodes/{episode_id}/logs` で確認できます。
- `llm.latency_by_phase`: `llm_call_logs` の phase 別（全 status）。呼び出しがない phase は含まれません（`latency_ms` NULL のみなら平均・最大は `null`）。`anomalies_by_phase` は異常（retry / json_parse_failed）がある phase のみ。
- `pending`: 期間に関係なく全件（`misreading_reports.approved = 0`、`episodes.status = 'awaiting_review'`）。

## 確認手順

```bash
cd backend
python -m pytest tests/test_admin_dashboard.py
```
