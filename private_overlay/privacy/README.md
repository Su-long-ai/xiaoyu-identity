# Provider privacy admission

XiaoYu keeps provider privacy as a thin overlay policy rather than rebuilding N.E.K.O's provider runtime.

`provider_policy.json` is an explicit endpoint allowlist. The checker resolves every relevant N.E.K.O model tier through N.E.K.O's own `ConfigManager.get_model_api_config()`, then validates the final hostname. Unknown hosts fail closed.

This catches configuration-time fallback such as a custom slot silently resolving to the assist/core provider. The current shared N.E.K.O chat factory constructs a single client from one resolved endpoint and SDK retries stay on that client; no error-driven cross-provider failover was found in the audited `402695cd...` source.

The gate intentionally denies N.E.K.O's public free relay and common third-party model routers by default. This is a private XiaoYu policy choice, not a claim that all allowlisted first-party vendors have identical privacy terms.

Current limitation: N.E.K.O can change provider configuration while running. The preflight gate does not yet prove that a hot provider switch cannot race an in-flight private request. Until that is closed, provider privacy remains partial acceptance rather than DONE.

## Runtime provider-change boundary

The audited N.E.K.O request path resolves one endpoint into one client and SDK retries remain on that client. Core session setup resolves paired model configuration from one snapshot; changing API settings ends active sessions and reloads configuration rather than mutating an existing session in place.

XiaoYu therefore treats automatic fallback and manual owner provider changes differently:

- Automatic cross-provider fallback to a denied relay/router is not accepted and was not found in the audited shared factory.
- An owner manually changing provider settings is an explicit configuration operation, not a fallback. Before continuing private XiaoYu use after such a change, rerun the provider preflight through run_checks.ps1 or check_provider_privacy.py.

We intentionally do not add a N.E.K.O core patch solely to police an explicit owner settings change.
