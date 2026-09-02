"""Generate a tiny Unicode PDF at test time — do not commit binary fixtures."""

from __future__ import annotations

from pathlib import Path


def write_text_pdf(path: Path, text: str) -> Path:
    """Write a one-page PDF whose pypdf extract_text() returns `text` (BMP Unicode)."""
    path = Path(path)
    lines = text.splitlines() or [""]
    content_ops = ["BT", "/F1 12 Tf", "50 750 Td"]
    for index, line in enumerate(lines):
        if index:
            content_ops.append("0 -14 Td")
        enc = "".join(f"{ord(ch):04X}" for ch in line if ord(ch) <= 0xFFFF)
        content_ops.append(f"<{enc}> Tj")
    content_ops.append("ET")
    content = "\n".join(content_ops) + "\n"
    tounicode = (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\n"
        "begincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n"
        "/CMapType 2 def\n"
        "1 begincodespacerange\n"
        "<0000> <FFFF>\n"
        "endcodespacerange\n"
        "1 beginbfrange\n"
        "<0000> <FFFF> <0000>\n"
        "endbfrange\n"
        "endcmap\n"
        "CMapName currentdict /CMap defineresource pop\n"
        "end\n"
        "end\n"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}endstream",
        (
            "<< /Type /Font /Subtype /Type0 /BaseFont /IdentitySans "
            "/Encoding /Identity-H /DescendantFonts [6 0 R] /ToUnicode 8 0 R >>"
        ),
        (
            "<< /Type /Font /Subtype /CIDFontType2 /BaseFont /IdentitySans "
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            "/FontDescriptor 7 0 R /DW 500 >>"
        ),
        (
            "<< /Type /FontDescriptor /FontName /IdentitySans /Flags 32 "
            "/FontBBox [0 -200 1000 800] /ItalicAngle 0 /Ascent 800 /Descent -200 "
            "/CapHeight 700 /StemV 80 >>"
        ),
        f"<< /Length {len(tounicode.encode('latin-1'))} >>\nstream\n{tounicode}endstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


MINI_TENDER = """# XX市政务云资源池扩容项目招标文件（节选）

## 目录

1. 投标邀请
2. 评标办法（综合评分法）
3. 采购需求

## 3 评标办法（综合评分法）

| 评分点 | 分值 | 评分标准 |
| --- | --- | --- |
| 类似业绩 | 12 | 每提供 1 个合同得 4 分 |
| 认证资质 | 8 | ISO 27001 与 ISO 20000 |

## 4 废标 / 否决投标条款

- 投标报价超过预算金额 860 万元
- 未提供须知 2.2 要求的有效认证证书

## 5 采购需求（节选）

★ 5.1 扩容计算资源：不少于 200 台云主机。
★ 5.2 扩容存储：分布式块存储可用容量 ≥ 500TB。
"""
