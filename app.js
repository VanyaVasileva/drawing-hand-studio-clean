(()=>{'use strict';
const $=id=>document.getElementById(id), LEAD=.07, INK_STREAMLINE=35, INK_FOLLOW=1-(INK_STREAMLINE/100)*.82;
const HANDS={default:'https://raw.githubusercontent.com/VanyaVasileva/drawing-hand-studio/main/assets/default_hand.png',cream:'assets/hand-cream-sleeve.png',sage:'assets/hand-sage-sleeve.png',pink:'assets/hand-pink-sleeve.png',dark:'assets/hand-dark-sleeve.png',brownOatmeal:'assets/hand-brown-oatmeal.png'};
const HAND_META={default:{tipX:14.8,tipY:34.4,scale:1},cream:{tipX:9.4,tipY:26.2,scale:1.319},sage:{tipX:11.0,tipY:28.1,scale:1.292},pink:{tipX:13.8,tipY:27.4,scale:1.308},dark:{tipX:8.5,tipY:28.1,scale:1.280},brownOatmeal:{tipX:10.8,tipY:24.5,scale:1.398}};
const file=$('file'),source=$('source'),make=$('make'),status=$('status'),fileStatus=$('fileStatus'),size=$('size'),duration=$('duration'),resultCard=$('resultCard'),result=$('result'),download=$('download'),out=$('output'),oc=out.getContext('2d',{alpha:false}),track=$('track'),tc=track.getContext('2d',{willReadFrequently:true});
const c={handSize:$('handSize'),tipX:$('tipX'),tipY:$('tipY'),offX:$('offX'),offY:$('offY'),sensitivity:$('sensitivity')};
const v={handSize:$('handSizeV'),tipX:$('tipXV'),tipY:$('tipYV'),offX:$('offXV'),offY:$('offYV'),sensitivity:$('sensV')};
let side='Right',preset='source',handStyle='default',srcURL,resURL,busy=false,ready=false,aCtx,aSrc,aDest,aDelay;
const pct=x=>(Math.round(+x*10)/10)+'%';
function labels(){v.handSize.textContent=pct(c.handSize.value);v.tipX.textContent=pct(c.tipX.value);v.tipY.textContent=pct(c.tipY.value);v.offX.textContent=pct(c.offX.value);v.offY.textContent=pct(c.offY.value);v.sensitivity.textContent=c.sensitivity.value}
Object.values(c).forEach(x=>x.oninput=labels);labels();
function seg(id,set){const el=$(id);if(!el)return;el.onclick=e=>{const b=e.target.closest('button');if(!b)return;[...b.parentNode.children].forEach(x=>x.classList.toggle('on',x===b));set(b.dataset.v)}}
seg('side',x=>side=x);seg('preset',x=>preset=x);
function setHandButton(name){const el=$('handStyle');if(!el)return;[...el.querySelectorAll('button')].forEach(b=>b.classList.toggle('on',b.dataset.v===name))}
function applyHandMeta(name){const m=HAND_META[name]||HAND_META.default;c.tipX.value=m.tipX;c.tipY.value=m.tipY;labels()}
const hand=new Image();hand.crossOrigin='anonymous';let handReady=Promise.resolve();
function loadHandStyle(name){handStyle=HANDS[name]?name:'default';applyHandMeta(handStyle);handReady=new Promise((ok,no)=>{hand.onload=()=>{if(ready&&!busy)status.textContent='Ready to create.';ok()};hand.onerror=()=>{if(handStyle!=='default'){const failed=handStyle;handStyle='default';setHandButton('default');applyHandMeta('default');status.textContent='Hand image not found: '+failed+'.';hand.onload=()=>ok();hand.onerror=()=>no(Error('Built-in hand image could not load'));hand.src=HANDS.default}else no(Error('Built-in hand image could not load'))};hand.src=HANDS[handStyle]});return handReady}
loadHandStyle('default');seg('handStyle',x=>loadHandStyle(x));
function meta(){if(source.videoWidth&&source.videoHeight){size.textContent=source.videoWidth+' × '+source.videoHeight;duration.textContent=isFinite(source.duration)?source.duration.toFixed(1)+'s':'—';ready=true;if(!busy)make.disabled=false;fileStatus.textContent='Video ready.';status.textContent='Ready to create.'}}
['loadedmetadata','loadeddata','canplay','durationchange'].forEach(x=>source.addEventListener(x,meta));
file.onchange=()=>{const f=file.files&&file.files[0];if(!f)return;ready=false;make.disabled=true;resultCard.classList.add('hide');fileStatus.textContent='Loading '+f.name+'…';status.textContent='Loading video…';if(srcURL)URL.revokeObjectURL(srcURL);source.pause();source.removeAttribute('src');source.load();srcURL=URL.createObjectURL(f);source.src=srcURL;source.load();setTimeout(meta,800);setTimeout(meta,2500)};
function mime(){for(const x of ['video/mp4;codecs="avc1.42E01E,mp4a.40.2"','video/mp4','video/webm;codecs=vp8,opus','video/webm'])if(window.MediaRecorder&&MediaRecorder.isTypeSupported(x))return x;return ''}
function even(n){n=Math.round(n);return Math.max(2,n-(n%2))}
function dims(w,h){if(preset==='source')return[even(w),even(h)];if(preset==='reel')return[1080,1920];if(preset==='youtube')return[1920,1080];return[even(w),even(h)]}
function quality(ctx){ctx.imageSmoothingEnabled=true;try{ctx.imageSmoothingQuality='high'}catch(e){}}
function fit(ctx,img,w,h){quality(ctx);const sw=img.videoWidth,sh=img.videoHeight,s=Math.min(w/sw,h/sh),dw=sw*s,dh=sh*s,dx=(w-dw)/2,dy=(h-dh)/2;ctx.fillStyle='#000';ctx.fillRect(0,0,w,h);ctx.drawImage(img,dx,dy,dw,dh);return{dx,dy,s}}
function bitrate(w,h,fps){return Math.round(Math.min(50e6,Math.max(18e6,w*h*fps*.22)))}
function tracker(vw,vh){
  const tw=Math.min(600,vw),th=Math.max(2,Math.round(vh*tw/vw)),cell=8,cols=Math.ceil(tw/cell),rows=Math.ceil(th/cell),N=cols*rows;
  track.width=tw;track.height=th;
  let prev=null,lastTarget=null,handPoint=null,localMiss=0;
  const toSource=p=>({x:p.x*vw/tw,y:p.y*vh/th});
  const read=()=>{tc.drawImage(source,0,0,tw,th);const d=tc.getImageData(0,0,tw,th).data,r=new Uint8Array(tw*th*3);for(let i=0,j=0;i<d.length;i+=4){r[j++]=d[i];r[j++]=d[i+1];r[j++]=d[i+2]}return r};
  return()=>{
    const r=read();if(!prev){prev=r;return{pos:handPoint}}
    const sens=+c.sensitivity.value,thr=Math.max(14,sens*.88),count=new Uint16Array(N),weight=new Float32Array(N),sumX=new Float32Array(N),sumY=new Float32Array(N);
    let changed=0;
    for(let y=1;y<th-1;y++)for(let x=1;x<tw-1;x++){
      const q=(y*tw+x)*3,m=Math.abs(r[q]-prev[q])+Math.abs(r[q+1]-prev[q+1])+Math.abs(r[q+2]-prev[q+2]);if(m<thr)continue;
      const k=Math.floor(y/cell)*cols+Math.floor(x/cell),wgt=Math.min(255,m);count[k]++;weight[k]+=wgt;sumX[k]+=x*wgt;sumY[k]+=y*wgt;changed++;
    }
    prev=r;
    const frac=changed/(tw*th),candidates=[];
    for(let gy=0;gy<rows;gy++)for(let gx=0;gx<cols;gx++){
      let cc=0,ww=0,xx=0,yy=0;
      for(let ny=Math.max(0,gy-1);ny<=Math.min(rows-1,gy+1);ny++)for(let nx=Math.max(0,gx-1);nx<=Math.min(cols-1,gx+1);nx++){
        const k=ny*cols+nx;cc+=count[k];ww+=weight[k];xx+=sumX[k];yy+=sumY[k];
      }
      if(cc<4||ww<=0||cc>1700)continue;
      candidates.push({x:xx/ww,y:yy/ww,count:cc,mean:ww/cc,base:Math.log1p(cc)*2+(ww/cc)*.018});
    }
    let chosen=null;
    if(frac<.09&&candidates.length){
      if(lastTarget){
        const lx=lastTarget.x*tw/vw,ly=lastTarget.y*th/vh,localRadius=Math.max(54,tw*.20);
        for(const p of candidates){const d=Math.hypot(p.x-lx,p.y-ly);if(d>localRadius)continue;const score=p.base-d*.035;if(!chosen||score>chosen.score)chosen={...p,score}}
        if(chosen)localMiss=0;else localMiss++;
      }else localMiss=2;
      if(!chosen&&localMiss>=1){
        for(const p of candidates){let score=p.base;if(p.y<th*.105)score+=1.8;if(lastTarget)score-=Math.min(300,Math.hypot(p.x-lastTarget.x*tw/vw,p.y-lastTarget.y*th/vh))*.003;if(!chosen||score>chosen.score)chosen={...p,score}}
        if(chosen)localMiss=0;
      }
    }
    if(chosen){
      lastTarget=toSource(chosen);
      if(!handPoint)handPoint={...lastTarget};
      else{
        const dx=lastTarget.x-handPoint.x,dy=lastTarget.y-handPoint.y;
        if(Math.hypot(dx,dy)>.45){handPoint.x+=dx*INK_FOLLOW;handPoint.y+=dy*INK_FOLLOW}
      }
    }
    return{pos:handPoint}
  }
}
async function audio(){const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return null;if(!aCtx){aCtx=new AC;aSrc=aCtx.createMediaElementSource(source);aDelay=aCtx.createDelay(1);aDelay.delayTime.value=LEAD;aDest=aCtx.createMediaStreamDestination();aSrc.connect(aDelay);aDelay.connect(aDest)}if(aCtx.state==='suspended')await aCtx.resume();return aDest.stream}
async function start(){source.pause();try{source.currentTime=0}catch{};if(source.readyState<2)await new Promise(r=>{let f=()=>{source.removeEventListener('loadeddata',f);r()};source.addEventListener('loadeddata',f,{once:true});setTimeout(f,1200)})}
function drawHand(p,F,w,h){const hm=HAND_META[handStyle]||HAND_META.default,hw=w*(+c.handSize.value/100)*hm.scale,hh=hw*hand.naturalHeight/hand.naturalWidth,px=F.dx+p.x*F.s+w*(+c.offX.value/100),py=F.dy+p.y*F.s+h*(+c.offY.value/100),tx0=hw*(+c.tipX.value/100),ty=hh*(+c.tipY.value/100);let tx=tx0;oc.save();quality(oc);oc.globalAlpha=1;if(side==='Left'){tx=hw-tx;const x=px-tx,y=py-ty;oc.translate(x+hw,y);oc.scale(-1,1);oc.drawImage(hand,0,0,hw,hh)}else oc.drawImage(hand,px-tx,py-ty,hw,hh);oc.restore()}
make.onclick=async()=>{if(busy||!ready)return;if(!MediaRecorder||!out.captureStream){status.textContent='This browser cannot export this video.';return}busy=true;make.disabled=true;resultCard.classList.add('hide');status.textContent='Preparing full-resolution video…';let cs;try{await handReady;await start();const vw=source.videoWidth,vh=source.videoHeight,[w,h]=dims(vw,vh);out.width=w;out.height=h;quality(oc);fit(oc,source,w,h);const fps=30,lead=Math.max(1,Math.round(fps*LEAD)),buf=[],trk=tracker(vw,vh);cs=out.captureStream(fps);const as=await audio(),tracks=[...cs.getVideoTracks(),...(as?as.getAudioTracks():[])],m=mime(),br=bitrate(w,h,fps),opts=m?{mimeType:m,videoBitsPerSecond:br,audioBitsPerSecond:192000}:{videoBitsPerSecond:br,audioBitsPerSecond:192000},rec=new MediaRecorder(new MediaStream(tracks),opts),chunks=[];rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};const stopped=new Promise(r=>rec.onstop=r);rec.start(500);let ended=false;source.onended=()=>ended=true;await source.play();let last=-1,P=null;
while(!ended&&!source.ended){await new Promise(r=>source.requestVideoFrameCallback?source.requestVideoFrameCallback(()=>r()):setTimeout(r,34));if(source.currentTime===last)continue;last=source.currentTime;const cv=document.createElement('canvas');cv.width=w;cv.height=h;const ccx=cv.getContext('2d',{alpha:false});quality(ccx);const F=fit(ccx,source,w,h),t=trk();P=t.pos;buf.push({cv,F});if(buf.length>lead){const z=buf.shift();quality(oc);oc.drawImage(z.cv,0,0);if(P)drawHand(P,z.F,w,h)}status.textContent='Processing full resolution… '+Math.min(100,Math.round(source.currentTime/source.duration*100))+'%'}
while(buf.length){const z=buf.shift();quality(oc);oc.drawImage(z.cv,0,0);if(P)drawHand(P,z.F,w,h);await new Promise(r=>setTimeout(r,34))}rec.stop();await stopped;const blob=new Blob(chunks,{type:rec.mimeType||m||'video/webm'});if(resURL)URL.revokeObjectURL(resURL);resURL=URL.createObjectURL(blob);result.src=resURL;const ext=blob.type.includes('mp4')?'mp4':'webm';download.href=resURL;download.download='drawing-hand.'+ext;download.textContent='Download '+ext.toUpperCase();resultCard.classList.remove('hide');status.textContent='Finished at '+w+' × '+h+'.'}catch(e){console.error(e);status.textContent='Could not create video: '+e.message;status.classList.add('err')}finally{if(cs)cs.getTracks().forEach(t=>t.stop());busy=false;make.disabled=!ready}}
})();