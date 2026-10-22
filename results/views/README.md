# 分类结果视图

CSV 与 Excel 使用相同记录和字段。大表按完整行分片；空值与零保持区分。

## 主性能

加速比为配对比值的几何均值。旧R02提供描述性CI；新固定输入实验未提供CI，留空。各系列单独使用。

- [main-performance.csv](main-performance.csv)（63 条记录）

## 消融对照

按分子/分母和条件解释。补测四分布单独追加；旧六格同二进制条件为漂移对照；TC两臂均开启。

- [ablation-comparisons.csv](ablation-comparisons.csv)（157 条记录）

## 算子微基准

独立算子harness结果，不等同于完整KeyGen、Sign或Verify加速。输出单位与统计口径保留原字段。

- [operator-microbenchmarks-01.csv](operator-microbenchmarks-01.csv)（1559 条记录）
- [operator-microbenchmarks-02.csv](operator-microbenchmarks-02.csv)（2093 条记录）
- [operator-microbenchmarks-03.csv](operator-microbenchmarks-03.csv)（1316 条记录）

## 辅助诊断

包含插桩、内存、热点及重试指标。legacy Dilithium与ML-DSA不作直接加速比较；诊断计时不纳入主性能。

- [auxiliary-diagnostics-01.csv](auxiliary-diagnostics-01.csv)（2588 条记录）
- [auxiliary-diagnostics-02.csv](auxiliary-diagnostics-02.csv)（1486 条记录）
- [auxiliary-diagnostics-03.csv](auxiliary-diagnostics-03.csv)（852 条记录）

## 正确性记录

本表按证据层级分类；1722条为记录行数，不能相加当作独立实验次数。工具进程、用例、子项、变体和恢复阶段可能从属或共享输出。原状态及数值保留。

- [correctness-records-01.csv](correctness-records-01.csv)（1448 条记录）
- [correctness-records-02.csv](correctness-records-02.csv)（274 条记录）

## 实验目录

按GPU、收到的数据轮次和实验系列导航；数据轮次是数据包分组，不是推断的日期。保留失败、停止、仅构建及复用记录；目录行数不等于独立实验次数。

- [experiment-catalog.csv](experiment-catalog.csv)（60 条记录）

## 问题与边界

保留失败、未运行、替换关系和原验收限制；原始英文限制保持来源用词。

- [limitations.csv](limitations.csv)（252 条记录）

## 环境

nvidia-smi显示的CUDA支持版本与实际nvcc编译器版本分别解释。缺失信息不从另一轮测试自动继承。

- [environments.csv](environments.csv)（42 条记录）

## 来源索引

来源ID用于连接结果表。! 或 !/ 表示外层ZIP内嵌套包；源行号与JSON定位共同用于核查。

- [source-index-01.csv](source-index-01.csv)（1425 条记录）
- [source-index-02.csv](source-index-02.csv)（1093 条记录）
- [source-index-03.csv](source-index-03.csv)（521 条记录）

## 数据表索引

包含正式测试、历史数据、元数据、遥测、QA夹具和17张派生表；数据行数不是独立样本数。

- [table-index-01.csv](table-index-01.csv)（534 条记录）
- [table-index-02.csv](table-index-02.csv)（481 条记录）
- [table-index-03.csv](table-index-03.csv)（516 条记录）
- [table-index-04.csv](table-index-04.csv)（504 条记录）
- [table-index-05.csv](table-index-05.csv)（4 条记录）

## 补测四分布明细

[完整数值](supplement-summary.csv)。观测范围不是置信区间。
