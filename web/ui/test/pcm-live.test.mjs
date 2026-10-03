import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
test('24 kHz live side-channel preserves each original 32 kHz sample',()=>{
 const messages=[];let Processor;const scope={AudioWorkletProcessor:class{constructor(){this.port={postMessage:message=>messages.push(message)};}},Int16Array,Float32Array,Math,registerProcessor:(_name,value)=>Processor=value};vm.runInNewContext(readFileSync(new URL('../../media-explorer/pcm-capture-v1.js',import.meta.url),'utf8'),scope);const capture=new Processor(),input=new Float32Array(32000);for(let i=0;i<input.length;i++)input[i]=.25*Math.sin(2*Math.PI*440*i/32000);for(let i=0;i<input.length;i+=128)capture.process([[input.subarray(i,i+128)]]);capture.port.onmessage({data:'stop'});const part=new Int16Array(messages.find(message=>message.type==='part').samples);assert.equal(part.length,32000);for(let i=0;i<input.length;i++)assert.equal(part[i],Math.round(input[i]*(input[i]<0?32768:32767))||0);const live=messages.filter(message=>message.type==='live-audio');assert.equal(live.reduce((total,message)=>total+message.samples.byteLength/2,0),24000);assert.equal(live.length,10);assert(live.every(message=>message.samples.byteLength===4800&&message.rms>.1));assert.equal(messages.at(-1).type,'stopped');
});
