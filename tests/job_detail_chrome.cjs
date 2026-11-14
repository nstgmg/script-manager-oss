// Chrome DevTools over anonymous pipes: no listening port or Dashboard service.
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const {pathToFileURL} = require('node:url');
const [chrome, fixture, widthText, profile, screenshot, marker = "job-detail-browser-result"] = process.argv.slice(2);
const width = Number(widthText);
const child = spawn(chrome, ['--headless=new', '--disable-gpu', '--no-first-run',
  '--no-default-browser-check', '--disable-background-networking', '--disable-sync',
  '--disable-extensions', '--host-resolver-rules=MAP * ~NOTFOUND',
  '--user-data-dir='+profile, '--remote-debugging-pipe'],
  {stdio:['ignore','ignore','pipe','pipe','pipe']});
let serial=0, buffer='', stderr='';
const requests=new Map(), events=new Map();
child.stderr.on('data', data=>{stderr=(stderr+data).slice(-2000);});
child.stdio[4].on('data', data=>{
  buffer+=data;
  let end;
  while((end=buffer.indexOf('\0'))>=0){
    const message=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);
    if(message.id){
      const pending=requests.get(message.id);requests.delete(message.id);
      if(message.error)pending?.reject(Error(JSON.stringify(message.error)));
      else pending?.resolve(message.result);
    }else{
      const key=(message.sessionId||'')+':'+message.method;
      events.get(key)?.(message.params);events.delete(key);
    }
  }
});
function send(method, params={}, sessionId){
  return new Promise((resolve,reject)=>{
    const id=++serial;requests.set(id,{resolve,reject});
    child.stdio[3].write(JSON.stringify({id,method,params,sessionId})+'\0');
  });
}
child.on('exit', code=>{
  for(const {reject} of requests.values())reject(Error('Chrome exited '+code+' '+stderr));
});
(async()=>{
  try{
    const {targetId}=await send('Target.createTarget',{url:'about:blank'});
    const {sessionId}=await send('Target.attachToTarget',{targetId,flatten:true});
    await send('Page.enable',{},sessionId);
    await send('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false},sessionId);
    const loaded=new Promise(resolve=>events.set(sessionId+':Page.loadEventFired',resolve));
    await send('Page.navigate',{url:pathToFileURL(fixture).href},sessionId);await loaded;
    const result=await send('Runtime.evaluate',{expression:`(async()=>{
      for(let i=0;i<600;i++){
        const result=document.getElementById(${JSON.stringify(marker)});
        if(result)return {text:result.textContent,width:innerWidth,scrollWidth:document.documentElement.scrollWidth};
        await new Promise(resolve=>setTimeout(resolve,50));
      }
      throw Error('Browser fixture timed out');
    })()`,awaitPromise:true,returnByValue:true},sessionId);
    if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));
    console.log(JSON.stringify(result.result.value));
    if(screenshot){
      const image=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},sessionId);
      fs.writeFileSync(screenshot,Buffer.from(image.data,'base64'));
      for(const section of (marker === 'job-detail-browser-result' ? ['local-runs','html-reports','packages-section','lifecycle-section','deployment-section'] : ['reset-title'])){
        await send('Runtime.evaluate',{expression:`(async()=>{
          const section=document.getElementById('${section}');
          if(section.tagName==='DETAILS')section.open=true;
          section.scrollIntoView({block:'start'});
          await new Promise(requestAnimationFrame);
        })()`,awaitPromise:true},sessionId);
        const panel=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},sessionId);
        fs.writeFileSync(screenshot.replace(/\.png$/, '-'+section+'.png'),Buffer.from(panel.data,'base64'));
      }
    }
  }catch(error){console.error(error.stack);process.exitCode=1;}
  finally{await send('Browser.close').catch(()=>{});}
})();
