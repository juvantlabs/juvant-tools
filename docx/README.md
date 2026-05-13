# docx/

Word DOCX rendering and inspection helpers. Standalone scripts — run
directly via `python3 docx/<script>.py`.

## Tools

| Script | What it does |
|---|---|
| [`md_to_docx.py`](md_to_docx.py) | Render a Markdown file into a Word DOCX using a `.docx` letterhead as the base (preserving its header, footer, logo, and section setup). Paragraphs, headings (H1–H4), lists (bullet + ordered, nested), tables, fenced code blocks, and horizontal rules are mapped to direct-formatted runs. Brand-customisable via optional `--config` TOML (fonts, colours, heading sizes) — see Brand spec below. |
| [`docx_inspect.py`](docx_inspect.py) | Dump the structure of any DOCX file: header/footer drawings + text, paragraph-style histogram, heading outline, table layout (rows/cols/header row), page setup. Pure inspection — no writes. |

## Prerequisites

```bash
pip install python-docx markdown-it-py
# Python 3.10 also needs:  pip install tomli
```

## Quick examples

```bash
# Generic render with neutral defaults (black text, default fonts)
python3 docx/md_to_docx.py input.md \
    --letterhead path/to/template.docx \
    --output out.docx

# Branded render with custom fonts/colours/heading sizes
python3 docx/md_to_docx.py input.md \
    --letterhead path/to/template.docx \
    --config path/to/brand.toml \
    --output out.docx

# Inspect the result
python3 docx/docx_inspect.py out.docx
```

## Brand spec

`md_to_docx.py --config` accepts a TOML file overriding any of the
neutral defaults. All keys are optional; omitted keys fall back to
neutral values.

```toml
[fonts]
body    = "Inter"
heading = "DM Serif Display"   # optional — falls back to body if omitted
mono    = "JetBrains Mono"

[colors]                       # hex strings, no '#' prefix
primary           = "2E86AB"   # H1/H2 headings, accents, table header bg, list markers, HR & H1 borders, inline code
body              = "333333"   # body text, H3/H4 headings, code block text, table body
muted             = "777777"   # italic-only paragraphs (epigraphs)
table_row_alt     = "F2F8FB"   # alternating table row shade
table_border      = "C5DEE8"   # table body cell borders
table_header_text = "FFFFFF"   # table header text (typically contrast vs. primary)
code_block_bg     = "F4F4F4"   # fenced code block background
generic_border    = "DDDDDD"   # default border colour where not overridden

[headings]
sizes = [22, 16, 13, 12]       # H1..H4 in pt
```

## Neutral defaults

If `--config` is omitted, the renderer uses:

| Section | Key | Default |
|---|---|---|
| fonts | body | `Calibri` |
| fonts | heading | same as `body` (falls back if omitted) |
| fonts | mono | `Consolas` |
| colors | primary | `000000` |
| colors | body | `000000` |
| colors | muted | `555555` |
| colors | table_row_alt | `F2F2F2` |
| colors | table_border | `DDDDDD` |
| colors | table_header_text | `FFFFFF` |
| colors | code_block_bg | `F4F4F4` |
| colors | generic_border | `DDDDDD` |
| headings | sizes | `[22, 16, 13, 12]` |

## What the renderer does NOT do

- Does not replace the letterhead's header / footer / logo — those are
  preserved verbatim from the template's section setup.
- Does not interpret HTML inside the Markdown source.
- Does not follow Markdown links (the link text is rendered, the URL is
  dropped). Hyperlink support is on the table for a future version.
- Does not handle nested lists deeper than the indentation calculation
  permits visually; deeply nested lists will render but with diminishing
  indent steps.
