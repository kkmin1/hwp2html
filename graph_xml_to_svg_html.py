#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import copy
import html
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


XSL_NS = {"xsl": "http://www.w3.org/1999/XSL/Transform"}


def load_hml2html_module(script_path: Path):
    spec = importlib.util.spec_from_file_location("hml2html_mod", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def strip_namespaces(elem):
    for node in elem.iter():
        if "}" in node.tag:
            node.tag = node.tag.split("}", 1)[1]
        node.attrib = {
            (k.split("}", 1)[1] if "}" in k else k): v
            for k, v in node.attrib.items()
        }
    return elem


def extract_shape_from_xsl(xsl_root, tag_name: str, position: str):
    template = xsl_root.find(f".//xsl:template[@match='{tag_name}']", XSL_NS)
    if template is None:
        return None

    for if_node in template.findall("xsl:if", XSL_NS):
        test = if_node.get("test", "")
        if test != f"@position='{position}'":
            continue
        for nested in if_node.findall("xsl:if", XSL_NS):
            for child in list(nested):
                if isinstance(child.tag, str) and child.tag.endswith(tag_name):
                    return strip_namespaces(copy.deepcopy(child))
    return None


def build_expanded_container(xml_path: Path, xsl_path: Path):
    src_root = ET.parse(xml_path).getroot()
    xsl_root = ET.parse(xsl_path).getroot()

    src_container = src_root.find(".//CONTAINER")
    if src_container is None:
        raise SystemExit("CONTAINER not found in XML")

    container = ET.Element("CONTAINER", dict(src_container.attrib))
    for child in list(src_container):
        tag_name = child.tag.split("}", 1)[-1]
        if tag_name == "SHAPEOBJECT":
            container.append(copy.deepcopy(child))
            continue

        expanded = extract_shape_from_xsl(xsl_root, tag_name, child.get("position", ""))
        if expanded is not None:
            container.append(expanded)

    return container


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


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: python graph_xml_to_svg_html.py input.xml output.html")

    xml_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    xsl_path = xml_path.with_suffix(".xsl")
    script_path = xml_path.with_name("hml2html.py")

    mod = load_hml2html_module(script_path)
    container = build_expanded_container(xml_path, xsl_path)
    svg = mod.container_to_svg(container, {})
    if not svg:
        raise SystemExit("failed to render SVG from container")

    out_path.write_text(build_html(svg, xml_path.stem), encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
