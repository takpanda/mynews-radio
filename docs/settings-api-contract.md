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

## ボイス設定 API（BEE-725）

AivisSpeech・VOICEVOX・Fish S2 Pro の男声・女声、計6項目を `user_settings` の追加カラムに保存する。各カラムは NULL 許容で、未保存の項目は `config.py` の現在値をそのまま返す。

### データ契約

```json
{
  "aivispeech_speaker_male": 1310138976,
  "aivispeech_speaker_female": 1388823424,
  "voicevox_speaker_male": 11,
  "voicevox_speaker_female": 2,
  "fishs2pro_voice_male": "male",
  "fishs2pro_voice_female": "morigawa"
}
```

- `aivispeech_speaker_*` / `voicevox_speaker_*` は整数の話者スタイルID（話者IDではない）。真偽値は拒否する。
- `fishs2pro_voice_*` は空文字を含まない文字列のボイス名。
- 6項目は常に全件を送信するフルリプレイス方式（`/settings` の優先テーマ等とは独立したカラム group）。

### API

| Method | Path | 動作 |
|---|---|---|
| GET | `/settings/voices` | 現在値を返す。未保存項目・DB取得失敗時は項目ごとに `config.py` の既定値を返す |
| PUT | `/settings/voices` | 入力検証後に保存。型不正・空文字は422、保存失敗は503 |
| GET | `/settings/voices/options` | 3エンジン分の選択肢一覧を共通形式で返す |

`GET /settings/voices/options` のレスポンス形式:

```json
{
  "aivispeech": {
    "status": "ok",
    "options": [
      {"display_name": "阿井田 茂 - ノーマル", "value": 1310138976, "speaker_name": "阿井田 茂", "style_name": "ノーマル"}
    ],
    "error": null
  },
  "voicevox": { "status": "ok", "options": [ /* 同形式 */ ], "error": null },
  "fishs2pro": {
    "status": "ok",
    "options": [
      {"display_name": "morigawa", "value": "morigawa", "speaker_name": null, "style_name": null}
    ],
    "error": null
  }
}
```

- AivisSpeech・VOICEVOX は Engine 互換 API `GET /speakers` から話者名・スタイル名を取得し、保存値 (`value`) にはスタイルIDを使用する。
- Fish S2 Pro は `GET /health` が返す `voices` をそのまま保存候補として使用する（話者・スタイルの区別がないため `speaker_name` / `style_name` は `null`）。
- 1エンジンの一覧取得に失敗しても他2エンジンの結果は返す。失敗したエンジンは `status: "error"` となり、`error` に一般的な失敗メッセージのみを含める（接続先や認証情報などの内部情報は含めない）。

### 生成処理への反映

`resolve_tts_speakers(engine)`（`app.services.settings_service`）が保存済み話者値（未保存項目は `config.py` 既定値）を返す一元的な解決処理で、以下の4経路すべてがこれを経由する。

- 手動生成・定期生成（`radio_pipeline._determine_tts_config`）
- 記事解説生成（`app.api.generate._run_commentary_generation`）
- 既存エピソードの再合成（`app.api.generate._stream_synthesize`）

`radio_pipeline.run_radio_pipeline` に `tts_speaker_male` / `tts_speaker_female` が明示的に渡された場合は、保存値より明示値を優先する既存契約を維持する（`_determine_tts_config` は明示値が無い場合のみ使われる）。設定行・追加カラム・DB自体のいずれが読み取れない場合も、`config.py` の既定値で生成を継続する。
