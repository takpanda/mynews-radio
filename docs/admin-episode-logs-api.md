# 管理者向けエピソード詳細ログ API

## エンドポイント

`GET /admin/episodes/{episode_id}/logs`

管理者セッション Cookie（`admin_session`）が必須です。Bearer API キーでは利用できません。Cookie がない場合は `401 {"detail":"Admin session required"}`、無効・期限切れの場合は `401 {"detail":"Invalid or expired session"}` を返します。

任意の `phase_log_id` は、同一エピソードの `synthesize` 工程試行だけを指定できます。未指定時は `attempt_no DESC, id DESC` の最新合成試行の行詳細を返します。指定対象が存在しない・別エピソード・別工程の場合は、いずれも `404 {"detail":"Synthesis phase log not found"}` です。

## 応答契約

- `episode`: `id`, `episode_date`, `seq`, `status`, `type`, `created_at`, `updated_at`
- `generation_jobs`: `claimed_at ASC, id ASC`。所有者は `owner.id` と `owner.username` のみを返却
- `timeline`: 監査ログを `source: "audit"`、工程試行を `source: "phase"` として統合し、`occurred_at ASC`、同時刻は audit、phase、最後に `source_id ASC` で返却
- `lines`: 選択した合成試行の行を `script_line_index ASC` で返却

日時は UTC ISO 8601、`duration_ms` と `processing_duration_ms` はミリ秒、`silence_before_sec` と `start_time_sec` は秒です。未確定工程の `result` は `incomplete` です。エピソードは存在してログがない場合、各配列は空で `200` を返します。

生IP、冪等性キー・そのハッシュ、入力ハッシュ、台本本文、例外本文、ファイルパス、URL、認証情報は応答に含めません。

## 確認手順

```bash
cd backend
PYTHONPATH=. pytest -q tests/test_admin_episode_logs.py tests/test_audit_logging.py tests/test_generation_detail_logs.py
```

認証、空データ、統合タイムライン、最新・過去試行の選択、別エピソード/別工程の非漏えいを確認します。
