"""TUI skin: speaker palette, short display names, Chinese chrome.

OpenCode stays the execute/revise runtime. This module is paint only —
it does not touch write_lock, the phase machine, or the review packet.
"""

from __future__ import annotations

from collections.abc import Sequence

from prd_ai_battle.models import Phase

# Reserved roles keep fixed colors. Advisors cycle the palette in yaml order
# so a third (or tenth) advisor does not collapse onto the first purple.
SPEAKER_USER = "speaker-user"
SPEAKER_PRIMARY = "speaker-primary"

USER_COLOR = "#3fb950"
PRIMARY_COLOR = "#58a6ff"

# Distinct hues — index is yaml advisor order, not a hardcoded advisor-a/b pair.
ADVISOR_PALETTE: tuple[str, ...] = (
    "#d2a8ff",
    "#f2cc60",
    "#ff7b72",
    "#39d0d6",
    "#ff9bce",
    "#7ee787",
    "#ffa657",
    "#a5d6ff",
)

PALETTE_SIZE = len(ADVISOR_PALETTE)

PHASE_LABELS_ZH: dict[Phase, str] = {
    Phase.DISCUSS: "讨论",
    Phase.LOCKED: "锁定",
    Phase.EXECUTE: "执行",
    Phase.REVIEW: "审核",
    Phase.REVISE: "修订",
}

TAB_REQUIREMENT = "需求"
TAB_BRIEF = "摘要"
TAB_MATRIX = "对照表"
TAB_STATE = "状态"

SIDEBAR_TITLE = "项目"
BTN_NEW_PROJECT = "新建"
NEW_PROJECT_PLACEHOLDER = "项目名称"

PHASE_ORDER_ZH = tuple(PHASE_LABELS_ZH[p] for p in PHASE_LABELS_ZH)


def speaker_display_name(model_id: str, *, primary_id: str = "primary") -> str:
    """Short bubble header. Yaml agent id, never a model dump like x-ai/grok-4.6."""
    if model_id == "user":
        return "用户"
    if model_id == primary_id:
        return "主笔"
    if model_id.startswith("advisor-"):
        short = model_id[len("advisor-") :]
        return short or model_id
    return model_id


def speaker_css_class(
    model_id: str,
    *,
    primary_id: str = "primary",
    advisor_ids: Sequence[str] = (),
) -> str:
    """CSS class for this speaker. Advisors are speaker-0..N in yaml order."""
    if model_id == "user":
        return SPEAKER_USER
    if model_id == primary_id:
        return SPEAKER_PRIMARY
    if advisor_ids:
        try:
            return f"speaker-{list(advisor_ids).index(model_id) % PALETTE_SIZE}"
        except ValueError:
            pass
    digest = sum((i + 1) * ord(ch) for i, ch in enumerate(model_id))
    return f"speaker-{digest % PALETTE_SIZE}"


def speaker_color(
    model_id: str,
    *,
    primary_id: str = "primary",
    advisor_ids: Sequence[str] = (),
) -> str:
    klass = speaker_css_class(model_id, primary_id=primary_id, advisor_ids=advisor_ids)
    if klass == SPEAKER_USER:
        return USER_COLOR
    if klass == SPEAKER_PRIMARY:
        return PRIMARY_COLOR
    idx = int(klass.rsplit("-", 1)[-1])
    return ADVISOR_PALETTE[idx % PALETTE_SIZE]


def matrix_lock_label(locked: bool) -> str:
    return "已锁定" if locked else "未锁定"


def phase_label(phase: Phase) -> str:
    return PHASE_LABELS_ZH[phase]


def phase_rail(current: Phase) -> str:
    """One-line 讨论 → 锁定 → 执行 → 审核 → 修订, current marked."""
    bits: list[str] = []
    for phase, label in PHASE_LABELS_ZH.items():
        if phase is current:
            bits.append(f"[bold #58a6ff]● {label}[/]")
        else:
            bits.append(f"[#8b949e]{label}[/]")
    return " → ".join(bits)


def status_line(*, phase: Phase, matrix_locked: bool, writer_id: str) -> str:
    """Always: current phase, 对照表 lock, who holds write_lock (primary.id)."""
    return (
        f"{phase_rail(phase)}    "
        f"阶段 [b]{phase_label(phase)}[/b]  "
        f"对照表 [b]{matrix_lock_label(matrix_locked)}[/b]  "
        f"写入 [b]{writer_id}[/b]"
    )


def header_subtitle(
    *,
    phase: Phase,
    matrix_locked: bool,
    writer_id: str,
    project_name: str = "",
) -> str:
    """Header strip: short chrome, no model-id dump."""
    base = f"{phase_label(phase)} · 对照表{matrix_lock_label(matrix_locked)} · 写入 {writer_id}"
    if project_name:
        return f"{project_name} · {base}"
    return base
