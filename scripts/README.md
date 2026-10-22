# 离线复核程序

需要Python 3.10或更新版本，仅使用标准库，无需安装依赖。请从仓库根目录执行：

```text
python scripts/verify.py
python scripts/rebuild.py --output build --check
```

verify只读发布文件。rebuild将中间模型、CSV、导航与摘要写到独立build目录，并与发布产品比较。完整原ZIP提取、GPU执行及Excel格式生成不属于标准Python重建步骤。

若已有提供@oai/artifact-tool的Node.js环境，可用相同模型重新排版工作簿：

```text
node scripts/build_workbook.mjs build/workbook_data.json build/summary.xlsx build/previews
```

这是可选路径；发布工作簿可直接下载。请见[完整重建范围](../docs/REPRODUCING.md)。
