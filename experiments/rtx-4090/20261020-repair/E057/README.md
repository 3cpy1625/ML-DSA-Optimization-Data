# E057 · split32_racecheck_original

设备：RTX-4090。来源轮次：4090 修补资格与故障恢复补充。

状态：`RACECHECK_STOPPED`

覆盖：{"run_id":"20261020T161628260124Z-b966f10f","parameters":[44,65,87],"planned_processes":3,"executed_processes":1,"variant_records":36}

边界：["Standalone archived primitive executables, not the current production DSOs or all historical split32 programs.","Seven small cases per parameter: raw permutation, SHAKE, uniform, eta at 17/65 requests, ExpandMask and SampleInBall; three comparison backends are retained.","No source edits, no compilation and no performance claim. A pass only covers the selected inputs and binary hashes.","150-second execution budget across three processes; each owned instrumented child is limited to 45 seconds or remaining budget. Export/SSH transfer are additional.","Only the child process group created by this runner may be stopped at timeout; no other GPU process is stopped."]

## 来源

- [S0589 原始定位对应材料](../../../../data/evidence/legacy/修补证据/archive_4090_patch/9f35c52db870dc76a46efc07.json)：`4090修补.zip!4090修补/split32_racecheck_v1/server_results/20261020T161628260124Z-b966f10f/20261020T161628260124Z-b966f10f.tar.gz!20261020T161628260124Z-b966f10f/RESULT.json`

[返回本轮分类结果](../README.md)
