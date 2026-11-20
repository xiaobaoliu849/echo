# Community server updates

Community clients load their voice provider list from the hosted server's
`/api/billing/hosted-info` response. Adding a provider to the desktop source or
pushing to GitHub does not update the running server. Rebuilding a community
installer alone also leaves the server unchanged.

For MOSS-Live, update both the community client and hosted backend. The backend
must include `services/realtime_moss_provider.py`, offer `MOSS` with model
`moss-live-1.0`, and have `api_keys.moss_api_key` configured in its private runtime
configuration. Keep that key on the server; never put it in a frontend bundle,
installer configuration, deployment archive, or Git commit.

Before restarting the server, back up the application and configuration, check
that the new backend imports in its server virtual environment, and check for
active calls. Preserve the existing accounts, balances, provider credentials,
and other runtime data. Keep a rollback copy until verification is complete.

After restarting, verify:

- The backend health endpoint responds successfully.
- `/api/billing/hosted-info` includes `MOSS` and `moss-live-1.0`. If
  `hosted_settings.providers` is explicitly configured, it replaces the default
  offering and must include MOSS to make it available.
- The same response through the community client's local backend includes MOSS.
- The community voice picker displays **Donald Trump** under MOSS-Live. A fresh
  community call selects that preset using voice ID
  `5e36ed14-b48a-5cb9-8c81-f61b00bab50e`, which the provider acknowledges during
  session setup.

Refresh or reopen the community client after changing the server offering so it
fetches the updated list. Existing explicit voice preferences remain available.
