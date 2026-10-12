# MyNews Radio 用 Alexa Skill 設計書

Echo Show 15（および音声対応 Alexa デバイス）で MyNews Radio（https://radio.beeworks.cc）のエピソードを AudioPlayer により連続再生する Alexa Custom Skill の設計書。

## 1. 目的とスコープ

- **目的**: 「Alexa、マイニュースラジオを開いて」で最新エピソードを案内・再生し、「続きから」「次へ」で連続再生できるようにする。
- **スコープ**: バックエンド（FastAPI + radio.beeworks.cc）は変更しない。スキル側（Lambda）が `radio.beeworks.cc` の既存 API と音声配信を利用する。
- **非スコープ**: 一般公開（ストア配信）は本設計では扱わない。自分の Echo Show 15 で開発中スキルとして動かすのをゴールとする。

## 2. 全体アーキテクチャ

```
「Alexa、マイニュースラジオを開いて」
        │
        ▼
Alexa Custom Skill (nodejs Lambda)
  ├─ LaunchRequest ──→ GET https://radio.beeworks.cc/api/episodes?category=commentary&limit=5
  │                        │  (AudioPlayer 用 metadata を組み立て)
  │                        ▼
  │                    Speech + AudioPlayer.Play(REPLACE_ALL)
  │
  ├─ AudioPlayer.PlaybackNearlyFinished ──→ AudioPlayer.Play(ENQUEUE) で次の回へ
  ├─ AMAZON.Pause / Resume / Next ──→ AudioPlayer.Stop / Play / 次へ
  └─ AudioPlayer.PlaybackFinished / Failed ──→ 状態管理（失敗時リカバリ）

音声実体: https://radio.beeworks.cc/audio/<dir>/<file>  (フルURL化)
```

- スキルは `https://radio.beeworks.cc` の **`/api/episodes`** を JSON で叩き、返ってきた各エピソードの `audio_url`（相対パス）へ `public_base_url` を結合してフルURLを作る。
- 音声はサーバー側 `serve_audio_file` が **Range 対応**で配信する（シーク・続き再生が動く）。

## 3. バックエンド確定仕様（実装 takpanda/mynews-radio から調査した値）

### 3.1 エピソードAPI `GET /api/episodes`

- **公開条件**: `status == "completed"` かつ **実音声ファイルが存在する**（`episodes.py` の `_is_public_episode`）。生成中・失敗・下書きは返らない。
- **クエリパラメータ**:
  - `limit`（int, ge=1）: 指定時は `{ items, total, has_next }` のオブジェクト、未指定なら全件の配列。
  - `offset`（int, ge=0）: 取得開始位置。
  - `category`（`all|tech|general|commentary`）: カテゴリ絞込。`commentary` は `type` を直接参照。`tech`/`general` は `categories` フィールド経由。
  - `include_failed`（bool）: 管理用（オーナーセッション必須）。
- **主なレスポンスフィールド**（各エピソード）:
  - `id` (number)
  - `title` / `subtitle` (string) — `script.json` / `metadata.json` から補完（`_enrich_episode`）
  - `date` (string, YYYY-MM-DD)
  - `duration` / `duration_seconds` (number, 秒)
  - `audio_url` (string, **相対パス**、例 `/audio/588/episode.mp3`)
  - `status` (string)
  - `type` (string, `radio` | `commentary`)
  - `source_url` (string)
  - `categories` (array)
  - `has_script` (bool)

### 3.2 音声配信 `GET /audio/{dir}/{file}`

- `main.py` の `serve_audio_file`: **HTTP Range 対応**のストリーミング配信（`206 Partial Content` / `Accept-Ranges: bytes`）。
- 公開HTTPS・有効なSSL証明書・`audio/mpeg`。Cloudflare 前段。
- AudioPlayer の要件（インターネット到達可能なHTTPS/ポート443/有効SSL/形式 16-384kbps/シーク可能）を**全て満たす**。

### 3.3 フルURL化のベース

- `public_base_url = "https://radio.beeworks.cc"`（`config.py:83`）。
- RSS 配信 `feed.py` の `_build_absolute_audio_url` は `{base}/audio/{dir}/{file}` と組み立てる。スキルも同じロジックで **`public_base_url + audio_url`** を結合する。

### 3.4 注意: RSS フィードは使わない

- `feed.py` に `GET /feed.xml` は存在するが、`https://radio.beeworks.cc/feed.xml` は **404**（デプロイで無効 or 別設定の疑い）。
- したがってスキルは RSS フィードに依存せず、**`/api/episodes` を直接叩く**。

## 4. フルURL化ヘルパー

```js
// Lambda 内のヘルパー
const PUBLIC_BASE_URL = 'https://radio.beeworks.cc';

function toAbsoluteAudioUrl(episode) {
  if (!episode || !episode.audio_url) return null;
  return `${PUBLIC_BASE_URL}${episode.audio_url}`; // audio_url は "/audio/588/episode.mp3" の形
}
```

- `audio_url` は必ずルート相対パス（`/` 始まり）で返るため、単純連接で良い。
- 将来 `public_base_url` を外部設定にする場合はスキルの環境変数に切り出す。

## 5. スキルレスポンス設計

### 5.1 LaunchRequest（起動）

- `/api/episodes?category=commentary&limit=5` を叩き、最新エピソードを特定。
- 例: 「MyNews Radio です。最新は『〇〇』です。再生しますか？」→ 再生 Intent へ。

### 5.2 再生 Intent → AudioPlayer.Play（REPLACE_ALL）

```json
{
  "version": "1.0",
  "response": {
    "shouldEndSession": true,
    "directives": [
      {
        "type": "AudioPlayer.Play",
        "playBehavior": "REPLACE_ALL",
        "audioItem": {
          "stream": {
            "token": "episode-588",
            "url": "https://radio.beeworks.cc/audio/588/episode.mp3",
            "offsetInMilliseconds": 0
          },
          "metadata": {
            "title": "音声合成の日本語化手法が一般化した話",
            "subtitle": "解説",
            "art": { "sources": [ { "url": "https://radio.beeworks.cc/images/categories/commentary.png" } ] },
            "backgroundImage": { "sources": [ { "url": "https://radio.beeworks.cc/images/categories/commentary.png" } ] }
          }
        }
      }
    ]
  }
}
```

- `shouldEndSession: true` にすることで、再生開始後はスキル名なしで再生コントロールが効く。
- `metadata.art` / `backgroundImage` は Echo Show 15 の画面に表示されるアートワーク。

### 5.3 AudioPlayer.PlaybackNearlyFinished（連続再生）

- エピソードが約80%再生されたら `AudioPlayer.PlaybackNearlyFinished` が飛んでくる。
- このタイミングで次の completed エピソードを `playBehavior: "ENQUEUE"` で流す（途切れない連続再生）。
- token を次のエピソードに更新しつつ、`expectedPreviousToken` をチェックして重複 ENQUEUE を防ぐ。

### 5.4 再生コントロール Intent

- `AMAZON.PauseIntent` → `AudioPlayer.Stop`
- `AMAZON.ResumeIntent` → `AudioPlayer.Play`（前回の offsetInMilliseconds から再開）
- `AMAZON.NextIntent` → 次のエピソードへ（または `PlaybackController.NextCommandIssued`）
- Echo Show 15 のタッチ操作時は `PlaybackController.*CommandIssued` が飛んでくるので同様に処理。

### 5.5 Player 状態イベント

- `AudioPlayer.PlaybackFinished` / `PlaybackStopped`: 状態をクリア。
- `AudioPlayer.PlaybackFailed`: ログ + 次のエピソードへスキップするリカバリ。

## 6. カテゴリ設計

- `commentary`（解説）: 短め（2-4分）。通しで聴く想定。
- `radio`（テック本編）: テックニュース。`category=tech` / `category=general` でも絞れる。
- UX 方針: まず「最新を再生」+ 連続再生で動かし、後からカテゴリ切替（「解説を続けて」「テックのニュースを続けて」）を足す。

## 7. エラー処理と再生状態管理

- API が空を返す / 404: 「新しいエピソードはまだありません」と案内して応答終了。
- 音声ストリーム失敗（PlaybackFailed）: ログに記録し、次のエピソードへ ENQUEUE を試みる。連続で失敗する場合は案内して終了。
- 状態は Lambda 内メモリ（または DynamoDB 等の永続化）で管理。PlaybackNearlyFinished 二重発火に備え token を必ず検証する。

## 8. 実機テスト手順（Echo Show 15）

1. Alexa Developer Console でスキルを作成（Custom / Alexa-hosted(Node.js) / English (US)）。
2. AudioPlayer インターフェースを有効化。
3. スキルに `https://radio.beeworks.cc` へのアクセス許可（アウトバウンド呼び出し）を設定。
4. 開発中スキルとして自分の Echo Show 15 に配信（開発者モード）。
5. 「マイニュースラジオを開いて」で再生確認 → 連続再生・一時停止・次へを検証。

## 9. 公開時の注意

- ポッドキャスト / ラジオ種別のスキルは現在 **developer preview**。一般ストア公開には Amazon（Music/Radio/Podcast 担当）への登録が必要。
- 自分のデバイスで試す分には不要。

## 10. 未確定事項と次のアクション

- [ ] `/api/episodes` の `category` フィルタ実動作を確認（commentary / tech / general の違い）→ 設計最終確定。
- [ ] カテゴリ切替インテントを入れるかの判断。
- [ ] Lambda スケルトン実装（Node.js index.js）。
- [ ] 実機テスト。

---

**関連**: Multica issue BEE-1123（本件の進行を追跡）。
