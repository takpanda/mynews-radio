import logging
import re
from typing import Dict, List, Tuple

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

_REPLACEMENT_PATTERNS = sorted(
    [(re.escape(k), v) for k, v in REPLACEMENT_TABLE.items()],
    key=lambda pair: len(pair[0]),
    reverse=True,
)

_COMPILED_PATTERN = re.compile("|".join(p[0] for p in _REPLACEMENT_PATTERNS))


def _build_replacement_entries(entries: List[Tuple[str, str]]) -> Tuple[Dict[str, str], re.Pattern]:
    sorted_entries = sorted(
        entries,
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    _map = dict(sorted_entries)
    pattern = re.compile("|".join(re.escape(k) for k, _v in sorted_entries))
    return _map, pattern


def _get_active_entries() -> Tuple[bool, List[Tuple[str, str]]]:
    """Query DB for dictionary entries.

    Returns:
        (has_any_entry, active_entries)
        - (True, [...]): DB has active entries
        - (True, []): DB has entries but all are disabled
        - (False, []): DB is empty (0 rows) or unreachable
    """
    try:
        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM dictionary_entries").fetchone()[0]
            if total == 0:
                return False, []
            rows = conn.execute(
                "SELECT surface, reading FROM dictionary_entries WHERE enabled = 1"
            ).fetchall()
            return True, [(r["surface"], r["reading"]) for r in rows]
    except Exception:
        logger.warning("Failed to read dictionary_entries from DB, falling back to static table")
        return False, []


def apply_replacements(text: str) -> str:
    """Apply pronunciation replacement from display text to spoken text.

    - Queries DB for enabled dictionary_entries first.
    - If DB has entries but all are disabled: no replacements (text unchanged).
    - If DB is empty (0 rows) or unreachable: falls back to static REPLACEMENT_TABLE.
    - Longest key first ensures "GitHub" matches before "Git".
    - Returns a new string; original is unchanged.
    """
    has_any_entry, active_entries = _get_active_entries()

    if has_any_entry and not active_entries:
        return text

    if has_any_entry and active_entries:
        entries = active_entries
    else:
        entries = list(REPLACEMENT_TABLE.items())

    _map, pattern = _build_replacement_entries(entries)

    def _replacer(m: re.Match) -> str:
        return _map.get(m.group(0), m.group(0))

    return pattern.sub(_replacer, text)
