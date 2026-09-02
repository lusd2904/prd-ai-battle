"""Ingest a long requirement and extract a shared brief.

Models receive the brief (目录 / 评分点 / 废标项 / 需求条款), not the raw tender.
Markdown 目标 / 必须做 / 可选 / 风险 / 约束 headings become matrix rows.
PDF files are parsed locally — the raw PDF is never sent to advisors.
"""

from __future__ import annotations

import re
from pathlib import Path

from prd_ai_battle.models import Brief, RequirementClause, ScoringPoint

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
SCORE_LINE_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(\d+(?:\.\d+)?)\s*\|")
SCORE_PLAIN_RE = re.compile(r"^(.+?)[：:\s]+(\d+(?:\.\d+)?)分(?:\s|$)")
DISQUALIFIER_HINTS = ("废标", "否决", "投标无效", "无效投标")
STAR_RE = re.compile(r"^★\s*(.+)")
# Markdown / Chinese lists, but not tender subsection numbers like "2.1 投标人".
LIST_ITEM_RE = re.compile(
    r"^(?:"
    r"[-*+·•]\s+"
    r"|(?<!\d)\d+[、\)]\s*"
    r"|(?<!\d)\d+\.\s+"
    r"|[（(]\d+[）)]\s*"
    r")(.*)$"
)
PLACEHOLDER_RE = re.compile(
    r"^(?:\(none\)|（none）|（无）|无|none|n/?a|—|–|-|…|\.{2,})$",
    re.IGNORECASE,
)
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
PDF_SUFFIXES = {".pdf"}

# Longest label first so "必须响应" wins over "必须".
_CLAUSE_KIND_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("must", ("必须响应", "必须做", "必做项", "硬性要求", "必选", "必须")),
    ("optional", ("可选优化", "可选做", "可选项", "加分项", "建议项", "可选")),
    ("risk", ("风险点", "风险与对策", "风险")),
    ("constraint", ("约束条件", "限制条件", "约束", "限制", "前提", "边界")),
    ("requirement", ("采购需求", "功能需求", "需求条款")),
    ("goal", ("总体目标", "需求目标", "目标")),
)
_KIND_PREFIX = {
    "must": "必须响应",
    "optional": "可选优化",
    "risk": "风险",
    "constraint": "约束",
    "requirement": "需求",
    "goal": "目标",
}
_CONTEXT_HEADINGS = ("现状", "背景", "概述", "前言", "说明")


class IngestError(ValueError):
    """Raised when a requirement file cannot be read or has no extractable text."""


def extract_brief(text: str, *, source_path: str = "") -> Brief:
    lines = text.splitlines()
    title = "Untitled requirement"
    toc: list[str] = []
    scoring: list[ScoringPoint] = []
    disqualifiers: list[str] = []
    starred: list[str] = []
    clauses: list[RequirementClause] = []
    in_disq = False
    in_toc = False
    clause_kind: str | None = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level, name = heading.group(1), heading.group(2).strip()
            is_doc_title = level == "#" and title == "Untitled requirement"
            if is_doc_title:
                title = name
            if _is_toc_marker(name):
                in_toc = True
                in_disq = False
                clause_kind = None
                continue
            in_toc = False
            in_disq = _is_disq_marker(name)
            if in_disq or is_doc_title or _is_context_heading(name):
                clause_kind = None
            else:
                clause_kind = _heading_kind(name)
            if level in {"#", "##"} and name != title:
                toc.append(name)
            continue

        if _is_toc_marker(line):
            in_toc = True
            in_disq = False
            clause_kind = None
            continue

        if _is_disq_bare_section(line):
            in_toc = False
            in_disq = True
            clause_kind = None
            if line != title:
                toc.append(line)
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

        if "。" not in line and "，" not in line:
            plain = SCORE_PLAIN_RE.match(line)
            if (
                plain
                and "评分" not in plain.group(1)
                and "分值" not in plain.group(1)
                and plain.group(1).strip() not in {"总分", "合计"}
            ):
                scoring.append(
                    ScoringPoint(
                        title=plain.group(1).strip(),
                        score=float(plain.group(2)),
                        detail=line,
                    )
                )
                continue

        star = STAR_RE.search(line)
        if star:
            body = star.group(1).strip()
            if not _is_placeholder(body):
                starred.append(body)
            continue

        if in_disq and (line.startswith("- ") or line.startswith("·") or line.startswith("•")):
            item = line.lstrip("-·• ").strip()
            if not _is_placeholder(item):
                disqualifiers.append(item)
            continue

        if clause_kind:
            next_kind = _ingest_requirement_line(line, clause_kind, clauses)
            if next_kind is not None:
                clause_kind = next_kind
                continue

    if not scoring:
        for raw in lines:
            if "分）" in raw or "分)" in raw:
                heading = HEADING_RE.match(raw.strip())
                if heading:
                    scoring.append(ScoringPoint(title=heading.group(2).strip()))

    if title == "Untitled requirement":
        title = _fallback_title(lines)

    clauses = _dedupe_clauses(clauses)
    _promote_must_clauses(clauses, starred)

    summary_bits = [title]
    if scoring:
        summary_bits.append(f"{len(scoring)} scoring points")
    if disqualifiers:
        summary_bits.append(f"{len(disqualifiers)} disqualification items")
    if starred:
        summary_bits.append(f"{len(starred)} starred must-respond clauses")
    if clauses:
        summary_bits.append(f"{len(clauses)} requirement clauses")

    return Brief(
        title=title,
        toc=_dedupe(toc),
        scoring_points=scoring,
        disqualifiers=_dedupe(disqualifiers),
        starred_requirements=_dedupe(starred),
        requirement_clauses=clauses,
        summary="; ".join(summary_bits),
        source_path=source_path,
    )


def pdf_to_text(path: Path) -> str:
    """Extract text from a PDF on this machine. Never uploads the file."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import FileNotDecryptedError, PdfReadError
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise IngestError(
            "PDF ingest requires pypdf. Install with: pip install 'prd-ai-battle[dev]' or pip install pypdf"
        ) from exc

    try:
        reader = PdfReader(str(path))
    except FileNotDecryptedError as exc:
        raise IngestError(f"PDF is encrypted and cannot be opened locally: {path}") from exc
    except (PdfReadError, OSError) as exc:
        raise IngestError(f"Could not parse PDF locally: {path} ({exc})") from exc

    if getattr(reader, "is_encrypted", False):
        try:
            if reader.decrypt("") == 0:
                raise IngestError(f"PDF is encrypted and cannot be opened locally: {path}")
        except IngestError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise IngestError(f"PDF is encrypted and cannot be opened locally: {path}") from exc

    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            extracted = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            raise IngestError(f"Failed to extract text from PDF page {index} of {path}: {exc}") from exc
        chunk = extracted.strip()
        if not chunk:
            continue
        if len(reader.pages) > 1:
            pages.append(f"[page {index}]\n{chunk}")
        else:
            pages.append(chunk)

    text = "\n\n".join(pages).strip()
    if not text:
        raise IngestError(
            f"No extractable text in {path}. This command reads the PDF text layer locally "
            "(pypdf) and does not OCR scanned image-only files."
        )
    return text + "\n"


def read_requirement_text(path: Path) -> str:
    """Load a 招标 file as text. PDFs are parsed locally; raw bytes are never returned."""
    path = Path(path)
    if not path.is_file():
        raise IngestError(f"Requirement not found: {path}")
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return pdf_to_text(path)
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8")
    raise IngestError(
        f"Unsupported requirement type {suffix or path.name!r}. "
        "Use a .pdf (parsed locally) or .md tender."
    )


def load_requirement(path: Path) -> tuple[str, Brief]:
    text = read_requirement_text(path)
    return text, extract_brief(text, source_path=str(path))


def bundled_sample_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "tender.md"


def _compact(line: str) -> str:
    return re.sub(r"\s+", "", line)


def _is_placeholder(text: str) -> bool:
    return not text or bool(PLACEHOLDER_RE.match(text.strip()))


def _normalize_heading(name: str) -> str:
    compact = _compact(name)
    compact = re.sub(r"^[★☆*]+", "", compact)
    compact = re.sub(r"^\d+", "", compact)
    return compact.strip("（）()：:、/ ")


def _is_context_heading(name: str) -> bool:
    norm = _normalize_heading(name)
    return any(norm == token or norm.startswith(token) for token in _CONTEXT_HEADINGS)


def _heading_kind(name: str) -> str | None:
    norm = _normalize_heading(name)
    if not norm:
        return None
    for kind, labels in _CLAUSE_KIND_LABELS:
        for label in labels:
            lab = _compact(label)
            if norm == lab or norm.startswith(lab):
                return kind
    return None


def _split_category_prefix(body: str) -> tuple[str | None, str]:
    text = body.strip()
    text = text.lstrip("*_ ").rstrip("*_ ")
    for kind, labels in _CLAUSE_KIND_LABELS:
        for label in labels:
            if text == label or text.startswith(label):
                rest = text[len(label) :].lstrip("：:、，, \t")
                return kind, rest
    return None, text


def _format_clause(kind: str, text: str) -> str:
    label = _KIND_PREFIX.get(kind, "")
    body = text.strip()
    if not label:
        return body
    if body.startswith(label):
        return body
    return f"{label}：{body}"


def _ingest_requirement_line(
    line: str, clause_kind: str, clauses: list[RequirementClause]
) -> str | None:
    """Consume a body line under a requirement heading. Return the (possibly updated) kind."""
    if line.startswith("|") or line.startswith("[page "):
        return clause_kind
    item = LIST_ITEM_RE.match(line)
    if item:
        body = item.group(1).strip()
        kind, rest = _split_category_prefix(body)
        if kind and not rest:
            return kind
        use_kind = kind or clause_kind
        text = rest if kind else body
        if _is_placeholder(text):
            return use_kind
        clauses.append(RequirementClause(kind=use_kind, text=_format_clause(use_kind, text)))
        return use_kind
    if _is_prose_clause(line):
        kind, rest = _split_category_prefix(line)
        use_kind = kind or clause_kind
        text = rest if kind and rest else (rest or line)
        if kind and not rest:
            return kind
        if not _is_placeholder(text):
            clauses.append(RequirementClause(kind=use_kind, text=_format_clause(use_kind, text)))
        return use_kind
    return clause_kind


def _is_prose_clause(line: str) -> bool:
    if HEADING_RE.match(line) or line.startswith("|"):
        return False
    if _is_placeholder(line):
        return False
    if "。" in line or "；" in line or ";" in line:
        return True
    return len(_compact(line)) >= 8


def _dedupe_clauses(items: list[RequirementClause]) -> list[RequirementClause]:
    seen: set[str] = set()
    out: list[RequirementClause] = []
    for item in items:
        key = _compact(item.text)
        if not key or _is_placeholder(item.text) or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _promote_must_clauses(clauses: list[RequirementClause], starred: list[str]) -> None:
    """必须 items also fill ★ 必须响应条款 so the brief is not `(none)`."""
    existing = {_compact(s) for s in starred}
    for clause in clauses:
        if clause.kind != "must":
            continue
        key = _compact(clause.text)
        if key and key not in existing:
            starred.append(clause.text)
            existing.add(key)


def _is_toc_marker(line: str) -> bool:
    return _compact(line).rstrip("：:") in {"目录", "目次"}


def _is_disq_marker(line: str) -> bool:
    return any(hint in _compact(line) for hint in DISQUALIFIER_HINTS)


def _is_disq_bare_section(line: str) -> bool:
    """Plain-text 废标 heading (PDF extract) — not a prose sentence."""
    if any(ch in line for ch in "。，；;"):
        return False
    compact = _compact(line)
    if not any(hint in compact for hint in DISQUALIFIER_HINTS):
        return False
    return len(compact) <= 24


def _fallback_title(lines: list[str]) -> str:
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("[page "):
            continue
        heading = HEADING_RE.match(line)
        if heading:
            return heading.group(2).strip()
        return line.lstrip("# ").strip()
    return "Untitled requirement"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
