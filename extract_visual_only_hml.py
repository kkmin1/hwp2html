#!/usr/bin/env python3
"""
Extract image and drawing-object content from an HWPML/HML file.

This keeps only:
- PICTURE nodes (embedded images)
- CONTAINER nodes (grouped drawing objects)

It also trims BINDATA/BINITEM entries so the output HML only keeps
image payloads that are still referenced by extracted picture nodes.

Usage:
    python extract_visual_only_hml.py input.hml output.hml
"""

from __future__ import annotations

import argparse
import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def find_section(root: ET.Element) -> ET.Element:
    section = root.find("./BODY/SECTION")
    if section is None:
        raise ValueError("SECTION not found in HML file")
    return section


def collect_visual_nodes(paragraph: ET.Element) -> tuple[list[ET.Element], set[str]]:
    pictures = paragraph.findall(".//PICTURE")
    containers = paragraph.findall(".//CONTAINER")
    nodes = [copy.deepcopy(node) for node in (containers + pictures)]

    used_bindata_ids: set[str] = set()
    for picture in pictures:
        image = picture.find("./IMAGE") or picture.find(".//IMAGE")
        if image is not None:
            bin_item = image.get("BinItem")
            if bin_item:
                used_bindata_ids.add(bin_item)

    return nodes, used_bindata_ids


def build_visual_only_paragraph(source_paragraph: ET.Element, visual_nodes: list[ET.Element]) -> ET.Element:
    new_paragraph = ET.Element("P", source_paragraph.attrib)
    new_text = ET.SubElement(new_paragraph, "TEXT", {"CharShape": "0"})

    for node in visual_nodes:
        new_text.append(node)
        ET.SubElement(new_text, "CHAR")

    return new_paragraph


def trim_bindata(root: ET.Element, used_bindata_ids: set[str]) -> None:
    mapping = root.find("./HEAD/MAPPINGTABLE")
    if mapping is not None:
        bindata_list = mapping.find("BINDATALIST")
        if bindata_list is not None:
            for item in list(bindata_list):
                if item.get("BinData") not in used_bindata_ids:
                    bindata_list.remove(item)
            bindata_list.set("Count", str(len(bindata_list.findall("BINITEM"))))

    storage = root.find("./TAIL/BINDATASTORAGE")
    if storage is not None:
        for item in list(storage):
            if item.get("Id") not in used_bindata_ids:
                storage.remove(item)


def extract_visual_only_hml(input_path: Path, output_path: Path) -> dict[str, int]:
    tree = ET.parse(input_path)
    root = tree.getroot()
    section = find_section(root)

    new_paragraphs: list[ET.Element] = []
    used_bindata_ids: set[str] = set()
    picture_count = 0
    container_count = 0

    for paragraph in section.findall("P"):
        pictures = paragraph.findall(".//PICTURE")
        containers = paragraph.findall(".//CONTAINER")
        visual_nodes, paragraph_bindata_ids = collect_visual_nodes(paragraph)
        if not visual_nodes:
            continue

        picture_count += len(pictures)
        container_count += len(containers)
        used_bindata_ids.update(paragraph_bindata_ids)
        new_paragraphs.append(build_visual_only_paragraph(paragraph, visual_nodes))

    for child in list(section):
        section.remove(child)
    for paragraph in new_paragraphs:
        section.append(paragraph)

    trim_bindata(root, used_bindata_ids)
    output_path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))

    return {
        "paragraphs": len(new_paragraphs),
        "pictures": picture_count,
        "containers": container_count,
        "bindata": len(used_bindata_ids),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract only image and drawing-object nodes from an HML file."
    )
    parser.add_argument("input_hml", type=Path, help="Source HML file")
    parser.add_argument("output_hml", type=Path, help="Destination HML file")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    stats = extract_visual_only_hml(args.input_hml, args.output_hml)
    print(f"OUT: {args.output_hml}")
    print(f"PARAGRAPHS: {stats['paragraphs']}")
    print(f"PICTURES: {stats['pictures']}")
    print(f"CONTAINERS: {stats['containers']}")
    print(f"BINDATA: {stats['bindata']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
