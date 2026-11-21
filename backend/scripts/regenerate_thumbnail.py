#!/usr/bin/env python3
"""Regenerate one episode thumbnail without rerunning episode generation or notifications."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.thumbnail_service import (  # noqa: E402
    generate_thumbnail,
    generate_thumbnail_variants,
)


def _regenerate_variants(episode_id: int | None) -> int:
    root = Path(os.environ.get("EPISODES_DIR", "data/episodes"))
    if episode_id is not None:
        targets = [root / str(episode_id) / "thumbnail.png"]
    else:
        targets = sorted(root.glob("*/thumbnail.png"))
    failed = 0
    for png in targets:
        try:
            generate_thumbnail_variants(png)
            print(f"縮小版を保存しました: {png.parent.name}")
        except Exception as exc:
            failed += 1
            print(f"縮小版の生成に失敗しました: {png.parent.name}: {exc}", file=sys.stderr)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_id", type=int, nargs="?", help="対象エピソードID")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存のサムネイルがある場合に上書きする",
    )
    parser.add_argument(
        "--variants-only",
        action="store_true",
        help="画像は再生成せず、既存の原寸PNGから縮小版WebPのみ生成する"
        "（episode_id 省略時は全エピソード）",
    )
    args = parser.parse_args()
    if args.variants_only:
        return _regenerate_variants(args.episode_id)
    if args.episode_id is None:
        parser.error("episode_id は必須です（--variants-only 時を除く）")
    try:
        path = generate_thumbnail(args.episode_id, overwrite=args.overwrite)
    except Exception as exc:
        print(f"サムネイル生成に失敗しました: {exc}", file=sys.stderr)
        return 1
    print(f"サムネイルを保存しました: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
