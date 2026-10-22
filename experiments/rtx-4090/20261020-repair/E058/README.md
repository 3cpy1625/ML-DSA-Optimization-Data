# E058 · split32_sync_patch

设备：RTX-4090。来源轮次：4090 修补资格与故障恢复补充。

状态：`SPLIT32_PATCH_TOOLS_9_OF_9_PASS`

覆盖：{"run_id":"20261020T162230081774Z-b4e3d46f","parameters":[44,65,87],"planned_processes":9,"executed_processes":9,"variant_records":324}

边界：["Privately rebuilt standalone primitive executables, not production DSOs or all historical split32 programs. Historical performance timings are not transferred to the patched binaries.","Seven small cases per parameter: raw permutation, SHAKE, uniform, eta at 17/65 requests, ExpandMask and SampleInBall; three comparison backends are retained.","Two shared-stream barriers are inserted in a private standalone harness; each parameter is rebuilt with the original flags and checked with racecheck/memcheck/synccheck. No performance claim.","150-second execution budget across private builds and nine tool processes; each owned instrumented child is limited to 30 seconds or remaining budget. Export/SSH transfer are additional.","Only the child process group created by this runner may be stopped at timeout; no other GPU process is stopped."]

## 来源

- [S0591 原始定位对应材料](../../../../data/evidence/legacy/修补证据/archive_4090_patch/1e280dade4f35690ff37f59b.json)：`4090修补.zip!4090修补/split32_sync_patch_v2/server_results/20261020T162230081774Z-b4e3d46f/20261020T162230081774Z-b4e3d46f.tar.gz!20261020T162230081774Z-b4e3d46f/RESULT.json`

[返回本轮分类结果](../README.md)
