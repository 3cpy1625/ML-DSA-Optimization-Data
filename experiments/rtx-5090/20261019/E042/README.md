# E042 · E02C_NONSIGN36

设备：RTX-5090。来源轮次：5090 首批归档（包名标记 20261019，含后续运行）。

状态：`PASS_SCOPE_LIMITED`

覆盖：{"cases":36,"negative_checks":480}

边界：六个独立KeyGen/Verify目标；12 KeyGen、24 Verify（12空消息/12消息32）；12非空Verify×40=480拒绝/接口检查；空消息负例NOT_APPLICABLE；canary未实现、PQClean不可用。

## 来源

- S0358：`5090实验结果_20261019/extracted/e2c36_754991/LOCAL_INTAKE_VERIFICATION.json`。本分享包仅保留来源定位。

[返回本轮分类结果](../README.md)
