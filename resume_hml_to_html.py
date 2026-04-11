from __future__ import annotations

"""Convert HWPML/HML documents into standalone HTML."""

import html
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


ALIGN_MAP = {
    "Left": "left",
    "Right": "right",
    "Center": "center",
    "Justify": "justify",
    "Distribute": "justify",
}

VERT_ALIGN_MAP = {
    "Top": "top",
    "Center": "middle",
    "Bottom": "bottom",
}

BORDER_STYLE_MAP = {
    "Solid": "solid",
    "Dot": "dotted",
    "None": "none",
}

SIDE_MAP = {
    "LEFTBORDER": "left",
    "RIGHTBORDER": "right",
    "TOPBORDER": "top",
    "BOTTOMBORDER": "bottom",
}

PAGE_MARGIN_REDUCTION_PX = 40.0
TABLE_HEIGHT_SCALE = 0.6


@dataclass
class HmlContext:
    para_shapes: dict[str, dict[str, str]]
    char_shapes: dict[str, dict[str, str]]
    fonts: dict[str, dict[str, str]]
    border_fills: dict[str, dict[str, dict[str, str]]]


@dataclass
class PageLayout:
    page_width_px: float | None
    page_height_px: float | None
    content_width_px: float | None
    content_height_px: float | None
    original_content_width_px: float | None
    original_content_height_px: float | None
    padding_top_px: float
    padding_right_px: float
    padding_bottom_px: float
    padding_left_px: float
    border_fill_id: str | None


def cleanup_text(text: str) -> str:
    text = "".join("인" if unicodedata.category(ch) == "Co" else ch for ch in text)
    text = text.replace("\xa0", " ")
    text = text.replace("\r", "")
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text


def hwp_unit_to_px(value: str | None) -> float | None:
    if not value:
        return None
    return round(int(value) / 75.0, 3)


def hwp_para_unit_to_px(value: str | None) -> float | None:
    if not value:
        return None
    return round(int(value) / 150.0, 3)


def hwp_percent_line_spacing_to_css(value: str | None, in_table_cell: bool = False) -> float | None:
    if not value:
        return None
    spacing = float(value) / 100.0
    if in_table_cell:
        # HWP percent line spacing renders tighter than CSS's equivalent unitless value.
        spacing *= 0.82
    return round(max(spacing, 1.0), 3)


def border_width_to_css(width: str | None) -> str:
    return width or "0"


def is_blank_text(text: str) -> bool:
    return not cleanup_text(text).strip()


def parse_context(root: ET.Element) -> HmlContext:
    para_shapes: dict[str, dict[str, str]] = {}
    for para_shape in root.findall(".//PARASHAPELIST/PARASHAPE"):
        data = dict(para_shape.attrib)
        for child in para_shape:
            data[child.tag] = dict(child.attrib)
        para_shapes[para_shape.get("Id", "")] = data

    char_shapes: dict[str, dict[str, str]] = {}
    for char_shape in root.findall(".//CHARSHAPELIST/CHARSHAPE"):
        data = dict(char_shape.attrib)
        for child in char_shape:
            data[child.tag] = dict(child.attrib)
        char_shapes[char_shape.get("Id", "")] = data

    fonts: dict[str, dict[str, str]] = {}
    for font_face in root.findall(".//FACENAMELIST/FONTFACE"):
        lang = font_face.get("Lang", "")
        for font in font_face.findall("FONT"):
            fonts.setdefault(font.get("Id", ""), {})[lang] = font.get("Name", "")

    border_fills: dict[str, dict[str, dict[str, str]]] = {}
    for border_fill in root.findall(".//BORDERFILLLIST/BORDERFILL"):
        border_fills[border_fill.get("Id", "")] = {
            child.tag: dict(child.attrib)
            for child in border_fill
            if child.tag in SIDE_MAP
        }

    return HmlContext(
        para_shapes=para_shapes,
        char_shapes=char_shapes,
        fonts=fonts,
        border_fills=border_fills,
    )


def parse_page_layout(root: ET.Element) -> PageLayout:
    section = root.find(".//BODY/SECTION")
    secdef = section.find("./P/TEXT/SECDEF") if section is not None else None

    page_def = None
    if secdef is not None:
        page_def = secdef.find("PAGEDEF")
    if page_def is None:
        page_def = next((node for node in root.findall(".//PAGEDEF") if node.find("PAGEMARGIN") is not None), None)

    page_width_px = None
    page_height_px = None
    padding_top_px = 0.0
    padding_right_px = 0.0
    padding_bottom_px = 0.0
    padding_left_px = 0.0
    if page_def is not None:
        page_width_px = hwp_unit_to_px(page_def.get("Width"))
        page_height_px = hwp_unit_to_px(page_def.get("Height"))
        margins = page_def.find("PAGEMARGIN")
        if margins is not None:
            padding_top_px = hwp_unit_to_px(margins.get("Top")) or 0.0
            padding_right_px = hwp_unit_to_px(margins.get("Right")) or 0.0
            padding_bottom_px = hwp_unit_to_px(margins.get("Bottom")) or 0.0
            padding_left_px = hwp_unit_to_px(margins.get("Left")) or 0.0

    padding_top_px = max(padding_top_px - PAGE_MARGIN_REDUCTION_PX, 0.0)
    padding_right_px = max(padding_right_px - PAGE_MARGIN_REDUCTION_PX, 0.0)
    padding_bottom_px = max(padding_bottom_px - PAGE_MARGIN_REDUCTION_PX, 0.0)
    padding_left_px = max(padding_left_px - PAGE_MARGIN_REDUCTION_PX, 0.0)

    border_fill_id = None
    if secdef is not None:
        for border_fill in secdef.findall("PAGEBORDERFILL"):
            if border_fill.get("Type") in {"Both", "Odd"}:
                border_fill_id = border_fill.get("BorferFill") or border_fill.get("BorderFill")
                if border_fill_id:
                    break

    content_width_px = None
    content_height_px = None
    original_content_width_px = None
    original_content_height_px = None
    if page_width_px is not None:
        original_content_width_px = max(page_width_px - (padding_left_px + PAGE_MARGIN_REDUCTION_PX) - (padding_right_px + PAGE_MARGIN_REDUCTION_PX), 0.0)
        content_width_px = max(page_width_px - padding_left_px - padding_right_px, 0.0)
    if page_height_px is not None:
        original_content_height_px = max(page_height_px - (padding_top_px + PAGE_MARGIN_REDUCTION_PX) - (padding_bottom_px + PAGE_MARGIN_REDUCTION_PX), 0.0)
        content_height_px = max(page_height_px - padding_top_px - padding_bottom_px, 0.0)

    return PageLayout(
        page_width_px=page_width_px,
        page_height_px=page_height_px,
        content_width_px=content_width_px,
        content_height_px=content_height_px,
        original_content_width_px=original_content_width_px,
        original_content_height_px=original_content_height_px,
        padding_top_px=padding_top_px,
        padding_right_px=padding_right_px,
        padding_bottom_px=padding_bottom_px,
        padding_left_px=padding_left_px,
        border_fill_id=border_fill_id,
    )


def inline_text_from_text_node(text_node: ET.Element) -> str:
    parts: list[str] = []
    if text_node.text:
        parts.append(text_node.text)
    for child in text_node:
        if child.tag == "CHAR":
            parts.append(child.text or "")
        if child.tail:
            parts.append(child.tail)
    return cleanup_text("".join(parts))


def char_shape_style(ctx: HmlContext, char_id: str | None) -> str:
    style_parts: list[str] = []

    char_shape = ctx.char_shapes.get(char_id or "", {})
    if char_shape:
        height = char_shape.get("Height")
        if height:
            style_parts.append(f"font-size:{float(height) / 100:.2f}pt")
        text_color = char_shape.get("TextColor")
        if text_color and text_color != "0":
            style_parts.append(f"color:#{int(text_color):06x}")
        font_id = char_shape.get("FONTID", {}).get("Hangul")
        font_name = ctx.fonts.get(font_id or "", {}).get("Hangul")
        if font_name:
            style_parts.append(f"font-family:{css_string(font_name)}")
        ratio = char_shape.get("RATIO", {}).get("Hangul")
        if ratio and ratio != "100":
            style_parts.append(f"font-stretch:{ratio}%")
            style_parts.append(f"transform:scaleX({float(ratio) / 100:.3f})")
        relsize = char_shape.get("RELSIZE", {}).get("Hangul")
        if relsize and relsize != "100":
            style_parts.append(f"font-size:{(float(height or 1000) / 100.0) * (float(relsize) / 100.0):.2f}pt")
        spacing = char_shape.get("CHARSPACING", {}).get("Hangul")
        if spacing and spacing != "0":
            style_parts.append(f"letter-spacing:{float(spacing) / 100:.3f}em")
        offset = char_shape.get("CHAROFFSET", {}).get("Hangul")
        if offset and offset != "0":
            style_parts.append(f"position:relative;top:{-(float(offset) / 100):.3f}em")
        if "BOLD" in char_shape:
            style_parts.append("font-weight:700")
        underline = char_shape.get("UNDERLINE")
        if underline and underline.get("Type") == "Bottom":
            style_parts.append("text-decoration:underline")
        if any(
            value and value != "100"
            for value in [ratio, relsize]
        ):
            style_parts.append("display:inline-block")

    return ";".join(style_parts)


def css_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def paragraph_plain_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for child in paragraph:
        if child.tag == "TEXT":
            parts.append(inline_text_from_text_node(child))
    return cleanup_text("".join(parts))


def para_style(
    ctx: HmlContext,
    para_id: str,
    include_margins: bool = True,
    in_table_cell: bool = False,
) -> str:
    style_parts: list[str] = []
    para = ctx.para_shapes.get(para_id, {})
    align = ALIGN_MAP.get(para.get("Align", ""))
    if align:
        style_parts.append(f"text-align:{align}")

    margins = para.get("PARAMARGIN", {})
    if include_margins:
        for css_name, key in (
            ("margin-left", "Left"),
            ("margin-right", "Right"),
            ("text-indent", "Indent"),
        ):
            px = hwp_para_unit_to_px(margins.get(key))
            if px and px != 0:
                style_parts.append(f"{css_name}:{px}px")

    line_spacing = margins.get("LineSpacing")
    if line_spacing and margins.get("LineSpacingType") == "Percent":
        css_spacing = hwp_percent_line_spacing_to_css(line_spacing, in_table_cell=in_table_cell)
        if css_spacing is not None:
            style_parts.append(f"line-height:{css_spacing:.3f}")

    return ";".join(style_parts)


def page_border_style(ctx: HmlContext, border_fill_id: str | None) -> str:
    if not border_fill_id:
        return ""
    border_fill = ctx.border_fills.get(border_fill_id, {})
    styles: list[str] = []
    for tag, css_side in SIDE_MAP.items():
        border = border_fill.get(tag)
        if not border:
            continue
        border_type = BORDER_STYLE_MAP.get(border.get("Type", "Solid"), "solid")
        width = border_width_to_css(border.get("Width"))
        if border_type == "none":
            styles.append(f"border-{css_side}:none")
        else:
            styles.append(f"border-{css_side}:{width} {border_type} #000")
    return ";".join(styles)


def render_distributed_text(
    text: str,
    run_style: str,
    left_margin_px: float = 0.0,
    right_margin_px: float = 0.0,
    css_class: str = "hwp-distribute",
) -> str:
    chars: list[str] = []
    for char in text:
        if char == " ":
            chars.append('<span class="hwp-char space">&nbsp;</span>')
        else:
            style_attr = f' style="{run_style}"' if run_style else ""
            chars.append(f'<span class="hwp-char"{style_attr}>{html.escape(char)}</span>')
    wrapper_style_parts = [
        f"margin-left:{left_margin_px}px" if left_margin_px else "",
        f"margin-right:{right_margin_px}px" if right_margin_px else "",
    ]
    if left_margin_px or right_margin_px:
        total_margin = left_margin_px + right_margin_px
        wrapper_style_parts.append(f"width:calc(100% - {total_margin:.3f}px)")
    wrapper_style = ";".join(part for part in wrapper_style_parts if part)
    style_attr = f' style="{wrapper_style}"' if wrapper_style else ""
    return f'<span class="{css_class}"{style_attr}>{"".join(chars)}</span>'


def render_text_run(
    ctx: HmlContext,
    text_node: ET.Element,
    distributed: bool,
    left_margin_px: float = 0.0,
    right_margin_px: float = 0.0,
) -> str:
    text = inline_text_from_text_node(text_node)
    if is_blank_text(text):
        return ""
    run_style = char_shape_style(ctx, text_node.get("CharShape"))
    if distributed:
        return render_distributed_text(text, run_style, left_margin_px, right_margin_px)
    plain_style = ";".join(part for part in [run_style, "white-space:pre"] if part)
    style_attr = f' style="{plain_style}"' if plain_style else ""
    return f"<span{style_attr}>{html.escape(text)}</span>"


def render_paragraph(ctx: HmlContext, paragraph: ET.Element, in_table_cell: bool = False) -> str:
    chunks: list[str] = []
    para = ctx.para_shapes.get(paragraph.get("ParaShape", ""), {})
    distributed = para.get("Align") == "Distribute"
    margins = para.get("PARAMARGIN", {})
    left_margin_px = hwp_para_unit_to_px(margins.get("Left")) or 0.0
    right_margin_px = hwp_para_unit_to_px(margins.get("Right")) or 0.0
    for child in paragraph:
        if child.tag != "TEXT":
            continue
        html_run = render_text_run(
            ctx,
            child,
            distributed=distributed,
            left_margin_px=left_margin_px,
            right_margin_px=right_margin_px,
        )
        if html_run:
            chunks.append(html_run)

    para_text_style = para_style(
        ctx,
        paragraph.get("ParaShape", ""),
        include_margins=not distributed,
        in_table_cell=in_table_cell,
    )
    if distributed:
        para_text_style = ";".join(
            part for part in [para_text_style, "text-align:initial"] if part
        )
    plain_text = paragraph_plain_text(paragraph)
    if plain_text.strip().startswith(tuple(f"{n}." for n in range(1, 10))):
        para_text_style = ";".join(part for part in [para_text_style, "margin-top:2em"] if part)
    style_attr = f' style="{para_text_style}"' if para_text_style else ""
    if not chunks:
        return f"<p{style_attr}>&nbsp;</p>"
    return f"<p{style_attr}>{''.join(chunks)}</p>"


def paragraph_height_px(ctx: HmlContext, paragraph: ET.Element) -> float:
    para = ctx.para_shapes.get(paragraph.get("ParaShape", ""), {})
    margins = para.get("PARAMARGIN", {})
    line_spacing = float(margins.get("LineSpacing", "160")) / 100.0
    max_font_pt = 10.0
    for text_node in paragraph.findall("TEXT"):
        char_shape = ctx.char_shapes.get(text_node.get("CharShape", ""), {})
        height = char_shape.get("Height")
        if height:
            max_font_pt = max(max_font_pt, float(height) / 100.0)
    return max((max_font_pt * (96.0 / 72.0) * line_spacing), 18.0)


def estimate_text_width_px(ctx: HmlContext, paragraph: ET.Element) -> float:
    text = paragraph_plain_text(paragraph)
    if not text.strip():
        return 0.0
    first_text = paragraph.find("TEXT")
    char_shape = ctx.char_shapes.get((first_text.get("CharShape") if first_text is not None else "") or "", {})
    font_size_pt = float(char_shape.get("Height", "1000")) / 100.0
    font_px = font_size_pt * (96.0 / 72.0)
    ratio = float(char_shape.get("RATIO", {}).get("Hangul", "100")) / 100.0
    spacing = float(char_shape.get("CHARSPACING", {}).get("Hangul", "0")) / 100.0
    relsize = float(char_shape.get("RELSIZE", {}).get("Hangul", "100")) / 100.0
    visible_chars = len(text.replace(" ", ""))
    spaces = len(text) - visible_chars
    base_char = font_px * relsize * ratio
    width = (visible_chars * base_char * 0.95) + (spaces * base_char * 0.7)
    if len(text) > 1:
        width += (len(text) - 1) * (font_px * spacing * 0.45)

    para = ctx.para_shapes.get(paragraph.get("ParaShape", ""), {})
    margins = para.get("PARAMARGIN", {})
    width += (hwp_para_unit_to_px(margins.get("Left")) or 0) + (hwp_para_unit_to_px(margins.get("Right")) or 0)
    if para.get("Align") == "Distribute":
        width += base_char * 2.2
    else:
        width += base_char * 1.2
    return width


def estimate_cell_required_width_px(ctx: HmlContext, cell: ET.Element) -> float:
    required = 0.0
    paralist = cell.find("PARALIST")
    if paralist is None:
        return 0.0
    for paragraph in paralist.findall("P"):
        required = max(required, estimate_text_width_px(ctx, paragraph))
    return required


def compute_column_widths(table: ET.Element) -> list[float]:
    col_count = int(table.get("ColCount", "0"))
    widths: list[float | None] = [None] * col_count
    constraints: list[tuple[int, int, float]] = []

    for cell in table.findall("./ROW/CELL"):
        col = int(cell.get("ColAddr", "0"))
        span = int(cell.get("ColSpan", "1"))
        width = hwp_unit_to_px(cell.get("Width"))
        if width is None:
            continue
        constraints.append((col, span, width))
        if span == 1 and 0 <= col < col_count:
            widths[col] = width

    progress = True
    while progress:
        progress = False
        for col, span, width in constraints:
            indices = [i for i in range(col, min(col + span, col_count))]
            unknown = [i for i in indices if widths[i] is None]
            if len(unknown) != 1:
                continue
            known_total = sum(widths[i] or 0 for i in indices if widths[i] is not None)
            widths[unknown[0]] = max(width - known_total, 0)
            progress = True

    unresolved = sorted(
        (
            (span, col, width)
            for col, span, width in constraints
            if span > 1 and any(widths[i] is None for i in range(col, min(col + span, col_count)))
        ),
        key=lambda item: item[0],
    )
    for span, col, width in unresolved:
        indices = [i for i in range(col, min(col + span, col_count))]
        unknown = [i for i in indices if widths[i] is None]
        if not unknown:
            continue
        known_total = sum(widths[i] or 0 for i in indices if widths[i] is not None)
        share = max(width - known_total, 0) / len(unknown)
        for i in unknown:
            widths[i] = share

    known_total = sum(w for w in widths if w is not None)
    missing = [i for i, w in enumerate(widths) if w is None]
    table_width = table_width_px(table)
    if missing:
        remaining = max((table_width or known_total) - known_total, 0)
        fallback = remaining / len(missing) if missing else 0
        for i in missing:
            widths[i] = fallback

    resolved = [w or 0 for w in widths]
    return resolved


def table_width_px(table: ET.Element) -> float | None:
    size = table.find("./SHAPEOBJECT/SIZE")
    if size is not None:
        return hwp_unit_to_px(size.get("Width"))

    row = table.find("ROW")
    if row is None:
        return None
    return sum(hwp_unit_to_px(cell.get("Width")) or 0 for cell in row.findall("CELL"))


def table_height_px(table: ET.Element) -> float | None:
    raw_height = raw_table_height_px(table)
    if raw_height is None:
        return None
    return round(raw_height * TABLE_HEIGHT_SCALE, 3)


def raw_table_height_px(table: ET.Element) -> float | None:
    size = table.find("./SHAPEOBJECT/SIZE")
    if size is not None:
        return hwp_unit_to_px(size.get("Height"))
    return None


def compute_row_heights(table: ET.Element) -> list[float]:
    rows = table.findall("ROW")
    row_heights: list[float] = [0.0] * len(rows)

    for row_index, row in enumerate(rows):
        max_height = 0.0
        for cell in row.findall("CELL"):
            if cell.get("RowSpan", "1") != "1":
                continue
            height = (hwp_unit_to_px(cell.get("Height")) or 0.0) * TABLE_HEIGHT_SCALE
            max_height = max(max_height, height)
        row_heights[row_index] = max_height

    changed = True
    while changed:
        changed = False
        for row_index, row in enumerate(rows):
            for cell in row.findall("CELL"):
                row_span = int(cell.get("RowSpan", "1"))
                if row_span <= 1:
                    continue
                total_height = (hwp_unit_to_px(cell.get("Height")) or 0.0) * TABLE_HEIGHT_SCALE
                span_end = min(row_index + row_span, len(rows))
                span_indices = list(range(row_index, span_end))
                unknown = [idx for idx in span_indices if row_heights[idx] == 0.0]
                if len(unknown) != 1:
                    continue
                known = sum(row_heights[idx] for idx in span_indices if row_heights[idx] != 0.0)
                row_heights[unknown[0]] = max(total_height - known, 0.0)
                changed = True

    for row_index, height in enumerate(row_heights):
        if height == 0.0:
            row_heights[row_index] = max(
                (hwp_unit_to_px(cell.get("Height")) or 0.0)
                for cell in rows[row_index].findall("CELL")
            ) * TABLE_HEIGHT_SCALE

    return row_heights


def table_cell_padding_values(table: ET.Element) -> tuple[float, float, float, float]:
    inside = table.find("INSIDEMARGIN")
    if inside is None:
        return (0.0, 0.0, 0.0, 0.0)
    top = hwp_unit_to_px(inside.get("Top")) or 0
    right = hwp_unit_to_px(inside.get("Right")) or 0
    bottom = hwp_unit_to_px(inside.get("Bottom")) or 0
    left = hwp_unit_to_px(inside.get("Left")) or 0
    return (top, right, bottom, left)


def table_cell_padding(table: ET.Element) -> str:
    top, right, bottom, left = table_cell_padding_values(table)
    if top == right == bottom == left == 0:
        return ""
    return f"{top}px {right}px {bottom}px {left}px"


def cell_style(
    ctx: HmlContext,
    cell: ET.Element,
    cell_padding: str = "",
    padding_values: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    use_cell_height: bool = True,
) -> str:
    styles: list[str] = []

    height = hwp_unit_to_px(cell.get("Height"))
    if height and use_cell_height:
        height *= TABLE_HEIGHT_SCALE
        top_pad, _, bottom_pad, _ = padding_values
        content_height = max(height - top_pad - bottom_pad, 0.0)
        styles.append(f"height:{content_height:.3f}px")
    if cell_padding:
        styles.append(f"padding:{cell_padding}")

    paralist = cell.find("PARALIST")
    if paralist is not None:
        vert_align = VERT_ALIGN_MAP.get(paralist.get("VertAlign", ""))
        if vert_align:
            styles.append(f"vertical-align:{vert_align}")

    border_fill = ctx.border_fills.get(cell.get("BorderFill", ""), {})
    for tag, css_side in SIDE_MAP.items():
        border = border_fill.get(tag)
        if not border:
            continue
        border_type = BORDER_STYLE_MAP.get(border.get("Type", "Solid"), "solid")
        width = border_width_to_css(border.get("Width"))
        if border_type == "none":
            styles.append(f"border-{css_side}:none")
        else:
            styles.append(f"border-{css_side}:{width} {border_type} #000")

    return ";".join(styles)


def render_cell_content(ctx: HmlContext, cell: ET.Element) -> str:
    paralist = cell.find("PARALIST")
    if paralist is None:
        return ""

    blocks: list[str] = []
    for paragraph in paralist.findall("P"):
        paragraph_html = render_paragraph(ctx, paragraph, in_table_cell=True)
        if paragraph_html:
            blocks.append(paragraph_html)

        for text_node in paragraph.findall("TEXT"):
            for child in text_node:
                if child.tag == "TABLE":
                    blocks.append(render_table(ctx, child))

    if not blocks:
        return "&nbsp;"
    return "".join(blocks)


def cell_contains_nested_table(cell: ET.Element) -> bool:
    return cell.find(".//TABLE") is not None


def render_table(ctx: HmlContext, table: ET.Element) -> str:
    width = table_width_px(table)
    height = table_height_px(table)
    table_styles = ["border-collapse:collapse", "table-layout:fixed"]
    if height:
        table_styles.append(f"height:{height:.3f}px")

    cell_padding_values = table_cell_padding_values(table)
    cell_padding = table_cell_padding(table)
    row_heights = compute_row_heights(table)
    rows_html: list[str] = []
    for row_index, row in enumerate(table.findall("ROW")):
        row_html: list[str] = []
        for cell in row.findall("CELL"):
            attrs: list[str] = []
            rowspan = cell.get("RowSpan", "1")
            colspan = cell.get("ColSpan", "1")
            if rowspan != "1":
                attrs.append(f' rowspan="{rowspan}"')
            if colspan != "1":
                attrs.append(f' colspan="{colspan}"')
            style = cell_style(
                ctx,
                cell,
                cell_padding=cell_padding,
                padding_values=cell_padding_values,
                use_cell_height=rowspan != "1",
            )
            if style:
                attrs.append(f' style="{style}"')
            if not cell_contains_nested_table(cell):
                attrs.append(' contenteditable="true"')
                attrs.append(' spellcheck="false"')
            row_html.append(f"<td{''.join(attrs)}>{render_cell_content(ctx, cell)}</td>")
        row_style = ""
        if row_index < len(row_heights) and row_heights[row_index] > 0:
            row_style = f' style="height:{row_heights[row_index]:.3f}px"'
        rows_html.append(f"<tr{row_style}>{''.join(row_html)}</tr>")

    widths = compute_column_widths(table)
    total_width = sum(widths)
    if width:
        table_styles.append(f"width:{width:.3f}px")
    else:
        table_styles.append(f"width:{total_width:.3f}px")
    colgroup = "".join(f'<col style="width:{w}px">' for w in widths)
    table_html = (
        f'<table style="{";".join(table_styles)}"><colgroup>{colgroup}</colgroup>'
        f"<tbody>{''.join(rows_html)}</tbody></table>"
    )
    return table_html


def block_height_px(ctx: HmlContext, paragraph: ET.Element) -> float:
    tables = [
        raw_table_height_px(child)
        for text_node in paragraph.findall("TEXT")
        for child in text_node
        if child.tag == "TABLE"
    ]
    table_heights = [height for height in tables if height]
    if table_heights:
        return sum(table_heights)
    return paragraph_height_px(ctx, paragraph)


def render_block(ctx: HmlContext, paragraph: ET.Element) -> str:
    blocks: list[str] = []
    for text_node in paragraph.findall("TEXT"):
        for child in text_node:
            if child.tag == "TABLE":
                blocks.append(render_table(ctx, child))

    if not blocks:
        para_html = render_paragraph(ctx, paragraph)
        if para_html:
            blocks.append(para_html)

    return "".join(blocks)


def render_page(ctx: HmlContext, content: str, layout: PageLayout, is_first_page: bool) -> str:
    styles: list[str] = []
    if not is_first_page:
        styles.append("margin-top:3em")
    if layout.page_width_px:
        styles.append(f"width:{layout.page_width_px:.3f}px")
    if layout.page_height_px:
        styles.append(f"min-height:{layout.page_height_px:.3f}px")
    styles.append(
        "padding:"
        f"{layout.padding_top_px:.3f}px "
        f"{layout.padding_right_px:.3f}px "
        f"{layout.padding_bottom_px:.3f}px "
        f"{layout.padding_left_px:.3f}px"
    )
    border_style = page_border_style(ctx, layout.border_fill_id)
    if border_style:
        styles.append(border_style)
    style_attr = f' style="{";".join(styles)}"' if styles else ""
    return f'<div class="page"{style_attr}>{content}</div>'


def build_document(root: ET.Element, title: str) -> str:
    ctx = parse_context(root)
    page_layout = parse_page_layout(root)

    body = root.find("BODY")
    if body is None:
        raise ValueError("BODY element not found")

    section = body.find("SECTION")
    if section is None:
        raise ValueError("SECTION element not found")

    page_blocks: list[list[str]] = [[]]
    current_height = 0.0
    max_content_height = page_layout.original_content_height_px or page_layout.content_height_px or 0.0
    for paragraph in section.findall("P"):
        block_height = block_height_px(ctx, paragraph)
        should_break = paragraph.get("PageBreak") == "true"
        if (
            not should_break
            and max_content_height > 0
            and current_height > 0
            and current_height + block_height > max_content_height
        ):
            should_break = True
        if should_break and page_blocks[-1]:
            page_blocks.append([])
            current_height = 0.0
        block_html = render_block(ctx, paragraph)
        if block_html:
            page_blocks[-1].append(block_html)
            current_height += block_height

    pages = [
        render_page(ctx, "".join(blocks), page_layout, is_first_page=(idx == 0))
        for idx, blocks in enumerate(page_blocks)
        if blocks
    ]

    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    body {{
      margin: 0;
      padding: 16px;
      background: #fff;
      color: #000;
      font-family: serif;
    }}
    .page {{
      box-sizing: border-box;
      background: #fff;
      overflow: hidden;
    }}
    table {{
      border-spacing: 0;
    }}
    td {{
      padding: 0;
      white-space: nowrap;
      overflow-wrap: normal;
      cursor: text;
    }}
    td:focus {{
      outline: 1px solid #3b82f6;
      outline-offset: -1px;
    }}
    p {{
      margin: 0;
      white-space: nowrap;
    }}
    .hwp-distribute {{
      display: flex;
      width: 100%;
      justify-content: space-between;
      align-items: center;
      flex-wrap: nowrap;
      gap: 0;
    }}
    .hwp-char {{
      flex: 0 0 auto;
      white-space: pre;
      transform-origin: center center;
    }}
    .hwp-char.space {{
      min-width: 0.5em;
    }}
  </style>
</head>
<body>
{''.join(pages)}
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    if len(argv) < 2 or len(argv) > 3:
        script_name = Path(argv[0]).name if argv else "hml_to_html.py"
        print(f"Usage: python {script_name} <input.hml> [output.html]")
        return 1

    input_path = Path(argv[1])
    output_path = (
        Path(argv[2])
        if len(argv) == 3
        else input_path.with_suffix(".html")
    )

    root = ET.parse(input_path).getroot()
    title = root.findtext("./HEAD/DOCSUMMARY/TITLE") or input_path.stem
    output_path.write_text(build_document(root, title), encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
