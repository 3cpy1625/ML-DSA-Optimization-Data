# 选存原始证据

legacy/按字节保留先前整理包中的小型JSON、日志、文本和来源清单。原文件名和嵌套关系通过[证据映射](../metadata/legacy-evidence-map.csv)及[来源索引](../metadata/source-index.csv)定位。

此目录不是全部输入ZIP的镜像。归档内的Python/CUDA/C++文本只作为证据，不被校验或重建程序执行。少数原始.json实际为失败Traceback，按原字节保留，不自动修正格式。
