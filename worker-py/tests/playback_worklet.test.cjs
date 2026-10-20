const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname,'../web/playback-worklet.js'),'utf8');
function player(rate=48000) {
  let Processor; const messages=[];
  vm.runInNewContext(code, {sampleRate:rate, Float32Array,
    AudioWorkletProcessor:class {constructor(){this.port={postMessage:m=>messages.push(m)};}},
    registerProcessor:(_,p)=>{Processor=p;}});
  const p=new Processor();
  return {p,messages,send:data=>p.port.onmessage({data}),
    render(){const out=new Float32Array(128); p.process([],[[out]]); return out;}};
}
for (const rate of [44100,48000]) test(`continuous resampling at ${rate}Hz preserves a tone across jittered 20ms boundaries`,()=>{
  const f=player(rate), frames=100, result=[];
  const frame=i=>Float32Array.from({length:480},(_,j)=>0.2*Math.sin(2*Math.PI*440*(i*480+j)/24000));
  let next=0, rendered=0;
  for (;next<4;next++) f.send({type:'audio',epoch:0,samples:frame(next)});
  // Later frames arrive with up to 15ms network/event-loop jitter. The initial
  // 80ms reserve should absorb this without gaps or sample duplication.
  while (!f.messages.some(m=>m.type==='drained') && rendered<rate*3) {
    const now=rendered/rate;
    while (next<frames && now>= (next-3)*0.02 + [0,0.015,-0.005,0.01][next%4]) {
      f.send({type:'audio',epoch:0,samples:frame(next++)});
      if (next===frames) f.send({type:'finish',epoch:0});
    }
    result.push(...f.render()); rendered+=128;
  }
  assert.equal(f.messages.filter(m=>m.type==='started').length,1);
  assert.equal(f.messages.filter(m=>m.type==='underrun').length,0);
  assert.equal(f.messages.filter(m=>m.type==='drained').length,1);
  // Exclude the intentional 3ms attack and final fade. Compare to the analytic
  // signal, not to another implementation of our resampler.
  let maxError=0, maxStep=0;
  for (let i=Math.ceil(rate*0.005);i<Math.floor(rate*1.99);i++) {
    maxError=Math.max(maxError,Math.abs(result[i]-0.2*Math.sin(2*Math.PI*440*i/rate)));
    maxStep=Math.max(maxStep,Math.abs(result[i]-result[i-1]));
  }
  assert.ok(maxError<0.0004,`tone error ${maxError}`);
  assert.ok(maxStep<0.014,`chunk-boundary discontinuity ${maxStep}`);
});
test('a short final response drains even below the startup threshold',()=>{
  const f=player();
  f.send({type:'audio',epoch:0,samples:new Float32Array(240).fill(0.2)});
  for(let i=0;i<4;i++) assert.ok(f.render().every(v=>v===0));
  f.send({type:'finish',epoch:0});
  for(let i=0;i<10;i++) f.render();
  assert.equal(f.messages.filter(m=>m.type==='started').length,1);
  assert.equal(f.messages.filter(m=>m.type==='drained').length,1);
});
test('real underruns fade to silence, rebuffer and count once per episode',()=>{
  const f=player();
  for(let i=0;i<4;i++) f.send({type:'audio',epoch:0,samples:new Float32Array(480).fill(0.2)});
  let last=0, maxStep=0;
  for(let i=0;i<60;i++) for(const value of f.render()) {maxStep=Math.max(maxStep,Math.abs(value-last));last=value;}
  assert.equal(f.messages.filter(m=>m.type==='underrun').length,1);
  assert.ok(maxStep<0.002,`hard underrun edge ${maxStep}`);
  assert.equal(last,0);
  for(let i=0;i<4;i++) f.send({type:'audio',epoch:0,samples:new Float32Array(480).fill(0.2)});
  f.render();
  assert.equal(f.messages.filter(m=>m.type==='started').length,2);
});
test('interruption clears buffered speech and rejects old-epoch audio',()=>{
  const f=player();
  for(let i=0;i<4;i++) f.send({type:'audio',epoch:0,samples:new Float32Array(480).fill(0.2)});
  f.render();
  f.send({type:'reset',epoch:1});
  f.send({type:'audio',epoch:0,samples:new Float32Array(480).fill(-0.9)});
  for(let i=0;i<4;i++) f.render();
  assert.ok(f.render().every(v=>v===0));
  assert.equal(f.p.write,0);
  assert.equal(f.p.read,0);
});
test('ring buffer overflow is explicit rather than dropping speech',()=>{
  const f=player();
  for(let i=0;i<151;i++) f.send({type:'audio',epoch:0,samples:new Float32Array(480)});
  assert.equal(f.messages.filter(m=>m.type==='error').length,1);
  assert.equal(f.p.write-f.p.read,72000);
});
