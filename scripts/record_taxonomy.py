"""Add documented navigation metadata without changing experiment measurements.

Input and output use the portable workbook-model JSON format.  The rules below
refer to the original series names, status fields, and source paths; they do not
infer experimental independence or use local filesystem paths.  Only three
known catalog source anchors are corrected, with an explicit change log.
"""
from __future__ import annotations

import copy
import json
import re
from collections import Counter

CORRECTNESS_COLUMNS = ["记录层级", "计数单位", "分类依据"]
CATALOG_COLUMNS = [
    "GPU", "数据轮次", "实验类别", "原始运行标识", "运行标识依据",
    "相关来源ID集合", "来源关联说明",
]

# These collection labels describe received datasets, not inferred run dates.
COLLECTIONS = {
    "新建文件夹(1).zip": ("RTX 4090", "历史R02与机制及截图记录", "rtx4090", "historical-r02"),
    "MLDSA_4090_Experiments.zip": ("RTX 4090", "4090主实验与补测", "rtx4090", "main-and-followups"),
    "5090实验结果_20261019.zip": ("RTX 5090", "5090首批实验", "rtx5090", "initial-collection"),
    "新5090.zip": ("RTX 5090", "5090组件消融补充", "rtx5090", "component-ablation"),
    "补测.zip": ("RTX 5090", "5090验证分布补测", "rtx5090", "verify-distributions"),
    "4090修补.zip": ("RTX 4090", "4090修补资格与恢复补充", "rtx4090", "repair-qualification"),
}

CATEGORY_SERIES = {
    "主性能": {"历史R02配对", "main_original_27", "E03_B8192"},
    "主性能补测": {"MLDSA_4090_Supplement_20261019"},
    "机制与消融": {"历史机制", "4090_m44_zerocopy", "4090_m65_ablation", "cta_m65_verify", "joint_m44_keygen", "m44_three_arm", "split32_m44_keygen", "wphc_m65_sign", "minimal_v65_distribution_supplement"},
    "联合矩阵与漂移对照": {"joint_matrix"},
    "算子微基准": {"4090_ntt_polynomial_chain", "4090_shake_sampling", "NTT_POLYNOMIAL", "SHAKE_SAMPLING", "SPLIT32_COMPARISON"},
    "阶段与资源诊断": {"4090_resources", "4090_resource_probe", "4090_sign_retry", "4090_stage_matrix", "4090_verify_traffic", "4090_verify_traffic_recheck", "4090_workspace", "MLDSA_4090_StagePrep_20261019", "E05_CUPTI"},
    "接口范围对照": {"4090_host_api"},
    "传统实现对照": {"legacy_baseline_27"},
    "正确性用例": {"4090_boundary", "V3_SMALL_CORRECTNESS", "E02A_BASELINE_EXPANDED", "CANDIDATE18_EARLIER_RUN", "E02A_CTA18", "E02C_NONSIGN36"},
    "工具资格与修补": {"4090_correctness_supplement", "E02B_ORIGINAL_SANITIZER", "E02B_WARP_SYNC_CANDIDATE", "E02B_CTA_SINGLE_REPLAY", "E02B_MIXED48", "SPLIT32_SANITIZER_FIRST", "SPLIT32_SANITIZER_POSTSETTLE", "split32_racecheck_original", "split32_sync_patch"},
    "资格验证": {"E03_B256_QUALIFICATION", "E13_B256_QUALIFICATION"},
    "构建与停止诊断": {"E11_TMPFS", "E03_EARLY_BUILD_FAILURE", "HISTORICAL_87_KEYGEN_COMPILER"},
    "故障与恢复": {"cuda_api_recovery"},
    "二进制身份核验": {"binary_identity_alignment"},
    "截图记录": {"截图复测"},
}
SERIES_CATEGORY = {series: kind for kind, series_set in CATEGORY_SERIES.items() for series in series_set}

# The catalog and metric exports use different, retained series identifiers.
# This explicit crosswalk navigates between them without renaming either one.
VIEW_SERIES_ALIASES = {
    "历史R02配对": {"4090 历史 R02"},
    "历史机制": {"C3_PFODR_V4", "CE_HSS_XP_001_FORMAL", "CE_SIGN_UNIFY_003_FORMAL"},
    "截图复测": {"原始大批量KeyGen结果.csv", "原始正确性九组结果.csv"},
    "4090_boundary": {"boundary_correctness_270"},
    "4090_correctness_supplement": {"sanitizer_supplement_72"},
    "4090_host_api": {"host_api_vs_device_27"},
    "4090_m44_zerocopy": {"m44_zero_copy_3"},
    "4090_m65_ablation": {"m65_early_reject_ablation_36"},
    "4090_ntt_polynomial_chain": {"ntt_polynomial_162_variants", "ntt_polynomial_459_process_ratios"},
    "4090_resources": {"hotspot_resources_81_symbols"},
    "4090_shake_sampling": {"shake_sampling_342_variants", "shake_sampling_234_ratios"},
    "4090_sign_retry": {"sign_retry_9"},
    "4090_stage_matrix": {"stage_processes_81"},
    "4090_verify_traffic": {"verify_traffic_62"},
    "4090_verify_traffic_recheck": {"verify_traffic_recheck_3"},
    "4090_workspace": {"workspace_27"},
    "MLDSA_4090_Supplement_20261019": {"4090 10/18+10/19修订"},
    "main_original_27": {"small_batch_correctness_cases_21", "small_batch_correctness_checks_171"},
    "legacy_baseline_27": {"legacy_baseline_54", "legacy_baseline_comparison_27", "legacy_baseline_correctness_126"},
    "E03_B8192": {"5090 E03 B8192"},
    "V3_SMALL_CORRECTNESS": {"v3_626756"},
    "E02A_BASELINE_EXPANDED": {"e2v2_642542"},
    "E02B_ORIGINAL_SANITIZER": {"e2b_657090"},
    "E02B_CTA_SINGLE_REPLAY": {"e2r_684616"},
    "E02B_MIXED48": {"e2m_699841"},
    "CANDIDATE18_EARLIER_RUN": {"a18_708718"},
    "E02A_CTA18": {"e2x_718474"},
}


def classify_correctness(row):
    """Return a row's evidence granularity, never an independent-test count."""
    archive, series = row.get("来源包", ""), row.get("实验系列", "")
    status = row.get("状态", "")
    check = row.get("工具或检查项", "")
    notes = row.get("备注", "") or ""
    if archive == "4090修补.zip":
        if status == "NOT_RUN_AFTER_P44_RACECHECK_STOP":
            return "未执行项", "1个计划项；实际执行数为0", "原状态明确为停止后未运行，未计为通过或工具进程。"
        if notes.startswith("variant_check；"):
            return "变体检查", "1个工具进程内的变体记录", "原record_role=variant_check；同一case可能共享最终输出，不能独立计次。"
        if notes.startswith("tool_process；"):
            return "工具进程", "1条工具进程结论", "原record_role=tool_process；工具结论与其变体检查分层保留。"
        if notes.startswith("recovery_phase；"):
            return "恢复阶段", "1个恢复流程阶段", "原record_role=recovery_phase；基线、故障注入和恢复是同一流程的不同阶段。"
        if notes.startswith("binary_identity；"):
            return "身份核验", "1个参数集与操作的二进制比对", "原record_role=binary_identity；SHA不一致表示资格不可迁移，不是算法输出失败。"
    if archive in {"新5090.zip", "补测.zip"} and check in {
        "最终输出、退出状态及计时核对", "final_output_statuses_identity_and_raw_timing"
    }:
        return "进程最终输出", "1个进程的保留最终输出记录", "原检查仅覆盖资格或性能进程最终输出；计时重复不等于逐次检查。"
    if archive == "新建文件夹(1).zip":
        if series in {"原始大批量KeyGen结果.csv", "原始正确性九组结果.csv"}:
            return "截图记录", "1条截图转录结果", "原备注明确截图转录且完整服务器日志未收到。"
        if series == "MLDSA_SANITIZER_RESULTS.csv":
            return "工具进程", "1条历史工具进程结论", "原表按tool/parameter/operation列出退出码和工具摘要；未重新运行。"
        if series == "MLDSA_G5_BYTE_CORRECTNESS.csv":
            return "用例汇总", "1个参数集/操作/批量的字节核对结果", "历史正确性表的单元格级结果；不推断其中输入样本相互独立。"
    if archive == "MLDSA_4090_Experiments.zip":
        if series == "small_batch_correctness_checks_171":
            return "子项检查", "1个用例内的检查子项", "原correctness_checks.csv；包含PASS、NOT_AVAILABLE及SKIPPED，不能与用例汇总相加。"
        if series == "small_batch_correctness_cases_21":
            return "用例汇总", "1个用例汇总", "原correctness_cases.csv；其细项另列于small_batch_correctness_checks_171。"
        if series == "sanitizer_supplement_72":
            return "工具进程", "1条工具进程记录，含复用项", "原工具补测表；备注区分复用59项与新增13项，不能视为72个新进程。"
        if series == "boundary_correctness_270":
            return "进程用例", "1个边界用例进程", "原boundary_cases.csv带attempt_id且状态为BOUNDARY_PROCESS_PASS。"
        if series == "legacy_baseline_correctness_126":
            return "进程输出汇总", "1个资格或性能进程的输出检查汇总", "原output_checks_126.csv包含stage、result_path和多种输出检查；属于传统实现对照。"
    if archive == "5090实验结果_20261019.zip":
        if series in {"SPLIT32_SANITIZER_FIRST", "SPLIT32_SANITIZER_POSTSETTLE"}:
            return "停止阶段汇总", "1个停止阶段报告", "原LOCAL_STOP_DIAGNOSIS.json的阶段结论；不是单个工具执行或新通过项。"
        if series in {"e2b_657090", "e2m_699841", "e2r_684616"} and check in {"memcheck", "racecheck", "synccheck", "initcheck"}:
            return "工具进程", "1个工具进程的用例结论", "原CASE_RESULT.json明确tool及工具结果；保留PASS和SANITIZER_FINDING。"
        if series in {"a18_708718", "e2v2_642542", "e2x_718474", "v3_626756", "E02C_NONSIGN36"}:
            return "用例汇总", "1个用例汇总", "原CASE_RESULT或LOCAL_INTAKE_VERIFICATION中的case级结论，内部checks不展开重复计数。"
    return "未细分", "1条原始记录；独立计数未确定", "未命中明确来源规则，保留原值而不推测层级。"


def _records(sheet):
    return [dict(zip(sheet["columns"], row)) for row in sheet["rows"]]


def _source_map(data):
    sheet = next(s for s in data["sheets"] if s["name"] == "来源索引")
    return {row["来源ID"]: row for row in _records(sheet)}


def _related_sources(row, sources):
    """Find historical collection anchors by preserved source path, not S IDs."""
    archive, series = row["来源包"], row["实验系列"]
    candidates = [(sid, src["包内路径"]) for sid, src in sources.items() if src["来源包"] == archive]
    if archive == "新建文件夹(1).zip":
        if series == "历史R02配对":
            ends = ("MLDSA_27_PERFORMANCE.csv", "MLDSA_27_ORIGINAL_CELL_RESULTS.csv", "MLDSA_BLOCK_RESULTS.csv", "MLDSA_PROCESS_REPLAY.csv")
            return [sid for sid, path in candidates if "/MATCHED_R02/" in path or path.endswith(ends)]
        if series == "历史机制":
            return [sid for sid, path in candidates if "/MECHANISM/" in path]
        if series == "截图复测":
            return [sid for sid, path in candidates if path.endswith(("原始大批量KeyGen结果.csv", "原始正确性九组结果.csv"))]
    return [row["来源ID"]] if row.get("来源ID") else []


def _run_identifier(row, sources):
    try:
        metadata = json.loads(row.get("计数与覆盖", "{}"))
    except (ValueError, TypeError):
        metadata = {}
    if isinstance(metadata, dict) and metadata.get("run_id"):
        return str(metadata["run_id"]), "原计数与覆盖中的run_id；保留原字符串"
    path = sources.get(row.get("来源ID", ""), {}).get("包内路径", "")
    # Preserve the complete directory component; do not turn timestamps into dates.
    for part in reversed(path.replace("!", "/").split("/")[:-1]):
        if re.search(r"20\d{6}[Tt]\d{6}(?:\d+)?[Zz]", part) and not part.endswith((".zip", ".tar.gz")):
            return part, "原来源路径中含运行时间戳的目录名；未解释为采集日期"
    return "", "原汇总未提供明确run_id，来源路径也未提供可唯一引用的运行目录；不从包名推断日期"


def enrich_workbook(data):
    """Return a deep copy with taxonomy fields and audited source-anchor fixes."""
    result = copy.deepcopy(data)
    sources = _source_map(result)
    corrections = list(result.get("source_corrections", []))
    for sheet in result["sheets"]:
        if sheet["name"] == "正确性记录":
            rows = _records(sheet)
            original_columns = [col for col in sheet["columns"] if col not in CORRECTNESS_COLUMNS]
            sheet["columns"] = CORRECTNESS_COLUMNS + original_columns
            sheet["rows"] = [list(classify_correctness(row)) + [row.get(col) for col in original_columns] for row in rows]
            sheet["note"] = f"本表按证据层级分类；{len(rows)}条为记录行数，不能相加当作独立实验次数。工具进程、用例、子项、变体和恢复阶段可能从属或共享输出。原状态及数值保留。"
        elif sheet["name"] == "实验目录":
            rows = _records(sheet)
            original_columns = [col for col in sheet["columns"] if col not in CATALOG_COLUMNS]
            new_rows = []
            for index, row in enumerate(rows, 1):
                gpu, collection, _, _ = COLLECTIONS.get(row["来源包"], ("未标注", "未细分", "unclassified", "unclassified"))
                related = _related_sources(row, sources)
                reason = "按原来源锚点关联；未据状态或包名推断实验日期。"
                if row["来源包"] == "新建文件夹(1).zip" and row["实验系列"] in {"历史R02配对", "历史机制", "截图复测"}:
                    reason = {
                        "历史R02配对": "主来源纠正为历史27格性能表；关联配对计划、进程和原始结果表，排除原误指的PFODR机制表。",
                        "历史机制": "补全来源锚点；关联历史MECHANISM目录各表，子系列不可合为整体加速。",
                        "截图复测": "补全来源锚点；关联两份截图转录CSV，完整服务器日志仍未收到。",
                    }[row["实验系列"]]
                    if related and row.get("来源ID", "") != related[0]:
                        corrections.append({"sheet": "实验目录", "record_index": index, "series": row["实验系列"], "field": "来源ID", "old_value": row.get("来源ID", ""), "new_value": related[0], "reason": reason})
                        row["来源ID"] = related[0]
                run_id, run_basis = _run_identifier(row, sources)
                extra = [gpu, collection, SERIES_CATEGORY.get(row["实验系列"], "未细分"), run_id, run_basis, ";".join(related), reason]
                new_rows.append(extra + [row.get(col) for col in original_columns])
            sheet["columns"] = CATALOG_COLUMNS + original_columns
            sheet["rows"] = new_rows
            sheet["note"] = "按GPU、收到的数据轮次和实验系列导航；数据轮次是数据包分组，不是推断的日期。保留失败、停止、仅构建及复用记录；目录行数不等于独立实验次数。"
    result["source_corrections"] = corrections
    correctness = next(s for s in result["sheets"] if s["name"] == "正确性记录")
    result["record_taxonomy"] = {
        "schema_version": "1.0", "count_semantics": "record_rows_not_independent_experiments",
        "correctness_counts": dict(Counter(row[0] for row in correctness["rows"])),
        "unknown_policy": "未细分；不推断实验日期、进程独立性或未提供的检查结论",
    }
    return result


def _slug(series):
    aliases = {"历史R02配对": "historical-r02-paired", "历史机制": "historical-mechanisms", "截图复测": "screenshot-records"}
    return aliases.get(series, re.sub(r"[^a-z0-9]+", "-", series.lower()).strip("-") or "unclassified")


def build_navigation(model):
    """Return one portable manifest record per experiment catalog row.

    Multiple records can share a directory (e.g. stopped/resumed runs). View row
    references are explicitly matching source anchors or series, not a claim
    that every dependent raw log belongs uniquely to one experiment.
    """
    source_map = _source_map(model)
    catalog = next(s for s in model["sheets"] if s["name"] == "实验目录")
    view_records = {sheet["name"]: _records(sheet) for sheet in model["sheets"] if sheet["name"] not in {"实验目录", "来源索引", "数据表索引", "环境", "问题与边界"}}
    entries = []
    for index, row in enumerate(_records(catalog), 1):
        archive, series = row["来源包"], row["实验系列"]
        gpu, collection, gpu_slug, collection_slug = COLLECTIONS.get(archive, ("未标注", "未细分", "unclassified", "unclassified"))
        related_ids = [sid for sid in row.get("相关来源ID集合", "").split(";") if sid]
        if not related_ids and row.get("来源ID"):
            related_ids = [row["来源ID"]]
        views = {}
        view_source_ids = set()
        aliases = VIEW_SERIES_ALIASES.get(series, set()) | {series}
        stopped_run = "STOPPED" in row["状态"]
        for sheet_name, sheet_rows in view_records.items():
            matches = []
            for n, view_row in enumerate(sheet_rows, 1):
                source_id = view_row.get("来源ID", "")
                view_archive = view_row.get("来源包") or source_map.get(source_id, {}).get("来源包")
                if view_archive != archive:
                    continue
                view_series = view_row.get("实验系列", view_row.get("结果系列", ""))
                if source_id in related_ids or view_series == series or (not stopped_run and view_series in aliases):
                    matches.append(n)
                    if source_id:
                        view_source_ids.add(source_id)
            if matches:
                basis = "相同来源ID或同来源包的显式实验系列映射；仅作导航，不构成独立实验计数"
                if series == "MLDSA_4090_Supplement_20261019" and sheet_name == "主性能":
                    basis += "；27格为原主实验加3格补测替换后的展示视图，不能计为27个新增补测格"
                if series == "main_original_27":
                    basis += "；所关联正确性记录与原主实验共享数据轮次，未将其资格迁移到后续新二进制"
                if series == "E02B_MIXED48":
                    basis += "；视图仅列21项新记录，其余复用项见原目录计数，不重复展开为48个新记录"
                views[sheet_name] = {"record_count": len(matches), "record_indices_1_based": matches, "match_basis": basis}
        entries.append({
            "catalog_record_id": f"CAT{index:04d}", "catalog_record_index": index,
            "gpu": gpu, "collection": collection, "archive": archive, "series": series,
            "category": row.get("实验类别", SERIES_CATEGORY.get(series, "未细分")),
            "status": row["状态"], "run_id": row.get("原始运行标识", ""),
            "run_id_basis": row.get("运行标识依据", ""),
            "directory": f"experiments/{gpu_slug}/{collection_slug}/{_slug(series)}",
            "primary_source_id": row.get("来源ID", ""), "source_ids": related_ids,
            "view_source_ids": sorted(view_source_ids),
            "source_paths": [source_map[sid]["包内路径"] for sid in related_ids if sid in source_map],
            "source_link_note": row.get("来源关联说明", ""),
            "original_counts_json": row.get("计数与覆盖", ""), "view_matches": views,
        })
    return entries


def build_navigation_manifest(model):
    """Compatibility wrapper with grouping-level counts."""
    entries = build_navigation(model)
    return {
        "schema_version": "1.0", "count_semantics": "catalog_records_not_independent_experiments",
        "records": entries, "catalog_records": len(entries),
        "navigation_directories": len({entry["directory"] for entry in entries}),
    }


def validate_preserved_fields(before, after):
    """Check every pre-existing cell, allowing only logged source corrections."""
    changed = {(item["sheet"], item["record_index"], item["field"]): item for item in after.get("source_corrections", [])}
    after_sheets = {sheet["name"]: sheet for sheet in after["sheets"]}
    checked_cells = 0
    for old_sheet in before["sheets"]:
        new_sheet = after_sheets[old_sheet["name"]]
        assert len(old_sheet["rows"]) == len(new_sheet["rows"]), old_sheet["name"]
        new_rows = _records(new_sheet)
        for index, old_row in enumerate(_records(old_sheet), 1):
            for column, old_value in old_row.items():
                new_value = new_rows[index - 1][column]
                if old_value != new_value:
                    key = (old_sheet["name"], index, column)
                    correction = changed.get(key)
                    assert correction and correction["old_value"] == old_value and correction["new_value"] == new_value, (key, old_value, new_value)
                checked_cells += 1
    return {"status": "PASS", "original_cells_checked": checked_cells, "documented_source_anchor_corrections": len(changed), "measurement_or_status_changes": 0}
