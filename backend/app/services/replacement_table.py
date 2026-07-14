import logging
import re
from typing import Dict, List, Optional

from app.db.connection import get_db_connection

logger = logging.getLogger(__name__)

REPLACEMENT_TABLE: Dict[str, str] = {
    # Companies / Products
    "Google": "\u30b0\u30fc\u30b0\u30eb",
    "Microsoft": "\u30de\u30a4\u30af\u30ed\u30bd\u30d5\u30c8",
    "Amazon": "\u30a2\u30de\u30be\u30f3",
    "Apple": "\u30a2\u30c3\u30d7\u30eb",
    "Meta": "\u30e1\u30bf",
    # Cloud
    "Google Cloud": "\u30b0\u30fc\u30b0\u30eb \u30af\u30e9\u30a6\u30c9",
    "AWS": "\u30a8\u30fc\u30b9\u30b7\u30fc\u30ea\u30fc",
    "Azure": "\u30a2\u30b8\u30e5\u30fc\u30eb",
    # Developer tools
    "GitHub": "\u30ae\u30c3\u30c8\u30cf\u30d6",
    "GitLab": "\u30ae\u30c3\u30c8\u30e9\u30d6",
    # Container / Infra
    "Docker": "\u30c9\u30c3\u30ab\u30fc",
    "Kubernetes": "\u30ad\u30e5\u30fc\u30d9\u30eb\u30cd\u30c6\u30a3\u30fc\u30b9",
    "Prometheus": "\u30d7\u30ed\u30df\u30fc\u30c6\u30a5\u30b9",
    "Grafana": "\u30b0\u30e9\u30d5\u30a1\u30ca",
    "Ansible": "\u30a2\u30f3\u30b7\u30db\u30eb",
    "Terraform": "\u30c6\u30e9\u30d5\u30a9\u30fc\u30e0",
    # ML / AI
    "PyTorch": "\u30d1\u30a4\u30c8\u30c3\u30c1",
    "TensorFlow": "\u30c6\u30f3\u30bd\u30fc\u30d5\u30ed\u30fc",
}


def get_active_entries() -> tuple[bool, List[Dict[str, str]]]:
    """辞書テーブルから有効な (is_active=1) エントリを取得する。

    Returns:
        (has_any_entry, active_entries)
        - (True, [{surface, reading}, ...]): DBにエントリが存在し、有効なものも存在する
        - (True, []): DBにエントリは存在するが、全て無効
        - (False, []): DBが空、または接続不可
    """
    try:
        with get_db_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM dictionary_entries").fetchone()[0]
            if total == 0:
                return False, []
            rows = conn.execute(
                "SELECT surface, reading FROM dictionary_entries WHERE is_active = 1"
            ).fetchall()
            return True, [{"surface": r["surface"], "reading": r["reading"]} for r in rows]
    except Exception as exc:
        logger.warning("Failed to fetch active dictionary entries: %s", exc)
        return False, []


def _build_patterns(
    entries: Optional[List[Dict[str, str]]] = None,
) -> tuple[list[tuple[str, str]], "re.Pattern"]:
    """エントリ一覧から正規表現パターンを構築する。"""
    if not entries:
        mapping: list[tuple[str, str]] = []
    else:
        mapping = [(re.escape(e["surface"]), e["reading"]) for e in entries]
    mapping = sorted(mapping, key=lambda pair: len(pair[0]), reverse=True)
    if not mapping:
        pattern = re.compile(r"(?!)")  # 空パターン = 決してマッチしない
    else:
        pattern = re.compile("|".join(p[0] for p in mapping))
    return mapping, pattern


def apply_replacements(text: str) -> str:
    """Display text → spoken text への発音置換を適用する。

    DB の有効な辞書エントリ (is_active=1) を優先して使用する。
    DB が空の場合は REPLACEMENT_TABLE のハードコード値をフォールバックとして使用する。
    DB にエントリは存在するが全て無効 (is_active=0) の場合は、入力テキストをそのまま返す。

    既存エピソードの spoken_text は変更されず、音声合成時の新規生成にのみ影響する。
    """
    has_any_entry, entries = get_active_entries()

    if has_any_entry and not entries:
        return text

    if not has_any_entry:
        entries_data = [
            {"surface": k, "reading": v} for k, v in REPLACEMENT_TABLE.items()
        ]
    else:
        entries_data = entries

    _map = {e["surface"]: e["reading"] for e in entries_data}
    _patterns = sorted(
        [(re.escape(k), v) for k, v in _map.items()],
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    if not _patterns:
        return text
    _pattern = re.compile("|".join(p[0] for p in _patterns))

    def _replacer(m: re.Match) -> str:
        return _map.get(m.group(0), m.group(0))

    return _pattern.sub(_replacer, text)
