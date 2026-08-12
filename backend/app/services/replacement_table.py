import logging
import re

from app.db.connection import get_db_connection
from app.services.text_normalization import normalize_dictionary_surface, normalize_text_with_span_map

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

    照合は Stage 2（AIVIS辞書同期）と同じ正規化規則（NFKC + 3桁区切りカンマ除去）を
    文章側にも適用したうえで行うため、カンマ有無・全角半角の表記ゆれを吸収できる。
    正規化後に同じ照合キーとなる辞書項目が複数ある場合は、読みの競合を避けるため
    どちらの読みも適用しない（対象の表記をログへ出力する）。

    既存エピソードの spoken_text は変更されず、音声合成時の新規生成にのみ影響する。
    表示用・保存用の元テキスト、DB の辞書表記そのものは変更しない。
    """
    _, entries = get_active_entries()
    if not entries or not text:
        return text

    entries_by_key: dict[str, list[dict[str, str]]] = {}
    for e in entries:
        key = normalize_dictionary_surface(e["surface"])
        entries_by_key.setdefault(key, []).append(e)

    reading_by_key: dict[str, str] = {}
    for key, group in entries_by_key.items():
        if len(group) > 1:
            logger.warning(
                "辞書照合キーが競合したため置換を適用しません: key=%r surfaces=%r",
                key, [g["surface"] for g in group],
            )
            continue
        reading_by_key[key] = group[0]["reading"]

    if not reading_by_key:
        return text

    normalized_text, spans = normalize_text_with_span_map(text)

    _patterns = sorted(reading_by_key.keys(), key=len, reverse=True)
    _pattern = re.compile("|".join(re.escape(k) for k in _patterns))

    result_parts: list[str] = []
    last_end = 0
    for m in _pattern.finditer(normalized_text):
        orig_start = spans[m.start()][0]
        orig_end = spans[m.end() - 1][1]
        result_parts.append(text[last_end:orig_start])
        result_parts.append(reading_by_key[m.group(0)])
        last_end = orig_end
    result_parts.append(text[last_end:])

    return "".join(result_parts)
