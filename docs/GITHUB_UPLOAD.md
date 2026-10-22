# 下载与后续更新

目标仓库：[3cpy1625/ML-DSA-Optimization-Data](https://github.com/3cpy1625/ML-DSA-Optimization-Data)。

从根目录README进入实验分类和CSV视图；使用Code → Download ZIP下载整个仓库。Excel位于results/summary.xlsx，下载后可用Excel或LibreOffice打开。原表采用哈希文件名，可从来源索引和实验导航追溯。

解压后保留data、results、experiments、scripts、docs和.github的相对结构。在根目录运行python scripts/verify.py即可校验文件；python scripts/rebuild.py --output build --check可离线重建并比较汇总。详细范围见[重建说明](REPRODUCING.md)。

后续补测按来源包和轮次补充，并更新索引、汇总、核验记录和SHA256SUMS。.gitattributes用于保持原始文件换行；不要手工重排原始表或覆盖历史测量。

checks中的报告记录本地核验；云端工作流执行状态以仓库Actions页面为准。本仓库包含全部已清点的原始CSV/TSV及选存证据，不是全部约28GB原始归档的完整镜像。
