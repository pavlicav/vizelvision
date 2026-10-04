const {chromium}=require(process.argv[2]||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[],requests=[],logs=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(['error','warning'].includes(m.type()))logs.push(m.text());});
  page.on('requestfailed',r=>logs.push(r.url()+': '+r.failure()?.errorText));
  page.on('request',r=>requests.push(r.url()));
  await page.goto(process.argv[3]);
  await page.locator('#watch-master').click();
  try{await page.waitForFunction(()=>document.querySelector('#master-video').videoWidth===1280&&!document.querySelector('#master-video').paused,{},{timeout:30000});}
  catch(error){console.error(JSON.stringify({errors,logs,requests,media:await page.evaluate(()=>{const v=document.querySelector('#master-video');return {label:document.querySelector('#monitor-status').textContent,ready:v.readyState,width:v.videoWidth,network:v.networkState,error:v.error?.message,hls:window.Hls?.version,supported:window.Hls?.isSupported()};})}));throw error;}
  const sample=()=>page.evaluate(()=>{
   const v=document.querySelector('#master-video'),c=document.createElement('canvas');c.width=2;c.height=2;
   const context=c.getContext('2d');context.drawImage(v,0,0,2,2);
   return {time:v.currentTime,source:v.currentSrc,pixel:[...context.getImageData(1,1,1,1).data]};
  });
  await page.waitForFunction(()=>{
   const v=document.querySelector('#master-video'),c=document.createElement('canvas');c.width=2;c.height=2;
   const context=c.getContext('2d');context.drawImage(v,0,0,2,2);const pixel=context.getImageData(1,1,1,1).data;
   return pixel[0]>150&&pixel[1]<50;
  },{},{timeout:15000});
  const before=await sample();assert.ok(before.pixel[0]>150&&before.pixel[1]<50,JSON.stringify(before));
  await page.locator('#fallback').click();
  await page.getByRole('dialog',{name:'Return to fallback'}).getByRole('button',{name:'Cut to fallback'}).click();
  await page.waitForFunction(()=>document.querySelector('#master-state').textContent.includes('fallback'));
  try{await page.waitForFunction(()=>{
   const v=document.querySelector('#master-video'),c=document.createElement('canvas');c.width=2;c.height=2;
   const context=c.getContext('2d');context.drawImage(v,0,0,2,2);const pixel=context.getImageData(1,1,1,1).data;
   // The fallback is the off-air test card now (not black): the red source has gone.
   return v.currentTime>3&&!(pixel[0]>150&&pixel[1]<50);
  },{},{timeout:25000});}
  catch(error){console.error(JSON.stringify({before,now:await sample(),errors,logs:logs.slice(-12),status:await page.locator('#monitor-status').textContent(),
   media:await page.evaluate(()=>{const v=document.querySelector('#master-video');return {paused:v.paused,ready:v.readyState,hidden:v.hidden,width:v.videoWidth,error:v.error?.message};})}));throw error;}
  const after=await sample();assert.ok(after.time>before.time);assert.equal(after.source,before.source,'cut must preserve player attachment');
  assert.ok(requests.some(url=>url.includes('/vizelvision/v1/master/media/')&&url.includes('.mp4')),'fragments use same-origin proxy under prefix');
  assert.ok(requests.every(url=>new URL(url).origin===new URL(process.argv[3]).origin),'no CDN or direct upstream calls');
  await page.locator('#stop-monitor').click();
  assert.equal(await page.locator('#monitor-status').textContent(),'Monitor off');
  assert.equal(await page.locator('#master-video').getAttribute('src'),null);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({ok:true,video_width:1280,same_player_across_cut:true,media_time_before:before.time,media_time_after:after.time,same_origin:true}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
