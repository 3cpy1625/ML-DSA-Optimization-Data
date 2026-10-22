# 下载后校验与重建

本仓库提供离线文件校验和汇总重建。Python需要3.10或更新版本，仅使用标准库。两者不需要 CUDA、GPU 或六个原始大 ZIP，也不执行归档中保存的实验脚本。

## 直接阅读

下载并解压仓库后，从根目录的 [README](../README.md) 开始。CSV 可用文本编辑器或电子表格软件打开，[Excel 汇总](../results/summary.xlsx) 可用 Excel 或 LibreOffice 打开。所有内部导航使用相对路径。

## 校验发布文件

在仓库根目录运行：

```text
python scripts/verify.py
```

程序读取随包校验信息，检查文件完整性、表结构和内部相对链接。它只读现有发布文件。退出成功表示这些程序检查通过；不能由此推出源实验本身没有误差，或未随包文件也被验证。

具体运行结果与核验范围见 [checks](../checks/)。如果文件被手工改动，哈希校验可能失败；这类差异应结合实际修改内容判断。

## 重建 CSV、实验导航和统计摘要

```text
python scripts/rebuild.py --output build --check
```

程序从 `data/derived/records/` 的六包归一化记录及随包原始表元数据重新生成结果，写入指定的 `build/` 目录，再与发布版进行比较。发布目录不会被覆盖。请将输出指向独立目录，避免与输入或发布文件混用。

CSV、导航和其余元数据逐字节比较。只有 `results/statistics.json` 中重新计算的三个系列几何平均值允许跨系统数学库末位差异（相对容差 `1e-14`、绝对容差 `1e-15`）；报告会单列使用该容差的文件。这不会改写发布数据，也不对原始表或结果 CSV 放宽比较。

重建输入是已整理的归一化记录。这一步公开结果的分类、来源关联与生成规则，不是从全部原始 ZIP 自动重新提取一次。原始记录提取正确与否，仍应按[字段字典](DATA_DICTIONARY.md)追溯原文；GPU性能也不会在这一步重测。

## Excel 的范围

发布包已提供 `results/summary.xlsx`，普通读取和 Python 校验不需要生成它。Excel 的排版程序是 `scripts/build_workbook.mjs`，依赖提供 `@oai/artifact-tool` 的 Node.js 环境；该依赖的可用性取决于实际运行环境。

因此，标准 Python 重建流程以 CSV、导航和统计摘要为目标，不承诺在普通 Python 环境重建 Excel 的格式或得到字节完全一致的 XLSX。已有工作簿仍可通过随包哈希和结构校验检查。

## 自动检查

`.github/workflows/validate.yml` 提供仓库检查配置。只有以后上传至 GitHub 并启用相应工作流后，GitHub才会执行它。配置存在不等于云端已运行；本地检查以 `checks/` 中的实际记录为准。
