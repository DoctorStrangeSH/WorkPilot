import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

type Message = {role: "user" | "assistant"; content: string};
type Status = {available: boolean; models: string[]};
type TaskDraft = {requestId:string; title:string; description:string; submitted?:boolean};
type Reply = {message: Message; model: string};

export function AiPage({connected,onTaskCreated}: {connected: boolean;onTaskCreated:()=>void}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [model, setModel] = useState("qwen2.5:0.5b");
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const [taskDraft,setTaskDraft]=useState<TaskDraft|null>(null);
  const [taskBusy,setTaskBusy]=useState(false);
  const [taskNotice,setTaskNotice]=useState("");
  const taskPending=useRef(false);
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
    }).catch(() => {if(active)setError("Не удалось проверить Ollama.");});
    else {setStatus(null);setMessages([]);setTaskDraft(null);}
    return () => {active = false;};
  }, [connected]);
  const startModel = async () => {
    if (pending.current) return;
    pending.current=true;setBusy(true);setError("");
    try {await invoke("start_local_ai");await refresh();}
    catch(reason){setError(String(reason));}
    finally {pending.current=false;setBusy(false);}
  };
  const send = async () => {
    if (pending.current || !connected || !draft.trim() || !status?.models.includes(model)) return;
    pending.current = true;setBusy(true);setError("");
    const text = draft.trim();
    let history = messages.slice(-6);
    while(history.length && history.reduce((sum,item)=>sum+item.content.length,0)+text.length>8000) history=history.slice(2);
    const request: Message[] = [...history, {role:"user",content:text}];
    setMessages(request);setDraft("");
    try {
      const reply = await invoke<Reply>("chat_ai", {model,messages:request});
      setMessages([...request, reply.message]);
    } catch(reason) {setMessages(history);setDraft(text);setError(String(reason));}
    finally {pending.current=false;setBusy(false);}
  };
  return <section className="page ai-page" aria-labelledby="ai-title">
    <div className="page-head"><div><div className="eyebrow">ЛОКАЛЬНЫЙ ИИ · ПЕРВЫЙ ТЕСТ</div><h1 id="ai-title">Поговорим с Маленией</h1><p>Задайте вопрос, дайте текст для разбора или попросите составить план.</p></div></div>
    <p className="note">Сообщения обрабатываются на этом компьютере. Доступ к вкладкам, файлам и автоматическому выполнению действий пока не подключён. Переписка не сохраняется на диск.</p>
    <div className="ai-controls"><button className="secondary" disabled={busy} onClick={()=>void startModel()}>Запустить Ollama</button><label>Модель <select value={model} disabled={busy || !status?.models.length} onChange={e=>setModel(e.target.value)}>{status?.models.length ? status.models.map(name=><option key={name}>{name}</option>) : <option>{model}</option>}</select></label><button className="secondary" disabled={!connected || busy} onClick={()=>void refresh()}>Проверить подключение</button><button className="secondary" disabled={busy || !messages.length} onClick={()=>{setMessages([]);setError("");}}>Очистить чат</button></div>
    {!connected ? <p role="status">Запустите агента на главной странице.</p> : !status?.available ? <p role="status">Ollama недоступен. Запустите локальный сервер Ollama и проверьте подключение.</p> : !status.models.length ? <p role="status">Подходящая модель ещё не установлена. Для первого теста нужна Qwen 2.5 0.5B.</p> : <p className="note">Модель подключена. Компактная модель может ошибаться — проверяйте важные ответы.</p>}
    {error ? <p className="alert error" role="alert">{error}</p> : null}
    <div className="panel ai-messages" role="log" aria-live="polite" aria-label="Переписка с Маленией">
      {!messages.length ? <p className="empty">Попробуйте: «Разбей задачу проверки заказа на пять шагов».</p> : messages.map((message,index)=><article className={"ai-message "+message.role} key={index}><b>{message.role==="user"?"Вы":"Маления"}</b><p>{message.content}</p>{message.role==="assistant" ? <button className="secondary" disabled={busy || taskBusy || !!taskDraft || !connected} onClick={()=>{setTaskNotice("");setTaskDraft({requestId:crypto.randomUUID(),title:(messages[index-1]?.content??"Задача из чата").slice(0,200),description:message.content});}}>Создать задачу из ответа</button> : null}</article>)}
      {busy ? <p role="status">Маления думает… Первый ответ может занять больше времени.</p> : null}
    </div>
    {taskNotice ? <p role="status" className="note">{taskNotice}</p> : null}
    {taskDraft ? <section className="panel ai-task-review" aria-labelledby="task-review-title"><h2 id="task-review-title">Проверьте задачу перед добавлением</h2><p>Модель может выдумывать сведения. Исправьте текст, если нужно. Подтверждение только сохраняет задачу в очереди.</p><label>Название<input autoFocus maxLength={200} disabled={taskBusy || taskDraft.submitted} value={taskDraft.title} onChange={e=>setTaskDraft({...taskDraft,title:e.target.value})}/></label><label>Описание<textarea rows={5} maxLength={2000} disabled={taskBusy || taskDraft.submitted} value={taskDraft.description} onChange={e=>setTaskDraft({...taskDraft,description:e.target.value})}/><small>{taskDraft.description.length}/2000{taskDraft.description.length>2000?" — сократите описание перед сохранением":""}</small></label><div><button className="secondary" disabled={taskBusy} onClick={()=>setTaskDraft(null)}>Отмена</button><button className="primary" disabled={taskBusy || !connected || !taskDraft.title.trim() || taskDraft.description.length>2000} onClick={()=>void saveTask()}>{taskBusy?"Сохраняем…":"Добавить в очередь"}</button></div></section> : null}
    <form className="ai-composer" onSubmit={event=>{event.preventDefault();void send();}}><label htmlFor="ai-draft">Ваше сообщение</label><textarea id="ai-draft" rows={3} maxLength={2000} value={draft} disabled={busy} onChange={e=>setDraft(e.target.value)} placeholder="Напишите вопрос или вставьте небольшой текст"/><button className="primary" type="submit" disabled={busy || !connected || !draft.trim() || !status?.models.includes(model)}>{busy?"Ожидаем ответ":"Отправить"}</button></form>
  </section>;
}
