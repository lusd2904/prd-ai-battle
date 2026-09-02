"""Build a 响应对照表 from an extracted brief and mark coverage from a draft."""

from __future__ import annotations

import re
from pathlib import Path

from prd_ai_battle.models import Brief, ComplianceMatrix, MatrixRow, ResponseStatus, RowStatus

REQUIREMENT_CATEGORIES = frozenset(
    {"must", "optional", "risk", "constraint", "goal", "requirement"}
)


def matrix_from_brief(brief: Brief) -> ComplianceMatrix:
    rows: list[MatrixRow] = []
    n = 1
    seen: set[str] = set()
    for item in brief.starred_requirements:
        if _skip_clause(item, seen):
            continue
        rows.append(
            MatrixRow(
                clause_id=f"S{n:02d}",
                clause=item,
                responded=ResponseStatus.NO,
                category="starred",
            )
        )
        n += 1
    for point in brief.scoring_points:
        label = point.title if point.score is None else f"{point.title}（{point.score:g}分）"
        if _skip_clause(label, seen):
            continue
        rows.append(
            MatrixRow(
                clause_id=f"P{n:02d}",
                clause=label,
                responded=ResponseStatus.NO,
                category="scoring",
            )
        )
        n += 1
    for item in brief.disqualifiers:
        if _skip_clause(item, seen):
            continue
        rows.append(
            MatrixRow(
                clause_id=f"D{n:02d}",
                clause=item,
                responded=ResponseStatus.NO,
                category="disqualifier",
                opinion="Must not trigger 废标",
                status=RowStatus.OPEN,
            )
        )
        n += 1
    for clause in brief.requirement_clauses:
        text = (clause.text or "").strip()
        if _skip_clause(text, seen):
            continue
        kind = (clause.kind or "requirement").strip() or "requirement"
        rows.append(
            MatrixRow(
                clause_id=f"R{n:02d}",
                clause=text,
                responded=ResponseStatus.NO,
                category=kind if kind in REQUIREMENT_CATEGORIES else "requirement",
            )
        )
        n += 1
    return ComplianceMatrix(title=f"响应对照表 · {brief.title}", rows=rows)


def _skip_clause(text: str, seen: set[str]) -> bool:
    compact = "".join(text.split())
    if not compact or compact in {"(none)", "（无）", "无", "-", "—"}:
        return True
    if compact in seen:
        return True
    seen.add(compact)
    return False


def apply_offline_seed(matrix: ComplianceMatrix) -> None:
    """Fill a plausible first-pass response so the demo can lock immediately."""
    if matrix.locked:
        return
    for row in matrix.rows:
        if row.category == "disqualifier":
            row.responded = ResponseStatus.YES
            row.evidence_page = "封皮 / 投标函"
            row.opinion = "密封、报价、认证、有效期均按须知执行"
            row.status = RowStatus.FILLED
        elif row.category == "starred":
            row.responded = ResponseStatus.YES
            row.evidence_page = "技术方案 ch.5"
            row.opinion = "★ 条款在实施方案中逐条响应"
            row.status = RowStatus.FILLED
        elif row.category in REQUIREMENT_CATEGORIES:
            row.responded = ResponseStatus.PARTIAL
            row.evidence_page = "方案正文"
            row.opinion = "需求条款已列入对照表，待一次稿补证据"
            row.status = RowStatus.FILLED
        else:
            row.responded = ResponseStatus.PARTIAL
            row.evidence_page = "商务 / 技术分册"
            row.opinion = "评分点已列提纲，待一次稿补证据"
            row.status = RowStatus.FILLED


_KIND_PREFIX_RE = re.compile(
    r"^(必须响应|可选优化|必须|可选|风险|约束|需求|目标)[：:\s]+"
)
_SPLIT_RE = re.compile(r"[，。；;、\n]+")
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_STOP_NEEDLES = frozenset(
    {
        "必须",
        "必须响应",
        "响应",
        "可选",
        "可选优化",
        "优化",
        "风险",
        "约束",
        "需求",
        "目标",
        "条款",
        "给出",
        "评估",
        "方案",
        "要求",
        "说明",
        "以及",
        "或者",
        "并",
        "的",
    }
)


def apply_draft_coverage(matrix: ComplianceMatrix, draft: str) -> list[MatrixRow]:
    """Set each existing row's 是否响应 / 证据 / 意见 from the draft.

    Locked tables keep the same clause list (no add/remove). Response fields
    update in place: yes if the draft addresses the clause, partial if weak,
    no if missing. Evidence is a draft heading or line range, not a tender page.
    """
    ids_before = [row.clause_id for row in matrix.rows]
    text = draft or ""
    for row in matrix.rows:
        responded, evidence, opinion = score_clause_coverage(row, text)
        matrix.apply_response(
            row.clause_id,
            responded=responded,
            evidence_page=evidence,
            opinion=opinion,
        )
    if [row.clause_id for row in matrix.rows] != ids_before:
        raise RuntimeError("Draft coverage must not add or remove 对照表 clauses")
    return list(matrix.rows)


def score_clause_coverage(row: MatrixRow, draft: str) -> tuple[ResponseStatus, str, str]:
    """Return (responded, evidence, opinion) for one locked/unlocked row."""
    if not (draft or "").strip():
        return ResponseStatus.NO, "", "一次稿未覆盖"
    needles = clause_needles(row)
    hits = [needle for needle in needles if needle and needle in draft]
    overlaps = shared_phrases(_clause_body(row.clause), draft)
    long_hits = [hit for hit in hits if hit != row.clause_id and len(hit) >= 6] + overlaps
    id_hit = row.clause_id in hits
    if not hits and not overlaps:
        return ResponseStatus.NO, "", "一次稿未覆盖"
    if id_hit or long_hits:
        evidence = evidence_locator(draft, long_hits[0] if long_hits else row.clause_id)
        return ResponseStatus.YES, evidence, "一次稿已覆盖该条款"
    evidence = evidence_locator(draft, hits[0])
    return ResponseStatus.PARTIAL, evidence, "一次稿仅部分覆盖"


def _clause_body(clause: str) -> str:
    return _KIND_PREFIX_RE.sub("", (clause or "").strip())


def shared_phrases(clause: str, draft: str, *, min_len: int = 6) -> list[str]:
    """Long substrings of the clause that also appear in the draft."""
    text = clause or ""
    found: list[str] = []
    index = 0
    while index <= len(text) - min_len:
        matched = ""
        max_len = min(len(text) - index, 32)
        for length in range(max_len, min_len - 1, -1):
            piece = text[index : index + length]
            if piece in _STOP_NEEDLES:
                continue
            if piece in draft:
                matched = piece
                break
        if matched:
            found.append(matched)
            index += len(matched)
        else:
            index += 1
    return found


def clause_needles(row: MatrixRow) -> list[str]:
    """Distinctive phrases used to decide yes / partial / no."""
    needles = [row.clause_id]
    body = _clause_body(row.clause)
    chunks = [chunk.strip("：: ") for chunk in _SPLIT_RE.split(body) if chunk.strip()]
    if body and body not in chunks:
        chunks.insert(0, body)
    for chunk in chunks:
        if len(chunk) >= 4 and chunk not in _STOP_NEEDLES:
            needles.append(chunk)
        for token in re.split(r"\s+", chunk):
            token = token.strip("：: ")
            if len(token) >= 3 and token not in _STOP_NEEDLES:
                needles.append(token)
    seen: set[str] = set()
    ordered: list[str] = []
    for needle in sorted(needles, key=len, reverse=True):
        if needle in seen:
            continue
        seen.add(needle)
        ordered.append(needle)
    return ordered


def evidence_locator(draft: str, needle: str) -> str:
    """Section heading and/or line range inside the draft (not a 招标 page)."""
    lines = (draft or "").splitlines()
    current_heading = ""
    matched_heading = ""
    start: int | None = None
    end: int | None = None
    in_code_fence = False
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_fence = not in_code_fence
        if not in_code_fence and _HEADING_RE.match(line):
            current_heading = _HEADING_RE.sub("", line).strip()
        if needle and needle in line:
            if start is None:
                start = index
                matched_heading = current_heading
            end = index
    if start is None:
        return current_heading or ""
    loc = f"L{start}" if start == end else f"L{start}–L{end}"
    return f"{matched_heading} · {loc}" if matched_heading else loc


def collapse_duplicated_root(path: Path, root: Path) -> Path:
    """Drop a repeated workspace prefix: root/root/drafts → root/drafts."""
    parts = list(path.parts)
    prefixes: list[tuple[str, ...]] = [tuple(root.parts)]
    try:
        prefixes.append(tuple(root.resolve().parts))
    except OSError:
        pass
    for prefix in prefixes:
        if not prefix:
            continue
        width = len(prefix)
        changed = True
        while changed:
            changed = False
            index = 0
            rebuilt: list[str] = []
            while index < len(parts):
                window = tuple(parts[index : index + width])
                nxt = tuple(parts[index + width : index + 2 * width])
                if window == prefix and nxt == prefix:
                    rebuilt.extend(prefix)
                    index += 2 * width
                    while tuple(parts[index : index + width]) == prefix:
                        index += width
                    changed = True
                else:
                    rebuilt.append(parts[index])
                    index += 1
            parts = rebuilt
    if not parts:
        return path
    if parts[0] == "/":
        return Path("/") / Path(*parts[1:])
    return Path(*parts)


def resolve_recorded_write_path(root: Path, incoming: str | Path) -> Path:
    """Resolve a record-draft path without doubling the workspace prefix.

    OpenCode often passes `.prd-ai-battle/round-matrix/drafts/v1/response.md`
    while the session root is already `.prd-ai-battle/round-matrix`. Prefixing
    blindly produced
    `.prd-ai-battle/round-matrix/.prd-ai-battle/round-matrix/drafts/...`.
    """
    raw = Path(incoming)
    collapsed = collapse_duplicated_root(raw if raw.is_absolute() else root / raw, root)
    collapsed = collapse_duplicated_root(collapsed, root)

    drafts_suffix = _drafts_suffix(raw)
    if drafts_suffix is not None:
        canonical = root / drafts_suffix
        if canonical.is_file() or not collapsed.is_file():
            return canonical

    if raw.is_absolute():
        return collapse_duplicated_root(raw, root)

    raw_s = str(raw)
    for prefix in (str(root), str(root.resolve()) if root.exists() else ""):
        if not prefix:
            continue
        if raw_s == prefix or raw_s.startswith(prefix.rstrip("/\\") + "/"):
            return collapse_duplicated_root(Path(raw_s), root)

    cwd_candidate = collapse_duplicated_root(Path.cwd() / raw, root)
    if cwd_candidate.is_file():
        return cwd_candidate
    if collapsed.is_file():
        return collapsed
    return collapse_duplicated_root(root / raw, root)


def _drafts_suffix(path: Path) -> Path | None:
    parts = path.parts
    indexes = [i for i, part in enumerate(parts) if part == "drafts"]
    if not indexes:
        return None
    start = indexes[-1]
    return Path(*parts[start:])
