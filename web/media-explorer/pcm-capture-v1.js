/* Browser capture v1: mono 32 kHz PCM16; no inference or audible monitoring. */
class PantherPcmCapture extends AudioWorkletProcessor {
  constructor() {
    super(); this.buffer = new Int16Array(480000); this.count = 0; this.partCount = 0; this.active = true; this.meterFrames = 0; this.peak = 0;
    // A bounded FIR suppresses frequencies above the 24 kHz stream's Nyquist
    // limit. The original capture path below is untouched.
    this.liveBuffer=new Int16Array(2400);this.liveCount=0;this.livePower=0;this.history=new Float32Array(32);this.historyAt=0;this.phase=0;this.previousFiltered=0;
    this.filter=Array.from({length:32},(_,i)=>{const x=i-15.5,cutoff=.3375;return (Math.sin(2*Math.PI*cutoff*x)/(Math.PI*x))*(.54-.46*Math.cos(2*Math.PI*i/31));});const sum=this.filter.reduce((a,b)=>a+b,0);this.filter=this.filter.map(v=>v/sum);
    this.port.onmessage = event => {
      if(event.data==='live-boundary'){this.flushLive();this.port.postMessage({type:'live-boundary'});}
      if (event.data === 'stop') { this.active = false; this.flushLive(); this.flush(); this.port.postMessage({type:'stopped'}); }
    };
  }
  flush() {
    if (!this.count) return;
    const samples = this.buffer.slice(0,this.count); this.port.postMessage({type:'part',samples:samples.buffer},[samples.buffer]); this.count = 0;
    if (++this.partCount >= 1000) { this.active = false; this.port.postMessage({type:'stopped'}); }
  }
  flushLive(){if(!this.liveCount)return;const samples=this.liveBuffer.slice(0,this.liveCount);this.port.postMessage({type:'live-audio',samples:samples.buffer,rms:Math.sqrt(this.livePower/this.liveCount)},[samples.buffer]);this.liveCount=0;this.livePower=0;}
  live(sample){
    this.history[this.historyAt]=sample;this.historyAt=(this.historyAt+1)%32;
    let filtered=0;for(let i=0;i<32;i++)filtered+=this.history[(this.historyAt+31-i)%32]*this.filter[i];
    this.phase+=3;if(this.phase>=4){this.phase-=4;const fraction=1-this.phase/3;const value=Math.max(-1,Math.min(1,this.previousFiltered+(filtered-this.previousFiltered)*fraction));this.liveBuffer[this.liveCount++]=Math.round(value*(value<0?32768:32767));this.livePower+=value*value;if(this.liveCount===this.liveBuffer.length)this.flushLive();}
    this.previousFiltered=filtered;
  }

  process(inputs) {
    if (!this.active) return false;
    const input = inputs[0]?.[0]; if (!input) return true;
    let peak = 0;
    for(const value of input) {
      const sample = Math.max(-1,Math.min(1,value)); peak = Math.max(peak,Math.abs(sample));
      this.live(sample);
      this.buffer[this.count++] = Math.round(sample * (sample < 0 ? 32768 : 32767));
      if(this.count === this.buffer.length) {this.flush();if(!this.active) break;}
    }
    this.peak = Math.max(this.peak, peak); this.meterFrames += input.length;
    if(this.meterFrames >= 3200) { this.meterFrames = 0; this.port.postMessage({type:'level',peak:this.peak}); this.peak = 0; }
    return true;
  }
}
registerProcessor('panther-pcm-capture-v1',PantherPcmCapture);
