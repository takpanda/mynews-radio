# mynews-radio

毎朝、はてなブックマークのホットエントリをもとに、あなた専用のニュースラジオ番組を自動生成するシステムです。

## 概要

1. **記事取得** — はてなブックマーク等のニュースソースから記事を収集
2. **要約生成** — Ollama（ローカル LLM）で各記事を日本語要約
3. **スクリプト生成** — 要約をもとにラジオ番組スクリプト（男女2人のトーク形式）を生成
4. **音声合成** — VOICEVOX / AivisSpeech でスクリプトを WAV に変換
5. **エピソード組み立て** — ジングル付きで WAV を結合し `episode.mp3` を生成

バッチは毎朝6時（デフォルト）に自動実行されます。Web フロントから手動実行も可能です。

## 技術スタック

| 層 | 技術 |
|---|---|
| バックエンド | Python / FastAPI / SQLite |
| フロントエンド | Next.js 14 / Tailwind CSS |
| LLM | Ollama（例: qwen3.6:35b） |
| 音声合成 | VOICEVOX / AivisSpeech |
| 音声結合 | ffmpeg |
| インフラ | Docker Compose |

## セットアップ

### 前提条件

- Docker / Docker Compose
- Ollama サーバー（ローカルネットワーク上に別途用意）
- VOICEVOX または AivisSpeech サーバー（ローカルネットワーク上に別途用意）

### 手順

1. 環境変数ファイルを作成・編集

```bash
cp .env.example .env
```

主な設定項目:

| 変数 | 説明 | デフォルト |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama API のエンドポイント | `http://192.168.1.103:11434` |
| `OLLAMA_MODEL` | 使用する LLM モデル | `qwen3.6:35b` |
| `VOICEVOX_BASE_URL` | VOICEVOX API のエンドポイント | `http://192.168.1.102:50021` |
| `VOICEVOX_SPEAKER_MALE` | 男性話者 ID | `11` |
| `VOICEVOX_SPEAKER_FEMALE` | 女性話者 ID | `2` |
| `AIVISPEECH_BASE_URL` | AivisSpeech API のエンドポイント | `http://192.168.1.102:10101` |
| `CRON_SCHEDULE` | バッチ実行スケジュール（cron 形式） | `0 6 * * *` |
| `EPISODE_RETENTION_DAYS` | エピソード保持日数 | `30` |

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
curl http://localhost:8000/health
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

## バッチパイプライン

```
import_articles
    → summarize_articles   (Ollama で要約)
    → generate_script      (Ollama でスクリプト生成)
    → synthesize_voicevox  (VOICEVOX / AivisSpeech で音声合成)
    → build_episode        (ffmpeg でジングル付き MP3 組み立て)
```

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
│       ├── batch/             # バッチ処理スクリプト
│       │   ├── orchestrate.py     # パイプライン統括
│       │   ├── import_articles.py
│       │   ├── summarize_articles.py
│       │   ├── generate_script.py
│       │   ├── synthesize_voicevox.py
│       │   └── build_episode.py
│       ├── db/
│       │   └── schema.sql
│       ├── prompts/           # LLM プロンプトテンプレート
│       └── services/          # 外部サービスクライアント
├── frontend/                  # Next.js フロントエンド
├── data/
│   ├── episodes/              # 生成済みエピソード (script.json, *.wav, episode.mp3)
│   ├── jingles/               # BGM・ジングル音声
│   └── logs/                  # バッチ実行ログ
├── tools/
│   └── generate_jingles.py    # ジングル生成ユーティリティ
├── docker-compose.yml
└── .env.example
```

## システムドキュメント

- HTML: `docs/system-documentation.html`
- フロー図 (SVG): `docs/system-flow.svg`
- ER図 (SVG): `docs/er-diagram.svg`
