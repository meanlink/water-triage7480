import {session} from '../stores/session.js';
export async function api(path,options={}){
 const r=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...(session.token?{Authorization:'Bearer '+session.token}:{}),...options.headers}});
 if(!r.ok){let d=await r.json().catch(()=>({detail:'连接失败，请稍后重试'}));if(r.status===401&&path!='/auth/login'){session.clear();location.hash='#/login';}throw new Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));}
 return r.json();
}
export async function download(id,format){
 const r=await fetch('/api/deliveries/'+id+'/download?format='+format,{headers:{Authorization:'Bearer '+session.token}});
 if(!r.ok)throw new Error('下载失败，请重试');
 const u=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=u;a.download='分析归档-'+id+'.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
}
export async function downloadJobDetail(id,side=''){
 const code=side==='训练'?'train':side==='验证'?'valid':'';
 const suffix=code?'-'+code:'';
 const r=await fetch('/api/jobs/'+id+'/detail.csv'+(side?('?side='+encodeURIComponent(side)):''),{headers:{Authorization:'Bearer '+session.token}});
 if(!r.ok){const d=await r.json().catch(()=>({detail:'下载失败，请重试'}));throw new Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));}
 const u=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=u;a.download='job-'+id+'-segment-detail'+suffix+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
}
