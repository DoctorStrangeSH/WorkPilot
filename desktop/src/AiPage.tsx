import { useEffect, useRef, useState } from "react";
import {KnowledgeEditor,type KnowledgeDraft} from "./KnowledgePage";
import { invoke } from "@tauri-apps/api/core";

const modelLabel=(name:string)=>({"qwen3:8b":"Шерлок","qwen3:14b":"Шерлок · расширенный","qwen3:4b":"Шерлок · облегчённый","qwen3:0.6b":"Шерлок · компактный тест","qwen2.5:0.5b":"Шерлок · старый тест","qwen2.5:1.5b":"Шерлок · тест 1.5","qwen2.5:3b":"Шерлок · тест 3"}[name]??"Шерлок");
type Source={id:string;title:string;source:string;excerpt:string;start?:number;end?:number;url?:string};
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
  const [useWeb,setUseWeb]=useState(false);
  const [setupStatus,setSetupStatus]=useState("");
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
    setSetupStatus("Подготовка движка… При первом запуске будет скачан архив около 1,6 ГБ.");
    const timer=setInterval(()=>{void invoke<string>("get_setup_status").then(setSetupStatus).catch(()=>{});},1000);
    try {await invoke("start_local_ai");await refresh();}
    catch(reason){setError(String(reason));}
    finally {clearInterval(timer);setSetupStatus("");pending.current=false;setBusy(false);}
  };
  const installSherlock=async()=>{
    if(pending.current)return;
    pending.current=true;setBusy(true);setError("");
    setSetupStatus("Подготавливаем движок…");
    let preparing=true;
    const timer=setInterval(()=>{if(preparing)void invoke<string>("get_setup_status").then(setSetupStatus).catch(()=>{});},1000);
    try{await invoke("start_local_ai");preparing=false;setSetupStatus("Скачиваем выбранного Шерлока… Оставьте окно открытым.");await invoke("install_sherlock",{model:installModel});await refresh();setModel(installModel);}
    catch(reason){setError(String(reason));}
    finally{clearInterval(timer);setSetupStatus("");pending.current=false;setBusy(false);}
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
      const reply = await invoke<Reply>("chat_ai", {model,messages:request,useKnowledge,knowledgeOnly,useWeb});
      setMessages([...history,{role:"user",content:text}, {...reply.message,sources:reply.sources,answer_mode:reply.answer_mode,cited_source_ids:reply.cited_source_ids}]);
    } catch(reason) {setMessages(history);setDraft(text);setError(String(reason));}
    finally {pending.current=false;setBusy(false);}
  };
  return <section className="page ai-page" aria-labelledby="ai-title">
    <div className="page-head"><div><div className="eyebrow">ЛОКАЛЬНЫЙ ИИ · ПАМЯТЬ И ЗНАНИЯ</div><h1 id="ai-title">Поговорим с Шерлоком</h1><p>Задайте вопрос, дайте текст для разбора или попросите составить план.</p></div></div>
    <p className="note">Сообщения обрабатываются локально. Интернет-поиск включается отдельно ниже: в Bing отправляется только текущий вопрос, без заметок и истории чата. Полная переписка не сохраняется; записи по кнопке «Запомнить» остаются в памяти после перезапуска. Автоматические действия и доступ к вкладкам не подключены.</p>
    <div className="ai-controls"><button className="secondary" disabled={busy} onClick={()=>void startModel()}>Запустить Шерлока</button><label>Модель <select value={model} disabled={busy || !status?.models.length} onChange={e=>setModel(e.target.value)}>{status?.models.length ? status.models.map(name=><option key={name} value={name}>{modelLabel(name)}</option>) : <option value={model}>{modelLabel(model)}</option>}</select></label><button className="secondary" disabled={!connected || busy} onClick={()=>void refresh()}>Проверить подключение</button><button className="secondary" disabled={busy || !messages.length} onClick={()=>{setMessages([]);setError("");}}>Очистить чат</button></div>
    {!connected ? <p role="status">Запустите агента на главной странице.</p> : !status?.available ? <p role="status">Локальный ИИ недоступен. Запустите Шерлока и проверьте подключение.</p> : !status.models.length ? <p role="status">Подходящая модель ещё не установлена. Установите Шерлока в блоке ниже.</p> : <p className="note">Модель подключена. ИИ может ошибаться — проверяйте важные ответы. Компактный тест заметно слабее основной версии.</p>}
    <details className="panel ai-task-review"><summary>Установить Шерлока на этом компьютере</summary><p>Для компьютера с 32 ГБ памяти рекомендуем основную версию. Загрузка занимает несколько гигабайт и требует интернета; ответы затем работают локально. На текущем маломощном компьютере не устанавливайте основную версию без свободной памяти. При отсутствии движка приложение само скачает и установит его (ещё около 1,6 ГБ).</p><label>Вариант<select disabled={busy} value={installModel} onChange={e=>setInstallModel(e.target.value)}><option value="qwen3:8b">Шерлок — основной, загрузка около 5 ГБ</option><option value="qwen3:4b">Шерлок — облегчённый, около 3 ГБ</option><option value="qwen3:14b">Шерлок — расширенный, около 9 ГБ</option></select></label><button className="secondary" disabled={busy || !connected} onClick={()=>void installSherlock()}>Скачать выбранного Шерлока</button><small>Оставьте окно открытым до завершения. Модель скачивается только по этой кнопке.</small></details>
    <label className="note"><input type="checkbox" checked={useKnowledge} disabled={busy || useWeb} onChange={e=>{setUseKnowledge(e.target.checked);if(!e.target.checked)setKnowledgeOnly(false);}}/> Использовать подтверждённую память и заметки</label>
    <label className="note"><input type="checkbox" aria-label="Только по знаниям" checked={knowledgeOnly} disabled={busy || !useKnowledge || useWeb} onChange={e=>setKnowledgeOnly(e.target.checked)}/> Только по знаниям: отвечать по найденным записям</label>
    <label className="note"><input type="checkbox" aria-label="Интернет-поиск" checked={useWeb} disabled={busy} onChange={e=>{setUseWeb(e.target.checked);if(e.target.checked)setKnowledgeOnly(false);}}/> Искать в интернете — отправлять текущий вопрос в Bing</label>
    {useWeb?<p className="note">Ответ по выдержкам поиска со ссылками на источники. Полные страницы не загружаются. Память и история чата в этом режиме не используются. Не вводите в вопрос секретные сведения.</p>:null}
    {setupStatus?<p role="status">{setupStatus}</p>:null}
    {knowledgeOnly?<p className="note">Сформулируйте вопрос полностью: в этом режиме используются текущий вопрос и найденные фрагменты, без истории чата. Если записей нет, генерация не запускается. Ссылки проверяются, правильность фактов — сверяйте с заметкой.</p>:null}
    {error ? <p className="alert error" role="alert">{error}</p> : null}
    <div className="panel ai-messages" role="log" aria-live="polite" aria-label="Переписка с Шерлоком">
      {!messages.length ? <p className="empty">Попробуйте: «Разбей задачу проверки заказа на пять шагов».</p> : messages.map((message,index)=><article className={"ai-message "+message.role} key={index}><b>{message.role==="user"?"Вы":"Шерлок"}</b><p>{message.content}</p>{message.answer_mode==="web"?<small>Режим: выдержки интернет-поиска</small>:null}{message.answer_mode==="knowledge_only"?<small>Режим: только по знаниям</small>:null}{message.sources?.length?<details className="ai-sources"><summary>Переданы модели: {message.sources.length} источников</summary>{message.sources.map(source=><div key={source.id}><b>{source.title}</b>{source.url && /^https?:\/\//.test(source.url)?<p><a href={source.url} target="_blank" rel="noopener noreferrer" onClick={event=>{event.preventDefault();void invoke("open_search_source",{url:source.url}).catch(()=>setError("Не удалось открыть источник в браузере. Скопируйте ссылку ниже."));}}>Открыть источник</a></p>:null}<small> · {source.source}{source.start!==undefined?` · символы ${source.start+1}–${source.end}`:""}{message.cited_source_ids?.includes(source.id)?" · модель сослалась на эту запись":""}</small><p>{source.excerpt}</p></div>)}</details>:null}{message.role==="assistant" ? <button className="secondary" disabled={busy || taskBusy || !!taskDraft || !connected} onClick={()=>{setTaskNotice("");setTaskDraft({requestId:crypto.randomUUID(),title:(messages[index-1]?.content??"Задача из чата").slice(0,200),description:message.content});}}>Создать задачу из ответа</button> : <button className="secondary" disabled={busy || !!memoryDraft || !connected} onClick={()=>setMemoryDraft({id:crypto.randomUUID(),title:message.content.slice(0,120),content:message.content,kind:"memory"})}>Запомнить</button>}</article>)}
      {busy ? <p role="status">Выполняем запрос… Загрузка движка или модели может занять несколько минут.</p> : null}
    </div>
    {memoryDraft?<KnowledgeEditor key={memoryDraft.id} initial={memoryDraft} connected={connected} onSaved={()=>{setMemoryDraft(null);setTaskNotice("Запись сохранена. Её можно найти и удалить в разделе «Память и знания».");}} onCancel={()=>setMemoryDraft(null)}/>:null}
    {taskNotice ? <p role="status" className="note">{taskNotice}</p> : null}
    {taskDraft ? <section className="panel ai-task-review" aria-labelledby="task-review-title"><h2 id="task-review-title">Проверьте задачу перед добавлением</h2><p>Модель может выдумывать сведения. Исправьте текст, если нужно. Подтверждение только сохраняет задачу в очереди.</p><label>Название<input autoFocus maxLength={200} disabled={taskBusy || taskDraft.submitted} value={taskDraft.title} onChange={e=>setTaskDraft({...taskDraft,title:e.target.value})}/></label><label>Описание<textarea rows={5} maxLength={2000} disabled={taskBusy || taskDraft.submitted} value={taskDraft.description} onChange={e=>setTaskDraft({...taskDraft,description:e.target.value})}/><small>{taskDraft.description.length}/2000{taskDraft.description.length>2000?" — сократите описание перед сохранением":""}</small></label><div><button className="secondary" disabled={taskBusy} onClick={()=>setTaskDraft(null)}>Отмена</button><button className="primary" disabled={taskBusy || !connected || !taskDraft.title.trim() || taskDraft.description.length>2000} onClick={()=>void saveTask()}>{taskBusy?"Сохраняем…":"Добавить в очередь"}</button></div></section> : null}
    <form className="ai-composer" onSubmit={event=>{event.preventDefault();void send();}}><label htmlFor="ai-draft">Ваше сообщение</label><textarea id="ai-draft" rows={3} maxLength={2000} value={draft} disabled={busy} onChange={e=>setDraft(e.target.value)} placeholder="Напишите вопрос или вставьте небольшой текст"/><button className="primary" type="submit" disabled={busy || !connected || !draft.trim() || !status?.models.includes(model)}>{busy?"Ожидаем ответ":"Отправить"}</button></form>
  </section>;
}
