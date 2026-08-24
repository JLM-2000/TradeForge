import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  LayoutDashboard,
  Menu,
  Pause,
  Play,
  RefreshCw,
  Settings,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  X,
  Zap,
} from "lucide-react";
import { fetchDashboard, postAction } from "./api";
import type { Dashboard, Notification, Order, Position } from "./types";

type Page = "Overview" | "Holdings" | "Orders" | "Activity" | "Settings";

const navigation: Array<{ page: Page; label: string; icon: typeof LayoutDashboard }> = [
  { page: "Overview", label: "Overview", icon: LayoutDashboard },
  { page: "Holdings", label: "Holdings", icon: TrendingUp },
  { page: "Orders", label: "Orders", icon: Activity },
  { page: "Activity", label: "Activity", icon: Bell },
  { page: "Settings", label: "Settings", icon: Settings },
];

function App() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [page, setPage] = useState<Page>("Overview");
  const [menuOpen, setMenuOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [stopOpen, setStopOpen] = useState(false);
  const [closeOpen, setCloseOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => setDashboard(await fetchDashboard());

  useEffect(() => {
    const controller = new AbortController();
    fetchDashboard(controller.signal).then(setDashboard).catch((reason: Error) => {
      if (reason.name !== "AbortError") setError(reason.message);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!dashboard) return;
    const configuredApi = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? "http://127.0.0.1:8001" : window.location.origin);
    const apiUrl = new URL(configuredApi);
    const protocol = apiUrl.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${apiUrl.host}/api/v1/ws`);
    socket.onmessage = (event) => setDashboard(JSON.parse(event.data) as Dashboard);
    socket.onerror = () => socket.close();
    return () => socket.close();
  }, [Boolean(dashboard)]);

  const action = async (key: string, path: string, body?: unknown) => {
    setBusy(key);
    setError(null);
    try {
      await postAction(path, body);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Action rejected");
    } finally {
      setBusy(null);
    }
  };

  const startAutomatic = async () => {
    setBusy("auto-start");
    setError(null);
    try {
      if (dashboard?.control.state === "PAUSED") await postAction("/api/v1/control/resume");
      await postAction("/api/v1/auto/start");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Automatic trading could not start");
    } finally {
      setBusy(null);
    }
  };

  if (!dashboard) return <LoadingState error={error} onRetry={() => window.location.reload()} />;

  return <div className="tf-app">
    <aside className={`tf-sidebar ${menuOpen ? "open" : ""}`}>
      <div className="tf-brand"><span className="tf-mark">TF</span><div><b>TradeForge</b><small>paper operations</small></div><button className="tf-icon-button tf-close-menu" aria-label="Close menu" onClick={() => setMenuOpen(false)}><X size={17} /></button></div>
      <div className="tf-account"><span className="tf-account-avatar">P</span><div><small>Personal workspace</small><b>Demo account</b></div><ChevronRight size={14} /></div>
      <div className="tf-nav-title">Terminal</div>
      <nav className="tf-nav">{navigation.map(({ page: itemPage, label, icon: Icon }) => <button key={itemPage} className={page === itemPage ? "active" : ""} onClick={() => { setPage(itemPage); setMenuOpen(false); }}><Icon size={16} /><span>{label}</span>{itemPage === "Activity" && dashboard.unreadNotifications > 0 && <i>{dashboard.unreadNotifications}</i>}</button>)}</nav>
      <div className="tf-sidebar-foot"><span><span className="tf-dot green" />PAPER only</span><button><CircleHelp size={14} />Safety guide</button></div>
    </aside>
    <div className="tf-workspace">
      <header className={`tf-header ${dashboard.control.killSwitch ? "kill" : ""}`}>
        <button className="tf-icon-button tf-menu" aria-label="Open menu" onClick={() => setMenuOpen(true)}><Menu size={19} /></button>
        <div className="tf-header-title"><span>TradeForge</span><b>/ {page}</b></div>
        <div className="tf-header-actions"><span className="tf-mode"><span className="tf-dot blue" />PAPER</span><span className="tf-live-status"><span className={`tf-dot ${dashboard.control.killSwitch ? "red" : "green"}`} />{dashboard.control.killSwitch ? "Stopped" : "Connected"}</span><button className="tf-icon-button tf-notification-trigger" aria-label="Notifications" onClick={() => setNotificationsOpen(!notificationsOpen)}><Bell size={18} />{dashboard.unreadNotifications > 0 && <i>{dashboard.unreadNotifications}</i>}</button><button className="tf-stop-small" onClick={() => setStopOpen(true)}><Zap size={14} fill="currentColor" />STOP</button><span className="tf-user">JL</span></div>
        {notificationsOpen && <NotificationPopover notifications={dashboard.notifications} unread={dashboard.unreadNotifications} onRead={() => { void action("read", "/api/v1/notifications/acknowledge"); }} onClose={() => setNotificationsOpen(false)} />}
      </header>
      <main className="tf-main">
        {error && <div className="tf-error"><AlertTriangle size={15} /><span>{error}</span><button onClick={() => setError(null)}><X size={14} /></button></div>}
        <div className="tf-heading"><div><span className="tf-eyebrow">PAPER ACCOUNT / {page.toUpperCase()}</span><h1>{page === "Overview" ? "Good morning, Javier" : page}</h1><p>{page === "Overview" ? "One clear view of what is held, what it is worth, and whether automation is running." : pageDescription(page)}</p></div><button className="tf-refresh" disabled={busy === "refresh"} onClick={() => void action("refresh", "/api/v1/control/system-check")}><RefreshCw size={14} className={busy === "refresh" ? "spin" : ""} />Refresh</button></div>
        {page === "Overview" && <Overview dashboard={dashboard} busy={busy} onAction={action} onStart={startAutomatic} onEndSession={() => setCloseOpen(true)} onStop={() => setStopOpen(true)} onNavigate={setPage} />}
        {page === "Holdings" && <Holdings positions={dashboard.positions} />}
        {page === "Orders" && <Orders orders={dashboard.orders} />}
        {page === "Activity" && <ActivityPage notifications={dashboard.notifications} audit={dashboard.audit} onRead={() => void action("read", "/api/v1/notifications/acknowledge")} />}
        {page === "Settings" && <SettingsPage dashboard={dashboard} />}
      </main>
    </div>
    {stopOpen && <StopModal busy={busy === "stop"} onClose={() => setStopOpen(false)} onConfirm={() => { setStopOpen(false); void action("stop", "/api/v1/control/stop-everything", { reason: "Owner activated STOP EVERYTHING" }); }} />}
    {closeOpen && <CloseSessionModal busy={busy === "close-session"} onClose={() => setCloseOpen(false)} onConfirm={() => { setCloseOpen(false); void action("close-session", "/api/v1/session/close"); }} />}
  </div>;
}

function Overview({ dashboard, busy, onAction, onStart, onEndSession, onStop, onNavigate }: { dashboard: Dashboard; busy: string | null; onAction: (key: string, path: string, body?: unknown) => Promise<void>; onStart: () => Promise<void>; onEndSession: () => void; onStop: () => void; onNavigate: (page: Page) => void }) {
  const running = dashboard.automation.running;
  const paused = dashboard.control.state === "PAUSED";
  return <>
    <section className={`tf-automation ${dashboard.control.killSwitch ? "danger" : running ? "running" : ""}`}><div className="tf-automation-icon">{dashboard.control.killSwitch ? <ShieldAlert size={22} /> : running ? <Activity size={22} /> : <Pause size={22} />}</div><div className="tf-automation-copy"><span className="tf-eyebrow">Automatic paper trading</span><h2>{dashboard.control.killSwitch ? "AUTOMATION STOPPED" : running ? "AUTO TRADING IS RUNNING" : paused ? "TRADING IS PAUSED" : "AUTO TRADING IS OFF"}</h2><p>{dashboard.control.killSwitch ? "Kill switch active. Nothing can execute until deliberate recovery." : running ? `${dashboard.automation.strategy} is observing simulated prices every ${dashboard.automation.intervalSeconds} seconds.` : dashboard.automation.lastAction ?? "Start automatic paper trading when you are ready."}</p></div><div className="tf-automation-actions">{!dashboard.control.killSwitch && !running && <button className="tf-primary" disabled={busy === "auto-start"} onClick={() => void onStart()}><Play size={15} fill="currentColor" />{paused ? "Resume & start" : "Start auto"}</button>}{running && <button className="tf-secondary" onClick={() => void onAction("auto-pause", "/api/v1/auto/pause", { reason: "Owner paused automatic paper trading" })}><Pause size={15} />Pause auto</button>}<button className="tf-close-session" disabled={dashboard.control.killSwitch || busy === "close-session"} onClick={onEndSession}><CheckCircle2 size={15} />Enough for today</button><button className="tf-stop-button" onClick={onStop}><Zap size={15} fill="currentColor" />Stop everything</button></div></section>
    <div className="tf-metric-grid"><Metric label="Total equity" value={`€${dashboard.metrics.totalEquity}`} detail={`${dashboard.metrics.totalReturnPct} total return`} accent="lime" /><Metric label="Available cash" value={`€${dashboard.metrics.availableCash}`} detail={`€${dashboard.metrics.withdrawableCash} withdrawable`} /><Metric label="Today" value={`€${dashboard.metrics.todayReturnPct}`} detail={`P&L €${dashboard.metrics.todayPnl}`} tone={Number(dashboard.metrics.todayPnl) >= 0 ? "positive" : "negative"} /><Metric label="Holdings" value={String(dashboard.metrics.positions)} detail={`€${dashboard.metrics.currentExposure} invested`} /></div>
    <div className="tf-main-grid"><section className="tf-card tf-chart-card"><CardHeader title="Equity" subtitle="Simulated account value" /><div className="tf-chart-value"><b>€{dashboard.metrics.totalEquity}</b><span className="tf-positive"><TrendingUp size={14} /> {dashboard.metrics.totalReturnPct}</span></div><MiniChart points={dashboard.charts.equity} /></section><section className="tf-card tf-today-card"><CardHeader title="Today" subtitle="Realized and unrealized" /><div className={`tf-today-number ${Number(dashboard.metrics.todayPnl) >= 0 ? "positive" : "negative"}`}>{Number(dashboard.metrics.todayPnl) >= 0 ? "+" : ""}€{dashboard.metrics.todayPnl}</div><div className="tf-pnl-lines"><div><span>Realized</span><b>€{dashboard.metrics.realizedPnl}</b></div><div><span>Unrealized</span><b>€{dashboard.metrics.unrealizedPnl}</b></div><div><span>Fees</span><b>-€{dashboard.metrics.fees}</b></div></div></section></div>
    <section className="tf-card"><CardHeader title="What we hold" subtitle="Long positions in the paper account" action={<button className="tf-link" onClick={() => onNavigate("Holdings")}>See all <ChevronRight size={14} /></button>} />{dashboard.positions.length ? <HoldingsTable positions={dashboard.positions} /> : <Empty label="No open positions. Auto will wait for the next valid entry." />}</section>
    <div className="tf-bottom-grid"><section className="tf-card"><CardHeader title="Latest orders" subtitle="Real simulated order lifecycle" action={<button className="tf-link" onClick={() => onNavigate("Orders")}>See all <ChevronRight size={14} /></button>} />{dashboard.orders.length ? <OrdersList orders={dashboard.orders.slice(0, 4)} /> : <Empty label="No orders yet" />}</section><section className="tf-card"><CardHeader title="Notifications" subtitle="Safety and automation events" action={<button className="tf-link" onClick={() => onNavigate("Activity")}>Activity <ChevronRight size={14} /></button>} />{dashboard.notifications.length ? <NotificationList notifications={dashboard.notifications.slice(0, 4)} /> : <Empty label="No notifications" />}</section></div>
  </>;
}

function Holdings({ positions }: { positions: Position[] }) { return <section className="tf-card"><CardHeader title="Holdings" subtitle="Current paper positions" />{positions.length ? <HoldingsTable positions={positions} detailed /> : <Empty label="No positions held" />}</section>; }
function Orders({ orders }: { orders: Order[] }) { return <section className="tf-card"><CardHeader title="Orders" subtitle="Created, risk-checked, filled, and recorded" />{orders.length ? <OrdersList orders={orders} detailed /> : <Empty label="No orders yet" />}</section>; }
function ActivityPage({ notifications, audit, onRead }: { notifications: Notification[]; audit: Dashboard["audit"]; onRead: () => void }) { return <div className="tf-activity-grid"><section className="tf-card"><CardHeader title="Notifications" subtitle="Control and trading events" action={<button className="tf-secondary small" onClick={onRead}>Mark all read</button>} />{notifications.length ? <NotificationList notifications={notifications} detailed /> : <Empty label="No notifications" />}</section><section className="tf-card"><CardHeader title="Audit" subtitle="Append-only recent events" />{audit.map((event) => <div className="tf-audit-item" key={event.eventId}><code>{event.type}</code><span>{event.origin}</span><small>{event.detail}</small></div>)}</section></div>; }
function SettingsPage({ dashboard }: { dashboard: Dashboard }) { return <div className="tf-settings-grid"><section className="tf-card"><CardHeader title="Safety boundaries" subtitle="These are not changed by the dashboard" />{[["Mode", dashboard.modeLabel], ["Live execution", "DISABLED"], ["Withdrawals", "DISABLED"], ["Account", "DEMO-BOT"], ["Personal use only", "ENFORCED"], ["MyInvestor", "PERMANENTLY DISABLED"]].map(([label, value]) => <div className="tf-setting" key={label}><span>{label}</span><b>{value}</b><small>LOCKED</small></div>)}</section><section className="tf-card"><CardHeader title="How this works" subtitle="The short version" /><div className="tf-explainer"><div><b>Strategy observes</b><span>Demo Trend v1 creates paper intents from simulated prices.</span></div><div><b>Risk decides</b><span>Owner hard limits cap every position and exposure.</span></div><div><b>Execution enforces</b><span>PaperBroker fills with spread, slippage, fees, and idempotency.</span></div><div><b>You control the session</b><span>Pause, close the day, or stop everything at any time.</span></div></div></section></div>; }

function Metric({ label, value, detail, accent, tone }: { label: string; value: string; detail: string; accent?: string; tone?: string }) { return <div className={`tf-metric ${accent ?? ""} ${tone ?? ""}`}><span>{label}</span><b>{value}</b><small>{detail}</small></div>; }
function CardHeader({ title, subtitle, action }: { title: string; subtitle: string; action?: ReactNode }) { return <div className="tf-card-header"><div><h2>{title}</h2><span>{subtitle}</span></div>{action}</div>; }
function HoldingsTable({ positions, detailed = false }: { positions: Position[]; detailed?: boolean }) { return <div className="tf-table-wrap"><table className="tf-table"><thead><tr><th>Holding</th><th>Units</th><th>Value</th><th>Entry / price</th><th>Return</th>{detailed && <th>Risk</th>}</tr></thead><tbody>{positions.map((position) => <tr key={position.instrument}><td><div className="tf-holding"><span>{position.ticker.slice(0, 1)}</span><div><b>{position.ticker}</b><small>{position.strategy}</small></div></div></td><td>{position.quantity}</td><td>€{position.marketValue}</td><td>€{position.averageEntry} <small className="tf-current">→ €{position.currentPrice}</small></td><td className={position.unrealizedPnl.startsWith("-") ? "tf-negative" : "tf-positive"}>{position.returnPct}</td>{detailed && <td><span className="tf-safe-label">{position.riskStatus}</span></td>}</tr>)}</tbody></table></div>; }
function OrdersList({ orders, detailed = false }: { orders: Order[]; detailed?: boolean }) { return <div className="tf-orders">{orders.map((order) => <div className="tf-order" key={order.id}><span className={`tf-order-side ${order.side === "BUY" ? "buy" : "sell"}`}>{order.side === "BUY" ? <ArrowDownRight size={14} /> : <ArrowUpRight size={14} />}</span><div className="tf-order-main"><b>{order.side} {order.instrument}</b><small>{order.quantity} units · {order.state.replaceAll("_", " ")}</small></div><span className={`tf-order-state ${order.state === "FILLED" ? "filled" : ""}`}>{order.fills[0] ? `€${order.fills[0].price}` : order.state.replaceAll("_", " ")}</span>{detailed && <time>{formatTime(order.createdAt)}</time>}</div>)}</div>; }
function NotificationList({ notifications, detailed = false }: { notifications: Notification[]; detailed?: boolean }) { return <div className="tf-notifications">{notifications.map((notification) => <div className={`tf-notification ${notification.severity}`} key={notification.id}><span><AlertTriangle size={14} /></span><div><b>{notification.title}</b><small>{notification.detail}</small></div>{detailed && <time>{formatTime(notification.time)}</time>}</div>)}</div>; }
function NotificationPopover({ notifications, unread, onRead, onClose }: { notifications: Notification[]; unread: number; onRead: () => void; onClose: () => void }) { return <div className="tf-notification-popover"><div><b>Notifications</b><button onClick={onClose}><X size={14} /></button></div>{notifications.length ? <NotificationList notifications={notifications.slice(0, 5)} detailed /> : <Empty label="No notifications" />}<button className="tf-read-button" disabled={!unread} onClick={onRead}>Mark all read</button></div>; }
function MiniChart({ points }: { points: Array<{ date: string; value: string }> }) { const values = points.map((point) => Number(point.value)); const min = Math.min(...values) - 1; const max = Math.max(...values) + 1; const width = 700; const height = 190; const denominator = Math.max(values.length - 1, 1); const coords = values.map((value, index) => `${(index / denominator) * width},${height - ((value - min) / (max - min)) * height}`).join(" "); return <div className="tf-mini-chart"><svg viewBox={`0 0 ${width} ${height + 20}`} role="img" aria-label="Equity curve"><defs><linearGradient id="tfGradient" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#b9f56d" stopOpacity=".25" /><stop offset="1" stopColor="#b9f56d" stopOpacity="0" /></linearGradient></defs><polygon points={`0,${height} ${coords} ${width},${height}`} fill="url(#tfGradient)" /><polyline points={coords} fill="none" stroke="#b9f56d" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg><div><span>{points[0]?.date}</span><span>{points.at(-1)?.date}</span></div></div>; }
function StopModal({ busy, onClose, onConfirm }: { busy: boolean; onClose: () => void; onConfirm: () => void }) { const [text, setText] = useState(""); return <Modal><div className="tf-modal-icon danger"><Zap size={23} fill="currentColor" /></div><span className="tf-eyebrow danger-text">Emergency automation freeze</span><h2>Stop everything?</h2><p>New orders will be blocked, auto trading will stop, and safe pending entries will be cancelled. Existing positions will not be sold.</p><div className="tf-modal-warning"><AlertTriangle size={16} />Emergency liquidation is separate. This button does not sell.</div><label>Type <b>STOP</b> to confirm<input autoFocus placeholder="STOP" value={text} onChange={(event) => setText(event.target.value)} /></label><div className="tf-modal-actions"><button className="tf-secondary" onClick={onClose}>Keep running</button><button className="tf-stop-button" disabled={text !== "STOP" || busy} onClick={onConfirm}>{busy ? <RefreshCw className="spin" size={15} /> : <Zap size={15} fill="currentColor" />}Activate stop</button></div></Modal>; }
function CloseSessionModal({ busy, onClose, onConfirm }: { busy: boolean; onClose: () => void; onConfirm: () => void }) { const [text, setText] = useState(""); return <Modal><div className="tf-modal-icon safe"><CheckCircle2 size={23} /></div><span className="tf-eyebrow">End paper session</span><h2>Enough for today?</h2><p>This pauses automatic paper trading and submits bounded SELL orders for every open simulated position. It realizes today's simulated winnings or losses.</p><div className="tf-modal-warning neutral"><ShieldAlert size={16} />This is a deliberate paper-session close, not the emergency kill switch.</div><label>Type <b>CLOSE</b> to confirm<input autoFocus placeholder="CLOSE" value={text} onChange={(event) => setText(event.target.value)} /></label><div className="tf-modal-actions"><button className="tf-secondary" onClick={onClose}>Keep trading</button><button className="tf-primary" disabled={text !== "CLOSE" || busy} onClick={onConfirm}>{busy ? <RefreshCw className="spin" size={15} /> : <CheckCircle2 size={15} />}Pause and sell positions</button></div></Modal>; }
function Modal({ children }: { children: ReactNode }) { return <div className="tf-modal-backdrop"><div className="tf-modal">{children}</div></div>; }
function Empty({ label }: { label: string }) { return <div className="tf-empty"><Activity size={17} /><span>{label}</span></div>; }
function LoadingState({ error, onRetry }: { error: string | null; onRetry: () => void }) { return <div className="tf-loading"><span className="tf-mark">TF</span><RefreshCw className={!error ? "spin" : ""} size={20} />{error ? <><h2>Paper terminal unavailable</h2><p>{error}</p><button className="tf-primary" onClick={onRetry}>Retry</button></> : <p>Connecting to TradeForge paper operations...</p>}</div>; }
function pageDescription(page: Page) { return { Overview: "", Holdings: "See exactly what the paper account holds.", Orders: "Every simulated buy and sell, with the fill price.", Activity: "Safety notifications and audit events.", Settings: "The small set of boundaries that cannot be bypassed." }[page]; }
function formatTime(value: string | null) { return value ? new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "-"; }

export default App;
