import {useEffect,useRef,useState} from "react";
import {invoke} from "@tauri-apps/api/core";

type RecordItem={id:string;title:string;content:string;kind:"memory"|"note";source:string};
export type KnowledgeDraft={id:string;title:string;content:string;kind:"memory"|"note"};

export function KnowledgeEditor({initial,onSaved,onCancel,connected}:{initial:KnowledgeDraft;onSaved:()=>void;onCancel:()=>void;connected:boolean}) {
  const [draft,setDraft]=useState(initial);
  const [busy,setBusy]=useState(false);
  const [attempted,setAttempted]=useState(false);
  const [error,setError]=useState("");
  const pending=useRef(false);
  const save=async()=>{
    if(pending.current || !connected || !draft.title.trim() || !draft.content.trim())return;
    pending.current=true;setBusy(true);setAttempted(true);setError("");
    try {await invoke("knowledge_action",{action:"save",payload:{request_id:draft.id,title:draft.title,content:draft.content,kind:draft.kind}});onSaved();}
    catch(reason){setError(String(reason));}
    finally{pending.current=false;setBusy(false);}
  };
  return <section className="panel ai-task-review" aria-label="Подтверждение записи в память"><h2>Проверьте запись перед сохранением</h2><p>Сохраняйте проверенные сведения и свои правила. Сохранённые записи могут передаваться локальной модели в следующих чатах. Полная переписка не сохраняется.</p><label>Тип<select disabled={busy || attempted} value={draft.kind} onChange={e=>setDraft({...draft,kind:e.target.value as "memory"|"note"})}><option value="memory">Постоянная память: правило или предпочтение</option><option value="note">Справочная заметка: поиск по вопросу</option></select></label><label>Название<input maxLength={120} disabled={busy || attempted} value={draft.title} onChange={e=>setDraft({...draft,title:e.target.value})}/></label><label>Текст<textarea rows={5} maxLength={draft.kind==="memory"?2000:6000} disabled={busy || attempted} value={draft.content} onChange={e=>setDraft({...draft,content:e.target.value})}/></label>{error?<p role="alert">{error} При неясном результате проверьте список знаний; повтор с тем же текстом безопасен.</p>:null}<div><button className="secondary" disabled={busy} onClick={onCancel}>Отмена</button><button className="primary" disabled={busy || !connected || !draft.title.trim() || !draft.content.trim() || draft.content.length>(draft.kind==="memory"?2000:6000)} onClick={()=>void save()}>{busy?"Сохраняем…":"Подтвердить и запомнить"}</button></div></section>;
}

export function KnowledgePage({connected}:{connected:boolean}) {
  const [records,setRecords]=useState<RecordItem[]>([]);
  const [draft,setDraft]=useState<KnowledgeDraft|null>(null);
  const [folder,setFolder]=useState("");
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState("");
  const pending=useRef(false);
  const refresh=async()=>{try{setRecords((await invoke<{records:RecordItem[]}>("get_knowledge")).records);}catch(reason){setNotice(String(reason));}};
  useEffect(()=>{if(connected)void refresh();else setRecords([]);},[connected]);
  const action=async(name:string,payload:object)=>{
    if(pending.current || !connected)return;
    pending.current=true;setBusy(true);setNotice("");
    try{const result=await invoke<{imported?:number}>("knowledge_action",{action:name,payload});setNotice(name==="import"?`Импортировано заметок: ${result.imported}. После изменения файлов повторите импорт.`:"Запись удалена.");await refresh();}
    catch(reason){setNotice(String(reason));}
    finally{pending.current=false;setBusy(false);}
  };
  return <section className="page"><div className="page-head"><div><div className="eyebrow">ЛОКАЛЬНАЯ БАЗА ЗНАНИЙ</div><h1>Память и знания</h1><p>Здесь хранятся только явно подтверждённые записи и импортированные вами заметки.</p></div></div><p className="note">Модель не переобучается: перед ответом она получает подходящие фрагменты. Память хранится после перезапуска. В один запрос передаётся до двух записей памяти и двух заметок, фрагментами до 600 символов. Поиск простой, по словам; он может пропускать нужные заметки. Все записи можно просмотреть и удалить.</p><div className="ai-controls"><button className="primary" disabled={!connected || busy || !!draft} onClick={()=>setDraft({id:crypto.randomUUID(),title:"",content:"",kind:"memory"})}>Добавить запись</button><button className="secondary" disabled={!connected || busy} onClick={()=>void refresh()}>Обновить список</button></div>{draft?<KnowledgeEditor key={draft.id} initial={draft} connected={connected} onSaved={()=>{setDraft(null);setNotice("Запись сохранена.");void refresh();}} onCancel={()=>setDraft(null)}/>:null}<section className="panel ai-task-review"><h2>Заметки Obsidian / Markdown</h2><p>Укажите отдельную папку. По кнопке будут прочитаны только обычные .md внутри неё: до 100 файлов, 6000 символов на заметку. Скрытые папки, вложения и ссылки пропускаются. Импорт — снимок файлов; повторный импорт заменит заметки этой папки и уберёт исчезнувшие. Исходные файлы не изменяются.</p><label>Полный путь к папке<input value={folder} disabled={busy || !connected} onChange={e=>setFolder(e.target.value)} placeholder="Вставьте путь к отдельной папке заметок"/></label><button className="secondary" disabled={!connected || busy || !folder.trim()} onClick={()=>void action("import",{folder:folder.trim()})}>Импортировать выбранную папку</button></section>{notice?<p role="status" className="note">{notice}</p>:null}{!connected?<p>Сначала запустите агента.</p>:<div className="knowledge-list">{!records.length?<p>Пока нет сохранённых знаний.</p>:records.map(record=><article className="panel knowledge-record" key={record.id}><h2>{record.title}</h2><small>{record.kind==="memory"?"Память":"Заметка"} · {record.source}</small><p>{record.content}</p><button className="danger" disabled={busy} onClick={()=>{if(window.confirm(`Удалить запись «${record.title}» из памяти Малении? Исходный файл останется.`))void action("delete",{id:record.id});}}>Удалить запись</button></article>)}</div>}</section>;
}
