import {useState} from "react";
import {invoke} from "@tauri-apps/api/core";
import {CheckCircle2, ClipboardCheck, Info, ShieldCheck} from "lucide-react";

type Proposal = {
  decision:"found"|"asgard"|"manual_review";
  proposed_status:string|null;
  comment:string|null;
  color:"green"|"orange"|"neutral";
  reason_code:string;
  evidence:Record<string,string|null>;
  write_enabled:false;
};
type Preview = {proposal:Proposal;read_only:true;source:"manual_input"};

const reasons:Record<string,string>={
  successful_scan_after_inventory:"Успешный скан на нужном СЦ позднее даты инвентаризации",
  asgard_accepted_at_fulfillment:"По данным, введённым из Asgard, грузоместо принято на ФФ",
  asgard_issued:"По данным, введённым из Asgard, грузоместо выдано",
  asgard_in_transit_with_issued_box_history:"Статус «В пути», в расширенной истории коробки присутствует «Выдан»",
  asgard_record_required:"Нет подтверждённого скана после инвентаризации. Нужны данные из Asgard",
  asgard_box_id_required_for_in_transit:"Для «В пути» нужно открыть ID коробки в Asgard",
  asgard_extended_history_required_for_in_transit:"Для «В пути» требуется расширенная история коробки",
  asgard_in_transit_without_confirmed_issued_history:"В расширенной истории коробки нет подтверждения «Выдан»",
  datalens_matching_scan_has_invalid_date:"Дата скана некорректна. Нужна ручная проверка",
  unknown_asgard_status:"Этот статус Asgard ещё не обучен. Нужна ручная проверка",
};
const dateTimeToIso=(value:string)=>value ? value.replace("T"," ") : "";

export function OrderCheckPage({connected}:{connected:boolean}){
  const [cargoPlace,setCargoPlace]=useState("");
  const [inventoryDate,setInventoryDate]=useState("");
  const [scanDate,setScanDate]=useState("");
  const [scanSc,setScanSc]=useState("101366");
  const [scanResult,setScanResult]=useState("OK");
  const [asgardStatus,setAsgardStatus]=useState("");
  const [boxId,setBoxId]=useState("");
  const [issuedInHistory,setIssuedInHistory]=useState(false);
  const [historyChecked,setHistoryChecked]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [preview,setPreview]=useState<Preview|null>(null);

  const clear=()=>{setPreview(null);setError("");};
  const useDemo=()=>{
    setCargoPlace("TEST-BOX-001");
    setInventoryDate("2026-09-26");
    setScanDate("2026-10-01T09:20");
    setScanSc("101366");
    setScanResult("OK");
    setAsgardStatus("");
    setBoxId("");
    setHistoryChecked(false);
    setIssuedInHistory(false);
    setPreview(null);
    setError("");
  };

  const check=async()=>{
    setBusy(true);setError("");setPreview(null);
    try{
      const scans=scanDate.trim()?[{
        main_partner_code_original:cargoPlace.trim(),
        sc_id:scanSc,
        result:scanResult,
        scanned_at:dateTimeToIso(scanDate)
      }]:[];
      const asgard=asgardStatus?{
        status:asgardStatus,
        ...(asgardStatus==="В пути"?{
          box_id:boxId.trim(),
          ...(historyChecked?{extended_history_statuses:issuedInHistory?["Выдан"]:[]}:{})
        }:{})
      }:null;
      const result=await invoke<Preview>("preview_order",{
        order:{cargo_place:cargoPlace.trim(),inventory_date:inventoryDate},
        datalensScans:scans,
        asgardRecord:asgard
      });
      setPreview(result);
    }catch(reason){setError(String(reason));}
    finally{setBusy(false);}
  };
  const outcome=preview?.proposal;
  return <section className="page order-check-page" aria-labelledby="order-check-title">
    <div className="page-head"><div><div className="eyebrow">РАБОЧИЕ НАВЫКИ · ПРЕДПРОСМОТР</div><h1 id="order-check-title">Проверка заказа</h1><p>Разбираем вручную введённые сведения по правилам ИНВенты, DataLens и Asgard.</p></div></div>
    <div className="sources-notice"><ShieldCheck size={17}/><span><b>Безопасный режим.</b> Пока нет автоматического доступа к ИНВенте, DataLens или Asgard. Malenia ничего не отправляет в эти системы, не меняет строки и не сохраняет введённый номер в историю задач. Вводи сведения только из источников, к которым у тебя есть разрешённый доступ.</span></div>
    <div className="order-work-grid">
      <div className="panel order-input-card">
        <div className="order-card-heading"><h2>1. Строка ИНВенты</h2><button className="secondary" type="button" onClick={useDemo} disabled={busy}>Тестовый пример</button></div>
        <label>Штрихкод грузоместа (main_partner_code_original)<input value={cargoPlace} maxLength={128} onChange={e=>{setCargoPlace(e.target.value);clear();}} placeholder="Например, штрихкод коробки" spellCheck={false}/></label>
        <label>Дата инвентаризации<input type="date" value={inventoryDate} onChange={e=>{setInventoryDate(e.target.value);clear();}}/></label>
        <h2>2. Последний скан DataLens</h2>
        <p>Если успешного скана нет, оставь дату пустой. При нескольких сканах сначала выбери самый поздний успешный скан нужного грузоместа.</p>
        <label>Дата и время скана<input type="datetime-local" value={scanDate} onChange={e=>{setScanDate(e.target.value);clear();}}/></label>
        <div className="order-inline">
          <label>SC ID<input value={scanSc} maxLength={20} onChange={e=>{setScanSc(e.target.value);clear();}} spellCheck={false}/></label>
          <label>Результат<select value={scanResult} onChange={e=>{setScanResult(e.target.value);clear();}}><option value="OK">OK</option><option value="ERROR">ERROR / неуспешный</option></select></label>
        </div>
        <h2>3. Asgard (если скан не подтвердил находку)</h2>
        <label>Статус грузоместа<select value={asgardStatus} onChange={e=>{setAsgardStatus(e.target.value);clear();}}><option value="">Не проверял</option><option value="Принят на ФФ">Принят на ФФ</option><option value="Выдан">Выдан</option><option value="В пути">В пути</option><option value="Неизвестный">Другой / неизвестный</option></select></label>
        {asgardStatus==="В пути"?<div className="order-history">
          <label>ID коробки<input value={boxId} maxLength={100} onChange={e=>{setBoxId(e.target.value);clear();}} placeholder="После перехода по ID коробки"/></label>
          <label className="order-checkbox"><input type="checkbox" checked={historyChecked} onChange={e=>{setHistoryChecked(e.target.checked);clear();}}/> Расширенная история открыта и проверена</label>
          {historyChecked?<label className="order-checkbox"><input type="checkbox" checked={issuedInHistory} onChange={e=>{setIssuedInHistory(e.target.checked);clear();}}/> В истории есть статус «Выдан»</label>:null}
        </div>:null}
        <button className="primary order-check-button" onClick={()=>void check()} disabled={!connected||busy||!cargoPlace.trim()||!inventoryDate}>{busy?"Проверяем…":"Проверить по правилам"} <ClipboardCheck size={15}/></button>
        {!connected?<p className="source-help">Чтобы проверить заказ, запусти локальный агент на главной странице.</p>:null}
      </div>
      <div className="panel order-result-card">
        <h2>Предлагаемый результат</h2>
        {!preview?<div className="order-result-empty"><Info size={23}/><b>Пока нет проверки</b><p>Заполни данные слева. Результат будет рассчитан локальным модулем правил.</p></div>:
          <div className="order-result">
            <span className={"order-result-state "+outcome?.color}>{outcome?.decision==="found"?"Найден":outcome?.decision==="asgard"?"В работе":"Ручная проверка"}</span>
            <p>{reasons[outcome?.reason_code??""]??"Недостаточно проверенных данных"}</p>
            <dl>
              <div><dt>Предлагаемый статус</dt><dd>{outcome?.proposed_status??"Не назначен"}</dd></div>
              <div><dt>Комментарий</dt><dd>{outcome?.comment??"Не назначен"}</dd></div>
              <div><dt>Цвет строки</dt><dd>{outcome?.color==="green"?"Зелёный":outcome?.color==="orange"?"Оранжевый":"Без изменения"}</dd></div>
              {outcome?.evidence.scan_date?<div><dt>Дата скана</dt><dd>{outcome.evidence.scan_date}</dd></div>:null}
              {outcome?.evidence.sc_id?<div><dt>СЦ</dt><dd>{outcome.evidence.sc_id}</dd></div>:null}
            </dl>
            <div className="order-readonly"><CheckCircle2 size={16}/> Это только предложение. Строка в ИНВенте не изменена.</div>
          </div>}
        {error?<p className="alert error" role="alert">{error}</p>:null}
      </div>
    </div>
  </section>;
}
