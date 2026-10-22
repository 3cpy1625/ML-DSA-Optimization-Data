# E029 · E03_B8192

设备：RTX-5090。来源轮次：5090 首批归档（包名标记 20261019，含后续运行）。

状态：`EXPLORATORY_FIXED_CONFIGURATION`

覆盖：{"cases":9,"processes":108,"timing_samples":1620,"batch":[8192],"parameters":[44,65,87]}

边界：44/65/87 × KeyGen/Sign/Verify；B8192；消息32B；108 GPU进程，3 CPU进程，1620条GPU event计时。封存二进制sanitizer仍NOT_RUN。

## 来源

- S0643：`5090实验结果_20261019/server_results/e03_persistent9_b8192/e03-persistent9-20261020t060300z-7acbe276/local_intake_01/RESULT.json`。本分享包仅保留来源定位。

[返回本轮分类结果](../README.md)
