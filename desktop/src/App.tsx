import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {KnowledgePage} from "./KnowledgePage";
import { AiPage } from "./AiPage";
import { invoke } from "@tauri-apps/api/core";
import { PermissionsPage, type PermissionRequest, type PermissionDecision } from "./PermissionsPage";
import {
  Activity, ArrowUpRight, BrainCircuit, Check, ChevronDown, CircleHelp,
  Clock3, Cpu, Database, FileSearch, Globe2, LayoutDashboard, ListTodo,
  LoaderCircle, LockKeyhole, MemoryStick, MoreHorizontal, Play, Plus,
  Search, Settings2, ShieldCheck, Sparkles, Square, X
} from "lucide-react";

type Task = { id:string; title:string; description:string; status:"pending"|"cancelled"; created_at:string; };
type EventItem = { id:number; event_type:string; message:string; created_at:string; };
type BrowserTab = { id:string; url:string; title:string; shared_at:string; };
type Resources = { total_memory_bytes:number; available_memory_bytes:number; used_memory_percent:number; logical_processors:number; cpu_usage_percent:number; mode:"normal"|"economy"|"emergency"; recommended_parallel_jobs:number; };
type Dashboard = { running:boolean; resources:Resources; tasks:Task[]; events:EventItem[]; browser_tabs:BrowserTab[]; permissions:PermissionRequest[]; };
type Page = "overview"|"tasks"|"browser"|"search"|"ai"|"settings"|"permissions"|"knowledge";

const labels:Record<Page,string>={overview:"Главная",tasks:"Задания",browser:"Браузер",search:"Поиск",ai:"Ассистент",settings:"Настройки",permissions:"Разрешения",knowledge:"Память и знания"};
const bytes=(n:number)=>n ? (n/1024/1024/1024).toFixed(1)+" ГБ" : "—";
const time=(v:string)=>{try{return new Intl.DateTimeFormat("ru-RU",{hour:"2-digit",minute:"2-digit"}).format(new Date(v));}catch{return v;}};

export default function App(){
  const [page,setPage]=useState<Page>("overview");
  const [data,setData]=useState<Dashboard|null>(null);
  const [busy,setBusy]=useState(false);
  const permissionDecisionBusy=useRef(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [title,setTitle]=useState("");
  const [description,setDescription]=useState("");
  const [filter,setFilter]=useState("");
  const [composer,setComposer]=useState(false);
  const connected=!!data?.running;

  const refresh=useCallback(async()=>{
    try{const result=await invoke<Dashboard>("get_dashboard");setData(result);setError("");}
    catch(reason){setData(null);if(String(reason)!=="Агент не запущен")setError(String(reason));}
  },[]);
  useEffect(()=>{void refresh();const id=window.setInterval(()=>void refresh(),3000);return()=>window.clearInterval(id);},[refresh]);

  const runAgent=async()=>{setBusy(true);setError("");try{const message=await invoke<string>("start_agent");setNotice(message);await refresh();}catch(e){setError(String(e));}finally{setBusy(false);}};
  const stopAgent=async()=>{setBusy(true);try{setNotice(await invoke<string>("stop_agent"));setData(null);}catch(e){setError(String(e));}finally{setBusy(false);}};
  const addTask=async()=>{if(!title.trim())return;setBusy(true);try{await invoke("create_task",{title:title.trim(),description});setTitle("");setDescription("");setComposer(false);setNotice("Задача добавлена в локальную очередь");await refresh();}catch(e){setError(String(e));}finally{setBusy(false);}};
  const cancelTask=async(id:string)=>{try{await invoke("cancel_task",{taskId:id});setNotice("Ожидающая задача отменена");await refresh();}catch(e){setError(String(e));}};
  const decidePermission=async(request:PermissionRequest,decision:PermissionDecision)=>{
    if(permissionDecisionBusy.current)return;
    permissionDecisionBusy.current=true;
    setBusy(true);setError("");let failure="";
    try{await invoke("decide_permission",{permissionId:request.id,binding:request.binding,decision});setNotice("Решение сохранено. Браузерные действия пока не подключены.");}
    catch(e){failure=String(e);}
    finally{await refresh();if(failure)setError(failure);permissionDecisionBusy.current=false;setBusy(false);}
  };
  const tasks=useMemo(()=>{const all=data?.tasks??[];return filter?all.filter(t=>t.title.toLowerCase().includes(filter.toLowerCase())):all;},[data,filter]);
  const mode=data?.resources.mode;
  const modeLabel=mode==="normal"?"Обычный":mode==="economy"?"Экономия":mode==="emergency"?"Защита":"—";

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><BrainCircuit size={22}/></div><div><b>Malenia</b><small>PERSONAL WORK AGENT</small></div></div>
      <div className="workspace"><div className="workspace-avatar">M</div><div><b>Моё пространство</b><small>Локальный компьютер</small></div><ChevronDown size={15}/></div>
      <div className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav>
        <Nav icon={<LayoutDashboard/>} label="Главная" active={page==="overview"} onClick={()=>setPage("overview")}/>
        <Nav icon={<Sparkles/>} label="Ассистент" active={page==="ai"} onClick={()=>setPage("ai")}/>
        <Nav icon={<ListTodo/>} label="Задания" active={page==="tasks"} count={data?.tasks.length} onClick={()=>setPage("tasks")}/>
        <Nav icon={<Globe2/>} label="Браузер" active={page==="browser"} onClick={()=>setPage("browser")}/>
      </nav>
      <div className="nav-label separated">ЗНАНИЯ И БЕЗОПАСНОСТЬ</div>
      <nav>
        <Nav icon={<Database/>} label="Память и знания" active={page==="knowledge"} onClick={()=>setPage("knowledge")}/>
        <Nav icon={<ShieldCheck/>} label="Разрешения" active={page==="permissions"} count={data?.permissions.filter(p=>p.status==="pending").length} onClick={()=>setPage("permissions")}/>
      </nav>
      <div className="nav-label separated">СИСТЕМА</div>
      <nav><Nav icon={<Settings2/>} label="Настройки" active={page==="settings"} onClick={()=>setPage("settings")}/></nav>
      <div className="side-spacer"/>
      <div className="privacy"><div><ShieldCheck size={17}/></div><b>Данные остаются локально</b><p>Ядро работает на этом компьютере. Секреты браузера не считываются.</p><small><LockKeyhole size={11}/> LOCAL-FIRST</small></div>
      <div className="user-row"><div className="user-avatar">M</div><div><b>Пользователь</b><small>Личный агент</small></div><MoreHorizontal size={18}/></div>
    </aside>

    <main className="main">
      <header className="topbar"><div className="crumb">Malenia <span>/</span> <b>{labels[page]}</b></div><div className="top-actions"><div className={"connection "+(connected?"online":"")}><i/> {connected?"Агент подключён":"Агент не запущен"}</div><button className="icon-btn" title="Справка"><CircleHelp size={17}/></button></div></header>
      <div className="content">
        {error&&<div className="alert error"><X size={15}/>{error}<button onClick={()=>setError("")}><X size={14}/></button></div>}
        {notice&&<div className="alert success"><Check size={15}/>{notice}<button onClick={()=>setNotice("")}><X size={14}/></button></div>}

        {page==="overview"&&<>
          <div className="welcome"><div><div className="eyebrow"><Sparkles size={13}/> ВАШ ЛОКАЛЬНЫЙ РАБОЧИЙ ПОМОЩНИК</div><h1>Ваш рабочий центр</h1><p>Задачи, ассистент и рабочие инструменты — в одном месте.</p></div><div className="date-chip"><Clock3 size={14}/>{new Intl.DateTimeFormat("ru-RU",{dateStyle:"long"}).format(new Date())}</div></div>
          <section className="hero">
            <div className="hero-copy"><div className="hero-kicker"><i/> MALENIA CORE</div><h2>{connected?"Шерлок готов помочь":"Подключим вашего помощника?"}</h2><p>{connected?"Откройте ассистента, чтобы задать вопрос, разобрать текст или составить план.":"Запустите локальное ядро. Затем откройте ассистента и настройте Шерлока."}</p><div className="hero-buttons">{!connected?<button className="primary" onClick={runAgent} disabled={busy}>{busy?<LoaderCircle className="spin" size={16}/>:<Play size={15}/>}Запустить агента</button>:<button className="primary" onClick={()=>setPage("ai")}><Sparkles size={15}/>Открыть ассистента</button>}{!connected?<button className="secondary" onClick={()=>setPage("ai")}><BrainCircuit size={15}/>Настроить Шерлока</button>:<button className="secondary" onClick={()=>setPage("browser")}><Globe2 size={15}/>Браузер</button>}</div></div>
            <div className="hero-graphic"><div className="ring ring1"/><div className="ring ring2"/><div className="core"><BrainCircuit size={54}/></div><span className="orbit o1"><Activity size={15}/></span><span className="orbit o2"><Database size={15}/></span><span className="orbit o3"><Globe2 size={15}/></span></div>
          </section>
          {connected?<section className="metrics">
            <Metric icon={<MemoryStick/>} label="Оперативная память" value={data?data.resources.used_memory_percent.toFixed(1)+"%":"—"} detail={data?bytes(data.resources.available_memory_bytes)+" свободно из "+bytes(data.resources.total_memory_bytes):"Данные пока недоступны"} tone={mode==="emergency"?"red":mode==="economy"?"amber":"green"} progress={data?.resources.used_memory_percent}/>
            <Metric icon={<Cpu/>} label="Загрузка процессора" value={data?data.resources.cpu_usage_percent.toFixed(1)+"%":"—"} detail={data?data.resources.logical_processors+" логических процессоров":"Данные пока недоступны"} tone="violet" progress={data?.resources.cpu_usage_percent}/>
            <Metric icon={<ListTodo/>} label="Задачи в очереди" value={String(data?.tasks.filter(t=>t.status==="pending").length??0)} detail="Сохранены, но ещё не выполняются автоматически" tone="blue"/>
            <Metric icon={<Activity/>} label="Режим ресурсов" value={modeLabel} detail={data?"Параллельность: "+data.resources.recommended_parallel_jobs:"Данные пока недоступны"} tone={mode==="emergency"?"red":mode==="economy"?"amber":"green"}/>
          </section>:<section className="setup-steps" aria-label="Первые шаги">
            <div className="setup-step"><span>1</span><div><b>Запустите локальное ядро</b><p>Агент работает на этом компьютере и хранит данные локально.</p></div></div>
            <div className="setup-step"><span>2</span><div><b>Откройте ассистента</b><p>Настройте модель Шерлок и начните диалог.</p></div></div>
          </section>}
          <section className="lower">
            <div className="panel"><div className="panel-head"><div><h3>Последние задания</h3><p>Локальная очередь Malenia</p></div><button className="link-btn" onClick={()=>setPage("tasks")}>Все задания <ArrowUpRight size={14}/></button></div><TaskList tasks={(data?.tasks??[]).slice(0,5)} onCancel={cancelTask}/></div>
            <div className="panel"><div className="panel-head"><div><h3>Активность</h3><p>Последние события агента</p></div><span className="live">● LIVE</span></div>{data?.events.length?<div className="events">{data.events.slice(0,6).map(e=><div className="event" key={e.id}><span><Check size={12}/></span><div><b>{e.message}</b><small>{time(e.created_at)}</small></div></div>)}</div>:<Empty title="Нет событий" text="Здесь появится история действий."/>}</div>
          </section>
        </>}

        {page==="tasks"&&<section className="page"><div className="page-head"><div><div className="eyebrow">УПРАВЛЕНИЕ ПРОЦЕССАМИ</div><h1>Задания</h1><p>Создавайте задачи и управляйте локальной очередью.</p></div><button className="primary" onClick={()=>setComposer(true)} disabled={!connected}><Plus size={15}/>Новая задача</button></div><div className="toolbar"><div className="search"><Search size={15}/><input value={filter} onChange={e=>setFilter(e.target.value)} placeholder="Поиск по заданиям..."/></div><small>{tasks.length} записей</small></div><div className="panel"><TaskList tasks={tasks} onCancel={cancelTask}/></div><div className="note"><CircleHelp size={15}/>Сейчас задания сохраняются локально в SQLite, но не запускаются автоматически. Выполнение будет подключено отдельным этапом.</div></section>}

        {page==="permissions"&&<PermissionsPage requests={data?.permissions??[]} connected={connected} busy={busy} onDecide={decidePermission}/>}
        {page==="browser"&&<BrowserPage tabs={data?.browser_tabs??[]} connected={connected}/>}
        {page==="search"&&<Coming icon={<FileSearch/>} title="Универсальный поиск" text="Здесь появится поиск по рабочим ресурсам, трекерам и фотографиям. Источники подключаются отдельными адаптерами."/>}
        {page==="knowledge"&&<KnowledgePage connected={connected}/>}
        {page==="ai"&&<AiPage connected={connected} onTaskCreated={()=>void refresh()}/>}
        {page==="settings"&&<section className="page"><div className="page-head"><div><div className="eyebrow">КОНФИГУРАЦИЯ</div><h1>Настройки</h1><p>Состояние локальной среды и параметры запуска.</p></div></div><div className="settings-grid"><Setting icon={<Database/>} title="Локальный агент" text="Python Runtime слушает только localhost." value={connected?"Запущен":"Остановлен"} action={<button className={connected?"danger":"primary"} onClick={connected?stopAgent:runAgent} disabled={busy}>{connected?<Square size={14}/>:<Play size={14}/>} {connected?"Остановить":"Запустить"}</button>}/><Setting icon={<ShieldCheck/>} title="Приватность" text="Секреты браузера не извлекаются. API доступен только локально." value="Local-first"/><Setting icon={<Cpu/>} title="Среда разработки" text="Windows · Python 3.11+ · SQLite · Tauri 2" value="Версия 0.6.0"/><Setting icon={<Globe2/>} title="Будущие подключения" text="Ручная передача вкладок Яндекс Браузера доступна через Browser Bridge. Шерлок поддерживает локальную модель и включаемый интернет-поиск." value="Доступны"/></div></section>}
      </div>
      <footer className="statusbar"><span><i className={connected?"":"idle"}/>{connected?"Локальный агент активен":"Локальный агент остановлен"}</span><span><LockKeyhole size={12}/>Локальная среда　·　Malenia 0.6.0</span></footer>
    </main>

    {composer&&<div className="backdrop" onClick={()=>setComposer(false)}><div className="modal" onClick={e=>e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">НОВОЕ ЗАДАНИЕ</div><h2>Что нужно сделать?</h2></div><button className="icon-btn" onClick={()=>setComposer(false)}><X size={17}/></button></div><label>Название задачи<input autoFocus maxLength={200} value={title} onChange={e=>setTitle(e.target.value)} placeholder="Например: проверить новые заказы"/></label><label>Описание <small>необязательно</small><textarea rows={4} maxLength={2000} value={description} onChange={e=>setDescription(e.target.value)} placeholder="Дополнительные детали..."/></label><div className="modal-foot"><span><LockKeyhole size={12}/>Сохранится локально</span><button className="primary" disabled={!connected||!title.trim()||busy} onClick={addTask}>{busy?<LoaderCircle className="spin" size={15}/>:<Plus size={15}/>}Добавить в очередь</button></div><p className="hint">Пока задача только сохраняется в очереди — автоматическое выполнение ещё не подключено.</p></div></div>}
  </div>;
}

function Nav({icon,label,active,count,onClick}:{icon:ReactNode;label:string;active:boolean;count?:number;onClick:()=>void}){return <button className={"nav-item "+(active?"active":"")} onClick={onClick}><span>{icon}</span>{label}{!!count&&<em>{count}</em>}</button>;}
function Metric({icon,label,value,detail,tone,progress}:{icon:ReactNode;label:string;value:string;detail:string;tone:string;progress?:number}){return <div className="metric"><div className={"metric-icon "+tone}>{icon}</div><small>{label}</small><strong>{value}</strong><p>{detail}</p>{progress!==undefined&&<div className="progress"><i className={tone} style={{width:Math.max(0,Math.min(progress,100))+"%"}}/></div>}</div>;}
function TaskList({tasks,onCancel}:{tasks:Task[];onCancel:(id:string)=>void}){if(!tasks.length)return <Empty title="Задач пока нет" text="Создайте задачу, чтобы она появилась здесь."/>;return <div className="task-list">{tasks.map(t=><div className="task-row" key={t.id}><span className={"task-state "+t.status}>{t.status==="pending"?<Clock3 size={14}/>:<X size={14}/>}</span><div className="task-copy"><b>{t.title}</b><small>{t.description||"Без дополнительного описания"} · {time(t.created_at)}</small></div><span className={"task-badge "+t.status}>{t.status==="pending"?"В очереди":"Отменено"}</span>{t.status==="pending"&&<button className="icon-btn tiny" title="Отменить" onClick={()=>onCancel(t.id)}><X size={14}/></button>}</div>)}</div>;}
function Empty({title,text}:{title:string;text:string}){return <div className="empty"><div><ListTodo size={18}/></div><b>{title}</b><p>{text}</p></div>;}
function BrowserPage({tabs,connected}:{tabs:BrowserTab[];connected:boolean}){
  return <section className="page">
    <div className="page-head"><div><div className="eyebrow">BROWSER BRIDGE · PREVIEW</div><h1>Браузер</h1><p>Передавайте Malenia только ту вкладку, которой поделились вручную.</p></div><span className="browser-state"><i className={connected?"":"idle"}/>{connected?"Агент подключён":"Сначала запустите агента"}</span></div>
    <div className="browser-safety"><div><ShieldCheck size={19}/></div><section><b>Приватность по умолчанию</b><p>Расширение не читает cookies, пароли, историю, DOM или содержимое страниц. URL сохраняется без query-параметров и фрагмента. Передача происходит только после нажатия «Поделиться вкладкой» в расширении.</p></section></div>
    <div className="panel browser-panel"><div className="panel-head"><div><h3>Вкладки, которыми вы поделились</h3><p>Последние 20 локальных записей</p></div><span className="live">{tabs.length} SHARED</span></div>
      {tabs.length?<div className="browser-tab-list">{tabs.map(tab=><article className="browser-tab" key={tab.id}><span className="browser-tab-icon"><Globe2 size={16}/></span><div className="browser-tab-copy"><b>{tab.title}</b><a href={tab.url} target="_blank" rel="noreferrer">{tab.url}</a><small>Передано вручную · {time(tab.shared_at)}</small></div></article>)}</div>:<Empty title="Пока нет переданных вкладок" text="Установите Malenia Browser Bridge, затем откройте нужную страницу и нажмите кнопку расширения «Поделиться вкладкой»."/>}
    </div>
    <div className="note"><CircleHelp size={15}/>Native Messaging работает только после регистрации расширения и хоста. Поддержка проверяется на установленной версии Яндекс Браузера; автоматический доступ к вкладкам не включён.</div>
  </section>;
}
function Coming({icon,title,text}:{icon:ReactNode;title:string;text:string}){return <div className="coming"><div>{icon}</div><small>СЛЕДУЮЩИЙ ЭТАП РАЗРАБОТКИ</small><h1>{title}</h1><p>{text}</p><span>Модуль пока не подключён</span></div>;}
function Setting({icon,title,text,value,action}:{icon:ReactNode;title:string;text:string;value:string;action?:ReactNode}){return <div className="panel setting"><div className="setting-icon">{icon}</div><h3>{title}</h3><p>{text}</p><div className="setting-bottom"><b>{value}</b>{action}</div></div>;}
