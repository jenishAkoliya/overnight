/* Overnight UI — React + htm, hash-routed, no build step. Never renders secrets or full email bodies. */
const {useState,useEffect,useRef,useMemo}=React; const html=htm.bind(React.createElement);
const api=(p,o)=>fetch(p,o).then(async r=>{let j={};try{j=await r.json()}catch(e){} return {...j,_ok:r.ok,_s:r.status}});
const post=(p,body)=>api(p,{method:'POST',...(body?{headers:{'content-type':'application/json'},body:JSON.stringify(body)}:{})});
const T=(s)=>s?new Date(s).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/Los_Angeles'}):'';
const DT=(s)=>s?new Date(s).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit'}):'';
const ACTION={archive:'Archive email',file_receipt:'Label & archive receipt',label:'Apply label',accept_recurring:'Accept recurring invite',rsvp:'RSVP to event',reminder:'Create calendar reminder',draft_reply:'Create reply draft',reply:'Send reply',payment:'Pay invoice',confirm_meeting:'Post to Slack + create event',cancel_meeting:'Cancel meeting',delete:'Delete data',share:'Share data',schedule:'Schedule / respond',other:'Manual review',work:'Focus work (you)'};
const RISK=['phishing','prompt_injection','spoofed_sender','money','irreversible','new_contact','delete','data_sharing','preference_conflict','external_send'];
const stateOf=t=>t.status==='blocked'?'BLOCKED':t.status==='failed'?'FAILED':(t.decision||'ASK');
const ORDER={BLOCKED:0,VERIFY:1,ASK:2,FAILED:1,AUTO:3};

/* ---------- small components ---------- */
const Badge=({s,children})=>html`<span class=${'badge b-'+s}>${children||s}</span>`;
const Chip=({c,risk})=>html`<span class=${'chip'+(risk?' risk':'')}>${c}</span>`;
const Conf=({v})=>html`<div style=${{display:'flex',alignItems:'center',gap:8}}><div class="bar" style=${{width:70}}><i style=${{width:Math.round((v||0)*100)+'%',background:v>=.8?'var(--ok)':v>=.5?'var(--warn)':'var(--bad)'}}/></div><small>${(v||0).toFixed(2)}</small></div>`;
const Empty=({title,children,action})=>html`<div class="empty"><b>${title}</b>${children}${action?html`<div style=${{marginTop:12}}>${action}</div>`:null}</div>`;
const Loading=({what})=>html`<div class="empty"><b>Loading…</b>${what||''}</div>`;
const ErrBox=({m})=>html`<div class="err">${m}</div>`;
const Card=({title,right,children,cls})=>html`<div class=${'card '+(cls||'')}>${title?html`<div style=${{display:'flex',alignItems:'center',marginBottom:10}}><h2 style=${{margin:0,flex:1}}>${title}</h2>${right}</div>`:null}${children}</div>`;
const Simulated=({sim})=>sim?html`<${Badge} s="SIM">SIMULATED</${Badge}>`:null;
const Risks=({t})=>html`<span>${(t.flags||[]).filter(f=>RISK.includes(f)).map(f=>html`<${Chip} key=${f} c=${'⚑ '+f.replace(/_/g,' ')} risk=${true}/>`)}</span>`;

function useFetch(path,deps=[]){const [d,setD]=useState(null);const [e,setE]=useState('');const [n,setN]=useState(0);
  useEffect(()=>{let live=true;setE('');api(path).then(j=>{if(!live)return;if(!j._ok)setE('Request failed ('+j._s+')');else setD(j)}).catch(x=>live&&setE(String(x)));return()=>{live=false}},[path,n,...deps]);
  return [d,e,()=>setN(x=>x+1)];}

/* ---------- confirm / verify modal ---------- */
function ConfirmModal({task,sim,live,onClose,onDone,notify}){
  const isReply=['reply','draft_reply'].includes(task.action_type); const [body,setBody]=useState(isReply?'Hi,\n\nThanks for your message — '+(task.suggestion||'happy to help.')+'\n\nBest,\nCortona':'');
  const [st,setSt]=useState(task.decision==='VERIFY'?'needs_verify':'ready'); const [busy,setBusy]=useState(false); const [err,setErr]=useState(''); const iid=useRef(null);
  const verify=async()=>{setSt('verifying');const r=await post('/verify/'+task.id+'/start');iid.current=r.id;
    for(let i=0;i<40;i++){await new Promise(x=>setTimeout(x,1000));const s=await api('/verify/'+iid.current+'/status?tid='+task.id);if(s.status==='completed'){setSt('ready');return}if(['failed','declined','expired'].includes(s.status)){setSt('failed');return}}setSt('failed')};
  const confirm=async()=>{setBusy(true);setErr('');const r=await post('/approve/'+task.id,isReply?{reply_body:body}:undefined);setBusy(false);if(!r._ok){setErr(r.detail||'Not allowed');return}notify(live?(r.result&&r.result.ok?'Done for real: '+(ACTION[task.action_type]||task.action_type):'Not done: '+(r.result?r.result.why:'error')):sim?'Approved — action simulated (dry run)':'Approved');onDone()};
  const ops=(task.council&&task.council.opinions)||[];
  return html`<div class="scrim" onClick=${onClose}><div class="modal" onClick=${e=>e.stopPropagation()} id="confirm-modal">
    <h2>Confirm proposed action</h2>
    ${live&&task.action_type!=='payment'?html`<div class="err" style=${{margin:'0 0 12px'}}><b>This will make a REAL change</b> on your account when you confirm${task.action_type==='reply'?' — the reply is actually SENT to the sender':''}.</div>`:html`<div class="strip" style=${{borderRadius:8,margin:'0 0 12px',padding:'8px 12px'}}><b>DRY RUN — No external changes will be made.</b></div>`}
    <dl class="kv"><dt>Action</dt><dd><b>${ACTION[task.action_type]||task.action_type}</b></dd><dt>Target</dt><dd>${task.title}</dd><dt>State</dt><dd><${Badge} s=${stateOf(task)}/> <${Simulated} sim=${sim}/></dd>
     <dt>Confidence</dt><dd><${Conf} v=${task.confidence}/></dd><dt>Why it needs you</dt><dd>${task.why}</dd><dt>Risk flags</dt><dd><${Risks} t=${task}/>${(task.flags||[]).filter(f=>RISK.includes(f)).length?null:html`<small>none</small>`}</dd></dl>
    <h3>Policy & council checks</h3>${ops.map(o=>html`<div class="why" key=${o.agent}><b>${o.agent}</b> <${Badge} s=${o.vote==='BLOCK'?'BLOCKED':o.vote}>${o.vote}</${Badge}> ${o.reason}</div>`)}
    ${task.decision==='VERIFY'?html`<h3>Identity verification (Persona)</h3>${st==='needs_verify'?html`<button class="warn" onClick=${verify}>Verify identity</button>`:st==='verifying'?html`<span>Verifying… <small style=${{cursor:'pointer',opacity:.4}} onClick=${()=>iid.current&&post('/verify/'+iid.current+'/simulate')}>(sim)</small></span>`:st==='failed'?html`<${ErrBox} m="Verification failed. Nothing was done."/>`:html`<${Badge} s="AUTO">Verified ✓</${Badge}>`}`:null}
    ${isReply?html`<h3>Your reply (edit before sending)</h3><textarea id="reply-body" rows="6" style=${{width:'100%',font:'inherit',padding:8,border:'1px solid var(--line2)',borderRadius:6}} value=${body} onInput=${e=>setBody(e.target.value)}/>`:null}
    ${err?html`<${ErrBox} m=${err}/>`:null}
    <div style=${{display:'flex',gap:8,justifyContent:'flex-end',marginTop:16}}><button onClick=${onClose}>Cancel</button><button class="pri" id="confirm-go" disabled=${busy||st!=='ready'} onClick=${confirm}>${busy?'Working…':live&&task.action_type!=='payment'?(task.action_type==='reply'?'Confirm & send':'Confirm & execute'):sim?'Confirm (simulated)':'Confirm'}</button></div></div></div>`;
}

/* ---------- task drawer ---------- */
function Drawer({t,sim,onClose,onApprove,onReject,goCouncil}){
  const it=t.item||{}; const sg=t.signal||{};
  return html`<div><div class="scrim" style=${{background:'#0f172a33',placeItems:'start'}} onClick=${onClose}/><div class="drawer" id="task-drawer">
    <div style=${{display:'flex',alignItems:'center',gap:8}}><${Badge} s=${stateOf(t)}/> <${Simulated} sim=${sim&&t.decision==='AUTO'}/> <span style=${{flex:1}}/><button class="sm" onClick=${onClose}>Close ✕</button></div>
    <h2 style=${{marginTop:12,fontSize:18}}>${t.title}</h2>
    <h3>Source</h3><dl class="kv"><dt>Where</dt><dd>${it.source||'—'} · ${it.type||''}</dd><dt>From</dt><dd>${it.author||'—'}</dd><dt>Subject</dt><dd>${it.subject||'—'} <small>(body is never shown)</small></dd><dt>Received</dt><dd>${it.ts?DT(it.ts):'—'}</dd></dl>
    <h3>Scoring</h3><dl class="kv"><dt>Confidence</dt><dd><${Conf} v=${t.confidence}/></dd><dt>Value</dt><dd>${t.value}</dd><dt>Small-model signal</dt><dd>routine ${sg.routine??'—'} · kind ${sg.kind||'—'} · stakes ${sg.stakes||'—'} <small>(${sg.via||'rules'})</small></dd><dt>Risk flags</dt><dd><${Risks} t=${t}/>${(t.flags||[]).length?null:html`<small>none</small>`}</dd></dl>
    <h3>Policy decision</h3><p>${t.why}</p>${t.suggestion?html`<h3>Suggestion</h3><div class="note">${t.suggestion}</div>`:null}
    ${t.result?html`<h3>Execution</h3><p>${t.result.status==='dry_run'||sim?html`<${Badge} s="SIM">SIMULATED</${Badge}>`:null} ${t.result.why}</p>`:null}
    <div style=${{display:'flex',gap:8,flexWrap:'wrap',marginTop:14}}><button onClick=${goCouncil}>Open council decision</button>
     ${t.status==='needs_you'&&t.action_type!=='work'?html`<button class="pri" onClick=${onApprove}>Review & approve…</button><button class="danger" onClick=${onReject}>Reject</button>`:null}</div></div></div>`;
}

/* ---------- pages ---------- */
function Overview({d,go}){
  const tasks=d.tasks, cnt=s=>tasks.filter(t=>stateOf(t)===s&&t.action_type!=='work').length; const N={AUTO:cnt('AUTO'),ASK:cnt('ASK'),VERIFY:cnt('VERIFY'),BLOCKED:cnt('BLOCKED'),FAILED:cnt('FAILED')};
  const total=Object.values(N).reduce((a,b)=>a+b,0)||1; const [rd]=useFetch('/readiness?sims=false',[d.runs]);
  const flags={};tasks.forEach(t=>(t.flags||[]).filter(f=>RISK.includes(f)).forEach(f=>flags[f]=(flags[f]||0)+1));
  if(!d.plan)return html`<div class="card"><${Empty} title="No plan yet" action=${html`<button class="pri" onClick=${d.run}>Simulate tonight</button>`}>Press “Simulate tonight” to read your sources, score every item and see what Overnight would do while you sleep.</${Empty}></div>`;
  const m=d.metrics||{};
  return html`<div class="grid" style=${{gap:16}}>
   <div class="grid g4">
    <${Card} cls="kpi"><b>${tasks.length}</b><span>items turned into tasks</span></${Card}>
    <${Card} cls="kpi"><b style=${{color:'var(--ok)'}}>${N.AUTO}</b><span>AUTO — simulated, safe & reversible</span></${Card}>
    <${Card} cls="kpi"><b style=${{color:'var(--warn)'}}>${N.ASK+N.VERIFY}</b><span>need you (${N.ASK} ask · ${N.VERIFY} verify)</span></${Card}>
    <${Card} cls="kpi"><b style=${{color:'var(--bad)'}}>${N.BLOCKED+N.FAILED}</b><span>blocked / failed — never executed</span></${Card}></div>
   <div class="grid g2">
    <${Card} title="Risk summary" right=${html`<button class="sm" onClick=${()=>go('tasks')}>Open inbox</button>`}>
      <div class="stack"><i style=${{width:N.AUTO/total*100+'%',background:'var(--ok)'}}/><i style=${{width:N.ASK/total*100+'%',background:'#f59e0b'}}/><i style=${{width:N.VERIFY/total*100+'%',background:'#d97706'}}/><i style=${{width:(N.BLOCKED+N.FAILED)/total*100+'%',background:'var(--bad)'}}/></div>
      <div style=${{margin:'10px 0'}}><${Badge} s="AUTO">AUTO ${N.AUTO}</${Badge}> <${Badge} s="ASK">ASK ${N.ASK}</${Badge}> <${Badge} s="VERIFY">VERIFY ${N.VERIFY}</${Badge}> <${Badge} s="BLOCKED">BLOCKED ${N.BLOCKED}</${Badge}></div>
      <h3>Risk flags raised</h3>${Object.keys(flags).length?Object.entries(flags).map(([f,n])=>html`<${Chip} key=${f} c=${f.replace(/_/g,' ')+' × '+n} risk=${true}/>`):html`<small>No risk flags in this run.</small>`}
      <h3>Morning brief</h3><p style=${{margin:0}}>${d.brief&&d.brief.greeting}</p>${d.brief&&(d.brief.failed||[]).length?html`<${ErrBox} m=${(d.brief.failed_detail||[]).map(f=>f.title).join('; ')+' — FAILED, not done'}/>`:null}</${Card}>
    <${Card} title="System health" right=${html`<button class="sm" onClick=${()=>go('settings')}>Safety</button>`}>
      ${rd?html`<dl class="kv"><dt>Server</dt><dd><span class="dot g"/>ok</dd><dt>Write policy</dt><dd><${Badge} s=${rd.dry_run?'SIM':'BLOCKED'}>${rd.dry_run?'DRY RUN':'LIVE WRITES'}</${Badge}></dd>
        <dt>Sources</dt><dd>${rd.live_sources.length?html`<${Badge} s="LIVE">LIVE: ${rd.live_sources.join(', ')}</${Badge}>`:html`<small>none live</small>`} <${Badge} s="MOCK">MOCK: ${rd.mock_sources.length}</${Badge}></dd>
        <dt>Hosted Superlinked</dt><dd>${rd.hosted_superlinked.blocked_because_real_data?'blocked (real data)':rd.hosted_superlinked.allowed_for_current_data?'allowed (demo data)':'off'} · ${rd.hosted_superlinked.calls_this_process} calls</dd>
        <dt>Tests</dt><dd>${rd.tests.known?html`<span class=${'dot '+(rd.tests.failed?'r':'g')}/>${rd.tests.collected-rd.tests.failed}/${rd.tests.collected} passed`:'not run yet'}</dd>
        <dt>Firedrill (local)</dt><dd>${rd.firedrill_local.not_run_yet?'not run yet — open Evaluations':rd.firedrill_local.passed+'/'+rd.firedrill_local.total+' scenarios (last run)'}</dd><dt>Secrets scan</dt><dd><span class=${'dot '+(rd.secrets_scan.clean?'g':'r')}/>${rd.secrets_scan.clean?'clean':'FOUND'}</dd>
        ${(rd.degraded||[]).length?html`<dt>Degraded</dt><dd style=${{color:'var(--bad)'}}>${rd.degraded.join(', ')} — see Sources</dd>`:null}</dl>`:html`<${Loading}/>`}
      ${m.sie_tier?html`<div class="why" style=${{marginTop:8}}>Superlinked tier <b>${m.sie_tier}</b>: ${m.sie_hosted_calls||0} hosted · ${m.sie_local_calls||0} local · ${m.sie_mock_calls||0} mock calls · ${m.gen_calls||0} generation · ${m.credits_used||0} credits</div>`:null}</${Card}></div>
   <div class="grid g2">
    <${Card} title=${'Tomorrow’s plan — '+new Date(d.plan.date+'T12:00').toLocaleDateString('en-US',{weekday:'long',month:'short',day:'numeric'})}><div class="why" style=${{marginBottom:6}}>${d.plan.summary} · planner: ${d.plan.planner}</div>
      <div class="tl">${d.plan.blocks.length?d.plan.blocks.map((b,i)=>html`<div class="blk" key=${i}><span class="tm">${T(b.start)}–${T(b.end)}</span><div><b>${b.title}</b> ${b.kind==='task'?html`<${Chip} c="focus task"/>`:null}${b.note?html`<div class="why">${b.note}</div>`:null}</div></div>`):html`<${Empty} title="Nothing scheduled">No events or focus tasks for this day.</${Empty}>`}</div></${Card}>
    <${Card} title="Recent activity" right=${html`<button class="sm" onClick=${()=>go('audit')}>Audit log</button>`}>
      ${d.events.length?d.events.slice(-9).reverse().map(e=>html`<div key=${e.seq} style=${{padding:'5px 0',borderBottom:'1px solid var(--line)'}}><${Chip} c=${e.agent} pri=${true}/> ${e.decision?html`<${Badge} s=${e.decision}/> `:null}${e.summary}</div>`):html`<${Empty} title="No activity yet"/>`}</${Card}></div>
   <${Card} title="Reminders — needs you" right=${html`<small>${(d.rem||[]).filter(r=>r.urgency==='overdue'||r.urgency==='soon').length} due soon or overdue</small>`}><${ReminderList} rs=${d.rem} reload=${d.loadRem} openTask=${d.openTask} limit=${6}/></${Card}>
   <${AskMemory}/></div>`;
}
function AskMemory(){const [q,setQ]=useState('Does the user own a car, and how do they get around?');const [r,setR]=useState(null);const [busy,setBusy]=useState(false);
  const go=async()=>{setBusy(true);setR(null);const j=await post('/memory/ask',{text:q});setBusy(false);setR(j)};
  return html`<${Card} title="Ask memory" right=${html`<${Chip} c="Cognee + Superlinked LLM & embeddings" pri=${true}/>`}><div style=${{display:'flex',gap:8}}><input type="text" id="mem-q" style=${{flex:1}} value=${q} onInput=${e=>setQ(e.target.value)} onKeyDown=${e=>{if(e.key==='Enter')go()}}/><button class="pri" disabled=${busy} onClick=${go}>${busy?'Thinking…':'Ask'}</button></div>
   ${r?(r.ok?html`<div style=${{marginTop:10}}>${(r.answers||[]).length?r.answers.map((a,i)=>html`<p key=${i} style=${{margin:'4px 0'}}>${a}</p>`):html`<small>No answer found.</small>`}<div class="why">${r.via}</div></div>`:html`<div style=${{marginTop:10}}><${ErrBox} m=${r.error||'Cognee unavailable'}/></div>`):null}</${Card}>`;}

function Tasks({d,sim,openTask}){
  const [f,setF]=useState('ALL'); const [q,setQ]=useState(''); const [sort,setSort]=useState('priority');
  const all=d.tasks; const stc=s=>all.filter(t=>s==='ALL'||stateOf(t)===s).length;
  let rows=all.filter(t=>(f==='ALL'||stateOf(t)===f)&&(!q||(t.title+' '+((t.item||{}).author||'')+' '+((t.item||{}).subject||'')).toLowerCase().includes(q.toLowerCase())));
  const risk=t=>(t.flags||[]).filter(x=>RISK.includes(x)).length;
  rows=[...rows].sort({priority:(a,b)=>ORDER[stateOf(a)]-ORDER[stateOf(b)]||b.priority-a.priority,confAsc:(a,b)=>a.confidence-b.confidence,confDesc:(a,b)=>b.confidence-a.confidence,risk:(a,b)=>risk(b)-risk(a),source:(a,b)=>((a.item||{}).source||'').localeCompare((b.item||{}).source||'')}[sort]);
  return html`<div>
   <${AddTask} d=${d}/>
   <div class="tools"><div class="seg" id="filters">${['ALL','AUTO','ASK','VERIFY','BLOCKED'].map(s=>html`<button key=${s} class=${f===s?'on':''} data-f=${s} onClick=${()=>setF(s)}>${s} <small>${stc(s)}</small></button>`)}</div>
    <input type="text" id="task-search" placeholder="Search tasks, senders, subjects…" value=${q} onInput=${e=>setQ(e.target.value)} style=${{flex:1,minWidth:180}}/>
    <select id="task-sort" value=${sort} onChange=${e=>setSort(e.target.value)}><option value="priority">Sort: priority</option><option value="confAsc">Confidence ↑ (least sure)</option><option value="confDesc">Confidence ↓</option><option value="risk">Most risk flags</option><option value="source">Source</option></select></div>
   <div class="card" style=${{padding:0,overflow:'auto'}}>${!d.plan?html`<${Empty} title="No tasks yet" action=${html`<button class="pri" onClick=${d.run}>Simulate tonight</button>`}>Run a night to ingest your sources.</${Empty}>`:!rows.length?html`<${Empty} title="No tasks match">Try another filter or search.</${Empty}>`:html`
    <table id="task-table"><thead><tr><th>State</th><th>Task</th><th>Source</th><th>Confidence</th><th>Value</th><th>Risk</th></tr></thead><tbody>${rows.map(t=>html`<tr class="click" key=${t.id} onClick=${()=>openTask(t.id)}>
      <td><${Badge} s=${stateOf(t)}/>${sim&&t.decision==='AUTO'?html`<div><${Simulated} sim=${true}/></div>`:null}</td><td><b>${t.title}</b><div class="why">${(t.item||{}).author||''}</div></td><td><${Badge} s="N">${(t.item||{}).source||'user'}</${Badge}></td><td><${Conf} v=${t.confidence}/></td><td>${t.value}</td><td><${Risks} t=${t}/></td></tr>`)}</tbody></table>`}</div></div>`;
}

function AddTask({d}){
  const [txt,setTxt]=useState(''); const [err,setErr]=useState(''); const [adding,setAdding]=useState(false); const [chips,setChips]=useState([]); const [ut,setUt]=useState([]);
  const loadUt=async()=>{try{const r=await api('/user-tasks');setUt(r.tasks||[])}catch(e){}}; useEffect(()=>{loadUt()},[d.plan&&d.plan.date,d.runs]);
  const add=async()=>{const text=txt.trim(); if(adding)return; setErr(''); if(!text){setErr('Please type a task first');return}
    setAdding(true);try{const r=await post('/user-task',{text});if(!r._ok)setErr(typeof r.detail==='string'?r.detail:(r.detail&&r.detail[0]&&r.detail[0].msg)||('Server error '+r._s));else{setTxt('');setChips(r.preferences||[]);d.notify('Saved to memory • will be planned tonight');loadUt()}}catch(e){setErr('Could not reach the server: '+e.message)}finally{setAdding(false)}};
  return html`<${Card} title="Add a task" cls="soft"><div style=${{display:'flex',gap:8}}><input id="task-input" type="text" style=${{flex:1}} placeholder="book dentist, I prefer mornings" value=${txt} disabled=${adding} onInput=${e=>setTxt(e.target.value)} onKeyDown=${e=>{if(e.key==='Enter')add()}}/><button id="task-add" class="pri" disabled=${adding} onClick=${add}>${adding?'…':'Add'}</button></div>
   ${err?html`<div id="task-error" class="why" style=${{color:'var(--bad)',marginTop:6}}>${err}</div>`:null}
   ${chips.map(c=>html`<span class="chip pri chip-pref" key=${c}>Preference learned: ${c.replace(/^Maya prefers /,'')}</span>`)}
   <div id="your-tasks" style=${{marginTop:8}}><h3>Your tasks</h3>${ut.length?ut.map(u=>html`<div key=${u.id} style=${{padding:'6px 0',borderBottom:'1px solid var(--line)'}}>${u.text}<div class="why">source: ${u.source} · ${u.status}${u.why?' · '+u.why:''}</div></div>`):html`<small>None yet.</small>`}</div></${Card}>`;
}

function Council({d,sel,setSel}){
  const [f,setF]=useState('NOAUTO'); const list=d.tasks.filter(t=>t.action_type!=='work'||t.user_added).filter(t=>f==='ALL'||(f==='NOAUTO'?stateOf(t)!=='AUTO':stateOf(t)===f)).sort((a,b)=>ORDER[stateOf(a)]-ORDER[stateOf(b)]||b.priority-a.priority);
  const t=d.tasks.find(x=>x.id===sel)||list[0]; const c=t&&t.council;
  if(!d.plan)return html`<div class="card"><${Empty} title="No council decisions yet" action=${html`<button class="pri" onClick=${d.run}>Simulate tonight</button>`}>Every task is debated by four specialists and a judge.</${Empty}></div>`;
  return html`<div class="grid" style=${{gridTemplateColumns:'minmax(280px,360px) 1fr',gap:16}}>
   <div><div class="tools"><div class="seg">${[['NOAUTO','Needs review'],['BLOCKED','Blocked'],['VERIFY','Verify'],['ALL','All']].map(([k,l])=>html`<button key=${k} class=${f===k?'on':''} onClick=${()=>setF(k)}>${l}</button>`)}</div></div>
    <div class="card" style=${{padding:0,maxHeight:'70vh',overflow:'auto'}} id="council-list">${list.length?html`<table><tbody>${list.map(x=>html`<tr key=${x.id} class=${'click'+(t&&x.id===t.id?' sel':'')} onClick=${()=>setSel(x.id)}><td style=${{width:84}}><${Badge} s=${stateOf(x)}/></td><td>${x.title}</td></tr>`)}</tbody></table>`:html`<${Empty} title="Nothing here"/>`}</div></div>
   <div id="council-detail">${!t||!c?html`<div class="card"><${Empty} title="Select a task"/></div>`:html`<div class="grid">
    <${Card} title="Problem summary" right=${html`<${Badge} s=${stateOf(t)}/>`}><p style=${{margin:0}}><b>${c.problem}</b></p><div class="why">From ${(t.item||{}).source||'you'} · ${(t.item||{}).author||''} · confidence ${t.confidence.toFixed(2)} · ${t.value} value</div></${Card}>
    <${Card} title="Evidence retrieved by Superlinked" right=${html`<${Chip} c=${c.retrieval} pri=${true}/>`}>${c.evidence.length?c.evidence.map((e,i)=>html`<div key=${i} style=${{padding:'6px 0',borderBottom:'1px solid var(--line)'}}><${Chip} c=${e.kind==='memory'?'memory · '+e.source:e.source}/> ${e.subject} ${e.author?html`<small>— ${e.author}</small>`:null} <small style=${{float:'right'}}>relevance ${e.score}</small></div>`):html`<small>No related items found in memory.</small>`}<div class="why" style=${{marginTop:6}}>Only subjects and senders are shown, never email bodies.</div></${Card}>
    <${Card} title="Specialist opinions"><div class="grid g2e">${c.opinions.map(o=>html`<div class="op" key=${o.agent}><h4>${o.agent} <${Badge} s=${o.vote==='BLOCK'?'BLOCKED':o.vote}>${o.vote}</${Badge}></h4><div class="why"><b>Rules:</b> ${o.reason}</div>${o.model?html`<div class="why" style=${{marginTop:4}}><${Chip} c=${o.model.split('/').pop().split(':')[0]} pri=${true}/> ${o.model_vote?html`<${Badge} s=${o.model_vote==='BLOCK'?'BLOCKED':o.model_vote}>${o.model_vote}</${Badge}>`:html`<small>no answer</small>`} ${o.model_reason}</div>`:null}</div>`)}</div>
      ${c.hive?html`<div class="why" style=${{marginTop:10}}><b>Model consensus:</b> ${c.hive.answered}/${c.hive.total} experts answered · majority ${c.hive.majority||'—'} · ${c.hive.objections} objection(s); ${c.hive.quorum} needed to escalate. The hive can add caution, never remove it.</div>`:html`<div class="why" style=${{marginTop:10}}>Hive not used for this run (hosted models unavailable for this data).</div>`}</${Card}>
    ${c.hive&&c.hive.steps?html`<${Card} title="Hive pipeline — expert models, one small step each" right=${html`<${Chip} c=${(c.hive.ms/1000).toFixed(1)+'s'}/>`}><table id="hive-steps"><tbody>${c.hive.steps.map((x,i)=>html`<tr key=${i}><td style=${{width:28,color:'var(--mut)'}}>${i+1}</td><td style=${{width:120}}><b>${x.step}</b><div class="why">${x.model.split('/').pop().split(':')[0]}</div></td><td>${x.output}</td><td style=${{width:90,textAlign:'right'}}>${x.vote?html`<${Badge} s=${x.vote==='BLOCK'?'BLOCKED':x.vote}>${x.vote}</${Badge}>`:''}</td></tr>`)}</tbody></table>${c.hive.next_step?html`<div class="note" style=${{marginTop:10}}><b>Next step:</b> ${c.hive.next_step}</div>`:null}</${Card}>`:null}
    ${t.suggestion?html`<${Card} title="Suggestion for you" cls="soft"><p style=${{margin:0}}>${t.suggestion}</p><div class="why">Based on your facts (Settings → profile).</div></${Card}>`:null}
    <${Card} title="Debate summary"><p style=${{margin:0}}>${c.debate}</p></${Card}>
    <${Card} title="Final judge decision" cls="soft" right=${html`<${Badge} s=${c.final==='BLOCK'?'BLOCKED':c.final}>${c.final==='BLOCK'?'BLOCKED':c.final}</${Badge}>`}><p style=${{margin:'0 0 6px'}}><b>Why this decision was selected</b></p><p style=${{margin:0}}>${c.why}</p><div class="why" style=${{marginTop:8}}>The judge never relaxes policy: hard rules win, and the council can only make a decision <i>more</i> cautious.</div></${Card}></div>`}</div></div>`;
}

function Actions({d,sim,openTask,confirm}){
  const rows=d.tasks.filter(t=>t.action_type!=='work'&&!t.user_added).sort((a,b)=>ORDER[stateOf(a)]-ORDER[stateOf(b)]);
  const status=t=>{const s=stateOf(t);
    if(s==='BLOCKED')return ['BLOCKED','Blocked — will not run'];if(s==='FAILED')return ['FAILED','Failed — NOT done'];if(t.status==='rejected')return ['N','Rejected'];if(t.status==='undone')return ['N','Undone'];
    if(t.status==='needs_you')return ['ASK','Awaiting your approval'];
    if(t.status==='done'||t.status==='approved')return t.decision==='AUTO'?['SIM',(t.result&&t.result.dry_run)||sim&&!(t.result&&t.result.status==='done')?'Simulated (dry run)':'Simulated in demo sandbox']:(t.result&&t.result.status==='done'&&!t.result.dry_run?['AUTO','Approved — executed']:['SIM','Approved — simulated']);return ['N','Planned']};
  if(!d.plan)return html`<div class="card"><${Empty} title="No proposed actions yet" action=${html`<button class="pri" onClick=${d.run}>Simulate tonight</button>`}/></div>`;
  return html`<div><div class="card soft" style=${{marginBottom:12}}>${d.live?html`<b>AUTO actions are simulated. Actions you approve run for real.</b> <span class="why">Review opens a confirmation form; a real change happens only after you confirm. Payments are always simulated; blocked items can never run.</span>`:html`<b>Nothing here has really executed.</b> <span class="why">${sim?'DRY RUN — every action is a simulation; no external changes will be made.':'Live writes are enabled.'}</span>`}</div>
   <div class="card" style=${{padding:0,overflow:'auto'}}><table id="actions-table"><thead><tr><th>Proposed action</th><th>Target</th><th>State</th><th>Status</th><th></th></tr></thead><tbody>${rows.map(t=>{const [k,l]=status(t);return html`<tr key=${t.id}>
    <td><b>${ACTION[t.action_type]||t.action_type}</b><div><${Simulated} sim=${sim&&!['BLOCKED','FAILED'].includes(stateOf(t))}/></div></td><td class="click" onClick=${()=>openTask(t.id)}>${t.title}<div class="why">${t.result?t.result.why:t.why}</div></td><td><${Badge} s=${stateOf(t)}/></td><td><${Badge} s=${k}>${l}</${Badge}></td>
    <td style=${{whiteSpace:'nowrap'}}>${t.status==='needs_you'?html`<button class="sm pri" onClick=${()=>confirm(t)}>Review…</button> <button class="sm danger" onClick=${()=>post('/reject/'+t.id).then(d.reload)}>Reject</button>`:t.status==='done'&&t.decision==='AUTO'?html`<button class="sm" onClick=${()=>post('/undo/'+t.id).then(d.reload)}>Undo</button>`:null}</td></tr>`})}</tbody></table></div></div>`;
}

function Audit(){
  const [a,e,reload]=useFetch('/audit'); const [tab,setTab]=useState('all'); useEffect(()=>{const i=setInterval(reload,4000);return()=>clearInterval(i)},[]);
  if(e)return html`<${ErrBox} m=${e}/>`; if(!a)return html`<${Loading}/>`;
  const ev=a.events.filter(x=>tab==='all'||(tab==='decisions'&&['PolicyEngine','Council','Persona'].includes(x.source))||(tab==='policy'&&['PolicyEngine','Council'].includes(x.source))||(tab==='retries'&&(x.step==='retry'||x.source==='SREAgent'||x.source==='Firedrill'||x.source==='Chaos'))||(tab==='writes'&&x.source==='Executor')).slice().reverse();
  return html`<div><div class=${'card'+(a.external_writes.count?'':' soft')} style=${{marginBottom:12,display:'flex',gap:12,alignItems:'center',flexWrap:'wrap'}}><${Badge} s=${a.external_writes.count?'BLOCKED':'AUTO'}>EXTERNAL WRITES: ${a.external_writes.count}</${Badge}><span>${a.external_writes.status}</span><span class="why" style=${{marginLeft:'auto'}}>${a.note}</span></div>
   <div class="tools"><div class="seg" id="audit-tabs">${[['all','All events'],['decisions','Decisions'],['policy','Policy checks'],['retries','Retries & SRE'],['writes','External-write status']].map(([k,l])=>html`<button key=${k} class=${tab===k?'on':''} onClick=${()=>setTab(k)}>${l}</button>`)}</div></div>
   <div class="card" style=${{padding:0,overflow:'auto'}}>${ev.length?html`<table id="audit-table"><thead><tr><th>Time</th><th>Source</th><th>Step</th><th>State</th><th>Detail (redacted)</th></tr></thead><tbody>${ev.slice(0,200).map(x=>html`<tr key=${x.seq}><td style=${{whiteSpace:'nowrap'}}>${DT(x.ts)}</td><td><${Chip} c=${x.source} pri=${true}/></td><td>${x.step}</td><td>${x.decision?html`<${Badge} s=${x.decision}/>`:''}</td><td>${x.summary}${x.why?html`<div class="why">${x.why}</div>`:null}</td></tr>`)}</tbody></table>`:html`<${Empty} title="No events in this view"/>`}</div>
   ${tab==='writes'?html`<div class="card" style=${{marginTop:12}}><h2>Actions & service calls</h2>${a.actions.length?html`<pre>${a.actions.map(x=>`${x.simulated?'SIMULATED':'EXECUTED '} ${String(x.decision).padEnd(6)} ${x.status.padEnd(9)} ${x.action.padEnd(22)} ${x.task}`).join('\n')}</pre>`:html`<small>No actions recorded.</small>`}<pre>${a.service_calls.length?a.service_calls.map(c=>`${c.ok?'OK  ':'FAIL'} ${c.service}.${c.op} ${c.error||''}`).join('\n'):'No outside service calls were made.'}</pre></div>`:null}</div>`;
}

function Sources({d}){
  const [s,e,reload]=useFetch('/sources',[d.runs]); if(e)return html`<${ErrBox} m=${e}/>`; if(!s)return html`<${Loading}/>`;
  const sie=s.sie; const live=s.sources.filter(x=>x.mode==='real'), mock=s.sources.filter(x=>x.mode!=='real');
  const card=x=>html`<${Card} key=${x.name} title=${x.name[0].toUpperCase()+x.name.slice(1)} right=${html`<${Badge} s=${x.mode==='real'?'LIVE':'MOCK'}>${x.mode==='real'?'LIVE':'MOCK'}</${Badge}>`}>
    <dl class="kv"><dt>Health</dt><dd><span class=${'dot '+(x.error?'r':x.mode==='real'?'g':'a')}/>${x.health}</dd><dt>Items last run</dt><dd>${x.items_last_ingest}</dd><dt>Access</dt><dd>${x.writable?'read + write (writes simulated)':'read-only'}</dd>${x.mode!=='real'?html`<dt>To go live</dt><dd class="why">needs ${x.credentials_needed.join(', ')}</dd>`:null}</dl>${x.error?html`<${ErrBox} m=${x.error}/>`:null}</${Card}>`;
  return html`<div class="grid"><div class="card soft"><b>LIVE SOURCES:</b> ${live.length?live.map(x=>x.name).join(', '):'none (demo data)'} · <b>MOCK SOURCES:</b> ${mock.map(x=>x.name).join(', ')||'none'}</div>
   <div class="grid g3">${s.sources.map(card)}</div>
   ${s.cognee?html`<${Card} title="Cognee memory" right=${html`<${Badge} s=${s.cognee.enabled?'LIVE':'MOCK'}>${s.cognee.enabled?'REAL':'LOCAL FALLBACK'}</${Badge}>`}><dl class="kv"><dt>Engine</dt><dd>${s.cognee.mode==='cloud'?'Cognee Cloud (tenant-hosted)':'cognee 1.6.10 local engine (LLM: Superlinked Qwen3.8-27B · embeddings: bge-m3 1024d)'}</dd><dt>State</dt><dd>${s.cognee.state}</dd><dt>Docs in graph</dt><dd>${s.cognee.docs}</dd>${s.cognee.last_error?html`<dt>Last error</dt><dd class="why">${s.cognee.last_error}</dd>`:null}</dl></${Card}>`:null}
   <${Card} title="Hosted Superlinked" right=${html`<${Badge} s=${sie.hosted_disabled?'BLOCKED':sie.tier==='hosted'?'AUTO':'N'}>tier: ${sie.tier}</${Badge}>`}>
    <dl class="kv"><dt>API key</dt><dd>${sie.hosted_key_present?'configured (value hidden)':'not set'}</dd><dt>Used for current data</dt><dd>${sie.tier==='hosted'?'yes — demo data only':'no'}</dd><dt>Real-email privacy</dt><dd>Hosted Superlinked is <b>never</b> sent real email unless explicitly allowed (currently off).</dd>
    <dt>Calls this process</dt><dd>${sie.calls.hosted} hosted · ${sie.calls.local} local · ${sie.calls.mock} mock</dd><dt>Credits used</dt><dd>${sie.credits}${sie.balance!=null?' · '+sie.balance.toLocaleString()+' left':''}</dd><dt>Models</dt><dd class="why">GLiNER2.5-Decide (triage) · GLiNER (extract) · Qwen3-Reranker (evidence/priority) · bge-m3 (embeddings) · ${sie.gen_model} (summaries)</dd></dl>${sie.hosted_disabled?html`<${ErrBox} m=${sie.disabled_reason}/>`:null}</${Card}></div>`;
}

function Evals({d}){
  const [st,setSt]=useState(null); const [open,setOpen]=useState({}); const [rd]=useFetch('/readiness?sims=false');
  const poll=async()=>{try{setSt(await api('/firedrill/status'))}catch(e){}}; useEffect(()=>{poll();const i=setInterval(poll,1000);return()=>clearInterval(i)},[]);
  if(!st)return html`<${Loading}/>`; const busy=st.running||st.sre_running; const rows=st.running?st.progress:(st.latest?st.latest.results:[]); const base=st.baseline,last=st.latest,sre=st.sre; const pct=(a,b)=>b?Math.round(100*a/b)+'%':'–';
  return html`<div class="grid">
   <${Card} title="Firedrill scenarios (local harness — maps 1:1 to Firedrill)" right=${html`<${Chip} c=${'config '+st.config}/>`}>
    <div class="tools"><button class="pri" id="run-sims" disabled=${busy} onClick=${()=>post('/firedrill/run?label='+(st.n_runs?'re-run':'baseline'))}>${st.running?'Running '+st.progress.length+'/'+st.total+'…':st.n_runs?'Re-run simulations':'Run simulations'}</button>
     <button disabled=${busy||!st.latest} onClick=${()=>post('/sre/run')}>${st.sre_running?'SRE agent working…':'Run SRE agent'}</button>${st.staged?html`<button class="ok" onClick=${()=>post('/sre/apply').then(poll)}>Apply patches</button>`:null}
     ${st.history.some(h=>h.status==='applied')?html`<button class="danger" onClick=${()=>post('/sre/revert').then(poll)}>Revert last apply</button>`:null}
     <button disabled=${busy} title="Restore the first-cut config to replay the improvement story" onClick=${()=>post('/sre/baseline').then(poll)}>Reset to baseline config</button></div>
    ${base?html`<div class="grid g4"><${Card} cls="kpi soft"><b>${base.pass}/${base.total}</b><span>BEFORE (first run) · ${pct(base.pass,base.total)}</span></${Card}><${Card} cls="kpi soft"><b style=${{color:last.pass>base.pass?'var(--ok)':'inherit'}}>${last.pass}/${last.total}</b><span>LATEST · ${pct(last.pass,last.total)}</span></${Card}>
      <${Card} cls="kpi soft"><b>${sre?sre.pass_before+'→'+sre.pass_after:'–'}</b><span>SRE validated result${sre&&sre.applied?' · applied':''}</span></${Card}><${Card} cls="kpi soft"><b>${sre?sre.kept.length+'/'+sre.rejected.length+'/'+sre.escalated.length:'–'}</b><span>patches kept / rejected / escalated</span></${Card}></div>`:html`<${Empty} title="Not run yet">Runs 15 failure scenarios (outages, 429s, phishing, injection, spoofing, mid-run instructions) through the real pipeline in isolated worlds. Results are measured, not scripted.</${Empty}>`}</${Card}>
   ${rows.length?html`<${Card} title="Scenario results"><table id="scenario-table"><tbody>${rows.map(r=>html`<${React.Fragment} key=${r.id}><tr class="click" onClick=${()=>setOpen({...open,[r.id]:!open[r.id]})}><td style=${{width:90}}><${Badge} s=${r.passed?'AUTO':'BLOCKED'}>${r.passed?'Pass':'Fail'}</${Badge}></td><td><b>${r.id} ${r.name}</b><div class="why">${r.passed?r.description:r.check_results.filter(c=>!c.passed).map(c=>c.desc).join(' · ')}</div></td><td class="why">${r.duration_ms} ms</td></tr>
     ${open[r.id]?html`<tr><td colspan="3" style=${{background:'var(--surface)'}}>${r.check_results.map(c=>html`<div key=${c.id} class="why" style=${{color:c.passed?'var(--ok)':'var(--bad)'}}>${c.passed?'✓':'✗'} <b>${c.desc}</b>${c.passed?null:html` — expected <i>${String(c.expected)}</i>, observed <i>${String(c.observed)}</i> <${Chip} c=${c.category} risk=${true}/>`}</div>`)}
       <details><summary class="why">Effects log (${(r.evidence.effects||[]).length}) — shows retries & recovery</summary><pre>${(r.evidence.effects||[]).map(e=>`${String(e.t).padStart(6)}s ${e.ok?'OK  ':'FAIL'} ${e.service}.${e.op} ${e.deduped?'(deduped) ':''}${e.error||''}`).join('\n')||'(no outside effects)'}</pre></details></td></tr>`:null}</${React.Fragment}>`)}</tbody></table></${Card}>`:null}
   ${sre?html`<${Card} title=${'SRE agent report — '+sre.diagnoser}>${sre.kept.map(k=>html`<div key=${k.id} class="op" style=${{marginBottom:8,borderColor:'var(--ok)'}}><h4><${Badge} s="AUTO">KEPT</${Badge}> ${k.file}</h4><div>${k.rationale}</div><div class="why">fixes ${k.gained.join(', ')} · no regressions · ${k.pass_before}→${k.pass_after} passing</div><pre>${k.diff}</pre></div>`)}
     ${sre.rejected.map(k=>html`<div key=${k.id} class="op" style=${{marginBottom:8,borderColor:'var(--bad)'}}><h4><${Badge} s="BLOCKED">REJECTED</${Badge}> ${k.file}</h4><div class="why">${k.reason}</div></div>`)}
     <h3>Diagnoses</h3>${sre.diagnoses.map((x,i)=>html`<div key=${i} style=${{padding:'6px 0',borderBottom:'1px solid var(--line)'}}><${Chip} c=${x.category} risk=${true}/><b>${x.scenario_id} ${x.scenario}</b><div class="why">${x.explanation||x.root_cause}${x.explained_by?html` <${Chip} c=${'explained by '+x.explained_by} pri=${true}/>`:null}</div>${x.escalate?html`<div class="why" style=${{color:'var(--warn)'}}>⚠ Escalated (needs a code change): ${x.escalate}</div>`:null}</div>`)}</${Card}>`:null}
   <${Card} title="Automated tests">${rd&&rd.tests.known?html`<span class=${'dot '+(rd.tests.failed?'r':'g')}/><b>${rd.tests.collected-rd.tests.failed}/${rd.tests.collected} passed</b> <span class="why">last run ${rd.tests.age_min} min ago · run <code>make test</code></span>`:html`<span class="why">Run <code>make test</code> to record results.</span>`}</${Card}></div>`;
}

function Settings(){
  const [s,e]=useFetch('/settings'); const [rd]=useFetch('/readiness?sims=false'); if(e)return html`<${ErrBox} m=${e}/>`; if(!s)return html`<${Loading}/>`;
  return html`<div class="grid g2e">
   <${Card} title="Write safety" right=${html`<${Badge} s=${s.dry_run?'SIM':'BLOCKED'}>${s.dry_run?'DRY RUN ON':'LIVE WRITES'}</${Badge}>`}><p style=${{marginTop:0}}><b>${s.write_policy}</b></p><p class="why">Dry-run is enforced in the executor: real connectors are never called for writes, every proposed action is recorded as SIMULATED, and payments are always simulated. It is set in the server environment and cannot be changed from this page.</p></${Card}>
   <${Card} title="Hosted Superlinked privacy"><p style=${{marginTop:0}}>Real email content to hosted Superlinked: <${Badge} s=${s.hosted_superlinked_for_real_data?'BLOCKED':'AUTO'}>${s.hosted_superlinked_for_real_data?'ALLOWED':'NOT ALLOWED'}</${Badge}></p><p class="why">Demo data may use the hosted models. When real Gmail/Calendar is live, triage falls back to local/mock models so your messages never leave this machine.</p></${Card}>
   <${Card} title="Approval requirements"><ul style=${{margin:0,paddingLeft:18}}>${s.approval_requirements.map((x,i)=>html`<li key=${i} style=${{marginBottom:4}}>${x}</li>`)}</ul></${Card}>
   <${Card} title="Policy rules"><dl class="kv"><dt>Hard blocks</dt><dd>${s.hard_blocks.map(f=>html`<${Chip} key=${f} c=${f} risk=${true}/>`)}</dd><dt>Always ask</dt><dd>${s.ask_flags.map(f=>html`<${Chip} key=${f} c=${f}/>`)}</dd><dt>Identity step-up</dt><dd>${s.verify_flags.map(f=>html`<${Chip} key=${f} c=${f}/>`)}</dd><dt>Retry policy</dt><dd>${s.retry.max_attempts} attempts · backoff ${s.retry.backoff_s}s ×${s.retry.backoff_factor}</dd></dl></${Card}>
   <${Card} title="Configuration status (values never shown)"><table><tbody>${Object.entries(s.configuration).map(([k,v])=>html`<tr key=${k}><td>${k}</td><td style=${{textAlign:'right'}}><${Badge} s=${v?'AUTO':'N'}>${v?'configured':'not set'}</${Badge}></td></tr>`)}</tbody></table><div class="why" style=${{marginTop:6}}>${s.note}</div></${Card}>
   <${Card} title="Readiness checks">${rd?html`<dl class="kv"><dt>Overall</dt><dd><${Badge} s=${rd.ready?'AUTO':'BLOCKED'}>${rd.ready?'READY':'NOT READY'}</${Badge}></dd><dt>Secrets in git</dt><dd>${rd.secrets_scan.clean?'none found':'FOUND: '+rd.secrets_scan.files_with_secrets.join(', ')}</dd><dt>Missing optional</dt><dd>${rd.missing_optional_integrations.map(x=>html`<${Chip} key=${x} c=${x.replace(/_/g,' ')}/>`)}</dd><dt>Firedrill CLI</dt><dd>${rd.firedrill_cli.skipped?'—':rd.firedrill_cli.signed_in?'signed in':'installed, not signed in'}</dd></dl>`:html`<${Loading}/>`}</${Card}></div>`;
}

/* ---------- reminders (in-app only) ---------- */
const URG={overdue:['BLOCKED','Overdue'],soon:['ASK','Due soon'],today:['N','Today'],upcoming:['N','Upcoming']};
const KIND_L={verify:'Verify',approve:'Approve',work:'Focus work','follow-up':'Follow-up',failed:'Failed'};
function ReminderList({rs,reload,openTask,limit}){
  if(!rs)return html`<${Loading}/>`; if(!rs.length)return html`<${Empty} title="You're all caught up">Nothing needs you right now.</${Empty}>`;
  return html`<div id="reminder-list">${rs.slice(0,limit||99).map(r=>html`<div key=${r.id} style=${{display:'flex',gap:10,alignItems:'flex-start',padding:'9px 0',borderBottom:'1px solid var(--line)'}}>
    <div style=${{flex:1,minWidth:0}}><div><${Badge} s=${URG[r.urgency][0]}>${URG[r.urgency][1]}</${Badge}> <${Chip} c=${KIND_L[r.kind]}/> <small>${T(r.due)}</small></div>
     <div class="click" style=${{fontWeight:500,marginTop:3,cursor:'pointer'}} onClick=${()=>openTask(r.task_id)}>${r.title}</div><div class="why">${r.what}${r.suggestion?' · '+r.suggestion:''}</div></div>
    <div style=${{display:'flex',gap:4,flex:'none'}}><button class="sm" onClick=${()=>post('/reminders/'+r.id+'/snooze?minutes=60').then(reload)}>Snooze 1h</button><button class="sm" onClick=${()=>post('/reminders/'+r.id+'/done').then(reload)}>Done</button></div></div>`)}</div>`;
}

/* ---------- app shell ---------- */
const IC={overview:'M3 3h7v7H3zM14 3h7v4h-7zM14 11h7v10h-7zM3 14h7v7H3z',tasks:'M4 4h16v16H4zM4 9h16M9 14h6',council:'M12 3v18M5 7h14M5 7l-3 7a4 4 0 0 0 6 0zM19 7l-3 7a4 4 0 0 0 6 0z',actions:'M5 12h14M13 6l6 6-6 6',audit:'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',sources:'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',evals:'M9 12l2 2 4-4M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z',settings:'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',bolt:'M13 2L4 14h7l-1 8 9-12h-7z',bell:'M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8M10 21h4',play:'M6 4l14 8-14 8z'};
const Icon=({n})=>html`<svg class="i" viewBox="0 0 24 24"><path d=${IC[n]}/></svg>`;
const NAV=[['overview','Overview','overview'],['tasks','Inbox / Tasks','tasks'],['council','Council Decisions','council'],['actions','Actions','actions'],['audit','Audit Log','audit'],['sources','Sources','sources'],['evals','Evaluations','evals'],['settings','Settings / Safety','settings']];
const TITLES={overview:['Overview','What Overnight did while you slept'],tasks:['Inbox / Tasks','Every item turned into a scored, explainable task'],council:['Council Decisions','Evidence, specialist opinions, debate and the judge’s decision'],actions:['Actions','Proposed actions — nothing has really executed'],audit:['Audit Log','Redacted history of decisions, policy checks, retries and writes'],sources:['Sources','LIVE vs MOCK connections and hosted-model status'],evals:['Evaluations','Firedrill scenarios, SRE improvements and test status'],settings:['Settings / Safety','Safety guarantees and configuration (no secrets shown)']};

function App(){
  const parse=()=>{const h=location.hash.replace(/^#\/?/,'');const [r,q]=h.split('?');return {route:NAV.some(n=>n[0]===r)?r:'overview',q:new URLSearchParams(q||'')}};
  const [loc,setLoc]=useState(parse()); const go=(r,q)=>{location.hash='#/'+r+(q?'?'+q:'')}; useEffect(()=>{const f=()=>{setLoc(parse());setOpen(false)};addEventListener('hashchange',f);return()=>removeEventListener('hashchange',f)},[]);
  const [health,setH]=useState(null); const [plan,setPlan]=useState(null); const [brief,setBrief]=useState(null); const [metrics,setM]=useState({}); const [events,setEv]=useState([]); const [running,setRun]=useState(false);
  const [loadErr,setLoadErr]=useState(''); const [toast,setToast]=useState(''); const [sel,setSel]=useState(null); const [drawer,setDrawer]=useState(null); const [conf,setConf]=useState(null); const [open,setOpen]=useState(false); const [runs,setRuns]=useState(0);
  const notify=m=>{setToast(m);setTimeout(()=>setToast(''),3500)};
  const [rem,setRem]=useState(null); const [bell,setBell]=useState(false); const loadRem=async()=>{try{const j=await api('/reminders');setRem(j.reminders||[])}catch(e){}};
  useEffect(()=>{loadRem();const i=setInterval(loadRem,30000);return()=>clearInterval(i)},[]);
  const load=async()=>{try{const [p,h]=await Promise.all([api('/plan'),api('/health')]);if(!h._ok)throw new Error('health '+h._s);setH(h);setPlan(p.plan);setBrief(p.brief);setM(p.metrics||{});setRun(!!p.running);setLoadErr('')}catch(e){setLoadErr('Cannot reach the Overnight server: '+e.message)}};
  useEffect(()=>{load();const es=new EventSource('/events');es.onmessage=e=>{const ev=JSON.parse(e.data);setEv(x=>[...x.slice(-299),ev]);if(['run_complete','ingest','preference'].includes(ev.step)){load();loadRem();setRuns(n=>n+1)}if(ev.step==='reminder_due'){notify('Reminder — '+ev.summary)}if(ev.step==='start')setRun(true);if(ev.step==='run_complete')setRun(false)};return()=>es.close()},[]);
  const run=(chaos)=>{setEv([]);post('/run-night'+(chaos?'?chaos='+chaos:''))};
  const tasks=plan?plan.tasks:[]; const sim=!health||health.dry_run!==false; const live=(health&&health.live_sources)||[]; const mock=health?health.connectors.filter(c=>c.mode!=='real').map(c=>c.name):[];
  const d={plan,tasks,brief,metrics,events,run,reload:load,notify,runs,rem,loadRem,live:!!(health&&health.approved_actions_live),openTask:id=>setDrawer(id)}; const [title,sub]=TITLES[loc.route]; const cnt=s=>tasks.filter(t=>stateOf(t)===s&&t.action_type!=='work').length;
  const openTask=id=>setDrawer(id); const drawerTask=drawer&&tasks.find(t=>t.id===drawer);
  if(loadErr&&!health)return html`<div style=${{padding:40}}><${ErrBox} m=${loadErr}/><p><button class="pri" onClick=${load}>Retry</button></p></div>`;
  const page={overview:()=>html`<${Overview} d=${d} go=${go}/>`,tasks:()=>html`<${Tasks} d=${d} sim=${sim} openTask=${openTask}/>`,council:()=>html`<${Council} d=${d} sel=${sel||loc.q.get('task')} setSel=${setSel}/>`,actions:()=>html`<${Actions} d=${d} sim=${sim} openTask=${openTask} confirm=${setConf}/>`,audit:()=>html`<${Audit}/>`,sources:()=>html`<${Sources} d=${d}/>`,evals:()=>html`<${Evals} d=${d}/>`,settings:()=>html`<${Settings}/>`}[loc.route];
  return html`<div id="shell">
   <aside class=${'side'+(open?' open':'')} id="sidebar"><div class="brand"><i>O</i>Overnight</div>
    <nav class="nav">${NAV.map(([k,l,ic])=>html`<a key=${k} href=${'#/'+k} class=${loc.route===k?'on':''} data-nav=${k}><${Icon} n=${ic}/>${l}${k==='tasks'&&tasks.length?html`<span class="ct">${tasks.length}</span>`:k==='council'&&cnt('BLOCKED')+cnt('VERIFY')+cnt('ASK')?html`<span class="ct">${cnt('BLOCKED')+cnt('VERIFY')+cnt('ASK')}</span>`:null}</a>`)}</nav>
    <div class="foot">Plans tomorrow while you sleep.<br/>Dry-run · redacted logs · no secrets</div></aside>
   <div class="main"><header class="top"><button class="menu" onClick=${()=>setOpen(!open)}>☰</button><div class="ttl"><h1 id="page-title">${title}</h1><div class="sub">${sub}</div></div>
     <span style=${{position:'relative'}}><button id="bell" title="Reminders" onClick=${()=>setBell(!bell)}><${Icon} n="bell"/>${rem&&rem.length?html`<span class="badge b-ASK" id="bell-count" style=${{padding:'0 6px'}}>${rem.length}</span>`:null}</button>
      ${bell?html`<div class="card" id="bell-panel" style=${{position:'absolute',right:0,top:40,width:'min(460px,92vw)',zIndex:20,boxShadow:'0 12px 32px #0000001f',maxHeight:'70vh',overflow:'auto'}}><div style=${{display:'flex',alignItems:'center',marginBottom:6}}><h2 style=${{margin:0,flex:1}}>Needs you</h2><small>in-app reminders only</small></div><${ReminderList} rs=${rem} reload=${loadRem} openTask=${id=>{setBell(false);openTask(id)}}/></div>`:null}</span>
     <button class="pri" id="run-night" disabled=${running} onClick=${()=>run()}><${Icon} n="play"/>${running?'Running…':'Simulate tonight'}</button>${live.length?null:html`<button disabled=${running} title="Inject a calendar outage and watch retries recover" onClick=${()=>run('calendar_blip')}><${Icon} n="bolt"/>With outage</button>`}</header>
    <div class="strip" id="mode-strip">${sim&&health&&health.approved_actions_live?html`<span class="mode">AUTO actions: DRY RUN — no changes. Approved actions: run for real after your confirmation.</span>`:sim?html`<span class="mode">DRY RUN — No external changes will be made.</span>`:html`<span class="mode" style=${{color:'var(--bad)'}}>LIVE WRITES ENABLED</span>`}
      <span class="src"><b>LIVE SOURCES</b>${live.length?live.map(x=>html`<span key=${x} class="badge b-LIVE">${x}</span>`):html`<small>none</small>`}</span><span class="src"><b>MOCK SOURCES</b>${mock.length?mock.map(x=>html`<span key=${x} class="badge b-MOCK">${x}</span>`):html`<small>none</small>`}</span>
      ${health&&Object.keys(health.source_errors||{}).length?html`<span class="badge b-BLOCKED">Degraded: ${Object.keys(health.source_errors).join(', ')}</span>`:null}</div>
    <main class="page" id="page">${page()}</main></div>
   ${drawerTask?html`<${Drawer} t=${drawerTask} sim=${sim} onClose=${()=>setDrawer(null)} goCouncil=${()=>{setSel(drawerTask.id);setDrawer(null);go('council','task='+drawerTask.id)}} onApprove=${()=>{setConf(drawerTask);setDrawer(null)}} onReject=${()=>{post('/reject/'+drawerTask.id).then(load);setDrawer(null)}}/>`:null}
   ${conf?html`<${ConfirmModal} task=${conf} sim=${sim} live=${!!(health&&health.approved_actions_live)} notify=${notify} onClose=${()=>setConf(null)} onDone=${()=>{setConf(null);load()}}/>`:null}
   ${toast?html`<div id="toast" class="toast">${toast}</div>`:null}</div>`;
}
ReactDOM.createRoot(document.getElementById('app')).render(html`<${App}/>`);
