/* Browser capture v1: mono 32 kHz PCM16; no inference or audible monitoring. */
class PantherPcmCapture extends AudioWorkletProcessor {
  constructor() {
    super(); this.buffer = new Int16Array(480000); this.count = 0; this.partCount = 0; this.active = true; this.meterFrames = 0;
    this.port.onmessage = event => {
      if (event.data === 'stop') { this.active = false; this.flush(); this.port.postMessage({type:'stopped'}); }
    };
  }
  flush() {
    if (!this.count) return;
    const samples = this.buffer.slice(0,this.count); this.port.postMessage({type:'part',samples:samples.buffer},[samples.buffer]); this.count = 0;
    if (++this.partCount >= 1000) { this.active = false; this.port.postMessage({type:'stopped'}); }
  }
  process(inputs) {
    if (!this.active) return false;
    const input = inputs[0]?.[0]; if (!input) return true;
    let peak = 0;
    for(const value of input) {
      const sample = Math.max(-1,Math.min(1,value)); peak = Math.max(peak,Math.abs(sample));
      this.buffer[this.count++] = Math.round(sample * (sample < 0 ? 32768 : 32767));
      if(this.count === this.buffer.length) {this.flush();if(!this.active) break;}
    }
    this.meterFrames += input.length;
    if(this.meterFrames >= 3200) { this.meterFrames = 0; this.port.postMessage({type:'level',peak}); }
    return true;
  }
}
registerProcessor('panther-pcm-capture-v1',PantherPcmCapture);
