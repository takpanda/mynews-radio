# 公開入口のクライアントIP保証

## 採用するプロキシ

Docker Compose の `proxy` サービスで Nginx `1.27-alpine` を使用する。ホストへ公開するのはこのサービスの `3010` ポートだけで、Next.js (`web`) は Compose 内部の `3010` ポートで待ち受ける。`web` には `ports` を設定しないため、ホストや外部ネットワークから Next.js コンテナへ直接到達できない。

`infra/nginx/public-entry.conf` は、受信した `X-Forwarded-For`、`Forwarded`、`X-Verified-Client-IP` を破棄し、TCP 接続元の `$remote_addr` で `X-Verified-Client-IP` を置換する。これにより、入力ヘッダー由来の値ではない単一値だけを Next.js へ付与する。アクセスログは無効化し、エラーログも `/dev/null` の `emerg` レベルとして、接続元IP・設定値・認証情報を記録しない。

エラーログを捨てるため、Nginx のプロキシ障害ログによる調査はできない。これは接続元IPを記録しない受入条件を優先した運用判断であり、障害調査はコンテナ状態、Composeイベント、Next.js／API側の個人情報を含まないアプリケーションログで行う。

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

3. Next.js の一時観測エンドポイントを `APP_ENV=staging` と `STAGING_HEADER_CHECK=1` の組み合わせで有効にして再起動する。`APP_ENV=staging` を必須にすることで、本番環境では環境変数を誤設定しても有効化されない。エンドポイントは値をログやDBへ保存しない。

   ```sh
   APP_ENV=staging STAGING_HEADER_CHECK=1 docker compose up -d --build web proxy
   curl -fsS http://<staging-host>:3010/api/staging-header-check
   ```

4. 偽装ヘッダーを3つ指定した要求を送り、Next.js が実際に受信した値をレスポンスで確認する。レスポンスの `verifiedClientIp` はTCP接続元の単一値であり、要求に指定した3つの値のいずれとも一致しないことを合格条件とする。レスポンス本文は記録・Issueへ転載しない。

   ```sh
   curl -i http://<staging-host>:3010/api/staging-header-check \
     -H 'X-Verified-Client-IP: 198.51.100.13' \
     -H 'X-Forwarded-For: 198.51.100.10, 198.51.100.11' \
     -H 'Forwarded: for=198.51.100.12'
   ```

   実際の確認対象は `/api/staging-header-check` とする。確認後、直ちに観測エンドポイントを無効化して再起動する。

   ```sh
   APP_ENV=staging STAGING_HEADER_CHECK=0 docker compose up -d web proxy
   test "$(curl -s -o /dev/null -w '%{http_code}' http://<staging-host>:3010/api/staging-header-check)" = 404
   ```

5. ホストから `web:3010` へ直接接続できないことを確認する。Compose のネットワーク内でのみ `web:3010` が解決・接続可能であることも確認する。

   ```sh
   docker compose ps
   docker inspect -f '{{json .NetworkSettings.Ports}}' mynews-radio-web
   docker compose exec proxy nginx -t
   ```

   `mynews-radio-web` の `3010/tcp` が `null`（ホスト公開なし）であること、`proxy` の `nginx -t` が成功すること、観測エンドポイントが404になることを合格条件とする。

## 本番反映手順

ステージング確認後、同じイメージ・設定を本番へ昇格し、`docker compose config`、`docker compose up -d --build proxy web api`、公開ヘルスチェックの順で実施する。反映前に `API_KEY` などの既存シークレットを変更せず、ログ収集側でも Nginx のアクセスログを有効化しない。ロールバックは直前のコミットへ戻して同じ Compose 手順を実行する。

## 同一Composeネットワーク内の直接到達を禁止する案（未適用）

現行構成は `web` のホスト公開を外し、外部からの直接到達を禁止している。一方、Compose の既定ネットワークでは同じネットワークに参加するコンテナから `web:3010` を名前解決して接続できる。これは今回の「公開入口以外」を外部到達と解釈した構成であり、仕様確定前に変更しない。

同一Composeネットワーク上の全ピアからも禁止する最小案は、`web` と `api` を別ネットワーク／別ネットワーク名前空間へ分離し、Next.js の API 通信を専用の一方向 egress（またはホスト側ファイアウォールで許可したAPI入口）へ変更すること。単純に `edge`（proxy/web）と `backend`（web/api）の2ネットワークへ分けるだけでは、`web` と `api` が共有する `backend` 上で相互到達できるため要件を満たさない。

この案を採用すると、`API_BASE` の変更、専用egressの追加、Composeネットワーク設計・運用監視の変更、既存の開発用接続手順の更新が必要になる。したがって、外部到達禁止で足りないと仕様確定した場合に別Issueで設計・検証し、今回のPRでは適用しない。
