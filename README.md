# mynews-radio
毎朝、あなた専用のニュース番組を自動生成。

## セットアップ

1. 環境変数ファイルを作成

```bash
cp .env.example .env
```

2. Docker Compose で起動

```bash
docker-compose up --build
```

## 動作確認

- API ヘルスチェック

```bash
curl http://localhost:8000/health
```

期待値:

```json
{"status":"ok"}
```

- Web フロント

ブラウザで `http://localhost:3000` を開き、Next.js の初期ページが表示されることを確認してください。

## ディレクトリ構成

```text
.
├── backend
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app
│       ├── __init__.py
│       ├── config.py
│       ├── main.py
│       ├── api
│       ├── db
│       │   └── schema.sql
│       └── services
├── frontend
│   ├── Dockerfile
│   ├── package.json
│   └── pages
│       └── index.js
├── data
├── docker-compose.yml
└── .env.example
```
