"""版管理されたプロンプトの選択、検証、レンダリング。"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.db.connection import get_db_connection
from app.prompts.definitions import PROMPT_TEMPLATE_DEFINITIONS

logger = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")
_PROMPTS_DIR = Path(__file__).resolve().parent


class PromptTemplateError(ValueError):
    """テンプレートの変数契約、またはレンダリング入力が不正。"""


@dataclass(frozen=True)
class PromptTemplate:
    template_key: str
    content: str
    source: str
    version_id: int | None = None


@dataclass(frozen=True)
class RenderedPrompt:
    template_key: str
    text: str
    source: str
    version_id: int | None = None


def extract_prompt_variables(content: str) -> set[str]:
    """波かっこ内の許可形式 `{variable}` だけを変数として認識する。"""
    return {match.group(1) for match in _TOKEN_PATTERN.finditer(content) if match.group(1)}


def validate_prompt_template(
    content: str,
    *,
    required_variables: Sequence[str],
    allowed_variables: Sequence[str],
) -> None:
    """必須変数と未知変数を検証する。JSON等の他の波かっこは無視する。"""
    variables = extract_prompt_variables(content)
    required = set(required_variables)
    allowed = set(allowed_variables)
    missing = required - variables
    unknown = variables - allowed
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing required variables: {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown variables: {', '.join(sorted(unknown))}")
        raise PromptTemplateError("; ".join(details))


def render_prompt_template(
    content: str,
    variables: Mapping[str, Any],
    *,
    required_variables: Sequence[str],
    allowed_variables: Sequence[str],
) -> str:
    """許可した変数だけを置換し、その他の波かっこはそのまま残す。"""
    validate_prompt_template(
        content,
        required_variables=required_variables,
        allowed_variables=allowed_variables,
    )
    missing = set(required_variables) - variables.keys()
    if missing:
        raise PromptTemplateError(f"missing render values: {', '.join(sorted(missing))}")
    unknown_values = variables.keys() - set(allowed_variables)
    if unknown_values:
        raise PromptTemplateError(f"unknown render values: {', '.join(sorted(unknown_values))}")
    # エスケープ波かっこは一度の走査で出力し、展開後の文字列を再解釈しない。
    rendered: list[str] = []
    cursor = 0
    for match in _TOKEN_PATTERN.finditer(content):
        rendered.append(content[cursor:match.start()])
        token = match.group(0)
        variable = match.group(1)
        if token in {"{{", "}}"}:
            rendered.append(token[0])
        elif variable in variables:
            rendered.append(str(variables[variable]))
        else:
            rendered.append(token)
        cursor = match.end()
    rendered.append(content[cursor:])
    return "".join(rendered)


def _validate_template_key(template_key: str) -> dict[str, Any]:
    definition = PROMPT_TEMPLATE_DEFINITIONS.get(template_key)
    if definition is None:
        raise PromptTemplateError(f"unknown prompt template: {template_key}")
    return definition


def _load_file_template(template_key: str, definition: Mapping[str, Any]) -> PromptTemplate:
    content = (_PROMPTS_DIR / definition["file"]).read_text(encoding="utf-8")
    validate_prompt_template(
        content,
        required_variables=definition["required_variables"],
        allowed_variables=definition["allowed_variables"],
    )
    return PromptTemplate(template_key=template_key, content=content, source="file")


def _active_template(
    conn: sqlite3.Connection,
    template_key: str,
    program_id: str | None,
    definition: Mapping[str, Any],
) -> PromptTemplate | None:
    row = conn.execute(
        "SELECT pv.id AS version_id, pv.content, pt.required_variables, pt.allowed_variables "
        "FROM prompt_templates pt JOIN prompt_versions pv ON pv.template_id = pt.id "
        "WHERE pt.template_key = ? AND pt.program_id IS ? AND pv.status = 'active'",
        (template_key, program_id),
    ).fetchone()
    if row is None:
        return None

    try:
        required = json.loads(row["required_variables"])
        allowed = json.loads(row["allowed_variables"])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise PromptTemplateError("invalid required variable metadata")
        if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
            raise PromptTemplateError("invalid allowed variable metadata")
        validate_prompt_template(
            row["content"], required_variables=required, allowed_variables=allowed
        )
        # 管理APIで契約を書き換えた場合も、コード側のテンプレート変数境界を超えない。
        if set(required) != set(definition["required_variables"]):
            raise PromptTemplateError("required variable contract does not match template definition")
        if not set(allowed) <= set(definition["allowed_variables"]):
            raise PromptTemplateError("allowed variable contract exceeds template definition")
        return PromptTemplate(
            template_key=template_key,
            content=row["content"],
            source="program" if program_id is not None else "common",
            version_id=row["version_id"],
        )
    except (TypeError, json.JSONDecodeError, PromptTemplateError) as exc:
        logger.warning(
            "Ignoring invalid active prompt template key=%s scope=%s: %s",
            template_key,
            "program" if program_id is not None else "common",
            exc,
        )
        return None


def load_prompt_template(template_key: str, *, program_id: str | None = None) -> PromptTemplate:
    """番組active版、共通active版、ファイルの順にテンプレートを選ぶ。"""
    definition = _validate_template_key(template_key)
    try:
        with get_db_connection() as conn:
            if program_id is not None:
                template = _active_template(conn, template_key, program_id, definition)
                if template is not None:
                    return template
            template = _active_template(conn, template_key, None, definition)
            if template is not None:
                return template
    except Exception:
        # DB接続・スキーマ・読込障害は非致命扱い。ファイルから生成を継続する。
        logger.warning("Prompt DB lookup failed; using file fallback key=%s", template_key, exc_info=True)

    return _load_file_template(template_key, definition)


def render_prompt(
    template_key: str,
    variables: Mapping[str, Any],
    *,
    program_id: str | None = None,
) -> RenderedPrompt:
    """DBまたはファイルから選択し、契約に従って完成プロンプトを返す。"""
    template = load_prompt_template(template_key, program_id=program_id)
    definition = _validate_template_key(template_key)
    text = render_prompt_template(
        template.content,
        variables,
        required_variables=definition["required_variables"],
        allowed_variables=definition["allowed_variables"],
    )
    return RenderedPrompt(
        template_key=template_key,
        text=text,
        source=template.source,
        version_id=template.version_id,
    )
