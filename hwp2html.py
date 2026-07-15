#!/usr/bin/env python3
"""End-to-end HWP -> HML -> editable GTree/SVG -> HTML converter."""

import argparse
import json
import re
from pathlib import Path

from hwpapi import App

from hml2html import HmlConverter


def export_hwp_sources(source: Path, output_dir: Path):
    hml_path = output_dir / f"{source.stem}.hml"
    reference_dir = output_dir / "native_reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    reference_html = reference_dir / "reference.html"

    with App() as app:
        document = app.docs.open(source)
        document.save_as(str(hml_path), format="HWPML2X")
        document.save_as(str(reference_html), format="HTML")
        document.close(save=False)

    fallback_images = []
    if reference_html.exists():
        raw = reference_html.read_bytes().decode("cp949", errors="replace")
        for match in re.finditer(r'src\s*=\s*["\']?([^"\' >]+)', raw, re.I):
            value = match.group(1).replace("\\", "/").removeprefix("./")
            candidate = reference_dir / value
            if candidate.suffix.lower() == ".gif" and candidate.exists():
                fallback_images.append(str(candidate))
    return hml_path, reference_html, fallback_images


def convert(source: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir = output_dir / "media"
    media_dir.mkdir(exist_ok=True)

    hml_path, reference_html, fallback_images = export_hwp_sources(source, output_dir)
    html_path = output_dir / f"{source.stem}.html"
    converter = HmlConverter(
        str(hml_path),
        media_dir=str(media_dir),
        fallback_images=fallback_images,
    )
    html_path.write_text(converter.convert(), encoding="utf-8")

    gtree_files = sorted(media_dir.glob("*.gtree"))
    svg_files = sorted(media_dir.glob("*.svg"))
    fallback_files = sorted(media_dir.glob("*_fallback.*"))
    report = {
        "source": str(source),
        "html": str(html_path),
        "hml": str(hml_path),
        "native_reference_html": str(reference_html),
        "containers": converter.container_counter,
        "editable_gtree": len(gtree_files),
        "editable_svg": len(svg_files),
        "gif_fallbacks": len(fallback_files),
        "equations": len(converter.eq_script_map),
        "footnotes": converter.footnote_counter,
        "embedded_images": len(converter.bin_images),
    }
    (output_dir / "conversion-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.exists():
        raise SystemExit(f"input not found: {source}")
    output = (args.output or source.with_name(source.stem + "_html")).resolve()
    print(json.dumps(convert(source, output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
