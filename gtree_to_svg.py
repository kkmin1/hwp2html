#!/usr/bin/env python3
"""Render JSON-based .gtree drawing objects as a standalone SVG."""

import html
import json
import math
import sys
from pathlib import Path


def dash_attr(value):
    return {
        "dotted": ' stroke-dasharray="2 4"',
        "dashed": ' stroke-dasharray="8 4"',
        "dash": ' stroke-dasharray="8 4"',
    }.get(str(value).lower(), "")


def opacity(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


def arc_path(obj):
    cx, cy = float(obj["cx"]), float(obj["cy"])
    rx, ry = abs(float(obj["rx"])), abs(float(obj["ry"]))
    start, end = float(obj["startAngle"]), float(obj["endAngle"])
    a1, a2 = math.radians(start), math.radians(end)
    x1, y1 = cx + rx * math.cos(a1), cy + ry * math.sin(a1)
    x2, y2 = cx + rx * math.cos(a2), cy + ry * math.sin(a2)
    delta = (end - start) % 360
    large = 1 if delta > 180 else 0
    return f"M {x1:.2f} {y1:.2f} A {rx:.2f} {ry:.2f} 0 {large} 1 {x2:.2f} {y2:.2f}"


def render(data):
    width = float(data.get("cvW", 1000))
    height = float(data.get("cvH", 800))
    body = []
    for obj in data.get("objects", []):
        kind = obj.get("type")
        alpha = opacity(obj.get("opacity", 1))
        stroke = obj.get("stroke", "#000000")
        sw = float(obj.get("sw", 1))
        dash = dash_attr(obj.get("dash"))
        if kind == "line":
            arrow = str(obj.get("arrow", "none")).lower()
            start = ' marker-start="url(#arrow)"' if arrow in {"start", "both"} else ""
            end = ' marker-end="url(#arrow)"' if arrow in {"end", "both"} else ""
            body.append(
                f'<line x1="{obj["x1"]}" y1="{obj["y1"]}" x2="{obj["x2"]}" y2="{obj["y2"]}" '
                f'stroke="{stroke}" stroke-width="{sw}" opacity="{alpha}"{dash}{start}{end}/>'
            )
        elif kind == "arc":
            body.append(
                f'<path d="{arc_path(obj)}" fill="none" stroke="{stroke}" '
                f'stroke-width="{sw}" opacity="{alpha}"{dash}/>'
            )
        elif kind == "rect":
            fill = "none" if obj.get("fillNone") else obj.get("fill", "none")
            fill_alpha = float(obj.get("fillOpacity", 100)) / 100
            body.append(
                f'<rect x="{obj["x"]}" y="{obj["y"]}" width="{obj["w"]}" height="{obj["h"]}" '
                f'rx="{obj.get("rx", 0)}" fill="{fill}" fill-opacity="{fill_alpha}" '
                f'stroke="{stroke}" stroke-width="{sw}" opacity="{alpha}"/>'
            )
        elif kind == "text":
            anchor = {"left": "start", "middle": "middle", "right": "end"}.get(obj.get("align"), "middle")
            weight = "700" if obj.get("bold") else "400"
            style = "italic" if obj.get("italic") else "normal"
            body.append(
                f'<text x="{obj["x"]}" y="{obj["y"]}" text-anchor="{anchor}" dominant-baseline="middle" '
                f'font-size="{obj.get("fs", 12)}" font-weight="{weight}" font-style="{style}" '
                f'fill="{obj.get("tc", "#000000")}" opacity="{alpha}">{html.escape(str(obj.get("text", "")))}</text>'
            )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" '
        f'width="{width:g}" height="{height:g}" '
        f'style="display:block;max-width:100%;margin:0 auto">'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
        '<path d="M0,0 L0,6 L7,3 z" fill="#000000"/></marker></defs>'
        + "".join(body)
        + "</svg>"
    )


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: gtree_to_svg.py input.gtree output.svg")
    source, target = map(Path, sys.argv[1:])
    data = json.loads(source.read_text(encoding="utf-8"))
    target.write_text(render(data), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
