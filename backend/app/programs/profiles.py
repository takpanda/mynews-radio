"""Immutable program definitions and their basic validation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


ProgramKind = Literal["radio", "commentary"]
ProgramNewsSource = Literal[
    "hatena_bookmark", "hatena_hotentry_all", "yahoo_news", "url"
]
_NEWS_SOURCES = {"hatena_bookmark", "hatena_hotentry_all", "yahoo_news", "url"}
_THEMES = {"technology", "business", "society", "sports", "entertainment", "general"}
_DURATION_PRESETS = {"short", "normal", "long"}
_SEGMENT_KINDS = {
    "radio": {"intro", "transition", "headline", "news", "discussion", "corner", "outro"},
    "commentary": {"intro", "headline", "news", "corner", "outro"},
}


@dataclass(frozen=True)
class ProgramCastMember:
    """A speaker used by a program, keyed by the script's speaker value."""

    key: str
    name: str
    role: str = ""
    mc_id: str | None = None
    voice_fishs2pro: str | None = None
    voice_aivispeech: int | None = None
    voice_voicevox: int | None = None
    persona: str = ""


@dataclass(frozen=True)
class ProgramSegment:
    """A named section in the order it appears in a program."""

    id: str
    kind: str
    order: int
    min_lines: int
    max_lines: int
    speaker_keys: tuple[str, ...] = ()
    label: str = ""


@dataclass(frozen=True)
class ProgramOptions:
    """Behavioral defaults consumed by later prompt and validation layers."""

    style: str | None = None
    mc_gender: str | None = None
    narrative_arc: bool = False
    review_mode: str = "on_failure"


@dataclass(frozen=True)
class ProgramProfile:
    """A prompt- and validation-ready definition of a radio program."""

    id: str
    name: str
    kind: str
    cast: tuple[ProgramCastMember, ...]
    segments: tuple[ProgramSegment, ...]
    options: ProgramOptions = ProgramOptions()
    news_source: ProgramNewsSource | None = None
    priority_themes: tuple[str, ...] | None = None
    excluded_themes: tuple[str, ...] | None = None
    max_articles: int | None = None
    min_importance_score: int | None = None
    duration_preset: str | None = None

    @property
    def speaker_keys(self) -> frozenset[str]:
        return frozenset(member.key for member in self.cast)


class ProfileValidationError(ValueError):
    """Raised when a program profile is internally inconsistent."""


def validate_program_profile(profile: ProgramProfile) -> None:
    """Validate profile invariants and raise with all detected problems."""
    errors: list[str] = []
    if profile.kind not in {"radio", "commentary"}:
        errors.append(f"unsupported program kind: {profile.kind!r}")
    if profile.options.review_mode not in {"always", "on_failure", "auto"}:
        errors.append(f"unsupported review_mode: {profile.options.review_mode!r}")
    if profile.news_source is not None and profile.news_source not in _NEWS_SOURCES:
        errors.append(f"unsupported news_source: {profile.news_source!r}")
    if profile.news_source == "url" and profile.kind != "commentary":
        errors.append("url news_source is only supported for commentary profiles")
    if profile.kind == "commentary" and profile.news_source not in (None, "url"):
        errors.append("commentary profiles must use the url news_source")
    for name, themes in (
        ("priority_themes", profile.priority_themes),
        ("excluded_themes", profile.excluded_themes),
    ):
        if themes is not None:
            if len(themes) != len(set(themes)):
                errors.append(f"{name} must not contain duplicates")
            if name == "priority_themes" and len(themes) > 3:
                errors.append("priority_themes must contain at most 3 items")
            if any(theme not in _THEMES for theme in themes):
                errors.append(f"{name} contains an unsupported theme")
    if profile.priority_themes is not None and profile.excluded_themes is not None:
        if set(profile.priority_themes) & set(profile.excluded_themes):
            errors.append("priority_themes and excluded_themes must not overlap")
    if profile.max_articles is not None and not 1 <= profile.max_articles <= 50:
        errors.append("max_articles must be between 1 and 50")
    if profile.min_importance_score is not None and not 1 <= profile.min_importance_score <= 5:
        errors.append("min_importance_score must be between 1 and 5")
    if profile.duration_preset is not None and profile.duration_preset not in _DURATION_PRESETS:
        errors.append(f"unsupported duration_preset: {profile.duration_preset!r}")

    cast_keys = [member.key for member in profile.cast]
    if not cast_keys:
        errors.append("program profile must include at least one cast member")
    if any(not key for key in cast_keys):
        errors.append("cast speaker keys must not be empty")
    if len(cast_keys) != len(set(cast_keys)):
        errors.append("cast speaker keys must be unique")
    if profile.kind == "commentary":
        if profile.options.narrative_arc:
            errors.append("commentary profiles do not support narrative_arc")
        if profile.options.style not in {None, "solo", "dialogue"}:
            errors.append(f"unsupported commentary style in profile: {profile.options.style!r}")
        if profile.options.style == "solo" and len(cast_keys) != 1:
            errors.append("commentary solo profiles must have exactly one cast member")
        if profile.options.style == "dialogue" and len(cast_keys) < 2:
            errors.append("commentary dialogue profiles must have at least two cast members")
        if profile.options.mc_gender and profile.options.mc_gender not in set(cast_keys):
            errors.append("commentary mc_gender must match a cast speaker key")

    if len(profile.segments) > 6:
        errors.append("program profiles may define at most 6 segments")

    segment_ids = [segment.id for segment in profile.segments]
    if any(not segment_id for segment_id in segment_ids):
        errors.append("segment ids must not be empty")
    if len(segment_ids) != len(set(segment_ids)):
        errors.append("segment ids must be unique")

    orders = [segment.order for segment in profile.segments]
    if len(orders) != len(set(orders)):
        errors.append("segment order values must be unique")
    if orders != sorted(orders):
        errors.append("segments must be declared in ascending order")

    known_speakers = set(cast_keys)
    for segment in profile.segments:
        if segment.kind not in _SEGMENT_KINDS.get(profile.kind, set()):
            errors.append(
                f"segment {segment.id!r} has unsupported kind {segment.kind!r}"
            )
        if segment.min_lines < 0 or segment.max_lines < segment.min_lines:
            errors.append(f"segment {segment.id!r} has invalid line-count bounds")
        unknown_speakers = set(segment.speaker_keys) - known_speakers
        if unknown_speakers:
            errors.append(
                f"segment {segment.id!r} references unknown speakers: "
                f"{', '.join(sorted(unknown_speakers))}"
            )

    if errors:
        raise ProfileValidationError("; ".join(errors))


def _segment(
    segment_id: str,
    kind: str,
    order: int,
    min_lines: int,
    max_lines: int,
    speaker_keys: tuple[str, ...],
    label: str = "",
) -> ProgramSegment:
    return ProgramSegment(segment_id, kind, order, min_lines, max_lines, speaker_keys, label)


_SEGMENT_LABELS = {
    "intro": "オープニング",
    "transition": "つなぎ",
    "headline": "ヘッドライン",
    "news": "ニュース",
    "discussion": "討論",
    "corner": "コーナー",
    "outro": "エンディング",
}


def segment_snapshots(profile: ProgramProfile) -> list[dict[str, str]]:
    """Return display metadata frozen into a generated script."""
    base_labels: list[str] = []
    label_counts: dict[str, int] = {}
    for segment in profile.segments:
        label = segment.label.strip() or _SEGMENT_LABELS.get(segment.kind, segment.kind)
        base_labels.append(label)
        label_counts[label] = label_counts.get(label, 0) + 1

    label_indexes: dict[str, int] = {}
    snapshots = []
    for segment, base_label in zip(profile.segments, base_labels):
        label_indexes[base_label] = label_indexes.get(base_label, 0) + 1
        label = base_label
        if label_counts[base_label] > 1:
            label = f"{base_label} {label_indexes[base_label]}"
        snapshots.append({"id": segment.id, "label": label})
    return snapshots


def profile_voice_overrides(profile: ProgramProfile, engine: str) -> dict[str, int | str]:
    """Return per-cast voice values configured for the selected TTS engine."""
    field_by_engine = {
        "fishs2pro": "voice_fishs2pro",
        "aivispeech": "voice_aivispeech",
        "voicevox": "voice_voicevox",
    }
    field = field_by_engine.get(engine)
    if field is None:
        return {}
    return {
        member.key: value
        for member in profile.cast
        if (value := getattr(member, field)) is not None
    }


def format_cast_personas(profile: ProgramProfile) -> str:
    """Render the selected MC identities, program roles, and personas for prompts."""
    lines = ["# 今回の出演MCと人物設定"]
    for index, member in enumerate(profile.cast, start=1):
        label = f"MC{index}"
        identity = f"（{member.name}）" if member.name else ""
        role = member.role.strip() or "役割指定なし"
        lines.append(f"- {label}{identity} / speakerキー `{member.key}` / 番組内の役割: {role}")
        if (persona := (member.persona or "").strip()):
            lines.append(f"  人物設定: {persona}")
    lines.extend([
        "人物設定はMC自身の経歴・性格・話し方を表し、番組内の役割はこの出演で担う担当範囲を表します。",
        "発話では人物設定と番組内の役割の両方を反映してください。",
    ])
    return "\n".join(lines)


RADIO_MALE_PERSONA = "38歳。元新聞記者・ニュースキャスター。落ち着いて理性的。難しい話も噛み砕いて伝え、短く歯切れよく、やわらかい言葉で要点を話す。"
RADIO_FEMALE_PERSONA = "31歳。ラジオパーソナリティ・生活情報コメンテーター。明るく率直で共感力が高い。やわらかく親しみやすい話し方で、少しテンポが速い。"
RADIO_MALE_ROLE = "事実・数字・データを正確に伝える。技術的な仕組み、制度、背景、歴史的経緯を平易な言葉で説明し、論点を整理する。もう一人のMCの分析・疑問・別角度の提起には、感情論ではなく事実や構造で応答する。"
RADIO_FEMALE_ROLE = "生活者・消費者の目線で影響を具体化する。リスクや不安、リスナーの疑問を言葉にし、実際の行動変容につなげる。生活影響・リスクシナリオ・社会的受容の切り口から分析や別角度の問題提起を行う。技術構造・制度・データの詳細解説は担わない。"
COMMENTARY_MALE_PERSONA = "落ち着いて知的でわかりやすい解説者。専門用語を適宜噛み砕き、事実・背景・影響をバランスよく伝える。"
COMMENTARY_FEMALE_PERSONA = "明るく率直で共感力が高い聞き手。生活者目線で影響を具体化し、リスナーの疑問を代弁する。"

_RADIO_CAST = (
    ProgramCastMember("male", "田村", RADIO_MALE_ROLE, mc_id="radio_male", persona=RADIO_MALE_PERSONA),
    ProgramCastMember("female", "山口", RADIO_FEMALE_ROLE, mc_id="radio_female", persona=RADIO_FEMALE_PERSONA),
)
_COMMENTARY_DIALOGUE_CAST = (
    ProgramCastMember("male", "", "解説者", mc_id="commentary_male", persona=COMMENTARY_MALE_PERSONA),
    ProgramCastMember("female", "", "聞き手", mc_id="commentary_female", persona=COMMENTARY_FEMALE_PERSONA),
)

RADIO_TWO_PERSON = ProgramProfile(
    id="radio_news_neighbor",
    name="ニュースのとなり",
    kind="radio",
    cast=_RADIO_CAST,
    segments=(
        _segment("intro", "intro", 0, 4, 5, ("male", "female")),
        _segment("transition", "transition", 1, 1, 2, ("male", "female")),
        _segment("news", "news", 2, 4, 8, ("male", "female")),
        _segment("discussion", "discussion", 3, 4, 8, ("male", "female")),
        _segment("outro", "outro", 4, 4, 6, ("male", "female")),
    ),
    options=ProgramOptions(narrative_arc=True),
    news_source="hatena_hotentry_all",
)

COMMENTARY_ONE_PERSON = ProgramProfile(
    id="commentary_solo",
    name="解説",
    kind="commentary",
    cast=(ProgramCastMember("male", "", "解説者", mc_id="commentary_male", persona=COMMENTARY_MALE_PERSONA),),
    segments=(
        _segment("intro", "intro", 0, 1, 2, ("male",)),
        _segment("news", "news", 1, 3, 12, ("male",)),
        _segment("outro", "outro", 2, 1, 2, ("male",)),
    ),
    options=ProgramOptions(style="solo", mc_gender="male"),
    news_source="url",
)

COMMENTARY_TWO_PERSON = ProgramProfile(
    id="commentary_dialogue",
    name="解説",
    kind="commentary",
    cast=_COMMENTARY_DIALOGUE_CAST,
    segments=(
        _segment("intro", "intro", 0, 1, 3, ("male", "female")),
        _segment("news", "news", 1, 3, 12, ("male", "female")),
        _segment("outro", "outro", 2, 1, 2, ("male", "female")),
    ),
    options=ProgramOptions(style="dialogue"),
    news_source="url",
)

DEFAULT_PROFILES: tuple[ProgramProfile, ...] = (
    RADIO_TWO_PERSON,
    COMMENTARY_ONE_PERSON,
    COMMENTARY_TWO_PERSON,
)


def get_default_profile(
    *,
    kind: str,
    program_name: str | None = None,
    news_source: str | None = None,
    style: str | None = None,
    mc_gender: str = "male",
) -> ProgramProfile:
    """Resolve one of the current generation modes to its profile.

    Radio retains the existing ``program_name`` / ``news_source`` selection;
    commentary retains its ``style`` / ``mc_gender`` arguments.
    """
    if kind == "radio":
        if program_name:
            is_tech_news = program_name == "テックニュース"
        else:
            is_tech_news = news_source == "hatena_bookmark"
        if is_tech_news:
            return replace(
                RADIO_TWO_PERSON,
                id="radio_tech_news",
                name="テックニュース",
                news_source="hatena_bookmark",
            )
        return RADIO_TWO_PERSON
    if kind == "commentary":
        if style == "dialogue":
            return COMMENTARY_TWO_PERSON
        if style not in (None, "solo"):
            raise ValueError(f"unsupported commentary style: {style!r}")
        if mc_gender not in {"male", "female"}:
            raise ValueError(f"unsupported commentary mc_gender: {mc_gender!r}")
        cast = (ProgramCastMember(
            mc_gender,
            "",
            "解説者",
            mc_id=f"commentary_{mc_gender}",
            persona=(
                COMMENTARY_FEMALE_PERSONA
                if mc_gender == "female"
                else COMMENTARY_MALE_PERSONA
            ),
        ),)
        segments = tuple(replace(segment, speaker_keys=(mc_gender,)) for segment in COMMENTARY_ONE_PERSON.segments)
        return replace(
            COMMENTARY_ONE_PERSON,
            cast=cast,
            segments=segments,
            options=replace(COMMENTARY_ONE_PERSON.options, mc_gender=mc_gender),
        )
    raise ValueError(f"unsupported program kind: {kind!r}")


def get_profile_by_id(
    profile_id: str,
    *,
    style: str | None = None,
    mc_gender: str = "male",
) -> ProgramProfile | None:
    """Return a registered default profile by its stable identifier."""
    if profile_id == "commentary_solo":
        return get_default_profile(
            kind="commentary",
            style="solo" if style in (None, "") else style,
            mc_gender=mc_gender,
        )
    for profile in DEFAULT_PROFILES:
        if profile.id == profile_id:
            return profile
    if profile_id == "radio_tech_news":
        return get_default_profile(kind="radio", program_name="テックニュース")
    return None


for _profile in DEFAULT_PROFILES:
    validate_program_profile(_profile)
