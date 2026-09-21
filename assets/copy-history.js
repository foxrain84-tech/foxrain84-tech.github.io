/* Copy telemetry stores only the existing count key and a server timestamp. */
(function(root){
  'use strict';
  const KEY = /^[a-z0-9_-]+_\d{8}_set\d+_cut\d+$/i;
  function makePatch(key, id){
    if(!KEY.test(key) || !/^[a-zA-Z0-9_-]{16,80}$/.test(id)) throw new Error('Invalid copy identifier');
    return {
      ['copyCounts/' + key]: {'.sv':{increment:1}},
      ['copyEvents/' + id]: {key, at:{'.sv':'timestamp'}},
      ['copyLast/' + key]: {'.sv':'timestamp'}
    };
  }
  async function record(db, key){
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    const id = Array.from(bytes, n => n.toString(16).padStart(2,'0')).join('');
    // One atomic PATCH: either all three locations change or none do.
    // Never retry an ambiguous response: an increment may already have committed.
    const response = await fetch(db + '/.json?print=silent', {
      method:'PATCH', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(makePatch(key,id)), keepalive:true,
      signal:AbortSignal.timeout(15000)
    });
    if(!response.ok) throw new Error('Copy record unavailable');
  }
  function events(value){
    if(value === null) return [];
    if(!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid event response');
    return Object.entries(value).map(([id,e]) => {
      if(!e || typeof e.key !== 'string' || !KEY.test(e.key) ||
        !Number.isSafeInteger(e.at) || e.at <= 0 || e.at > 8640000000000000) throw new Error('Invalid event');
      return {id,key:e.key,at:e.at};
    }).sort((a,b) => b.at-a.at || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0));
  }
  function day(at = Date.now(), zone = 'Asia/Seoul'){
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
      timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'
    }).formatToParts(new Date(at)).map(p => [p.type,p.value]));
    return p.year + '-' + p.month + '-' + p.day;
  }
  function midnight(value, zone){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error('Invalid date');
    const target = Date.parse(value + 'T00:00:00Z');
    if(!Number.isFinite(target) || new Date(target).toISOString().slice(0,10) !== value) throw new Error('Invalid date');
    let guess = target;
    for(let i=0;i<4;i++){
      const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
        timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',
        hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'
      }).formatToParts(new Date(guess)).map(p => [p.type,p.value]));
      const rendered = Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute,+p.second);
      const delta = target-rendered;
      guess += delta;
      if(!delta) return guess;
    }
    throw new Error('Cannot resolve local date');
  }
  function range(value,zone){
    const next = new Date(Date.parse(value+'T00:00:00Z')+86400000).toISOString().slice(0,10);
    return {start:midnight(value,zone),end:midnight(next,zone)-1};
  }
  function eventURL(db,{date='',zone='Asia/Seoul',limit=null}={}){
    const params = new URLSearchParams({orderBy:JSON.stringify('at')});
    if(date){
      const r=range(date,zone);
      params.set('startAt',String(r.start)); params.set('endAt',String(r.end));
    }
    if(limit !== null) params.set('limitToLast',String(limit));
    return db+'/copyEvents.json?'+params;
  }
  function catalog(pages){
    const result=new Map();
    Object.entries(pages).forEach(([route,page]) => {
      if(!page || page.redirect) return;
      (page.cuts || []).forEach(cut => {
        const item={route,page,cut,keys:allCountKeys(page,cut)};
        item.keys.forEach(key => { if(!result.has(key)) result.set(key,item); });
      });
    });
    return result;
  }
  function lastFor(item,last){
    return Math.max(0,...(item?.keys || []).map(key => Number.isSafeInteger(last?.[key]) && last[key] <= 8640000000000000 ? last[key] : 0));
  }
  root.CopyHistory={makePatch,record,events,day,midnight,range,eventURL,catalog,lastFor};
})(typeof window === 'undefined' ? globalThis : window);
