export type RunState = {
  phase:"idle"|"waiting"|"running"|"pausing"|"paused"|"completed"|"error";
  processed:number; total:number; source:string; message:string;
};
type Job = {job_id:string;status:string};
type Batch = {job:Job;queued_orders:number;eligible_orders:number;batch_start:number;remaining_orders:number};
type Invoke = <T>(command:string,args?:Record<string,unknown>)=>Promise<T>;
export class InventaRun {
  state:RunState={phase:"idle",processed:0,total:0,source:"",message:"Выбери лист и начни разбор."};
  private inventoryDate:string|undefined;
  private active=false;
  private requesting=false;
  private job: {id:string;end:number;remaining:number}|null=null;
  private timer:ReturnType<typeof setTimeout>|undefined;
  constructor(private invoke:Invoke,private changed:(state:RunState)=>void,private delay=2000){}
  private update(patch:Partial<RunState>){this.state={...this.state,...patch};this.changed({...this.state});}
  async start(source:string, inventoryDate?:string){
    if(this.active||this.requesting)return;
    if(this.job && (source!==this.state.source||inventoryDate!==this.inventoryDate))return;
    this.active=true;
    if(source!==this.state.source||inventoryDate!==this.inventoryDate)this.update({processed:0,total:0});
    this.inventoryDate=inventoryDate;
    this.update({source,message:"Читаю лист и готовлю очередь…"});
    if(this.job){this.update({phase:"waiting"});return;}
    await this.next();
  }
  async restart(source:string, inventoryDate?:string){
    if(this.active||this.requesting||this.job)return;
    this.requesting=true;
    try{
      await this.invoke("reset_inventa_order_batch",{spreadsheetUrl:source});
      this.update({processed:0,total:0});
    }catch(error){this.fail(String(error));return;}
    finally{this.requesting=false;}
    await this.start(source,inventoryDate);
  }
  pause(){
    this.active=false;
    this.update({phase:this.job||this.requesting?"pausing":"paused",
      message:this.job||this.requesting?"Текущая партия завершится; новые заказы не запускаются.":"Разбор на паузе. Можно продолжить с сохранённого места."});
  }
  dispose(){this.active=false;clearTimeout(this.timer);}
  private fail(message:string){this.active=false;this.job=null;this.update({phase:"error",message});}
  private async next(){
    if(!this.active||this.requesting)return;
    this.requesting=true;
    this.update({phase:"waiting"});
    try{
      const batch=await this.invoke<Batch>("check_inventa_order_batch",{spreadsheetUrl:this.state.source,inventoryDate:this.inventoryDate||null});
      if(!batch.job?.job_id||batch.queued_orders<1)throw Error("Некорректный ответ очереди");
      // A changed/reordered sheet must not silently restart an ongoing run.
      if(this.state.processed>batch.batch_start && this.state.source){
        this.active=false;
        this.update({message:"Список строк изменился. Завершаю текущую партию и ставлю разбор на паузу."});
      }
      this.job={id:batch.job.job_id,end:batch.batch_start+batch.queued_orders,remaining:batch.remaining_orders};
      this.update({processed:batch.batch_start,total:batch.eligible_orders,phase:this.active?"waiting":"pausing",
        message:this.active?"Ожидаю Browser Bridge. Он проверяет очередь примерно раз в минуту.":"После текущей партии разбор будет приостановлен."});
      this.schedule();
    }catch(error){
      if(String(error).includes("inventa_batch_complete")){
        this.active=false;this.update({phase:"completed",processed:this.state.total,message:"Этот список уже проходил сверку. Нажми «Начать заново», чтобы проверить его повторно."});
      }else this.fail(String(error));
    }finally{this.requesting=false;}
  }
  private schedule(){clearTimeout(this.timer);this.timer=setTimeout(()=>void this.poll(),this.delay);}
  private async poll(){
    if(!this.job)return;
    try{
      const data=await this.invoke<{browser_audit_job:Job|null}>("get_dashboard");
      const current=data.browser_audit_job;
      if(!current||current.job_id!==this.job.id){this.fail("Очередь изменилась. Нажми «Продолжить», чтобы сверить сохранённую позицию.");return;}
      if(current.status==="completed"){
        const completed=this.job;this.job=null;
        this.update({processed:completed.end});
        if(!completed.remaining){this.active=false;this.update({phase:"completed",message:"Разбор листа завершён. Запись результатов в таблицу ещё не подключена."});return;}
        if(this.active)await this.next();
        else this.update({phase:"paused",message:"Пауза. Проверенная позиция сохранена; продолжение не пропустит строки."});
      }else if(["failed","expired"].includes(current.status)){
        this.fail(current.status==="expired"?"Browser Bridge не ответил. Проверь расширение и разрешения, затем продолжи.":"Не удалось проверить текущую партию. Проверь результат в «Моей рабочей среде» и продолжи — позиция не сдвинута.");
      }else{
        this.update({phase:this.active?(current.status==="running"?"running":"waiting"):"pausing",
          message:!this.active?"Завершаю текущую партию перед паузой.":current.status==="running"?"Проверяю DataLens и Asgard…":"Ожидаю Browser Bridge…"});
        this.schedule();
      }
    }catch(error){this.fail("Связь с агентом прервалась: "+String(error));}
  }
}
