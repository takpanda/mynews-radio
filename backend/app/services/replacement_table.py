import re
from typing import Dict

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


def apply_replacements(text: str) -> str:
    """Apply pronunciation replacement from display text to spoken text.

    - Longest key first ensures "GitHub" matches before "Git".
    - Returns a new string; original is unchanged.
    """
    _map = dict(_REPLACEMENT_PATTERNS)

    def _replacer(m: re.Match) -> str:
        return _map.get(m.group(0), m.group(0))

    return _COMPILED_PATTERN.sub(_replacer, text)
