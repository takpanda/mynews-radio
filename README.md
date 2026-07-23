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
| `API_KEY` | API キー（設定時は `POST /generate` と `POST /episodes/{id}/synthesize` に `Authorization: Bearer <key>` が必要） | 空文字（認証無効） |
| `GENERATE_RATE_LIMIT` | 生成系 API のレート制限（例: `5/minute`, `100/hour`） | `5/minute` |
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
# 1. 依存関係をロックファイルに従ってインストール
cd frontend && npm ci

# 2. テストを実行
npm test -- --runInBand
```

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
| POST | `/generate` | エピソード生成（SSE で進捗ストリーミング）※認証（API_KEY 設定時）およびレート制限対象 |
| POST | `/episodes/:id/synthesize` | エピソード音声合成 ※認証（API_KEY 設定時）およびレート制限対象 |

### エピソード生成リクエスト

> **認証**: `API_KEY` が設定されている場合、`Authorization: Bearer <API_KEY>` ヘッダーが必要です。設定がない場合は認証チェックを行いません。
>
> **レート制限**: 既定値 `5/minute`（環境変数 `GENERATE_RATE_LIMIT` で変更可能）。超過時は `429` `{"detail": "Rate limit exceeded. Try again later."}` を返します。

```bash
curl -X POST http://localhost:8010/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
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
