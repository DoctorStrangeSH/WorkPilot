import { useEffect, useMemo, useState } from "react";

export type PermissionRequest = {
  id: string;
  binding: string;
  capability: "browser.read_text" | "browser.screenshot";
  tab_id: number;
  document_id: string;
  parameters: Record<string, unknown>;
  status: "pending" | "approved" | "denied" | "revoked" | "consumed" | "expired";
  expires_at: number;
  remaining_seconds: number;
};
export type PermissionDecision = "allow" | "deny" | "revoke";

const statusLabels: Record<PermissionRequest["status"], string> = {
  pending: "Ожидает решения", approved: "Разрешено один раз", denied: "Отклонено",
  revoked: "Отозвано", consumed: "Использовано", expired: "Срок истёк",
};

type Props = {
  requests: PermissionRequest[];
  connected: boolean;
  busy: boolean;
  onDecide: (request: PermissionRequest, decision: PermissionDecision) => void;
};

export function PermissionsPage({ requests, connected, busy, onDecide }: Props) {
  const [now, setNow] = useState(() => performance.now());
  // Anchor server lifetimes once per received snapshot, never once per render.
  const deadlines = useMemo(() => {
    const observed = performance.now();
    return new Map(requests.map(request => [request.id, observed + request.remaining_seconds * 1000]));
  }, [requests]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(performance.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return <section className="page permissions-page" aria-labelledby="permissions-title">
    <div className="page-head"><div><div className="eyebrow">КОНТРОЛЬ ДЕЙСТВИЙ</div>
      <h1 id="permissions-title">Разрешения</h1>
      <p>Один запрос — одно действие на конкретной вкладке.</p>
    </div></div>
    <div className="note permission-preview">Предварительная версия: чтение страниц и снимки экрана ещё не подключены. Подтверждение сохраняет решение, но не запускает действие.</div>
    {!connected ? <p role="status">Запустите агента, чтобы видеть запросы.</p> : null}
    {connected && requests.length === 0 ? <div className="empty"><b>Нет запросов на разрешение</b><p>Запрос появится здесь, когда подключённый модуль предложит конкретное действие.</p></div> : null}
    {requests.map(request => {
      const remaining = Math.ceil(Math.max(0, Math.min(request.remaining_seconds, ((deadlines.get(request.id) ?? now) - now) / 1000)));
      const live = request.status === "pending" || request.status === "approved";
      const status = live && remaining === 0 ? "expired" : request.status;
      const disabled = !connected || busy || remaining === 0;
      return <article className="panel permission-card" key={request.id} aria-label={`Запрос для вкладки ${request.tab_id}`}>
        <div className="panel-head"><h2>{request.capability === "browser.read_text" ? "Прочитать текст страницы" : "Сделать снимок вкладки"}</h2><span>{statusLabels[status]}</span></div>
        <dl><dt>Вкладка</dt><dd>{request.tab_id}</dd><dt>Документ</dt><dd>{request.document_id}</dd></dl>
        <details><summary>Точные параметры действия</summary><pre>{JSON.stringify(request.parameters, null, 2)}</pre></details>
        {live ? <p>До истечения разрешения: {remaining} сек.</p> : null}
        <div className="permission-actions">
          {status === "pending" ? <><button className="secondary" disabled={disabled} onClick={() => onDecide(request, "deny")}>Отклонить</button><button className="primary" disabled={disabled} onClick={() => onDecide(request, "allow")}>Разрешить один раз</button></> : null}
          {status === "approved" ? <button className="danger" disabled={disabled} onClick={() => onDecide(request, "revoke")}>Отозвать разрешение</button> : null}
        </div>
      </article>;
    })}
  </section>;
}
