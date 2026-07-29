# mynews-radio

毎朝、はてなブックマークのホットエントリをもとに、あなた専用のニュースラジオ番組を自動生成するシステムです。

## 概要

1. **記事取得** — はてなブックマーク等のニュースソースから記事を収集
2. **要約生成** — Ollama（ローカル LLM）で各記事を日本語要約
3. **スクリプト生成** — 要約をもとにラジオ番組スクリプト（男女2人のトーク形式）を生成
4. **脚本レビュー** — 4 監督（天才・新人・心配性・楽観的）による LLM レビューで脚本改訂
5. **音声合成** — AivisSpeech / VOICEVOX / Irodori-TTS でスクリプトを WAV に変換
6. **エピソード組み立て** — ジングル付きで WAV を結合し `episode.mp3` を生成

バッチは毎朝6時（デフォルト）に自動実行されます。Web フロントから手動実行も可能です。

## 技術スタック

| 層 | 技術 |
|---|---|
| バックエンド | Python 3.11 / FastAPI / SQLite |
| フロントエンド | Next.js 14 / React 18 / Tailwind CSS |
| LLM | Ollama（例: qwen3.6:35b） |
| 音声合成 | AivisSpeech（デフォルト）/ VOICEVOX / Irodori-TTS |
| 音声結合 | ffmpeg |
| インフラ | Docker Compose |

## セットアップ

### 前提条件

- Docker / Docker Compose
- Node.js 20.x / npm 10 以上（フロントエンドのローカルテストを実行する場合）
- Ollama サーバー（ローカルネットワーク上に別途用意）
- TTS サーバー（AivisSpeech、VOICEVOX、または Irodori-TTS のいずれか）

### 手順

1. 環境変数ファイルを直接作成・編集

`.env` ファイルをプロジェクトルートに作成し、以下の設定項目を書き込みます。

主な設定項目:

| 変数 | 説明 | デフォルト |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama API のエンドポイント | `http://192.168.1.103:11434` |
| `OLLAMA_MODEL` | 使用する LLM モデル | `qwen3.6:35b` |
| `VOICEVOX_BASE_URL` | VOICEVOX API のエンドポイント | `http://192.168.1.102:50021` |
| `VOICEVOX_SPEAKER_MALE` | 男性話者 ID | `11` |
| `VOICEVOX_SPEAKER_FEMALE` | 女性話者 ID | `2` |
| `AIVISPEECH_BASE_URL` | AivisSpeech API のエンドポイント | `http://192.168.1.102:10101` |
| `AIVISPEECH_SPEAKER_MALE` | AivisSpeech 男性話者 ID | `1310138976`（阿井田茂） |
| `AIVISPEECH_SPEAKER_FEMALE` | AivisSpeech 女性話者 ID | `1388823424`（湊音エル） |
| `API_KEY` | API キー（管理API向け。手動の生成開始・再音声合成は管理者セッションが必要） | 空文字 |
| `GENERATE_RATE_LIMIT` | 生成系 API のレート制限（例: `5/minute`, `100/hour`） | `5/minute` |
| `VAPID_PUBLIC_KEY` | Web Push購読でクライアントへ渡すVAPID公開鍵。未設定時は購読APIが503を返す | 空文字（未設定時は購読不可） |
| `VAPID_PRIVATE_KEY` | Web Push送信用VAPID秘密鍵（ログへ出力しない）。cron環境へ自動注入。未設定時は配信バッチがスキップ | 空文字（未設定時は配信スキップ） |
| `VAPID_CLAIMS_EMAIL` | Web Push VAPID claims の連絡先メールアドレス。`VAPID_PRIVATE_KEY` と併せて設定必須 | 空文字（未設定時は配信スキップ） |
| `PUSH_RATE_LIMIT` | Web Push購読登録・解除APIのレート制限 | `30/minute` |
| `DEFAULT_TTS_ENGINE` | デフォルト TTS エンジン (`aivispeech` / `voicevox`) | `aivispeech` |
| `CRON_SCHEDULE` | バッチ実行スケジュール（cron 形式） | `0 6 * * *` |
| `EPISODE_RETENTION_DAYS` | エピソード保持日数 | `30` |
| `MAX_SCRIPT_ARTICLES` | スクリプト生成に使用する最大記事数 | `10` |
| `MIN_IMPORTANCE_SCORE` | 記事の最低重要度スコア | `3` |

2. ジングル音声ファイルを配置（任意）

```
data/jingles/opening.mp3
data/jingles/ending.mp3
data/jingles/transition.mp3
```

3. Docker Compose で起動

```bash
docker compose up --build
```

## 動作確認

### API ヘルスチェック

```bash
curl http://localhost:8010/health
# => {"status":"ok"}
```

### Web フロント

ブラウザで `http://localhost:3010` を開きます。最新エピソードの再生と、エピソードの手動生成が可能です。

### バッチ手動実行

```bash
# 今日分のエピソードを手動生成
docker compose exec api python3 /app/app/batch/orchestrate.py

# 特定日付を指定して生成
docker compose exec api python3 /app/app/batch/orchestrate.py 2026-05-31
```

### フロントエンドテスト（ローカル）

依存関係未導入の状態からフロントエンドのテストを実行するには:

```bash
# 1. Node.js 20.x を選択（nvmを使う場合）
cd frontend
nvm use

# 2. 依存関係をロックファイルに従ってインストール
npm ci

# 3. テストを実行
npm test -- --runInBand
```

`nvm` を使わない場合は、Node.js 20.x と npm 10 以上を用意したうえで `frontend` ディレクトリから `npm ci` を実行してください。`.nvmrc` と `package.json` の `engines` が必要なバージョンを示します。

### フロントエンドテスト（Docker）

```bash
# Docker イメージをビルド
docker compose build web

# テストを実行（コンテナ内で npm test）
docker compose run --rm web npm test -- --runInBand
```

## バッチパイプライン

```
import_articles
    → summarize_articles          (Ollama で要約)
    → generate_script             (Ollama でスクリプト生成)
    → review_script               (4 監督レビューで脚本改訂、非致命的)
    → synthesize_voicevox         (AivisSpeech / VOICEVOX で音声合成)
    → build_episode               (ffmpeg でジングル付き MP3 組み立て)
```

### 4 監督レビューシステム

スクリプト生成後、以下の 4 人のバーチャル監督による LLM レビューが自動実行されます:

| 監督 | 役割 |
|---|---|
| **天才監督** | 創造性と独創性を評価 |
| **新人監督** | 初心者の視点で分かりやすさをチェック |
| **心配性監督** | リスクや問題点を指摘 |
| **楽観的監督** | ポジティブなフィードバックと改善提案 |

レビュー結果を統合して改訂版スクリプトが生成され、別途音声合成・組み立てされます。このステップは非致命的で、失敗してもメインパイプラインには影響しません。

### エピソード自動クリーンアップ

`EPISODE_RETENTION_DAYS` で指定した日数を超えたエピソードは自動的に削除されます（DB レコードと関連ファイルの両方）。

いずれかのステップが失敗した場合、後続ステップはスキップされ、エピソードのステータスが `failed` に設定されます。

## ディレクトリ構成

```text
.
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── crontab
│   └── app/
│       ├── config.py          # 設定（環境変数）
│       ├── main.py            # FastAPI アプリ
│       ├── api/               # REST API エンドポイント
│       │   ├── health.py
│       │   ├── episodes.py
│       │   └── generate.py
│       ├── batch/             # バッチ処理スクリプト
│       │   ├── orchestrate.py     # パイプライン統括
│       │   ├── import_articles.py
│       │   ├── summarize_articles.py
│       │   ├── generate_script.py
│       │   ├── review_script.py   # 4 監督レビュー
│       │   ├── synthesize_voicevox.py
│       │   ├── build_episode.py
│       │   ├── cleanup_episodes.py
│       │   └── run_daily.py
│       ├── db/
│       │   └── schema.sql
│       ├── prompts/           # LLM プロンプトテンプレート
│       └── services/          # 外部サービスクライアント
│           ├── ollama_client.py
│           ├── voicevox_client.py
│           ├── irodori_client.py
│           ├── hatena_fetcher.py
│           ├── ffmpeg_service.py
│           └── episode_service.py
├── frontend/                  # Next.js フロントエンド
│   ├── app/
│   │   ├── api/               # API ルート
│   │   ├── components/        # React コンポーネント
│   │   │   ├── EpisodePlayer.tsx
│   │   │   ├── EpisodeList.tsx
│   │   │   ├── ScriptViewer.tsx
│   │   │   └── GenerateEpisodeButton.tsx
│   │   └── episodes/          # エピソードページ
│   └── package.json
├── data/
│   ├── episodes/              # 生成済みエピソード (script.json, *.wav, episode.mp3)
│   ├── jingles/               # BGM・ジングル音声
│   └── logs/                  # バッチ実行ログ
├── tools/
│   └── generate_jingles.py    # ジングル生成ユーティリティ
├── docker-compose.yml
└── README.md
```

## TTS エンジン切替

`DEFAULT_TTS_ENGINE` 環境変数でデフォルトの音声合成エンジンを切替できます:

| 値 | エンジン | 説明 |
|---|---|---|
| `aivispeech` | AivisSpeech | デフォルト。高品質な日本語音声合成 |
| `voicevox` | VOICEVOX | オープンソース TTS エンジン |

Irodori-TTS（OpenAI 互換 API）も利用可能です。詳細は `backend/app/services/irodori_client.py` を参照してください。

## システムドキュメント

- HTML: `docs/mynews-radio-system-documentation.html`

## API エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/health` | バックエンドヘルスチェック |
| GET | `/health/ollama` | Ollama 疎通確認 |
| GET | `/health/voicevox` | VOICEVOX 疎通確認 |
| GET | `/episodes` | エピソード一覧取得 |
| GET | `/episodes/:id` | エピソード詳細取得 |
| GET | `/episodes/:id/script` | スクリプト JSON 取得 |
| GET | `/audio/:id/*` | 音声ファイル配信 |
| POST | `/generate` | エピソード生成（SSE で進捗ストリーミング）※管理者セッション認証およびレート制限対象 |
| POST | `/episodes/:id/synthesize` | エピソード音声合成 ※管理者セッション認証およびレート制限対象 |
| GET | `/push/vapid-public-key` | VAPID公開鍵取得。未設定時は503を返す |
| POST | `/push/subscriptions` | Web Push購読登録。endpoint(p256dh,auth)を受付け、解除専用の不透明な `subscription_id` を返す（冪等、レート制限対象）。バリデーションエラー時は `{"detail": "Invalid push subscription"}` |
| DELETE | `/push/subscriptions/:subscription_id` | 不透明な `subscription_id` による購読解除（未登録でも冪等に204、レート制限対象） |

### エピソード生成リクエスト

> **認証**: 生成開始と再音声合成は、ログイン済みの管理者セッション（`admin_session` Cookie）が必要です。`API_KEY` によるBearer認証では実行できません。
>
> **レート制限**: 既定値 `5/minute`（環境変数 `GENERATE_RATE_LIMIT` で変更可能）。超過時は `429` と `Retry-After`（秒）を返します。同一操作の再送では同じ `Idempotency-Key` を送信してください。

```bash
curl -X POST http://localhost:8010/generate \
  -H "Content-Type: application/json" \
  -H "Cookie: admin_session=your-admin-session" \
  -d '{
    "date": "2026-06-14",
    "max_articles": 10,
    "news_source": "hatena_bookmark",
    "tts_engine": "aivispeech",
    "enable_review": true
  }'
```

`POST /generate` は Server-Sent Events (SSE) で各フェーズの進捗をストリーミングします:

| フェーズ | 説明 |
|---|---|
| `start` | 開始 |
| `import` | 記事取得 |
| `summarize` | LLM 要約 |
| `generate_script` | 台本生成 |
| `review` | 4 監督レビュー |
| `synthesize` | 音声合成 |
| `build` | MP3 統合 |
| `complete` | 完了 |

## ニュースソース

| ソース | ID | 説明 |
|---|---|---|
| はてなブックマーク (tech) | `hatena_bookmark` | news.beeworks.cc API 経由のテックニュース |
| はてなホットエントリー | `hatena_hotentry_all` | Hatena RSS 経由の総合ニュース |
| Yahoo! ニュース | `yahoo_news` | Yahoo! Japan RSS 経由の総合ニュース |

## Web Push通知

### 通知の対象

通知は `type=radio` のエピソード完了時に送信されます（手動生成を含む）。解説エピソードなど `radio` 以外のタイプでは通知されません。

### 利用手順

ホーム画面のエピソード情報下部に通知トグルボタンがあります。

- **未購読時**: 「毎朝、完成を通知」と表示。クリックするとブラウザの通知許可ダイアログが表示されます
- **許可後**: 自動的に購読が登録され「通知ON」に変わります。以後、`type=radio` のエピソードが完成するたびに通知が届きます
- **購読中**: 「通知ON」と表示。クリックすると購読を解除できます
- **拒否時**: 「通知オフ」と表示。トグルを押すと「ブラウザの設定で通知を有効にしてください」と案内します
- **非対応環境**: ブラウザが Web Push に対応していない場合「通知に対応していません」と表示されます

通知をタップすると該当エピソードの詳細画面（`/episodes/{id}`）が開きます。エピソードが特定できない場合はトップページ（`/`）が開きます。

### 購読登録・解除の流れ

1. 利用者がトグルボタンをクリック
2. `Notification.requestPermission()` でブラウザの権限ダイアログを表示
3. 許可された場合、サーバーから VAPID 公開鍵を取得
4. `PushManager.subscribe()` でプッシュ購読オブジェクトを生成
5. 購読情報（endpoint, p256dh, auth）をサーバーに登録
6. サーバーから発行された不透明な `subscription_id` をローカルストレージに保存
7. 解除時は `subscription_id` でサーバーに DELETE し、`PushManager.unsubscribe()` を実行

## Web Push配信（運用者向け）

### 配信方式

Web Push の配送は常駐ワーカーではなく、1分周期の cron ジョブ（`deliver_notifications.py`）で処理されます。`entrypoint.sh` によりコンテナ起動時に自動設定されます。

### 前提条件

配信を有効にするには以下の3つの環境変数がすべて設定されている必要があります。

- `VAPID_PUBLIC_KEY` — 公開鍵。未設定時は購読APIが503を返し、クライアントは購読できません
- `VAPID_PRIVATE_KEY` — 秘密鍵。cron 環境へ自動注入されます。未設定時は配信バッチがスキップされます
- `VAPID_CLAIMS_EMAIL` — 連絡先メールアドレス。`VAPID_PRIVATE_KEY` と併せて設定必須

秘密鍵はログに出力されないよう設計されています。`entrypoint.sh` の `crontab -l` 表示でもマスクされます。

### 無効購読の自動停止

配信先が 410 Gone または 404 Not Found を返した場合、該当の購読レコードは自動的に無効化（`is_active = 0`）され、以降の配信対象から除外されます。

### 再送動作

送信試行は初回を含め最大3回（失敗後は60秒、次の失敗後は120秒で再試行）。3回すべて失敗すると配信は `failed` 状態になります。

### 配信状態の確認

配信結果は `data/logs/crontab.log` に記録されます。VAPID送信設定済みの場合、各実行サイクルの終了時に以下の統計が出力されます。

```
Web Push delivery complete: claimed=N success=N failed=N disabled=N
```

各項目の意味:

| 項目 | 説明 |
|------|------|
| claimed | 今回のサイクルで処理した配信件数 |
| success | 成功した配信件数 |
| failed | 今回のサイクルで失敗した送信試行数（後続サイクルで再試行されるものも含む） |
| disabled | 410/404 により無効化された購読数 |

VAPID秘密鍵またはclaimsが未設定の場合、配信バッチは統計を出力せずにスキップされます。

## トラブルシューティング

### Ollama に接続できない

```bash
# Ollama の疎通確認
curl http://localhost:8010/health/ollama
```

`OLLAMA_BASE_URL` が正しいか確認し、Ollama サーバーが起動していることを確認してください。

### 音声合成が失敗する

TTS エンジンのヘルスチェックを確認:

```bash
curl http://localhost:8010/health/voicevox
```

`DEFAULT_TTS_ENGINE` を `aivispeech` または `voicevox` に切替えてみてください。

### エピソードが生成されない

ログを確認:

```bash
docker compose logs api | grep -i error
```

バッチを手動実行して詳細なエラーを確認:

```bash
docker compose exec api python3 /app/app/batch/orchestrate.py
```

### 古いエピソードをクリーンアップ

`cleanup_episodes.py` を手動実行:

```bash
docker compose exec api python3 /app/app/batch/cleanup_episodes.py
```
