# ML-DSA-Optimization-Data

面向GPU高吞吐的ML-DSA后量子数字签名关键算子与验签流程协同优化设计项目的数据。

版本：2026-10-21 v4。汇总 RTX 4090 与 RTX 5090 的六个实验数据包，提供原始表、派生结果、来源索引和离线复核程序。

## 从这里开始

- [按 RTX 4090 实验浏览](experiments/rtx-4090/)；[按 RTX 5090 实验浏览](experiments/rtx-5090/)。
- [在线浏览结果 CSV](results/views/)；[下载 Excel 汇总](results/summary.xlsx)。Excel 无法在线预览时，下载后用 Excel 或 LibreOffice 打开。
- [查找来源与原始表](data/metadata/)；[阅读字段字典](docs/DATA_DICTIONARY.md)。
- [了解统计口径与限制](docs/METHODS.md)；[下载后校验和重建结果](docs/REPRODUCING.md)。
- [阅读各数据包的完整结果说明](results/RESULT_NOTES.zh-CN.txt)；[查看版本变更](CHANGELOG.md)。
- [查看本版本核验记录](checks/)；[了解引用与后续补测方式](docs/REUSE.md)。

## 数据分层

```text
data/
  raw/tables/          原始 CSV/TSV，按原字节 SHA256 去重保存
  derived/tables/      从 JSON、日志等提取的派生表
  derived/records/     六包归一化记录，作为汇总重建输入
  metadata/           来源、表格、文件和完整性索引
  evidence/           选存的日志、JSON 等小型原始证据
results/
  views/              按用途分类的结果 CSV
  summary.xlsx        可筛选的 Excel 汇总
experiments/
  rtx-4090/           按来源轮次、实验系列和类型浏览
  rtx-5090/
scripts/              校验与重建程序
checks/               发布前核验记录
docs/                 字段、方法、复核和复用说明
```

原始表包含 **2,022 条来源路径、909 份不同字节内容**；派生表另存 **17 份**。同一原始文件在多处出现时只存一份内容，所有来源路径仍保留。原始表的编码、换行、表头和数值不随展示格式调整。这里的“原始”表示输入包中原有的文件，其中也包括原实验生成的汇总表与元数据，不代表每行都是独立原始测量。

主性能保留 **63 条结果**：4090 历史 R02 的 27 条、4090 10/18＋10/19 修订的 27 条、5090 E03 的 9 条。不同系列分别解释，不合成一个跨设备“总加速比”。正确性视图的 **1,722 条记录**含工具过程、子项检查和汇总等不同层级，不能当作 1,722 次独立实验。

## 重要的数据边界

本版调整分类、索引、导航和可复核程序，没有新增 GPU 测量。4090 修补包提供资格检查、故障恢复和二进制身份审计；它没有替换主性能结果。修补前告警、未运行项、失败后恢复记录和版本不匹配结论继续保留。

这里保存了六包清点范围内的全部原始 CSV/TSV，以及选存的小型证据。它不是六个输入 ZIP 的完整镜像，不包含其中全部二进制、完整代码、日志和截图。由来源记录重建汇总，也不等于重新执行 GPU 实验或独立重做全部资格测试。

输入包为：`新建文件夹(1).zip`、`MLDSA_4090_Experiments.zip`、`5090实验结果_20261019.zip`、`新5090.zip`、`补测.zip`、`4090修补.zip`。包内路径仅用于追溯，不要求下载者拥有整理时的本机目录。来源索引标明“仓库文件”和“材料保留状态”；“仅保留来源定位”的条目没有随包文件，不能把来源记录数当作下载文件数。

## 下载和校验

可使用 GitHub 的 **Code → Download ZIP** 下载全部内容。解压后在仓库根目录运行：

```text
python scripts/verify.py
python scripts/rebuild.py --output build --check
```

第一条只读校验文件、表结构和相对链接；第二条将重建结果写到 `build/` 并与发布结果比较。两者离线运行，不调用 GPU。无需运行程序也可直接阅读 CSV 和 Excel。具体范围见[复核说明](docs/REPRODUCING.md)。

## 结构参考

实验导航参考了 [MLPerf 按系统、基准、场景与运行组织结果的方式](https://github.com/mlcommons/inference/blob/master/tools/submission/submission_structure.md)；结果表与转换程序分开保存，参考了 [pqm4 的基准结果与导出程序](https://github.com/mupq/pqm4/blob/master/README.md)。本项目采用适合当前数据的分类，不表示获得这些项目的认证或满足其提交规则。
