import { useEffect, useRef, useState } from "react";
import {KnowledgeEditor,type KnowledgeDraft} from "./KnowledgePage";
import { invoke } from "@tauri-apps/api/core";

const modelLabel=(name:string)=>({"qwen3:8b":"Шерлок","qwen3:14b":"Шерлок · расширенный","qwen3:4b":"Шерлок · облегчённый","qwen3:0.6b":"Шерлок · компактный тест","qwen2.5:0.5b":"Шерлок · старый тест","qwen2.5:1.5b":"Шерлок · тест 1.5","qwen2.5:3b":"Шерлок · тест 3"}[name]??"Шерлок");
type Source={id:string;title:string;source:string;excerpt:string;start?:number;end?:number};
type Message = {role: "user" | "assistant"; content: string;sources?:Source[];answer_mode?:string;cited_source_ids?:string[]};
type Status = {available: boolean; models: string[]};
type TaskDraft = {requestId:string; title:string; description:string; submitted?:boolean};
type Reply = {message: Message; model: string;sources?:Source[];answer_mode?:string;cited_source_ids?:string[]};

export function AiPage({connected,onTaskCreated}: {connected: boolean;onTaskCreated:()=>void}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [model, setModel] = useState("qwen3:8b");
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const [taskDraft,setTaskDraft]=useState<TaskDraft|null>(null);
  const [taskBusy,setTaskBusy]=useState(false);
  const [taskNotice,setTaskNotice]=useState("");
  const taskPending=useRef(false);
  const [memoryDraft,setMemoryDraft]=useState<KnowledgeDraft|null>(null);
  const [useKnowledge,setUseKnowledge]=useState(true);
  const [knowledgeOnly,setKnowledgeOnly]=useState(false);
  const [installModel,setInstallModel]=useState("qwen3:8b");
  const saveTask=async()=>{
    if(!taskDraft || taskPending.current || !connected || !taskDraft.title.trim() || taskDraft.description.length>2000)return;
    taskPending.current=true;setTaskBusy(true);setTaskNotice("");setTaskDraft({...taskDraft,submitted:true});
    try {
      await invoke("create_task",{title:taskDraft.title.trim(),description:taskDraft.description,requestId:taskDraft.requestId});
      setTaskDraft(null);setTaskNotice("Задача добавлена в очередь. Автоматическое выполнение пока не подключено.");onTaskCreated();
    } catch {setTaskNotice("Сохранение не подтверждено. Можно повторить тот же запрос без дубликата или проверить раздел «Задания».");}
    finally {taskPending.current=false;setTaskBusy(false);}
  };
  const refresh = async () => {
    try {
      const result = await invoke<Status>("get_ai_status");
      setStatus(result);setError("");
      if (result.models.length && !result.models.includes(model)) setModel(result.models[0]);
    } catch {setStatus(null);setError("Сначала запустите локального агента.");}
  };
  useEffect(() => {
    let active = true;
    if (connected) void invoke<Status>("get_ai_status").then(result => {
      if (active) {setStatus(result);if(result.models.length)setModel(result.models[0]);}
    }).catch(() => {if(active)setError("Не удалось проверить локальный движок.");});
    else {setStatus(null);setMessages([]);setTaskDraft(null);setMemoryDraft(null);}
    return () => {active = false;};
  }, [connected]);
  const startModel = async () => {
    if (pending.current) return;
    pending.current=true;setBusy(true);setError("");
    try {await invoke("start_local_ai");await refresh();}
    catch(reason){setError(String(reason));}
    finally {pending.current=false;setBusy(false);}
  };
  const installSherlock=async()=>{
    if(pending.current)return;
    pending.current=true;setBusy(true);setError("");
    try{await invoke("install_sherlock",{model:installModel});await refresh();setModel(installModel);}
    catch(reason){setError(String(reason));}
    finally{pending.current=false;setBusy(false);}
  };
  const send = async () => {
    if (pending.current || !connected || !draft.trim() || !status?.models.includes(model)) return;
    pending.current = true;setBusy(true);setError("");
    const text = draft.trim();
    let history = messages.slice(-6);
    while(history.length && history.reduce((sum,item)=>sum+item.content.length,0)+text.length>8000) history=history.slice(2);
    const request: Message[] = [...history.map(({role,content})=>({role,content})), {role:"user",content:text}];
    setMessages([...history,{role:"user",content:text}]);setDraft("");
    try {
      const reply = await invoke<Reply>("chat_ai", {model,messages:request,useKnowledge,knowledgeOnly});
      setMessages([...history,{role:"user",content:text}, {...reply.message,sources:reply.sources,answer_mode:reply.answer_mode,cited_source_ids:reply.cited_source_ids}]);
    } catch(reason) {setMessages(history);setDraft(text);setError(String(reason));}
    finally {pending.current=false;setBusy(false);}
  };
  return <section className="page ai-page" aria-labelledby="ai-title">
    <div className="page-head"><div><div className="eyebrow">ЛОКАЛЬНЫЙ ИИ · ПАМЯТЬ И ЗНАНИЯ</div><h1 id="ai-title">Поговорим с Шерлоком</h1><p>Задайте вопрос, дайте текст для разбора или попросите составить план.</p></div></div>
    <p className="note">Сообщения обрабатываются локально. Можно подключать только сохранённые вами знания. Полная переписка не сохраняется; записи по кнопке «Запомнить» остаются в памяти после перезапуска. Автоматические действия и доступ к вкладкам не подключены.</p>
    <div className="ai-controls"><button className="secondary" disabled={busy} onClick={()=>void startModel()}>Запустить Шерлока</button><label>Модель <select value={model} disabled={busy || !status?.models.length} onChange={e=>setModel(e.target.value)}>{status?.models.length ? status.models.map(name=><option key={name} value={name}>{modelLabel(name)}</option>) : <option value={model}>{modelLabel(model)}</option>}</select></label><button className="secondary" disabled={!connected || busy} onClick={()=>void refresh()}>Проверить подключение</button><button className="secondary" disabled={busy || !messages.length} onClick={()=>{setMessages([]);setError("");}}>Очистить чат</button></div>
    {!connected ? <p role="status">Запустите агента на главной странице.</p> : !status?.available ? <p role="status">Локальный ИИ недоступен. Запустите Шерлока и проверьте подключение.</p> : !status.models.length ? <p role="status">Подходящая модель ещё не установлена. Установите Шерлока в блоке ниже.</p> : <p className="note">Модель подключена. ИИ может ошибаться — проверяйте важные ответы. Компактный тест заметно слабее основной версии.</p>}
    <details className="panel ai-task-review"><summary>Установить Шерлока на этом компьютере</summary><p>Для компьютера с 32 ГБ памяти рекомендуем основную версию. Загрузка занимает несколько гигабайт и требует интернета; ответы затем работают локально. На текущем маломощном компьютере не устанавливайте основную версию без свободной памяти. Сначала запустите локальный ИИ.</p><label>Вариант<select disabled={busy} value={installModel} onChange={e=>setInstallModel(e.target.value)}><option value="qwen3:8b">Шерлок — основной, загрузка около 5 ГБ</option><option value="qwen3:4b">Шерлок — облегчённый, около 3 ГБ</option><option value="qwen3:14b">Шерлок — расширенный, около 9 ГБ</option></select></label><button className="secondary" disabled={busy || !connected} onClick={()=>void installSherlock()}>Скачать выбранного Шерлока</button><small>Оставьте окно открытым до завершения. Модель скачивается только по этой кнопке.</small></details>
    <label className="note"><input type="checkbox" checked={useKnowledge} disabled={busy} onChange={e=>{setUseKnowledge(e.target.checked);if(!e.target.checked)setKnowledgeOnly(false);}}/> Использовать подтверждённую память и заметки</label>
    <label className="note"><input type="checkbox" aria-label="Только по знаниям" checked={knowledgeOnly} disabled={busy || !useKnowledge} onChange={e=>setKnowledgeOnly(e.target.checked)}/> Только по знаниям: отвечать по найденным записям</label>
    {knowledgeOnly?<p className="note">Сформулируйте вопрос полностью: в этом режиме используются текущий вопрос и найденные фрагменты, без истории чата. Если записей нет, генерация не запускается. Ссылки проверяются, правильность фактов — сверяйте с заметкой.</p>:null}
    {error ? <p className="alert error" role="alert">{error}</p> : null}
    <div className="panel ai-messages" role="log" aria-live="polite" aria-label="Переписка с Шерлоком">
      {!messages.length ? <p className="empty">Попробуйте: «Разбей задачу проверки заказа на пять шагов».</p> : messages.map((message,index)=><article className={"ai-message "+message.role} key={index}><b>{message.role==="user"?"Вы":"Шерлок"}</b><p>{message.content}</p>{message.answer_mode==="knowledge_only"?<small>Режим: только по знаниям</small>:null}{message.sources?.length?<details className="ai-sources"><summary>Переданы модели: {message.sources.length} записей</summary>{message.sources.map(source=><div key={source.id}><b>{source.title}</b><small> · {source.source}{source.start!==undefined?` · символы ${source.start+1}–${source.end}`:""}{message.cited_source_ids?.includes(source.id)?" · модель сослалась на эту запись":""}</small><p>{source.excerpt}</p></div>)}</details>:null}{message.role==="assistant" ? <button className="secondary" disabled={busy || taskBusy || !!taskDraft || !connected} onClick={()=>{setTaskNotice("");setTaskDraft({requestId:crypto.randomUUID(),title:(messages[index-1]?.content??"Задача из чата").slice(0,200),description:message.content});}}>Создать задачу из ответа</button> : <button className="secondary" disabled={busy || !!memoryDraft || !connected} onClick={()=>setMemoryDraft({id:crypto.randomUUID(),title:message.content.slice(0,120),content:message.content,kind:"memory"})}>Запомнить</button>}</article>)}
      {busy ? <p role="status">Шерлок думает… Первый ответ может занять больше времени.</p> : null}
    </div>
    {memoryDraft?<KnowledgeEditor key={memoryDraft.id} initial={memoryDraft} connected={connected} onSaved={()=>{setMemoryDraft(null);setTaskNotice("Запись сохранена. Её можно найти и удалить в разделе «Память и знания».");}} onCancel={()=>setMemoryDraft(null)}/>:null}
    {taskNotice ? <p role="status" className="note">{taskNotice}</p> : null}
    {taskDraft ? <section className="panel ai-task-review" aria-labelledby="task-review-title"><h2 id="task-review-title">Проверьте задачу перед добавлением</h2><p>Модель может выдумывать сведения. Исправьте текст, если нужно. Подтверждение только сохраняет задачу в очереди.</p><label>Название<input autoFocus maxLength={200} disabled={taskBusy || taskDraft.submitted} value={taskDraft.title} onChange={e=>setTaskDraft({...taskDraft,title:e.target.value})}/></label><label>Описание<textarea rows={5} maxLength={2000} disabled={taskBusy || taskDraft.submitted} value={taskDraft.description} onChange={e=>setTaskDraft({...taskDraft,description:e.target.value})}/><small>{taskDraft.description.length}/2000{taskDraft.description.length>2000?" — сократите описание перед сохранением":""}</small></label><div><button className="secondary" disabled={taskBusy} onClick={()=>setTaskDraft(null)}>Отмена</button><button className="primary" disabled={taskBusy || !connected || !taskDraft.title.trim() || taskDraft.description.length>2000} onClick={()=>void saveTask()}>{taskBusy?"Сохраняем…":"Добавить в очередь"}</button></div></section> : null}
    <form className="ai-composer" onSubmit={event=>{event.preventDefault();void send();}}><label htmlFor="ai-draft">Ваше сообщение</label><textarea id="ai-draft" rows={3} maxLength={2000} value={draft} disabled={busy} onChange={e=>setDraft(e.target.value)} placeholder="Напишите вопрос или вставьте небольшой текст"/><button className="primary" type="submit" disabled={busy || !connected || !draft.trim() || !status?.models.includes(model)}>{busy?"Ожидаем ответ":"Отправить"}</button></form>
  </section>;
}
