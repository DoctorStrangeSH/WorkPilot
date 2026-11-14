import {useEffect,useRef,useState} from "react";
import {invoke} from "@tauri-apps/api/core";

type Skill={
  id:string;title:string;description:string;instructions:string;
  terms:string;status:"draft"|"approved";builtin:boolean
};
type Draft={request_id:string;title:string;description:string;instructions:string;terms:string};
const blank=():Draft=>({request_id:crypto.randomUUID(),title:"",description:"",instructions:"",terms:""});

export function SkillsPage({connected}:{connected:boolean}){
  const [items,setItems]=useState<Skill[]>([]);
  const [draft,setDraft]=useState<Draft|null>(null);
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState("");
  const active=useRef(false);
  const refresh=async()=>{
    if(!connected){setItems([]);return;}
    try{
      const result=await invoke<{skills:Skill[]}>("get_skills");
      setItems(result.skills);
    }catch{setNotice("Не удалось получить навыки локального агента.");}
  };
  useEffect(()=>{void refresh();},[connected]);
  const run=async(action:"draft"|"approve"|"delete",payload:object)=>{
    if(active.current||!connected)return;
    active.current=true;setBusy(true);setNotice("");
    try{
      await invoke("skill_action",{action,payload});
      if(action==="draft")setDraft(null);
      setNotice(action==="draft"?"Черновик сохранён. Проверьте его и утвердите.":action==="approve"?"Навык утверждён и доступен Шерлоку.":"Навык удалён.");
      await refresh();
    }catch{setNotice("Не удалось сохранить изменение. Проверьте данные и попробуйте ещё раз.");}
    finally{active.current=false;setBusy(false);}
  };
  return <section className="page" aria-label="Навыки Malenia">
    <div className="page-head"><div><div className="eyebrow">РАСШИРЯЕМАЯ СИСТЕМА</div>
      <h1>Навыки Malenia</h1>
      <p>Шерлок подбирает подходящие инструкции для разных задач, не только заказов.</p>
    </div></div>
    <p className="note">Навыки — это сохранённые способы решения задач, а не исполняемые программы. Они помогают модели планировать и рассуждать, но не дают ей новых прав. Новые навыки начинают работать только после вашего утверждения. Веса Qwen не переобучаются.</p>
    <div className="ai-controls"><button className="primary" disabled={!connected||busy||!!draft} onClick={()=>setDraft(blank())}>Создать навык</button>
      <button className="secondary" disabled={!connected||busy} onClick={()=>void refresh()}>Обновить</button></div>
    {draft?<div className="panel ai-task-review" aria-label="Новый навык">
      <h2>Новый навык</h2>
      <p>Опишите безопасный и повторяемый способ работы. Не вводите пароли, токены или персональные данные заказов.</p>
      <label>Название<input maxLength={80} value={draft.title} disabled={busy} onChange={e=>setDraft({...draft,title:e.target.value})}/></label>
      <label>Назначение<input maxLength={200} value={draft.description} disabled={busy} onChange={e=>setDraft({...draft,description:e.target.value})}/></label>
      <label>Правила выполнения<textarea rows={5} maxLength={1600} value={draft.instructions} disabled={busy} onChange={e=>setDraft({...draft,instructions:e.target.value})}/></label>
      <label>Ключевые слова<input maxLength={240} value={draft.terms} disabled={busy} onChange={e=>setDraft({...draft,terms:e.target.value})}/></label>
      <div className="ai-controls">
        <button className="secondary" disabled={busy} onClick={()=>setDraft(null)}>Отмена</button>
        <button className="primary" disabled={busy||!connected||![draft.title,draft.description,draft.instructions,draft.terms].every(v=>v.trim())} onClick={()=>void run("draft",draft)}>Сохранить черновик</button>
      </div>
    </div>:null}
    {notice?<p className="note" role="status">{notice}</p>:null}
    <div className="panel browser-panel">
      <div className="panel-head"><div><h3>Каталог навыков</h3><p>{items.filter(x=>x.status==="approved").length} активных · {items.filter(x=>x.status==="draft").length} черновиков</p></div></div>
      {items.length?items.map(item=><article className="browser-tab" key={item.id}>
        <div className="browser-tab-copy">
          <b>{item.title} · {item.status==="draft"?"Черновик":"Активен"}{item.builtin?" · Встроенный":""}</b>
          <p>{item.description}</p>
          <details><summary>Инструкции и ключевые слова</summary><p>{item.instructions}</p><small>{item.terms}</small></details>
          {!item.builtin?<div className="ai-controls">
            {item.status==="draft"?<button className="primary" disabled={busy} onClick={()=>void run("approve",{id:item.id})}>Утвердить</button>:null}
            <button className="secondary" disabled={busy} onClick={()=>void run("delete",{id:item.id})}>Удалить</button>
          </div>:null}
        </div>
      </article>):<p className="note">Каталог не загружен. Запустите локального агента.</p>}
    </div>
  </section>;
}
