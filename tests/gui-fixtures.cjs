const {chromium}=require('playwright-core');
const path=require('path'),fs=require('fs');
const artifacts=path.resolve(__dirname,'../artifacts');fs.mkdirSync(artifacts,{recursive:true});
const fonts=path.resolve(__dirname,'../web/fonts');
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
 let cur=null,overviewCalls=0,overrideHandler=null;const posts=[];
 // Every page gets the same fixture API; nothing reaches a live controller.
 const wire=async page=>{
  await page.route('**/fonts/*.woff2',r=>{const f=path.join(fonts,path.basename(new URL(r.request().url()).pathname));return fs.existsSync(f)?r.fulfill({body:fs.readFileSync(f),contentType:'font/woff2'}):r.fulfill({status:404,body:''});});
  await page.route('**/api/cached',r=>r.fulfill({json:{devices:[]}}));
  await page.route('**/api/overview',r=>{overviewCalls++;return r.fulfill({json:cur});});
  await page.route('**/api/override',async r=>{const body=r.request().postDataJSON();posts.push({body,at:Date.now()});const res=await overrideHandler(body);return r.fulfill({json:res});});
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

 check(!errors.length,errors.join('\n'));
 console.log('GUI checked: offline/live/cached, light+dark, phone+desktop; pending connect/disconnect; render-from-state; overview fallback; failure revert; ANC slider release + coalescing; ANC switch off; replace via cups; settings dialog; no JS errors or mobile overflow; here-controller footer; Mac popover mode (single column, height report, open window).');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
