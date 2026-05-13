"""
md_to_docx.py — Render a Markdown file into a Word DOCX, preserving a letterhead
================================================================================
Opens a `.docx` letterhead template (with its header, footer, page setup, logo,
and section configuration), strips the body, and re-renders Markdown content
into it. Headings, paragraphs, lists, tables, fenced code, and horizontal rules
are mapped to direct-formatted runs and paragraphs — independent of the
template's Word style definitions — so the visual output is determined entirely
by the brand spec (optional TOML), not by the letterhead's built-in styles.

The script ships with **neutral defaults** (black text, default fonts, neutral
table shading) so it works as a generic MD→DOCX tool on any letterhead. For
branded output, pass `--config` pointing to a TOML file overriding any of:

    [fonts]
    body    = "Inter"
    heading = "DM Serif Display"   # optional — falls back to body if omitted
    mono    = "JetBrains Mono"

    [colors]                       # hex strings, no '#' prefix
    primary           = "2E86AB"   # H1/H2, accents, table header bg, list markers, HR & H1 borders, inline code
    body              = "333333"   # body text, H3/H4, code block text, table body
    muted             = "777777"   # italic-only paragraphs (epigraphs)
    table_row_alt     = "F2F8FB"   # alternating table row shade
    table_border      = "C5DEE8"   # table body cell borders
    table_header_text = "FFFFFF"   # table header text (typically contrast vs. primary)
    code_block_bg     = "F4F4F4"   # fenced code block background
    generic_border    = "DDDDDD"   # default border colour where not overridden

    [headings]
    sizes = [22, 16, 13, 12]       # H1..H4 in pt

All keys are optional; omitted keys fall back to neutral defaults.

Usage:
    python3 md_to_docx.py INPUT.md --letterhead TEMPLATE.docx --output OUT.docx
                          [--config BRAND.toml]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from markdown_it import MarkdownIt


# ----------------------------------------------------------------------------
# Brand spec
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class BrandSpec:
    body_font: str
    heading_font: str
    mono_font: str
    primary: RGBColor
    primary_hex: str
    body_color: RGBColor
    muted: RGBColor
    table_row_alt_hex: str
    table_border_hex: str
    table_header_text: RGBColor
    code_block_bg_hex: str
    generic_border_hex: str
    heading_sizes: tuple[int, int, int, int]


NEUTRAL_DEFAULTS: dict = {
    "fonts": {
        "body": "Calibri",
        "heading": "Calibri",
        "mono": "Consolas",
    },
    "colors": {
        "primary": "000000",
        "body": "000000",
        "muted": "555555",
        "table_row_alt": "F2F2F2",
        "table_border": "DDDDDD",
        "table_header_text": "FFFFFF",
        "code_block_bg": "F4F4F4",
        "generic_border": "DDDDDD",
    },
    "headings": {
        "sizes": [22, 16, 13, 12],
    },
}


def _hex_to_rgb(hex_str: str) -> RGBColor:
    s = hex_str.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"Expected 6-char hex, got {hex_str!r}")
    return RGBColor(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def load_brand(config_path: Path | None) -> BrandSpec:
    spec: dict = {
        section: dict(values) for section, values in NEUTRAL_DEFAULTS.items()
    }
    if config_path is not None:
        with open(config_path, "rb") as f:
            overrides = tomllib.load(f)
        for section, values in overrides.items():
            if section in spec and isinstance(values, dict):
                spec[section].update(values)
            else:
                spec[section] = values

    sizes_raw = spec["headings"]["sizes"]
    if len(sizes_raw) != 4:
        raise ValueError(f"headings.sizes must have 4 values (H1..H4), got {sizes_raw}")

    primary_hex = spec["colors"]["primary"].lstrip("#").upper()
    return BrandSpec(
        body_font=spec["fonts"]["body"],
        heading_font=spec["fonts"].get("heading", spec["fonts"]["body"]),
        mono_font=spec["fonts"]["mono"],
        primary=_hex_to_rgb(primary_hex),
        primary_hex=primary_hex,
        body_color=_hex_to_rgb(spec["colors"]["body"]),
        muted=_hex_to_rgb(spec["colors"]["muted"]),
        table_row_alt_hex=spec["colors"]["table_row_alt"].lstrip("#").upper(),
        table_border_hex=spec["colors"]["table_border"].lstrip("#").upper(),
        table_header_text=_hex_to_rgb(spec["colors"]["table_header_text"]),
        code_block_bg_hex=spec["colors"]["code_block_bg"].lstrip("#").upper(),
        generic_border_hex=spec["colors"]["generic_border"].lstrip("#").upper(),
        heading_sizes=tuple(int(s) for s in sizes_raw),  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------------------
# DOCX primitives
# ----------------------------------------------------------------------------


def clear_body(doc) -> None:
    """Remove all paragraphs/tables from the document body but keep the trailing
    sectPr (page setup, header/footer references)."""
    body = doc.element.body
    for child in list(body):
        if child.tag == qn("w:sectPr"):
            continue
        body.remove(child)


def set_run(
    run,
    *,
    font: str,
    size: int = 11,
    color: RGBColor | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
) -> None:
    run.font.name = font
    rPr = run._r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        rFonts.set(qn("w:" + attr), font)
    run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = color
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def set_paragraph_spacing(p, *, before: int = 0, after: int = 4, line: float = 1.25) -> None:
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line


def set_cell_shading(cell, hex_color: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def set_cell_borders(cell, *, color: str, size: str = "4") -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        b = OxmlElement(f"w:{edge}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), size)
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), color)
        tcBorders.append(b)
    tcPr.append(tcBorders)


def set_table_borders(table, *, color: str, size: str = "4") -> None:
    tbl = table._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    existing = tblPr.find(qn("w:tblBorders"))
    if existing is not None:
        tblPr.remove(existing)
    tblBorders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{edge}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), size)
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), color)
        tblBorders.append(b)
    tblPr.append(tblBorders)


def add_bottom_border(p, *, color_hex: str, size: str = "8", space: str = "4") -> None:
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), space)
    bottom.set(qn("w:color"), color_hex)
    pBdr.append(bottom)
    pPr.append(pBdr)


def add_paragraph_shading(p, *, fill_hex: str) -> None:
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    pPr.append(shd)


# ----------------------------------------------------------------------------
# Inline rendering
# ----------------------------------------------------------------------------


def render_inline_into_paragraph(
    p,
    inline_token,
    brand: BrandSpec,
    *,
    base_size: int = 11,
    base_color: RGBColor | None = None,
    font_override: str | None = None,
) -> None:
    if inline_token is None or not inline_token.children:
        return
    text_font = font_override if font_override is not None else brand.body_font
    bold = False
    italic = False
    for tok in inline_token.children:
        t = tok.type
        if t == "text":
            r = p.add_run(tok.content)
            set_run(r, font=text_font, size=base_size, color=base_color, bold=bold, italic=italic)
        elif t == "softbreak":
            r = p.add_run(" ")
            set_run(r, font=text_font, size=base_size, color=base_color)
        elif t == "hardbreak":
            r = p.add_run()
            r.add_break()
        elif t == "strong_open":
            bold = True
        elif t == "strong_close":
            bold = False
        elif t == "em_open":
            italic = True
        elif t == "em_close":
            italic = False
        elif t == "code_inline":
            r = p.add_run(tok.content)
            set_run(r, font=brand.mono_font, size=base_size - 1, color=brand.primary)
        elif t in ("link_open", "link_close", "s_open", "s_close"):
            pass
        else:
            if tok.content:
                r = p.add_run(tok.content)
                set_run(r, font=text_font, size=base_size, color=base_color, bold=bold, italic=italic)


# ----------------------------------------------------------------------------
# Block rendering
# ----------------------------------------------------------------------------


HEADING_SPACING = {
    1: {"before": 0, "after": 8},
    2: {"before": 18, "after": 6},
    3: {"before": 12, "after": 4},
    4: {"before": 8, "after": 2},
}


def heading_color(level: int, brand: BrandSpec) -> RGBColor:
    return brand.primary if level <= 2 else brand.body_color


def render(md_text: str, letterhead_path: Path, brand: BrandSpec):
    md = MarkdownIt("commonmark", {"html": False, "breaks": False, "linkify": False})
    md.enable("table")
    tokens = md.parse(md_text)

    doc = Document(str(letterhead_path))
    clear_body(doc)

    list_stack: list[dict] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        ttype = tok.type

        if ttype == "heading_open":
            level = int(tok.tag[1])
            inline = tokens[i + 1]
            size = brand.heading_sizes[min(level, 4) - 1]
            spacing = HEADING_SPACING.get(level, HEADING_SPACING[4])
            color = heading_color(level, brand)
            p = doc.add_paragraph()
            set_paragraph_spacing(p, before=spacing["before"], after=spacing["after"], line=1.2)
            try:
                p.style = doc.styles[f"Heading {level}"]
            except KeyError:
                pass
            if level == 1:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                add_bottom_border(p, color_hex=brand.primary_hex)
            render_inline_into_paragraph(
                p, inline, brand, base_size=size, base_color=color,
                font_override=brand.heading_font,
            )
            for r in p.runs:
                r.bold = True
            i += 3
            continue

        if ttype == "paragraph_open":
            inline = tokens[i + 1]
            inside_list = bool(list_stack)
            p = doc.add_paragraph()
            if inside_list:
                set_paragraph_spacing(p, before=0, after=2, line=1.25)
            else:
                set_paragraph_spacing(p, before=0, after=6, line=1.3)
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            children = inline.children or []
            only_em = (
                len(children) >= 2
                and children[0].type == "em_open"
                and children[-1].type == "em_close"
            )
            base_color = brand.muted if only_em else brand.body_color
            render_inline_into_paragraph(p, inline, brand, base_size=11, base_color=base_color)
            i += 3
            continue

        if ttype == "bullet_list_open":
            list_stack.append({"type": "ul", "level": len(list_stack)})
            i += 1
            continue
        if ttype == "ordered_list_open":
            list_stack.append(
                {
                    "type": "ol",
                    "level": len(list_stack),
                    "index": int(tok.attrGet("start") or 1),
                }
            )
            i += 1
            continue
        if ttype in ("bullet_list_close", "ordered_list_close"):
            list_stack.pop()
            i += 1
            continue

        if ttype == "list_item_open":
            current_list = list_stack[-1]
            depth = 1
            j = i + 1
            first_para_rendered = False
            while j < len(tokens) and depth > 0:
                tj = tokens[j]
                if tj.type == "list_item_open":
                    depth += 1
                elif tj.type == "list_item_close":
                    depth -= 1
                    if depth == 0:
                        break
                if depth == 1 and tj.type == "paragraph_open":
                    inline_tok = tokens[j + 1]
                    p = doc.add_paragraph()
                    indent = Cm(0.6 + 0.4 * (current_list["level"]))
                    p.paragraph_format.left_indent = indent
                    p.paragraph_format.first_line_indent = Cm(-0.45)
                    set_paragraph_spacing(p, before=0, after=3, line=1.3)
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    if not first_para_rendered:
                        if current_list["type"] == "ul":
                            mr = p.add_run("•  ")
                            set_run(mr, font=brand.body_font, size=11, color=brand.primary, bold=True)
                        else:
                            n = current_list["index"]
                            current_list["index"] = n + 1
                            mr = p.add_run(f"{n}. ")
                            set_run(mr, font=brand.body_font, size=11, color=brand.primary, bold=True)
                        first_para_rendered = True
                    render_inline_into_paragraph(
                        p, inline_tok, brand, base_size=11, base_color=brand.body_color
                    )
                    j += 3
                    continue
                j += 1
            i = j + 1
            continue

        if ttype == "table_open":
            j = i + 1
            cols = 0
            header_cells = []
            while tokens[j].type != "thead_close":
                if tokens[j].type == "th_open":
                    inline_tok = tokens[j + 1]
                    header_cells.append(inline_tok)
                    cols += 1
                j += 1
            body_rows = []
            current_cells = None
            while tokens[j].type != "table_close":
                if tokens[j].type == "tr_open":
                    current_cells = []
                elif tokens[j].type == "td_open":
                    inline_tok = tokens[j + 1]
                    current_cells.append(inline_tok)
                elif tokens[j].type == "tr_close":
                    if current_cells is not None:
                        body_rows.append(current_cells)
                    current_cells = None
                j += 1

            table = doc.add_table(rows=1 + len(body_rows), cols=cols)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = True
            set_table_borders(table, color=brand.generic_border_hex)

            for ci, inline_tok in enumerate(header_cells):
                cell = table.rows[0].cells[ci]
                set_cell_shading(cell, brand.primary_hex)
                set_cell_borders(cell, color=brand.primary_hex)
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                cell.paragraphs[0].text = ""
                p = cell.paragraphs[0]
                set_paragraph_spacing(p, before=2, after=2, line=1.2)
                render_inline_into_paragraph(
                    p, inline_tok, brand, base_size=10, base_color=brand.table_header_text
                )
                for r in p.runs:
                    r.bold = True
                    r.font.color.rgb = brand.table_header_text

            for ri, row in enumerate(body_rows, start=1):
                shade = brand.table_row_alt_hex if ri % 2 == 1 else "FFFFFF"
                for ci, inline_tok in enumerate(row):
                    if ci >= cols:
                        break
                    cell = table.rows[ri].cells[ci]
                    set_cell_shading(cell, shade)
                    set_cell_borders(cell, color=brand.table_border_hex)
                    cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
                    cell.paragraphs[0].text = ""
                    p = cell.paragraphs[0]
                    set_paragraph_spacing(p, before=2, after=2, line=1.25)
                    render_inline_into_paragraph(
                        p, inline_tok, brand, base_size=10, base_color=brand.body_color
                    )

            spacer = doc.add_paragraph()
            set_paragraph_spacing(spacer, before=0, after=6, line=1.0)
            i = j + 1
            continue

        if ttype == "hr":
            p = doc.add_paragraph()
            set_paragraph_spacing(p, before=6, after=12, line=1.0)
            add_bottom_border(p, color_hex=brand.primary_hex, size="6", space="1")
            i += 1
            continue

        if ttype in ("fence", "code_block"):
            p = doc.add_paragraph()
            set_paragraph_spacing(p, before=4, after=8, line=1.25)
            add_paragraph_shading(p, fill_hex=brand.code_block_bg_hex)
            r = p.add_run(tok.content.rstrip())
            set_run(r, font=brand.mono_font, size=10, color=brand.body_color)
            i += 1
            continue

        i += 1

    return doc


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render a Markdown file into a Word DOCX, preserving a letterhead template.",
    )
    parser.add_argument("input", type=Path, help="Source Markdown file")
    parser.add_argument(
        "--letterhead",
        "-l",
        type=Path,
        required=True,
        help="Letterhead DOCX template (header, footer, section setup are preserved)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Output DOCX path",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help="Optional brand spec TOML (fonts, colors, heading sizes). "
        "Omitted keys fall back to neutral defaults.",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 2
    if not args.letterhead.is_file():
        print(f"error: letterhead not found: {args.letterhead}", file=sys.stderr)
        return 2
    if args.config is not None and not args.config.is_file():
        print(f"error: config not found: {args.config}", file=sys.stderr)
        return 2

    brand = load_brand(args.config)
    md_text = args.input.read_text(encoding="utf-8")
    doc = render(md_text, args.letterhead, brand)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(args.output))
    print(f"Saved: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
