import {useMemo,useState} from "react";
import {invoke} from "@tauri-apps/api/core";
import {ClipboardCopy, ClipboardList, ShieldCheck} from "lucide-react";

type Decision = {
  decision:"found"|"asgard"|"manual_review";
  proposed_status:string|null;
  comment:string|null;
  color:"green"|"orange"|"neutral";
  reason_code:string;
  evidence:Record<string,string|null>;
  write_enabled:false;
};
type BatchResponse={
  results:{index:number;source_row:number|null;cargo_place:string;inventory_date:string;proposal:Decision}[];
  summary:{found:number;in_progress:number;manual_review:number};
  total:number;read_only:true;source:"manual_input";write_enabled:false;
};
type BatchInput={
  source_row:number;
  order:{cargo_place:string;inventory_date:string};
  datalens_scans:{main_partner_code_original:string;sc_id:string;result:string;scanned_at:string}[];
  asgard_record:{status:string;box_id?:string;extended_history_statuses?:string[]}|null;
};
const headers=["Грузоместо","Дата инвента","Дата скана","SC ID","Результат скана","Статус Asgard","ID коробки","История проверена","Выдан в истории"];
const demo=[
  ["TEST-BOX-001","26.09.2026","01.10.2026 09:20","101366","OK","","","",""],
  ["TEST-BOX-002","12.09.2026","06.09.2026 08:00","101366","OK","Принят на ФФ","","",""],
  ["TEST-BOX-003","12.09.2026","06.09.2026 08:00","101366","OK","В пути","BOX-003","да","да"],
  ["TEST-BOX-004","12.09.2026","","","","","","",""]
].map(row=>row.join("\t")).join("\n");
const date=(value:string):string=>{
  const v=value.trim();
  if(/^\d{4}-\d{2}-\d{2}$/.test(v)){
    const parsed=new Date(v+"T00:00:00Z");
    if(!Number.isNaN(parsed.getTime())&&parsed.toISOString().startsWith(v))return v;
  }
  const match=/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(v);
  if(match){
    const iso=match[3]+"-"+match[2].padStart(2,"0")+"-"+match[1].padStart(2,"0");
    return date(iso);
  }
  throw new Error("Неправильная дата «"+v+"» — используйте ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.");
};
const scanDate=(value:string):string=>{
  const v=value.trim();
  const match=/^(\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(v);
  if(!match)throw new Error("Неправильная дата скана «"+v+"» — нужна дата и время.");
  const h=Number(match[2]),m=Number(match[3]),s=Number(match[4]??"0");
  if(h>23||m>59||s>59)throw new Error("Некорректное время скана: "+v);
  return date(match[1])+"T"+match[2]+":"+match[3]+":"+(match[4]??"00");
};
const checked=(v:string, field:string):boolean=>{
  const text=v.trim().toLowerCase();
  if(!text||text==="нет"||text==="0"||text==="no")return false;
  if(text==="да"||text==="1"||text==="yes")return true;
  throw new Error("Поле «"+field+"» должно содержать «да», «нет» или быть пустым.");
};
const parseRows=(raw:string):BatchInput[]=>{
  const lines=raw.replace(/\r\n?/g,"\n").split("\n").filter(line=>line.trim());
  if(lines.length===0)throw new Error("Вставьте хотя бы одну строку из Excel.");
  const body=lines[0].startsWith("Грузоместо\t")?lines.slice(1):lines;
  if(body.length<1||body.length>100)throw new Error("Допускается от 1 до 100 строк за одну проверку.");
  return body.map((line,i)=>{
    const cells=line.split("\t").map(v=>v.trim());
    if(cells.length<2||cells.length>9)throw new Error("Строка "+(i+1)+": ожидается от 2 до 9 столбцов, разделённых табуляцией.");
    const [cargo,inv,scanned="",sc="",result="",status="",box="",history="",issued=""]=cells;
    if(!cargo||cargo.length>128||/[\r\n\u0000-\u001f]/.test(cargo))throw new Error("Строка "+(i+1)+": укажите штрихкод грузоместа (не более 128 символов).");
    let normalizedDate:string,normalizedScan="";
    try{normalizedDate=date(inv);if(scanned)normalizedScan=scanDate(scanned);}catch(e){throw new Error("Строка "+(i+1)+": "+String(e));}
    if(scanned&&(!sc||!result))throw new Error("Строка "+(i+1)+": для скана обязательно укажите SC ID и результат (OK или ERROR).");
    if(result&&!["OK","ERROR"].includes(result))throw new Error("Строка "+(i+1)+": результат скана должен быть OK или ERROR.");
    if(status.length>120)throw new Error("Строка "+(i+1)+": статус Asgard слишком длинный.");
    let verified=false,wasIssued=false;
    try{verified=checked(history,"История проверена");wasIssued=checked(issued,"Выдан в истории");}catch(e){throw new Error("Строка "+(i+1)+": "+String(e));}
    if(wasIssued&&!verified)throw new Error("Строка "+(i+1)+": нельзя отметить «Выдан в истории», не подтвердив её просмотр.");
    if(box.length>100)throw new Error("Строка "+(i+1)+": ID коробки слишком длинный.");
    return {
      source_row:i+1,
      order:{cargo_place:cargo,inventory_date:normalizedDate},
      datalens_scans:normalizedScan?[{main_partner_code_original:cargo,sc_id:sc,result:result,scanned_at:normalizedScan}]:[],
      asgard_record:status?{
        status,...(status==="В пути"?{box_id:box,...(verified?{extended_history_statuses:wasIssued?["Выдан"]:[]}:{})}:{})
      }:null
    };
  });
};
const safeCell=(value:unknown):string=>{
  const text=String(value??"").replace(/[\t\r\n]/g," ");
  // Excel interprets leading =, +, -, @ as formulas. Force a text cell.
  return /^[\s]*[=+\-@]/.test(text)?"'"+text:text;
};
const report=(batch:BatchResponse):string=>{
  const rows=[["Строка","Грузоместо","Дата инвента","Предложенный статус","Комментарий","Цвет","Решение","Причина","Дата скана","SC ID"]];
  for(const row of batch.results){
    const p=row.proposal;
    rows.push([
      String(row.source_row??row.index),row.cargo_place,row.inventory_date,
      p.proposed_status??"",p.comment??"",
      p.color==="green"?"Зелёный":p.color==="orange"?"Оранжевый":"Без изменения",
      p.decision==="found"?"Найден":p.decision==="asgard"?"В работе":"Ручная проверка",
      p.reason_code,p.evidence.scan_date??"",p.evidence.sc_id??""
    ]);
  }
  return rows.map(row=>row.map(safeCell).join("\t")).join("\r\n");
};

export function OrderBatchPage({connected}:{connected:boolean}){
  const [input,setInput]=useState("");
  const [batch,setBatch]=useState<BatchResponse|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const count=useMemo(()=>input.trim()?input.trim().split(/\r?\n/).filter(Boolean).length:0,[input]);
  const check=async()=>{
    setBusy(true);setError("");setNotice("");setBatch(null);
    try{
      const rows=parseRows(input);
      const response=await invoke<BatchResponse>("preview_order_batch",{rows});
      if(!response.read_only||response.write_enabled!==false)throw new Error("Сервер не подтвердил режим только чтения.");
      setBatch(response);
    }catch(e){setError(String(e));}
    finally{setBusy(false);}
  };
  const copy=async()=>{
    if(!batch)return;
    try{await navigator.clipboard.writeText(report(batch));setNotice("Таблица скопирована. Вставьте её в новый лист Excel (Ctrl+V).");}
    catch{setError("Не удалось скопировать таблицу. Проверьте разрешение буфера обмена.");}
  };
  return <section className="page order-batch-page">
    <div className="page-head"><div><div className="eyebrow">РАБОЧИЕ НАВЫКИ · ПАКЕТНАЯ ПРОВЕРКА</div><h1>Проверка списка заказов</h1><p>До 100 грузомест, одна сводка и копирование результатов в Excel.</p></div></div>
    <div className="sources-notice"><ShieldCheck size={17}/><span>Только ручной ввод и предварительный расчёт. Никаких запросов к Google, DataLens или Asgard, записи в ИНВенту и сохранения грузомест в задачи. Данные остаются в текущем окне приложения.</span></div>
    <div className="panel batch-input-card">
      <div className="panel-head"><div><h3>Данные из Excel</h3><p>Вставьте выделенные строки с табуляцией между столбцами. Первая строка с названиями столбцов необязательна.</p></div><button className="secondary" onClick={()=>{setInput(demo);setBatch(null);setError("");setNotice("");}} disabled={busy}>Тестовый пример</button></div>
      <div className="batch-cols">{headers.map((h,i)=><span key={h}>{i+1}. {h}</span>)}</div>
      <textarea aria-label="Строки грузомест из Excel" value={input} onChange={e=>{setInput(e.target.value);setBatch(null);setError("");setNotice("");}} placeholder="Вставьте строки из Excel (Ctrl+V). Даты: ДД.ММ.ГГГГ, время скана: ДД.ММ.ГГГГ ЧЧ:ММ." rows={7} spellCheck={false} maxLength={100000}/>
      <div className="batch-actions"><small>{count} строк (максимум 100). Если скана нет, оставьте его дату пустой. Новый статус Asgard можно указать текстом — Malenia направит его на ручную проверку.</small><button className="primary" disabled={!connected||busy||!input.trim()} onClick={()=>void check()}><ClipboardList size={15}/>{busy?"Проверяем…":"Проверить список"}</button></div>
      {!connected?<p className="source-help">Запустите локальный агент на главной странице.</p>:null}
    </div>
    {error?<p role="alert" className="alert error">{error}</p>:null}
    {notice?<p role="status" className="alert success">{notice}</p>:null}
    {batch?<div className="panel batch-results">
      <div className="panel-head"><div><h3>Сводка предложений</h3><p>Ни одна строка в исходном Excel не изменена.</p></div><button className="secondary" onClick={()=>void copy()}><ClipboardCopy size={14}/> Скопировать для Excel</button></div>
      <div className="batch-summary"><span className="green">Найдено: {batch.summary.found}</span><span className="orange">В работе: {batch.summary.in_progress}</span><span>Ручная проверка: {batch.summary.manual_review}</span><b>Всего: {batch.total}</b></div>
      <div className="batch-table-scroll"><table><thead><tr><th>№</th><th>Грузоместо</th><th>Дата инвента</th><th>Статус</th><th>Комментарий</th><th>Причина</th></tr></thead><tbody>{batch.results.map(row=><tr key={row.index}><td>{row.source_row??row.index}</td><td>{row.cargo_place}</td><td>{row.inventory_date}</td><td><span className={"order-result-state "+row.proposal.color}>{row.proposal.proposed_status??"Ручная проверка"}</span></td><td>{row.proposal.comment??"—"}</td><td>{row.proposal.reason_code}</td></tr>)}</tbody></table></div>
      <p className="batch-footnote">Это предложения, рассчитанные по вручную внесённым данным. Перед использованием проверьте соответствие сканов грузоместам и правильность источников.</p>
    </div>:null}
  </section>;
}
