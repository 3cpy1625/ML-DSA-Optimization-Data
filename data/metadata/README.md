# 来源与结构索引

- [表格索引](table-index.csv)：所有2039条表路径，含原始/派生、表头和列宽。大表可在[结果视图](../../results/views/README.md)按分片阅读。
- [来源索引](source-index.csv)：来源ID、原包内位置、SHA和仓库内可打开材料。
- [实验目录](experiments.json)；[实验与视图行关联](experiment-view-links.json)。
- [正确性记录层级](record-taxonomy.json)；[三处来源纠正](source-corrections.json)。
- [原始包清单](source-archives.json)；[外层归档目录](archive-inventory.json)。
- [相同表内容的多路径](duplicate-tables.csv)；[保留证据映射](legacy-evidence-map.csv)。
- [本版表结构修正记录](schema-corrections.json)；[结果CSV分片清单](view-manifest.json)。

表路径、内容份数、结果行数和独立实验数是不同概念。原始路径字符串不会作为下载者的本机文件依赖。
