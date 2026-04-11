#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Convert HWP/HML drawing objects into .gtree JSON for web-image-editor-object."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


XSL_NS = {"xsl": "http://www.w3.org/1999/XSL/Transform"}
SVG_SCALE = 0.035
UNICODE_SUBSCRIPT_MAP = str.maketrans({
    "0": "₀",
    "1": "₁",
    "2": "₂",
    "3": "₃",
    "4": "₄",
    "5": "₅",
    "6": "₆",
    "7": "₇",
    "8": "₈",
    "9": "₉",
    "+": "₊",
    "-": "₋",
    "=": "₌",
    "(": "₍",
    ")": "₎",
})


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def load_hml2html_module(script_path: Path):
    spec = importlib.util.spec_from_file_location("hml2html_mod", script_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def strip_namespaces(elem: ET.Element) -> ET.Element:
    for node in elem.iter():
        if "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]
        node.attrib = {
            (k.split("}", 1)[1] if "}" in k else k): v
            for k, v in node.attrib.items()
        }
    return elem


def extract_shape_from_xsl(xsl_root: ET.Element, tag_name: str, position: str):
    template = xsl_root.find(f".//xsl:template[@match='{tag_name}']", XSL_NS)
    if template is None:
        return None

    for if_node in template.findall("xsl:if", XSL_NS):
        if if_node.get("test", "") != f"@position='{position}'":
            continue
        for nested in if_node.findall("xsl:if", XSL_NS):
            for child in list(nested):
                if isinstance(child.tag, str) and local_name(child.tag) == tag_name:
                    return strip_namespaces(copy.deepcopy(child))
    return None


def build_expanded_container(xml_path: Path, xsl_path: Path) -> ET.Element:
    src_root = strip_namespaces(ET.parse(xml_path).getroot())
    xsl_root = ET.parse(xsl_path).getroot()

    src_container = src_root.find(".//CONTAINER")
    if src_container is None:
        raise SystemExit("CONTAINER not found in XML")

    container = ET.Element("CONTAINER", dict(src_container.attrib))
    for child in list(src_container):
        tag_name = local_name(child.tag)
        if tag_name == "SHAPEOBJECT":
            container.append(copy.deepcopy(child))
            continue

        expanded = extract_shape_from_xsl(xsl_root, tag_name, child.get("position", ""))
        if expanded is not None:
            container.append(expanded)

    return container


def parse_hml_containers(root: ET.Element) -> list[ET.Element]:
    root = strip_namespaces(root)
    containers: list[ET.Element] = []
    for container in root.findall(".//CONTAINER"):
        # Embedded HML already contains full shape definitions under the container.
        if any(child.find("DRAWINGOBJECT") is not None for child in list(container)):
            containers.append(container)
    return containers


def parse_hml_direct_shapes(root: ET.Element) -> list[ET.Element]:
    root = strip_namespaces(root)
    shapes: list[ET.Element] = []
    for node in root.findall(".//BODY/SECTION/P/TEXT/*"):
        tag = local_name(node.tag)
        if tag in {"PICTURE"} and node.find("SHAPECOMPONENT") is not None:
            shapes.append(node)
        elif tag in {"ARC", "CURVE", "POLYGON", "LINE", "CONNECTLINE", "ELLIPSE", "RECTANGLE"} and node.find("DRAWINGOBJECT") is not None:
            shapes.append(node)
    return shapes


def color_from_hwp_int(color_int: str | None) -> str:
    try:
        value = int(color_int or "0")
    except ValueError:
        return "#000000"
    value &= 0xFFFFFF
    r = value & 0xFF
    g = (value >> 8) & 0xFF
    b = (value >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def px(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or default) * SVG_SCALE
    except ValueError:
        return default


class GTreeBuilder:
    def __init__(self, hml2html_mod):
        self.hml2html = hml2html_mod
        self.objects: list[dict] = []
        self.next_id = 1
        self.min_x = math.inf
        self.min_y = math.inf
        self.max_x = -math.inf
        self.max_y = -math.inf
        self.warnings: list[str] = []

    def uid(self) -> int:
        current = self.next_id
        self.next_id += 1
        return current

    def update_bounds(self, x1: float, y1: float, x2: float, y2: float):
        self.min_x = min(self.min_x, x1)
        self.min_y = min(self.min_y, y1)
        self.max_x = max(self.max_x, x2)
        self.max_y = max(self.max_y, y2)

    def get_sc(self, elem: ET.Element):
        if local_name(elem.tag) == "PICTURE":
            return elem.find("SHAPECOMPONENT")
        drawing = elem.find("DRAWINGOBJECT")
        if drawing is None:
            return None
        return drawing.find("SHAPECOMPONENT")

    def image_data_uri(self, elem: ET.Element) -> str | None:
        image = elem.find("IMAGE")
        if image is None:
            return None
        bin_item_id = image.get("BinItem")
        if not bin_item_id:
            return None
        root = getattr(self, "_root", None)
        if root is None:
            return None
        fmt = "png"
        bin_item = root.find(f".//BINITEM[@BinData='{bin_item_id}']")
        if bin_item is not None:
            fmt = (bin_item.get("Format") or "png").lower()
        bindata = root.find(f".//BINDATA[@Id='{bin_item_id}']")
        if bindata is None or not (bindata.text and bindata.text.strip()):
            return None
        mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "webp": "image/webp",
            "svg": "image/svg+xml",
        }.get(fmt, "application/octet-stream")
        payload = "".join(bindata.text.split())
        return f"data:{mime};base64,{payload}"

    def apply_shape_position(self, elem: ET.Element, mat):
        shape_obj = elem.find("SHAPEOBJECT")
        pos = shape_obj.find("POSITION") if shape_obj is not None else None
        if pos is None:
            return mat
        dx = float(pos.get("HorzOffset", "0"))
        dy = float(pos.get("VertOffset", "0"))
        if dx == 0 and dy == 0:
            return mat
        trans = (1.0, 0.0, dx, 0.0, 1.0, dy)
        if mat is None:
            return trans
        return self.mat_mul(trans, mat)

    def mat_mul(self, a, b):
        return (
            a[0] * b[0] + a[1] * b[3],
            a[0] * b[1] + a[1] * b[4],
            a[0] * b[2] + a[1] * b[5] + a[2],
            a[3] * b[0] + a[4] * b[3],
            a[3] * b[1] + a[4] * b[4],
            a[3] * b[2] + a[4] * b[5] + a[5],
        )

    def get_render_matrix(self, sc: ET.Element):
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
            mat = self.mat_mul(mat, cur)
        return mat

    def apply_mat(self, mat, x: float, y: float):
        if mat is None:
            return px(str(x)), px(str(y))
        tx = mat[0] * x + mat[1] * y + mat[2]
        ty = mat[3] * x + mat[4] * y + mat[5]
        return px(str(tx)), px(str(ty))

    def transformed_bbox(self, sc: ET.Element, mat):
        ow = float(sc.get("OriWidth", sc.get("CurWidth", "100")))
        oh = float(sc.get("OriHeight", sc.get("CurHeight", "100")))
        corners = [
            self.apply_mat(mat, 0.0, 0.0),
            self.apply_mat(mat, ow, 0.0),
            self.apply_mat(mat, 0.0, oh),
            self.apply_mat(mat, ow, oh),
        ]
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        return min(xs), min(ys), max(xs), max(ys)

    def line_style(self, elem: ET.Element) -> tuple[str, float, str, str]:
        drawing = elem.find("DRAWINGOBJECT")
        shape = drawing.find("LINESHAPE") if drawing is not None else None
        if shape is None:
            return "#000000", 1.5, "none", "none"

        stroke = color_from_hwp_int(shape.get("Color"))
        if shape.get("Alpha") == "255":
            stroke = "none"
        width = max(0.5, px(shape.get("Width"), 141.0) * 0.4)

        style = shape.get("Style", "Solid")
        if style == "Dot":
            dash = "dotted"
        elif style == "Dash":
            dash = "dashed"
        else:
            dash = "none"

        tail = shape.get("TailStyle", "Normal")
        head = shape.get("HeadStyle", "Normal")
        if tail == "Arrow" and head == "Arrow":
            arrow = "both"
        elif tail == "Arrow":
            arrow = "end"
        elif head == "Arrow":
            arrow = "start"
        else:
            arrow = "none"
        return stroke, width, dash, arrow

    def fill_style(self, elem: ET.Element) -> tuple[str, bool, int]:
        drawing = elem.find("DRAWINGOBJECT")
        brush = drawing.find("WINDOWBRUSH") if drawing is not None else None
        if brush is None and drawing is not None:
            brush = drawing.find("./FILLBRUSH/WINDOWBRUSH")
        if brush is None:
            return "#ffffff", True, 100

        alpha = int(brush.get("Alpha", "0") or "0")
        if alpha >= 255:
            return color_from_hwp_int(brush.get("FaceColor")), True, 100
        fill_opacity = max(0, min(100, round((255 - alpha) * 100 / 255)))
        return color_from_hwp_int(brush.get("FaceColor")), False, fill_opacity

    def control_point_to_local(self, sc: ET.Element, cp: ET.Element):
        ow = float(sc.get("OriWidth", sc.get("CurWidth", "100")))
        oh = float(sc.get("OriHeight", sc.get("CurHeight", "100")))
        raw_x = float(cp.get("X", "0"))
        raw_y = float(cp.get("Y", "0"))
        if 0.0 <= raw_x <= 100.0 and 0.0 <= raw_y <= 100.0:
            return ow * raw_x / 100.0, oh * raw_y / 100.0
        return raw_x, raw_y

    def text_style(self, elem: ET.Element, box_h: float) -> tuple[float, str, bool]:
        char_shape_id = None
        for text_node in elem.iter("TEXT"):
            char_shape_id = text_node.get("CharShape")
            if char_shape_id:
                break
        fs = max(12, min(28, round(box_h * 0.55)))
        tc = "#1a1a18"
        bold = False
        if char_shape_id:
            root = getattr(self, "_root", None)
            if root is not None:
                cs = root.find(f".//CHARSHAPE[@Id='{char_shape_id}']")
                if cs is not None:
                    fs = max(fs, round(float(cs.get("Height", "1000")) / 40.0))
                    tc = color_from_hwp_int(cs.get("TextColor", "0"))
                    bold = cs.find("BOLD") is not None
        return fs, tc, bold

    def normalize_label_text(self, text: str) -> str:
        text = text.replace("`", " ")
        text = " ".join(text.split())
        text = text.replace(" _", "_").replace("_ ", "_")
        text = text.replace("{ ", "{").replace(" }", "}")
        text = text.replace(" ,", ",")
        text = text.replace("( ", "(").replace(" )", ")")
        text = text.strip()
        text = text.replace("x0", "x_{0}").replace("x1", "x_{1}")
        text = text.replace("y0", "y_{0}").replace("y1", "y_{1}")
        text = re.sub(r"_\{([^{}]+)\}", lambda m: m.group(1).translate(UNICODE_SUBSCRIPT_MAP), text)
        return text

    def label_objects(self, elem: ET.Element, xpos: float, ypos: float, cw: float, ch: float):
        text = "".join(c.text or "" for c in elem.iter("CHAR")).strip()
        scripts = [s.text.strip() for s in elem.iter("SCRIPT") if s.text and s.text.strip()]
        if scripts:
            text = scripts[0]
        if not text:
            return
        text = self.normalize_label_text(text)
        fs, tc, bold = self.text_style(elem, ch)
        self.objects.append({
            "id": self.uid(),
            "type": "text",
            "x": round(xpos + cw / 2),
            "y": round(ypos + ch / 2),
            "text": text,
            "fs": fs,
            "tc": tc,
            "bold": bold,
            "italic": False,
            "align": "middle",
            "opacity": 1,
        })
        self.update_bounds(xpos, ypos, xpos + cw, ypos + ch)

    def add_rect(self, elem: ET.Element, bbox: tuple[float, float, float, float]):
        xpos, ypos, x2, y2 = bbox
        cw, ch = x2 - xpos, y2 - ypos
        stroke, sw, _, _ = self.line_style(elem)
        fill, fill_none, fill_opacity = self.fill_style(elem)
        obj = {
            "id": self.uid(),
            "type": "rect",
            "x": round(xpos),
            "y": round(ypos),
            "w": max(1, round(cw)),
            "h": max(1, round(ch)),
            "rx": 3,
            "stroke": stroke,
            "sw": round(sw, 2),
            "fill": fill,
            "fillNone": fill_none,
            "fillOpacity": fill_opacity,
            "opacity": 1,
        }
        self.objects.append(obj)
        self.update_bounds(xpos, ypos, x2, y2)
        self.label_objects(elem, xpos, ypos, cw, ch)

    def add_ellipse(self, elem: ET.Element, sc: ET.Element, mat):
        stroke, sw, _, _ = self.line_style(elem)
        fill, fill_none, fill_opacity = self.fill_style(elem)
        center_x = float(elem.get("CenterX", sc.get("OriWidth", "0")))
        center_y = float(elem.get("CenterY", sc.get("OriHeight", "0")))
        axis_x = float(elem.get("Axis2X", "0")) or (float(sc.get("OriWidth", "0")) / 2.0)
        axis_y = float(elem.get("Axis1Y", "0")) or (float(sc.get("OriHeight", "0")) / 2.0)
        cx, cy = self.apply_mat(mat, center_x, center_y)
        px_rx, _ = self.apply_mat(mat, center_x + axis_x, center_y)
        _, py_ry = self.apply_mat(mat, center_x, center_y + axis_y)
        rx = max(4.5, abs(px_rx - cx))
        ry = max(4.5, abs(py_ry - cy))

        if abs(rx - ry) <= 1:
            obj = {
                "id": self.uid(),
                "type": "circle",
                "cx": round(cx),
                "cy": round(cy),
                "r": round(rx),
                "stroke": stroke,
                "sw": round(sw, 2),
                "fill": fill,
                "fillNone": fill_none,
                "fillOpacity": fill_opacity,
                "opacity": 1,
            }
        else:
            obj = {
                "id": self.uid(),
                "type": "ellipse",
                "cx": round(cx),
                "cy": round(cy),
                "rx": round(rx),
                "ry": round(ry),
                "stroke": stroke,
                "sw": round(sw, 2),
                "fill": fill,
                "fillNone": fill_none,
                "fillOpacity": fill_opacity,
                "opacity": 1,
            }
        self.objects.append(obj)
        self.update_bounds(cx - rx, cy - ry, cx + rx, cy + ry)

    def add_line_object(self, x1: float, y1: float, x2: float, y2: float, stroke: str, sw: float, dash: str, arrow: str):
        if math.hypot(x2 - x1, y2 - y1) < 1:
            return
        obj = {
            "id": self.uid(),
            "type": "line",
            "x1": round(x1),
            "y1": round(y1),
            "x2": round(x2),
            "y2": round(y2),
            "stroke": stroke,
            "sw": round(sw, 2),
            "dash": dash,
            "arrow": arrow,
            "opacity": 1,
        }
        self.objects.append(obj)
        self.update_bounds(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def add_line(self, elem: ET.Element, mat):
        stroke, sw, dash, arrow = self.line_style(elem)
        x1, y1 = self.apply_mat(mat, float(elem.get("StartX", "0")), float(elem.get("StartY", "0")))
        x2, y2 = self.apply_mat(mat, float(elem.get("EndX", "0")), float(elem.get("EndY", "0")))
        if elem.get("IsReverseHV", "false") == "true":
            x1, y1, x2, y2 = x2, y2, x1, y1
        self.add_line_object(x1, y1, x2, y2, stroke, sw, dash, arrow)

    def add_connectline(self, elem: ET.Element, sc: ET.Element, mat):
        stroke, sw, dash, arrow = self.line_style(elem)
        points = elem.findall("CONTROLPOINT")
        if len(points) >= 2:
            p1x, p1y = self.control_point_to_local(sc, points[0])
            p2x, p2y = self.control_point_to_local(sc, points[1])
            x1, y1 = self.apply_mat(mat, p1x, p1y)
            x2, y2 = self.apply_mat(mat, p2x, p2y)
            self.add_line_object(x1, y1, x2, y2, stroke, sw, dash, arrow)

    def add_polygon(self, elem: ET.Element, mat):
        stroke, sw, dash, _ = self.line_style(elem)
        fill, fill_none, fill_opacity = self.fill_style(elem)
        points = [self.apply_mat(mat, float(p.get("X", "0")), float(p.get("Y", "0"))) for p in elem.findall("POINT")]
        if len(points) < 2:
            return
        closed = len(points) >= 3 and not fill_none
        obj = {
            "id": self.uid(),
            "type": "polygon" if closed else "polyline",
            "points": [[round(x), round(y)] for x, y in points],
            "stroke": stroke,
            "sw": round(sw, 2),
            "dash": dash,
            "opacity": 1,
        }
        if closed:
            obj["fill"] = fill
            obj["fillNone"] = fill_none
            obj["fillOpacity"] = fill_opacity
        self.objects.append(obj)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        self.update_bounds(min(xs), min(ys), max(xs), max(ys))

    def add_curve(self, elem: ET.Element, mat):
        stroke, sw, dash, arrow = self.line_style(elem)
        segments = elem.findall("SEGMENT")
        if not segments:
            return
        points = []
        first = segments[0]
        points.append(self.apply_mat(mat, float(first.get("X1", "0")), float(first.get("Y1", "0"))))
        for seg in segments:
            points.append(self.apply_mat(mat, float(seg.get("X2", "0")), float(seg.get("Y2", "0"))))
        deduped = []
        for pt in points:
            if not deduped or abs(deduped[-1][0] - pt[0]) > 0.1 or abs(deduped[-1][1] - pt[1]) > 0.1:
                deduped.append(pt)
        if len(deduped) < 2:
            return
        obj = {
            "id": self.uid(),
            "type": "bezier",
            "points": [[round(x), round(y)] for x, y in deduped],
            "stroke": stroke,
            "sw": round(sw, 2),
            "dash": dash,
            "arrow": arrow,
            "opacity": 1,
        }
        self.objects.append(obj)
        xs = [p[0] for p in deduped]
        ys = [p[1] for p in deduped]
        self.update_bounds(min(xs), min(ys), max(xs), max(ys))

    def add_arc(self, elem: ET.Element, mat):
        stroke, sw, dash, _ = self.line_style(elem)
        center_x = float(elem.get("CenterX", "0"))
        center_y = float(elem.get("CenterY", "0"))
        start_local = (
            center_x + float(elem.get("Axis1X", "0")),
            center_y + float(elem.get("Axis1Y", "0")),
        )
        end_local = (
            center_x + float(elem.get("Axis2X", "0")),
            center_y + float(elem.get("Axis2Y", "0")),
        )
        cx, cy = self.apply_mat(mat, center_x, center_y)
        sx, sy = self.apply_mat(mat, *start_local)
        ex, ey = self.apply_mat(mat, *end_local)
        rx = max(1.0, abs(ex - cx))
        ry = max(1.0, abs(sy - cy))
        start_angle = math.degrees(math.atan2(sy - cy, sx - cx))
        end_angle = math.degrees(math.atan2(ey - cy, ex - cx))
        obj = {
            "id": self.uid(),
            "type": "arc",
            "cx": round(cx),
            "cy": round(cy),
            "rx": round(rx),
            "ry": round(ry),
            "startAngle": round(start_angle, 2),
            "endAngle": round(end_angle, 2),
            "stroke": stroke,
            "sw": round(sw, 2),
            "dash": dash,
            "opacity": 1,
        }
        self.objects.append(obj)
        self.update_bounds(cx - rx, cy - ry, cx + rx, cy + ry)

    def add_picture(self, elem: ET.Element, bbox: tuple[float, float, float, float]):
        href = self.image_data_uri(elem)
        if not href:
            self.warnings.append("PICTURE skipped: embedded image data not found")
            return
        xpos, ypos, x2, y2 = bbox
        obj = {
            "id": self.uid(),
            "type": "image",
            "x": round(xpos),
            "y": round(ypos),
            "w": max(1, round(x2 - xpos)),
            "h": max(1, round(y2 - ypos)),
            "href": href,
            "opacity": 1,
        }
        self.objects.append(obj)
        self.update_bounds(xpos, ypos, x2, y2)

    def consume_container(self, container: ET.Element):
        for child in list(container):
            self.consume_shape(child)

    def consume_shape(self, child: ET.Element):
        tag = local_name(child.tag)
        if tag in {"SHAPEOBJECT", "SHAPECOMPONENT"}:
            return

        sc = self.get_sc(child)
        if sc is None:
            return

        mat = self.apply_shape_position(child, self.get_render_matrix(sc))
        bbox = self.transformed_bbox(sc, mat)

        if tag == "RECTANGLE":
            self.add_rect(child, bbox)
        elif tag == "ELLIPSE":
            self.add_ellipse(child, sc, mat)
        elif tag == "LINE":
            self.add_line(child, mat)
        elif tag == "CONNECTLINE":
            self.add_connectline(child, sc, mat)
        elif tag == "POLYGON":
            self.add_polygon(child, mat)
        elif tag == "CURVE":
            self.add_curve(child, mat)
        elif tag == "ARC":
            self.add_arc(child, mat)
        elif tag == "PICTURE":
            self.add_picture(child, bbox)
        else:
            self.warnings.append(f"Unsupported shape type skipped: {tag}")

    def build(self) -> dict:
        if not self.objects:
            raise SystemExit("No supported drawing objects found.")

        pad = 20
        shift_x = pad - self.min_x
        shift_y = pad - self.min_y

        for obj in self.objects:
            if obj["type"] in {"rect", "image", "text"}:
                obj["x"] = round(obj["x"] + shift_x)
                obj["y"] = round(obj["y"] + shift_y)
            elif obj["type"] in {"circle", "ellipse", "arc"}:
                obj["cx"] = round(obj["cx"] + shift_x)
                obj["cy"] = round(obj["cy"] + shift_y)
            elif obj["type"] in {"polygon", "polyline", "bezier"}:
                obj["points"] = [[round(x + shift_x), round(y + shift_y)] for x, y in obj["points"]]
            else:
                obj["x1"] = round(obj["x1"] + shift_x)
                obj["y1"] = round(obj["y1"] + shift_y)
                obj["x2"] = round(obj["x2"] + shift_x)
                obj["y2"] = round(obj["y2"] + shift_y)

        cv_w = max(400, round(self.max_x - self.min_x + pad * 2))
        cv_h = max(300, round(self.max_y - self.min_y + pad * 2))
        return {
            "version": 1,
            "appName": "KS 이미지 에디터",
            "cvW": cv_w,
            "cvH": cv_h,
            "objects": self.objects,
            "meta": {
                "source": "hml_to_gtree.py",
                "warnings": self.warnings,
            },
        }


def collect_drawables(input_path: Path) -> tuple[list[ET.Element], list[ET.Element]]:
    suffix = input_path.suffix.lower()
    if suffix == ".xml":
        xsl_path = input_path.with_suffix(".xsl")
        if xsl_path.exists():
            return [build_expanded_container(input_path, xsl_path)], []
    root = ET.parse(input_path).getroot()
    return parse_hml_containers(root), parse_hml_direct_shapes(root)


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: python hml_to_gtree.py input.hml output.gtree")

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    script_path = input_path.with_name("hml2html.py")
    if not script_path.exists():
        script_path = Path(__file__).with_name("hml2html.py")

    containers, direct_shapes = collect_drawables(input_path)
    if not containers and not direct_shapes:
        raise SystemExit("No supported drawing objects found in HML/XML.")

    hml2html_mod = load_hml2html_module(script_path)
    builder = GTreeBuilder(hml2html_mod)
    builder._root = strip_namespaces(ET.parse(input_path).getroot())
    for container in containers:
        builder.consume_container(container)
    for shape in direct_shapes:
        builder.consume_shape(shape)

    output_path.write_text(
        json.dumps(builder.build(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(output_path)
    for warning in builder.warnings:
        print(f"warning: {warning}")


if __name__ == "__main__":
    main()
