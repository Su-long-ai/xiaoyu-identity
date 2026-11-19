# Provider privacy admission

XiaoYu keeps provider privacy as a thin overlay policy rather than rebuilding N.E.K.O's provider runtime.

`provider_policy.json` is an explicit endpoint allowlist. The checker resolves every relevant N.E.K.O model tier through N.E.K.O's own `ConfigManager.get_model_api_config()`, then validates the final hostname. Unknown hosts fail closed.

This catches configuration-time fallback such as a custom slot silently resolving to the assist/core provider. The current shared N.E.K.O chat factory constructs a single client from one resolved endpoint and SDK retries stay on that client; no error-driven cross-provider failover was found in the audited `7b776173...` source.

The gate intentionally denies N.E.K.O's public free relay and common third-party model routers by default. This is a private XiaoYu policy choice, not a claim that all allowlisted first-party vendors have identical privacy terms.

Runtime provider-change boundary is now accepted for the XiaoYu product scope. Provider/model/endpoint resolution is captured per call/session rather than mutating an existing client in place. Saving provider settings notifies clients, retires the captured pre-save sessions with an expected-session identity guard, then reloads configuration. A manual provider edit is therefore treated as an explicit owner-authorized reconfiguration boundary, not silent fallback.

## Runtime provider-change boundary

The audited N.E.K.O request path resolves one endpoint into one client and SDK retries remain on that client. Core session setup resolves paired model configuration from one snapshot; changing API settings ends active sessions and reloads configuration rather than mutating an existing session in place.

XiaoYu therefore treats automatic fallback and manual owner provider changes differently:

- Automatic cross-provider fallback to a denied relay/router is not accepted and was not found in the audited shared factory.
- An owner manually changing provider settings is an explicit configuration operation, not a fallback. Existing in-flight sessions retain their captured client/provider and the save path retires the captured sessions before the new configuration becomes the next-session authority.
- Normal XiaoYu startup reruns the provider preflight through run_checks.ps1 / check_provider_privacy.py. Unknown endpoints and denied relay/router endpoints fail closed.

We intentionally do not add a N.E.K.O core patch solely to police an explicit owner settings change.
