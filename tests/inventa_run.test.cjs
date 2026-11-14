const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const {createRequire}=require('node:module');
const ts=createRequire(path.resolve(__dirname,'../desktop/package.json'))('typescript');
const source=ts.transpileModule(fs.readFileSync(path.resolve(__dirname,'../desktop/src/inventaRun.ts'),'utf8'),
  {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function harness(){
  const timers=new Map();let seq=0,offset=0,requests=0,status='pending',latest;
  const exports={};vm.runInNewContext(source,{exports,setTimeout:fn=>{timers.set(++seq,fn);return seq;},clearTimeout:id=>timers.delete(id)});
  const states=[];
  const invoke=async command=>{
    if(command==='get_dashboard')return {browser_audit_job:latest?{...latest,status}:null};
    requests++;const start=offset;latest={job_id:'job-'+requests,status:'pending'};status='pending';
    return {job:latest,batch_start:start,queued_orders:Math.min(20,45-start),eligible_orders:45,remaining_orders:Math.max(0,45-start-20)};
  };
  const runner=new exports.InventaRun(invoke,state=>states.push(state));
  return {runner,states,get requests(){return requests;},
    setStatus(value){status=value;if(value==='completed')offset=Math.min(45,offset+20);},
    replaceJob(){latest={job_id:'some-other-job'};},
    async tick(){const [id,fn]=timers.entries().next().value||[];assert.ok(fn,'poll is scheduled');timers.delete(id);fn();await flush();},
    get timerCount(){return timers.size;}};
}
test('one start automatically checks the entire sheet and counts only acknowledged completions',async()=>{
  const h=harness();await h.runner.start('SHEET');
  assert.equal(h.requests,1);assert.equal(h.runner.state.processed,0);
  h.setStatus('running');await h.tick();assert.equal(h.requests,1);
  for(const done of [20,40,45]){
    h.setStatus('completed');await h.tick();assert.equal(h.runner.state.processed,done);
  }
  assert.equal(h.requests,3);assert.equal(h.runner.state.phase,'completed');assert.equal(h.timerCount,0);
});
test('pause finishes the current batch without starting another and resume continues',async()=>{
  const h=harness();await h.runner.start('SHEET');h.runner.pause();
  assert.equal(h.runner.state.phase,'pausing');
  h.setStatus('completed');await h.tick();assert.equal(h.requests,1);assert.equal(h.runner.state.phase,'paused');
  await h.runner.start('SHEET');assert.equal(h.requests,2);assert.equal(h.runner.state.processed,20);
  h.runner.dispose();
});
test('failed or replaced jobs stop continuation without counting the batch as processed',async()=>{
  for(const failure of ['failed','expired','replaced']){
    const h=harness();await h.runner.start('SHEET');
    if(failure==='replaced')h.replaceJob();else h.setStatus(failure);
    await h.tick();assert.equal(h.requests,1);assert.equal(h.runner.state.phase,'error');
    assert.equal(h.runner.state.processed,0);assert.equal(h.timerCount,0);
  }
});
test('duplicate clicks and switching sheets cannot enqueue concurrent jobs',async()=>{
  const h=harness();await h.runner.start('SHEET');await h.runner.start('SHEET');
  h.runner.pause();await h.runner.start('OTHER');assert.equal(h.requests,1);assert.equal(h.runner.state.source,'SHEET');
  h.runner.dispose();assert.equal(h.timerCount,0);
});
