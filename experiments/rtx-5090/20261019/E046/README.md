# E046 · SPLIT32_SANITIZER_POSTSETTLE

设备：RTX-5090。来源轮次：5090 首批归档（包名标记 20261019，含后续运行）。

状态：`STOPPED_WITH_RACECHECK_FINDING`

覆盖：{"cases":4,"passed":3,"failed":1,"not_run":8,"planned":12}

边界：3 memcheck PASS；p44 warp=1 racecheck 103 warnings，展示100 hazards，退出86；8未启动。与此前算子正确性/性能PASS并存，不可抹掉finding。

## 来源

- S0588：`5090实验结果_20261019/server_results/split32_sanitizer_postsettle_stopped/LOCAL_STOP_DIAGNOSIS.json`。本分享包仅保留来源定位。

[返回本轮分类结果](../README.md)
