/* Install on the user's authorized Dedao page, then open a different lesson
 * through its normal UI without a full reload. Captures exactly one genuine
 * same-origin article/info POST. Headers remain in a closure, never in exports.
 * The facade allows only the listed read endpoints. clear()/cancel() restores
 * or removes all helper-owned state; no account or playback-progress writes.
 */
(()=>{
  "use strict";
  if(location.origin!=="https://www.dedao.cn") throw new Error("Use the authorized https://www.dedao.cn page");
  window.__courseArchiveCapture?.cancel?.();
  const status={installed:true,captured:false,expired:false,cancelled:false,requests:0};
  const allowed=new Map([
    ["/pc/bauhinia/pc/class/info","POST"],["/pc/bauhinia/pc/class/free_article_list","POST"],
    ["/pc/bauhinia/pc/article/info","POST"],["/pc/ddarticle/v1/article/get/v2","GET"],
    ["/pc/bauhinia/v1/audio/mutiget_by_alias","POST"],["/media_gate/gate/api/v1/web","POST"]
  ]);
  const prototype=XMLHttpRequest.prototype;
  const original={open:prototype.open,setRequestHeader:prototype.setRequestHeader,send:prototype.send};
  const observations=new WeakMap();let expiry;let active=true;
  function restore(){prototype.open=original.open;prototype.setRequestHeader=original.setRequestHeader;prototype.send=original.send;clearTimeout(expiry);status.installed=false;}
  prototype.open=function(method,url,...rest){
    const target=new URL(url,location.href);
    if(String(method).toUpperCase()==="POST" && target.origin===location.origin && target.pathname==="/pc/bauhinia/pc/article/info") observations.set(this,{headers:[]});
    return original.open.call(this,method,url,...rest);
  };
  prototype.setRequestHeader=function(name,value){const record=observations.get(this);if(record) record.headers.push([String(name),String(value)]);return original.setRequestHeader.call(this,name,value);};
  prototype.send=function(body){
    const record=observations.get(this);
    if(record && !status.captured && active){
      status.captured=true;restore();window.__courseArchiveReadSession?.clear?.();
      let sourcePayload={};try{sourcePayload=JSON.parse(body || "{}");}catch{sourcePayload={};}
      const headers=record.headers;const withCredentials=Boolean(this.withCredentials);
      let lastStart=Date.now();let queue=Promise.resolve();let cleared=false;let halted=false;
      const inspected=Object.freeze({captured:true,path:"/pc/bauhinia/pc/article/info",method:"POST",header_names:[...new Set(headers.map(([name])=>name))],body_fields:Object.keys(sourcePayload),with_credentials:withCredentials});
      const facade={
        inspect:()=>inspected,
        read:(path,{payload=null,query=null}={})=>{
          if(!allowed.has(path)) return Promise.reject(new Error("Unsupported read endpoint"));
          const operation=queue.then(async()=>{
            if(cleared || halted) throw new Error("Read session was cleared or halted");
            await new Promise(resolve=>setTimeout(resolve,Math.max(0,350-(Date.now()-lastStart))));
            if(cleared || halted) throw new Error("Read session was cleared or halted");
            const url=new URL(path,location.origin);
            if(query) for(const [key,value] of Object.entries(query)) url.searchParams.set(key,String(value));
            lastStart=Date.now();status.requests++;
            return await new Promise((resolve,reject)=>{
              const xhr=new XMLHttpRequest();const method=allowed.get(path);
              original.open.call(xhr,method,url.href,true);xhr.withCredentials=withCredentials;xhr.timeout=20000;
              for(const [name,value] of headers) original.setRequestHeader.call(xhr,name,value);
              xhr.onload=()=>{
                if(xhr.status<200 || xhr.status>=300){halted=true;status.stopped=true;reject(Object.assign(new Error("HTTP read rejected"),{http_status:xhr.status}));return;}
                try{const data=JSON.parse(xhr.responseText);if(!data?.h || Number(data.h.c)!==0){halted=true;status.stopped=true;reject(Object.assign(new Error("API read rejected or challenge"),{http_status:xhr.status,api_code:data?.h?.c}));return;}resolve({http_status:xhr.status,data});}catch{halted=true;status.stopped=true;reject(new Error("Non-JSON response or challenge"));}
              };
              xhr.onerror=()=>{halted=true;status.stopped=true;reject(new Error("Same-origin read failed"));};xhr.ontimeout=()=>{halted=true;status.stopped=true;reject(new Error("Read timed out"));};
              const requestPayload=path==="/pc/bauhinia/pc/article/info" ? {...sourcePayload,...payload} : payload;
              original.send.call(xhr,method==="POST" ? JSON.stringify(requestPayload || {}) : null);
            });
          });
          queue=operation.catch(()=>{});return operation;
        },
        clear:()=>{cleared=true;for(const header of headers) header[1]="";sourcePayload={};if(window.__courseArchiveReadSession===facade) delete window.__courseArchiveReadSession;}
      };
      window.__courseArchiveReadSession=Object.freeze(facade);
    }
    return original.send.call(this,body);
  };
  const cancel=()=>{active=false;status.cancelled=true;restore();};
  window.__courseArchiveCapture={status,cancel};
  expiry=setTimeout(()=>{active=false;status.expired=true;restore();},120000);
  return {...status,instruction:"Open a different lesson through the normal page UI, then inspect capture status; clear the read session after exports"};
})();
