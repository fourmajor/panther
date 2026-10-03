// Real-time preview is a separate 24 kHz stream. Closed 32 kHz originals and
// the independent full transcription remain owned by the recording pipeline.
export class LiveTranscription {
 constructor({onText,onError,onProviderEvent,onOrder}){this.onText=onText;this.onError=onError;this.onProviderEvent=onProviderEvent;this.onOrder=onOrder;this.predecessors=new Map();this.pendingTurns=new Set();this.completedTurns=new Set();this.awaitingCommits=0;this.items=new Map();this.frames=[];this.speech=false;this.silence=0;this.samples=0;this.noise=.001;this.closed=false;}
 async connect(credentials){
  if(credentials.model!=='gpt-live-transcribe'||typeof credentials.clientSecret!=='string'||!credentials.clientSecret)throw new Error('Live transcription unavailable');
  const socket=this.socket=new WebSocket('wss://api.openai.com/v1/realtime?intent=transcription',['realtime','openai-insecure-api-key.'+credentials.clientSecret]);
  await new Promise((resolve,reject)=>{
   let ready=false;const timeout=setTimeout(()=>{socket.close();reject(new Error('Live transcription connection timed out'));},12000);
   const fail=()=>{if(this.closed)return;this.failed=true;this.drainAbort?.();clearTimeout(timeout);if(!ready)reject(new Error('Live transcription disconnected'));else if(!this.closed)this.onError();};
   socket.addEventListener('error',fail);socket.addEventListener('close',fail);
   const session=credentials.session||{type:'transcription',audio:{input:{format:{type:'audio/pcm',rate:24000},transcription:{model:'gpt-live-transcribe',languages:['en'],delay:'low'},turn_detection:null,noise_reduction:{type:'far_field'}}}};
   socket.addEventListener('open',()=>socket.send(JSON.stringify({type:'session.update',session})));

   socket.addEventListener('message',event=>{
    let data;try{data=JSON.parse(event.data);}catch{return;}
    if(['session.created','session.updated','error','conversation.item.input_audio_transcription.delta','conversation.item.input_audio_transcription.completed','conversation.item.input_audio_transcription.failed','input_audio_buffer.committed'].includes(data.type))this.onProviderEvent?.(Object.fromEntries(['type','event_id','item_id','content_index','delta','transcript','error','session','previous_item_id','preceding_item_id','usage'].filter(key=>data[key]!==undefined).map(key=>[key,key==='error'?{type:data.error?.type,code:data.error?.code}:key==='session'?{id:data.session?.id,type:data.session?.type}:data[key]])));
    if(data.type==='input_audio_buffer.committed'){
     this.awaitingCommits=Math.max(0,this.awaitingCommits-1);if(typeof data.item_id==='string'){this.predecessors.set(data.item_id,data.previous_item_id??data.preceding_item_id??null);if(!this.completedTurns.has(data.item_id))this.pendingTurns.add(data.item_id);this.order();}this.drainCheck?.();
    }
    if(data.type==='conversation.item.input_audio_transcription.failed'){this.onError();this.pendingTurns.delete(data.item_id);this.failed=true;this.drainCheck?.();}
    if(data.type==='session.updated'){ready=true;clearTimeout(timeout);resolve();}
    if(data.type==='error'){fail();socket.close();return;}
    if(['conversation.item.input_audio_transcription.delta','conversation.item.input_audio_transcription.completed'].includes(data.type)){
     const id=data.item_id;if(typeof id!=='string')return;const prior=this.items.get(id)||'';const text=data.type.endsWith('.completed')?data.transcript:prior+(data.delta||'');if(typeof text!=='string')return;this.items.set(id,text);this.onText(id,text,data.type.endsWith('.completed'));if(data.type.endsWith('.completed')){this.completedTurns.add(id);this.pendingTurns.delete(id);this.drainCheck?.();}this.order();
    }
   });
  });
 }
 send(data){if(this.socket?.readyState===WebSocket.OPEN&&!this.closed)this.socket.send(JSON.stringify(data));}
 append(samples){const bytes=new Uint8Array(samples);let raw='';for(let offset=0;offset<bytes.length;offset+=8192)raw+=String.fromCharCode(...bytes.subarray(offset,offset+8192));this.send({type:'input_audio_buffer.append',audio:btoa(raw)});this.samples+=bytes.length/2;}
 audio(samples,rms){
  if(this.closed||this.socket?.readyState!==WebSocket.OPEN)return;
  const voiced=rms>Math.max(.004,this.noise*3.5),count=samples.byteLength/2;
  if(!this.speech){if(!voiced){this.noise=.98*this.noise+.02*Math.min(rms,.008);this.frames.push(samples);if(this.frames.length>3)this.frames.shift();return;}this.speech=true;for(const frame of this.frames)this.append(frame);this.frames=[];}
  this.append(samples);this.silence=voiced?0:this.silence+count;
  if(this.silence>=16800||this.samples>=720000)this.commit();
 }
 commit(){if(this.samples>=2400){this.awaitingCommits++;this.send({type:'input_audio_buffer.commit'});}this.samples=0;this.silence=0;this.speech=false;this.frames=[];}
 pause(){this.commit();}
 order(){const ordered=[],seen=new Set();const place=id=>{if(seen.has(id))return;seen.add(id);const before=this.predecessors.get(id);if(before&&this.predecessors.has(before))place(before);ordered.push(id);};for(const id of this.predecessors.keys())place(id);for(const id of this.items.keys())if(!seen.has(id))ordered.push(id);this.onOrder?.(ordered);}
 async finish(){this.commit();if((this.awaitingCommits||this.pendingTurns.size)&&this.socket?.readyState===WebSocket.OPEN)await new Promise(resolve=>{const timeout=setTimeout(resolve,10000);this.drainAbort=()=>{clearTimeout(timeout);resolve();};this.drainCheck=()=>{if(!this.awaitingCommits&&!this.pendingTurns.size){clearTimeout(timeout);resolve();}};this.drainCheck();});const complete=!this.failed&&!this.awaitingCommits&&!this.pendingTurns.size;this.close();return {complete,pendingTurns:this.awaitingCommits+this.pendingTurns.size};}
 close(){this.closed=true;this.socket?.close();this.frames=[];}
}
