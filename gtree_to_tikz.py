#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Convert KS image editor .gtree JSON into a TikZ .tex file.

The output style follows the coordinate convention used in web-tikz:
- 40 px == 1 cm
- y axis is flipped from screen coordinates into TikZ coordinates
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


PX_PER_CM = 40.0


def esc_tex(text: str) -> str:
    repl = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
    }
    out = []
    for ch in str(text):
        out.append(repl.get(ch, ch))
    return "".join(out)


def fmt_num(value: float) -> str:
    s = f"{value:.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def to_tikz_x(x: float) -> str:
    return fmt_num(x / PX_PER_CM)


def to_tikz_y(y: float, canvas_h: float) -> str:
    return fmt_num((canvas_h - y) / PX_PER_CM)


def color_opt(hex_color: str, prefix: str) -> tuple[list[str], str]:
    if not hex_color or hex_color == "none":
        return [], "none"
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return [], hex_color
    name = f"{prefix}{h.lower()}"
    return [rf"\definecolor{{{name}}}{{HTML}}{{{h.upper()}}}"], name


def line_style(obj: dict, stroke_name: str, extra: list[str] | None = None) -> str:
    parts = list(extra or [])
    parts.append(f"draw={stroke_name}")
    parts.append(f"line width={fmt_num((obj.get('sw', 1.5) / 1.5))}pt")
    dash = obj.get("dash", "none")
    if dash == "dashed":
        parts.append("dashed")
    elif dash == "dotted":
        parts.append("dotted")
    arrow = obj.get("arrow", "none")
    if arrow == "end":
        parts.append("->")
    elif arrow == "start":
        parts.append("<-")
    elif arrow == "both":
        parts.append("<->")
    opacity = obj.get("opacity", 1)
    if opacity != 1:
        parts.append(f"opacity={fmt_num(opacity)}")
    return ", ".join(parts)


def fill_parts(obj: dict, fill_name: str) -> list[str]:
    parts: list[str] = []
    if not obj.get("fillNone", False) and fill_name != "none":
        parts.append(f"fill={fill_name}")
        fill_opacity = obj.get("fillOpacity", 100)
        if fill_opacity < 100:
            parts.append(f"fill opacity={fmt_num(fill_opacity / 100)}")
    return parts


def polyline_draw(obj: dict, canvas_h: float, closed: bool) -> str:
    coords = [
        f"({to_tikz_x(x)}, {to_tikz_y(y, canvas_h)})"
        for x, y in obj.get("points", [])
    ]
    joiner = " -- ".join(coords)
    if closed:
        joiner += " -- cycle"
    return joiner


def catmull_rom_to_cubic(points: list[list[float]]) -> list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]]:
    if len(points) < 2:
        return []
    segments = []
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i > 0 else points[i]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else p2
        cp1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        cp2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        segments.append((cp1, cp2, (p2[0], p2[1])))
    return segments


def arc_endpoint(cx: float, cy: float, rx: float, ry: float, angle_deg: float) -> tuple[float, float]:
    rad = math.radians(angle_deg)
    return cx + rx * math.cos(rad), cy + ry * math.sin(rad)


def generate_tikz(data: dict) -> str:
    canvas_h = float(data.get("cvH", 600))
    lines: list[str] = []
    color_defs: list[str] = []
    seen_defs: set[str] = set()
    warnings: list[str] = []

    def add_defs(defs: list[str]):
        for line in defs:
            if line not in seen_defs:
                color_defs.append(line)
                seen_defs.add(line)

    body: list[str] = [r"\begin{tikzpicture}"]

    for obj in data.get("objects", []):
        otype = obj.get("type")
        stroke_defs, stroke_name = color_opt(obj.get("stroke", "#000000"), "draw")
        add_defs(stroke_defs)
        fill_defs, fill_name = color_opt(obj.get("fill", "#ffffff"), "fill")
        add_defs(fill_defs)
        text_defs, text_name = color_opt(obj.get("tc", "#000000"), "text")
        add_defs(text_defs)

        if otype == "line":
            style = line_style(obj, stroke_name)
            body.append(
                rf"  \draw[{style}] ({to_tikz_x(obj['x1'])}, {to_tikz_y(obj['y1'], canvas_h)}) -- ({to_tikz_x(obj['x2'])}, {to_tikz_y(obj['y2'], canvas_h)});"
            )
        elif otype == "polyline":
            style = line_style(obj, stroke_name)
            body.append(rf"  \draw[{style}] {polyline_draw(obj, canvas_h, False)};")
        elif otype == "polygon":
            style = line_style(obj, stroke_name, fill_parts(obj, fill_name))
            body.append(rf"  \draw[{style}] {polyline_draw(obj, canvas_h, True)};")
        elif otype == "rect":
            style = line_style(obj, stroke_name, fill_parts(obj, fill_name))
            x1, y1 = to_tikz_x(obj["x"]), to_tikz_y(obj["y"], canvas_h)
            x2, y2 = to_tikz_x(obj["x"] + obj["w"]), to_tikz_y(obj["y"] + obj["h"], canvas_h)
            body.append(rf"  \draw[{style}] ({x1}, {y1}) rectangle ({x2}, {y2});")
        elif otype == "circle":
            style = line_style(obj, stroke_name, fill_parts(obj, fill_name))
            body.append(
                rf"  \draw[{style}] ({to_tikz_x(obj['cx'])}, {to_tikz_y(obj['cy'], canvas_h)}) circle ({fmt_num(obj['r'] / PX_PER_CM)}cm);"
            )
        elif otype == "ellipse":
            style = line_style(obj, stroke_name, fill_parts(obj, fill_name))
            body.append(
                rf"  \draw[{style}] ({to_tikz_x(obj['cx'])}, {to_tikz_y(obj['cy'], canvas_h)}) ellipse ({fmt_num(obj['rx'] / PX_PER_CM)}cm and {fmt_num(obj['ry'] / PX_PER_CM)}cm);"
            )
        elif otype == "arc":
            style = line_style(obj, stroke_name)
            sx, sy = arc_endpoint(obj["cx"], obj["cy"], obj["rx"], obj["ry"], obj.get("startAngle", 0))
            body.append(
                rf"  \draw[{style}] ({to_tikz_x(sx)}, {to_tikz_y(sy, canvas_h)}) arc[start angle={fmt_num(-obj.get('startAngle', 0))}, end angle={fmt_num(-obj.get('endAngle', 0))}, x radius={fmt_num(obj['rx'] / PX_PER_CM)}cm, y radius={fmt_num(obj['ry'] / PX_PER_CM)}cm];"
            )
        elif otype == "text":
            fs = int(obj.get("fs", 14))
            opacity = obj.get("opacity", 1)
            extra = [f"text={text_name}", rf"font=\fontsize{{{fs}}}{{{fs+2}}}\selectfont"]
            if opacity != 1:
                extra.append(f"opacity={fmt_num(opacity)}")
            align = obj.get("align", "middle")
            if align == "start":
                extra.append("anchor=west")
            elif align == "end":
                extra.append("anchor=east")
            body.append(
                rf"  \node[{', '.join(extra)}] at ({to_tikz_x(obj['x'])}, {to_tikz_y(obj['y'], canvas_h)}) {{{esc_tex(obj.get('text', ''))}}};"
            )
        elif otype == "quadratic":
            style = line_style(obj, stroke_name)
            body.append(
                rf"  \draw[{style}] ({to_tikz_x(obj['x1'])}, {to_tikz_y(obj['y1'], canvas_h)}) .. controls ({to_tikz_x(obj['cx1'])}, {to_tikz_y(obj['cy1'], canvas_h)}) .. ({to_tikz_x(obj['x2'])}, {to_tikz_y(obj['y2'], canvas_h)});"
            )
        elif otype == "cubic":
            style = line_style(obj, stroke_name)
            body.append(
                rf"  \draw[{style}] ({to_tikz_x(obj['x1'])}, {to_tikz_y(obj['y1'], canvas_h)}) .. controls ({to_tikz_x(obj['cx1'])}, {to_tikz_y(obj['cy1'], canvas_h)}) and ({to_tikz_x(obj['cx2'])}, {to_tikz_y(obj['cy2'], canvas_h)}) .. ({to_tikz_x(obj['x2'])}, {to_tikz_y(obj['y2'], canvas_h)});"
            )
        elif otype == "bezier":
            points = obj.get("points", [])
            if len(points) < 2:
                continue
            style = line_style(obj, stroke_name)
            segs = catmull_rom_to_cubic(points)
            start = points[0]
            path = [rf"({to_tikz_x(start[0])}, {to_tikz_y(start[1], canvas_h)})"]
            for cp1, cp2, end in segs:
                path.append(
                    rf".. controls ({to_tikz_x(cp1[0])}, {to_tikz_y(cp1[1], canvas_h)}) and ({to_tikz_x(cp2[0])}, {to_tikz_y(cp2[1], canvas_h)}) .. ({to_tikz_x(end[0])}, {to_tikz_y(end[1], canvas_h)})"
                )
            body.append(rf"  \draw[{style}] " + " ".join(path) + ";")
        elif otype == "image":
            warnings.append("image objects are not converted to pure TikZ by this script")
            body.append(f"  % image skipped at ({obj.get('x')}, {obj.get('y')}) size {obj.get('w')}x{obj.get('h')}")
        else:
            warnings.append(f"unsupported object type: {otype}")
            body.append(f"  % unsupported object skipped: {otype}")

    body.append(r"\end{tikzpicture}")

    out = []
    if warnings:
        out.append("% warnings:")
        for w in warnings:
            out.append(f"% - {w}")
        out.append("")
    out.extend(color_defs)
    if color_defs:
        out.append("")
    out.extend(body)
    return "\n".join(out) + "\n"


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: python gtree_to_tikz.py input.gtree output.tex")
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    data = json.loads(input_path.read_text(encoding="utf-8"))
    output_path.write_text(generate_tikz(data), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
