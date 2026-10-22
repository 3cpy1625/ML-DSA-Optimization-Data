# E059 · cuda_api_recovery

设备：RTX-4090。来源轮次：4090 修补资格与故障恢复补充。

状态：`INTERNAL_CUDA_RECOVERY_9_OF_9_PASS_SCOPE_PARTIAL`

覆盖：{"run_id":"20261020T161911383836Z-958989e7","parameters":[44,65,87],"batch":256,"fault_checks":9,"phases":21,"passed_output_byte_checks":12,"unique_selected_vectors":3,"group_complete":false}

边界：["Three CUDA API failure-return probes per parameter: workspace initialization, host-to-device input staging, and device-to-host output export.","Unchanged production Sign DSOs; a new host caller and a process-local LD_PRELOAD interposer are test artifacts, not formal performance binaries.","Each parameter uses the same loaded DSO, stream and workspace for success/fault/recovery across seven calls. No manual workspace clearing occurs between calls.","Failure must propagate backend_error, mark all requests failed, commit none, and preserve sentinel host output. Valid/recovery bytes match the retained selected official vector.","Residual workspace bytes are counted after failures; residual nonzero bytes do not establish secret content but prevent claiming complete automatic zeroization.","These are injected CUDA function return codes, not actual device memory exhaustion, asynchronous device faults, sampler exhaustion, or every internal error path.","No sampler total hard cap or explicit exhaustion status was added by the incremental refill patch. This group remains partial until the missing paths/contracts are addressed.","Three selected official Sign vectors repeated to B256; no new independent KAT coverage, performance claim or sanitizer claim.","150-second admission/execution target including host compilation and shared-lock waits. Packaging, upload, download and user passphrase time are additional."]

## 来源

- [S0592 原始定位对应材料](../../../../data/evidence/legacy/修补证据/archive_4090_patch/3293436e7efdab2d456ee043.json)：`4090修补.zip!4090修补/02_采样异常与恢复/internal_recovery_v1/server_results/20261020T161911383836Z-958989e7/20261020T161911383836Z-958989e7.tar.gz!20261020T161911383836Z-958989e7/RESULT.json`

[返回本轮分类结果](../README.md)
