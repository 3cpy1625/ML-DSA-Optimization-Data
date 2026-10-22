import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';

const input=path.resolve(process.argv[2]??'build/workbook_data.json');
const output=path.resolve(process.argv[3]??'build/summary.xlsx');
const directory=path.resolve(process.argv[4]??path.dirname(output));
await fs.mkdir(path.dirname(output),{recursive:true});
await fs.mkdir(directory,{recursive:true});
const config={date:'2026-10-21',revision:'v4'};
const d=JSON.parse(await fs.readFile(input,'utf8'));
const wb=Workbook.create();
const FONT='Microsoft YaHei';
const C={ink:'#243247',muted:'#596779',head:'#253E5E',soft:'#EAF0F6',line:'#CED7E0',warn:'#FFF1D6'};
const clean=x=>{
  if(x===undefined || x===null)return null;
  if(typeof x==='object')return JSON.stringify(x);
  if(typeof x==='string' && x.startsWith('='))return "'"+x;
  return x;
};
const col=n=>{let s='';while(n){n--;s=String.fromCharCode(65+n%26)+s;n=Math.floor(n/26);}return s;};
const intro=wb.worksheets.add('概览');
for(const s of d.sheets)wb.worksheets.add(s.name);
for(let idx=0;idx<d.sheets.length;idx++){
  const s=d.sheets[idx], sh=wb.worksheets.getItem(s.name);
  const N=s.columns.length, R=s.rows.length+4;
  sh.showGridLines=false;
  sh.getRange(`A1:${col(N)}${R}`).format.font={name:FONT,size:10,color:C.ink};
  sh.getRange(`A1:${col(N)}${R}`).format.rowHeight=21;
  sh.getRange(`A1:${col(N)}${R}`).format.verticalAlignment='center';
  sh.getRange(`A1:${col(N)}${R}`).format.columnWidth=15;
  sh.getRange('A2').values=[[s.title]];
  sh.getRange('A2').format.font={name:FONT,size:15,bold:true,color:C.ink};
  sh.getRange('A2').format.rowHeight=29;
  sh.getRange('A3').values=[[s.note]];
  sh.getRange('A3').format.font={name:FONT,size:10,color:C.muted};
  sh.getRange('A3').format.rowHeight=25;
  sh.getRangeByIndexes(3,0,1,N).values=[s.columns];
  for(let start=0;start<s.rows.length;start+=1000){
    const block=s.rows.slice(start,start+1000).map(row=>Array.from({length:N},(_,j)=>clean(row[j])));
    sh.getRangeByIndexes(start+4,0,block.length,N).values=block;
  }
  sh.getRange(`A4:${col(N)}4`).format={fill:C.head,font:{name:FONT,size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:38,horizontalAlignment:'center',verticalAlignment:'center'};
  const table=sh.tables.add(`A4:${col(N)}${R}`,true,`ExperimentTable${idx+1}`);
  table.showFilterButton=true;
  sh.freezePanes.freezeRows(4);
  for(let j=0;j<N;j++){
    const title=s.columns[j], range=sh.getRange(`${col(j+1)}5:${col(j+1)}${R}`);
    const width=/包内路径|表格路径|仓库文件|数据包文件/.test(title)?105:/SHA256/.test(title)?68:/来源包/.test(title)?29:/备注|说明|状态|用途|范围|比值方向|归约方法|系列|条件|指标原名|覆盖|分类依据|计数单位|数据轮次/.test(title)?32:14;
    sh.getRange(`${col(j+1)}1:${col(j+1)}${R}`).format.columnWidth=width;
    if(/_ms|_x|^值$|CI95/.test(title)){range.setNumberFormat('0.000000');range.format.horizontalAlignment='right';}
    else if(/数$|批量|参数|字节|行号|重复数/.test(title)){range.setNumberFormat('#,##0');range.format.horizontalAlignment='right';}
  }
  const wrapCols=[];
  for(let j=0;j<N;j++){
    const title=s.columns[j];
    if(/条件或后端|状态或用途|数据状态|具体说明|计数与覆盖|边界说明|包内路径|表格路径|备注|重复单位|^用例$|工具或检查项|^状态$|分类依据|计数单位|来源关联说明|表头判定依据|原始字段|字段来源/.test(title)){
      const width=/路径/.test(title)?115:/说明|覆盖|分类依据|原始字段/.test(title)?85:/重复单位|^状态$/.test(title)?32:/^用例$/.test(title)?40:/工具或检查项/.test(title)?34:60;
      sh.getRange(`${col(j+1)}1:${col(j+1)}${R}`).format.columnWidth=width;
      sh.getRange(`${col(j+1)}5:${col(j+1)}${R}`).format.wrapText=true;
      wrapCols.push([j,width]);
    }
    if(s.name==='环境' && title==='值'){
      sh.getRange(`${col(j+1)}1:${col(j+1)}${R}`).format.columnWidth=100;
      sh.getRange(`${col(j+1)}5:${col(j+1)}${R}`).format.wrapText=true;
      wrapCols.push([j,100]);
    }
    const navigationWidths={'原始运行标识':58,'运行标识依据':62,'相关来源ID集合':42,'类别':34,'材料保留状态':28};
    if(Object.hasOwn(navigationWidths,title)){
      const width=navigationWidths[title];
      sh.getRange(`${col(j+1)}1:${col(j+1)}${R}`).format.columnWidth=width;
      sh.getRange(`${col(j+1)}5:${col(j+1)}${R}`).format.wrapText=true;
      wrapCols.push([j,width]);
    }
  }
  if(wrapCols.length)for(let r=0;r<s.rows.length;r++){
    let lines=1;
    for(const [j,width] of wrapCols){
      const value=String(clean(s.rows[r][j])??'');
      const length=[...value].reduce((n,c)=>n+(c.charCodeAt(0)>255?1.8:1),0);
      lines=Math.max(lines,Math.ceil(length/(width-3)));
    }
    if(lines>1)sh.getRange(`A${r+5}:${col(N)}${r+5}`).format.rowHeight=lines*15+8;
  }
  if(s.name==='主性能'){
    sh.tabColor=C.head;
    sh.getRange(`J5:J${R}`).conditionalFormats.add('cellIs',{operator:'lessThan',formula:1,format:{fill:'#FCE7E5',font:{color:'#9B2922',bold:true}}});
  }
  if(s.name==='消融对照')sh.tabColor='#52728E';
  if(s.name==='问题与边界')sh.tabColor='#BC8C38';
  console.log(JSON.stringify({sheet:s.name,rows:s.rows.length,columns:N}));
}
intro.showGridLines=false;
intro.tabColor=C.head;
intro.getRange('A1:H49').format.font={name:FONT,size:10,color:C.ink};
intro.getRange('A1:H49').format.rowHeight=24;
intro.getRange('A1:H49').format.verticalAlignment='center';
const widths=[31,16,18,18,18,18,20,55];
widths.forEach((w,j)=>intro.getRange(`${col(j+1)}1:${col(j+1)}49`).format.columnWidth=w);
intro.getRange('A2').values=[['ML-DSA 项目实验数据汇总']];
intro.getRange('A2').format.font={name:FONT,size:16,bold:true,color:C.ink};
intro.getRange('A2').format.rowHeight=32;
intro.getRange('A3').values=[[`整理日期 ${config.date} ${config.revision}；覆盖${d.summary.archives.length}个压缩包，原始与派生分层、记录层级明确。按平台和轮次分别统计。`]];
intro.getRange('A3').format.font={name:FONT,size:10,color:C.muted};
intro.getRange('A5:H5').values=[['结果系列','条件格数','几何平均加速_x','最小加速_x','最大加速_x','点估计 >1 的格数','基准','使用范围']];
intro.getRange('A5:H5').format={fill:C.head,font:{name:FONT,size:10,bold:true,color:'#FFFFFF'},rowHeight:38,wrapText:true,horizontalAlignment:'center'};
d.groups.forEach((g,i)=>{
  const row=6+i;
  intro.getRange(`A${row}:H${row}`).values=[[g.name,g.cells,null,g.min,g.max,g.above_one,'cuPQC 0.4.1',i===0?'历史原样本；描述性95%CI':i===1?'仅替换3格；固定配置；无推断CI':'固定B8192；探索性；sanitizer未运行']];
  intro.getRange(`C${row}`).formulas=[[`=GEOMEAN('主性能'!J${g.start}:J${g.end})`]];
});
intro.getRange('C6:E8').setNumberFormat('0.0000"x"');
intro.getRange('A6:H8').format.rowHeight=33;
intro.getRange('H6:H8').format.wrapText=true;
intro.getRange('A10').values=[['加速比 = 对照耗时 / 本项目耗时；>1 表示本项目更快。不同系列不合并计算总加速比。']];
intro.getRange('A11').values=[['“点估计 >1”只描述数值方向，不代表统计显著。批量摊销耗时不等于单请求延迟。']];
intro.getRange('A10:H11').format.font={name:FONT,size:10,color:C.muted};
intro.getRange('A13').values=[['需要保留的关键结论']];
intro.getRange('A13').format.font={name:FONT,size:12,bold:true};
const bullets=[
  ['4090 修订','27格仅替换 M65 Sign B8192/B16384、M87 Sign B4096；原记录保留，不拼接旧样本。'],
  ['5090 未领先项','M44 Sign 0.9906×、M87 Sign 0.4201×；均在B8192、32字节、固定cuPQC配置下。'],
  ['最新组件消融','M44 KeyGen联合1.5063×、M65 Sign 1.3635×；仅关闭指定组件，TC两臂均启用。'],
  ['Verify 输入差异','新5090 M65 Verify全有效0.9961×、全无效z 3.3604×；6个矩阵格为同二进制漂移对照。'],
  ['正确性版本边界','原M65 Sign与split32有racecheck警告；候选通过不能赋予另一版本完整资格。'],
  ['同源历史去重','两个包中的R02历史27格为同一批数据；324进程、4860条原始计时只计一次。'],
];
bullets.forEach((r,i)=>{intro.getRange(`A${14+i}:B${14+i}`).values=[r];intro.getRange(`A${14+i}`).format.font={name:FONT,size:10,bold:true};});
intro.getRange('A20').values=[['补测 Verify：全有效0.995898×、全无效3.362735×、分组50%无效1.347508×、分散50%无效0.997195×；单独追加，不替换旧结果。']];
intro.getRange('A20').format.font={name:FONT,size:10,bold:true,color:C.ink};
intro.getRange('A21').values=[[d.patch_overview??'4090修补：补充版本资格、异常恢复和二进制身份核验；原63格性能数值保留。']];
intro.getRange('A21').format.font={name:FONT,size:10,bold:true,color:C.ink};
intro.getRange('A23').values=[['结构化数据清点']];
intro.getRange('A23').format.font={name:FONT,size:12,bold:true};
intro.getRange('A25:D25').values=[['来源包','原始/派生表路径数','同包唯一字节表','压缩包大小_GB']];
intro.getRange('A25:D25').format={fill:C.head,font:{name:FONT,size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:38};
d.summary.archives.forEach((r,i)=>intro.getRange(`A${26+i}:D${26+i}`).values=[[r['来源包'],r['表格路径数'],r['同包唯一表格数'],r['压缩字节数']/1e9]]);
intro.getRange('D26:D31').setNumberFormat('0.000');
intro.getRange('A33:B36').values=[
  ['原始 CSV/TSV 路径',d.summary.original_table_paths],
  ['从JSON/日志整理的派生表',d.summary.derived_table_paths],
  ['跨包按原字节去重表',d.summary.unique_table_bytes],
  ['相同内容的额外路径',d.summary.repeated_table_paths],
];
intro.getRange('A38').values=[['表路径包含正式结果、历史再导出、遥测、索引和QA夹具；表行数不能当作独立样本总数。']];
intro.getRange('A39').values=[['全部表的来源、角色和哈希见“数据表索引”；原表位于 data/raw，派生表位于 data/derived；仓库提供实验导航。']];
intro.getRange('A41').values=[['独立核对与修订边界']];
intro.getRange('A41').format.font={name:FONT,size:12,bold:true};
intro.getRange('A42').values=[['旧4090：4860条计时、27格点估计和100000次bootstrap CI复算一致。']];
intro.getRange('A43').values=[['新4090：4860+540条计时重算30格一致；5090 E03：1620条计时及9格配对加速比一致。']];
intro.getRange('A44').values=[['新5090：141进程、1530条性能计时+15条资格计时及18项对照统计核对一致。']];
intro.getRange('A45').values=[['补测：585个清单文件哈希、56进程、720条性能+8条资格计时、24对统计和四格汇总核对一致。']];
intro.getRange('A46').values=[[d.patch_verification??'4090修补的独立测试程序资格与历史生产二进制分开记录；不自动追认旧性能的版本资格。']];
intro.getRange('A48').values=[['这是离线整理和统计核对；未执行项目代码、GPU实验或重新运行sanitizer。']];
intro.getRange('A48').format.font={name:FONT,size:10,color:C.muted};
wb.recalculate();
const overview=await wb.inspect({kind:'table',range:'概览!A5:H8',include:'values,formulas',tableMaxRows:5,tableMaxCols:8,maxChars:4500});
console.log(overview.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50},maxChars:2000});
console.log(errors.ndjson);
await fs.writeFile(path.join(directory,'workbook-inspect.json'),JSON.stringify({overview,errors},null,2));
const xlsx=await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(output);
console.log('EXPORTED');
const previews=[
 ['概览','A1:H48','summary-preview.png'],
 ['正确性记录','A1:I10','correctness-preview.png'],
 ['正确性记录','A1325:I1329','patch-hierarchy-preview.png'],
 ['实验目录','A1:K10','catalog-preview.png'],
 ['来源索引','A1:F8','sources-preview.png'],
 ['数据表索引','A1:K10','table-schema-preview.png'],
 ['数据表索引','A1987:K1990','schema-repair-preview.png'],
];
for(const [sheetName,range,name] of previews){
 const preview=await wb.render({sheetName,range,scale:1,format:'png'});
 await fs.writeFile(path.join(directory,name),new Uint8Array(await preview.arrayBuffer()));
}
console.log('RENDERED');
