# 辞書機能 エラーパターン整理と対応方針

> BEE-415: 辞書CRUD操作・読み替え適用処理における全エラーパターンの文書化
> 作成日: 2026-07-12

---

## 1. 共通方針

### 1.1 エラーレスポンス形式

既存API（`episodes.py`, `generate.py`）は FastAPI 標準の `HTTPException` を使用し、`{"detail": "<メッセージ>"}` 形式でエラーを返している。辞書APIもこれに統一する。

```json
{"detail": "<エラーメッセージ>"}
```

**エラーコード（`error_code`）の採用判断**: 現時点では採用しない。

- 既存APIでエラーコードを使用する例がなく、単一プロジェクト内で統一が取れている
- フロントエンドがエラーコードに依存する設計になっていない
- エラーコード導入は全APIへの波及・フロントエンド側の対応が必要で、本Issueの対象外
- 将来的に `error_code` が必要になった場合も、本ドキュメントの各パターンに error_code を割り当てることは容易

### 1.2 使用するHTTPステータスコード一覧

| ステータス | 用途 | 該当パターン |
|-----------|------|-------------|
| 400 Bad Request | 業務バリデーションエラー（Pydantic自動検出外） | 更新対象の整合性エラー、リクエスト矛盾 |
| 401 Unauthorized | APIキー認証失敗 | 認証なし / キー不一致 |
| 404 Not Found | リソース未発見 | 存在しないID参照 |
| 409 Conflict | リソース競合 / 重複 | ユニーク制約違反 |
| 422 Unprocessable Entity | Pydanticスキーマバリデーション | 必須フィールド欠落、型不正、文字数超過、enum範囲外 |
| 500 Internal Server Error | DBエラー等の予期しないサーバ障害 | DB接続失敗、SQL実行エラー |

### 1.3 エラー種別の分類

エラーパターンを以下の4カテゴリに分類して整理する:

1. **スキーマバリデーションエラー** — Pydanticが自動検出（422）
2. **業務バリデーションエラー** — アプリケーションロジックで検出（400/404/409）
3. **DBエラー** — データベースレベルの障害（500）
4. **認証エラー** — APIキー認証（401）

---

## 2. 現状の不整合・確認事項

### 2.1 スキーマと契約書の不整合

| 項目 | schema.sql | api-dictionary-contract.md | 判断 |
|------|-----------|---------------------------|------|
| ユニーク制約 | `surface` 単体に `UNIQUE` | `word` + `reading` の組み合わせで一意 | **契約書に合わせる必要あり**。`surface`単体のUNIQUE制約では、同じ単語を異なる読みで登録できず、辞書としての柔軟性が損なわれる。スキーマ修正が必要（`UNIQUE(surface, reading)` に変更）。 |
| カラム名 | `surface`, `enabled` | `word`, `status` | 契約書の命名（`word`, `status`）に合わせるか、API層でマッピングする。本Issueは実装作業ではないため、スキーマ変更は設計判断として留める。 |
| カテゴリの制約 | `TEXT DEFAULT ''`（任意） | 1〜100文字で必須 | 契約書の制約を優先（API入力検証で担保） |

### 2.2 大文字小文字の扱い

現状の `replacement_table.py` は **大文字小文字を区別する**（`re.escape` → `re.compile` で `re.IGNORECASE` なし）。

**判断**: 辞書DB管理APIでも現状に合わせ、**大文字小文字を区別する（case-sensitive）** とする。英単語の読み替えは "Google" と "google" を別の読みに設定できるようにするため、case-sensitive で統一する。ただし、現状の辞書初期シードデータ（`main.py` の seed 処理）はすべて大文字始まりの英単語であり、生成時の `apply_replacements` が case-sensitive であることを考慮し、生成時の適用処理についても検討が必要（セクション5参照）。

### 2.3 マッチング方式

現状の `replacement_table.py` は正規表現の `|`（OR）によるマッチングを使用しており、**単語境界（`\b`）や文字列アンカー（`^`/`$`）を設定していない**。そのため、辞書エントリのキーワードが他の単語の部分文字列として現れた場合も置換が発生する（例："fooGooglebar" 内の "Google" も置換される）。したがって、現状は **部分一致（正規表現 OR による最長一致）** の動作となっている。

**判断**: 辞書DB連携後も現状の実装を踏襲する場合、部分一致によるリスクを受け入れることになる。不自然な読み替えを防ぎたい場合は、実装を **単語境界付きの完全一致**（`re.compile(r"\b(?:" + ... + r")\b")`）に変更する必要があるが、その場合「GitHub」の "Git" 部分が置換されなくなるなどトレードオフが存在する。本Issueでは以下の方針とする。

- **実装方針**: 部分一致の現状を維持する（単語境界なし）
- **理由**: 英単語の読み替え辞書（製品名・サービス名）において、単語境界を設けると「preGoogle」や「GooglePost」のように他の単語と連結している場合に置換されなくなるなど、辞書エントリが期待通りに機能しないケースが生じるため。単語境界ありに変更する場合は、全テストケースの見直しが必要。
- **大文字小文字の区別**: 現状維持（case-sensitive）

---

## 3. 辞書登録（POST /admin/dictionary）のエラーパターン

### 3.1 パターン一覧

| # | エラーパターン | カテゴリ | HTTP Status | レスポンス例 | 備考 |
|---|---------------|---------|------------|-------------|------|
| E-C-01 | APIキー未指定 / 不一致 | 認証 | 401 | `{"detail": "Invalid or missing API key"}` | `verify_api_key` 共通依存。既存と同一。 |
| E-C-02 | 必須フィールド欠落（`word`, `reading`, `category` のいずれか） | スキーマバリデーション | 422 | `{"detail": [{"loc": ["body", "word"], "msg": "field required", "type": "value_error.missing"}]}` | Pydantic自動生成。必須3フィールドの各欠落パターン。 |
| E-C-03 | `word` 文字数超過（101文字以上） | スキーマバリデーション | 422 | `{"detail": [{"loc": ["body", "word"], "msg": "ensure this value has at most 100 characters", "type": "value_error.any_str.max_length"}]}` | Pydantic自動生成。制約は契約書に基づく。 |
| E-C-04 | `reading` 文字数超過（201文字以上） | スキーマバリデーション | 422 | `{"detail": [{"loc": ["body", "reading"], "msg": "ensure this value has at most 200 characters", "type": "value_error.any_str.max_length"}]}` | Pydantic自動生成。 |
| E-C-05 | `category` 文字数超過（101文字以上） | スキーマバリデーション | 422 | `{"detail": [{"loc": ["body", "category"], "msg": "ensure this value has at most 100 characters", "type": "value_error.any_str.max_length"}]}` | Pydantic自動生成。 |
| E-C-06 | `notes` 文字数超過（501文字以上） | スキーマバリデーション | 422 | `{"detail": [{"loc": ["body", "notes"], "msg": "ensure this value has at most 500 characters", "type": "value_error.any_str.max_length"}]}` | Pydantic自動生成。`notes` は任意フィールド。 |
| E-C-07 | 型不正（数値が渡される等） | スキーマバリデーション | 422 | `{"detail": [{"loc": ["body", "word"], "msg": "str type expected", "type": "type_error.str"}]}` | Pydantic自動生成。 |
| E-C-08 | 同一 `word` + `reading` の重複登録 | 業務バリデーション | 409 | `{"detail": "Dictionary entry already exists"}` | 契約書ベース。スキーマ変更後に `UNIQUE(surface, reading)` 制約でDBレベルでも担保。 |
| E-C-09 | 同一 `word` のみ既存（異なる `reading`） | 業務バリデーション | (許可) | 正常作成 (201) | 同じ単語でも異なる読みなら別エントリとして許可。例：「東京」（とうきょう）と「東京」（とうけい）。 |
| E-C-10 | DB接続エラー | DBエラー | 500 | `{"detail": "Internal server error"}` | コネクション取得失敗、トランザクション障害。既存APIはDBエラー時のハンドラを未定義。追加議論が必要。 |
| E-C-11 | DBユニーク制約違反（SQLiteの `UNIQUE constraint failed`） | DBエラー | 500 または 409 | `{"detail": "Internal server error"}` または `{"detail": "Dictionary entry already exists"}` | 業務ロジックで事前検出するため、通常は発生しない。例外が漏れた場合のフォールバックとして500でもよいが、本ドキュメントでは**409でハンドリングするのが望ましい**と提言する。 |
| E-C-12 | `word` が空文字 | スキーマバリデーション | 422 | `{"detail": [{"loc": ["body", "word"], "msg": "ensure this value has at least 1 character", "type": "value_error.any_str.min_length"}]}` | Pydantic自動生成。`min_length=1` の指定が必要。 |
| E-C-13 | `reading` が空文字 | スキーマバリデーション | 422 | `{"detail": [{"loc": ["body", "reading"], "msg": "ensure this value has at least 1 character", "type": "value_error.any_str.min_length"}]}` | Pydantic自動生成。`min_length=1` の指定が必要。 |
| E-C-14 | `category` が空文字 | スキーマバリデーション | 422 | `{"detail": [{"loc": ["body", "category"], "msg": "ensure this value has at least 1 character", "type": "value_error.any_str.min_length"}]}` | Pydantic自動生成。`min_length=1` の指定が必要。 |

### 3.2 対応方針サマリ

- 認証エラー: `Depends(verify_api_key)` で一貫対応
- スキーマバリデーション: Pydanticモデルの `Field(min_length=1, max_length=...)` で自動検出（422）
- 重複チェック: サービス層で事前SELECTによる存在確認を行い、存在する場合は 409 Conflict
- DBエラー: FastAPIのグローバル例外ハンドラでキャッチし500を返す（後述のセクション8参照）

---

## 4. 辞書更新（PUT /admin/dictionary/{id}）のエラーパターン

### 4.1 パターン一覧

| # | エラーパターン | カテゴリ | HTTP Status | レスポンス例 | 備考 |
|---|---------------|---------|------------|-------------|------|
| E-U-01 | APIキー未指定 / 不一致 | 認証 | 401 | `{"detail": "Invalid or missing API key"}` | 共通。 |
| E-U-02 | 存在しないIDへの更新 | 業務バリデーション | 404 | `{"detail": "Dictionary entry not found"}` | 該当IDのレコードがDBに存在しない。 |
| E-U-03 | 必須フィールド欠落 | スキーマバリデーション | 422 | (E-C-02と同様) | 作成と同一バリデーション。 |
| E-U-04 | 文字数超過（全フィールド） | スキーマバリデーション | 422 | (E-C-03〜E-C-06と同様) | 作成と同一制約。 |
| E-U-05 | 型不正 | スキーマバリデーション | 422 | (E-C-07と同様) | 作成と同一。 |
| E-U-06 | 更新後の `word` + `reading` が別エントリと重複 | 業務バリデーション | 409 | `{"detail": "Dictionary entry already exists"}` | 自分自身（同一ID）への更新は許可。同一IDの場合は重複カウントしない。 |
| E-U-07 | 更新内容が現在値と完全同一 | (正常) | 200 | 正常に更新される | 冪等に動作。更新日時は更新される（設計判断）。 |
| E-U-08 | IDが負数 or 0 | パスパラメータバリデーション | 422 | `{"detail": [{"loc": ["path", "id"], "msg": "ensure this value is greater than or equal to 1", "type": "value_error"}]}` | FastAPIの `Path(ge=1)` で自動検出。 |
| E-U-09 | DB接続エラー | DBエラー | 500 | `{"detail": "Internal server error"}` | |
| E-U-10 | DBユニーク制約違反 | DBエラー | (409推奨) | 業務ロジックで事前検出するため通常は発生しない。フォールバックとして409または500。 |

### 4.2 対応方針サマリ

- 404: サービス層で該当IDの存在確認 → 存在しない場合は `HTTPException(404)`
- 409: 重複チェックは「同一IDを除外した」条件でSELECT → 存在する場合は `HTTPException(409)`
- 同一内容の更新: 冪等に200で成功（更新日時は更新する。不要なら条件分岐も可）

---

## 5. 辞書削除（状態切替 PATCH /admin/dictionary/{id}/status）のエラーパターン

### 5.1 パターン一覧

| # | エラーパターン | カテゴリ | HTTP Status | レスポンス例 | 備考 |
|---|---------------|---------|------------|-------------|------|
| E-D-01 | APIキー未指定 / 不一致 | 認証 | 401 | `{"detail": "Invalid or missing API key"}` | 共通。 |
| E-D-02 | 存在しないIDへの状態切替 | 業務バリデーション | 404 | `{"detail": "Dictionary entry not found"}` | |
| E-D-03 | `status` の値が `active` / `inactive` 以外 | スキーマバリデーション | 422 | Pydantic自動生成（enumバリデーション） | Pydanticの `Enum` / `Literal` で自動検出。 |
| E-D-04 | 同一状態への切替（冪等） | (正常) | 200 | 通常更新。既存と同じ状態で更新される。 | 冪等動作として許可。更新日時は更新されるか否かは設計判断。 |
| E-D-05 | IDが負数 or 0 | パスパラメータバリデーション | 422 | (E-U-08と同様) | |
| E-D-06 | DB接続エラー | DBエラー | 500 | `{"detail": "Internal server error"}` | |

### 5.2 物理削除（DELETE）について

契約書通り、物理削除は初回対象外（BEE-408 論理削除方針による）。DELETEエンドポイントのエラーパターンは本ドキュメントでは対象外とするが、将来的に実装する場合のエラーパターンを「参考」として Appendix A に記載する。

### 5.3 対応方針サマリ

- 状態切替は `PATCH /admin/dictionary/{id}/status` のみ
- `status` フィールドは `Literal["active", "inactive"]` で型定義 → Pydanticが422を自動生成
- 存在確認 → なければ404

---

## 6. 辞書取得（GET）のエラーパターン

### 6.1 一覧取得（GET /admin/dictionary）

| # | エラーパターン | カテゴリ | HTTP Status | レスポンス | 備考 |
|---|---------------|---------|------------|-----------|------|
| E-L-01 | APIキー未指定 / 不一致 | 認証 | 401 | `{"detail": "Invalid or missing API key"}` | |
| E-L-02 | 空データ（DBに1件もない） | (正常) | 200 | `[]`（limit未指定時）または `{"items": [], "total": 0, "has_next": false, "stats": {"total": 0, "active": 0, "inactive": 0}}`（limit指定時） | 空配列または空データを返す。エラーではない。 |
| E-L-03 | フィルタ該当なし（検索結果0件） | (正常) | 200 | `[]` または `{"items": [], "total": 0, "has_next": false}` | stats はフィルタ非依存の全件実数。 |
| E-L-04 | `limit` に負数・0 | スキーマバリデーション | 422 | Pydantic自動生成（`ge=1`） | |
| E-L-05 | `offset` に負数 | スキーマバリデーション | 422 | Pydantic自動生成（`ge=0`） | |
| E-L-06 | DB接続エラー | DBエラー | 500 | `{"detail": "Internal server error"}` | |
| E-L-07 | クエリパラメータに不正な値（`limit=abc`） | スキーマバリデーション | 422 | Pydantic自動生成（型バリデーション） | FastAPI自動検出。 |

### 6.2 詳細取得（GET /admin/dictionary/{id}）

| # | エラーパターン | カテゴリ | HTTP Status | レスポンス例 | 備考 |
|---|---------------|---------|------------|-------------|------|
| E-G-01 | APIキー未指定 / 不一致 | 認証 | 401 | `{"detail": "Invalid or missing API key"}` | |
| E-G-02 | 存在しないID | 業務バリデーション | 404 | `{"detail": "Dictionary entry not found"}` | |
| E-G-03 | IDが負数 or 0 | パスパラメータバリデーション | 422 | (E-U-08と同様) | `Path(ge=1)` |
| E-G-04 | DB接続エラー | DBエラー | 500 | `{"detail": "Internal server error"}` | |

### 6.3 対応方針サマリ

- 一覧取得: 空データ/フィルタ該当なしはエラーではなく正常。stats は常にフィルタ非依存の全件実数。
- 詳細取得: 存在確認 → なければ404。作成/更新と同一のエラーメッセージを使用。

---

## 7. 辞書読み替え適用処理（生成時）のエラーパターン

### 7.1 現状の読み替え処理

現在の `synthesize_voicevox.py` の `apply_replacements()` は、静的な `REPLACEMENT_TABLE`（`replacement_table.py`）を使用している。DBの `dictionary_entries` テーブルは参照していない。

将来的にDB辞書を読み込む改修を行う場合のエラーパターンも併記する。

### 7.2 パターン一覧

| # | エラーパターン | 現状の動作 | 将来の動作（DB辞書連携後） | 対応方針 |
|---|---------------|-----------|--------------------------|---------|
| E-A-01 | 辞書未準備（DBにエントリが0件） | 静的辞書があるため問題なし。空のテキストには空文字を返す。 | DB辞書が0件の場合、置換なしで元テキストがそのまま使われる。 | 空辞書状態は正常。`apply_replacements` は置換なしで元のテキストを返す。エラーにはしない。 |
| E-A-02 | 無効エントリ（`enabled=0` / `status=inactive`）の扱い | 静的辞書は全エントリ有効。 | `enabled=0` または `status=inactive` のエントリは読み替え対象から除外する。 | 生成時の辞書適用処理で `enabled=1` (status=active) のエントリのみフィルタする。 |
| E-A-03 | 大文字小文字の扱い | 大文字小文字を区別する（case-sensitive） | 現状維持。大文字小文字を区別する。 | ただし、原稿テキストが「google」と小文字で書かれていても大文字「Google」にマッチしない問題がある。必要に応じて re.IGNORECASE の導入を検討するが、本Issueでは現状維持を前提とする。 |
| E-A-04 | 部分一致による不自然な置換 | 部分一致（単語境界なしの正規表現OR最長一致）。例：`fooGooglebar` → `fooグーグルbar`（"Google" が部分文字列としてマッチ） | 現状維持。部分一致（単語境界なし）を継続。 | 単語境界の導入はトレードオフがある（「A Google」は置換されるが「preGoogle」や「GooglePost」のように連結語では置換されなくなる等）。本Issueでは現状維持とする。意図しない部分一致が問題になる場合は、別Issueでの対応を推奨。 |
| E-A-05 | 辞書エントリが大量になった場合の性能 | 静的辞書（約20エントリ）で問題なし。 | エントリ数が1000〜10000になった場合、正規表現のコンパイル・実行に時間がかかる可能性がある。 | DB辞書連携時は、起動時に `enabled=1` の全エントリをメモリに読み込んで正規表現を構築する方式を検討する。リクエスト毎にDBクエリを発行する方式は避ける。 |
| E-A-06 | 包含関係にあるキーの置換順序 | `re.Pattern.sub()` は一回置換を行った結果を再走査しない。また、パターンは長いキー順（降順）にソートされている。例：`Git|GitLab` では `GitLab` が先にマッチし、`GitLab → ギットラブ` が正しく置換される。`Git` 単体は `Git → ギット` となる。 | 現状維持。一回置換・最長一致を継続。 | `re.Pattern.sub()` の仕様上、一度置換されたテキストが再度置換されることはない。最長一致のソートロジックにより、包含関係にあるキーは長い方が優先される。 |
| E-A-07 | TTSエンジンの音声合成処理での置換テキスト異常 | 置換後のテキストが空文字になる場合、`synthesize_line` に空文字が渡される可能性がある。 | 静的辞書に空文字の読みはないためリスク低。ただし、管理画面から空文字の `reading` が登録される可能性はPydanticの `min_length=1` で防止する。 | APIのスキーマバリデーションで `reading` の `min_length=1` を設定する。これにより空文字の辞書エントリはそもそも登録できない。 |
| E-A-08 | 特殊文字・エスケープの問題 | `re.escape()` で特殊文字をエスケープしている。 | 現状維持。辞書エントリの `surface` に正規表現の特殊文字（`.`, `*`, `+`, `?`, `(`, `)`, `[`, `]`, `{`, `}`, `\\`, `|`, `^`, `$`）が含まれていても安全に動作する。 | DB辞書連携後も `re.escape()` を維持する。 |
| E-A-09 | 置換後テキストがTTSエンジンで発声不能 | システム側では検出できない。TTSエンジン側の問題。 | 現状と同じ。 | 対象外（TTSエンジン側のエラー処理）。 |
| E-A-10 | 辞書エントリの文字コード問題 | Python内部はUnicodeで一貫。 | 現状維持。DB（SQLite）もUTF-8で保存。 | 問題なし。 |
| E-A-11 | 原稿テキストに辞書エントリの `surface` が含まれない場合 | 置換なしで元テキストを返す。 | 同上。 | 正常動作。エラーではない。 |
| E-A-12 | 原稿テキストが `None` | `line.get("text", "")` はキーが存在しない場合のみ `""` を返す。キーが存在して値が `None` の場合は `None` が返り、`apply_replacements(None)` で TypeError が発生する。 | `original_text = line.get("text", "") or ""` に変更するか、`apply_replacements` 側で None をハンドリングする必要がある。 | **対応必須**。None を空文字に正規化（`or ""`）することを `synthesize_voicevox.py` の該当行に追加する。正規化後は通常通り後続処理を継続する。ログに警告を出力して記録を残すことを推奨。 |
| E-A-14 | 原稿テキストが空文字 | `original_text = line.get("text", "")` で空文字が返る。`apply_replacements("")` は `""` を返す。 | 同上。 | 正常動作。エラーではない。空文字のテキストはそのまま TTS エンジンに送られるが、空文字の音声合成は TTS エンジン側でハンドリングされる。 |
| E-A-13 | 辞書読み込みに失敗（DB接続障害） | 静的辞書のため発生しない。 | DB辞書連携後に発生しうる。 | 起動時の辞書読み込みでDB接続障害が発生した場合、空の辞書としてフォールバックするか、アプリケーションの起動を中断するかは設計判断。本Issueでは「空の辞書としてフォールバックし、ログに警告を出力する」を推奨する。 |

### 7.3 対応方針サマリ

- TTSエンジン側のエラー: 対象外
- 辞書未準備: 正常（置換なしでフォールバック）
- 無効エントリ: 生成時の辞書適用でフィルタ（`enabled=1` のみ対象）
- 大文字小文字: 現状は case-sensitive を維持。将来的に `re.IGNORECASE` 導入を検討可
- 大量エントリ: 起動時メモリ読み込み方式を推奨
- 部分一致: 現状維持（単語境界なし）。意図しない置換リスクを許容する。単語境界導入は別Issue。
- None 正規化: `synthesize_voicevox.py` の `original_text = line.get("text", "")` を `original_text = line.get("text", "") or ""` に修正することを推奨（実装タスク）。正規化後は後続処理を継続。ログ警告を出力する。

---

## 8. 既存コードとの整合性

### 8.1 既存APIのエラーハンドリングパターン一覧

| ファイル | ステータス | detail文字列 | 備考 |
|---------|-----------|-------------|------|
| `episodes.py` | 404 | `"Episode not found"` | エピソード未発見 |
| `episodes.py` | 404 | `"Script file not found"` | 台本ファイル未発見 |
| `episodes.py` | 404 | `"Review file not found"` | レビューファイル未発見 |
| `episodes.py` | 404 | `"Article not found"` | 記事未発見 |
| `main.py` | 404 | `"Audio file not found"` | 音声ファイル未発見 |
| `main.py` | 416 | `"Range Not Satisfiable"` | Rangeリクエスト不正 |
| `generate.py` | 401 | `"Invalid or missing API key"` | 認証失敗 |
| `generate.py` | 400 | `"mc_gender must be 'male' or 'female'"` | enumバリデーション |
| `generate.py` | 400 | `"style must be 'solo' or 'dialogue'"` | enumバリデーション |
| `generate.py` | 400 | `"Access to internal network address is not allowed"` | SSRFチェック |
| `generate.py` | 409 | `"Episode for {date} already exists"` | 重複エピソード |
| `main.py` | 429 | `"Rate limit exceeded. Try again later."` | レート制限 |
| Pydantic自動 | 422 | 配列 detail | スキーマバリデーション |

### 8.2 辞書APIのエラーパターンとの整合性マッピング

| 既存APIのパターン | 辞書APIでの対応 | 整合状況 |
|------------------|----------------|---------|
| 401 + `verify_api_key` | 同一関数を流用 | 完全一致 |
| 404 + `"Episode not found"` 形式 | `"Dictionary entry not found"` で統一 | 命名のみ異なる。パターンとして同一 |
| 409 + 重複文字列形式 | `"Dictionary entry already exists"` | 同上 |
| 400 + 業務バリデーション | 辞書APIでは現状該当なし | — |
| 422 + Pydantic自動生成配列 | `Field(min_length=1, max_length=...)` で統一 | 完全一致 |
| 500 + 未定義 | 辞書APIでも未定義 | 今後の課題（8.3節参照） |
| 429 + レート制限 | 辞書APIには未適用（対象外判断） | 対象外 |

### 8.3 DBエラー（500）のグローバルハンドリング検討

現状、プロジェクト全体で DBエラー（`sqlite3.Error`）のグローバル例外ハンドラは定義されていない。`generate.py` の `sqlite3.IntegrityError` は個別にキャッチしている。

**提言**: 本Issueの範囲外だが、グローバル例外ハンドラの追加を将来の課題として提案する。

```python
# main.py に追加（提案）
import sqlite3
from fastapi.responses import JSONResponse

@app.exception_handler(sqlite3.Error)
async def _sqlite_error_handler(request: Request, exc: sqlite3.Error) -> JSONResponse:
    logger.error("Database error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
```

---

## 9. HTTPステータスコード割り当て方針

### 9.1 ステータスコード選定基準

| ステータス | 選定基準 | 例 |
|-----------|---------|-----|
| **400 Bad Request** | クライアントのリクエストが不正だが、Pydanticスキーマでは検出できないもの。辞書APIでは現状該当なし。 | SSRFチェック、業務ルール違反 |
| **401 Unauthorized** | 認証が必須のエンドポイントで、APIキーがない or 不正。 | 全エンドポイント共通 |
| **404 Not Found** | 指定されたリソース（ID）が存在しない。 | GET/PUT/PATCH の存在確認 |
| **409 Conflict** | 作成または更新の結果、リソースの一意性制約に違反する。 | 同一 `word` + `reading` の重複 |
| **422 Unprocessable Entity** | リクエストボディの内容がスキーマ定義に違反している。 | 必須フィールド欠落、文字数超過、型不正 |
| **500 Internal Server Error** | サーバー側の予期しない障害。 | DB接続失敗、予期しない例外 |

### 9.2 400 vs 422 の線引き

**400を使う条件**（辞書APIでは現状該当なし）:
- Pydanticのスキーマバリデーションでは検出できない業務ルール違反
- 例: 「`word` と `reading` が同一の値」を禁止する場合

**422を使う条件**（辞書APIではこれが中心）:
- Pydanticの `Field` 制約（`min_length`, `max_length`, `regex`, `ge` 等）で検出可能なもの
- FastAPIの `Path` / `Query` バリデーションで検出可能なもの

---

## 10. エラーパターン網羅性チェックリスト

### 10.1 辞書登録（POST）: 受入条件カバレッジ

| 受入条件 | 該当パターン | カバー状況 |
|---------|------------|-----------|
| 重複登録エラー | E-C-08 | ✅ |
| 不正フォーマットエラー | E-C-07（型不正） | ✅ |
| 必須フィールド欠落 | E-C-02 | ✅ |
| 文字数超過 | E-C-03〜E-C-06 | ✅ |
| DBエラー | E-C-10, E-C-11 | ✅（対応方針含む） |

### 10.2 辞書更新（PUT）: 受入条件カバレッジ

| 受入条件 | 該当パターン | カバー状況 |
|---------|------------|-----------|
| 存在しないIDの更新禁止 | E-U-02 | ✅ |
| ユニーク制約違反 | E-U-06 | ✅ |

### 10.3 辞書削除（PATCH status）: 受入条件カバレッジ

| 受入条件 | 該当パターン | カバー状況 |
|---------|------------|-----------|
| 存在しないIDの削除 | E-D-02 | ✅ |
| 参照整合性の検討 | (物理削除は対象外) | ✅（論理削除方針との整合性確認済み） |

### 10.4 辞書取得（GET）: 受入条件カバレッジ

| 受入条件 | 該当パターン | カバー状況 |
|---------|------------|-----------|
| 存在しないID | E-G-02 | ✅ |
| 一覧取得の空データ | E-L-02 | ✅ |

### 10.5 読み替え適用（synthesize_voicevox.py）: 受入条件カバレッジ

| 受入条件 | 該当パターン | カバー状況 |
|---------|------------|-----------|
| 辞書未準備時の動作 | E-A-01 | ✅ |
| 無効エントリの扱い | E-A-02 | ✅ |
| 大文字小文字の扱い | E-A-03 | ✅ |

---

## 11. 判断に迷う点・確認事項

### 11.1 スキーマのユニーク制約変更（`surface` 単体 → `surface` + `reading`）

**現状**: `schema.sql` では `surface TEXT NOT NULL UNIQUE` となっており、`surface` 単体でユニーク。
**契約書**: `word` + `reading` の組み合わせで一意と定義。

**判断**: 契約書の定義が正しい（同じ単語でも異なる読み方を許容するのは辞書として自然）。
**影響**: `schema.sql` の `CREATE TABLE dictionary_entries` の `UNIQUE` 制約を以下のように変更する必要がある。

```sql
CREATE TABLE IF NOT EXISTS dictionary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    surface TEXT NOT NULL,
    reading TEXT NOT NULL,
    category TEXT DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(surface, reading)
);
```

**ただし**: これは実装作業（BEE-412）で対応する項目。本Issueでは認識合わせとして文書化する。

### 11.2 大文字小文字の確認

**判断**: case-sensitive を維持。英単語の読み替え用途では、大文字小文字を区別することで細かい制御が可能になる（例：「Google」と「google」を別の読みに設定できる）。

**影響**: 現状の辞書シードデータはすべて大文字始まりの英単語のため、原稿テキストが小文字で記述された場合は置換されない。今後の課題。

### 11.3 マッチング方式の確認

**現状**: 単語境界なしの正規表現 OR による部分一致。例：`fooGooglebar` 内の `Google` も置換される。

**判断**: 現状の部分一致を維持する。単語境界（`\b`）を導入すると「A Google」は置換されるが「preGoogle」や「GooglePost」のように単語が連結している場合は置換されなくなるなど、トレードオフがある。単語境界導入による厳密な完全一致への変更は、別Issueでの対応を推奨する。

### 11.4 エラーレスポンス形式（`error_code` 追加の要否）

**判断**: 現時点では `error_code` を追加しない。既存APIとの統一を優先。

---

## 12. テスト観点

各エラーパターンに対応するテスト観点は、`api-dictionary-contract.md` の「6. テスト観点」に記載済み。本ドキュメントの各パターンと合同書のテスト観点の対応は以下の通り。

| 本ドキュメント | 合同書テスト観点 |
|--------------|----------------|
| E-C-01 / E-U-01 / E-D-01 / E-L-01 / E-G-01 | 認証 |
| E-C-02〜E-C-07, E-C-12〜E-C-14 | 作成・更新のスキーマバリデーション |
| E-C-08, E-U-06 | 作成・更新の重複 |
| E-U-02, E-D-02, E-G-02 | 存在しないID |
| E-L-02, E-L-03 | 空結果 / フィルタ該当なし |
| E-L-04, E-L-05 | ページネーション境界 |
| E-A-01〜E-A-03 | 生成連携 |
| E-A-04 | 部分一致のテスト（例: `fooGooglebar` → `fooグーグルbar`） |
| E-A-06 | 包含キーの置換順序（`GitLab` → `ギットラブ`）、一回置換の再走査なし |
| E-A-12, E-A-14 | `text: null` のケース、空文字のケース |

---

## Appendix A: 物理削除（DELETE）のエラーパターン（参考）

> 本Issueでは対象外。BEE-408の方針により論理削除で代替中。将来的にDELETEエンドポイントを実装する場合の参考として記載する。

| # | エラーパターン | HTTP Status | 備考 |
|---|---------------|------------|------|
| E-DEL-01 | APIキー未指定 / 不一致 | 401 | 共通。 |
| E-DEL-02 | 存在しないIDへの削除 | 404 | |
| E-DEL-03 | 他テーブルから参照されているエントリの削除 | 409 または 500 | 参照整合性。episode_items には紐づかない想定だが、将来的な参照先出現時に考慮が必要。 |
| E-DEL-04 | DB接続エラー | 500 | |
| E-DEL-05 | べき等性（同一IDの2回目削除） | 404 | 2回目は「既に存在しない」ため404。 |

---

## Appendix B: エラーパターン別テスト一覧

| テストケースID | 操作 | 条件 | 期待HTTP Status | 期待detail |
|--------------|------|------|----------------|-----------|
| T-C-01 | POST | 正常作成 | 201 | — |
| T-C-02 | POST | Authorization ヘッダなし | 401 | `"Invalid or missing API key"` |
| T-C-03 | POST | `word` 欠落 | 422 | `field required` (Pydantic) |
| T-C-04 | POST | `reading` 欠落 | 422 | `field required` (Pydantic) |
| T-C-05 | POST | `category` 欠落 | 422 | `field required` (Pydantic) |
| T-C-06 | POST | `word` 101文字 | 422 | `max_length` (Pydantic) |
| T-C-07 | POST | `reading` 201文字 | 422 | `max_length` (Pydantic) |
| T-C-08 | POST | `category` 101文字 | 422 | `max_length` (Pydantic) |
| T-C-09 | POST | `notes` 501文字 | 422 | `max_length` (Pydantic) |
| T-C-10 | POST | `word` 空文字 | 422 | `min_length` (Pydantic) |
| T-C-11 | POST | 同一 `word` + `reading` | 409 | `"Dictionary entry already exists"` |
| T-C-12 | POST | 同一 `word` + 異なる `reading` | 201 | 正常作成 |
| T-U-01 | PUT | 正常更新 | 200 | — |
| T-U-02 | PUT | 存在しないID | 404 | `"Dictionary entry not found"` |
| T-U-03 | PUT | 更新後、別エントリと重複 | 409 | `"Dictionary entry already exists"` |
| T-U-04 | PUT | 自身と同じ値に更新 | 200 | 冪等許可 |
| T-D-01 | PATCH status | `active` → `inactive` | 200 | — |
| T-D-02 | PATCH status | 存在しないID | 404 | `"Dictionary entry not found"` |
| T-D-03 | PATCH status | `status="invalid"` | 422 | Pydantic enum |
| T-D-04 | PATCH status | 同一状態への切替 | 200 | 冪等許可 |
| T-G-01 | GET /{id} | 正常取得 | 200 | — |
| T-G-02 | GET /{id} | 存在しないID | 404 | `"Dictionary entry not found"` |
| T-L-01 | GET / | 空DB | 200 | `[]` または空データ |
| T-L-02 | GET / | フィルタ該当なし | 200 | `{items:[], total:0}` |
| T-A-01 | 読み替え適用 | 部分一致（`fooGooglebar` → `fooグーグルbar`） | 正常 | `"fooグーグルbar"` |
| T-A-02 | 読み替え適用 | `text` フィールドが `null` | 正常 | None を空文字に正規化（`or ""`）し、後続処理を継続。ログ警告を出力。 |
| T-A-03 | 読み替え適用 | `text` フィールドが空文字 | 正常 | 空文字のまま後続処理へ。エラーにしない。 |
| T-A-04 | 読み替え適用 | 包含キー（`GitLab` が `Git` より長い） | 正常 | `GitLab` → `ギットラブ`（`Git` が先にマッチしない） |
| T-A-05 | 読み替え適用 | 一回置換の再走査なし（`A→B`, `B→C` の辞書） | 正常 | `A` → `B`（再走査され `B→C` とはならない） |
