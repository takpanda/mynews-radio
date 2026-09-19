"""Shared constants for script quality contracts."""

import re


FAREWELL_RE = re.compile(
    r"(?:また(?:明日|次回|来週)|それではまた|お会いしましょう|"
    r"さようなら|お元気で|お届けしました|お聴きいただき|"
    r"お聞きいただき|番組を終わります|締めくくり)"
)

COMMENTARY_IGNORED_LINT_CODES = frozenset({
    "INTRO_FORMAT",
    "INTRO_LINEUP",
    "OUTRO_LENGTH",
    "TRANS_VARIATION",
    "TRANS_CONTEXT",
    "TRANSITION_LENGTH",
    "TRANSITION_SOLO",
    "TRANSITION_REDUNDANT",
    "DISCUSSION_ARTICLE_POSITION",
    "DISCUSSION_LENGTH",
    "DISCUSSION_ARTICLE_DRIFT",
})
