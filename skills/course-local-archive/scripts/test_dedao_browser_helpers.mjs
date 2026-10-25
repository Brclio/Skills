#!/usr/bin/env node
// Entirely offline VM fixtures: no browser account, network or real tokens.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
const directory=path.dirname(fileURLToPath(import.meta.url));
const scratch=await fs.mkdtemp(path.join(os.tmpdir(),'course-archive-browser-mock-'));
const files=['export_dedao_in_page.js','export_dedao_media_in_page.js','export_dedao_private_tokens_in_page.js','capture_dedao_read_session.js'];
const scripts=Object.fromEntries(await Promise.all(files.map(async name=>[name,await fs.readFile(path.join(directory,name),'utf8')])));
const fixtures={
 alpha:{enid:'fixture-course-alpha',name:'Alpha course',chapters:[['a',['101','102']],['b',['103']]],extra:'fixture-extra-alpha'},
 beta:{enid:'fixture-course-beta',name:'Beta course',chapters:[['c',['201','202']]],extra:'fixture-extra-beta'}
};
await fs.writeFile(path.join(scratch,'fixtures.json'),JSON.stringify(fixtures));
const lessons=new Map();
for(const course of Object.values(fixtures)) for(const [chapter,ids] of course.chapters) for(const [index,id] of ids.entries()) lessons.set(id,{id,course,chapter,index,video:id==='101'||id==='103'||id==='201',extra:id!=='102'&&id!=='202'});
const clone=value=>JSON.parse(JSON.stringify(value));
function body(id){const l=lessons.get(id);const text=`${l.course.name} original prose ${id}`;return {article:{id,token:'FIXTURE-ARTICLE-SECRET'},content:JSON.stringify([{type:'paragraph',text,contents:[{type:'text',text:{content:text,bold:true}}]},{type:'audio',aliasId:`main-${id}`,title:'main',duration:60},...(l.extra ? [{type:'audio',aliasId:l.course.extra,title:'extra',duration:30}] : [])])};}
function info(id){const l=lessons.get(id);return {class_enid:l.course.enid,dd_article_token:`FIXTURE-BODY-${id}`,article_info:{id_str:id,enid:id,class_enid:l.course.enid,title:`Lesson ${id}`,audio:{alias_id:`main-${id}`,mp3_play_url:`https://fixture.invalid/audio/${id}.m3u8`,token:'FIXTURE-AUDIO-SECRET',token_version:1},video_status:l.video?1:0,video:l.video?[{dd_media_id_str:`media-${id}`,token:`FIXTURE-PRIVATE-${id}`,token_version:1,is_drm:true}]:[],media_base_info:l.video?[{media_type:2,source_id:`media-${id}`,security_token:`FIXTURE-SECURITY-${id}`}]:[]},csrf_token:'FIXTURE-CSRF-EXPORTED-NEVER',authorization:'FIXTURE-AUTH-NEVER'};}
function environment({course=fixtures.alpha,article=null,options={},failure={}}={}){
 let elapsed=0;let timer=0;const calls=[],downloads=[],blobs=new Map();
 class Clock extends Date{constructor(...args){super(...(args.length?args:[1700000000000+elapsed]));}static now(){return 1700000000000+elapsed;}}
 class LocalURL extends URL{static createObjectURL(blob){const key=`blob:fixture-${blobs.size}`;blobs.set(key,blob);return key;}static revokeObjectURL(key){blobs.delete(key);}}
 const cookie='csrfToken=FIXTURE-CSRF; account_session=FIXTURE-COOKIE-NEVER';
 const document={cookie,body:{appendChild(){}},createElement(){return {href:'',download:'',click(){downloads.push({filename:this.download,blob:blobs.get(this.href)});},remove(){}};}};
 function route(url,method,payload,transport){
  const u=new URL(url,'https://www.dedao.cn');assert.equal(u.origin,'https://www.dedao.cn');calls.push({path:u.pathname,method,payload:clone(payload),at:Clock.now(),transport});
  if(u.pathname==='/pc/bauhinia/pc/class/info'){
   const c=Object.values(fixtures).find(c=>c.enid===payload.detail_id);assert.ok(c);
   return {status:200,data:{h:{c:0},c:{class_info:{enid:c.enid,name:c.name,current_article_count:c.chapters.flatMap(x=>x[1]).length+(failure.catalogCountMismatch?1:0),token:'FIXTURE-CLASS-TOKEN-NEVER'},chapter_list:c.chapters.map(([id,ids])=>({id_str:id,name:`Section ${id}`,phase_num:ids.length})),session_id:'FIXTURE-SESSION-NEVER'}}};
  }
  if(u.pathname==='/pc/bauhinia/pc/class/free_article_list'){
   const c=Object.values(fixtures).find(c=>c.enid===payload.detail_id);const ids=c.chapters.find(x=>x[0]===payload.chapter_id)[1];
   const after=String(payload.max_id)==='0'?0:ids.indexOf(String(payload.max_id))+1;
   const index=failure.paginationCycle&&after>0?0:after;
   const slice=ids.slice(index,index+1);
   return {status:200,data:{h:{c:0},c:{article_list:slice.map(id=>({id_str:id,enid:id,title:`Lesson ${id}`,class_enid:c.enid,order_num:ids.indexOf(id),dd_article_token:'FIXTURE-CATALOG-TOKEN-NEVER'})),...(failure.noMoreFlags?{}:{has_more:failure.paginationCycle&&after>0?true:index+slice.length<ids.length})}}};
  }
  if(u.pathname==='/pc/bauhinia/pc/article/info'){
   const id=String(payload.detail_id);assert.ok(lessons.has(id));
   if(failure.deniedLesson===id)return {status:failure.deniedStatus||403,data:{h:{c:1,e:'not exported token=FIXTURE-PRIVATE-ERROR'}}};
   if(failure.challengeLesson===id)return {status:200,html:'<html>challenge</html>'};
   return {status:200,data:{h:{c:0},c:info(id)}};
  }
  if(u.pathname==='/pc/ddarticle/v1/article/get/v2'){
   const id=u.searchParams.get('token').replace('FIXTURE-BODY-','');
   return {status:200,data:{h:{c:0},c:failure.emptyBody===id?{article:{id},content:'[]'}:body(id)}};
  }
  if(u.pathname==='/media_gate/gate/api/v1/web'){
   const id=payload.media_id_str.replace('media-','');assert.equal(payload.security_token,`FIXTURE-SECURITY-${id}`);
   if(failure.deniedGate)return {status:401,data:{h:{c:1}}};
   return {status:200,data:{h:{c:0},c:{drm_token:'FIXTURE-DRM-NEVER',tracks:[{duration:60,formats:[480,720].map(resolution=>({type:'video',format:'m3u8',resolution,url:`https://fixture.invalid/video/${id}/${resolution}.m3u8`,drm_token:'FIXTURE-FORMAT-DRM-NEVER'}))}]}}};
  }
  if(u.pathname==='/pc/bauhinia/v1/audio/mutiget_by_alias')return {status:200,data:{h:{c:0},c:{list:[{alias_id:failure.wrongAlias?'wrong-alias':payload.ids,title:'source extra audio',duration:30,mp3_play_url:`https://fixture.invalid/${payload.ids}.mp3`,token:'FIXTURE-EXTRA-SECRET',token_version:1}]}}};
  throw new Error('Unexpected fixture endpoint '+u.pathname);
 }
 class XHR{
  constructor(){this.headers=[];this.withCredentials=false;}
  open(method,url){this.method=method;this.url=url;}
  setRequestHeader(name,value){this.headers.push([name,value]);}
  send(value){const result=route(this.url,this.method,value?JSON.parse(value):null,'xhr');this.status=result.status;this.responseText=result.html||JSON.stringify(result.data);queueMicrotask(()=>this.onload?.());}
 }
 const ctx=vm.createContext({URL:LocalURL,Blob,Date:Clock,AbortController,XMLHttpRequest:XHR,location:{origin:'https://www.dedao.cn',href:`https://www.dedao.cn/course/${article?'article':'detail'}?id=${article||course.enid}`},document,console:{log(){throw new Error('Helpers must not log fixture secrets');}},setTimeout(fn,ms=0){const id=++timer;if(ms<=1000 || failure.timeout&&ms<=60000)queueMicrotask(()=>{elapsed+=ms;fn();});return id;},clearTimeout(){},fetch:async(url,settings)=>{assert.equal(settings.credentials,'same-origin');assert.equal(settings.mode,'same-origin');assert.equal(settings.redirect,'error');assert.equal(settings.headers['Xi-Csrf-Token'],'FIXTURE-CSRF');const result=route(url,settings.method,settings.body?JSON.parse(settings.body):null,'fetch');if(failure.timeout)return await new Promise(()=>{});return {status:result.status,ok:result.status>=200&&result.status<300,json:async()=>{if(result.html)throw new Error('challenge');return clone(result.data);}};}});
 ctx.window=ctx;ctx.__courseArchiveOptions=options;
 return {ctx,calls,downloads,XHR,run:name=>vm.runInContext(scripts[name],ctx,{timeout:5000}),async json(index=downloads.length-1){return JSON.parse(await downloads[index].blob.text());},checkGaps(){for(let i=1;i<calls.length;i++)assert.ok(calls[i].at-calls[i-1].at>=350,`Request gap ${calls[i].at-calls[i-1].at}ms`);}};
}
const normalFiles=['export_dedao_in_page.js','export_dedao_media_in_page.js'];
function noSecrets(value){const text=JSON.stringify(value);for(const secret of ['FIXTURE-PRIVATE-','FIXTURE-SECURITY-','FIXTURE-CLASS-TOKEN','FIXTURE-CATALOG-TOKEN','FIXTURE-BODY-','FIXTURE-ARTICLE-SECRET','FIXTURE-AUDIO-SECRET','FIXTURE-EXTRA-SECRET','FIXTURE-DRM-NEVER','FIXTURE-FORMAT-DRM','FIXTURE-COOKIE','FIXTURE-CSRF','FIXTURE-AUTH','FIXTURE-SESSION'])assert.ok(!text.includes(secret),`Secret leaked: ${secret}`);}
let tests=0;
try{
 const alpha=environment({options:{requestGapMs:1}});const complete=await alpha.run(files[0]);const source=await alpha.json();assert.equal(complete.complete,true);assert.equal(source.lessons.length,3);assert.equal(source.course.enid,fixtures.alpha.enid);assert.equal(source.lessons[0].info.article_info.video[0].token_version,1);assert.equal(source.lessons[0].body.content,body('101').content);assert.ok(alpha.calls.some(c=>c.payload?.max_id==='101'));noSecrets(source);alpha.checkGaps();tests++;
 const beta=environment({article:'201'});await beta.run(files[0]);const b=await beta.json();assert.equal(b.course.enid,fixtures.beta.enid);assert.equal(b.lessons.length,2);noSecrets(b);beta.checkGaps();tests++;
 const override=environment({article:'201',options:{courseId:fixtures.alpha.enid}});await override.run(files[0]);assert.equal((await override.json()).course.enid,fixtures.alpha.enid);tests++;
 for(const status of [401,403,429]){const e=environment({failure:{deniedLesson:'102',deniedStatus:status}});await e.run(files[0]);const x=await e.json();assert.equal(x.complete,false);assert.equal(x.lessons.length,1);assert.equal(x.summary.stopped,true);assert.equal(x.errors[0].http_status,status);assert.ok(!e.calls.some(c=>c.path.endsWith('/article/info')&&c.payload.detail_id==='103'));noSecrets(x);tests++;}
 for(const failure of [{challengeLesson:'101'},{emptyBody:'101'},{paginationCycle:true}]){const e=environment({failure});await e.run(files[0]);const x=await e.json();assert.equal(x.complete,false);assert.equal(x.summary.imported_bodies,0);assert.equal(x.errors.length,1);noSecrets(x);tests++;}
 const noFlags=environment({failure:{noMoreFlags:true}});await noFlags.run(files[0]);assert.equal((await noFlags.json()).complete,true);assert.equal((await noFlags.json()).lessons.length,3);noFlags.checkGaps();tests++;
 const badCount=environment({failure:{catalogCountMismatch:true}});await badCount.run(files[0]);const countPartial=await badCount.json();assert.equal(countPartial.complete,false);assert.equal(countPartial.lessons.length,0);assert.equal(countPartial.course.current_article_count,4);assert.equal(countPartial.catalog.length,3);tests++;
 const timedOut=environment({failure:{timeout:true}});await timedOut.run(files[0]);const timeoutPartial=await timedOut.json();assert.equal(timeoutPartial.complete,false);assert.match(timeoutPartial.errors[0].message,/timed out/);assert.equal(timedOut.calls.length,1);tests++;
 const media=environment();media.ctx.__courseArchiveExport=source;const mstatus=await media.run(files[1]);assert.equal(mstatus.complete,true);assert.equal(media.downloads.length,2);const web=await media.json(0),extras=await media.json(1);assert.equal(web.videos.length,2);assert.equal(extras.audios.length,1);assert.deepEqual(extras.audios[0].lesson_ids,['101','103']);assert.equal(extras.audios[0].alias_id,fixtures.alpha.extra);assert.equal(extras.audios[0].audio.alias_id,fixtures.alpha.extra);assert.equal(extras.audios[0].lesson_id,'');assert.ok(media.calls.every(c=>!c.path.endsWith('/article/get/v2')));noSecrets(web);noSecrets(extras);media.checkGaps();tests++;
 for(const failure of [{wrongAlias:true},{deniedGate:true}]){const e=environment({failure});e.ctx.__courseArchiveExport=source;await e.run(files[1]);for(let i=0;i<2;i++){const x=await e.json(i);assert.equal(x.complete,false);assert.equal(x.errors.length,1);noSecrets(x);}tests++;}
 const betaMedia=environment({article:'201'});betaMedia.ctx.__courseArchiveExport=b;await betaMedia.run(files[1]);assert.equal((await betaMedia.json(0)).videos.length,1);assert.equal((await betaMedia.json(1)).audios[0].alias_id,fixtures.beta.extra);noSecrets(await betaMedia.json(0));noSecrets(await betaMedia.json(1));betaMedia.checkGaps();tests++;
 const missingMode=environment();await assert.rejects(missingMode.run(files[2]),/private_tokens/);assert.equal(missingMode.calls.length,0);assert.equal(missingMode.downloads.length,0);tests++;
 const privateEnv=environment({options:{mode:'private_tokens'}});const privateStatus=await privateEnv.run(files[2]);const secrets=await privateEnv.json();assert.equal(secrets.complete,true);assert.equal(secrets.videos.length,2);assert.deepEqual(Object.keys(secrets.videos[0]).sort(),['lesson_id','token']);assert.equal(secrets.videos[0].token,'FIXTURE-PRIVATE-101');assert.ok(!JSON.stringify(privateStatus).includes('FIXTURE-PRIVATE'));assert.ok(!JSON.stringify(secrets).includes('FIXTURE-COOKIE'));assert.ok(!JSON.stringify(secrets).includes('FIXTURE-SECURITY'));privateEnv.checkGaps();tests++;
 const betaPrivate=environment({course:fixtures.beta,options:{mode:'private_tokens'}});await betaPrivate.run(files[2]);assert.equal((await betaPrivate.json()).videos.length,1);assert.equal((await betaPrivate.json()).videos[0].lesson_id,'201');tests++;
 const partialPrivate=environment({options:{mode:'private_tokens'},failure:{deniedLesson:'103'}});await partialPrivate.run(files[2]);const p=await partialPrivate.json();assert.equal(p.complete,false);assert.equal(p.videos.length,1);tests++;
 const captured=environment();const originalOpen=captured.XHR.prototype.open;const installed=captured.run(files[3]);assert.equal(installed.captured,false);const genuine=new captured.XHR();genuine.open('POST','/pc/bauhinia/pc/article/info');genuine.withCredentials=true;genuine.setRequestHeader('Content-Type','application/json');genuine.setRequestHeader('Xi-Gat','FIXTURE-GENUINE-HEADER-NEVER');genuine.send(JSON.stringify({detail_id:'101',source:'normal-ui'}));assert.equal(captured.ctx.__courseArchiveCapture.status.captured,true);assert.equal(captured.XHR.prototype.open,originalOpen);assert.ok(!JSON.stringify(captured.ctx.__courseArchiveReadSession.inspect()).includes('FIXTURE-GENUINE'));captured.ctx.document.cookie='';await captured.run(files[0]);const fromFacade=await captured.json();assert.equal(fromFacade.complete,true);noSecrets(fromFacade);assert.ok(captured.calls.every(c=>c.transport==='xhr'));captured.checkGaps();await assert.rejects(captured.ctx.__courseArchiveReadSession.read('/account/delete'),/Unsupported/);captured.ctx.__courseArchiveReadSession.clear();assert.equal(captured.ctx.__courseArchiveReadSession,undefined);tests++;
 const deniedFacade=environment({failure:{deniedLesson:'102'}});deniedFacade.run(files[3]);const originalRequest=new deniedFacade.XHR();originalRequest.open('POST','/pc/bauhinia/pc/article/info');originalRequest.setRequestHeader('Xi-Gat','FIXTURE-GENUINE-HEADER-NEVER');originalRequest.send(JSON.stringify({detail_id:'101'}));await assert.rejects(deniedFacade.ctx.__courseArchiveReadSession.read('/pc/bauhinia/pc/article/info',{payload:{detail_id:'102'}}),/rejected/);const networkCount=deniedFacade.calls.length;await assert.rejects(deniedFacade.ctx.__courseArchiveReadSession.read('/pc/bauhinia/pc/article/info',{payload:{detail_id:'103'}}),/halted/);assert.equal(deniedFacade.calls.length,networkCount);deniedFacade.ctx.__courseArchiveReadSession.clear();tests++;
 console.log(JSON.stringify({status:'passed',offline_scenarios:tests,helpers:files,live_network_requests:0,fixture_directory_removed:true}));
}finally{await fs.rm(scratch,{recursive:true,force:true});}
