# 核验范围与记录

- original-source-byte-audit.json：从六个原ZIP（含嵌套tar）逐字节检查2022条原始表路径，覆盖909份内容；外层42704条目录元数据匹配。该审查在v3阶段完成，v4通过相同SHA及字节保留衔接。
- table-schema-validation.json：v4全部2039表路径的文件、表头、列宽与数据行数。
- preservation_check.json：对照v3的251859个原字段值；允许登记的索引列数/仓库路径及3处来源纠正，测量和状态不改写。
- taxonomy_validation.json：正确性记录层级与来源规则检查。
- source-navigation-audit.json：60条实验导航、六包分类视图与随包来源材料的独立复核。
- local-validation.json：全部表结构、来源关联、文档链接、Excel与CSV逐单元格比较及134份重建产品的实际本地核验结果。

记录中的历史统计只描述所列范围，不替代对源实验真实性或未收到二进制的核验。最终文件清单由根目录的SHA256SUMS覆盖，可再次运行随包校验程序检查。

`.github/workflows/validate.yml`已配置同样的只读校验与重建比对；本地准备不代表GitHub云端已经执行。
