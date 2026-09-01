"""Chapter/section diffs — the only artifact slice advisors see in review."""

from __future__ import annotations

import difflib

from prd_ai_battle.models import SectionDiff


def split_sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading = "preamble"
    buf: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("#"):
            if buf:
                sections.append((heading, "\n".join(buf).strip()))
            heading = line.lstrip("#").strip() or heading
            buf = [line]
        else:
            buf.append(line)
    if buf:
        sections.append((heading, "\n".join(buf).strip()))
    return sections


def chapter_diffs(old: str, new: str) -> list[SectionDiff]:
    old_map = {h: body for h, body in split_sections(old)}
    new_sections = split_sections(new)
    seen: set[str] = set()
    out: list[SectionDiff] = []
    for heading, body in new_sections:
        seen.add(heading)
        prev = old_map.get(heading, "")
        if prev == body:
            continue
        diff = "\n".join(
            difflib.unified_diff(
                prev.splitlines(),
                body.splitlines(),
                fromfile=f"previous/{heading}",
                tofile=f"current/{heading}",
                lineterm="",
            )
        )
        out.append(SectionDiff(heading=heading, diff=diff or body))
    for heading, body in old_map.items():
        if heading not in seen:
            diff = "\n".join(
                difflib.unified_diff(
                    body.splitlines(),
                    [],
                    fromfile=f"previous/{heading}",
                    tofile=f"current/{heading}",
                    lineterm="",
                )
            )
            out.append(SectionDiff(heading=heading, diff=diff))
    return out
