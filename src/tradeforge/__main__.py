"""Safe local status command; it never submits an order."""

from __future__ import annotations

from .config import Settings


def main() -> int:
    settings = Settings.from_env()
    print("TradeForge")
    print(f"MODE={settings.mode.value}")
    print(f"BOT_ACCOUNT_ID={settings.bot_account_id}")
    print(f"LIVE_EXECUTION_ALLOWED={settings.live_execution_allowed}")
    print("REAL_BROKER_CONNECTION=DISABLED")
    print("WITHDRAWALS=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
