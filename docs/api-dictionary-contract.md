# 辞書管理API契約書

> BEE-422 統合案A（`/admin/dictionary` パス、既存ルータ方式）に基づく API 契約
> 事前レビュー must 項目（藤崎奈緒）および認証前提条件を含む

---

## 1. 共通仕様

### ベースパス

- `/admin/dictionary`
- `/api` プレフィックスは付けない（既存 `/episodes`, `/generate` と同一方式）
- リバースプロキシ側で `/api` を付与する構成を推奨

### ルータマウント方式

`backend/app/api/dictionary.py` にて定義:

```python
router = APIRouter()
```

`backend/app/main.py` にてマウント:

```python
from app.api.dictionary import router as dictionary_router
app.include_router(dictionary_router)
```

### 認証方式

| 項目 | 仕様 |
|------|------|
| 方式 | Bearer Token（`Authorization: Bearer <token>`） |
| 検証関数 | `generate.py` の `verify_api_key` を流用 |
| APIキー未設定時 | `API_KEY` 環境変数が未設定の場合は認証を通過（全許可） |
| 認証失敗時 | HTTP 401 `{"detail": "Invalid or missing API key"}` |
| 適用範囲 | 全エンドポイント共通（`dependencies=[Depends(verify_api_key)]`） |

#### 認証前提条件（管理者限定の保証について）

- 本 API が管理者限定となるのは、`API_KEY` が管理者専用キーとして運用される場合に限られる
- `API_KEY` 未設定環境では認証が通過するため、ステージング・本番環境では必ず `API_KEY` を設定すること
- 上記の前提が満たされない場合、管理者限定の保証はできない
- 追加の認可機構（ロールベースなど）は初回対象外とする

### データ形式

- リクエスト/レスポンスともに JSON
- 文字エンコーディング: UTF-8

### エラー形式

全てのエラーは FastAPI 標準の形式で返却する。401/404/409 は文字列の `detail`、422 は Pydantic が自動生成する配列の `detail` となる。

**401/404/409（文字列 detail）:**

```json
{"detail": "<エラーメッセージ>"}
```

**422（配列 detail）:**

```json
{"detail": [{"loc": ["body", "word"], "msg": "ensure this value has at most 100 characters", "type": "value_error"}]}
```

| ステータス | 条件 | 例 |
|-----------|------|-----|
| 400 Bad Request | アプリケーション固有の業務バリデーション（Pydanticが自動検出しない条件） | SSRFチェック、業務ルール違反、依存関係の不整合。辞書管理APIでは現状 400 を返す条件は定義しない |
| 401 Unauthorized | APIキーなし / 不一致 | `{"detail": "Invalid or missing API key"}`（文字列 detail） |
| 404 Not Found | 指定したIDのリソースが存在しない | `{"detail": "Dictionary entry not found"}`（文字列 detail） |
| 409 Conflict | 同一 `word` + `reading` の重複 | `{"detail": "Dictionary entry already exists"}`（文字列 detail） |
| 422 Unprocessable Entity | Pydantic が自動検出するスキーマバリデーション | `max_length` 超過、`ge`/`le` 制約違反、必須フィールド欠落、型不正（**配列 detail**） |

---

## 2. エンドポイント一覧

### 2.1 一覧取得

| 項目 | 内容 |
|------|------|
| メソッド | GET |
| パス | `/admin/dictionary` |
| 認証 | 要 |
| 概要 | 辞書エントリの一覧を取得する |

#### クエリパラメータ

| パラメータ | 型 | 必須 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| `limit` | integer | 任意 | 未指定時は全件 | 取得件数（ge=1） |
| `offset` | integer | 任意 | 0 | 取得開始位置（ge=0） |
| `search` | string | 任意 | なし | 部分一致検索（`word`, `reading` 対象） |
| `category` | string | 任意 | なし | カテゴリによるフィルタ |
| `status` | string | 任意 | なし | 状態フィルタ（`active` または `inactive`）。両方表示する場合はクエリを省略する |

> **`status` フィルタについて**: 一覧APIは `status=active` / `status=inactive` の両方をサポートし、`inactive` を常に除外しない。画面要件（BEE-420）では無効エントリも一覧表示するため、`status` 未指定時は全状態のエントリを返却する。`inactive` の除外適用対象は生成時の辞書適用のみ（セクション5参照）。

#### レスポンス（成功時: 200）

`limit` 指定時:

```json
{
  "items": [
    {
      "id": 1,
      "word": "サンプル",
      "reading": "サンプル",
      "category": "ニュース",
      "status": "active",
      "notes": "備考",
      "updated_at": "2026-07-12T12:00:00Z"
    }
  ],
  "total": 42,
  "has_next": true,
  "stats": {
    "total": 100,
    "active": 80,
    "inactive": 20
  }
}
```

`limit` 未指定時（既存API `episodes.py` と同一動作）:

```json
[
  {
    "id": 1,
    "word": "サンプル",
    "reading": "サンプル",
    "category": "ニュース",
    "status": "active",
    "notes": "備考",
    "updated_at": "2026-07-12T12:00:00Z"
  }
]
```

> **BEE-420 への注意**: `limit` 未指定で呼び出すと配列が返る。管理画面はページネーションが前提のため、常に `limit` を指定して呼び出すこと。

#### エラーケース

なし（空の場合は `[]` を返す）

---

### 2.2 詳細取得

| 項目 | 内容 |
|------|------|
| メソッド | GET |
| パス | `/admin/dictionary/{id}` |
| 認証 | 要 |
| 概要 | 指定したIDの辞書エントリの詳細を取得する |

#### パスパラメータ

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `id` | integer | 必須 | 辞書エントリのID |

#### レスポンス（成功時: 200）

```json
{
  "id": 1,
  "word": "サンプル",
  "reading": "サンプル",
  "category": "ニュース",
  "status": "active",
  "notes": "備考",
  "updated_at": "2026-07-12T12:00:00Z"
}
```

#### エラーケース

| 条件 | ステータス | 内容 |
|------|-----------|------|
| 存在しないID | 404 | `{"detail": "Dictionary entry not found"}` |

---

### 2.3 作成

| 項目 | 内容 |
|------|------|
| メソッド | POST |
| パス | `/admin/dictionary` |
| 認証 | 要 |
| 概要 | 辞書エントリを作成する |

#### リクエストボディ

```json
{
  "word": "サンプル",
  "reading": "サンプル",
  "category": "ニュース",
  "notes": "備考（任意）"
}
```

| フィールド | 型 | 必須 | 制約 | 説明 |
|-----------|-----|------|------|------|
| `word` | string | 必須 | 1〜100文字 | 単語（表層形）。BEE-420のUI制約に合わせる |
| `reading` | string | 必須 | 1〜200文字 | 読み。BEE-420のUI制約に合わせる |
| `category` | string | 必須 | 1〜100文字 | カテゴリ |
| `notes` | string | 任意 | 最大500文字 | 備考。BEE-420のUI制約に合わせる |

> **入力制限の根拠**: BEE-420 の UI 制約（word:100, reading:200, notes:500）に API 側を合わせる。UI で入力可能な値が API で弾かれることを防ぎ、かつ UI 制約を超える値の API 直投入も防止する。100/200/500 は辞書エントリとして十分な長さである。

#### レスポンス（成功時: 201）

```json
{
  "id": 1,
  "word": "サンプル",
  "reading": "サンプル",
  "category": "ニュース",
  "status": "active",
  "notes": "備考",
  "updated_at": "2026-07-12T12:00:00Z"
}
```

#### エラーケース

| 条件 | ステータス | 内容 |
|------|-----------|------|
| 同一 `word` + `reading` が既存 | 409 | `{"detail": "Dictionary entry already exists"}` |
| スキーマバリデーション（必須フィールド欠落、`max_length` 超過、型不正） | 422 | Pydantic エラー形式（配列 detail） |

---

### 2.4 更新

| 項目 | 内容 |
|------|------|
| メソッド | PUT |
| パス | `/admin/dictionary/{id}` |
| 認証 | 要 |
| 概要 | 指定したIDの辞書エントリを更新する |

#### パスパラメータ

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `id` | integer | 必須 | 辞書エントリのID |

#### リクエストボディ

```json
{
  "word": "サンプル（更新後）",
  "reading": "サンプル",
  "category": "テクノロジー",
  "notes": "更新後の備考"
}
```

| フィールド | 型 | 必須 | 制約 | 説明 |
|-----------|-----|------|------|------|
| `word` | string | 必須 | 1〜100文字 | 単語（表層形） |
| `reading` | string | 必須 | 1〜200文字 | 読み |
| `category` | string | 必須 | 1〜100文字 | カテゴリ |
| `notes` | string | 任意 | 最大500文字 | 備考 |

#### レスポンス（成功時: 200）

```json
{
  "id": 1,
  "word": "サンプル（更新後）",
  "reading": "サンプル",
  "category": "テクノロジー",
  "status": "active",
  "notes": "更新後の備考",
  "updated_at": "2026-07-12T13:00:00Z"
}
```

#### エラーケース

| 条件 | ステータス | 内容 |
|------|-----------|------|
| 存在しないID | 404 | `{"detail": "Dictionary entry not found"}` |
| 同一 `word` + `reading` が別エントリに存在 | 409 | `{"detail": "Dictionary entry already exists"}` |
| スキーマバリデーション（必須フィールド欠落、`max_length` 超過、型不正） | 422 | Pydantic エラー形式（配列 detail） |

---

### 2.5 状態切替

| 項目 | 内容 |
|------|------|
| メソッド | PATCH |
| パス | `/admin/dictionary/{id}/status` |
| 認証 | 要 |
| 概要 | 辞書エントリの有効/無効状態を切り替える（論理削除相当） |

#### パスパラメータ

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `id` | integer | 必須 | 辞書エントリのID |

#### リクエストボディ

```json
{
  "status": "inactive"
}
```

| フィールド | 型 | 必須 | 制約 | 説明 |
|-----------|-----|------|------|------|
| `status` | string | 必須 | `active` または `inactive` | 設定する状態 |

#### レスポンス（成功時: 200）

```json
{
  "id": 1,
  "word": "サンプル",
  "reading": "サンプル",
  "category": "ニュース",
  "status": "inactive",
  "notes": "備考",
  "updated_at": "2026-07-12T14:00:00Z"
}
```

#### エラーケース

| 条件 | ステータス | 内容 |
|------|-----------|------|
| 存在しないID | 404 | `{"detail": "Dictionary entry not found"}` |
| `status` が `active` / `inactive` 以外 | 422 | Pydantic スキーマバリデーション（配列 detail） |

> **注**: 物理削除（DELETE）は初回対象外（BEE-408 の方針）。状態切替による論理削除で代替する。

---

## 3. レスポンス項目一覧

全エンドポイント共通のレスポンス項目:

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `id` | integer | 常に含まれる | 辞書エントリの一意識別子 |
| `word` | string | 常に含まれる | 単語（表層形） |
| `reading` | string | 常に含まれる | 読み |
| `category` | string | 常に含まれる | カテゴリ |
| `status` | string | 常に含まれる | 状態: `active` または `inactive` |
| `notes` | string | なしの場合は空文字 | 備考 |
| `updated_at` | string (ISO 8601) | 常に含まれる | 最終更新日時（UTC） |

> **`updated_by` について**: 初回対象外（変更履歴は初回対象外とする BEE-408 の方針による）。実装上、最終更新者のみを返す場合はフィールドとして追加可能だが、その場合は変更履歴を保存するものではなく「現在のエントリの最終更新者」であることを明記すること。

---

## 4. ページネーション仕様

`GET /admin/dictionary` のページネーションは既存API（`episodes.py`）と同一方式とする。

| 項目 | 仕様 |
|------|------|
| パラメータ | `limit`（任意, ge=1）, `offset`（任意, デフォルト0, ge=0） |
| limit 未指定時 | 配列を返す（全件返却、従来動作に準拠） |
| limit 指定時 | `{"items": [...], "total": N, "has_next": bool, "stats": {...}}` 形式 |
| `total` | フィルタ適用後の総件数 |
| `has_next` | 次ページが存在するか（`offset + limit < total`） |
| `stats` | limit指定時のみ付与。フィルタ（search/category）非依存の全件実数。`{total, active, inactive}` |

> **重要**: `limit` 未指定時は配列を返すため、`stats` も `total` も含まれない。BEE-420 は必ず `limit` を指定すること。`stats` の数値は初期表示時に1回取得し、エントリ追加/削除後に必要に応じて再取得する。

---

## 5. リレーション・画面接続メモ

- **一覧画面**: `GET /admin/dictionary` — 検索・カテゴリ・状態フィルタ、ページネーション
- **追加画面**: `POST /admin/dictionary` — Create form
- **編集画面**: `PUT /admin/dictionary/{id}` — Edit form
- **状態切替UI**: `PATCH /admin/dictionary/{id}/status` — トグルスイッチ or ボタン
- **統計表示**: 一覧レスポンスの `stats: {total, active, inactive}` を利用。フィルタ非依存の全件実数で、統計バー（全件数・有効数・無効数）の表示に使う。初期表示時に1回取得し、エントリ追加/削除後に必要に応じて再取得する。`total`（フィルタ適用後）とは別値であることに注意
- **生成時の辞書適用**: `status: inactive` のエントリは生成（番組台本生成・解説生成）の辞書適用対象から除外する。
  - 一覧APIは常に全状態を返却可能（`status` クエリでフィルタ）。`inactive` 除外は生成ロジック側の責務である。
- **削除ボタン**: 初回画面要件に含めない（BEE-408 論理削除方針による）

---

## 6. テスト観点

| カテゴリ | 観点 |
|----------|------|
| 認証 | 認証なし（Authorization ヘッダなし）→ 401、不正Bearer（誤ったトークン）→ 401、正しいBearer → 200/201 |
| 一覧 | 空結果（DBに0件）、全件取得（limit未指定）、`limit` + `offset` ページネーション正常動作 |
| ページ境界 | `limit=1` + `offset=0`／`limit=1` + `offset=超出`（空リストが返ること）、`limit=0` または負値 → 422 |
| フィルタ | `search` 単体、`category` 単体、`status` 単体（active/inactive 各々）、複合フィルタ（`search` + `category` + `status` の組み合わせ） |
| 空結果フィルタ | 存在しない `search` 語、存在しない `category`、該当なしの複合フィルタ → `{items:[], total:0, has_next:false}` |
| 作成 | 正常作成 → 201、同一 `word` + `reading` の重複登録 → 409、必須フィールド欠落 → 422、文字数超過（word 101文字等）→ 422 |
| 更新 | 正常更新 → 200、存在しないID → 404、重複更新（別エントリと同一 word+reading）→ 409、スキーマバリデーション → 422 |
| 状態切替 | `active` → `inactive` → 200、`inactive` → `active` → 200、存在しないID → 404、不正値（`status: "invalid"`）→ 422、同一状態への切替 → 200（冪等） |
| 生成連携 | `status: inactive` のエントリが生成（台本生成・解説生成）の辞書適用対象から除外されること。inactive→active に戻した後に生成対象に含まれること。 |

---

## 7. 関連Issueとの対応

| Issue | 関連 | 備考 |
|-------|------|------|
| BEE-408 | 論理削除方針の根拠 | DELETE エンドポイントを初回対象外とする根拠、変更履歴初回対象外 |
| BEE-409 | QA テスト観点 | 本契約書に基づくテスト設計 |
| BEE-410 | 実装依存（辞書機能全体統括） | 本契約書確定後、BEE-410 完了を待って BEE-412 実装着手 |
| BEE-412 | 実装元 | 本契約書に基づきバックエンド実装を担当 |
| BEE-420 | 画面実装 | 本契約書のエンドポイントに接続 |
| BEE-421 | 統合（Close予定） | BEE-412 に統合、API契約は本ドキュメントで代替 |
| BEE-413 | 確定レビュー | 本契約書レビュー後、実装レビューへ |

---

## 8. レビュー履歴

| 日時 | レビューア | 区分 | 内容 |
|------|-----------|------|------|
| 2026-07-12 | 藤崎 奈緒 | 事前レビュー | must: DELETE 除外、limit/offset + `{items,total,has_next}`、`updated_by` 注釈、422エラー対応； should: `/api` prefix 統一、認証前提条件明記 |
| 2026-07-12 | 白石 綾乃 | 統合確定 | 案A採用を決定 |
| 2026-07-12 | 藤崎 奈緒 | 確定レビュー(1回目) | must: limit未指定時の形式統一（配列 vs {items,total,has_next}）、入力制限不整合、stats未定義； should: 400/422境界不明瞭 |
| 2026-07-12 | 長谷川 優香 | 修正案提示 | 4件の修正案を提示（limit未指定=配列、word:100/reading:200/notes:500、stats追加、400/422境界明確化） |
| 2026-07-12 | 白石 綾乃 | 修正指示 | 上記4件の契約書反映を指示 |
