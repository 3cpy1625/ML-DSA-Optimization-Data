import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import statistics
import struct
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'minimal_v65_20261020T145604Z_6e07c795.tar.gz'
PACKAGE = Path(r'D:\app\微信\记录\xwechat_files\wxid_vuflnub0ujnu22_330b\msg\file\2026-10\mldsa_minimal_v65_20261020.zip')
PATTERNS = ('valid', 'invalid', 'grouped50', 'dispersed50')
GPU = 'GPU-43cf85da-3fa2-0d23-3066-d8781644bb2a'
SOURCE = '61d79c85c0199c049dcac0ad3f752dce789efb57170686f5833bc0b18003fb01'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def invalid(pattern, i):
    return pattern == 'invalid' or pattern == 'grouped50' and i % 256 < 128 or pattern == 'dispersed50' and (73 * i) % 256 < 128

def close(a, b):
    assert math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12), (a, b)

data, hashes, sizes, members = {}, {}, {}, set()
prefix = ARCHIVE.name.removesuffix('.tar.gz')
with tarfile.open(ARCHIVE, 'r|gz') as tar:
    for m in tar:
        p = PurePosixPath(m.name)
        assert not p.is_absolute() and '..' not in p.parts and p.parts[0] == prefix
        assert m.name not in members
        members.add(m.name)
        if m.isdir():
            continue
        assert m.isfile() or m.islnk(), ('unsupported archive member', m.name)
        if m.islnk():
            assert m.linkname in data, ('non-backward link', m.name)
            value = data[m.linkname]
        else:
            value = tar.extractfile(m).read()
            assert len(value) == m.size
        data[m.name] = value
        hashes[m.name] = sha(value)
        sizes[m.name] = len(value)

def read(name):
    return data[prefix + '/' + name]

def js(name):
    return json.loads(read(name))

manifest = js('MANIFEST.json')['files']
assert len({x['path'] for x in manifest}) == len(manifest)
assert {prefix + '/' + x['path'] for x in manifest} == set(data) - {prefix + '/MANIFEST.json'}
for f in manifest:
    key = prefix + '/' + f['path']
    assert hashes[key] == f['sha256'] and sizes[key] == f['bytes'], key
with zipfile.ZipFile(PACKAGE) as z:
    for name in ('anchors.json', 'verify_minimal.py'):
        assert z.read(name) == read(name), name
anchors, build, preflight, result = (js(n) for n in ('anchors.json', 'BUILD.json', 'PREFLIGHT.json', 'RESULT.json'))
assert result['status'] == 'COMPLETE' and preflight['status'] == 'PINNED_FILES_PASS'
assert anchors['gpu'] == GPU and anchors['framework_sha256'] == SOURCE
assert anchors['files'] == preflight['files']
build_anchor = next(x for x in anchors['files'] if x['path'].endswith('/BUILD.json'))
assert sha(read('BUILD.json')) == build_anchor['sha256']
records = result['records']
expected_order = [(256, -1, p, a) for p in PATTERNS for a in ('ON', 'OFF')]
expected_order += [(8192, b, p, a) for b in range(6) for p in PATTERNS[b % 4:] + PATTERNS[:b % 4] for a in (('ON', 'OFF') if b % 2 == 0 else ('OFF', 'ON'))]
assert [(r['batch'], r['block'], r['pattern'], r['arm']) for r in records] == expected_order
originals = {b: read(f'b{b}_block{(-1 if b == 256 else 0)}_valid_ON/input.bin') for b in (256, 8192)}
expected_inputs = {}
for b, original in originals.items():
    assert len(original) == b * (3309 + 32 + 1952)
    fact = next(x for x in anchors['files'] if x['path'].endswith(f'/reference_{b}/input.bin'))
    assert sha(original) == fact['sha256']
    for p in PATTERNS:
        mutated = bytearray(original)
        for i in range(b):
            if invalid(p, i):
                mutated[i * 3309 + 48:i * 3309 + 51] = bytes(3)
        expected_inputs[b, p] = bytes(mutated)
        assert sha(mutated) == preflight['expected_input_sha256'][str(b)][p]

timings = 0
for r in records:
    b, p, a, job = r['batch'], r['pattern'], r['arm'], r['job']
    assert js(job + '/PASS.json') == r
    inp, out = read(job + '/input.bin'), read(job + '/output.bin')
    assert inp == expected_inputs[b, p] and sha(inp) == r['input_sha256']
    assert len(out) == b * 4 and sha(out) == r['output_sha256']
    statuses = struct.unpack('<' + 'i' * b, out)
    assert all((v < 0 if invalid(p, i) else v == 0) for i, v in enumerate(statuses))
    assert sum(v == 0 for v in statuses) == r['accepted_rows']
    proc = js(job + '/PROCESS.json')
    assert proc['exit_code'] == 0 and not read(job + '/stderr.log')
    argv = proc['argv']
    assert argv[0] == build[a]['bench']
    opts = dict(zip(argv[1::2], argv[2::2]))
    repeat = 1 if b == 256 else 15
    assert opts['--batch'] == str(b) and opts['--repeat'] == str(repeat)
    assert opts['--warmup'] == ('0' if b == 256 else '5')
    assert opts['--operation'] == 'verify' and opts['--level'] == '65'
    assert opts['--timing-scope'] == 'device-resident' and opts['--corpus'] == 'natural'
    assert opts['--module-dir'] == build[a]['modules'] and opts['--message-bytes'] == '32'
    if p == 'invalid':
        assert opts['--verify-invalid-z-stride'] == '1'
    elif p in ('grouped50', 'dispersed50'):
        assert [opts['--verify-invalid-z-' + k] for k in ('numerator', 'denominator', 'offset', 'multiplier')] == ['128', '256', '0', '1' if p == 'grouped50' else '73']
    csvrows = list(csv.reader(io.StringIO(read(job + '/stdout.log').decode())))
    raw = [v for v in csvrows if v and v[0] == 'raw']
    summary = [v for v in csvrows if len(v) > 2 and v[:2] == ['summary', 'ML-DSA']]
    assert len(raw) == repeat and len(summary) == 1 and summary[0][-1] == 'PASS'
    assert all(len(v) == 11 and v[1:5] == ['ML-DSA', 'verify', '3', str(b)] and v[6:9] == ['unified', 'DEVICE_RESIDENT_GPU_INTERVAL', 'natural'] for v in raw)
    assert [int(v[9]) for v in raw] == list(range(repeat))
    values = [float(v[10]) for v in raw]
    assert all(math.isfinite(v) and v > 0 for v in values) and values == r['samples_ms']
    close(statistics.mean(values), r['mean_ms'])
    timings += repeat if b == 8192 else 0
    native, engine = js(job + '/native.json'), js(job + '/engine.json')
    for identity in (native, engine):
        device = identity['cuda_device']
        assert device['uuid'].replace('-', '').lower() == GPU[4:].replace('-', '').lower()
        assert (device['compute_capability_major'], device['compute_capability_minor']) == (12, 0)
    assert engine['framework_source_sha256'] == SOURCE and len(engine['modules']) == 1
    module = engine['modules'][0]
    assert module['attested'] is True
    assert module['sha256'] == module['post_load_sha256'] == module['expected_sha256'] == build[a]['sha256']
    modulepath = build[a]['modules'] + '/libloce_mldsa65_verify_d3_sm120.so'
    assert native['loaded_path'] == module['path'] == modulepath
    assert native['pre_load_sha256'] == native['post_load_sha256'] == build[a]['sha256']
    assert native['operation'] == 'verify' and native['level'] == 3
    assert all(native['embedded'].get(k) == v for k, v in build[a]['embedded_identity'].items() if k != 'abi_version')
    observations = [json.loads(v) for v in read(job + '/GPU.jsonl').decode().splitlines() if v.strip()]
    assert len(observations) >= 3
    assert all(all(pid == proc['pid'] for pid in obs['pids']) and obs['gpu_csv'].startswith(GPU + ',') for obs in observations)
    after = js(job + '/GPU_AFTER.json')
    assert not after['pids'] and after['memory_mib'] <= 200

rows = list(csv.DictReader(io.StringIO(read('summary.csv').decode())))
assert [r['pattern'] for r in rows] == list(PATTERNS) and timings == 720
paired = list(csv.DictReader(io.StringIO(read('paired_blocks.csv').decode())))
assert len(paired) == 24
for row in rows:
    pattern = row['pattern']
    pairs, on, off = [], [], []
    for block in range(6):
        pair = {r['arm']: r for r in records if r['batch'] == 8192 and r['block'] == block and r['pattern'] == pattern}
        assert pair['ON']['input_sha256'] == pair['OFF']['input_sha256']
        on.append(pair['ON']['mean_ms']); off.append(pair['OFF']['mean_ms'])
        pairs.append(off[-1] / on[-1])
        entry = [x for x in paired if x['pattern'] == pattern and int(x['block']) == block]
        assert len(entry) == 1
        for key, value in [('on_ms', on[-1]), ('off_ms', off[-1]), ('off_over_on', pairs[-1])]:
            close(entry[0][key], value)
    ratio = math.exp(statistics.mean(math.log(x) for x in pairs))
    for key, value in [('on_mean_ms', statistics.mean(on)), ('off_mean_ms', statistics.mean(off)), ('paired_geomean_speedup', ratio), ('min_pair_ratio', min(pairs)), ('max_pair_ratio', max(pairs)), ('time_reduction_pct', 100 * (1 - 1 / ratio))]:
        close(row[key], value)
        close(next(x for x in result['summary'] if x['pattern'] == pattern)[key], value)
    assert int(row['pairs']) == 6 and int(row['batch']) == 8192

with ARCHIVE.open('rb') as f:
    archive_sha = hashlib.file_digest(f, 'sha256').hexdigest()
report = dict(status='LOCALLY_VERIFIED_PASS', archive=str(ARCHIVE), archive_sha256=archive_sha,
              manifest_files_verified=len(manifest), qualification_processes=8,
              performance_processes=48, performance_timings=720,
              capture_elapsed_seconds=result['elapsed_seconds'], summary=rows,
              limitations=result['limitations'], transport_note='Remote archive checksum not downloaded; gzip integrity and all internal manifest hashes verified. GPU exclusivity checked only at recorded observations.')
for name in ('summary.csv', 'paired_blocks.csv', 'RESULT.json', 'PREFLIGHT.json', 'BUILD.json', 'anchors.json'):
    target = ROOT / name
    assert not target.exists(), 'Preserve existing output: ' + str(target)
    target.write_bytes(read(name))
(ROOT / 'LOCAL_VERIFICATION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
(ROOT / (ARCHIVE.name + '.sha256')).write_text(archive_sha + '  ' + ARCHIVE.name + '\n', encoding='ascii')
print(json.dumps(report, ensure_ascii=False, indent=2))
