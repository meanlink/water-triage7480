import {jobs} from '../api/entities.js';
import {downloadJobDetail} from '../api/client.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {chart} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
function metricCards(metrics){
 return '<div class="metrics">'+metrics.map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'<small>'+esc(m.unit||'')+'</small></strong></div>').join('')+'</div>';
}
function splitPanel(r){
 const s=r.split;if(!s)return '';
 const cc=s.class_counts||{};
 const card=(zh,key,segKey,recKey)=>'<div class="split-card"><h3>'+zh+'侧</h3><dl><dt>管段数</dt><dd>'+esc(s[segKey])+' 段</dd><dt>记录数</dt><dd>'+esc(s[recKey])+' 条</dd><dt>漏点样本</dt><dd>'+esc((cc[key]||{}).leak??'—')+' 条</dd><dt>非漏点样本</dt><dd>'+esc((cc[key]||{}).normal??'—')+' 条</dd></dl></div>';
 return '<section class="panel split-panel"><div class="section-title"><h2>管段隔离划分</h2><span>'+esc(s.version||'')+'</span></div>'
  +'<p class="split-rule">'+esc(s.rule||'')+'</p>'
  +'<div class="split-grid">'+card('训练','train','train_segments','train_records')+card('验证','valid','valid_segments','valid_records')+'</div>'
  +'<div class="split-badges"><span class="badge ok">同一管段复测整体同侧，不跨训练/验证</span><span class="badge">归属仅取决于管段编号，调换导入顺序不变</span><span class="badge">调整树参数不改变归属</span>'+(s.duplicate_segment_records?'<span class="badge note">含 '+esc(s.duplicate_segment_records)+' 条同管段复测记录</span>':'')+'</div></section>';
}
function bothSideMetrics(r){
 const groups=r.metric_groups;if(!groups?.length)return '';
 return '<section class="panel"><div class="section-title"><h2>两侧指标对照（两类样本均可评估）</h2><span>指标来源侧逐行见下方明细</span></div>'
  +groups.map(g=>'<div class="side-metric"><div class="side-head"><strong>'+esc(g.side)+'侧</strong><span>'+esc(g.sample_records)+' 条记录 · 漏点 '+esc(g.class_counts.leak)+' / 非漏点 '+esc(g.class_counts.normal)+'</span></div>'+metricCards(g.metrics)+'</div>').join('')
  +'<p class="hint">验证侧指标反映对未参与训练管段的泛化表现；训练侧与验证侧差距过大提示过拟合。</p></section>';
}
function detailSection(j,r){
 const cols=r.table?.columns||[],allRows=r.table?.rows||[];
 const isV2=!!r.split;
 const buttons='<div class="detail-actions"><button class="button small" data-csv="'+j.id+'" data-side="">下载全部明细 CSV ↓</button>'
  +(isV2?'<button class="button small" data-csv="'+j.id+'" data-side="训练">仅训练侧 ↓</button><button class="button small" data-csv="'+j.id+'" data-side="验证">仅验证侧 ↓</button>':'')+'</div>';
 if(!isV2){
  return '<section class="panel"><div class="section-title"><h2>结果明细</h2><span>'+allRows.length+' 行 · 历史试验</span></div>'
   +'<p class="warning legacy-note">该试验创建于管段隔离口径升级前，按旧分层留出口径计算，无管段归属与哈希桶列；历史指标与明细保持原样可查。新试验将按管段编号固定归属并补充两侧指标。</p>'
   +buttons+table(cols,allRows)+'</section>';
 }
 const sideFilter='<div class="side-filter" data-job="'+j.id+'"><button class="button small primary" data-filter="全部">全部 '+allRows.length+'</button><button class="button small" data-filter="训练">训练 '+allRows.filter(x=>x.split_side==='训练').length+'</button><button class="button small" data-filter="验证">验证 '+allRows.filter(x=>x.split_side==='验证').length+'</button></div>';
 return '<section class="panel"><div class="section-title"><h2>管段分诊明细与归属核对</h2><span>'+allRows.length+' 行（训练+验证全覆盖）</span></div>'
  +'<p class="hint">「划分归属」标明该记录所在侧，「哈希桶」为管段编号 SHA-256 取模结果（桶号 &lt; '+esc(r.split.threshold)+' 进验证侧）；可按管段编号在下载 CSV 中复核归属与指标来源。</p>'
  +buttons+sideFilter+'<div id="detail-table">'+table(cols,allRows)+'</div></section>';
}
export async function results(id){
 workspace.jobs=await jobs.list();const j=id?await jobs.get(id):(workspace.jobs.find(j=>j.id===workspace.selectedJob)||workspace.jobs[0]);
 if(j&&!workspace.jobs.some(x=>x.id===j.id))workspace.jobs.push(j);
 if(!j)return heading('04 / REVIEW','结果复核','尚无分析结果。')+'<div class="empty">先到分析工作台，选择批次并提交一次计算。<a href="#/workbench">前往工作台 ↗</a></div>';
 workspace.selectedJob=j.id;const r=j.result||{};
 return heading('04 / REVIEW','结果复核与业务解释',j.name,'<button class="button" id="refresh-results">刷新结果 ↻</button>')
  +'<div class="result-selector"><label>分析记录<select id="select-job">'+workspace.jobs.map(x=>'<option value="'+x.id+'" '+(x.id===j.id?'selected':'')+'>'+esc(x.name)+' · '+esc(x.status)+(x.result?.schema_version===2?' · 管段隔离':x.status==='completed'?' · 旧口径':'')+'</option>').join('')+'</select></label>'+status(j.status)+'<span>'+date(j.created_at)+'</span><span class="approval">'+(j.approved?'已获业务批准':'待负责人复核')+'</span></div>'
  +(j.status==='completed'
   ?'<section class="result-lead"><p class="eyebrow">COMPUTED FINDING</p><h2>'+esc(r.summary)+'</h2>'+metricCards(r.metrics||[])+'</section>'
    +splitPanel(r)
    +(r.metric_groups?bothSideMetrics(r):'')
    +'<section class="panel">'+chart(r.chart)+'</section>'
    +'<div class="two-columns"><section class="panel"><div class="section-title"><h2>业务解释</h2><span>由计算结果生成</span></div><ol class="questions">'+(r.findings||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ol>'+(r.warnings||[]).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+'</section><section class="method-sheet compact"><p class="eyebrow">REPRODUCIBILITY</p><h3>计算口径与参数</h3><p>'+esc(r.method)+'</p><pre>'+esc(JSON.stringify(j.params,null,2))+'</pre>'+(session.user.role==='admin'&&!j.approved?'<button class="primary" id="approve-job">批准此业务结论</button>':'')+'<p class="hint">仅批准结果可进入定时分发档案。</p></section></div>'
    +detailSection(j,r)
   :'<section class="panel empty">'+(j.status==='failed'?'计算失败：'+esc(j.error)+'。请返回工作台调整参数或数据。':'后台正在执行计算。点击刷新结果查看最新进展。')+'<a href="#/workbench">返回工作台 ↗</a></section>');
}
export function bindResults(refresh){
 document.querySelector('#refresh-results')?.addEventListener('click',refresh);
 document.querySelector('#select-job')?.addEventListener('change',e=>{workspace.selectedJob=Number(e.target.value);location.hash='#/results/'+e.target.value;});
 document.querySelector('#approve-job')?.addEventListener('click',async()=>{try{await jobs.approve(workspace.selectedJob);notify('已批准，可创建分发计划');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelectorAll('[data-csv]').forEach(b=>b.addEventListener('click',async()=>{try{await downloadJobDetail(Number(b.dataset.csv),b.dataset.side);notify('明细 CSV 已下载，可按管段编号核对归属');}catch(e){notify(e.message,true);}}));
 const filterBox=document.querySelector('.side-filter');
 if(filterBox){
  const jobId=Number(filterBox.dataset.job);
  filterBox.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',async()=>{
   const job=workspace.jobs.find(x=>x.id===jobId)||await jobs.get(jobId);
   const all=job.result?.table?.rows||[],cols=job.result?.table?.columns||[];
   const f=b.dataset.filter,rows=f==='全部'?all:all.filter(x=>x.split_side===f);
   filterBox.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('primary',x===b));
   document.querySelector('#detail-table').innerHTML=table(cols,rows);
  }));
 }
}
