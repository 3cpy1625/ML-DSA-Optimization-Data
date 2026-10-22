# E045 · SPLIT32_SANITIZER_FIRST

设备：RTX-5090。来源轮次：5090 首批归档（包名标记 20261019，含后续运行）。

状态：`STOPPED_GPU_POST_IDLE_GUARD`

覆盖：{"cases":3,"saved_pass":2,"planned":12}

边界：实际3次memcheck退出0且0 findings，只有2已写PASS；第三进程后GPU利用率36%触发守卫，不能视全矩阵PASS。

## 来源

- S0587：`5090实验结果_20261019/server_results/split32_sanitizer_stopped/LOCAL_STOP_DIAGNOSIS.json`。本分享包仅保留来源定位。

[返回本轮分类结果](../README.md)
