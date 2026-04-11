#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import html
import importlib.util
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


SVG_SCALE = 0.035
SVG_DISPLAY_SCALE = 2.0 / 3.0


def load_hml2html_module(script_path: Path):
    spec = importlib.util.spec_from_file_location("hml2html_mod", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_html(svg: str, title: str):
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script>
(function() {{
  function renderAllMath() {{
    document.querySelectorAll('span.math').forEach(function(el) {{
      katex.render(el.textContent, el, {{throwOnError: false, displayMode: false}});
    }});
  }}
  var script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js';
  script.onload = renderAllMath;
  document.head.appendChild(script);
}})();
</script>
<style>
  body {{
    margin: 0;
    padding: 24px;
    background: #fafafa;
    color: #222;
    font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif;
  }}
  .frame {{
    width: fit-content;
    margin: 0 auto;
    padding: 18px;
    background: white;
    border: 1px solid #ddd;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
  }}
  svg {{
    display: block;
    max-width: 100%;
    height: auto;
  }}
</style>
</head>
<body>
<div class="frame">
{svg}
</div>
</body>
</html>
"""


def build_graph_renderer(mod):
    hwp_script_to_latex = mod.hwp_script_to_latex
    color_from_int = mod.color_from_int

    def px(val):
        return float(val) * SVG_SCALE

    def get_sc(elem):
        do = elem.find("DRAWINGOBJECT")
        if do is None:
            return None
        return do.find("SHAPECOMPONENT")

    def mat_mul(a, b):
        return (
            a[0] * b[0] + a[1] * b[3],
            a[0] * b[1] + a[1] * b[4],
            a[0] * b[2] + a[1] * b[5] + a[2],
            a[3] * b[0] + a[4] * b[3],
            a[3] * b[1] + a[4] * b[4],
            a[3] * b[2] + a[4] * b[5] + a[5],
        )

    def get_render_matrix(sc):
        ri = sc.find("RENDERINGINFO")
        if ri is None:
            return None
        mat = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        for child in list(ri):
            if child.tag not in ("TRANSMATRIX", "SCAMATRIX", "ROTMATRIX"):
                continue
            cur = (
                float(child.get("E1", "1")),
                float(child.get("E2", "0")),
                float(child.get("E3", "0")),
                float(child.get("E4", "0")),
                float(child.get("E5", "1")),
                float(child.get("E6", "0")),
            )
            mat = mat_mul(mat, cur)
        return mat

    def apply_mat(mat, x, y):
        if mat is None:
            return px(x), px(y)
        tx = mat[0] * x + mat[1] * y + mat[2]
        ty = mat[3] * x + mat[4] * y + mat[5]
        return px(tx), px(ty)

    def transformed_bbox(sc, mat):
        ow = float(sc.get("OriWidth", sc.get("CurWidth", "100")))
        oh = float(sc.get("OriHeight", sc.get("CurHeight", "100")))
        corners = [
            apply_mat(mat, 0.0, 0.0),
            apply_mat(mat, ow, 0.0),
            apply_mat(mat, 0.0, oh),
            apply_mat(mat, ow, oh),
        ]
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        return min(xs), min(ys), max(xs), max(ys)

    def get_lineshape(elem):
        do = elem.find("DRAWINGOBJECT")
        ls = do.find("LINESHAPE") if do is not None else None
        if ls is None:
            return "#000000", 1.5, "none", "none"
        color = color_from_int(ls.get("Color", "0"))
        if int(ls.get("Alpha", "0")) == 255:
            color = "none"
        width = max(0.5, float(ls.get("Width", "141")) * SVG_SCALE * 0.4)
        tail = ls.get("TailStyle", "Normal")
        head = ls.get("HeadStyle", "Normal")
        me = "url(#arr)" if head == "Arrow" else "none"
        ms = "url(#arr)" if tail == "Arrow" else "none"
        return color, width, ms, me

    def get_fill(elem):
        do = elem.find("DRAWINGOBJECT")
        wb = do.find("WINDOWBRUSH") if do is not None else None
        fb = do.find("./FILLBRUSH/WINDOWBRUSH") if do is not None else None
        wb = wb if wb is not None else fb
        if wb is None:
            return "none"
        if int(wb.get("Alpha", "0")) == 0:
            return "none"
        return color_from_int(wb.get("FaceColor", "16777215"))

    def get_label(elem):
        labels = []
        for sc2 in elem.iter("SCRIPT"):
            if sc2.text:
                labels.append(("eq", hwp_script_to_latex(sc2.text)))
        if not labels:
            combined = "".join(c.text for c in elem.iter("CHAR") if c.text and c.text.strip())
            if combined:
                labels.append(("text", combined))
        return labels

    def get_label_style():
        return {
            "font_family": "HCR Batang,'함초롬바탕',serif",
            "font_weight": "700",
            "fill": "#111111",
            "font_scale": 2.0,
        }

    def parse_simple_math_segments(text):
        normalized = text.replace(r"\,", " ")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        normalized = re.sub(r"([A-Za-z])\s*([01])\b", r"\1_{\2}", normalized)
        segments = []
        i = 0
        while i < len(normalized):
            ch = normalized[i]
            if ch == "\\":
                i += 1
                continue
            if i + 3 < len(normalized) and normalized[i + 1:i + 3] in ("_{", "^{"):
                kind = "sub" if normalized[i + 1] == "_" else "sup"
                base = ch
                j = i + 3
                depth = 1
                buf = []
                while j < len(normalized) and depth:
                    if normalized[j] == "{":
                        depth += 1
                        buf.append(normalized[j])
                    elif normalized[j] == "}":
                        depth -= 1
                        if depth:
                            buf.append(normalized[j])
                    else:
                        buf.append(normalized[j])
                    j += 1
                segments.append(("base", base))
                segments.append((kind, "".join(buf).strip()))
                i = j
                continue
            segments.append(("base", ch))
            i += 1
        return segments

    def can_render_as_svg_text(label_type, label_value):
        if label_type == "text":
            return True
        simple = label_value.replace(r"\,", " ")
        return re.fullmatch(r"[\(\), A-Za-z0-9_\{\}]+", simple) is not None

    def build_svg_text_label(label_value, x, y, w, h, label_style, fs, comment):
        segments = parse_simple_math_segments(label_value)
        parts = [
            f'  <!-- {comment} -->',
            f'  <text x="{x + w/2:.1f}" y="{y + h/2:.1f}" '
            f'fill="{label_style["fill"]}" '
            f'font-family="{label_style["font_family"]}" '
            f'font-weight="{label_style["font_weight"]}" '
            f'font-size="{fs:.0f}px" '
            f'text-anchor="middle" '
            f'dominant-baseline="middle">'
        ]
        for kind, value in segments:
            safe = html.escape(value)
            if kind == "base":
                parts.append(f'    <tspan baseline-shift="baseline">{safe}</tspan>')
            elif kind == "sub":
                parts.append(
                    f'    <tspan dx="{-fs * 0.22:.1f}" baseline-shift="-22%" font-size="{fs * 0.68:.1f}px">{safe}</tspan>'
                )
            else:
                parts.append(
                    f'    <tspan dx="{-fs * 0.20:.1f}" baseline-shift="32%" font-size="{fs * 0.68:.1f}px">{safe}</tspan>'
                )
        parts.append("  </text>")
        return "\n".join(parts)

    def control_point_to_local(sc, cp):
        ow = float(sc.get("OriWidth", sc.get("CurWidth", "100")))
        oh = float(sc.get("OriHeight", sc.get("CurHeight", "100")))
        raw_x = float(cp.get("X", "0"))
        raw_y = float(cp.get("Y", "0"))
        if 0.0 <= raw_x <= 100.0 and 0.0 <= raw_y <= 100.0:
            return ow * raw_x / 100.0, oh * raw_y / 100.0
        return raw_x, raw_y

    def curve_points(child, mat):
        """CURVE의 SEGMENT 끝점들을 순서대로 추출해 화면 좌표로 바꾼다."""
        segments = child.findall("SEGMENT")
        if not segments:
            return []
        pts = []
        first = segments[0]
        pts.append(apply_mat(mat, float(first.get("X1", "0")), float(first.get("Y1", "0"))))
        for seg in segments:
            pts.append(apply_mat(mat, float(seg.get("X2", "0")), float(seg.get("Y2", "0"))))
        deduped = []
        for pt in pts:
            if not deduped or abs(deduped[-1][0] - pt[0]) > 0.1 or abs(deduped[-1][1] - pt[1]) > 0.1:
                deduped.append(pt)
        return deduped

    def point_path(points):
        """주어진 점들을 HML에 나온 순서대로 그대로 잇는다."""
        if len(points) < 2:
            return ""
        d = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
        for x, y in points[1:]:
            d.append(f"L {x:.1f} {y:.1f}")
        return " ".join(d)

    def container_to_svg(container_elem):
        shapes = []

        for child in container_elem:
            tag = child.tag
            if tag in ("SHAPEOBJECT", "SHAPECOMPONENT"):
                continue
            sc = get_sc(child)
            if sc is None:
                continue

            mat = get_render_matrix(sc)
            bbox_x1, bbox_y1, bbox_x2, bbox_y2 = transformed_bbox(sc, mat)
            xpos, ypos = bbox_x1, bbox_y1
            cw, ch = bbox_x2 - bbox_x1, bbox_y2 - bbox_y1
            stroke, sw, ms, me = get_lineshape(child)
            fill = get_fill(child)
            me_a = f'marker-end="{me}"' if me != "none" else ""
            ms_a = f'marker-start="{ms}"' if ms != "none" else ""
            svg = ""
            bx1, by1, bx2, by2 = xpos, ypos, xpos + cw, ypos + ch

            if tag == "LINE":
                x1, y1 = apply_mat(mat, float(child.get("StartX", "0")), float(child.get("StartY", "0")))
                x2, y2 = apply_mat(mat, float(child.get("EndX", "0")), float(child.get("EndY", "0")))
                if child.get("IsReverseHV", "false") == "true":
                    x1, y1, x2, y2 = x2, y2, x1, y1
                style = child.find("./DRAWINGOBJECT/LINESHAPE")
                style_name = style.get("Style", "Solid") if style is not None else "Solid"
                dash = 'stroke-dasharray="4,4"' if style_name == "Dot" else 'stroke-dasharray="8,4"' if style_name == "Dash" else ""
                comment = "점선 선분 그리기" if style_name == "Dot" else "일반 선 그리기"
                bx1, by1, bx2, by2 = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
                svg = (
                    f'  <!-- {comment} -->\n'
                    f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                    f'stroke="{stroke}" stroke-width="{sw:.2f}" {dash} {me_a} {ms_a}/>'
                )

            elif tag == "CONNECTLINE":
                cps = child.findall("CONTROLPOINT")
                if len(cps) >= 2:
                    cx1, cy1 = control_point_to_local(sc, cps[0])
                    cx2, cy2 = control_point_to_local(sc, cps[1])
                    x1, y1 = apply_mat(mat, cx1, cy1)
                    x2, y2 = apply_mat(mat, cx2, cy2)
                    bx1, by1, bx2, by2 = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
                    svg = (
                        f'  <!-- 연결선 그리기 -->\n'
                        f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                        f'stroke="{stroke}" stroke-width="{sw:.2f}" {me_a} {ms_a}/>'
                    )

            elif tag == "ELLIPSE":
                center_x = float(child.get("CenterX", sc.get("OriWidth", "0")))
                center_y = float(child.get("CenterY", sc.get("OriHeight", "0")))
                axis_x = float(child.get("Axis2X", "0")) or (float(sc.get("OriWidth", "0")) / 2.0)
                axis_y = float(child.get("Axis1Y", "0")) or (float(sc.get("OriHeight", "0")) / 2.0)
                cx, cy = apply_mat(mat, center_x, center_y)
                px_rx, _ = apply_mat(mat, center_x + axis_x, center_y)
                _, py_ry = apply_mat(mat, center_x, center_y + axis_y)
                rx = max(4.5, abs(px_rx - cx))
                ry = max(4.5, abs(py_ry - cy))
                ell_fill = fill if fill != "none" else "#000000"
                bx1, by1, bx2, by2 = cx - rx, cy - ry, cx + rx, cy + ry
                svg = (
                    f'  <!-- 교점의 굵은 점 그리기 -->\n'
                    f'  <ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'fill="{ell_fill}" stroke="{stroke}" stroke-width="{sw:.2f}"/>'
                )

            elif tag == "RECTANGLE":
                labels = get_label(child)
                label_style = get_label_style()
                parts = [
                    '  <!-- 라벨 배치용 사각형 -->',
                    f'  <rect x="{xpos:.1f}" y="{ypos:.1f}" width="{cw:.1f}" height="{ch:.1f}" '
                    f'fill="none" stroke="none" stroke-width="{sw:.2f}"/>'
                ]
                for ltype, lval in labels:
                    fs = max(9, min(14, ch * 0.5)) * label_style["font_scale"]
                    fw = max(cw, 36)
                    fh = max(ch, 18)
                    box_x, box_y = xpos, ypos
                    if ltype == "text" or can_render_as_svg_text(ltype, lval):
                        parts.append(build_svg_text_label(
                            lval, box_x, box_y, fw, fh, label_style, fs,
                            "축 이름/좌표 라벨 텍스트" if ltype == "text" else "수식 라벨"
                        ))
                    else:
                        safe = html.escape(lval, quote=False)
                        parts.append('  <!-- 수식 라벨 -->')
                        parts.append(
                            f'  <foreignObject x="{box_x:.1f}" y="{box_y:.1f}" width="{fw:.1f}" height="{fh:.1f}">'
                            f'<div xmlns="http://www.w3.org/1999/xhtml" '
                            f'style="font-size:{fs:.0f}px;text-align:center;display:flex;align-items:center;justify-content:center;height:100%;">'
                            f'<span class="math">{safe}</span></div></foreignObject>'
                        )
                svg = "\n".join(parts)

            elif tag == "CURVE":
                pts = curve_points(child, mat)
                if pts:
                    bx1 = min(p[0] for p in pts)
                    by1 = min(p[1] for p in pts)
                    bx2 = max(p[0] for p in pts)
                    by2 = max(p[1] for p in pts)
                    path_d = point_path(pts)
                    svg = (
                        f'  <!-- 곡선 도형 그리기 -->\n'
                        f'  <path d="{path_d}" fill="none" stroke="{stroke}" stroke-width="{sw:.2f}" {me_a}/>'
                    )

            if svg:
                shapes.append((svg, bx1, by1, bx2, by2))

        if not shapes:
            return ""

        pad = 15
        vx = min(s[1] for s in shapes) - pad
        vy = min(s[2] for s in shapes) - pad
        vw = max(s[3] for s in shapes) - min(s[1] for s in shapes) + pad * 2
        vh = max(s[4] for s in shapes) - min(s[2] for s in shapes) + pad * 2
        disp_w = min(700, vw) * SVG_DISPLAY_SCALE
        disp_h = vh * (disp_w / vw)

        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xhtml="http://www.w3.org/1999/xhtml" '
            f'viewBox="{vx:.1f} {vy:.1f} {vw:.1f} {vh:.1f}" width="{disp_w:.0f}" height="{disp_h:.0f}" '
            f'style="display:block;margin:1em auto;overflow:visible;">',
            "  <!-- 화살표 마커 정의 -->",
            "  <defs>",
            '    <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">',
            '      <path d="M0,0 L0,6 L7,3 z" fill="#000"/>',
            "    </marker>",
            "  </defs>",
            "  <!-- 도형 본체 시작 -->",
        ]
        lines += [s[0] for s in shapes]
        lines.append("</svg>")
        return "\n".join(lines)

    return container_to_svg


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: python graph_hml_to_svg_html.py input.hml output.html")

    hml_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    script_path = hml_path.with_name("hml2html.py")

    mod = load_hml2html_module(script_path)
    root = ET.parse(hml_path).getroot()
    container = root.find(".//CONTAINER")
    if container is None:
        raise SystemExit("CONTAINER not found in HML")

    renderer = build_graph_renderer(mod)
    svg = renderer(container)
    if not svg:
        raise SystemExit("failed to render SVG from container")

    out_path.write_text(build_html(svg, hml_path.stem), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
