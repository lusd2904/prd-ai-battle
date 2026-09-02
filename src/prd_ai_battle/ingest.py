"""Ingest a long requirement and extract a shared brief.

Models receive the brief (目录 / 评分点 / 废标项), not the raw tender.
PDF files are parsed locally — the raw PDF is never sent to advisors.
"""

from __future__ import annotations

import re
from pathlib import Path

from prd_ai_battle.models import Brief, ScoringPoint

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
SCORE_LINE_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(\d+(?:\.\d+)?)\s*\|")
SCORE_PLAIN_RE = re.compile(r"^(.+?)[：:\s]+(\d+(?:\.\d+)?)分(?:\s|$)")
DISQUALIFIER_HINTS = ("废标", "否决", "投标无效", "无效投标")
STAR_RE = re.compile(r"^★\s*(.+)")
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
PDF_SUFFIXES = {".pdf"}


class IngestError(ValueError):
    """Raised when a requirement file cannot be read or has no extractable text."""


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
            if _is_toc_marker(name):
                in_toc = True
                in_disq = False
                continue
            in_toc = False
            in_disq = _is_disq_marker(name)
            if level in {"#", "##"} and name != title:
                toc.append(name)
            continue

        if _is_toc_marker(line):
            in_toc = True
            in_disq = False
            continue

        if _is_disq_bare_section(line):
            in_toc = False
            in_disq = True
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
            starred.append(star.group(1).strip())

        if in_disq and (line.startswith("- ") or line.startswith("·") or line.startswith("•")):
            disqualifiers.append(line.lstrip("-·• ").strip())

    if not scoring:
        for raw in lines:
            if "分）" in raw or "分)" in raw:
                heading = HEADING_RE.match(raw.strip())
                if heading:
                    scoring.append(ScoringPoint(title=heading.group(2).strip()))

    if title == "Untitled requirement":
        title = _fallback_title(lines)

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
