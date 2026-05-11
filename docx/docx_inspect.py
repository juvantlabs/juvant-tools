"""
docx_inspect.py — Dump the structure of a DOCX file for visual review
======================================================================
Re-opens a generated DOCX and prints its header/footer content, paragraph
style histogram, heading outline, table layout, and page setup. Useful as
a sanity check after rendering with `md_to_docx.py` (or any other DOCX
producer) to confirm the letterhead's header/footer survived, paragraph
styles map to the expected `Heading N`, and tables came out at the
expected row/column counts.

Pure inspection — no modifications, no output files.

Usage:
    python3 docx_inspect.py PATH.docx
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


def inspect(path: Path) -> None:
    doc = Document(str(path))

    print("=== HEADERS ===")
    for sec_idx, section in enumerate(doc.sections):
        print(f"Section {sec_idx}:")
        for kind, hdr in (
            ("default header", section.header),
            ("first-page header", section.first_page_header),
            ("even-page header", section.even_page_header),
        ):
            drawings = hdr.part.element.findall(".//" + qn("w:drawing"))
            texts = [t.text for t in hdr.part.element.findall(".//" + qn("w:t")) if t.text]
            print(
                f"  {kind}: drawings={len(drawings)}, "
                f"text_runs={len(texts)}, sample={texts[:3]}"
            )

    print("\n=== FOOTERS ===")
    for sec_idx, section in enumerate(doc.sections):
        print(f"Section {sec_idx}:")
        for kind, ftr in (
            ("default footer", section.footer),
            ("first-page footer", section.first_page_footer),
            ("even-page footer", section.even_page_footer),
        ):
            texts = [t.text for t in ftr.part.element.findall(".//" + qn("w:t")) if t.text]
            print(f"  {kind}: text_runs={len(texts)}, sample={texts[:5]}")

    print("\n=== BODY ===")
    para_styles: Counter[str] = Counter()
    heading_titles: list[tuple[str, str]] = []
    for p in doc.paragraphs:
        para_styles[p.style.name] += 1
        if p.style.name.startswith("Heading"):
            heading_titles.append((p.style.name, p.text[:60]))
    print("Paragraphs by style:")
    for name, n in sorted(para_styles.items(), key=lambda x: -x[1]):
        print(f"  {name}: {n}")
    print(f"\nTotal paragraphs: {len(doc.paragraphs)}")
    print(f"Total tables: {len(doc.tables)}")
    for ti, t in enumerate(doc.tables):
        print(f"  Table {ti}: rows={len(t.rows)}, cols={len(t.columns)}")
        hdr = [c.text[:30] for c in t.rows[0].cells]
        print(f"    header: {hdr}")
    print("\nFirst 12 headings:")
    for s, t in heading_titles[:12]:
        print(f"  [{s}] {t}")

    print("\n=== PAGE SETUP ===")
    sec = doc.sections[0]
    print(f"  page width: {sec.page_width}")
    print(f"  page height: {sec.page_height}")
    print(
        f"  margins T/R/B/L: {sec.top_margin} / {sec.right_margin} / "
        f"{sec.bottom_margin} / {sec.left_margin}"
    )
    print("\nOK")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dump the structure of a DOCX file for visual review.",
    )
    parser.add_argument("path", type=Path, help="DOCX file to inspect")
    args = parser.parse_args()

    if not args.path.is_file():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2

    inspect(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
