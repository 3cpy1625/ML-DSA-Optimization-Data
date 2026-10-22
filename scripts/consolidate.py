from pathlib import Path
import json,csv,math,statistics,collections,re,sys
sys.stdout.reconfigure(encoding='utf-8')
import argparse
parser=argparse.ArgumentParser(description='Consolidate shipped normalized source records; no GPU execution.')
parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
ROOT=args.repo.resolve()
BASE=ROOT/'data/derived/records'
OUT=args.output.resolve()
OUT.mkdir(parents=True,exist_ok=True)
CONFIG={'include_supplement':True,'include_4090_patch':True}
keys=['archive_old','archive_4090','archive_5090','archive_new5090']
if CONFIG.get('include_supplement'):keys.append('archive_supplement')
if CONFIG.get('include_4090_patch'):keys.append('archive_4090_patch')
data={k:json.loads((BASE/k/'analysis.json').read_text('utf-8')) for k in keys}
cat=json.loads((BASE/'catalog.json').read_text('utf-8'))
source_registry={}
def text(v):
    if v is None:return ''
    if isinstance(v,(dict,list)):return json.dumps(v,ensure_ascii=False,separators=(',',':'))
    return str(v)
def num(v):
    if v is None or isinstance(v,bool) or v=='':return None
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None
def src(archive,source,sha=''):
    s='；'.join(source) if isinstance(source,list) else text(source)
    if not s:return ''
    key=(archive,s)
    if key not in source_registry:
        source_registry[key]=dict(来源ID=f'S{len(source_registry)+1:04d}',来源包=archive,包内路径=s,SHA256=sha)
    elif sha and not source_registry[key]['SHA256']:source_registry[key]['SHA256']=sha
    return source_registry[key]['来源ID']
def source_fields(archive,r):
    return [src(archive,r.get('source',''),r.get('source_sha256',r.get('sha256',''))),r.get('line',r.get('source_line')),r.get('json_pointer','')]
main=[]
for r in data['archive_old']['metrics']:
    if r['experiment']!='4090历史R02配对':continue
    main.append(['4090 历史 R02','RTX 4090',r['parameter'],r['operation'],r['batch'],32,r['candidate_ms'],r['control_ms'],'6进程中位数的中位数',r['value'],r['ci_low'],r['ci_high'],None,None,6,15,'历史27格；已从stdout重算点估计及CI','cuPQC 0.4.1 / G3','完整设备驻留操作']+source_fields(data['archive_old']['archive'],r))
for r in data['archive_4090']['recommended_performance']:
    repl=text(r.get('replaces_original_cell')).lower()=='true'
    main.append(['4090 10/18+10/19修订','RTX 4090',int(r['parameter']),r['operation'],int(r['batch']),32,float(r['ours_mean_ms']),float(r['cupqc_mean_ms']),'6进程均值的均值',float(r['geomean_paired_speedup']),None,None,num(r.get('speedup_block_min')),num(r.get('speedup_block_max')),6,15,'替换复测；不与原样本合并' if repl else '10/18原测保留','cuPQC 0.4.1 / ours','device-resident；固定BlockDim=128、单流']+source_fields(data['archive_4090']['archive'],r))
for r in data['archive_5090']['main_results']:
    main.append(['5090 E03 B8192','RTX 5090',int(r['parameter']),r['operation'],8192,32,float(r['ours_mean_ms']),float(r['cupqc_mean_ms']),'6进程均值的均值',float(r['geomean_paired_speedup']),None,None,None,None,6,15,'固定配置探索性结果；封存DSO sanitizer未运行','cuPQC 0.4.1 / ours','device-resident；固定BlockDim=128、单流']+source_fields(data['archive_5090']['archive'],r))
maincols=['结果系列','GPU','参数集','操作','批量','消息字节','本项目耗时_ms','cuPQC耗时_ms','耗时归约方法','配对几何加速比_x','CI95下界_x','CI95上界_x','观测配对最小_x','观测配对最大_x','配对区组数','每进程计时次数','数据状态','比值方向','计时范围','来源ID','源行号','JSON定位']
metriccols=['实验系列','GPU','参数集或mode','操作','批量','条件或后端','指标原名','值','单位','对照分子','候选分母','重复数','重复单位','状态或用途','CI95下界','CI95上界','来源ID','源行号','JSON定位']
ablation=[];micro=[];aux=[];correct=[]
correctcols=['来源包','实验系列','参数集或mode','操作','批量','用例','工具或检查项','状态','报告错误数','拒绝数','备注','来源ID','源行号','JSON定位']
def canonical_metric(r,archive,default_gpu=''):
    family=r.get('experiment',r.get('family',r.get('experiment_id','')))
    condition=r.get('variant',r.get('input_type',r.get('case',r.get('backend',''))))
    if r.get('notes'):condition=text(condition)+'；'+text(r['notes'])
    return [family,r.get('gpu',default_gpu),num(r.get('parameter',r.get('level',r.get('mode')))),r.get('operation',''),num(r.get('batch')),text(condition),r.get('metric',''),num(r.get('value')),r.get('unit',''),r.get('control',''),r.get('candidate',''),num(r.get('n')),'见原表口径',r.get('status',r.get('notes','')),num(r.get('ci_low')),num(r.get('ci_high'))]+source_fields(archive,r)
for r in data['archive_old']['metrics']:
    if r['experiment']=='4090历史R02配对':continue
    row=canonical_metric(r,data['archive_old']['archive'])
    row[12]='配对区组';ablation.append(row)
for r in data['archive_5090']['metrics']:
    if r['experiment']=='E03_B8192':continue
    row=canonical_metric(r,data['archive_5090']['archive'])
    if any(s in r['experiment'].upper() for s in ['NTT','SHAKE','SPLIT32']):
        row[12]='GPU进程；每进程15次；固定语料'
        micro.append(row)
    else:
        if 'E05' in r['experiment']:row[12]='GPU进程；每进程15测量范围'
        aux.append(row)
for r in data['archive_5090']['correctness']:
    correct.append([data['archive_5090']['archive'],r.get('experiment',''),num(r.get('level')),r.get('operation',''),num(r.get('batch')),r.get('case_id',''),r.get('tool',r.get('check','')),r.get('status',''),num(r.get('reported_errors')),num(r.get('rejected_count')),text(r.get('tool_result',r.get('application_checks_status','')))]+source_fields(data['archive_5090']['archive'],r))
for table in json.loads((BASE/'archive_old/tables.json').read_text('utf-8')):
    name=Path(table['source']).name
    if name not in ['MLDSA_G5_BYTE_CORRECTNESS.csv','MLDSA_SANITIZER_RESULTS.csv','原始正确性九组结果.csv','原始大批量KeyGen结果.csv']:continue
    for r in table['rows']:
        rr=dict(r,source=table['source'],line=r['_source_line'],sha256=table['sha256'])
        note='截图转录；未收到完整服务器日志' if name.startswith('原始') else '历史记录；本次未重跑GPU'
        correct.append([data['archive_old']['archive'],name,num(r.get('parameter')),r.get('operation',''),num(r.get('batch')),'',r.get('tool','byte_identity'),r.get('status',''),None,None,note]+source_fields(data['archive_old']['archive'],rr))
skipfamilies={'4090_ours_vs_cupqc_original','4090_ours_vs_cupqc_recommended'}
idkeys={'parameter','mode','level','batch','source_line','source_line_end','block','process_index','index','seed','message_bytes'}
numeric_context={'processes','process_runs','paired_processes','process_pairs','process_blocks','paired_process_blocks','accepted_processes','samples_per_process','warmups_per_process','input_datasets','blocks','accepted_blocks','repetitions_per_process','cupqc_block_dim','cupqc_streams'}
def unit_for(k):
    if 'bytes' in k:return 'byte'
    if k.endswith('_ms') or '_ms_' in k:return 'ms'
    if k.endswith('_ns') or '_ns_' in k:return 'ns'
    if 'pct' in k or 'percent' in k:return '%'
    if 'per_second' in k or 'ops_s' in k:return 'ops/s'
    if any(x in k for x in ['ratio','speedup','over_']):return 'x'
    return '原指标单位'
for r in data['archive_4090']['metrics']:
    f=r['family']
    if f in skipfamilies or f.startswith('historical_'):continue
    if any(s in f for s in ['correctness','sanitizer']):
        note='仅诊断；不作为正常性能' if 'diagnostic_gpu_ms' in r else ''
        if f=='sanitizer_supplement_72':note+='；复用/新增='+r.get('provenance','')+'；工具结果为0错误，不含racecheck'
        correct.append([data['archive_4090']['archive'],f,num(r.get('parameter',r.get('level',r.get('mode')))),r.get('operation',''),num(r.get('batch')),r.get('case_id',r.get('case',r.get('pattern',''))),r.get('tool',r.get('check','')),r.get('status',r.get('output_check','SOURCE_REPORTED_ZERO_ERRORS' if num(r.get('reported_errors'))==0 else '')),num(r.get('reported_errors')),num(r.get('rejected_count')),note]+source_fields(data['archive_4090']['archive'],r))
        continue
    condition='; '.join(f'{k}={r[k]}' for k in ['case','backend','stop','comparison','ratio','kernel_name','block','process_index'] if k in r and num(r[k]) is None)
    n=next((num(r[k]) for k in ['paired_processes','process_pairs','paired_process_blocks','process_blocks','processes','process_runs','accepted_processes','accepted_blocks','blocks'] if k in r and num(r[k]) is not None),None)
    target=micro if any(x in f for x in ['shake','ntt']) else ablation if any(x in f for x in ['ablation','zero_copy']) else aux
    for k,v in r.items():
        val=num(v)
        if val is None or k in idkeys or k in numeric_context:continue
        # Original detailed CSV retains protocol identifiers and ancillary fields.
        if any(x in k for x in ['sha256','source','signature','binary','attempt_id']):continue
        control=r.get('numerator',r.get('implementation',''))
        candidate=r.get('denominator','')
        status=r.get('review_status',r.get('scope',r.get('timing_scope','')))
        if f in ['m44_zero_copy_3','m65_early_reject_ablation_36']:
            control='OFF';candidate='ON'
        if f=='m44_zero_copy_3':
            active=text(r.get('on_source_path_expected_active')).lower()=='true'
            status='路径预期激活' if active else 'B8192路径未激活对照；不能解释为零拷贝收益'
        if f.startswith('legacy_'):status='legacy Dilithium v3.1；非FIPS204可比；HOST_API含传输'
        if f=='host_api_vs_device_27':status='host/API与device缓冲契约不同；非隔离传输开销；非完整应用E2E'
        repeats='进程级重复；固定语料'
        if 'process_ratios' in f:repeats='单个配对block；此行非跨block汇总';n=1
        row=[f,'RTX 4090',num(r.get('parameter',r.get('mode'))),r.get('operation',''),num(r.get('batch')),condition,k,val,unit_for(k),control,candidate,n,repeats,status,None,None]+source_fields(data['archive_4090']['archive'],r)
        target.append(row)
new=data['archive_new5090']
for r in new['metrics']:
    f=r.get('experiment_id',r.get('experiment',''))
    value=num(r.get('paired_geomean_speedup',r.get('geomean_paired_speedup',r.get('off_over_on_gm'))))
    if value is None:
        value=next((num(v) for k,v in r.items() if ('speedup' in k or 'ratio' in k) and num(v) is not None),None)
    metric=next((k for k,v in r.items() if ('speedup' in k or 'ratio' in k) and num(v) is not None),'paired_geomean_speedup')
    condition=r.get('input_type',r.get('comparison',r.get('role','')))
    status='固定B8192/32B；无CI、无sanitizer；四组件范围'
    control=r.get('off_label',r.get('numerator','OFF/对照'))
    candidate=r.get('on_label',r.get('denominator','ON/候选'))
    if r.get('evidence')=='NEW_IDENTICAL_BUILD_DRIFT_CONTROL':
        condition='相同二进制漂移对照'
        status='NEW_IDENTICAL_BUILD_DRIFT_CONTROL；并未关闭该单元优化；无CI、无sanitizer'
        control='OFF标签（相同构建）';candidate='ON标签（相同构建）'
    if r.get('evidence')=='REUSED_QUALIFIED_PAIR':
        condition='已核验配对结果复用'
        status='REUSED_QUALIFIED_PAIR；复用此前消融，不新增进程或计时'
    if f=='wphc_m65_sign':control='W1';candidate='W3'
    ablation.append([f or r.get('cell_id','matrix'), 'RTX 5090',num(r.get('parameter')),r.get('operation',''),num(r.get('batch',8192)),text(condition),metric,value,'x',control,candidate,num(r.get('paired_blocks',6)),'配对进程区组',status,None,None]+source_fields(new['archive'],r))
newtables=json.loads((BASE/'archive_new5090/tables.json').read_text('utf-8'))
nt=next(t for t in newtables if t['name']=='new5090_unique_process_records')
for rr in nt['rows']:
    r=dict(zip(nt['header'],rr)) if isinstance(rr,list) else rr
    correct.append([new['archive'],r.get('experiment_id',''),num(r.get('parameter')),r.get('operation',''),num(r.get('batch')),r.get('job',''),'最终输出、退出状态及计时核对',r.get('correctness','PASS'),None,None,'固定输入；仅最终输出检查；非标准KAT；无sanitizer；'+text(r.get('record_role'))]+source_fields(new['archive'],r))
if 'archive_supplement' in data:
    supplement=data['archive_supplement']
    definitions={
        'valid':'全有效',
        'invalid':'全无效z',
        'grouped50':'分组50%无效z；i%256<128',
        'dispersed50':'分散50%无效z；(73*i)%256<128；非旧奇偶交替',
    }
    supplement_rows=[]
    for r in supplement['metrics']:
        condition=definitions[r['pattern']]
        detail=(f"独立补测；ON/OFF复用各自旧构建；不替换旧结果；固定输入；"
                f"ON={r['on_mean_ms']:.12g}ms；OFF={r['off_mean_ms']:.12g}ms；"
                f"观测配对范围={r['min_pair_ratio']:.12g}–{r['max_pair_ratio']:.12g}，非CI；无新KAT/sanitizer")
        ablation.append([r['experiment_id'],'RTX 5090',65,'verify',8192,condition,
            'paired_geomean_speedup',r['paired_geomean_speedup'],'x','CTA OFF','CTA ON',
            r['paired_blocks'],'配对进程区组；每进程15次',detail,None,None]+source_fields(supplement['archive'],r))
        supplement_rows.append([r['pattern'],condition,65,'verify',8192,32,
            r['on_mean_ms'],r['off_mean_ms'],r['paired_geomean_speedup'],
            r['min_pair_ratio'],r['max_pair_ratio'],6,15,detail]+source_fields(supplement['archive'],r))
    supplement_cols=['输入分布','定义','参数集','操作','批量','消息字节','CTA_ON均值_ms',
        'CTA_OFF均值_ms','配对OFF_ON几何比_x','观测最小比_x','观测最大比_x',
        '配对区组数','每进程计时次数','说明','来源ID','源行号','JSON定位']
    with (OUT/'补测四分布明细.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(supplement_cols);writer.writerows(supplement_rows)
    for r in supplement['correctness']:
        note='资格验证' if r['record_role']=='qualification' else '性能进程最终输出检查'
        correct.append([supplement['archive'],r['experiment_id'],65,'verify',r['batch'],
            r['case'],r['check'],r['status'],r['errors'],r['rejected_rows'],
            note+'；仅核对最终输出；复用CPU有效语料oracle；无新标准KAT/sanitizer']+
            source_fields(supplement['archive'],r))
for r in data['archive_5090']['experiments']:
    f=r.get('experiment','')
    if 'SANITIZER' in f.upper() or 'sanitizer' in text(r.get('source','')).lower():
        if 'split32' in (f+' '+text(r.get('source',''))).lower():
            correct.append([data['archive_5090']['archive'],f,None,'split32',None,'停止阶段汇总','racecheck',r.get('status','STOPPED'),None,None,'103 warnings；停止后8项未运行；性能结果不解除该问题']+source_fields(data['archive_5090']['archive'],r))
if 'archive_4090_patch' in data:
    patch=data['archive_4090_patch']
    for r in patch.get('metrics',[]):
        row=canonical_metric(r,patch['archive'],'RTX 4090')
        row[12]=r.get('repeat_unit','原记录检查项；不作为主性能样本')
        aux.append(row)
    for r in patch.get('correctness',[]):
        note=text(r.get('notes',r.get('note','')))
        if r.get('warnings') is not None and r.get('record_role')=='tool_process':
            note=f"工具警告数={r['warnings']}；"+note
        context='；'.join(f'{k}={r[k]}' for k in ['backend','policy','tool','returncode','displayed_hazards'] if k in r)
        if context:note=context+'；'+note
        if r.get('record_role'):note=text(r['record_role'])+'；'+note
        correct.append([patch['archive'],r.get('experiment_id',r.get('experiment','')),
            num(r.get('parameter')),r.get('operation',''),num(r.get('batch')),
            r.get('case',''),r.get('check',''),r.get('status',''),num(r.get('errors')),
            num(r.get('rejected_rows')),note]+source_fields(patch['archive'],r))
experiments=[]
expcols=['来源包','实验系列','状态','参数或批量','计数与覆盖','边界说明','来源ID','源行号','JSON定位']
for key,d in data.items():
    if key=='archive_old':
        oldex=[
            {'experiment':'历史R02配对','status':'FORMAL_PAIRED_COMPLETE','counts':{'cells':27,'blocks':162,'processes':324,'raw_samples':4860},'notes':'27格在4090包内重复再导出，仅算一次','source':next(r['source'] for r in d['metrics'])},
            {'experiment':'历史机制','status':'SOURCE_REPORTED','counts':{'HSS':6,'PFODR':8,'SIGN_UNIFY':4},'notes':'部分仅汇总证据，不能归为新主线消融'},
            {'experiment':'截图复测','status':'PASS_REPORTED_BY_RUNNER','counts':{'correctness_cases':9,'large_keygen_cases':9},'notes':'完整服务器日志未收到'}]
    else:oldex=d.get('experiments',[])
    for r in oldex:
        f=r.get('experiment',r.get('family',r.get('experiment_id','')))
        ctx={k:v for k,v in r.items() if k not in ['status','source','source_line','line','sha256','extracted_path','family','experiment','experiment_id','notes','limits','limitations','scope','case'] and (isinstance(v,(int,float,dict,list)) or k in ['started_utc','completed_utc','run_id'])}
        notes=r.get('notes',r.get('limitations',r.get('limits',r.get('scope',''))))
        experiments.append([d['archive'],f,r.get('status',''),text(r.get('batch',r.get('parameters',''))),text(ctx),text(notes)]+source_fields(d['archive'],r))
quality=[];env=[]
for key,d in data.items():
    for r in d.get('quality',[]):
        quality.append([d['archive'],r.get('family',r.get('experiment','')),r.get('issue',r.get('status','限制')),r.get('severity',''),text(r.get('detail',r.get('limitation',r.get('effect',r.get('evidence','')))))]+source_fields(d['archive'],r))
    for r in d.get('failures',[]):
        quality.append([d['archive'],r.get('type',''),r.get('status',''),'已恢复、非算法失败',text(r.get('detail',''))]+source_fields(d['archive'],r))
    en=d.get('environment',[])
    if isinstance(en,dict):
        for k,v in en.items():
            if k in ['source','source_line','toolchain_provenance','source_compilation_sha256']:continue
            env.append([d['archive'],en.get('gpu',''),k,'未记录' if v is None else text(v),'',src(d['archive'],en.get('source','')),1])
    else:
        for r in en:
            if 'field' in r:
                env.append([d['archive'],r.get('gpu',''),r['field'],'未记录' if r.get('value') is None else r.get('value'),r.get('unit',''),src(d['archive'],r.get('source','')),r.get('line',1)])
            elif key=='archive_4090' and r.get('extracted_path'):
                p=Path(r['extracted_path'])
                if p.exists():
                    lines=p.read_text('utf-8',errors='replace').splitlines()
                    selected=[l.strip() for l in lines if re.search(r'Model name|CPU\(s\)|Socket|Mem:|NVIDIA|580\.|release|V12|version',l)]
                    env.append([d['archive'],'RTX 4090',p.stem,'；'.join(selected[:12]),'',src(d['archive'],r.get('source','')),r.get('source_line',1)])
quality.insert(0,['全部','跨系列比较','不可混算','关键','不同GPU、代码版本、计时范围、输入集、重复层级、对照实现分开统计；不计算跨包总加速比。','','',''])
quality.insert(1,['全部','历史R02去重','同源历史','关键','旧包与4090 historical 的27格指标完全一致；3张关键表字节一致，仅GPU UUID匿名化不同。27格/324进程/4860样本只计一次。','','',''])
quality.insert(2,['全部','统计定义','单位与层级','关键','加速比>1表示分母候选更快；配对比值的几何均值不等于汇总耗时之比。min/max为观测范围，不能代称CI。批量时间/批量为摊销时间，不是单请求延迟。','','',''])
for d in data.values():
    for source_record in d.get('sources',[]):
        if isinstance(source_record,dict):
            src(d['archive'],source_record.get('source',''),source_record.get('sha256',''))
for r in cat['catalog']:
    # A derived CSV's hash belongs to the CSV, not its source JSON/log file.
    original_sha=r['SHA256'] if r['是否派生表']=='否' else ''
    r['来源ID']=src(r['来源包'],r['表格路径'],original_sha)
verified_source_map=BASE/'original_source_sha_map_new5090_supplement.json'
if verified_source_map.exists():
    hashes=json.loads(verified_source_map.read_text('utf-8'))
    for registered in source_registry.values():
        original=registered['包内路径']
        if original in hashes:registered['SHA256']=hashes[original]
patch_evidence=BASE/'archive_4090_patch/evidence_index.csv'
if 'archive_4090_patch' in data and patch_evidence.exists():
    with patch_evidence.open(encoding='utf-8-sig',newline='') as f:
        hashes={r['原始来源']:r['实际SHA256'] for r in csv.DictReader(f)}
    for registered in source_registry.values():
        if registered['包内路径'] in hashes:registered['SHA256']=hashes[registered['包内路径']]
catalogcols=['来源ID']+[c for c in cat['catalog'][0] if c!='来源ID']
catalogrows=[[r.get(c) for c in catalogcols] for r in cat['catalog']]
sourcecols=['来源ID','来源包','包内路径','SHA256']
all_sources=[[r[c] for c in sourcecols] for r in source_registry.values()]
overview_groups=[]
for name in dict.fromkeys(r[0] for r in main):
    rows=[r for r in main if r[0]==name]
    overview_groups.append(dict(name=name,cells=len(rows),gm=statistics.geometric_mean(r[9] for r in rows),min=min(r[9] for r in rows),max=max(r[9] for r in rows),above_one=sum(r[9]>1 for r in rows),start=main.index(rows[0])+5,end=main.index(rows[-1])+5))
sheets=[
    dict(name='主性能',title='ML-DSA 主性能分轮次汇总',note='加速比为配对比值的几何均值。旧R02提供描述性CI；新固定输入实验未提供CI，留空。各系列单独使用。',columns=maincols,rows=main),
    dict(name='消融对照',title='组件、机制、九宫格与补测对照',note='按分子/分母和条件解释。补测四分布单独追加；旧六格同二进制条件为漂移对照；TC两臂均开启。',columns=metriccols,rows=ablation),
    dict(name='算子微基准',title='SHAKE、NTT与split32独立算子',note='独立算子harness结果，不等同于完整KeyGen、Sign或Verify加速。输出单位与统计口径保留原字段。',columns=metriccols,rows=micro),
    dict(name='辅助诊断',title='主机API、legacy基线、阶段与资源诊断',note='包含插桩、内存、热点及重试指标。legacy Dilithium与ML-DSA不作直接加速比较；诊断计时不纳入主性能。',columns=metriccols,rows=aux),
    dict(name='正确性记录',title='正确性、sanitizer与截图记录',note='PASS按原证据保留；本次未重跑GPU。区分历史、截图、插桩工具和版本资格，不把未覆盖项计为通过。',columns=correctcols,rows=correct),
    dict(name='实验目录',title='按实验家族组织的测试覆盖',note='一行是一个结果系列或执行阶段，可能包含旧版本、续跑与修订，不可直接相加为独立实验总数。',columns=expcols,rows=experiments),
    dict(name='问题与边界',title='数据问题与结果使用边界',note='保留失败、未运行、替换关系和原验收限制；原始英文限制保持来源用词。',columns=['来源包','实验系列','问题或状态','重要程度','具体说明','来源ID','源行号','JSON定位'],rows=quality),
    dict(name='环境',title='实测环境与缺失项',note='nvidia-smi显示的CUDA支持版本与实际nvcc编译器版本分别解释。缺失信息不从另一轮测试自动继承。',columns=['来源包','GPU','字段','值','单位','来源ID','源行号'],rows=env),
    dict(name='来源索引',title='每项结论对应的归档位置',note='来源ID用于连接结果表。! 或 !/ 表示外层ZIP内嵌套包；源行号与JSON定位共同用于核查。',columns=sourcecols,rows=all_sources),
    dict(name='数据表索引',title='全部已采集结构化表及重复副本',note=f"包含正式测试、历史数据、元数据、遥测、QA夹具和{cat['summary']['derived_table_paths']}张派生表；数据行数不是独立样本数。",columns=catalogcols,rows=catalogrows)
]
result=dict(summary=cat['summary'],groups=overview_groups,sheets=sheets,all_findings={d['archive']:d.get('findings',[]) for d in data.values()})
if 'archive_4090_patch' in data:
    result['patch_overview']='4090修补：独立测试程序9项工具检查通过；历史性能9个模块与当前资格均不同，原性能结果不自动继承新资格。'
    result['patch_verification']='4090修补：保留修补前147,462条racecheck告警；故障恢复9项通过但仍为部分覆盖，非零残留字段保留。'
(OUT/'workbook_data.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
for sheet in sheets:
    if sheet['name'] in ['主性能','消融对照','实验目录','问题与边界']:
        with (OUT/(sheet['name']+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(sheet['columns']);w.writerows(sheet['rows'])
print(json.dumps(dict(groups=overview_groups,sheets=[(s['name'],len(s['rows'])) for s in sheets]),ensure_ascii=False,indent=2))
