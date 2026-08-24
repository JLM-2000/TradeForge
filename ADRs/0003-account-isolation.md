# ADR 0003: Account Isolation

- Status: Accepted
- Decision: Orders require an exact positive `BOT_ACCOUNT_ID` match and are
  checked against a personal-investment denylist.
- Reason: The execution architecture, not an AI prompt, must make personal
  investment access impossible.
