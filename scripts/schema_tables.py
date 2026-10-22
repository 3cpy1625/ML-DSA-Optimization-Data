"""Rebuild the table catalog from unchanged CSV/TSV bytes (standard library only).

``build_catalog(legacy_zip_path, repo_root)`` copies content-addressed table bytes
into ``data/raw/tables`` and ``data/derived/tables`` and returns a catalog, the
legacy-compatible inventory summary, and detailed schema repair statistics.
The catalog's raw/derived flag means original archive file versus a table
created during this consolidation, not raw measurement versus source summary.

``validate_catalog(repo_root, catalog)`` is read-only. It validates all referenced
bytes, dimensions, and schema values without relying on the original computer.
The original archive comparison remains a separately retained provenance audit.
"""

from __future__ import annotations

import collections
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile


CATALOG_MEMBER = "结构化表索引.csv"
SUMMARY_MEMBER = "清点统计.json"


def _integer(value):
    return int(value)


def _read_rows(raw, extension):
    """Keep values as text; blank physical lines are not data records."""
    text = raw.decode("utf-8-sig", errors="strict")
    delimiter = "\t" if extension.lower() == ".tsv" else ","
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    return [row for row in rows if row], len(rows) - sum(bool(row) for row in rows)


def _infer_header(legacy_row, rows):
    """Use retained metadata and checked record count, never a CSV heuristic.

    Seven 4090 repair cases.tsv paths carry positional column definitions in the
    old catalog but no header record in their actual bytes. Recognize these by
    their documented role, basename, and exact retained data-row count. Do not
    silently make the same assumption for arbitrary unrelated tables.
    """
    if not rows:
        return "不适用（空文件）", "原文件没有非空CSV/TSV记录", ""
    old_fields = legacy_row.get("字段", "")
    if not old_fields:
        return "否", "旧索引未提供表头；逐条解析后数据行数与旧索引一致", ""
    if (
        legacy_row.get("来源包") == "4090修补.zip"
        and legacy_row.get("类别") == "input_case_specification"
        and legacy_row.get("表格路径", "").endswith("/cases.tsv")
        and len(rows) == _integer(legacy_row["数据行数"])
    ):
        return (
            "否",
            "cases.tsv首行是用例数据；旧字段名为位置定义；全部记录数与旧数据行数一致",
            old_fields,
        )
    return "是", "原文件首条记录为表头；其余记录数与旧数据行数一致", ""


def _schema(raw, extension, header_flag):
    rows, empty_lines = _read_rows(raw, extension)
    if header_flag == "是":
        if not rows:
            raise ValueError("A header-bearing table cannot be empty")
        header = rows[0]
        data = rows[1:]
    elif header_flag == "否":
        header = []
        data = rows
    elif header_flag == "不适用（空文件）":
        if rows:
            raise ValueError("An empty-file table contains records")
        header = []
        data = []
    else:
        raise ValueError(f"Unknown header flag: {header_flag}")
    # Include the header width so a ragged data table is never labelled fixed.
    widths = sorted({len(row) for row in rows})
    fixed = len(widths) == 1
    result = {
        "数据行数": len(data),
        "字段数": widths[0] if fixed else "",
        "有无表头": header_flag,
        "最小字段数": min(widths) if widths else "",
        "最大字段数": max(widths) if widths else "",
        "列宽模式": "固定宽度" if fixed else ("可变宽度" if widths else "空文件"),
        "观测字段数集合": ";".join(map(str, widths)),
        "字段": " / ".join(header),
        "原始字段": json.dumps(header, ensure_ascii=False, separators=(",", ":")),
        "原始字节数": len(raw),
        "解析编码": "UTF-8（可带BOM）",
        "分隔符": "TAB" if extension.lower() == ".tsv" else "COMMA",
        "空白记录数": empty_lines,
    }
    return result


def _safe_target(repo_root, relative):
    """Do not permit archive or catalog paths to escape the destination."""
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or "\\" in relative:
        raise ValueError(f"Unsafe relative repository path: {relative}")
    root = Path(repo_root).resolve()
    target = root.joinpath(*rel.parts).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"Path escapes the repository: {relative}")
    return target


def build_catalog(legacy_zip_path, repo_root):
    """Copy byte-identical table files and rebuild metadata; no source writes."""
    catalog = []
    changes = []
    unique = {}
    legacy_field_inflation = 0
    formerly_zero_nonempty = 0
    positional_header_definitions = 0
    exact_byte_checks = 0
    with zipfile.ZipFile(legacy_zip_path, "r") as archive:
        legacy_catalog = list(
            csv.DictReader(io.StringIO(archive.read(CATALOG_MEMBER).decode("utf-8-sig")))
        )
        summary = json.loads(archive.read(SUMMARY_MEMBER).decode("utf-8-sig"))
        for old in legacy_catalog:
            member = old["数据包文件"]
            raw = archive.read(member)
            sha = hashlib.sha256(raw).hexdigest()
            if sha != old["SHA256"]:
                raise ValueError(f"Legacy table hash mismatch: {member}")
            if len(raw) != _integer(old["原始字节数"]):
                raise ValueError(f"Legacy table size mismatch: {member}")
            extension = PurePosixPath(member).suffix.lower()
            if extension not in (".csv", ".tsv"):
                raise ValueError(f"Unsupported table type: {member}")
            rows, _ = _read_rows(raw, extension)
            header, basis, positional_fields = _infer_header(old, rows)
            schema = _schema(raw, extension, header)
            if schema["数据行数"] != _integer(old["数据行数"]):
                raise ValueError(
                    f"Data-row count changed: {old['表格路径']}: "
                    f"{old['数据行数']} -> {schema['数据行数']}"
                )
            derived = old["是否派生表"]
            if derived not in ("是", "否"):
                raise ValueError(f"Unknown raw/derived flag: {derived}")
            layer = "derived" if derived == "是" else "raw"
            relative = f"data/{layer}/tables/{sha}{extension}"
            target = _safe_target(repo_root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != raw:
                    raise ValueError(f"Existing destination has different bytes: {relative}")
            else:
                target.write_bytes(raw)
            if target.read_bytes() != raw:
                raise ValueError(f"Copied table differs from source bytes: {relative}")
            exact_byte_checks += 1
            row = dict(old)
            row.update(schema)
            row.update(
                数据包文件=relative,
                表头判定依据=basis,
                位置字段说明=positional_fields,
                位置字段说明来源=("v3索引中的位置定义；不是文件表头" if positional_fields else ""),
                数据层级=("整理派生表" if derived == "是" else "原包原样表"),
            )
            for key in ("同内容路径数", "原始字节数"):
                row[key] = _integer(row[key])
            catalog.append(row)
            content_key = (sha, layer, extension)
            if content_key not in unique:
                unique[content_key] = row
            elif unique[content_key]["有无表头"] != header:
                raise ValueError(f"Same byte content has conflicting header semantics: {sha}")
            changed = {
                key: {"v3": old.get(key, ""), "v4": row[key]}
                for key in ("字段数", "字段")
                if str(old.get(key, "")) != str(row[key])
            }
            if changed:
                changes.append(
                    {"来源包": old["来源包"], "表格路径": old["表格路径"], "SHA256": sha, "changes": changed}
                )
            if header == "是" and _integer(old["字段数"]) == len(rows[0]) + 2:
                old_columns = old["字段"].split(" / ")
                if old_columns[:-2] == rows[0] and set(old_columns[-2:]) == {"source_line", "source"}:
                    legacy_field_inflation += 1
            if old["字段数"] == "0" and rows:
                formerly_zero_nonempty += 1
            if positional_fields:
                positional_header_definitions += 1

    # Keep every original inventory key and recompute values relevant to tables.
    all_shas = {row["SHA256"] for row in catalog}
    raw_shas = {row["SHA256"] for row in catalog if row["是否派生表"] == "否"}
    derived_shas = {row["SHA256"] for row in catalog if row["是否派生表"] == "是"}
    if raw_shas & derived_shas:
        raise ValueError("Identical bytes found in both raw and derived layers; review classification")
    by_sha = collections.defaultdict(list)
    for row in catalog:
        by_sha[row["SHA256"]].append(row)
    recomputed = {
        "table_paths": len(catalog),
        "original_table_paths": sum(row["是否派生表"] == "否" for row in catalog),
        "derived_table_paths": sum(row["是否派生表"] == "是" for row in catalog),
        "unique_table_bytes": len(all_shas),
        "repeated_table_paths": len(catalog) - len(all_shas),
        "unique_table_rows": sum(group[0]["数据行数"] for group in by_sha.values()),
        "cross_archive_duplicate_groups": sum(len({row["来源包"] for row in group}) > 1 for group in by_sha.values()),
    }
    for key, value in recomputed.items():
        if key in summary and summary[key] != value:
            raise ValueError(f"Legacy inventory count changed: {key}: {summary[key]} -> {value}")
    summary.update(recomputed)
    summary["original_unique_contents"] = len(raw_shas)
    summary["derived_unique_contents"] = len(derived_shas)
    stats = {
        "status": "PASS",
        "byte_comparison_against_v3_table_paths": exact_byte_checks,
        "unique_contents_unchanged": len(all_shas),
        "data_row_counts_unchanged": len(catalog),
        "extra_source_source_line_columns_removed": legacy_field_inflation,
        "formerly_zero_field_nonempty_paths_corrected": formerly_zero_nonempty,
        "positional_definitions_separated_from_real_headers": positional_header_definitions,
        "header_paths": sum(row["有无表头"] == "是" for row in catalog),
        "headerless_paths": sum(row["有无表头"] == "否" for row in catalog),
        "empty_file_paths": sum(row["列宽模式"] == "空文件" for row in catalog),
        "fixed_width_paths": sum(row["列宽模式"] == "固定宽度" for row in catalog),
        "variable_width_paths": sum(row["列宽模式"] == "可变宽度" for row in catalog),
        "schema_changed_paths": len(changes),
        "changes": changes,
        "counting_note": "数据行数为CSV/TSV解析记录数；有表头时扣除首记录，无表头时保留全部记录；不是独立实验或样本次数。",
        "raw_definition": "原包原样表表示用户原ZIP中的CSV/TSV原字节，可能是原实验已产生的汇总表；整理派生表表示本次整理从JSON/日志等转成的表。",
    }
    validate_catalog(repo_root, catalog)
    return catalog, summary, stats


def validate_catalog(repo_root, catalog):
    """Read-only portable integrity/schema check; raise ValueError on mismatch."""
    seen_sources = set()
    hashes = set()
    raw_hashes = set()
    derived_hashes = set()
    by_sha = collections.defaultdict(list)
    for row in catalog:
        # Several distinct derived tables legitimately share the same JSON/log
        # source list. Their SHA identifies the particular derived table.
        identity = (row["来源包"], row["表格路径"], row["SHA256"])
        if identity in seen_sources:
            raise ValueError(f"Duplicate source identity: {identity}")
        seen_sources.add(identity)
        relative = row["数据包文件"]
        target = _safe_target(repo_root, relative)
        raw = target.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha != row["SHA256"]:
            raise ValueError(f"Table hash mismatch: {relative}")
        extension = target.suffix.lower()
        derived = row["是否派生表"] == "是"
        layer = "derived" if derived else "raw"
        expected = f"data/{layer}/tables/{sha}{extension}"
        if relative != expected:
            raise ValueError(f"Content/layer path mismatch: {relative}")
        schema = _schema(raw, extension, row["有无表头"])
        for key, value in schema.items():
            if str(row[key]) != str(value):
                raise ValueError(f"Schema mismatch for {relative}: {key}: {row[key]!r} != {value!r}")
        if row["有无表头"] != "是" and json.loads(row["原始字段"]):
            raise ValueError(f"Headerless file is falsely assigned original headers: {relative}")
        hashes.add(sha)
        (derived_hashes if derived else raw_hashes).add(sha)
        by_sha[sha].append(row)
    for sha, group in by_sha.items():
        cross_archive = "是" if len({row["来源包"] for row in group}) > 1 else "否"
        for row in group:
            if _integer(row["同内容路径数"]) != len(group) or row["跨包同内容"] != cross_archive:
                raise ValueError(f"Duplicate-group metadata mismatch: {sha}")
    if raw_hashes & derived_hashes:
        raise ValueError("Raw and derived content hashes overlap")
    return {
        "status": "PASS",
        "table_paths": len(catalog),
        "unique_contents": len(hashes),
        "original_table_paths": sum(row["是否派生表"] == "否" for row in catalog),
        "derived_table_paths": sum(row["是否派生表"] == "是" for row in catalog),
        "original_unique_contents": len(raw_hashes),
        "derived_unique_contents": len(derived_hashes),
        "schema_checked_paths": len(catalog),
        "scope": "Repository table bytes match catalog SHA256/size/schema. Original-archive identity is established by the separately retained source audit, not inferred from this self-consistency check.",
    }
