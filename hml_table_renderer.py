from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Callable


BORDER_STYLE_MAP = {
    "Solid": "solid",
    "Dot": "dotted",
    "None": "none",
}

VERT_ALIGN_MAP = {
    "Top": "top",
    "Center": "middle",
    "Bottom": "bottom",
}

SIDE_MAP = {
    "LEFTBORDER": "left",
    "RIGHTBORDER": "right",
    "TOPBORDER": "top",
    "BOTTOMBORDER": "bottom",
}


def hwp_unit_to_px(value: str | None) -> float | None:
    if not value:
        return None
    return round(int(value) / 75.0, 3)


def border_width_to_css(width: str | None) -> str:
    return width or "0"


def table_width_px(table: ET.Element) -> float | None:
    size = table.find("./SHAPEOBJECT/SIZE")
    if size is not None:
        return hwp_unit_to_px(size.get("Width"))

    row = table.find("ROW")
    if row is None:
        return None
    return sum(hwp_unit_to_px(cell.get("Width")) or 0 for cell in row.findall("CELL"))


def raw_table_height_px(table: ET.Element) -> float | None:
    size = table.find("./SHAPEOBJECT/SIZE")
    if size is not None:
        return hwp_unit_to_px(size.get("Height"))
    return None


def table_height_px(table: ET.Element, height_scale: float = 1.0) -> float | None:
    raw_height = raw_table_height_px(table)
    if raw_height is None:
        return None
    return round(raw_height * height_scale, 3)


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
    total_width = table_width_px(table)
    if missing:
        remaining = max((total_width or known_total) - known_total, 0)
        fallback = remaining / len(missing) if missing else 0
        for i in missing:
            widths[i] = fallback

    return [w or 0 for w in widths]


def compute_row_heights(table: ET.Element, height_scale: float = 1.0) -> list[float]:
    rows = table.findall("ROW")
    row_heights: list[float] = [0.0] * len(rows)

    for row_index, row in enumerate(rows):
        max_height = 0.0
        for cell in row.findall("CELL"):
            if cell.get("RowSpan", "1") != "1":
                continue
            height = (hwp_unit_to_px(cell.get("Height")) or 0.0) * height_scale
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
                total_height = (hwp_unit_to_px(cell.get("Height")) or 0.0) * height_scale
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
            ) * height_scale

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
    cell: ET.Element,
    border_fills: dict[str, dict[str, dict[str, str]]],
    cell_padding: str = "",
    padding_values: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    use_cell_height: bool = True,
    height_scale: float = 1.0,
) -> str:
    styles: list[str] = []

    height = hwp_unit_to_px(cell.get("Height"))
    if height and use_cell_height:
        height *= height_scale
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

    border_fill = border_fills.get(cell.get("BorderFill", ""), {})
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


def render_table(
    table: ET.Element,
    border_fills: dict[str, dict[str, dict[str, str]]],
    render_cell_content: Callable[[ET.Element], str],
    *,
    height_scale: float = 1.0,
    editable: bool = False,
    editable_predicate: Callable[[ET.Element], bool] | None = None,
) -> str:
    width = table_width_px(table)
    height = table_height_px(table, height_scale=height_scale)
    table_styles = ["border-collapse:collapse", "table-layout:fixed"]
    if height:
        table_styles.append(f"height:{height:.3f}px")

    cell_padding_values = table_cell_padding_values(table)
    cell_padding = table_cell_padding(table)
    row_heights = compute_row_heights(table, height_scale=height_scale)
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
                cell,
                border_fills,
                cell_padding=cell_padding,
                padding_values=cell_padding_values,
                use_cell_height=rowspan != "1",
                height_scale=height_scale,
            )
            if style:
                attrs.append(f' style="{style}"')
            if editable and (editable_predicate(cell) if editable_predicate else True):
                attrs.append(' contenteditable="true"')
                attrs.append(' spellcheck="false"')
            row_html.append(f"<td{''.join(attrs)}>{render_cell_content(cell)}</td>")
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
    return (
        f'<table style="{";".join(table_styles)}"><colgroup>{colgroup}</colgroup>'
        f"<tbody>{''.join(rows_html)}</tbody></table>\n"
    )
