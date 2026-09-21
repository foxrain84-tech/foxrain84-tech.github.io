/* Stats-only UI; the archive and copy routes retain their existing layout. */
async function renderCopyDashboard(pages){
  const el=(tag,text,cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const button=(text,action) => {const b=el('button',text,'stats-control');b.type='button';b.onclick=action;return b;};
  const content=document.getElementById('content');
  const meta=document.getElementById('meta');
  const notice=document.getElementById('notice');
  document.body.classList.add('stats-page');
  document.title='@yulim_mood · 프롬프트 복사 기록';
  document.getElementById('title').textContent='프롬프트 복사 기록';
  meta.textContent='어떤 프롬프트가 언제 복사되었는지 확인하세요.';
  content.replaceChildren(); notice.textContent=''; showBack('/','← 홈으로');
  if(!COUNTS_ENABLED){meta.textContent='복사수 집계가 아직 연결되지 않았습니다.';return;}
  const zone='Asia/Seoul'; // All display and day filters are fixed to Korea time.
  let counts={},history=null,last={},rows=[],baseline=null;
  let refreshId=0,eventsId=0,selectedDate='',limit=50,onlyChanges=false;
  const catalog=CopyHistory.catalog(pages);
  const toolbar=el('div',undefined,'stats-toolbar');
  const timeLabel=el('span','한국 시간 (KST · UTC+9)','stats-note');
  const refresh=button('새로고침',()=>load());toolbar.append(timeLabel,refresh);content.append(toolbar);
  const cards=el('div',undefined,'stats-cards');
  const card=(label,detail)=>{const n=el('section',undefined,'stats-card');const v=el('div','—','stats-card-value');n.append(el('div',label,'stats-card-label'),v,el('div',detail,'stats-card-detail'));cards.append(n);return v;};
  const totalCard=card('누적 복사수','기존 복사 횟수 포함');
  const todayCard=card('오늘 기록된 복사','한국 시간 0시 기준 · 기록 기능 적용 이후');
  const lastCard=card('최근 복사','상세 내역에서 날짜 확인');
  content.append(cards);
  const makeSection=(heading,cls)=>{
    const section=el('section',undefined,'stats-section '+cls);
    const head=el('div',undefined,'stats-section-head');head.append(el('h2',heading));section.append(head);content.append(section);return {section,head};
  };
  const recent=makeSection('최근 복사 내역','stats-recent');
  const filters=el('div',undefined,'stats-filters');
  const all=button('전체',()=>chooseDate(''));
  const today=button('오늘',()=>chooseDate(CopyHistory.day(Date.now(),zone)));
  const dateInput=el('input',undefined,'stats-control');dateInput.type='date';dateInput.setAttribute('aria-label','복사 내역 날짜 선택');
  dateInput.onchange=()=>chooseDate(dateInput.value);
  filters.append(all,today,dateInput);recent.head.append(filters);
  function table(parent,headers,cls){
    const wrap=el('div',undefined,'stats-table-wrap');wrap.tabIndex=0;wrap.setAttribute('aria-label','표 · 좁은 화면에서는 좌우로 스크롤');
    const t=el('table',undefined,'stats-table '+cls);t.append(el('caption',headers.join(' · ')));
    const thead=el('thead');const tr=el('tr');headers.forEach(h=>{const th=el('th',h);th.scope='col';tr.append(th);});thead.append(tr);
    const body=el('tbody');t.append(thead,body);wrap.append(t);parent.append(wrap);return body;
  }
  const eventBody=table(recent.section,['복사 시각','프롬프트','세트 / 컷'],'stats-history-table');
  const eventStatus=el('p','불러오는 중…','stats-note');eventStatus.setAttribute('aria-live','polite');
  const more=button('더 보기',()=>{limit+=50;loadEvents();});more.classList.add('stats-more');more.hidden=true;
  recent.section.append(eventStatus,more,el('p','복사 기록은 기능 적용 이후부터 표시됩니다. 모바일에서는 표를 좌우로 밀어 확인하세요.','stats-note'));
  const ranking=makeSection('복사수 랭킹','stats-ranking');
  const changed=button('순위 변동만 보기',()=>{onlyChanges=!onlyChanges;drawRanks();});changed.setAttribute('aria-pressed','false');ranking.head.append(changed);
  const rankBody=table(ranking.section,['순위','프롬프트 · 세트 / 컷','누적 복사수','어제 대비 증가','마지막 복사'],'stats-ranking-table');
  const rankNote=el('p','불러오는 중…','stats-note');ranking.section.append(rankNote);
  const stateNote=el('p','', 'stats-note');content.append(stateNote);
  const dateTime=(at,short=false)=>at?new Intl.DateTimeFormat('ko-KR',{
    timeZone:zone,...(short?{}:{year:'numeric',month:'2-digit',day:'2-digit'}),
    hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'
  }).format(new Date(at)):'—';
  function promptCell(item){
    const td=el('td');
    if(item){
      const a=el('a',item.cut.title || '제목 없는 컷');a.href=item.route;
      td.append(a,el('span',pageLabel(item.page)+' · '+formatDate(item.page.date),'sub'));
    }else td.append(el('span','현재 공개 목록에 없는 컷'));
    return td;
  }
  function chooseDate(value){selectedDate=value;limit=50;dateInput.value=value;loadEvents();}
  async function loadEvents(){
    const request=++eventsId;
    all.setAttribute('aria-pressed',String(!selectedDate));
    today.setAttribute('aria-pressed',String(selectedDate===CopyHistory.day(Date.now(),zone)));
    eventStatus.textContent='복사 기록을 불러오는 중…';more.disabled=true;
    try{
      const data=await fetchStatsJSON(CopyHistory.eventURL(FIREBASE_DB,{date:selectedDate,zone,limit:limit+1}));
      const entries=CopyHistory.events(data);
      if(request!==eventsId)return;
      eventBody.replaceChildren();
      entries.slice(0,limit).forEach(e=>{
        const item=catalog.get(e.key);const tr=el('tr');
        tr.append(el('td',dateTime(e.at),'stats-time'),promptCell(item),
          el('td',item?'SET '+String(item.page.source_set||item.page.set).padStart(2,'0')+' · CUT '+String(item.cut.cut).padStart(2,'0'):'—','stats-number'));
        eventBody.append(tr);
      });
      eventStatus.textContent=entries.length
        ? (selectedDate || '전체 기간')+' · 최신순 '+Math.min(entries.length,limit)+'건 표시'
        : '해당 기간의 복사 기록이 없습니다.';
      more.hidden=entries.length<=limit;
    }catch(_){
      if(request!==eventsId)return;
      eventBody.replaceChildren();more.hidden=true;
      eventStatus.textContent='복사 기록을 불러오지 못했습니다. Firebase 규칙·인덱스 설정 또는 네트워크를 확인한 뒤 새로고침해 주세요.';
    }finally{if(request===eventsId)more.disabled=false;}
  }
  function drawRanks(){
    rankBody.replaceChildren();
    changed.disabled=!baseline;changed.setAttribute('aria-pressed',String(onlyChanges));changed.textContent=onlyChanges?'전체 랭킹 보기':'순위 변동만 보기';
    const shown=rows.filter(row=>!onlyChanges || row.oldRank===null || row.movement!==0);
    shown.forEach(row=>{
      const tr=el('tr'),rank=el('td');rank.append(el('span',String(row.rank),'stats-rank'));
      const shift=baseline?statsMovement(row):'비교 기록 없음';
      rank.append(el('span',shift,'sub '+(row.movement>0?'stats-up':row.movement<0?'stats-down':'')));
      const item=catalog.get(row.id);const prompt=promptCell(item);
      if(item)prompt.append(el('span','SET '+String(row.setNum).padStart(2,'0')+' · CUT '+String(row.cutNum).padStart(2,'0'),'sub'));
      const growth=el('td');growth.append(el('span',baseline?(row.delta>0?'+':'')+row.delta.toLocaleString():'—',baseline?'stats-pill '+(row.delta<0?'stats-down':'stats-up'):''));
      const at=CopyHistory.lastFor(item,last);
      tr.append(rank,prompt,el('td',row.count.toLocaleString()+'회','stats-number'),growth,el('td',at?dateTime(at):'—','stats-number'));rankBody.append(tr);
    });
    if(!shown.length){const tr=el('tr');const td=el('td',onlyChanges?'순위가 변동된 컷이 없습니다.':'아직 복사된 프롬프트가 없습니다.','stats-empty');td.colSpan=5;tr.append(td);rankBody.append(tr);}
    rankNote.textContent=(baseline
      ? '비교 기준: '+dateTime(Date.parse(baseline.at))+' (한국 날짜 기준 전날 마지막 저장값). 자정 확정값은 아닙니다.'
      : '어제 비교 기록이 없습니다. 전날 저장 기록이 쌓이면 증가량과 순위 변화가 표시됩니다.')+
      ' 기존과 동일한 컷별 랭킹이며, 동일 복사수는 공동 순위입니다. 시각이 없는 과거 복사는 —로 표시합니다.';
  }
  async function load(){
    const request=++refreshId;++eventsId;refresh.disabled=true;stateNote.textContent='최신 집계를 불러오는 중…';
    const todayDate=CopyHistory.day(Date.now(),zone);
    const result=await Promise.allSettled([
      fetchStatsJSON(FIREBASE_DB+'/copyCounts.json'),
      fetchStatsJSON('https://raw.githubusercontent.com/foxrain84-tech/foxrain84-tech.github.io/main/stats-history.json?v='+Date.now()),
      fetchStatsJSON(FIREBASE_DB+'/copyLast.json'),
      fetchStatsJSON(CopyHistory.eventURL(FIREBASE_DB,{date:todayDate,zone}))
    ]);
    if(request!==refreshId)return;
    const failures=[];
    if(result[0].status==='fulfilled' && validStatsCounts(result[0].value || {})){
      counts=result[0].value || {};history=result[1].status==='fulfilled'?result[1].value:null;
      baseline=history?statsBaseline(history):null;
      const current=statsRows(pages,counts);
      rows=baseline?statsChanges(current,statsRows(pages,baseline.counts)):current;
      if(!baseline)onlyChanges=false;
      totalCard.textContent=rows.reduce((n,r)=>n+r.count,0).toLocaleString()+'회';
      meta.textContent='어떤 프롬프트가 언제 복사되었는지 확인하세요. · 복사된 컷 '+rows.length+'개';
    }else{rows=[];baseline=null;totalCard.textContent='—';failures.push('누적 복사수 조회 실패');}
    last={};lastCard.textContent='—';
    if(result[2].status==='fulfilled' && (result[2].value===null || validStatsCounts(result[2].value))){
      last=result[2].value || {};
      const latest=Object.values(last).reduce((max,at)=>Math.max(max,at),0);
      if(latest && latest<=8640000000000000){lastCard.textContent=dateTime(latest,true);lastCard.nextElementSibling.textContent=dateTime(latest);}
      else lastCard.nextElementSibling.textContent='기록 기능 적용 이후 표시';
    }else{lastCard.nextElementSibling.textContent='최근 시각 조회 실패';failures.push('최근 시각 조회 실패');}
    todayCard.textContent='—';
    try{
      if(result[3].status!=='fulfilled')throw new Error();
      todayCard.textContent=CopyHistory.events(result[3].value).length.toLocaleString()+'회';
    }catch(_){failures.push('오늘 기록 조회 실패');}
    drawRanks();
    if(result[0].status==='rejected')rankNote.textContent='랭킹을 불러오지 못했습니다. 새로고침해 주세요.';
    stateNote.textContent=failures.length?failures.join(' · ')+' · 설정 또는 네트워크를 확인해 주세요.':'갱신: '+dateTime(Date.now());
    refresh.disabled=false;
    loadEvents();
  }
  notice.textContent='모든 복사 시각과 날짜는 한국 시간(KST) 기준입니다. 어제 대비 증감은 기존 한국 시간 스냅샷 기준이므로 두 수치는 다를 수 있습니다.';
  await load();
}
