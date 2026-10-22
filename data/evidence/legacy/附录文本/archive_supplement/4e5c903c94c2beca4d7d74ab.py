#!/usr/bin/env python3
"""Bounded V65 distribution capture; reuses pinned binaries, never builds."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import signal
import statistics
import struct
import subprocess
import sys
import tarfile
import time
import uuid

HERE = Path(__file__).resolve().parent
PATTERNS = ("valid", "invalid", "grouped50", "dispersed50")
SOURCE_NAME = "libloce_mldsa65_verify_d3_sm120.so"
MAX_SECONDS = 1800


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def invalid_at(pattern, i):
    require(pattern in PATTERNS, "Unknown pattern")
    return (pattern == "invalid"
            or pattern == "grouped50" and i % 256 < 128
            or pattern == "dispersed50" and (73 * i) % 256 < 128)


def expected_input(original, batch, pattern):
    require(len(original) == batch * (3309 + 32 + 1952),
            "Wrong V65 input length")
    result = bytearray(original)
    for i in range(batch):
        if invalid_at(pattern, i):
            start = i * 3309 + 48
            result[start:start + 3] = b"\0\0\0"
    return bytes(result)


def check_output(data, batch, pattern):
    require(len(data) == batch * 4, "Wrong Verify output size")
    values = struct.unpack("<" + "i" * batch, data)
    require(all((v < 0 if invalid_at(pattern, i) else v == 0)
                for i, v in enumerate(values)), "Wrong per-row Verify results")
    return sum(v == 0 for v in values)


def check_corpus(path, original, batch):
    blob = Path(path).read_bytes()
    require(len(blob) >= 112, "Truncated natural corpus")
    header = struct.unpack("<8sIIQIIIIII32s32s", blob[:112])
    require(header[:10] == (b"MLDNAT02", 2, 65, batch, 1, 32, 1952, 4032, 3309, 9437),
            "Wrong natural corpus header")
    payload = memoryview(blob)[112:]
    require(len(payload) == batch * 9437
            and hashlib.sha256(payload).digest() == header[11], "Corrupt corpus payload")
    rebuilt = bytearray()
    for i in range(batch):
        require(struct.unpack_from("<II", payload, i * 9437) == (i, 1),
                "Wrong corpus row identity")
    for start, count in ((6088, 3309), (40, 32), (104, 1952)):
        for i in range(batch):
            offset = i * 9437 + start
            rebuilt.extend(payload[offset:offset + count])
    require(rebuilt == original, "Corpus differs from retained CPU-reference Verify input")


def parse_samples(text, repeats, batch):
    rows = list(csv.reader(io.StringIO(text)))
    raw = [r for r in rows if r and r[0] == "raw"]
    summaries = [r for r in rows if len(r) > 2
                 and r[0] == "summary" and r[1] == "ML-DSA"]
    require(len(raw) == repeats and len(summaries) == 1
            and summaries[0][-1] == "PASS", "Incomplete/failed benchmark output")
    require(all(len(r) == 11 and r[1:5] == ["ML-DSA", "verify", "3", str(batch)]
                and r[6:9] == ["unified", "DEVICE_RESIDENT_GPU_INTERVAL", "natural"]
                for r in raw), "Wrong timing scope or operation")
    require([int(r[9]) for r in raw] == list(range(repeats)),
            "Wrong measurement iteration sequence")
    samples = [float(r[10]) for r in raw]
    require(all(math.isfinite(v) and v > 0 for v in samples), "Invalid times")
    return samples


def check_identities(engine, native, config, anchors):
    expected_sha = config["sha256"]
    gpu_hex = anchors["gpu"][4:].replace("-", "").lower()
    for identity in (engine, native):
        device = identity["cuda_device"]
        require(device["uuid"].replace("-", "").lower() == gpu_hex
                and device["compute_capability_major"] == 12
                and device["compute_capability_minor"] == 0, "Wrong loaded GPU")
    require(engine["framework_source_sha256"] == anchors["framework_sha256"],
            "Framework identity changed")
    require(len(engine["modules"]) == 1, "Unexpected loaded module set")
    module = engine["modules"][0]
    require(Path(module["path"]) == Path(config["modules"]) / SOURCE_NAME,
            "Wrong loaded module path")
    require(module["attested"] is True
            and module["sha256"] == module["post_load_sha256"]
            == module["expected_sha256"] == expected_sha,
            "Loaded module hash or attestation mismatch")
    require(native["pre_load_sha256"] == native["post_load_sha256"] == expected_sha
            and Path(native["loaded_path"]) == Path(config["modules"]) / SOURCE_NAME
            and native["operation"] == "verify" and native["level"] == 3,
            "Native module identity mismatch")
    for key, value in config["embedded_identity"].items():
        if key != "abi_version":
            require(native["embedded"].get(key) == value,
                    "Embedded identity mismatch: " + key)


class Capture:
    def __init__(self):
        require(sys.platform == "linux", "Run check/run on the Linux 5090 server")
        self.anchors = load(HERE / "anchors.json")
        self.base = Path(self.anchors["base"])
        self.gpu = self.anchors["gpu"]
        self.old = self.base / self.anchors["source_run"]
        root = self.base / "新5090"
        require(root.is_dir() and not root.is_symlink(), "Original output root missing")
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run = root / ("minimal_v65_" + stamp + "_" + uuid.uuid4().hex[:8])
        self.run.mkdir()
        self.started = time.monotonic()
        self.deadline = self.started + MAX_SECONDS
        self.records = []
        self.result = {
            "status": "PREFLIGHT", "run": str(self.run),
            "scope": "V65 CTA ON/OFF, B8192, fixed corpus, four invalid-z distributions",
            "deadline_seconds": MAX_SECONDS, "performance_processes_planned": 48,
            "qualification_processes_planned": 8, "timing_samples_planned": 720,
            "limitations": [
                "One fixed input corpus; timings are not independent inputs",
                "Device-resident full-operation interval; no host setup/transfers",
                "Checks final timed output, not every timed output",
                "Retained valid CPU oracle reused; mutation statuses checked by construction",
                "No new independent standard KAT or sanitizer qualification",
                "Historical 4090 comparison is mechanism-level, not pure hardware attribution"],
            "records": self.records}
        self.env = {k: v for k, v in os.environ.items()
                    if k in ("HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL")}
        self.env.update(
            PATH=str(self.base / "tools/python312/bin") + ":"
                 + str(self.base / "tools/cuda-12.9.1/bin") + ":/usr/bin:/bin",
            LD_LIBRARY_PATH=str(self.base / "tools/cuda-12.9.1/lib64"),
            CUDA_VISIBLE_DEVICES=self.gpu, OMP_NUM_THREADS="2")
        shutil.copy2(HERE / "anchors.json", self.run / "anchors.json")
        shutil.copy2(__file__, self.run / "verify_minimal.py")
        self.save()
        print("RUN=" + str(self.run), flush=True)

    def save(self):
        self.result["elapsed_seconds"] = round(time.monotonic() - self.started, 3)
        write_json(self.run / "RESULT.json", self.result)

    def time_left(self):
        value = self.deadline - time.monotonic()
        require(value > 0, "30-minute total capture limit reached")
        return value

    def smi(self, args):
        self.time_left()
        return subprocess.check_output(
            ["nvidia-smi", "-i", self.gpu] + args,
            text=True, stderr=subprocess.STDOUT,
            timeout=min(10, self.time_left()), env=self.env)

    def snapshot(self):
        gpu = self.smi(["--query-gpu=uuid,name,memory.used,utilization.gpu,"
                        "temperature.gpu,clocks.sm,power.draw",
                        "--format=csv,noheader,nounits"])
        processes = self.smi(["--query-compute-apps=pid,process_name",
                              "--format=csv,noheader"])
        row = next(csv.reader(io.StringIO(gpu)))
        require(row[0].strip() == self.gpu and "5090" in row[1], "Wrong GPU")
        pids = [int(r[0].strip()) for r in csv.reader(io.StringIO(processes)) if r]
        return {"utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "gpu_csv": gpu.strip(), "pids": pids,
                "memory_mib": float(row[2]), "utilization": float(row[3])}

    def wait_idle(self, log):
        end = min(self.deadline, time.monotonic() + 120)
        quiet = 0
        with log.open("a", encoding="utf-8") as out:
            while time.monotonic() < end:
                obs = self.snapshot()
                out.write(json.dumps(obs) + "\n")
                out.flush()
                good = not obs["pids"] and obs["memory_mib"] <= 200 and obs["utilization"] <= 2
                quiet = quiet + 1 if good else 0
                if quiet >= 3:
                    return
                time.sleep(min(1, self.time_left()))
        raise RuntimeError("GPU not idle within 120 seconds; no process launched")

    def preflight(self):
        facts = []
        for fact in self.anchors["files"]:
            self.time_left()
            path = self.base / fact["path"]
            require(path.is_file() and not path.is_symlink(), "Missing regular file: " + str(path))
            require(path.stat().st_size == fact["bytes"]
                    and digest(path) == fact["sha256"], "Pinned file changed: " + str(path))
            facts.append(fact)
        self.config = load(self.old / "BUILD.json")
        require(set(self.config) == {"ON", "OFF"}, "Wrong build arms")
        for c in self.config.values():
            require(os.access(c["bench"], os.X_OK), "Benchmark is not executable")
        require(shutil.disk_usage(self.run).free >= 2 * 1024**3,
                "Need at least 2 GiB free; do not delete historical evidence")
        self.refs = {}
        for batch in (256, 8192):
            ref = self.old / ("reference_" + str(batch))
            original = (ref / "input.bin").read_bytes()
            require((ref / "output.bin").read_bytes() == bytes(batch * 4),
                    "Retained valid CPU oracle must accept every row")
            check_corpus(ref / "corpus.bin", original, batch)
            self.refs[batch] = {}
            for pattern in PATTERNS:
                data = expected_input(original, batch, pattern)
                self.refs[batch][pattern] = hashlib.sha256(data).hexdigest()
        write_json(self.run / "PREFLIGHT.json", {
            "status": "PINNED_FILES_PASS", "files": facts,
            "gpu": self.snapshot(), "expected_input_sha256": self.refs})
        shutil.copy2(self.old / "BUILD.json", self.run / "BUILD.json")
        for batch in (256, 8192):
            shutil.copy2(self.old / ("reference_" + str(batch)) / "ORIGINAL_MANIFEST.json",
                         self.run / ("CPU_REFERENCE_" + str(batch) + ".json"))
        self.result["status"] = "PREFLIGHT_PASS"
        self.save()

    @staticmethod
    def stop_owned(child):
        if child.poll() is not None:
            return
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)

    def deduplicate(self, path):
        key = digest(path)
        pool = self.run / "verified_blobs"
        pool.mkdir(exist_ok=True)
        shared = pool / (key + ".bin")
        require(path.parent.parent == self.run and not path.is_symlink(),
                "Unexpected newly-created output path")
        if shared.exists():
            require(not shared.is_symlink() and digest(shared) == key,
                    "Existing evidence blob changed")
            # Only a just-created, verified file in this new run is replaced.
            path.unlink()
            os.link(shared, path)
        else:
            os.link(path, shared)
        return key

    def invoke(self, arm, batch, block, pattern):
        self.time_left()
        job = self.run / ("b%d_block%d_%s_%s" % (batch, block, pattern, arm))
        job.mkdir()
        c = self.config[arm]
        self.wait_idle(job / "GPU.jsonl")
        require(digest(c["bench"]) == c["bench_sha256"]
                and digest(Path(c["modules"]) / SOURCE_NAME) == c["sha256"],
                "Benchmark/module changed before launch")
        require(shutil.disk_usage(self.run).free >= 512 * 1024**2,
                "Less than 512 MiB free; stopping")
        repeat = 1 if batch == 256 else 15
        argv = [c["bench"], "--algorithm", "mldsa", "--operation", "verify",
                "--level", "65", "--batch", str(batch), "--variant", "unified",
                "--timing-scope", "device-resident", "--representation", "packed",
                "--corpus", "natural", "--corpus-file",
                str(self.old / ("reference_" + str(batch)) / "corpus.bin"),
                "--warmup", "0" if batch == 256 else "5", "--repeat", str(repeat),
                "--message-bytes", "32", "--seed", "0x4d4c445341435550",
                "--module-dir", c["modules"]]
        if pattern == "invalid":
            argv += ["--verify-invalid-z-stride", "1"]
        elif pattern in ("grouped50", "dispersed50"):
            argv += ["--verify-invalid-z-numerator", "128",
                     "--verify-invalid-z-denominator", "256",
                     "--verify-invalid-z-offset", "0",
                     "--verify-invalid-z-multiplier", "1" if pattern == "grouped50" else "73"]
        env = dict(self.env)
        env.update(LOCE_BENCH_INPUT_FILE=str(job / "input.bin"),
                   LOCE_BENCH_OUTPUT_FILE=str(job / "output.bin"),
                   LOCE_NATIVE_DIRECT_IDENTITY_OUTPUT=str(job / "native.json"),
                   LOCE_MODULE_IDENTITY_OUTPUT=str(job / "engine.json"))
        process = {"argv": argv, "environment_overrides": {
            k: v for k, v in env.items()
            if k.startswith(("LOCE_", "CUDA_", "OMP_", "LD_LIBRARY"))}}
        write_json(job / "PROCESS.json", process)
        start = time.monotonic()
        def child_file_limits():
            import resource
            resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024**2, 128 * 1024**2))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        with (job / "stdout.log").open("wb") as out, (job / "stderr.log").open("wb") as err:
            child = subprocess.Popen(argv, stdout=out, stderr=err, env=env,
                                     start_new_session=True, preexec_fn=child_file_limits)
            process["pid"] = child.pid
            try:
                with (job / "GPU.jsonl").open("a", encoding="utf-8") as monitor:
                    while child.poll() is None:
                        self.time_left()
                        require(time.monotonic() - start < 120, "Single process exceeded 120 seconds")
                        obs = self.snapshot()
                        monitor.write(json.dumps(obs) + "\n")
                        monitor.flush()
                        require(all(pid == child.pid for pid in obs["pids"]),
                                "Another GPU process appeared; block not accepted")
                        time.sleep(min(.25, self.time_left()))
            finally:
                self.stop_owned(child)
                process.update(exit_code=child.poll(),
                               elapsed_seconds=time.monotonic() - start)
                write_json(job / "PROCESS.json", process)
        require(child.returncode == 0, "Benchmark failed; inspect saved logs")
        require((job / "stderr.log").stat().st_size == 0,
                "Nonempty benchmark stderr; inspect before accepting")
        post = self.snapshot()
        write_json(job / "GPU_AFTER.json", post)
        require(not post["pids"] and post["memory_mib"] <= 200, "GPU occupied after process")
        require(digest(job / "input.bin") == self.refs[batch][pattern],
                "Actual mutated input differs from CPU-reference input")
        accepted = check_output((job / "output.bin").read_bytes(), batch, pattern)
        check_identities(load(job / "engine.json"), load(job / "native.json"),
                         c, self.anchors)
        values = parse_samples((job / "stdout.log").read_text(), repeat, batch)
        record = {"arm": arm, "batch": batch, "block": block, "pattern": pattern,
                  "job": job.name, "accepted_rows": accepted, "samples_ms": values,
                  "mean_ms": statistics.mean(values),
                  "input_sha256": self.deduplicate(job / "input.bin"),
                  "output_sha256": self.deduplicate(job / "output.bin")}
        write_json(job / "PASS.json", record)
        self.records.append(record)
        self.result["status"] = "CAPTURING"
        self.save()
        print("PASS", job.name, "accepted_rows=" + str(accepted), flush=True)

    def collect(self):
        for pattern in PATTERNS:
            for arm in ("ON", "OFF"):
                self.invoke(arm, 256, -1, pattern)
        for block in range(6):
            for pattern in PATTERNS[block % 4:] + PATTERNS[:block % 4]:
                for arm in (("ON", "OFF") if block % 2 == 0 else ("OFF", "ON")):
                    self.invoke(arm, 8192, block, pattern)
        require(len(self.records) == 56, "Incomplete experiment")
        rows, paired = [], []
        for pattern in PATTERNS:
            ratios, on, off = [], [], []
            for block in range(6):
                pair = {r["arm"]: r for r in self.records
                        if r["batch"] == 8192 and r["pattern"] == pattern and r["block"] == block}
                require(set(pair) == {"ON", "OFF"}
                        and pair["ON"]["input_sha256"] == pair["OFF"]["input_sha256"],
                        "Unmatched pair")
                ratio = pair["OFF"]["mean_ms"] / pair["ON"]["mean_ms"]
                ratios.append(ratio)
                on.append(pair["ON"]["mean_ms"])
                off.append(pair["OFF"]["mean_ms"])
                paired.append({"pattern": pattern, "block": block,
                               "on_ms": on[-1], "off_ms": off[-1], "off_over_on": ratio})
            speedup = math.exp(statistics.mean(math.log(x) for x in ratios))
            rows.append({"pattern": pattern, "batch": 8192, "pairs": 6,
                         "on_mean_ms": statistics.mean(on), "off_mean_ms": statistics.mean(off),
                         "paired_geomean_speedup": speedup,
                         "time_reduction_pct": 100 * (1 - 1 / speedup),
                         "min_pair_ratio": min(ratios), "max_pair_ratio": max(ratios)})
        for name, values in (("summary.csv", rows), ("paired_blocks.csv", paired)):
            with (self.run / name).open("w", encoding="utf-8", newline="") as out:
                writer = csv.DictWriter(out, fieldnames=list(values[0]))
                writer.writeheader()
                writer.writerows(values)
        # Revalidate retained artifacts after all processes, without recompilation.
        for fact in self.anchors["files"]:
            self.time_left()
            require(digest(self.base / fact["path"]) == fact["sha256"],
                    "Retained artifact changed during capture")
        self.result.update(status="COMPLETE", qualification_processes=8,
                           performance_processes=48, raw_performance_samples=720,
                           summary=rows)
        self.save()


def package(run):
    manifest = [{"path": str(p.relative_to(run)), "bytes": p.stat().st_size,
                 "sha256": digest(p)}
                for p in sorted(run.rglob("*")) if p.is_file()]
    write_json(run / "MANIFEST.json", {"files": manifest})
    target = run.with_name(run.name + ".tar.gz")
    require(not target.exists(), "Archive already exists")
    with tarfile.open(target, "w:gz", compresslevel=1, dereference=False) as tar:
        tar.add(run, arcname=run.name)
    target.with_name(target.name + ".sha256").write_text(
        digest(target) + "  " + target.name + "\n", encoding="ascii")
    (HERE / "LATEST_ARCHIVE.txt").write_text(str(target) + "\n", encoding="utf-8")
    print("ARCHIVE=" + str(target), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "run"))
    args = parser.parse_args()
    if args.action == "run":
        (HERE / "LATEST_ARCHIVE.txt").write_text("", encoding="utf-8")
    capture = None
    code = 0
    try:
        capture = Capture()
        capture.preflight()
        if args.action == "check":
            print("PREFLIGHT_PASS: files verified; no benchmark launched", flush=True)
            return 0
        capture.collect()
        print("COMPLETE: 8 qualification + 48 performance processes; 720 timings", flush=True)
    except BaseException as error:
        code = 1
        print("STOPPED:", repr(error), flush=True)
        if capture is not None:
            capture.result.update(status="STOPPED", error=repr(error))
            capture.save()
    if capture is not None and args.action == "run":
        try:
            package(capture.run)
        except Exception as error:
            code = 1
            print("PACKAGE_FAILED:", repr(error), "raw evidence kept at", capture.run, flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
