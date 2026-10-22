# E056 · minimal_v65_distribution_supplement

设备：RTX-5090。来源轮次：5090 Verify 四分布补测。

状态：`COMPLETE`

覆盖：{"run_id":"minimal_v65_20261020T145604Z_6e07c795","parameter":65,"qualification_batch":256,"performance_batch":8192,"message_bytes":32,"unique_processes":56,"qualification_processes":8,"performance_processes":48,"performance_timing_samples":720,"qualification_timing_samples":8,"capture_seconds":178.267}

边界：["One fixed input corpus; timings are not independent inputs","Device-resident full-operation interval; no host setup/transfers","Checks final timed output, not every timed output","Retained valid CPU oracle reused; mutation statuses checked by construction","No new independent standard KAT or sanitizer qualification","Historical 4090 comparison is mechanism-level, not pure hardware attribution"]

## 来源

- [S0530 原始定位对应材料](../../../../data/evidence/legacy/附录JSON/archive_supplement/3e8587c57afdaab529a3072c.json)：`补测.zip!补测/minimal_v65_20261020T145604Z_6e07c795.tar.gz!minimal_v65_20261020T145604Z_6e07c795/RESULT.json`

[返回本轮分类结果](../README.md)
