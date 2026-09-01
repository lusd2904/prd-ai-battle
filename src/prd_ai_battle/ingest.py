"""Ingest a long requirement and extract a shared brief.

Models receive the brief (目录 / 评分点 / 废标项), not the raw tender.
"""

from __future__ import annotations

import re
from pathlib import Path

from prd_ai_battle.models import Brief, ScoringPoint

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
SCORE_LINE_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(\d+(?:\.\d+)?)\s*\|")
DISQUALIFIER_HINTS = ("废标", "否决", "投标无效", "无效投标")
STAR_RE = re.compile(r"^★\s*(.+)")


def extract_brief(text: str, *, source_path: str = "") -> Brief:
    lines = text.splitlines()
    title = "Untitled requirement"
    toc: list[str] = []
    scoring: list[ScoringPoint] = []
    disqualifiers: list[str] = []
    starred: list[str] = []
    in_disq = False
    in_toc = False

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level, name = heading.group(1), heading.group(2).strip()
            if level == "#" and title == "Untitled requirement":
                title = name
            if name == "目录":
                in_toc = True
                in_disq = False
                continue
            in_toc = False
            in_disq = any(h in name for h in DISQUALIFIER_HINTS)
            if level in {"#", "##"} and name != title:
                toc.append(name)
            continue

        if in_toc and (line.startswith("- ") or re.match(r"^\d+[\.、]", line)):
            toc.append(line.lstrip("- ").strip())
            continue

        score = SCORE_LINE_RE.match(line)
        if score and "评分" not in score.group(1) and "分值" not in score.group(1):
            scoring.append(
                ScoringPoint(
                    title=score.group(1).strip(),
                    score=float(score.group(2)),
                    detail=line,
                )
            )
            continue

        star = STAR_RE.search(line)
        if star:
            starred.append(star.group(1).strip())

        if in_disq and (line.startswith("- ") or line.startswith("·")):
            disqualifiers.append(line.lstrip("-· ").strip())

    if not scoring:
        for raw in lines:
            if "分）" in raw or "分)" in raw:
                heading = HEADING_RE.match(raw.strip())
                if heading:
                    scoring.append(ScoringPoint(title=heading.group(2).strip()))

    summary_bits = [title]
    if scoring:
        summary_bits.append(f"{len(scoring)} scoring points")
    if disqualifiers:
        summary_bits.append(f"{len(disqualifiers)} disqualification items")
    if starred:
        summary_bits.append(f"{len(starred)} starred must-respond clauses")

    return Brief(
        title=title,
        toc=_dedupe(toc),
        scoring_points=scoring,
        disqualifiers=_dedupe(disqualifiers),
        starred_requirements=_dedupe(starred),
        summary="; ".join(summary_bits),
        source_path=source_path,
    )


def load_requirement(path: Path) -> tuple[str, Brief]:
    text = path.read_text(encoding="utf-8")
    return text, extract_brief(text, source_path=str(path))


def bundled_sample_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "tender.md"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
