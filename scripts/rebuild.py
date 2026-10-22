"""Rebuild published CSV views and navigation using only shipped inputs (Python 3.10+)."""
from pathlib import Path
import argparse, collections, csv, hashlib, io, json, math, os, shutil, statistics, subprocess, sys
sys.dont_write_bytecode = True
from record_taxonomy import enrich_workbook, build_navigation as taxonomy_navigation
WRITTEN=set()

NAMES={'主性能':'main-performance','消融对照':'ablation-comparisons','算子微基准':'operator-microbenchmarks','辅助诊断':'auxiliary-diagnostics','正确性记录':'correctness-records','实验目录':'experiment-catalog','问题与边界':'limitations','环境':'environments','来源索引':'source-index','数据表索引':'table-index'}
ROUNDS={
 '新建文件夹(1).zip':('rtx-4090','historical-r02','历史 R02、机制与截图记录'),
 'MLDSA_4090_Experiments.zip':('rtx-4090','20261018-19','4090 主实验与复测（10/18—10/19 批次，含历史回溯）'),
 '4090修补.zip':('rtx-4090','20261020-repair','4090 修补资格与故障恢复补充'),
 '5090实验结果_20261019.zip':('rtx-5090','20261019','5090 首批归档（包名标记 20261019，含后续运行）'),
 '新5090.zip':('rtx-5090','20261020-components','5090 组件消融与矩阵补充'),
 '补测.zip':('rtx-5090','20261020-verify-supplement','5090 Verify 四分布补测'),
}

def dump(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
 WRITTEN.add(path)

def csv_bytes(columns,rows):
 s=io.StringIO(newline='');w=csv.writer(s);w.writerow(columns);w.writerows(rows)
 return ('\ufeff'+s.getvalue()).encode('utf-8')

def write_parts(root,relative,columns,rows,limit=450000):
 # Deterministic shards, each containing whole CSV records and the same header.
 groups=[];group=[];size=len(csv_bytes(columns,[]))
 for row in rows:
  b=len(csv_bytes([], [row]))-len(csv_bytes([],[]))
  if group and size+b>=limit:groups.append(group);group=[];size=len(csv_bytes(columns,[]))
  group.append(row);size+=b
 if group or not groups:groups.append(group)
 entries=[]
 for i,g in enumerate(groups,1):
  p=Path(relative)
  target=p.with_name(p.stem+(f'-{i:02d}' if len(groups)>1 else '')+'.csv')
  raw=csv_bytes(columns,g);dest=root/target;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
  WRITTEN.add(dest)
  entries.append({'path':target.as_posix(),'rows':len(g),'columns':len(columns),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
 return entries

def rel_link(from_file,target):return Path(os.path.relpath(target,from_file.parent)).as_posix()

def write_md(path,text):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(text.rstrip()+'\n',encoding='utf-8',newline='\n')
 WRITTEN.add(path)

def statistics_match(expected_path,rebuilt_path):
 # Platform math libraries can differ in the last bits of a calculated geometric mean.
 # Every other key and every stored measurement must still agree exactly.
 expected=json.loads(expected_path.read_text('utf-8'))
 rebuilt=json.loads(rebuilt_path.read_text('utf-8'))
 if len(expected['main_series'])!=len(rebuilt['main_series']):return False
 for left,right in zip(expected['main_series'],rebuilt['main_series']):
  if not math.isclose(left['gm'],right['gm'],rel_tol=1e-14,abs_tol=1e-15):return False
  right['gm']=left['gm']
 return expected==rebuilt

def add_source_locations(model,repo):
 catalog=json.loads((repo/'data/derived/records/catalog.json').read_text('utf-8'))['catalog']
 by_source={(r['来源包'],r['表格路径']):r for r in catalog}
 by_hash={r['SHA256']:r['数据包文件'] for r in catalog}
 # Original evidence hashes can resolve non-table source IDs without relying on local paths.
 with (repo/'data/metadata/legacy-evidence-map.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):by_hash.setdefault(r['SHA256'],r['仓库文件'])
 sheet=next(s for s in model['sheets'] if s['name']=='来源索引')
 cols=sheet['columns'];new=[]
 for row in sheet['rows']:
  r=dict(zip(cols,row));t=by_source.get((r['来源包'],r['包内路径']))
  location=by_hash.get(r['SHA256'],'') if r['SHA256'] else ''
  if not location and t and (not r['SHA256'] or r['SHA256']==t['SHA256']):location=t['数据包文件']
  role='派生表' if location.startswith('data/derived/tables/') else '随包提供' if location else '仅保留来源定位'
  new.append(row+[location,role])
 sheet['columns']=cols+['仓库文件','材料保留状态'];sheet['rows']=new

def build_navigation(model,out,repo,views):
 sources={r[0]:dict(zip(s['columns'],r)) for s in model['sheets'] if s['name']=='来源索引' for r in s['rows']}
 exp=next(s for s in model['sheets'] if s['name']=='实验目录')
 items=[];global_lines=['# 实验导航','','按设备、数据轮次与结果系列浏览。系列和检查记录不是独立样本数。','']
 for gpu in ['rtx-4090','rtx-5090']:
  global_lines.append(f'- [{gpu.upper()}]({gpu}/README.md)')
  gpu_lines=[f'# {gpu.upper()}','','不同轮次、对照与版本资格分别保留。','']
  for archive,(platform,round_id,label) in ROUNDS.items():
   if platform!=gpu:continue
   group=Path('experiments')/gpu/round_id;group_file=out/group/'README.md'
   gpu_lines.append(f'- [{label}]({round_id}/README.md)')
   lines=[f'# {label}','',f'来源包：`{archive}`。此目录为结果导航和筛选视图，原始表只存一份。','','## 分类结果','']
   for sheet in model['sheets']:
    if sheet['name'] in ('来源索引','数据表索引','实验目录'):continue
    cols=sheet['columns'];subset=[]
    for row in sheet['rows']:
     r=dict(zip(cols,row));source=sources.get(r.get('来源ID',''),{})
     if r.get('来源包',source.get('来源包'))==archive:subset.append(row)
    if not subset:continue
    parts=write_parts(out,group/(NAMES[sheet['name']]+'.csv'),cols,subset)
    for p in parts:lines.append(f"- [{sheet['name']}（{p['rows']} 条记录）]({Path(p['path']).name})")
   lines+=['','## 结果系列','']
   for index,row in enumerate(exp['rows'],1):
    r=dict(zip(exp['columns'],row))
    if r['来源包']!=archive:continue
    eid=f'E{index:03d}';page=group/eid/'README.md'
    lines.append(f"- [{eid} · {r['实验系列']}]({eid}/README.md)")
    body=[f"# {eid} · {r['实验系列']}",'',f"设备：{gpu.upper()}。来源轮次：{label}。",'',f"状态：`{r['状态']}`",'',f"覆盖：{r['计数与覆盖']}",'',f"边界：{r['边界说明'] or '参见原记录及对应结果表。'}",'','## 来源','']
    ids=set([r.get('来源ID','')]);more=r.get('相关来源ID集合','')
    if isinstance(more,list):ids.update(more)
    else:
     import re
     ids.update(re.findall(r'S\d{4,}',str(more)))
    ids.discard('')
    for sid in sorted(ids):
     source=sources[sid];file=source.get('仓库文件','')
     if file:body.append(f"- [{sid} 原始定位对应材料]({rel_link(out/page,out/file)})：`{source['包内路径']}`")
     else:body.append(f"- {sid}：`{source['包内路径']}`。本分享包仅保留来源定位。")
    body+=['',f'[返回本轮分类结果]({rel_link(out/page,group_file)})']
    write_md(out/page,'\n'.join(body))
    items.append({'experiment_id':eid,'gpu':gpu,'round':round_id,'archive':archive,'series':r['实验系列'],'page':page.as_posix(),'source_ids':sorted(ids),'status':r['状态']})
   write_md(group_file,'\n'.join(lines))
  write_md(out/'experiments'/gpu/'README.md','\n'.join(gpu_lines))
 write_md(out/'experiments/README.md','\n'.join(global_lines))
 dump(out/'data/metadata/experiments.json',items)
 return items

def main():
 WRITTEN.clear()
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
 p.add_argument('--output',type=Path,default=Path('build'))
 p.add_argument('--check',action='store_true',help='Compare rebuilt products with published files.')
 a=p.parse_args();repo=a.repo.resolve();out=a.output.resolve()
 if out==repo or repo.is_relative_to(out):raise ValueError('Choose a separate output folder, not the repository or its parent.')
 if out.is_relative_to(repo) and not out.is_relative_to(repo/'build'):
  raise ValueError('Inside the repository, output must stay under build/ to protect published files.')
 out.mkdir(parents=True,exist_ok=True)
 stage=out/'_intermediate'
 result=subprocess.run([sys.executable,str(repo/'scripts/consolidate.py'),'--repo',str(repo),'--output',str(stage)],capture_output=True,text=True,encoding='utf-8')
 if result.returncode:raise RuntimeError(result.stderr or result.stdout)
 model=json.loads((stage/'workbook_data.json').read_text('utf-8'))
 model=enrich_workbook(model)
 # Keep classification visible without putting long rule descriptions before the results.
 for sheet in model['sheets']:
  if sheet['name']=='正确性记录':
   lead=['记录层级','来源包','实验系列','参数集或mode','操作','批量','用例','工具或检查项','状态']
  elif sheet['name']=='数据表索引':
   lead=['来源ID','来源包','数据层级','是否派生表','有无表头','列宽模式','字段数','最小字段数','最大字段数','数据行数','类别','表格路径']
  else:continue
  cols=lead+[c for c in sheet['columns'] if c not in lead]
  indices=[sheet['columns'].index(c) for c in cols]
  sheet['rows']=[[r[i] for i in indices] for r in sheet['rows']];sheet['columns']=cols
 add_source_locations(model,repo)
 # Shared model is a build intermediate. CSVs remain the public machine-readable interface.
 dump(out/'workbook_data.json',model)
 entries=[];views={};toc=['# 分类结果视图','','CSV 与 Excel 使用相同记录和字段。大表按完整行分片；空值与零保持区分。','']
 for s in model['sheets']:
  parts=write_parts(out,Path('results/views')/(NAMES[s['name']]+'.csv'),s['columns'],s['rows'])
  entries+=parts;views[s['name']]=parts
  toc += [f"## {s['name']}",'',s['note'],'']
  toc += [f"- [{Path(r['path']).name}]({Path(r['path']).name})（{r['rows']} 条记录）" for r in parts]
  toc += ['']
 supplement=list(csv.reader((stage/'补测四分布明细.csv').open(encoding='utf-8-sig',newline='')))
 entries+=write_parts(out,Path('results/views/supplement-summary.csv'),supplement[0],supplement[1:])
 toc+=['## 补测四分布明细','','[完整数值](supplement-summary.csv)。观测范围不是置信区间。']
 write_md(out/'results/views/README.md','\n'.join(toc))
 dump(out/'data/metadata/view-manifest.json',entries)
 source=next(s for s in model['sheets'] if s['name']=='来源索引')
 dest=out/'data/metadata/source-index.csv';dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(csv_bytes(source['columns'],source['rows']))
 WRITTEN.add(dest)
 table=next(s for s in model['sheets'] if s['name']=='数据表索引')
 (out/'data/metadata/table-index.csv').write_bytes(csv_bytes(table['columns'],table['rows']))
 WRITTEN.add(out/'data/metadata/table-index.csv')
 dump(out/'results/statistics.json',{'main_series':model['groups'],'table_summary':model['summary'],'note':'分系列配对几何均值；表路径数与行数不是独立样本数。'})
 notes=['ML-DSA 实验结果与证据边界','2026-10-21 v4；仅分类、来源和复核组织调整，原测量与状态保持。','',
        '不同GPU、输入分布、计时范围及历史轮次分别解释；原始表在data/raw，派生表和归一记录在data/derived。',
        '主性能为27+27+9条；正确性1722条包含多个记录层级，不等于1722次独立实验。','']
 for group in model['groups']:
  notes.append(f"{group['name']}：{group['cells']}条件格，分系列几何平均倍率 {group['gm']:.12g}。")
 for archive,findings in model['all_findings'].items():
  notes+=['',archive]
  notes.extend(str(v) if not isinstance(v,(dict,list)) else json.dumps(v,ensure_ascii=False) for v in findings)
 (out/'results/RESULT_NOTES.zh-CN.txt').write_text('\n'.join(notes)+'\n',encoding='utf-8',newline='\n')
 WRITTEN.add(out/'results/RESULT_NOTES.zh-CN.txt')
 navigation=build_navigation(model,out,repo,views)
 semantic=taxonomy_navigation(model)
 pages={x['experiment_id']:x['page'] for x in navigation}
 for entry in semantic:
  entry['classification_group']=entry.pop('directory')
  entry['page']=pages[f"E{entry['catalog_record_index']:03d}"]
  entry['directory']=Path(entry['page']).parent.as_posix()
 dump(out/'data/metadata/experiment-view-links.json',semantic)
 dump(out/'data/metadata/record-taxonomy.json',model['record_taxonomy'])
 dump(out/'data/metadata/source-corrections.json',model['source_corrections'])
 # Record every generated public product, excluding intermediates and this manifest itself.
 generated=sorted(f.relative_to(out).as_posix() for f in WRITTEN if f.name not in ('workbook_data.json','rebuild-report.json'))
 generated=[n for n in generated if not n.startswith('checks/')]
 checks=[];numeric_tolerance_files=[]
 if a.check:
  for name in generated:
   expected=repo/name
   if not expected.is_file():raise ValueError('Published file missing: '+name)
   if expected.read_bytes()!=(out/name).read_bytes():
    if name=='results/statistics.json' and statistics_match(expected,out/name):numeric_tolerance_files.append(name)
    else:raise ValueError('Rebuild differs from published file: '+name)
   checks.append(name)
 report={'status':'PASS','check_published':a.check,'generated_files':len(generated),'compared_files':len(checks),'byte_equal_files':len(checks)-len(numeric_tolerance_files),'numeric_tolerance_files':numeric_tolerance_files,'experiments':len(navigation),'csv_view_parts':len(entries),'requires_gpu':False,'requires_network':False}
 dump(out/'rebuild-report.json',report)
 print(json.dumps(report,ensure_ascii=True))

if __name__=='__main__':main()
