const {chromium}=require('playwright-core');
const path=require('path'),fs=require('fs');
const artifacts=path.resolve(process.env.BOSE_ARTIFACTS||path.join(__dirname,'../artifacts'));fs.mkdirSync(artifacts,{recursive:true});
const web=path.resolve(__dirname,'../web'),fonts=path.join(web,'fonts');
const contract=JSON.parse(fs.readFileSync(path.join(__dirname,'switch-contract.json'),'utf8')),M=contract.messages;
const shot=(page,name,full=true)=>page.screenshot({path:path.join(artifacts,name),fullPage:full});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function check(ok,text){if(!ok)throw Error(text);}

// Synthetic devices only (public repo).
const DEV={pc:{address:'AA:AA:AA:AA:AA:AA',name:'Desktop PC'},mac:{address:'BB:BB:BB:BB:BB:BB',name:'MacBook Pro'},phone:{address:'CC:CC:CC:CC:CC:CC',name:'Android phone'},tv:{address:'DD:DD:DD:DD:DD:DD',name:'Living room TV'}};
const roles={pc:DEV.pc.address,mac:DEV.mac.address,phone:DEV.phone.address};
function overview(connected,noise={level:7,enabled:true},extra={}){
 return {here:'pc',reachable:true,cached:false,observed:Math.floor(Date.now()/1000),battery:81,noise,roles,
  devices:[DEV.pc,DEV.phone,DEV.mac,DEV.tv].map(d=>({...d,connected:connected.includes(d.address),current:d===DEV.pc})),
  controllers:[{controller:'pc',reachable:true},{controller:'phone',reachable:true},{controller:'mac',reachable:false,checking:true}],...extra};
}

(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 // Optional: SCREENSHOT_SCALE=2 renders every page at 2x for README images.
 const scale=Number(process.env.SCREENSHOT_SCALE)||1;
 if(scale!==1){const np=browser.newPage.bind(browser);browser.newPage=(o={})=>np({deviceScaleFactor:scale,...o});}
 const page=await browser.newPage({viewport:{width:1280,height:950}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let cur=null,overviewCalls=0,overrideHandler=null,switchHandler=null,switchReplied=0;const posts=[],switchPosts=[];
 // GET /api/state: null = an older controller (404), so the page keeps its overview polling; else a scripted long-poll.
 let states=null;const stateGets=[],cancels=[];
 // Every page gets the same fixture API; nothing reaches a live controller.
 const wire=async page=>{
  // Without BOSE_URL the page itself comes from this checkout's web/, so no running helper is needed.
  if(!process.env.BOSE_URL)await page.route(u=>!new URL(u).pathname.startsWith('/api/'),r=>{const p=new URL(r.request().url()).pathname,f=path.join(web,p==='/'?'index.html':p);const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'};return f.startsWith(web)&&fs.existsSync(f)&&fs.statSync(f).isFile()?r.fulfill({body:fs.readFileSync(f),contentType:types[path.extname(f)]||'application/octet-stream'}):r.fulfill({status:404,body:''});});
  await page.route('**/fonts/*.woff2',r=>{const f=path.join(fonts,path.basename(new URL(r.request().url()).pathname));return fs.existsSync(f)?r.fulfill({body:fs.readFileSync(f),contentType:'font/woff2'}):r.fulfill({status:404,body:''});});
  await page.route('**/api/cached',r=>r.fulfill({json:{devices:[]}}));
  await page.route('**/api/overview',r=>{overviewCalls++;return r.fulfill({json:cur});});
  await page.route('**/api/override',async r=>{const body=r.request().postDataJSON();posts.push({body,at:Date.now()});const res=await overrideHandler(body);return r.fulfill({json:res});});
  await page.route(u=>new URL(u).pathname==='/api/state',async r=>{
   if(!states)return r.fulfill({status:404,body:'not found'});
   const q=new URL(r.request().url()).searchParams;const after=q.has('after')?Number(q.get('after')):null;stateGets.push({after,wait:q.get('wait')});
   if(after!=null&&states.snap.seq<=after)await states.next(Math.min(Number(q.get('wait'))||0,25)*1000);
   try{await r.fulfill({json:{...states.snap,now:Date.now()/1000}});}catch(e){}
  });
  await page.route('**/api/switch/cancel',async r=>{cancels.push(r.request().postDataJSON());if(states?.onCancel)states.onCancel();return r.fulfill({json:{ok:true}});});
  await page.route('**/api/switch',async r=>{const body=r.request().postDataJSON();switchPosts.push({body,at:Date.now()});const res=await switchHandler(body);switchReplied=Date.now();return r.fulfill({json:res});});
 };
 await wire(page);
 const ready=(p=page)=>p.evaluate(()=>document.fonts.ready.then(()=>new Promise(r=>setTimeout(r,400))));
 // No ridge pixel may sit in the caption row of the band.
 const ridgesClear=(p=page)=>p.evaluate(()=>{const c=document.querySelector('#ridges'),cap=document.querySelector('.plot .cap');const rows=Math.ceil((cap.offsetTop+cap.offsetHeight)*c.height/c.clientHeight);const d=c.getContext('2d').getImageData(0,0,c.width,rows).data;for(let i=3;i<d.length;i+=4)if(d[i]>8)return false;return true;});
 // The status line under the title stays on one line, at least 12px above the band caption.
 const headerFits=async(label,p=page)=>{const m=await p.evaluate(()=>{const sub=document.querySelector('.sub'),cap=document.querySelector('.plot .cap span');const lh=parseFloat(getComputedStyle(sub).lineHeight);return {lines:sub.offsetHeight/lh,gap:cap.getBoundingClientRect().top-sub.getBoundingClientRect().bottom,text:sub.textContent};});check(m.lines<1.5&&m.gap>=12,`Header status (${label}) must be one line ≥12px above the caption: ${JSON.stringify(m)}`);};
 const scheme=async(colorScheme)=>{await page.emulateMedia({colorScheme});await ready();};

 // Offline headset
 cur={here:'pc',reachable:false,battery:null,roles:{},devices:[],controllers:[]};
 await page.goto(process.env.BOSE_URL||'http://127.0.0.1:8847');
 await page.getByText('Headset unavailable',{exact:true}).waitFor({timeout:20000});
 await ready();await shot(page,'desktop-offline.png');
 check(!await page.locator('#slot-count').isVisible(),'Slot count must hide when the headset is unknown');
 await page.setViewportSize({width:390,height:844});await ready();await shot(page,'phone-offline.png');
 check(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),'Mobile horizontal overflow (offline)');

 // Live check found no controller that reaches the headset: last-known slots, reasons per controller
 cur={...overview([DEV.phone.address]),reachable:false,cached:true,checked:Date.now()/1000,observed:Math.floor(Date.now()/1000)-3*3600,
  controllers:[{controller:'pc',reachable:false,link:false,error:'Headset is not connected to this PC'},{controller:'phone',reachable:false,error:'Controller unavailable: ConnectionRefusedError'},{controller:'mac',reachable:false,error:'Controller unavailable: TimeoutError'}]};
 await page.setViewportSize({width:390,height:844});await page.reload();
 await page.getByText('Not reachable · last known',{exact:false}).waitFor();await ready();
 check(!await page.locator('#slot-count').isVisible(),'Slot count must hide when no controller reaches the headset');
 check((await page.locator('#controllers').textContent())==='Controllers: PC not connected · Phone app not running · Mac no answer','Controller reasons: '+await page.locator('#controllers').textContent());
 check(await page.getByText('No controller can reach the headset right now',{exact:false}).isVisible(),'Unreachable explanation missing');
 check(await page.locator('.cup.unknown',{hasText:'Not known'}).count()===1,'Open slot must read unknown after a failed live check');
 check(await page.locator('#devices button:not([disabled])').count()===0,'Last-known state must not offer actions');
 await shot(page,'phone-unreachable.png');
 await page.setViewportSize({width:1280,height:950});

 // Two slots full, light + dark, phone + desktop
 const both=[DEV.pc.address,DEV.phone.address];
 cur=overview(both);await page.reload();
 await page.locator('.cup',{hasText:'Desktop PC'}).waitFor();await page.getByText('Live · just now').waitFor();
 check(await page.locator('.cup').count()===2,'Two slot cups expected');
 check(!await page.locator('#noise-controls').isHidden(),'Noise controls missing');
 check(await page.locator('#noise-level').inputValue()==='7','Noise level mismatch');
 check(await page.locator('#noise-enabled').isChecked(),'ANC switch should be on');
 check(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),'Mobile horizontal overflow (connected)');
 check((await page.locator('#slot-count').textContent())==='2 of 2 connected','Header should count occupied slots');
 await headerFits('live 390');await page.setViewportSize({width:360,height:800});await headerFits('live 360');await page.setViewportSize({width:390,height:844});
 await ready();await shot(page,'phone-light.png');
 await page.emulateMedia({colorScheme:'dark'});await ready();await shot(page,'phone-dark.png');
 await page.setViewportSize({width:1280,height:900});await ready();await shot(page,'desktop-dark.png');
 await page.emulateMedia({colorScheme:'light'});await ready();await shot(page,'desktop-light.png');
 check(await page.evaluate(()=>{const a=document.querySelector('.col-main').getBoundingClientRect(),b=document.querySelector('.col-side').getBoundingClientRect();return b.left>=a.right&&a.width>300;}),'Desktop should use two columns');
 check(await page.evaluate(()=>{const p=document.querySelector('#plot').getBoundingClientRect(),a=document.querySelector('.col-main').getBoundingClientRect(),b=document.querySelector('.col-side').getBoundingClientRect();return p.left<=a.left+1&&p.right>=b.right-1&&p.height>=180&&Math.abs(a.top-b.top)<2&&p.bottom<=a.top;}),'Desktop ridge band should span both columns above them, tops aligned');
 check(await page.evaluate(()=>{const s=document.querySelector('.shell'),last=Math.max(document.querySelector('.col-main').getBoundingClientRect().bottom,document.querySelector('.col-side').getBoundingClientRect().bottom);const top=document.querySelector('.top').getBoundingClientRect().top;return innerHeight-last<top+120&&s.scrollHeight<=innerHeight+1;}),'Desktop content should be vertically balanced');
 await page.setViewportSize({width:390,height:844});

 // Slider: rapid input events, one request on release, rendered from the response state
 overrideHandler=async b=>{await sleep(400);cur=overview(both,{level:b.level,enabled:b.enabled});return {ok:true,verified:true,message:'Noise cancellation updated',state:cur};};
 let calls=overviewCalls;posts.length=0;
 await page.locator('#noise-level').evaluate(el=>{for(const v of [6,5,4,3]){el.value=String(v);el.dispatchEvent(new Event('input',{bubbles:true}));}el.dispatchEvent(new Event('change',{bubbles:true}));});
 await page.getByText('Setting level 3…').waitFor({timeout:300});
 await page.getByText('Noise cancellation updated',{exact:true}).waitFor();
 check(posts.length===1&&JSON.stringify(posts[0].body)===JSON.stringify({action:'noise',level:3,enabled:true}),'Slider release must send exactly one request: '+JSON.stringify(posts.map(p=>p.body)));
 check(overviewCalls===calls,'Must render from the override state, not call /api/overview again');
 check((await page.locator('#noise-current').textContent())==='On · level 3 of 10','Noise line did not settle');

 // Coalescing: releases during a write queue only the latest value, ≥250 ms apart
 posts.length=0;
 await page.locator('#noise-level').evaluate(async el=>{const rel=v=>{el.value=String(v);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));};rel(5);await new Promise(r=>setTimeout(r,60));rel(6);await new Promise(r=>setTimeout(r,60));rel(8);});
 await page.waitForFunction(()=>document.querySelector('#noise-current').textContent==='On · level 8 of 10',null,{timeout:5000});
 check(JSON.stringify(posts.map(p=>p.body.level))==='[5,8]','Stale level must be dropped: '+JSON.stringify(posts.map(p=>p.body.level)));
 check(posts[1].at-posts[0].at>=250,'ANC writes must start ≥250 ms apart');

 // Noise response with an empty device list: merge noise/battery only, keep the cups
 overrideHandler=async b=>{await sleep(100);cur=overview(both,{level:b.level,enabled:b.enabled});return {ok:true,verified:true,message:'Noise cancellation updated',state:{...cur,battery:77,devices:[],controllers:[]}};};
 await page.locator('#noise-level').evaluate(el=>{el.value='9';el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));});
 await page.waitForFunction(()=>document.querySelector('#noise-current').textContent==='On · level 9 of 10');
 check((await page.locator('#battery').textContent())==='77%','Battery from a noise response should merge');
 check(await page.locator('.cup',{hasText:'Desktop PC'}).count()===1&&await page.locator('.device',{hasText:'MacBook Pro'}).count()===1,'Empty devices in a noise response must not wipe devices');
 overrideHandler=async b=>{await sleep(400);cur=overview(both,{level:b.level,enabled:b.enabled});return {ok:true,verified:true,message:'Noise cancellation updated',state:cur};};
 await page.locator('#noise-level').evaluate(el=>{el.value='8';el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));});
 await page.waitForFunction(()=>document.querySelector('#noise-current').textContent==='On · level 8 of 10');
 await sleep(300);

 // ANC switch off
 posts.length=0;calls=overviewCalls;
 await page.locator('#noise-enabled').click();
 await page.getByText('Noise cancellation updated',{exact:true}).waitFor();
 await page.waitForFunction(()=>document.querySelector('#noise-current').textContent.startsWith('Off'));
 check(JSON.stringify(posts[0].body)===JSON.stringify({action:'noise',level:8,enabled:false}),'Incorrect ANC off payload '+JSON.stringify(posts[0]?.body));
 check(await page.locator('#noise-level').isDisabled(),'Slider must be disabled while ANC is off');
 check(overviewCalls===calls,'ANC switch should render from state');
 await ready();check(await ridgesClear(),'ANC-off ridges climb into the caption (phone light)');await shot(page,'phone-anc-off-light.png');
 await scheme('dark');check(await ridgesClear(),'ANC-off ridges climb into the caption (phone dark)');await shot(page,'phone-anc-off-dark.png');
 await page.setViewportSize({width:1280,height:900});await ready();check(await ridgesClear(),'ANC-off ridges climb into the caption (desktop dark)');
 await scheme('light');check(await ridgesClear(),'ANC-off ridges climb into the caption (desktop light)');
 await page.setViewportSize({width:390,height:844});await ready();
 await page.locator('#noise-enabled').click();await page.waitForFunction(()=>document.querySelector('#noise-current').textContent==='On · level 8 of 10');

 // Disconnect: pending immediately, then render from state
 overrideHandler=async b=>{await sleep(600);cur=overview([DEV.pc.address],cur.noise);return {ok:true,verified:true,message:'Android phone disconnected',state:cur};};
 calls=overviewCalls;
 await page.getByRole('button',{name:'Disconnect Android phone'}).click();
 await page.locator('.cup.pending .pill.pending',{hasText:'Disconnecting…'}).waitFor({timeout:200});
 await page.getByText('Android phone disconnected').waitFor();
 check(await page.locator('.cup.open',{hasText:'Open slot'}).count()===1,'Freed slot should show Open slot');
 check(overviewCalls===calls,'Disconnect should render from state');

 // Connect into the open slot: pending cup shown at once
 overrideHandler=async b=>{await sleep(900);cur=overview([DEV.pc.address,DEV.mac.address],cur.noise);return {ok:true,verified:true,message:'MacBook Pro connected',state:cur};};
 await page.getByRole('button',{name:'Connect MacBook Pro'}).click();
 await page.locator('.cup.pending .pill.pending',{hasText:'Connecting…'}).waitFor({timeout:200});
 check(await page.locator('.device',{hasText:'MacBook Pro'}).count()===0,'A device pending in a cup must leave the saved list');
 check(await page.locator('[data-live="true"]:enabled').count()===0,'Other mutations must be disabled while one runs');
 await shot(page,'phone-pending.png');
 await page.getByText('MacBook Pro connected').waitFor();
 check((await page.locator('.cup').nth(1).textContent()).includes('MacBook Pro'),'MacBook Pro should take slot 2');

 // Failure reverts to the last confirmed state; a response without state falls back to one overview read
 overrideHandler=async()=>{await sleep(200);return {ok:false,verified:false,message:'The headset didn’t confirm the disconnect.'};};
 await page.getByRole('button',{name:'Disconnect MacBook Pro'}).click();
 await page.getByText('The headset didn’t confirm the disconnect.').waitFor();
 check(await page.getByRole('button',{name:'Disconnect MacBook Pro'}).isEnabled(),'Failed disconnect must revert');

 // Both full: Connect turns the cups into Replace targets
 posts.length=0;
 await page.getByRole('button',{name:'Connect Android phone'}).click();
 await page.getByRole('button',{name:'Replace MacBook Pro'}).waitFor();
 check(await page.getByRole('button',{name:/^Replace /}).count()===2,'Both cups should be replace targets');
 check(await page.evaluate(()=>document.querySelector('#choose').getBoundingClientRect().bottom<=document.querySelector('#cups').getBoundingClientRect().top),'Replace prompt should sit above the cups');
 await shot(page,'phone-replace.png');
 await page.getByRole('button',{name:'Cancel',exact:true}).click();
 check(await page.getByRole('button',{name:/^Replace /}).count()===0,'Cancel should restore the cups');
 overrideHandler=async b=>{await sleep(300);cur=overview([DEV.pc.address,DEV.phone.address],cur.noise);return {ok:true,verified:true,message:'Android phone connected'};};
 calls=overviewCalls;
 await page.getByRole('button',{name:'Connect Android phone'}).click();
 await page.getByRole('button',{name:'Replace MacBook Pro'}).click();
 await page.locator('.cup.pending',{hasText:'Replacing MacBook Pro'}).waitFor({timeout:200});
 await page.getByText('Android phone connected').waitFor();
 check(JSON.stringify(posts[0].body)===JSON.stringify({action:'connect',address:DEV.phone.address,replace:DEV.mac.address}),'Incorrect replace payload '+JSON.stringify(posts[0]?.body));
 check(overviewCalls===calls+1,'Response without state should fall back to exactly one overview call');
 check((await page.locator('.cup').nth(1).textContent()).includes('Android phone'),'Replacement should land in the replaced slot');

 // Settings dialog
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.getByText('Controller settings',{exact:true}).waitFor();
 check(await page.locator('#role-fields select').count()===3,'Role selectors missing');
 await shot(page,'phone-settings.png',false);
 await page.getByRole('button',{name:'Close',exact:true}).click();

 // Cached state is read-only
 cur={...overview(both),reachable:false,cached:true,observed:Math.floor(Date.now()/1000)-3600,controllers:[]};
 await page.reload();await page.getByText(/^last known /).waitFor();
 await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
 check(await page.locator('.cup').count()===2,'Cups must show in cached state');
 check(await page.locator('[data-live="true"]:enabled').count()===0,'Cached connections must not enable mutations');
 check(await page.locator('#noise-slider.off').count()===1,'Cached ANC slider should be dimmed');
 check((await page.locator('#headset-status').textContent()).startsWith('last known ')&&(await page.locator('#slot-count').textContent())==='2 of 2','Cached header should read "2 of 2 · last known <time>"');
 await headerFits('cached 390');await page.setViewportSize({width:360,height:800});await headerFits('cached 360');await page.setViewportSize({width:390,height:844});
 await ready();await shot(page,'phone-cached.png');

 // The controller serving the page reads the headset live, so it is "here" even if its own list lags
 const base=process.env.BOSE_URL||'http://127.0.0.1:8847';
 for(const [label,controllers] of [['missing',[{controller:'pc',reachable:true}]],['checking',[{controller:'pc',reachable:true},{controller:'phone',checking:true}]],['checking unreachable',[{controller:'pc',reachable:true},{controller:'phone',reachable:false,checking:true}]]]){
  cur=overview(both,undefined,{here:'phone',controllers});await page.reload();await page.getByText('Live · just now').waitFor();
  const foot=await page.locator('#controllers').textContent();
  check(foot.includes('Phone here')&&!foot.includes('Phone checking'),`Here controller (${label}) should read "Phone here": ${foot}`);
 }
 // A checking controller whose device holds a slot reads "connected"
 cur=overview(both,undefined,{controllers:[{controller:'pc',reachable:true},{controller:'phone',checking:true},{controller:'mac',reachable:false,checking:true}]});await page.reload();await page.getByText('Live · just now').waitFor();
 {const foot=await page.locator('#controllers').textContent();check(foot.includes('Phone connected')&&!foot.includes('Phone checking')&&foot.includes('Mac checking'),`Connected controller should read "Phone connected": ${foot}`);}
 check(!await page.evaluate(()=>document.documentElement.classList.contains('popover')),'Normal page must not be in popover mode');

 // Mac menu-bar popover: 380 px web view, phone layout, height reported to the native side
 for(const colorScheme of ['light','dark']){
  const pop=await browser.newPage({viewport:{width:380,height:800},colorScheme});pop.on('pageerror',e=>errors.push(e.message));
  await pop.addInitScript(()=>{window.__sizes=[];window.__opened=0;window.webkit={messageHandlers:{boseSize:{postMessage:m=>window.__sizes.push(m.height)},boseOpenWindow:{postMessage:()=>window.__opened++}}};});
  await wire(pop);cur=overview(both);
  await pop.goto(base+'/?view=popover');await pop.locator('.cup',{hasText:'Desktop PC'}).waitFor();await pop.getByText('Live · just now').waitFor();await ready(pop);
  check(await pop.evaluate(()=>document.documentElement.classList.contains('popover')),'Popover class missing');
  check(!await pop.evaluate(()=>document.documentElement.scrollWidth>innerWidth),`Popover horizontal overflow (${colorScheme})`);
  check(await pop.evaluate(()=>document.querySelector('.col-side').getBoundingClientRect().top>=document.querySelector('.col-main').getBoundingClientRect().bottom-1),'Popover must be single-column');
  await headerFits('popover',pop);
  check(await ridgesClear(pop),`Popover ridges climb into the caption (${colorScheme})`);
  const sizes=await pop.evaluate(()=>window.__sizes),last=sizes[sizes.length-1];
  const shellH=await pop.evaluate(()=>Math.ceil(document.querySelector('.shell').getBoundingClientRect().height));
  check(last>300&&last<900&&last===shellH,`Popover height report out of range: ${JSON.stringify(sizes)} (shell ${shellH})`);
  check(sizes.every((h,i)=>!i||h!==sizes[i-1]),'Height reports must skip unchanged values');
  console.log(`popover ${colorScheme}: reported heights ${JSON.stringify(sizes)}`);
  await shot(pop,`popover-${colorScheme}.png`);
  if(colorScheme==='light'){
   await pop.getByRole('button',{name:'Settings',exact:true}).click();
   await pop.getByRole('button',{name:'Open full window'}).click();
   check(await pop.evaluate(()=>window.__opened)===1,'Open full window must post to boseOpenWindow');
   overrideHandler=async()=>{await sleep(900);cur=overview([DEV.pc.address],cur.noise);return {ok:true,verified:true,message:'Android phone disconnected',state:cur};};
   await pop.getByRole('button',{name:'Disconnect Android phone'}).click();
   await pop.locator('.cup.pending .pill.pending',{hasText:'Disconnecting…'}).waitFor({timeout:200});
   await shot(pop,'popover-pending.png');await pop.getByText('Android phone disconnected').waitFor();
  }
  await pop.close();
 }

 // ---- Use here: every scenario of tests/switch-contract.json against scripted /api/switch replies ----
 const other={other1:'phone',other2:'mac',here:'pc'},lab=r=>contract.labels[other[r]],addr=r=>DEV[other[r]].address;
 const fill=(t,label)=>t.replace('{label}',label);
 const textOf=k=>k.split('.').slice(1).reduce((o,p)=>o[p],M);
 const reply=(sc,body)=>{const e=sc.expect;
  if(e.outcome==='busy'||(sc.replace&&!body.replace))return {ok:false,busy:true,error_key:'busy',error:M.busy,slots:sc.start.map(r=>({address:addr(r),label:lab(r)}))};
  if(e.outcome==='ok'){cur=overview((e.connected||[]).map(addr),cur.noise);return {ok:true,verified:true,message:M.ok,state:cur};}
  return {ok:false,error_key:e.error_key,error:M.errors[e.error_key],detail:'scripted'};};
 const settle=async()=>{await sw.mouse.move(1,1);await sleep(250);};
 const sw=await browser.newPage({viewport:{width:390,height:844}});sw.on('pageerror',e=>errors.push(e.message));await wire(sw);
 const status=()=>sw.locator('#message').textContent();
 for(const sc of contract.scenarios){
  cur=overview(sc.start.map(addr));await sw.goto(base);await sw.getByText('Live · just now').waitFor();await ready(sw);
  switchPosts.length=0;switchReplied=0;switchHandler=async b=>{await sleep(700);return reply(sc,b);};
  if(sc.name==='success')await shot(sw,'switch-idle.png');
  const tapped=Date.now();await sw.getByRole('button',{name:/^Use here/}).click();
  await sw.locator('#message.pend',{hasText:M.pending}).waitFor({timeout:400});
  check(!switchReplied,`${sc.name}: "${M.pending}" must show before the reply`);
  check(await sw.locator('#use-here').textContent()===M.pending&&await sw.locator('#use-here').isDisabled(),`${sc.name}: Use here must turn pending at once`);
  if(sc.name==='success')await shot(sw,'switch-pending.png');
  await sw.waitForFunction(()=>!document.querySelector('#message.pend'),null,{timeout:5000});
  const first=switchPosts[0].body;
  check(switchPosts.length===1&&first.source==='web'&&/^[a-z0-9]{1,32}$/.test(first.request_id)&&!('replace' in first)&&Object.keys(first).length===2,`${sc.name}: bad switch payload ${JSON.stringify(first)}`);
  if(sc.expect.outcome==='busy'||sc.replace){
   await sw.getByText(M.busy,{exact:true}).waitFor();
   const offered=await sw.locator('#choose-options button').allTextContents();
   const want=(sc.expect.offered||sc.start.map(r=>'Replace {'+r+'}')).map(o=>o.replace(/\{(other\d)\}/,(_,r)=>lab(r)));
   check(JSON.stringify(offered)===JSON.stringify(want),`${sc.name}: offered ${JSON.stringify(offered)}, want ${JSON.stringify(want)}`);
   check(JSON.stringify(want)===JSON.stringify(sc.start.map(r=>fill(M.replace,lab(r)))),`${sc.name}: offers must be messages.replace per slot`);
   if(sc.name==='both_busy'){await settle();await shot(sw,'switch-busy.png');};
   if(!sc.replace){check(switchPosts.length===1,`${sc.name}: busy must not resend`);await sw.getByRole('button',{name:'Cancel',exact:true}).click();check(await sw.locator('#choose').isHidden(),'Cancel hides the busy prompt');continue;}
   switchReplied=0;await sw.getByRole('button',{name:fill(M.replace,lab(sc.replace)),exact:true}).click();
   await sw.locator('#message.pend',{hasText:fill(M.replacing,lab(sc.replace))}).waitFor({timeout:400});check(!switchReplied,`${sc.name}: "${fill(M.replacing,lab(sc.replace))}" must show before the reply`);
   await sw.waitForFunction(()=>!document.querySelector('#message.pend'),null,{timeout:5000});
   const second=switchPosts[1]?.body;
   check(switchPosts.length===2&&second.replace===addr(sc.replace)&&second.source==='web'&&second.request_id!==first.request_id,`${sc.name}: bad replace payload ${JSON.stringify(second)}`);
  }
  const want=sc.expect.outcome==='ok'?textOf(sc.expect.text):textOf(sc.expect.text)+M.retry_hint;
  check(await status()===want,`${sc.name}: status "${await status()}", want "${want}"`);
  check((await sw.locator('#message.error').count()===1)===(sc.expect.outcome==='error'),`${sc.name}: error styling`);
  if(sc.expect.outcome==='ok')for(const r of sc.expect.connected)check(await sw.locator('.cup',{hasText:DEV[other[r]].name}).count()===1,`${sc.name}: ${r} should hold a cup`);
  check(await sw.locator('#use-here').isEnabled(),`${sc.name}: Use here must be tappable again`);
  if(sc.name==='success'){await settle();await shot(sw,'switch-ok.png');};
  if(sc.name==='unreachable'){await settle();await shot(sw,'switch-error.png');};
 }
 // The Mac popover sends its own source
 cur=overview([DEV.phone.address],undefined,{here:'mac'});switchPosts.length=0;switchHandler=async()=>({ok:true,verified:true,message:M.ok,state:overview([DEV.phone.address,DEV.mac.address],undefined,{here:'mac'})});
 await sw.goto(base+'/?view=popover');await sw.getByText('Live · just now').waitFor();await sw.getByRole('button',{name:/^Use here/}).click();await sw.getByText(M.ok,{exact:true}).waitFor();
 check(switchPosts[0].body.source==='mac-popover','Mac popover source: '+JSON.stringify(switchPosts[0].body));
 // Per-row Connect shows the controller's contract text on failure
 cur=overview([DEV.pc.address,DEV.phone.address]);await sw.goto(base);await sw.getByText('Live · just now').waitFor();
 overrideHandler=async()=>({ok:false,error_key:'keep_one',error:M.errors.keep_one,detail:'scripted'});
 await sw.getByRole('button',{name:'Connect MacBook Pro'}).click();await sw.getByRole('button',{name:'Replace Android phone'}).click();
 await sw.getByText(M.errors.keep_one,{exact:true}).waitFor();
 // Android WebView: the bridge's switchHere is used when present, with the same reply shape
 await sw.addInitScript(()=>{window.__switched=[];window.Android={request:(id,p,d)=>fetch(p,d?{method:'POST',headers:{'Content-Type':'application/json'},body:d}:{}).then(r=>r.text()).then(t=>window.finishRequest(id,t)),
  switchHere:(id,body)=>{window.__switched.push(JSON.parse(body));setTimeout(()=>window.finishRequest(id,JSON.stringify({ok:false,error_key:'timeout',error:'Took too long to switch'})),300);},settings:()=>{}};});
 cur=overview([DEV.phone.address]);switchPosts.length=0;await sw.goto(base);await sw.getByText('Live · just now').waitFor();
 await sw.getByRole('button',{name:/^Use here/}).click();await sw.locator('#message.pend',{hasText:M.pending}).waitFor({timeout:250});
 await sw.getByText(M.errors.timeout+M.retry_hint,{exact:true}).waitFor();
 const bridged=await sw.evaluate(()=>window.__switched);
 check(bridged.length===1&&bridged[0].source==='android-app'&&!switchPosts.length,'Android bridge switchHere: '+JSON.stringify(bridged));
 await sw.close();

 // ---- Shared state machine: GET /api/state long-poll (docs/state-machine.md §3), rendered as-is ----
 {
  const shots=path.join(artifacts,'state');fs.mkdirSync(shots,{recursive:true});
  const steps=contract.steps||{};const lbl=(k,label)=>(steps[k]||k).replace('{label}',label);
  const now=()=>Date.now()/1000;
  const slot=(d,role,state,extra={})=>({address:d.address,role,label:contract.labels[role]||d.name,name:d.name,state,...extra});
  const free={state:'free'};
  const ctl=[{id:'pc',state:'here'},{id:'phone',state:'available'},{id:'mac',state:'offline',reason:'Headset is not connected to this Mac'}];
  const snapshot=(o={})=>({seq:0,headset:{reachable:true,via:'pc',read_age:1.4,battery:62,noise:{level:7,enabled:true},product:'Bose 700',controllers:ctl,...o.headset},
   slots:o.slots,devices:o.devices||[],audio:{sink:'bluez_output.AA_AA_AA_AA_AA_AA.1',default:true},operation:o.operation??null});
  const waiters=[];
  states={snap:null,onCancel:null,
   next:ms=>new Promise(res=>{const t=setTimeout(res,ms);waiters.push(()=>{clearTimeout(t);res();});}),
   set(snap){snap.seq=(this.snap?.seq||0)+1;this.snap=snap;waiters.splice(0).forEach(f=>f());}};
  const step=(name,label,state,extra={})=>({name,label,state,...extra});
  const op=(target,phase,list,extra={})=>({id:'k3f9a2',source:'web',target,action:'switch',phase,started_at:now()-3,deadline:150,steps:list,result:null,...extra});
  const tv={address:DEV.tv.address,role:null,label:DEV.tv.name,name:DEV.tv.name,state:'disconnected'};
  // Scenes: Mac → PC with the phone kept (spec §2 release rule), then a phone tap that has to ask.
  const scenes={
   idle:()=>snapshot({slots:[slot(DEV.phone,'phone','connected'),slot(DEV.pc,'pc','connected')],devices:[slot(DEV.mac,'mac','disconnected'),tv]}),
   macphone:()=>snapshot({slots:[slot(DEV.phone,'phone','connected'),slot(DEV.mac,'mac','connected')],devices:[slot(DEV.pc,'pc','disconnected'),tv]}),
   releasing:()=>snapshot({slots:[slot(DEV.phone,'phone','connected'),slot(DEV.mac,'mac','releasing')],devices:[slot(DEV.pc,'pc','disconnected'),tv],
    operation:op('pc','releasing',[step('reading',lbl('reading'),'done',{seconds:0.4}),step('releasing',lbl('releasing','Mac'),'active',{since:now()-1.1}),step('connecting',lbl('connecting_here','PC'),'pending'),step('audio',lbl('audio'),'pending')])}),
   connecting:()=>snapshot({slots:[slot(DEV.phone,'phone','connected'),slot(DEV.pc,'pc','connecting')],devices:[slot(DEV.mac,'mac','disconnected'),tv],
    operation:op('pc','connecting',[step('reading',lbl('reading'),'done',{seconds:0.4}),step('releasing',lbl('releasing','Mac'),'done',{seconds:1.4}),step('connecting',lbl('connecting_here','PC'),'active',{since:now()-0.8}),step('audio',lbl('audio'),'pending')])}),
   done:()=>snapshot({slots:[slot(DEV.phone,'phone','connected'),slot(DEV.pc,'pc','connected')],devices:[slot(DEV.mac,'mac','disconnected'),tv],
    operation:op('pc','done',[step('reading',lbl('reading'),'done',{seconds:0.4}),step('releasing',lbl('releasing','Mac'),'done',{seconds:1.4}),step('connecting',lbl('connecting_here','PC'),'done',{seconds:1.9}),step('audio',lbl('audio'),'done',{seconds:0.4})],
     {started_at:now()-4.3,result:{ok:true,text:M.ok,seconds:4.1}})}),
   failed:()=>snapshot({slots:[slot(DEV.phone,'phone','connected'),slot(DEV.mac,'mac','connected')],devices:[slot(DEV.pc,'pc','disconnected'),tv],
    operation:op('pc','failed',[step('reading',lbl('reading'),'done',{seconds:0.4}),step('releasing',lbl('releasing','Mac'),'failed',{seconds:12.0})],
     {started_at:now()-12.6,result:{ok:false,error_key:'unverified',text:lbl('release_failed','Mac'),step:'releasing',detail:'scripted',seconds:12.4}})}),
   choose:()=>snapshot({slots:[slot(DEV.mac,'mac','connected'),slot(DEV.pc,'pc','connected')],devices:[slot(DEV.phone,'phone','disconnected'),tv],
    operation:op('phone','choose',[step('reading',lbl('reading'),'done',{seconds:0.5}),step('choose',lbl('choose'),'active',{since:now()-0.6})],
     {choices:[{address:DEV.mac.address,label:'Mac'},{address:DEV.pc.address,label:'PC'}]})}),
   unreachable:()=>snapshot({headset:{reachable:false,via:null,read_age:140,battery:null,noise:null,
     controllers:[{id:'pc',state:'offline',reason:'Headset is not connected to this PC'},{id:'phone',state:'offline',reason:'Controller unavailable: ConnectionRefusedError'},{id:'mac',state:'offline',reason:'Controller unavailable: TimeoutError'}]},
    slots:[slot(DEV.phone,'phone','unknown',{age:140}),slot(DEV.pc,'pc','unknown',{age:140})],devices:[slot(DEV.mac,'mac','unknown',{age:140}),tv]}),
  };
  const st=await browser.newPage({viewport:{width:390,height:844}});st.on('pageerror',e=>errors.push(e.message));await wire(st);
  const chips=()=>st.locator('.cup .chip').allTextContents();
  const opText=()=>st.locator('#op').innerText();
  cur=overview([DEV.pc.address,DEV.phone.address]);overviewCalls=0;
  states.set(scenes.idle());await st.goto(base);await st.locator('.cup .chip',{hasText:'Connected'}).first().waitFor();await ready(st);
  check(JSON.stringify(await chips())===JSON.stringify(['Connected','Connected']),'Idle chips: '+JSON.stringify(await chips()));
  check(overviewCalls===0,'State mode must not poll /api/overview');
  check(/^(Live )?via this PC · read /.test(await st.locator('#headset-status').textContent())&&await headerFits('state 390',st)===undefined,'Header via + read age: '+await st.locator('#headset-status').textContent());
  check(await st.locator('#op').isHidden()&&await st.locator('#use-here').isVisible(),'Idle: Use here, no operation card');
  await st.waitForFunction(()=>true);await sleep(300);
  check(stateGets.some(g=>g.after===states.snap.seq&&g.wait==='25'),'Long-poll must send after=<seq>&wait=25: '+JSON.stringify(stateGets.slice(-3)));
  check(await st.locator('.device',{hasText:'MacBook Pro'}).getByRole('button',{name:'Move the headphones to the Mac'}).isVisible(),'Mac row offers Move to Mac');
  check(!(await st.locator('#devices').textContent()).includes('Android phone'),'A device holding a slot never shows as saved');

  // Tap Move to Mac: one non-blocking POST with target, the first step shown before the reply
  switchPosts.length=0;switchReplied=0;switchHandler=async b=>{await sleep(500);return {accepted:true,seq:states.snap.seq,operation:op('mac','reading',[step('reading',lbl('reading'),'active',{since:now()})],{started_at:now()})};};
  await st.getByRole('button',{name:'Move the headphones to the Mac'}).click();
  await st.locator('#op .step.active',{hasText:lbl('reading')}).waitFor({timeout:300});check(!switchReplied,'The first step must show before the controller answers');
  await sleep(700);
  const mb=switchPosts[0]?.body;check(switchPosts.length===1&&mb.target==='mac'&&mb.source==='web'&&/^[a-z0-9]{1,32}$/.test(mb.request_id)&&!('replace' in mb),'Move to Mac payload '+JSON.stringify(mb));
  check((await opText()).includes('Moving to the Mac'),'Operation title for the Mac: '+await opText());
  check(await st.locator('[data-switch="true"]:enabled').count()===0&&await st.locator('[data-live="true"]:enabled').count()===0,'One operation at a time: other actions disabled');

  // Mac → PC: releasing, connecting, done; each pushed by the long-poll, never inferred by the page
  states.set(scenes.macphone());await st.locator('#op').waitFor({state:'hidden'});
  switchPosts.length=0;switchHandler=async()=>({accepted:true,seq:states.snap.seq,operation:scenes.releasing().operation});
  await st.getByRole('button',{name:/^Use here/}).click();await sleep(200);
  check(switchPosts[0]?.body.target==='pc','Use here sends target pc: '+JSON.stringify(switchPosts[0]?.body));
  states.set(scenes.releasing());await st.locator('#op .step.active',{hasText:lbl('releasing','Mac')}).waitFor();
  check(JSON.stringify(await chips())===JSON.stringify(['Connected','Releasing…']),'Releasing chips: '+JSON.stringify(await chips()));
  check((await st.locator('#op .step.done').first().textContent()).includes('0.4 s'),'Done step shows its seconds');
  check(await st.locator('#op .step.pending').count()===2,'Pending steps listed');
  states.set(scenes.connecting());await st.locator('#op .step.active',{hasText:lbl('connecting_here','PC')}).waitFor();
  check(JSON.stringify(await chips())===JSON.stringify(['Connected','Connecting…']),'Connecting chips: '+JSON.stringify(await chips()));
  check(await st.locator('.device',{hasText:'Desktop PC'}).count()===0,'A connecting device leaves the saved list');
  states.set(scenes.done());await st.locator('#op .op-r',{hasText:`${M.ok} · 4.1 s`}).waitFor();
  check(await st.locator('#op .step.done').count()===4,'All four steps done');
  check(await st.locator('#use-here').isHidden(),'Result shows in place of Use here');
  // Auto-clear: the controller drops the finished operation
  states.set(scenes.idle());await st.locator('#op').waitFor({state:'hidden'});check(await st.locator('#use-here').isVisible(),'Use here returns after the result clears');

  // Failure: the failed step says why; Try again sends the same target
  states.set(scenes.failed());await st.locator('#op .step.failed .why',{hasText:lbl('release_failed','Mac')}).waitFor();
  check((await st.locator('#op .step.failed .ss').textContent())==='12.0 s','Failed step shows its seconds');
  switchPosts.length=0;switchHandler=async()=>({accepted:true,seq:states.snap.seq,operation:scenes.releasing().operation});
  await st.getByRole('button',{name:'Try again'}).click();await sleep(200);
  check(switchPosts.length===1&&switchPosts[0].body.target==='pc','Try again resends the tap once: '+JSON.stringify(switchPosts.map(p=>p.body)));

  // Choose: Replace Mac / Replace PC / Cancel; a choice is a new tap with replace, Cancel ends the phase
  states.set(scenes.choose());await st.getByRole('button',{name:'Replace Mac',exact:true}).waitFor();
  check(JSON.stringify(await st.locator('#op .op-choose button').allTextContents())==='["Replace Mac","Replace PC","Cancel"]','Choose buttons');
  switchPosts.length=0;switchHandler=async()=>({accepted:true,seq:states.snap.seq,operation:scenes.choose().operation});
  await st.getByRole('button',{name:'Replace Mac',exact:true}).click();await sleep(200);
  check(switchPosts.length===1&&switchPosts[0].body.target==='phone'&&switchPosts[0].body.replace===DEV.mac.address,'Replace payload '+JSON.stringify(switchPosts[0]?.body));
  states.set(scenes.choose());await st.getByRole('button',{name:'Cancel',exact:true}).waitFor();
  cancels.length=0;await st.getByRole('button',{name:'Cancel',exact:true}).click();await sleep(200);
  check(cancels.length===1,'Cancel posts /api/switch/cancel');

  // Unreachable: unknown slots with their age, each controller's reason
  states.set(scenes.unreachable());await st.locator('.cup .chip',{hasText:'Unknown'}).first().waitFor();
  check(JSON.stringify(await chips())===JSON.stringify(['Unknown · 2 min ago','Unknown · 2 min ago']),'Unknown chips: '+JSON.stringify(await chips()));
  const reasons=await st.locator('#controllers li').allTextContents();
  check(JSON.stringify(reasons)===JSON.stringify(['PCHeadset is not connected to this PC','Phoneapp not running','Macno answer']),'Controller reasons: '+JSON.stringify(reasons));
  check((await st.locator('#headset-status').textContent()).startsWith('Not reachable · last read 2 min ago'),'Unreachable header: '+await st.locator('#headset-status').textContent());
  check(await st.locator('#use-here').isEnabled(),'Use here stays available: the controller reads the headset itself');
  check(!await st.evaluate(()=>document.documentElement.scrollWidth>innerWidth),'State mode horizontal overflow');

  // Screenshots: every scene, light + dark, phone + desktop. Times are frozen-ish: the shots are taken right after set().
  for(const [w,h,kind] of [[390,844,'phone'],[1280,900,'desktop']]){
   await st.setViewportSize({width:w,height:h});
   for(const colorScheme of ['light','dark']){
    await st.emulateMedia({colorScheme});
    for(const name of Object.keys(scenes)){
     if(name==='macphone')continue;
     states.set(scenes[name]());await st.mouse.move(1,1);await sleep(150);await ready(st);
     check(await st.evaluate(()=>[...document.querySelectorAll('.cup .chip')].every(c=>[c,...c.children].every(e=>getComputedStyle(e).display==='none'||e.scrollWidth<=e.clientWidth+1)&&c.getBoundingClientRect().right<=c.closest('.cup').getBoundingClientRect().right-8)),`${name} ${kind}: a state chip is cut off`);
     check(await st.evaluate(()=>{const t=[...document.querySelectorAll('.cup .chip')].map(c=>c.getBoundingClientRect().top+c.offsetHeight/2);for(const a of document.querySelectorAll('.cup .slot-age,.cup .slot'))if(getComputedStyle(a).display!=='none')t.push(a.getBoundingClientRect().top+a.offsetHeight/2);return t.every(v=>Math.abs(v-t[0])<=1.5);}),`${name} ${kind}: chips misaligned`);
     if(kind==='phone')check(!await st.evaluate(()=>document.documentElement.scrollWidth>innerWidth),`${name} phone overflow`);
     await shot(st,`state/${kind}-${colorScheme}-${name}.png`);
    }
   }
  }
  await st.close();
  // The Mac popover in state mode: single column with the operation card, heights still reported
  const pop=await browser.newPage({viewport:{width:380,height:800}});pop.on('pageerror',e=>errors.push(e.message));
  await pop.addInitScript(()=>{window.__sizes=[];window.webkit={messageHandlers:{boseSize:{postMessage:m=>window.__sizes.push(m.height)}}};});
  await wire(pop);states.set(scenes.connecting());await pop.goto(base+'/?view=popover');await pop.locator('#op .step.active').waitFor();await ready(pop);
  check(!await pop.evaluate(()=>document.documentElement.scrollWidth>innerWidth),'Popover state overflow');
  check(await pop.evaluate(()=>window.__sizes.length>0),'Popover height reported in state mode');
  await shot(pop,'state/popover-light-connecting.png');await pop.close();
  states=null;
 }

 check(!errors.length,errors.join('\n'));
 console.log(`GUI checked: offline/live/cached, light+dark, phone+desktop; pending connect/disconnect; render-from-state; overview fallback; failure revert; ANC slider release + coalescing; ANC switch off; replace via cups; settings dialog; no JS errors or mobile overflow; here-controller footer; Mac popover mode (single column, height report, open window); Use here through ${contract.scenarios.length} contract scenarios + popover source, row contract text, Android bridge; /api/state long-poll: chips, steps, timings, result, auto-clear, retry, choose/cancel, Move-to targets, unreachable reasons, 404 fallback, popover.`);
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
