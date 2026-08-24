export type Severity = "info" | "warning" | "critical";

export interface Dashboard {
  product: string;
  mode: string;
  modeLabel: string;
  marketDataMode: string;
  demo: boolean;
  liveExecution: boolean;
  system: {
    status: string;
    bot: string;
    broker: string;
    market: string;
    risk: string;
    reconciliation: string;
    lastUpdate: string;
  };
  control: {
    state: string;
    reason: string;
    killSwitch: boolean;
    activatedAt: string | null;
    cancelPendingOnPause: boolean;
  };
  automation: {
    running: boolean;
    strategy: string;
    intervalSeconds: number;
    tradeEverySeconds: number;
    lastAction: string | null;
    tick: number;
    sessionClosed: boolean;
  };
  metrics: Record<string, string | number>;
  risk: {
    mode: string;
    hardLimits: Record<string, string | number>;
    currentTarget: string;
    allowedMin: string;
    allowedMax: string;
    dailyUsed: string;
    dailyLossBudget: string;
  };
  charts: {
    equity: Array<{ date: string; value: string }>;
    pnl: Array<{ label: string; value: string; color: string }>;
    drawdown: Array<{ label: string; value: string }>;
  };
  positions: Position[];
  orders: Order[];
  notifications: Notification[];
  unreadNotifications: number;
  audit: AuditEvent[];
  health: HealthItem[];
  scenarios: Array<{ id: string; label: string }>;
}

export interface Position {
  instrument: string;
  isin: string;
  ticker: string;
  side: string;
  quantity: string;
  averageEntry: string;
  currentPrice: string;
  marketValue: string;
  costBasis: string;
  unrealizedPnl: string;
  returnPct: string;
  exposure: string;
  strategy: string;
  openedAt: string | null;
  riskStatus: string;
}

export interface Order {
  id: string;
  brokerId: string;
  instrument: string;
  side: string;
  quantity: string;
  state: string;
  createdAt: string | null;
  message: string;
  fills: Array<{ quantity: string; price: string; fees: string }>;
}

export interface Notification {
  id: string;
  severity: Severity;
  title: string;
  detail: string;
  time: string | null;
  read?: boolean;
}

export interface AuditEvent {
  eventId: string;
  type: string;
  origin: string;
  time: string | null;
  detail: string;
}

export interface HealthItem {
  name: string;
  status: string;
  latency: string;
  detail: string;
}
