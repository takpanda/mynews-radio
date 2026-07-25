# 番組設定 API 契約（MVP）

認証未導入のため、設定は SQLite の `user_settings` テーブルに単一端末・単一ユーザーとして保存する。保存行の ID は常に `1` で、テーマ配列は JSON として保持する。

## データ契約

```json
{
  "priority_themes": ["technology", "business"],
  "excluded_themes": ["sports"],
  "duration_preset": "normal"
}
```

- テーマは `technology`, `business`, `society`, `sports`, `entertainment`, `general` のみ。
- `priority_themes` は最大3件。各配列に重複は許可しない。
- `priority_themes` と `excluded_themes` の同一テーマは許可しない（422）。
- `duration_preset` は `short`（6記事・重要度4以上）、`normal`（10記事・3以上）、`long`（14記事・2以上）のいずれか。
- 未設定または初期化後は、両テーマ配列が空、`duration_preset` が `normal`。

## API

| Method | Path | 動作 |
|---|---|---|
| GET | `/settings` | 現在値を返す。DB取得失敗時も既定値を返し標準生成を継続 |
| PUT | `/settings` | 入力検証後に保存。入力不正は422、保存失敗は503 |
| DELETE | `/settings` | 設定行を削除し既定値へ初期化。失敗は503 |

生成側は保存形式ではなく `ProgramSettings.generation_params()` の契約を利用する。`radio_pipeline` から台本生成・記事選定へ優先テーマ、除外テーマ、尺の件数・重要度が渡される。優先テーマは候補の先頭へ寄せ、除外テーマは対象外とする。ただし重要度5以上の `technology` / `society` は安全弁Bにより対象へ戻す。設定取得が失敗した場合も同メソッドで既定値を取得できるため、既存の標準生成を妨げない。
