import logging
import re

from app.db.connection import get_db_connection

logger = logging.getLogger(__name__)


def get_active_entries() -> tuple[bool, list[dict[str, str]]]:
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


def apply_replacements(text: str) -> str:
    """Display text → spoken text への発音置換を適用する。

    DB の有効な辞書エントリ (is_active=1) のみを使用する。
    DB に有効なエントリがない場合は、入力テキストをそのまま返す。
    呼び出しごとに DB を参照するため、辞書編集は次回合成に即時反映される。

    既存エピソードの spoken_text は変更されず、音声合成時の新規生成にのみ影響する。
    """
    _, entries = get_active_entries()
    if not entries:
        return text

    _map = {e["surface"]: e["reading"] for e in entries}
    _patterns = sorted(
        [(re.escape(k), v) for k, v in _map.items()],
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    _pattern = re.compile("|".join(p[0] for p in _patterns))

    def _replacer(m: re.Match) -> str:
        return _map.get(m.group(0), m.group(0))

    return _pattern.sub(_replacer, text)
