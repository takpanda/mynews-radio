## pi5向けTelegram通知設定・確認手順

番組生成コンテナの実行環境（pi5の`.env`など）に、Bot tokenをファイルへ直書きせず秘密情報管理の仕組みから注入します。

```dotenv
TELEGRAM_BOT_TOKEN=<Telegram Bot API token>
TELEGRAM_CHAT_ID=<Telegram destination chat id>
PUBLIC_BASE_URL=https://radio.beeworks.cc
```

`TELEGRAM_CHAT_ID`に通知先を設定します。tokenとchat idはリポジトリ、Issue、通常ログへ記録しないでください。既存の`.env`注入経路を使い、`docker compose up -d --build api`後にプロセスを再起動します。

### 手動確認

1. tokenを未投入の状態で既存の生成テストを実行し、生成結果・エピソード終了状態が従来どおりになることを確認する。
2. 試験用グループでBotに投稿権限を与え、tokenと`TELEGRAM_CHAT_ID`を一時的に設定する。
3. 番組を1本生成し、成功通知にタイトル、エピソード番号、`https://radio.beeworks.cc/episodes/{episode}`形式のURLが含まれることを確認する。
4. 記事取得または音声合成を試験環境で失敗させ、失敗工程と短いエラー概要が通知されることを確認する。tokenや長大なスタックトレースが含まれないことも確認する。
5. Telegram APIを到達不能にして再度生成し、通知失敗が警告ログに記録されても生成の成功／失敗状態が変わらないことを確認する。
6. 確認後、試験用tokenを無効化・削除し、本番グループへの実送信は人間の承認後に行う。
