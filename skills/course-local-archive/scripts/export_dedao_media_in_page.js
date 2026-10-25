/* Export all returned Web video formats and exact additional embedded audio.
 * Run after export_dedao_in_page.js when possible. Always refreshes authorized
 * article info; security_token is used only inside the page and never exported.
 * Writes two JSON files; place them at raw/authorized-web-media.json and
 * raw/authorized-extra-audio.json in the selected course folder.
 */
(async()=>{
  "use strict";
  if (location.origin !== "https://www.dedao.cn") throw new Error("Use the already authorized https://www.dedao.cn page");
  const options = window.__courseArchiveOptions || {};
  const state = {phase:"initializing", complete:false, stopped:false, requests:0, catalog_lessons:0, imported_bodies:0, scanned_lessons:0, videos:0, extra_audio:0, errors:0};
  const gap = Math.max(350, Number(options.requestGapMs) || 350);
  const timeoutMs = Math.max(1000, Math.min(60000, Number(options.timeoutMs) || 20000));
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const error = (message, http_status = null, api_code = null) => Object.assign(new Error(message), {http_status, api_code});
  const publicError = caught => ({message:String(caught.message || "Read failed").replace(/https?:\/\/[^\s]+/g,"[URL omitted]").slice(0,240), http_status:caught.http_status || null, api_code:caught.api_code ?? null});
  const secretName = key => {
    const normalized = key.replace(/([a-z])([A-Z])/g,"$1_$2").toLowerCase().replace(/[^a-z0-9]+/g,"_");
    if (["token_version","drm_version","has_play_auth"].includes(normalized)) return false;
    if (["tk","gat","xi_gat","sid","isid","jwt"].includes(normalized)) return true;
    return /(?:^|_)(?:token|key|secret|authorization|cookie|csrf|password|credential|session)(?:_|$)/.test(normalized) || normalized === "play_auth" || normalized === "play_auth_id";
  };
  const clean = value => Array.isArray(value) ? value.map(clean) : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).filter(([key])=>!secretName(key)).map(([key,child])=>[key,clean(child)])) : value;
  const allowed = new Map([
    ["/pc/bauhinia/pc/class/info","POST"], ["/pc/bauhinia/pc/class/free_article_list","POST"],
    ["/pc/bauhinia/pc/article/info","POST"], ["/pc/ddarticle/v1/article/get/v2","GET"],
    ["/pc/bauhinia/v1/audio/mutiget_by_alias","POST"], ["/media_gate/gate/api/v1/web","POST"]
  ]);
  async function read(path, payload = null, query = null) {
    if (state.stop_requested) throw error("Stopped by request");
    if (!allowed.has(path)) throw error("Unsupported read endpoint");
    const previous = Number(window.__courseArchiveLastRequestAt) || 0;
    await pause(Math.max(0,gap-(Date.now()-previous)));
    if (state.stop_requested) throw error("Stopped by request");
    window.__courseArchiveLastRequestAt = Date.now(); state.requests++;
    const controller = new AbortController(); let timer;
    try {
      const operation = (async()=>{
        const facade = window.__courseArchiveReadSession || window.__dedaoReadSession;
        if (facade?.read) return await facade.read(path,{payload,query});
        const cookie = document.cookie.split(";").map(x=>x.trim()).find(x=>x.startsWith("csrfToken="));
        if (!cookie) throw error("Authorized page has no CSRF token; capture a genuine read session");
        const url = new URL(path,location.origin);
        if (query) for (const [key,value] of Object.entries(query)) url.searchParams.set(key,String(value));
        const response = await fetch(url.href,{method:allowed.get(path),credentials:"same-origin",mode:"same-origin",redirect:"error",signal:controller.signal,headers:{"Content-Type":"application/json","Xi-DT":"web","Xi-Csrf-Token":cookie.slice(10)},...(payload ? {body:JSON.stringify(payload)} : {})});
        if (!response.ok) throw error("HTTP read rejected",response.status);
        let data; try { data = await response.json(); } catch { throw error("Non-JSON response or challenge",response.status); }
        return {http_status:response.status,data};
      })();
      const result = await Promise.race([operation,new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(error("Read timed out"));},timeoutMs);})]);
      if (!result || result.http_status < 200 || result.http_status >= 300) throw error("HTTP read rejected",result?.http_status);
      if (!result.data?.h || Number(result.data.h.c) !== 0) throw error("API read rejected or challenge",result.http_status,result.data?.h?.c);
      return result.data.c;
    } finally { clearTimeout(timer); }
  }
  function save(value, filename) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:"application/json;charset=utf-8"}));
    const anchor = document.createElement("a");anchor.href=url;anchor.download=filename;document.body.appendChild(anchor);anchor.click();anchor.remove();
    setTimeout(()=>URL.revokeObjectURL(url),60000);
    return filename;
  }
  const safeId = id => String(id).replace(/[^A-Za-z0-9_-]/g,"_");
  const infoCache = new Map();
  let catalogProgress = null;
  async function courseId() {
    if (options.courseId) return String(options.courseId);
    const url = new URL(location.href);
    const id = url.searchParams.get("id");
    if (!id) throw error("Provide window.__courseArchiveOptions.courseId");
    if (url.pathname === "/course/detail") return id;
    if (url.pathname === "/course/article") {
      const info = await read("/pc/bauhinia/pc/article/info",{detail_id:id});infoCache.set(id,info);
      const resolved = info.class_enid || info.article_info?.class_enid || info.class_info?.enid;
      if (resolved) return String(resolved);
    }
    throw error("Could not resolve the course from this page");
  }
  async function articleInfo(enid) {
    if (infoCache.has(enid)) {const value=infoCache.get(enid);infoCache.delete(enid);return value;}
    return await read("/pc/bauhinia/pc/article/info",{detail_id:enid});
  }
  function moreFlag(value) {
    for (const key of ["has_more","has_more_article_list","has_next","has_more_flat_article_list"]) if (key in value) return Boolean(value[key]);
    return null;
  }
  async function catalog(id) {
    state.phase="catalog";
    const metadata=await read("/pc/bauhinia/pc/class/info",{detail_id:id,is_login:1});
    const course=metadata?.class_info;
    const expected=Number(course?.current_article_count);
    if (!course?.enid || !Number.isInteger(expected) || expected<0) throw error("Source course count or identity is unavailable");
    if (String(course.enid)!==String(id)) throw error("Source course identity differs from the requested course");
    state.expected_lesson_count=expected;
    catalogProgress={course:clean(course),metadata:clean(metadata),sections:[],lessons:[]};
    const chapters=Array.isArray(metadata.chapter_list) && metadata.chapter_list.length ? metadata.chapter_list : [{id_str:"0",name:course.name || "课程",intro:""}];
    const sections=[];const ids=new Map();const enids=new Map();
    function accept(section, rows) {
      let added=0;
      for (const row of rows) {
        const lessonId=String(row.id_str ?? row.id ?? "");const enid=String(row.enid || "");
        if (!lessonId || !enid) throw error("Catalog lesson identity is missing");
        if (row.class_enid && String(row.class_enid)!==String(course.enid)) throw error("Catalog contains a different course");
        if (ids.has(lessonId)) {
          const before=ids.get(lessonId);
          if (before.enid!==enid || before.title!==row.title || before.section_id!==section.id) throw error("Conflicting duplicate catalog identity");
          continue;
        }
        if (enids.has(enid)) throw error("Catalog has duplicate article enids");
        const item={id:lessonId,enid,title:String(row.title || ""),section_id:section.id,section:section.name,catalog:row};
        section.rows.push(item);ids.set(lessonId,item);enids.set(enid,item);added++;catalogProgress.lessons.push(clean(item));state.catalog_lessons=ids.size;
      }
      if (ids.size>expected) throw error("Catalog exceeds the source course count");
      return added;
    }
    async function page(section, first) {
      const result=await read("/pc/bauhinia/pc/class/free_article_list",{detail_id:id,chapter_id:section.id,count:first ? 0 : Math.max(1,Math.min(500,Number(options.pageSize)||100)),max_id:section.max_id,max_order_num:section.max_order_num});
      if (!Array.isArray(result?.article_list)) throw error("Catalog page is not an article list");
      section.pages++;
      const rows=result.article_list;const added=accept(section,rows);const more=moreFlag(result);
      const last=rows[rows.length-1];
      const nextId=String(result.next_max_id ?? result.max_id ?? last?.id_str ?? last?.id ?? section.max_id);
      const nextOrder=result.next_max_order_num ?? result.max_order_num ?? last?.order_num ?? section.max_order_num;
      const changed=nextId!==String(section.max_id) || String(nextOrder)!==String(section.max_order_num);
      if (!first && more===true && (!added || !changed)) throw error("Catalog pagination did not advance");
      section.max_id=nextId;section.max_order_num=nextOrder;section.more=more;
      section.exhausted=more===false || rows.length===0 || (!first && !added && more!==true);
      if (section.pages>10000) throw error("Catalog exceeded the pagination bound");
    }
    for (const chapter of chapters) {
      const section={id:String(chapter.id_str ?? chapter.id),name:String(chapter.name || "课程"),source:chapter,rows:[],pages:0,max_id:0,max_order_num:0,more:null,exhausted:false};sections.push(section);catalogProgress.sections.push(clean(chapter));await page(section,true);
    }
    while (sections.some(s=>s.more===true || ids.size<expected && !s.exhausted)) {
      let progressed=false;
      for (const section of sections) {
        if (section.exhausted || section.more!==true && ids.size>=expected) continue;
        const before=ids.size;await page(section,false);progressed ||= ids.size>before;
      }
      if (!progressed && !sections.some(s=>s.more===true)) break;
    }
    const lessons=sections.flatMap(s=>s.rows);
    if (lessons.length!==expected || ids.size!==expected || sections.some(s=>s.more===true)) throw error("Catalog is incomplete against the source count");
    state.catalog_lessons=expected;
    return {course,metadata,sections:sections.map(s=>({...s.source,id:s.id,id_str:s.id,name:s.name,lesson_count:s.rows.length,pages_read:s.pages,pagination_count_verified:true})),lessons};
  }
  async function bodyFor(info) {
    const token=info.dd_article_token;
    if (!token) throw error("The source did not grant lesson body access");
    const body=await read("/pc/ddarticle/v1/article/get/v2",null,{token,sign:"b23a426b357d1b83",appid:"1632426125495894021",is_new:"1"});
    let blocks;try {blocks=JSON.parse(body.content);} catch {throw error("Lesson body is not valid JSON");}
    if (!Array.isArray(blocks) || !blocks.length) throw error("Lesson body is empty or is not a block array");
    return {body,blocks};
  }
  function checkInfo(info,lesson) {
    const article=info.article_info || {};
    const id=article.id_str ?? article.id ?? info.article_id;
    if (id!==undefined && String(id)!==lesson.id || article.enid && String(article.enid)!==lesson.enid) throw error("Lesson info differs from the catalog identity");
  }

  window.__courseArchiveMediaStatus=state;
  let id="unresolved";
  const videos={schema_version:1,source:"authorized_same_origin_web_media",captured_at:new Date().toISOString(),videos:[],errors:[],complete:false};
  const extras={schema_version:1,source:"authorized_exact_embedded_audio_aliases",captured_at:new Date().toISOString(),audios:[],errors:[],complete:false};
  const aliases=new Map();
  function embedded(value,result=[]) {
    if (Array.isArray(value)) for (const child of value) embedded(child,result);
    else if (value && typeof value==="object") {if (value.type==="audio") result.push(value);for(const child of Object.values(value)) if(child && typeof child==="object") embedded(child,result);}
    return result;
  }
  try {
    id=await courseId();const found=await catalog(id);const cached=window.__courseArchiveExport;
    const cachedRows=cached?.complete && cached.course?.enid===id ? new Map(cached.lessons.map(row=>[String(row.id),row])) : new Map();
    for (const target of [videos,extras]) {target.course_id=id;target.source_url=location.origin+"/course/detail?id="+encodeURIComponent(id);target.expected_lesson_count=found.lessons.length;}
    state.phase="media";
    for(const lesson of found.lessons) {
      const info=await articleInfo(lesson.enid);checkInfo(info,lesson);const article=info.article_info || {};
      const saved=cachedRows.get(lesson.id);let blocks;
      if(saved?.enid===lesson.enid) {try {blocks=JSON.parse(saved.body.content);} catch {throw error("Cached lesson body is invalid");}}
      else blocks=(await bodyFor(info)).blocks;
      if(!Array.isArray(blocks)||!blocks.length) throw error("Media inventory lacks a complete lesson body");
      const main=String(article.audio?.alias_id || "");
      for(const block of embedded(blocks)) {
        const alias=String(block.aliasId || block.alias_id || "");if(!alias) throw error("Embedded audio has no exact alias");if(alias===main) continue;
        const record=aliases.get(alias) || {alias_id:alias,lesson_ids:[],title:String(block.title || ""),expected_duration:block.duration};
        if(!record.lesson_ids.includes(lesson.id)) record.lesson_ids.push(lesson.id);aliases.set(alias,record);
      }
      const declared=Array.isArray(article.video) ? article.video : [];
      const ids=[...new Set(declared.map(v=>String(v.dd_media_id_str || v.dd_media_id || "")).filter(x=>x && x!=="0"))];
      if(!ids.length && (Number(article.video_status)>0 || declared.length)) {
        const mediaId=String(article.dd_media_id_str || article.dd_media_id || "");if(!mediaId || mediaId==="0") throw error("Video source has no media identity");ids.push(mediaId);
      }
      for(let index=0;index<ids.length;index++) {
        const mediaId=ids[index];const base=Array.isArray(article.media_base_info) ? article.media_base_info : [];
        const candidates=base.filter(item=>Number(item.media_type)===2 || String(item.media_id_str || item.dd_media_id_str || "")===mediaId);
        const exact=candidates.filter(item=>String(item.media_id_str || item.dd_media_id_str || item.source_id || "")===mediaId);
        const selected=exact.length===1 ? exact[0] : candidates.length===1 ? candidates[0] : null;
        if(!selected?.security_token) throw error("Video security authorization is unavailable or ambiguous");
        const media=await read("/media_gate/gate/api/v1/web",{media_id_str:mediaId,media_alias_id:"",security_token:selected.security_token});
        const formats=(media?.tracks || []).flatMap(track=>track.formats || []);
        if(!formats.some(format=>format.type==="video" && format.format==="m3u8" && /^https?:\/\//.test(format.url || ""))) throw error("Authorized Web source returned no HLS video formats");
        videos.videos.push({lesson_id:lesson.id,enid:lesson.enid,title:lesson.title,source_media_id:mediaId,...(ids.length>1 ? {video_index:index} : {}),media:clean(media)});state.videos=videos.videos.length;
      }
      state.scanned_lessons++;
    }
    state.phase="extra_audio";
    for(const item of aliases.values()) {
      const result=await read("/pc/bauhinia/v1/audio/mutiget_by_alias",{get_extra_data:1,ids:item.alias_id});
      const matched=(result?.list || []).filter(audio=>String(audio.alias_id)===item.alias_id);
      if(matched.length!==1 || !/^https?:\/\//.test(matched[0].mp3_play_url || "")) throw error("Exact embedded audio alias is missing or ambiguous");
      extras.audios.push({...item,lesson_id:item.lesson_ids.length===1 ? item.lesson_ids[0] : "",audio:clean(matched[0])});state.extra_audio=extras.audios.length;
    }
    state.complete=state.scanned_lessons===found.lessons.length && extras.audios.length===aliases.size;
    videos.complete=state.complete;extras.complete=state.complete;state.phase="finished";
  } catch(caught) {const safe=publicError(caught);videos.errors.push(safe);extras.errors.push(safe);state.errors=1;state.stopped=true;state.phase="stopped";}
  for(const target of [videos,extras]) {target.finished_at=new Date().toISOString();target.summary={...state};}
  const suffix=safeId(id)+"-"+(state.complete ? "complete" : "partial")+".json";
  const filenames=[save(videos,"dedao-web-media-"+suffix),save(extras,"dedao-extra-audio-"+suffix)];
  window.__courseArchiveMediaExport=videos;window.__courseArchiveExtraAudioExport=extras;
  return {...state,filenames};
})();
