"""Read-only offline checks for the published experiment data repository.

Run ``python scripts/verify.py`` from any directory, or pass ``--repo PATH``.
Only the Python standard library is required. This script does not execute
project experiments, repair files, update checksums, or regenerate deliverables.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import math
import posixpath
import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True

from schema_tables import validate_catalog


VIEW_SHEETS = {
    "main-performance": "主性能",
    "ablation-comparisons": "消融对照",
    "operator-microbenchmarks": "算子微基准",
    "auxiliary-diagnostics": "辅助诊断",
    "correctness-records": "正确性记录",
    "experiment-catalog": "实验目录",
    "limitations": "问题与边界",
    "environments": "环境",
    "source-index": "来源索引",
    "table-index": "数据表索引",
}
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SOURCE_ID = re.compile(r"S\d{4,}")
MAX_GIT_FILE_BYTES = 100 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_path(root, relative):
    require(isinstance(relative, str) and bool(relative), "Empty repository path")
    rel = PurePosixPath(relative)
    require(
        not rel.is_absolute() and ".." not in rel.parts and "\\" not in relative
        and not re.match(r"^[A-Za-z]:", relative),
        f"Unsafe repository path: {relative}",
    )
    target = root.joinpath(*rel.parts).resolve()
    require(target.is_relative_to(root), f"Path leaves repository: {relative}")
    return target


def ignored_file(relative):
    parts = PurePosixPath(relative).parts
    return bool(parts and parts[0] in {".git", "build"}) or "__pycache__" in parts


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksums(root):
    checksum_file = root / "SHA256SUMS"
    require(checksum_file.is_file(), "Missing SHA256SUMS")
    expected = {}
    for number, line in enumerate(checksum_file.read_text("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([A-Fa-f0-9]{64}) [ *](.+)", line)
        require(match is not None, f"Malformed SHA256SUMS record {number}")
        digest, relative = match.groups()
        require(relative != "SHA256SUMS", "SHA256SUMS cannot hash itself")
        require(relative not in expected, f"Duplicate checksum path: {relative}")
        require(not ignored_file(relative), f"Build/cache file appears in release manifest: {relative}")
        safe_path(root, relative)
        expected[relative] = digest.lower()
    require(expected, "SHA256SUMS is empty")
    actual = set()
    total = 0
    largest = (0, "")
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if ignored_file(relative) or relative == "SHA256SUMS":
            continue
        require(not path.is_symlink(), f"Release contains a symbolic link: {relative}")
        if not path.is_file():
            continue
        actual.add(relative)
        require(relative in expected, f"Unlisted release file: {relative}")
        size = path.stat().st_size
        require(size <= MAX_GIT_FILE_BYTES, f"File exceeds 100 MiB GitHub Git limit: {relative}")
        require(file_hash(path) == expected[relative], f"SHA256 mismatch: {relative}")
        total += size
        largest = max(largest, (size, relative))
    require(actual == set(expected), "Missing release files: " + ", ".join(sorted(set(expected) - actual)[:10]))
    return {"files": len(actual), "bytes": total, "largest_file_bytes": largest[0], "largest_file": largest[1]}


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    require(bool(rows), f"Missing CSV header: {path.name}")
    columns, records = rows[0], rows[1:]
    require(bool(columns), f"Empty CSV header: {path.name}")
    for number, row in enumerate(records, 2):
        require(len(row) == len(columns), f"CSV width mismatch: {path.name}, record {number}")
    return columns, records


def read_dicts(path):
    columns, records = read_csv(path)
    require(len(set(columns)) == len(columns), f"Duplicate CSV column: {path.name}")
    return [dict(zip(columns, row)) for row in records]


def verify_views(root):
    manifest = json.loads((root / "data/metadata/view-manifest.json").read_text("utf-8"))
    require(isinstance(manifest, list) and manifest, "Empty or unsupported view manifest")
    seen = set()
    grouped = {}
    total_records = 0
    for item in manifest:
        relative = item["path"]
        require(relative not in seen, f"Repeated view manifest path: {relative}")
        seen.add(relative)
        path = safe_path(root, relative)
        require(path.is_file(), f"Missing CSV view: {relative}")
        require(path.stat().st_size == item["bytes"], f"CSV view byte size mismatch: {relative}")
        require(file_hash(path) == item["sha256"], f"CSV view hash mismatch: {relative}")
        columns, records = read_csv(path)
        require(len(columns) == item["columns"], f"CSV view column count mismatch: {relative}")
        require(len(records) == item["rows"], f"CSV view record count mismatch: {relative}")
        total_records += len(records)
        require(item["bytes"] < 512000, f"CSV view exceeds GitHub preview size target: {relative}")
        key = re.sub(r"-\d{2}$", "", path.stem)
        if key not in grouped:
            grouped[key] = {"columns": columns, "records": [], "parts": []}
        require(grouped[key]["columns"] == columns, f"Inconsistent CSV shard headers: {key}")
        grouped[key]["records"].extend(records)
        grouped[key]["parts"].append(relative)
    for key in VIEW_SHEETS:
        require(key in grouped, f"Missing required view: {key}")
    require(len(grouped["main-performance"]["records"]) == 63, "Expected 63 main-performance records")
    correctness = grouped["correctness-records"]
    require(len(correctness["records"]) == 1722, "Expected 1722 correctness records")
    for field in ("记录层级", "计数单位", "分类依据"):
        require(field in correctness["columns"], f"Missing correctness taxonomy: {field}")
        index = correctness["columns"].index(field)
        require(all(row[index].strip() for row in correctness["records"]), f"Empty correctness taxonomy: {field}")
    table = grouped["table-index"]
    for field in ("是否派生表", "有无表头", "最小字段数", "最大字段数", "列宽模式", "原始字段", "数据层级"):
        require(field in table["columns"], f"Missing explicit table-schema field: {field}")
    index = table["columns"].index("是否派生表")
    require(all(row[index] in ("是", "否") for row in table["records"]), "Invalid raw/derived flags")
    # Canonical metadata exports and split browser views describe identical rows.
    for key in ("source-index", "table-index"):
        columns, records = read_csv(root / f"data/metadata/{key}.csv")
        require(columns == grouped[key]["columns"] and records == grouped[key]["records"], f"Metadata and view differ: {key}")
    return grouped, {"parts": len(manifest), "records": total_records, "main_records": 63, "correctness_records": 1722}


def verify_sources(root, grouped):
    sources = read_dicts(root / "data/metadata/source-index.csv")
    ids = [row["来源ID"] for row in sources]
    require(all(SOURCE_ID.fullmatch(sid) for sid in ids), "Malformed source ID")
    require(len(ids) == len(set(ids)), "Source IDs are not unique")
    known = set(ids)
    references = 0
    retained_locations = 0
    for row in sources:
        relative = row.get("仓库文件", "")
        if not relative:
            continue
        path = safe_path(root, relative)
        require(path.is_file(), f"Missing retained source material: {row['来源ID']}")
        sha = row.get("SHA256", "")
        if re.fullmatch(r"[A-Fa-f0-9]{64}", sha):
            require(file_hash(path) == sha.lower(), f"Retained source SHA mismatch: {row['来源ID']}")
        retained_locations += 1
    for key, view in grouped.items():
        for index, field in enumerate(view["columns"]):
            if "来源ID" not in field:
                continue
            for row in view["records"]:
                value = row[index]
                if not value.strip():
                    continue
                if field == "来源ID":
                    require(SOURCE_ID.fullmatch(value) is not None, f"Malformed single source ID in {key}")
                matches = SOURCE_ID.findall(value)
                require(bool(matches), f"Unparseable source reference in {key}/{field}")
                for sid in matches:
                    require(sid in known, f"Unresolved source ID {sid} in {key}")
                    references += 1
    experiments = json.loads((root / "data/metadata/experiments.json").read_text("utf-8"))
    if isinstance(experiments, dict):
        experiments = experiments["records"]
    require(len(experiments) == 60, "Expected 60 experiment-catalog records")
    for item in experiments:
        for sid in item.get("source_ids", []):
            require(sid in known, f"Unresolved experiment source ID: {sid}")
        relative = item.get("page") or item.get("directory")
        require(bool(relative) and safe_path(root, relative).exists(), "Missing experiment navigation target")
    return {"unique_ids": len(known), "resolved_references": references, "retained_source_locations": retained_locations, "experiments": len(experiments)}


def verify_evidence_map(root):
    records = read_dicts(root / "data/metadata/legacy-evidence-map.csv")
    seen = set()
    for row in records:
        relative = row["仓库文件"]
        require(relative not in seen, f"Duplicate retained-evidence path: {relative}")
        seen.add(relative)
        path = safe_path(root, relative)
        require(path.is_file(), f"Missing retained evidence: {relative}")
        require(path.stat().st_size == int(row["字节数"]), f"Retained evidence size mismatch: {relative}")
        require(file_hash(path) == row["SHA256"], f"Retained evidence SHA mismatch: {relative}")
    return {"files": len(records)}


def markdown_targets(text):
    """Extract inline links with balanced filename parentheses and references."""
    text = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1\s*$", "", text)
    for start in re.finditer(r"\]\(", text):
        position = start.end()
        depth = 1
        angle = False
        escaped = False
        end = position
        while end < len(text):
            char = text[end]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "<":
                angle = True
            elif char == ">":
                angle = False
            elif not angle and char == "(":
                depth += 1
            elif not angle and char == ")":
                depth -= 1
                if depth == 0:
                    yield text[position:end].strip()
                    break
            end += 1
    for match in re.finditer(r"(?m)^\s{0,3}\[[^\]]+\]:\s*(.+)$", text):
        yield match.group(1).strip()


def verify_markdown_links(root):
    count = 0
    documents = 0
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        if ignored_file(relative) or relative.startswith(("data/evidence/", "data/derived/legacy-analysis/")):
            continue
        documents += 1
        for target in markdown_targets(path.read_text("utf-8-sig")):
            if target.startswith("<"):
                target = target[1:target.index(">")]
            else:
                # Markdown optional quoted title, not an unescaped space in a filename.
                target = re.sub(r"\s+[\"'].*[\"']\s*$", "", target)
            target = target.replace("\\(", "(").replace("\\)", ")")
            parsed = urlsplit(target)
            if parsed.scheme.lower() in {"http", "https", "mailto", "tel"} or parsed.netloc:
                continue
            require(not parsed.scheme, f"Nonportable link scheme in {relative}: {target}")
            if not parsed.path:
                continue
            decoded = unquote(parsed.path)
            require(not decoded.startswith(("/", "\\")) and not re.match(r"^[A-Za-z]:", decoded), f"Nonportable Markdown path in {relative}: {target}")
            destination = (path.parent / decoded).resolve()
            require(destination.is_relative_to(root), f"Markdown link escapes repository: {relative}: {target}")
            require(destination.exists(), f"Broken Markdown link: {relative}: {target}")
            if destination.is_dir():
                require((destination / "README.md").is_file() or any(destination.iterdir()), f"Empty directory Markdown target: {relative}: {target}")
            count += 1
    return {"documents": documents, "relative_links": count}


def column_number(reference):
    match = re.match(r"([A-Z]+)", reference)
    require(match is not None, f"Invalid XLSX cell reference: {reference}")
    result = 0
    for letter in match.group(1):
        result = result * 26 + ord(letter) - ord("A") + 1
    return result


def xlsx_cells(archive, path, shared):
    tree = ET.fromstring(archive.read(path))
    rows = {}
    formulas = 0
    for row in tree.findall("s:sheetData/s:row", NS):
        values = {}
        for cell in row.findall("s:c", NS):
            ref, kind = cell.get("r"), cell.get("t", "n")
            require(kind != "e", f"XLSX error cell in {path}: {ref}")
            node = cell.find("s:v", NS)
            text = node.text if node is not None else ""
            if kind == "s":
                value = shared[int(text)] if text else ""
            elif kind == "inlineStr":
                value = "".join(n.text or "" for n in cell.findall("s:is//s:t", NS))
            else:
                value = text or ""
            if cell.find("s:f", NS) is not None:
                formulas += 1
            values[column_number(ref)] = (value, kind)
        rows[int(row.get("r"))] = values
    return rows, formulas


def same_cell(expected, actual):
    value, kind = actual
    if kind not in {"n", "b"} or expected == "" or value == "":
        return expected == value
    try:
        left, right = float(expected), float(value)
    except ValueError:
        return expected == value
    return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def verify_workbook(root, grouped):
    workbook = root / "results/summary.xlsx"
    require(workbook.is_file(), "Missing results/summary.xlsx")
    compared = 0
    formulas = 0
    with zipfile.ZipFile(workbook) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate XLSX archive members")
        require(not any("vbaproject" in name.lower() or name.startswith("xl/externalLinks/") for name in names), "Workbook contains macros or external workbook links")
        for name in names:
            rel = PurePosixPath(name)
            require(not rel.is_absolute() and ".." not in rel.parts, f"Unsafe XLSX member: {name}")
            if name.endswith(".rels"):
                rels = ET.fromstring(archive.read(name))
                for relation in rels:
                    require(not relation.get("Type", "").endswith("/externalLink"), "Workbook has an external workbook relationship")
        shared = []
        if "xl/sharedStrings.xml" in names:
            tree = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(n.text or "" for n in item.findall(".//s:t", NS)) for item in tree.findall("s:si", NS)]
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {node.get("Id"): node.get("Target") for node in relationships}
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = {}
        for sheet in book.findall("s:sheets/s:sheet", NS):
            target = targets[sheet.get("{" + OFFICE_REL + "}id")]
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            sheets[sheet.get("name")] = member
        require(set(sheets) == {"概览", *VIEW_SHEETS.values()}, "Workbook must contain the expected 11 sheets")
        for name, member in sheets.items():
            cells, formula_count = xlsx_cells(archive, member, shared)
            formulas += formula_count
            if name == "概览":
                continue
            key = next(key for key, sheet_name in VIEW_SHEETS.items() if sheet_name == name)
            view = grouped[key]
            columns = view["columns"]
            header_rows = [number for number, values in cells.items() if [values.get(i, ("", ""))[0] for i in range(1, len(columns) + 1)] == columns]
            require(len(header_rows) == 1, f"Cannot uniquely locate workbook header: {name}")
            first = header_rows[0] + 1
            for row_number, expected in enumerate(view["records"], first):
                actual_row = cells.get(row_number, {})
                for column, value in enumerate(expected, 1):
                    actual = actual_row.get(column, ("", ""))
                    require(same_cell(value, actual), f"Workbook differs from CSV: {name}, row {row_number}, column {column}")
                    compared += 1
            last = first + len(view["records"]) - 1
            extra = [number for number, values in cells.items() if number > last and any(value[0] != "" for value in values.values())]
            require(not extra, f"Unexpected workbook data after last CSV row: {name}")
    return {"sheets": len(sheets), "compared_data_cells": compared, "formulas": formulas, "macros": False, "external_workbook_links": False}


def run(repo):
    root = Path(repo).resolve()
    require(root.is_dir(), "Repository directory does not exist")
    result = {"status": "PASS", "read_only": True}
    result["release"] = verify_checksums(root)
    catalog = read_dicts(root / "data/metadata/table-index.csv")
    result["tables"] = validate_catalog(root, catalog)
    require(result["tables"]["table_paths"] == 2039 and result["tables"]["unique_contents"] == 926, "Unexpected table inventory counts")
    grouped, result["views"] = verify_views(root)
    result["sources"] = verify_sources(root, grouped)
    result["retained_evidence"] = verify_evidence_map(root)
    result["links"] = verify_markdown_links(root)
    result["workbook"] = verify_workbook(root, grouped)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = run(args.repo)
    except Exception as error:
        print(json.dumps({"status": "FAIL", "read_only": True, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
