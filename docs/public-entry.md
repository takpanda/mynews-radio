# 公開入口のクライアントIP保証

## 採用するプロキシ

Docker Compose の `proxy` サービスで Nginx `1.27-alpine` を使用する。ホストへ公開するのはこのサービスの `3010` ポートだけで、Next.js (`web`) は Compose 内部の `3010` ポートで待ち受ける。`web` には `ports` を設定しないため、ホストや外部ネットワークから Next.js コンテナへ直接到達できない。

`infra/nginx/public-entry.conf` は、受信した `X-Forwarded-For` と `Forwarded` を破棄し、TCP 接続元の `$remote_addr` で `X-Verified-Client-IP` を置換する。これにより、入力ヘッダー由来の値ではない単一値だけを Next.js へ付与する。アクセスログは無効化し、接続元IP・設定値・認証情報を通常ログへ出力しない。

この構成で TLS 終端やロードバランサを Nginx の前段に置く場合、その装置から Nginx までの TCP 接続元を信頼できる構成にすること。任意クライアントから届く `X-Forwarded-For` を Nginx の `real_ip` 設定で採用してはならない。

## ステージング反映手順

1. ステージングの作業ディレクトリで変更を反映する。

   ```sh
   git fetch origin
   git checkout <反映対象コミット>
   docker compose config
   docker compose up -d --build proxy web api
   ```

2. 公開入口経由の疎通を確認する。

   ```sh
   curl -fsS http://<staging-host>:3010/
   ```

3. 偽装ヘッダーを付けた要求を送り、Next.js の受信値をステージング側の一時的な検証用観測手段（プロキシの設定検証または承認済みのテスト計測）で確認する。要求に指定した値が `X-Verified-Client-IP` として到達せず、Nginx が観測した TCP 接続元の単一値だけが到達することを確認する。

   ```sh
   curl -i http://<staging-host>:3010/ \
     -H 'X-Forwarded-For: 198.51.100.10, 198.51.100.11' \
     -H 'Forwarded: for=198.51.100.12' \
     -H 'X-Verified-Client-IP: 198.51.100.13'
   ```

4. ホストから `web:3010` へ直接接続できないことを確認する。Compose のネットワーク内でのみ `web:3010` が解決・接続可能であることも確認する。

   ```sh
   docker compose ps
   docker compose port web 3010
   docker compose exec proxy nginx -t
   ```

   `docker compose port web 3010` が空であること、`proxy` の `nginx -t` が成功することを合格条件とする。

## 本番反映手順

ステージング確認後、同じイメージ・設定を本番へ昇格し、`docker compose config`、`docker compose up -d --build proxy web api`、公開ヘルスチェックの順で実施する。反映前に `API_KEY` などの既存シークレットを変更せず、ログ収集側でも Nginx のアクセスログを有効化しない。ロールバックは直前のコミットへ戻して同じ Compose 手順を実行する。
