"""Build profile-specific prompt sections without changing legacy prompt baselines."""

from __future__ import annotations

import json

from app.programs.profiles import (
    COMMENTARY_ONE_PERSON,
    COMMENTARY_TWO_PERSON,
    RADIO_TWO_PERSON,
    ProgramProfile,
    get_default_profile,
)


class PromptBuilder:
    """Render the cast, structure, and example portions of a program prompt."""

    def __init__(self, profile: ProgramProfile):
        self.profile = profile

    @property
    def cast_section(self) -> str:
        members = self.profile.cast
        if len(members) == 1:
            member = members[0]
            return (
                "# 出演者と文体\n"
                f"- 話者キー: {member.key}（{member.name or member.role or '解説者'}）\n"
                "- 一人語りの自然なナレーションで進行し、聞き手への問いかけや相槌を入れない。\n"
                "- 事実・背景・影響を、専門用語を噛み砕いて説明する。\n"
            )
        lines = ["# 出演者と役割分担"]
        for member in members:
            description = "：" + member.role if member.role else ""
            lines.append(f"- speaker キー `{member.key}`: {member.name or member.key}{description}")
        lines.append("- 出演者が交互に話し、役割に応じて異なる視点を加える。")
        return "\n".join(lines) + "\n"

    @property
    def structure_section(self) -> str:
        lines = ["# 番組構成"]
        for segment in self.profile.segments:
            lines.append(
                f"- {segment.id}（{segment.kind}）: {segment.min_lines}〜{segment.max_lines}行"
            )
        if len(self.profile.cast) == 1 and self.profile.kind == "radio":
            lines.append("- 記事間のtransitionは、各記事の間に独立した1行を入れる。")
        elif len(self.profile.cast) > 1:
            lines.append("- 複数出演者は掛け合いで進行し、それぞれの役割を守る。")
        return "\n".join(lines) + "\n"

    @property
    def output_example(self) -> str:
        speaker = self.profile.cast[0].key if self.profile.cast else "male"
        example = {
            "lines": [
                {
                    "speaker": speaker,
                    "text": "〔このセクションの内容〕",
                    "article_id": None,
                    "segment": self.profile.segments[0].id if self.profile.segments else "intro",
                    "section": self.profile.segments[0].kind if self.profile.segments else "intro",
                    "delivery": "neutral",
                }
            ]
        }
        return json.dumps(example, ensure_ascii=False, indent=2)

    def supplemental_sections(self) -> str:
        """Return generated sections for a non-legacy cast; legacy prompts stay byte-identical."""
        if self.uses_legacy_prompt:
            return ""
        return "\n".join((self.cast_section, self.structure_section, self.output_example)) + "\n"

    @property
    def uses_legacy_prompt(self) -> bool:
        """Whether an existing hand-authored prompt exactly represents this profile."""
        legacy_profiles = (
            RADIO_TWO_PERSON,
            get_default_profile(kind="radio", program_name="テックニュース"),
            COMMENTARY_ONE_PERSON,
            get_default_profile(kind="commentary", style="solo", mc_gender="female"),
            COMMENTARY_TWO_PERSON,
        )
        return any(
            self.profile.kind == legacy.kind
            and self.profile.cast == legacy.cast
            and self.profile.segments == legacy.segments
            and self.profile.options == legacy.options
            for legacy in legacy_profiles
        )

    def build_profile_prompt(
        self,
        *,
        task_description: str,
        input_description: str,
        additional_instructions: str = "",
    ) -> str:
        """Build a self-contained prompt without conflicting legacy cast rules."""
        allowed_speakers = ", ".join(member.key for member in self.profile.cast)
        sections = ", ".join(segment.kind for segment in self.profile.segments)
        requirements = [
            "- 各行に speaker / text / article_id / segment / section / delivery を含める。",
            f"- speaker はプロフィールで定義されたキー（{allowed_speakers}）だけを使う。",
            f"- section はプロフィールのセクション（{sections}）だけを使う。",
            "- segment は対応する section のプロフィール上の segment id を使う。",
        ]
        content = [
            task_description,
            "必ず JSON のみを返してください。",
            self.cast_section,
            self.structure_section,
            "# 出力例（形式を守ること）",
            self.output_example,
            "# 出力ルール",
            *requirements,
        ]
        if additional_instructions:
            content.extend(("# 追加指示", additional_instructions))
        content.extend((input_description,))
        return "\n\n".join(content)

    def segment_for_section(self, section: str) -> str:
        """Resolve an output section to its profile segment id."""
        segment = next((item for item in self.profile.segments if item.kind == section), None)
        if segment is None:
            raise ValueError(f"profile {self.profile.id!r} has no segment for section {section!r}")
        return segment.id
