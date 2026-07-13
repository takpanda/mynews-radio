# 不正データ登録時の回復手順

> 対象: BEE-417 / 辞書エントリ (`dictionary_entries`)

## 前提

- 辞書エントリは論理削除（`enabled` フラグによる無効化）で管理する
- 物理削除（DELETE）は行わない
- 既存エピソードの `spoken_text` は辞書変更の影響を受けない
  - `apply_replacements()` は音声合成時にのみ呼ばれる
  - 過去に生成されたエピソードの `spoken_text` は変更されない

## 事前確認

不正データを発見したら、まず以下を確認する。

1. 該当エントリの `id` を特定する（管理画面 or API）
2. 影響を確認する: どのエピソードで使われた可能性があるか
3. 修正後の正しい値（`word`, `reading`, `category`）を用意する

## 回復手順

### 手順1: 不正エントリの無効化

該当エントリを `inactive` に設定することで、以降の音声合成で使用されなくなる。

```http
PATCH /admin/dictionary/{id}/status
Content-Type: application/json
Authorization: Bearer <API_KEY>

{
  "status": "inactive"
}
```

**確認事項:**
- レスポンスの `status` が `inactive` になっていること
- 管理画面の一覧で該当エントリが無効表示になっていること

### 手順2: エントリ情報の修正

無効化したエントリの内容を正しい値に修正する。

```http
PUT /admin/dictionary/{id}
Content-Type: application/json
Authorization: Bearer <API_KEY>

{
  "word": "正しい単語",
  "reading": "正しい読み",
  "category": "正しいカテゴリ",
  "notes": "修正理由のメモ"
}
```

**確認事項:**
- レスポンスの各フィールドが正しい値になっていること
- 204 ではなく 200 が返ること（更新後のエントリ内容が返る）

### 手順3: エントリの再有効化

修正が完了したら、エントリを `active` に戻す。

```http
PATCH /admin/dictionary/{id}/status
Content-Type: application/json
Authorization: Bearer <API_KEY>

{
  "status": "active"
}
```

**確認事項:**
- レスポンスの `status` が `active` になっていること
- 管理画面の一覧で該当エントリが有効表示になっていること

## 回復フロー図

```
不正データ発見
    │
    ▼
┌─────────────────────┐
│ ① エントリを無効化  │  ← PATCH .../status  {"status": "inactive"}
│   (以降、新規生成    │
│    で使用されない)   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ ② エントリを修正    │  ← PUT .../dictionary/{id}  (正しい値)
│   (word/reading/    │
│    category/notes)  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ ③ エントリを再有効化│  ← PATCH .../status  {"status": "active"}
│   (新規生成で      │
│    使用される)      │
└─────────────────────┘
```

## 注意事項

### 既存エピソードへの影響

- 一度生成された `spoken_text` は変更されない
- 無効化したエントリの影響を受けた過去エピソードを修正したい場合は、該当エピソードを再生成する必要がある
- 再生成は `POST /generate` エンドポイントから行う

### データ損失の防止

- 物理削除（DELETE）は行わない
- 誤って無効化した場合は、手順3の再有効化で元に戻せる
- 修正時の値は正しいことを確認してから適用する

### 重複の防止

- 同一 `word` + `reading` の組み合わせは作成時に 409 Conflict で拒否される
- 修正時に別エントリと重複する場合も 409 Conflict で拒否される
- 重複を避けるため、作成前に一覧APIで検索して確認する

## API一覧

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/admin/dictionary` | 一覧取得（search/category/status フィルタ対応） |
| GET | `/admin/dictionary/{id}` | 詳細取得 |
| POST | `/admin/dictionary` | 作成 |
| PUT | `/admin/dictionary/{id}` | 更新 |
| PATCH | `/admin/dictionary/{id}/status` | 状態切替（active/inactive） |

## 補足: 一括操作について

複数のエントリを同時に無効化する必要がある場合は、各エントリに対して個別に PATCH を実行する。一括操作のエンドポイントは今回の実装対象外である。
