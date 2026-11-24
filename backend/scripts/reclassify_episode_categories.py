#!/usr/bin/env python3
"""公開済み通常回のカテゴリ（episodes.categories）を再選定する。

既定は dry-run（DBへ書き込まない）。--apply 指定時のみ更新する。
既定の対象は categories が空の completed な通常回（解説・ダイジェスト除く）。

使い方:
  python scripts/reclassify_episode_categories.py                  # 対象と結果を表示のみ
  python scripts/reclassify_episode_categories.py --episode-id 12  # 1件のみ
  python scripts/reclassify_episode_categories.py --apply          # 実際に更新
  python scripts/reclassify_episode_categories.py --all --apply    # 既に値がある回も再選定

ロールバック: 実行時に更新前の値を標準出力へ ``id=<n> before=<json>`` で出力する。
ログを保存しておき、``UPDATE episodes SET categories = '<json>' WHERE id = <n>`` で戻せる。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.connection import get_db_connection  # noqa: E402
from app.services.episode_category_service import (  # noqa: E402
    parse_episode_categories,
    select_episode_categories,
)
from app.services.episode_service import EpisodeService  # noqa: E402
from app.services.llm_provider import resolve_pipeline_llm_selection  # noqa: E402


def _targets(episode_id: int | None, include_all: bool) -> list[dict]:
    query = "SELECT * FROM episodes WHERE status = 'completed'"
    params: tuple = ()
    if episode_id is not None:
        query += " AND id = ?"
        params = (episode_id,)
    with get_db_connection() as conn:
        rows = [dict(r) for r in conn.execute(query + " ORDER BY id", params).fetchall()]
    result = []
    for row in rows:
        if row.get("type") in {"commentary", "digest"}:
            continue
        if not include_all and parse_episode_categories(row.get("categories")):
            continue
        result.append(row)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode-id", type=int, help="対象エピソードID（省略時は該当する全件）")
    parser.add_argument("--all", action="store_true", help="categories が空でない回も再選定する")
    parser.add_argument("--apply", action="store_true", help="DBを更新する（省略時は dry-run）")
    args = parser.parse_args()

    selection = resolve_pipeline_llm_selection()
    base = os.environ.get("EPISODES_DIR", "data/episodes")
    service = EpisodeService()
    failed = 0
    targets = _targets(args.episode_id, args.all)
    print(f"対象 {len(targets)} 件 ({'apply' if args.apply else 'dry-run'})")
    for row in targets:
        episode_dir = os.path.join(base, str(row["id"]))
        categories = select_episode_categories(
            os.path.join(episode_dir, "script.json"),
            os.path.join(episode_dir, "summaries.json"),
            llm_provider=selection.content_provider,
            llm_model=selection.content_model,
        )
        before = json.dumps(parse_episode_categories(row.get("categories")), ensure_ascii=False)
        after = json.dumps(categories, ensure_ascii=False)
        print(f"id={row['id']} before={before} after={after}")
        if not categories:
            failed += 1  # 空のまま上書きしない
            continue
        if args.apply:
            service.update_episode_categories(row["id"], categories)
    if failed:
        print(f"選定結果が空で更新しなかった回: {failed} 件", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
