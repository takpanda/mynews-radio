"""公開済み通常回のカテゴリ（episodes.categories）を再選定する。

既定は dry-run: DBは読み取り専用で開き、LLM呼び出しログ（llm_call_logs / JSONL）も
書き込まない。--apply 指定時のみ更新する。content LLM が Codex 等（認証状態を更新し得る）の場合、
dry-run は推論せず対象一覧のみ表示する。
対象は公開API（/api/episodes）と同じ判定で公開される通常回（completed かつ音声ファイルあり、
解説・ダイジェスト除く）のうち categories が空の回。台本は公開APIと同じ規則
（ID ディレクトリ→旧形式の日付ディレクトリ）で解決する。

使い方:
  python scripts/reclassify_episode_categories.py                  # 対象と結果を表示のみ
  python scripts/reclassify_episode_categories.py --episode-id 12  # 1件のみ
  python scripts/reclassify_episode_categories.py --apply          # 更新（バックアップ出力あり）
  python scripts/reclassify_episode_categories.py --all --apply    # 既に値がある回も再選定
  python scripts/reclassify_episode_categories.py --restore categories_backup_XXXX.jsonl

ロールバック: --apply は更新直前の生の値（DBに入っていた文字列そのまま）を
``--backup-file``（既定 categories_backup_<日時>.jsonl、1行1件 {"id":..,"categories":..}）へ
更新前に書き出す（既存ファイルは拒否。実行ごとに新規ファイルを指定）。--restore <file> でパラメーター化した UPDATE により元の値へ戻す。
"""

import argparse
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.episodes import _is_public_episode, _resolve_episode_directory  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.connection import _resolve_sqlite_path, get_db_connection  # noqa: E402
from app.services.episode_category_service import (  # noqa: E402
    parse_episode_categories,
    select_episode_categories,
)
from app.services.episode_service import EpisodeService  # noqa: E402
from app.services.llm_provider import resolve_pipeline_llm_selection, validate_provider_model  # noqa: E402


@contextmanager
def _readonly_db_connection():
    """dry-run用。書き込み・PRAGMA変更を一切行わない読み取り専用接続。"""
    path = _resolve_sqlite_path(get_settings().database_url)
    conn = sqlite3.connect(f"{Path(os.path.abspath(path)).as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _targets(episode_id: int | None, include_all: bool, connection=get_db_connection) -> list[dict]:
    query = "SELECT * FROM episodes WHERE status = 'completed'"
    params: tuple = ()
    if episode_id is not None:
        query += " AND id = ?"
        params = (episode_id,)
    with connection() as conn:
        rows = [dict(r) for r in conn.execute(query + " ORDER BY id", params).fetchall()]
    result = []
    for row in rows:
        if row.get("type") in {"commentary", "digest"}:
            continue
        if not _is_public_episode(row):  # 公開APIと同じ判定（音声ファイルの実在まで）
            continue
        if not include_all and parse_episode_categories(row.get("categories")):
            continue
        result.append(row)
    return result


def _fetch_raw_categories(episode_id: int) -> str | None:
    with get_db_connection() as conn:
        row = conn.execute("SELECT categories FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    return row["categories"] if row else None


def _restore(path: str) -> int:
    count = 0
    with open(path, encoding="utf-8") as handle, get_db_connection() as conn:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            conn.execute(
                "UPDATE episodes SET categories = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item["categories"], item["id"]),
            )
            count += 1
    print(f"{count} 件を復元しました")
    return 0


def _select(row: dict, selection) -> list[str]:
    episode_dir = _resolve_episode_directory(row)
    return select_episode_categories(
        os.path.join(episode_dir, "script.json"),
        os.path.join(episode_dir, "summaries.json"),
        llm_provider=selection.content_provider,
        llm_model=selection.content_model,
        episode_id=row["id"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode-id", type=int, help="対象エピソードID（省略時は該当する全件）")
    parser.add_argument("--all", action="store_true", help="categories が空でない回も再選定する")
    parser.add_argument("--apply", action="store_true", help="DBを更新する（省略時は dry-run）")
    parser.add_argument("--backup-file", help="--apply 時の更新前の値の出力先")
    parser.add_argument("--restore", metavar="FILE", help="バックアップファイルから元の値へ戻す")
    args = parser.parse_args()

    if args.restore:
        return _restore(args.restore)

    selection = resolve_pipeline_llm_selection()
    service = EpisodeService()
    failed = 0
    backup_path = args.backup_file or f"categories_backup_{datetime.now():%Y%m%d_%H%M%S_%f}.jsonl"
    if args.apply and os.path.exists(backup_path):
        # 追記すると復元時に古い行が先に適用され、初回更新前へ戻せなくなる。
        print(f"バックアップ先が既に存在します: {backup_path}（実行ごとに新規ファイルを指定してください）", file=sys.stderr)
        return 2

    # Codex等の認証状態を持つクライアントは、初期化・更新でトークン/ロックファイルへ書き込むため
    # dry-run では推論せず、対象の一覧だけを表示する。
    infer_in_dry_run = True
    if not args.apply:
        try:
            infer_in_dry_run = not validate_provider_model(
                selection.content_provider, selection.content_model
            ).responses_api
        except Exception:
            infer_in_dry_run = False

    # dry-run は DB を読み取り専用にし、LLM呼び出しログも書かない。
    patches = []
    if not args.apply:
        patches = [
            patch("app.prompts.service.get_db_connection", _readonly_db_connection),
            patch("app.services.ollama_client._record_llm_call", lambda *a, **k: None),
            patch("app.services.codex_client._record_llm_call", lambda *a, **k: None),
        ]
    for p in patches:
        p.start()
    try:
        targets = _targets(args.episode_id, args.all, _readonly_db_connection if not args.apply else get_db_connection)
        print(f"対象 {len(targets)} 件 ({'apply' if args.apply else 'dry-run'})")
        if not args.apply and not infer_in_dry_run:
            for row in targets:
                print(f"id={row['id']} date={row.get('episode_date')} before={json.dumps(parse_episode_categories(row.get('categories')), ensure_ascii=False)}")
            print(
                "content LLM が認証状態（トークンファイル）を更新し得るため、dry-run では推論しません。"
                "選定結果の確認は --apply 時のバックアップ付き実行で行ってください。"
            )
            return 0
        first_written = False
        for row in targets:
            categories = _select(row, selection)
            before = json.dumps(parse_episode_categories(row.get("categories")), ensure_ascii=False)
            after = json.dumps(categories, ensure_ascii=False)
            print(f"id={row['id']} before={before} after={after}")
            if not categories:
                failed += 1  # 空のまま上書きしない
                continue
            if args.apply:
                raw = _fetch_raw_categories(row["id"])  # 更新直前の生の値
                with open(backup_path, "a" if first_written else "x", encoding="utf-8") as handle:
                    handle.write(json.dumps({"id": row["id"], "categories": raw}, ensure_ascii=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                first_written = True
                service.update_episode_categories(row["id"], categories)
    finally:
        for p in patches:
            p.stop()
    if args.apply:
        print(f"更新前の値を {backup_path} に保存しました")
    if failed:
        print(f"選定結果が空で更新しなかった回: {failed} 件", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
