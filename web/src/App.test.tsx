import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const fixture = {
  product: "TradeForge", mode: "PAPER", modeLabel: "PAPER - SYNTHETIC MARKET DATA", marketDataMode: "SYNTHETIC", demo: true, liveExecution: false,
  system: { status: "HEALTHY", bot: "RUNNING", broker: "HEALTHY", market: "HEALTHY", risk: "HEALTHY", reconciliation: "OK", lastUpdate: "2026-08-24T12:00:00Z" },
  control: { state: "RUNNING", reason: "", killSwitch: false, activatedAt: null, cancelPendingOnPause: true },
  automation: { running: false, strategy: "Demo Trend v1", intervalSeconds: 5, lastAction: null, tick: 0, sessionClosed: false },
  metrics: { totalEquity: "124.94", availableCash: "64.79", investedCapital: "60.15", withdrawableCash: "64.79", totalDeposits: "100.00", totalWithdrawals: "0.00", realizedPnl: "18.42", unrealizedPnl: "2.14", totalPnl: "20.56", todayPnl: "1.12", weekPnl: "4.18", monthPnl: "8.92", yearPnl: "18.42", allTimePnl: "18.42", currentDrawdown: "2.8%", maxDrawdown: "6.4%", currentExposure: "60.15", positions: 3, openOrders: 0, fees: "0.20", winRate: "64.3%", profitFactor: "1.84" },
  risk: { mode: "AUTO", hardLimits: { totalCapital: "150.00", maxPosition: "25.00", maxExposure: "75.00", maxOpenPositions: 3, dailyLoss: "5.00", dailyProfit: "20.00", maxDrawdown: "10%" }, currentTarget: "12.50", allowedMin: "1.00", allowedMax: "25.00", dailyUsed: "1.12", dailyLossBudget: "5.00" },
  charts: { equity: [{ date: "24 Aug", value: "124.94" }], pnl: [], drawdown: [] }, positions: [], orders: [], notifications: [], unreadNotifications: 0, audit: [], health: [], scenarios: [],
};

class MockWebSocket {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close() {}
  constructor() { /* dashboard stream is intentionally quiet in this test */ }
}

describe("TradeForge dashboard safety controls", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => fixture }));
  });

  it("requires typed confirmation before activating STOP EVERYTHING", async () => {
    render(<App />);
    expect(await screen.findByText("PAPER · SYNTHETIC DATA")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /stop everything/i }));
    expect(screen.getByRole("heading", { name: "Stop everything?" })).toBeInTheDocument();
    const confirm = screen.getByPlaceholderText("STOP");
    expect(screen.getByRole("button", { name: /activate stop/i })).toBeDisabled();
    fireEvent.change(confirm, { target: { value: "STOP" } });
    expect(screen.getByRole("button", { name: /activate stop/i })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: /activate stop/i }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/control/stop-everything"), expect.objectContaining({ method: "POST" })));
  });
});
