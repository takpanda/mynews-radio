"""Immutable program definitions and their basic validation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


ProgramKind = Literal["radio", "commentary"]
_SEGMENT_KINDS = {
    "radio": {"intro", "transition", "news", "discussion", "outro"},
    "commentary": {"intro", "news", "outro"},
}


@dataclass(frozen=True)
class ProgramCastMember:
    """A speaker used by a program, keyed by the script's speaker value."""

    key: str
    name: str
    role: str = ""


@dataclass(frozen=True)
class ProgramSegment:
    """A named section in the order it appears in a program."""

    id: str
    kind: str
    order: int
    min_lines: int
    max_lines: int
    speaker_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProgramOptions:
    """Behavioral defaults consumed by later prompt and validation layers."""

    style: str | None = None
    mc_gender: str | None = None
    narrative_arc: bool = False


@dataclass(frozen=True)
class ProgramProfile:
    """A prompt- and validation-ready definition of a radio program."""

    id: str
    name: str
    kind: str
    cast: tuple[ProgramCastMember, ...]
    segments: tuple[ProgramSegment, ...]
    options: ProgramOptions = ProgramOptions()

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

    cast_keys = [member.key for member in profile.cast]
    if any(not key for key in cast_keys):
        errors.append("cast speaker keys must not be empty")
    if len(cast_keys) != len(set(cast_keys)):
        errors.append("cast speaker keys must be unique")

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
) -> ProgramSegment:
    return ProgramSegment(segment_id, kind, order, min_lines, max_lines, speaker_keys)


_RADIO_CAST = (
    ProgramCastMember("male", "田村", "メインMC"),
    ProgramCastMember("female", "山口", "パートナーMC"),
)
_COMMENTARY_DIALOGUE_CAST = (
    ProgramCastMember("male", "", "解説者"),
    ProgramCastMember("female", "", "聞き手"),
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
)

COMMENTARY_ONE_PERSON = ProgramProfile(
    id="commentary_solo",
    name="解説",
    kind="commentary",
    cast=(ProgramCastMember("male", "", "解説者"),),
    segments=(
        _segment("intro", "intro", 0, 1, 1, ("male",)),
        _segment("news", "news", 1, 6, 9, ("male",)),
        _segment("outro", "outro", 2, 1, 1, ("male",)),
    ),
    options=ProgramOptions(style="solo", mc_gender="male"),
)

COMMENTARY_TWO_PERSON = ProgramProfile(
    id="commentary_dialogue",
    name="解説",
    kind="commentary",
    cast=_COMMENTARY_DIALOGUE_CAST,
    segments=(
        _segment("intro", "intro", 0, 2, 2, ("male", "female")),
        _segment("news", "news", 1, 6, 9, ("male", "female")),
        _segment("outro", "outro", 2, 2, 2, ("male", "female")),
    ),
    options=ProgramOptions(style="dialogue"),
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
        if program_name == "テックニュース":
            return replace(RADIO_TWO_PERSON, id="radio_tech_news", name="テックニュース")
        return RADIO_TWO_PERSON
    if kind == "commentary":
        if style == "dialogue":
            return COMMENTARY_TWO_PERSON
        if style not in (None, "solo"):
            raise ValueError(f"unsupported commentary style: {style!r}")
        if mc_gender not in {"male", "female"}:
            raise ValueError(f"unsupported commentary mc_gender: {mc_gender!r}")
        cast = (ProgramCastMember(mc_gender, "", "解説者"),)
        segments = tuple(replace(segment, speaker_keys=(mc_gender,)) for segment in COMMENTARY_ONE_PERSON.segments)
        return replace(
            COMMENTARY_ONE_PERSON,
            cast=cast,
            segments=segments,
            options=replace(COMMENTARY_ONE_PERSON.options, mc_gender=mc_gender),
        )
    raise ValueError(f"unsupported program kind: {kind!r}")


for _profile in DEFAULT_PROFILES:
    validate_program_profile(_profile)
