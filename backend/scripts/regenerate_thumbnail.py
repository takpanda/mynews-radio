#!/usr/bin/env python3
"""Regenerate one episode thumbnail without rerunning episode generation or notifications."""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.thumbnail_service import generate_thumbnail  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode_id", type=int, help="対象エピソードID")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="既存のサムネイルがある場合に上書きする",
    )
    args = parser.parse_args()
    try:
        path = generate_thumbnail(args.episode_id, overwrite=args.overwrite)
    except Exception as exc:
        print(f"サムネイル生成に失敗しました: {exc}", file=sys.stderr)
        return 1
    print(f"サムネイルを保存しました: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
