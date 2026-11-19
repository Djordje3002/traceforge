# Threat model and limits

TraceForge models an agent that may follow malicious text, choose a forbidden tool, supply invalid arguments, loop, or misunderstand an uncertain write. Retrieved documents and tool results are untrusted inputs. Trusted code supplies capabilities and the grader.

## Boundaries that exist

- The agent has only five declared business tools; there is no shell or arbitrary Python execution tool.
- Every episode owns an isolated simulated world. Policy checks run outside the agent's decision logic.
- Input and output contracts reject unexpected structure. Tool outputs cannot expand capabilities.
- The HTTP server binds `127.0.0.1`, rejects non-loopback Host headers and cross-origin browser requests, requires JSON mutation bodies, and serves only a fixed asset allowlist.
- Provider credentials are environment-only and never accepted through API run configuration or the dashboard. Upstream error bodies are not copied into traces.
- The UI escapes dynamic text; event payloads render as text, not HTML. A restrictive content policy disables third-party scripts and framing.

## Boundaries that do not exist

- This is not an OS/container sandbox for untrusted code. Never load arbitrary tool implementations from an untrusted user.
- The local server has no user authentication, TLS termination, distributed rate limiter, or multi-tenant access controls. Do not expose its port publicly.
- Any process with access to the SQLite file can read or rewrite traces. Hash chains provide tamper evidence against incomplete edits, not adversarial database-owner authenticity.
- The token-marker content check is a demonstration rule, not general DLP or prompt-injection detection. It does not inspect arbitrary encodings, paraphrases, or all outbound channels.
- State-based grading enumerates known violations; it cannot prove general safety. There are no claims about unseen attacks.
- Real model providers receive the simulated task, capabilities, and tool observations. Their own privacy and retention policies apply.
- Cancellation of an in-flight thread-backed HTTP call cannot retract a request already sent to the provider. Its timeout bounds network waiting, but it can finish after an episode deadline.

Run configurations cannot choose a provider base URL or API key; those are trusted server settings. Do not run the app in an environment where untrusted parties can edit those variables. Avoid putting confidential user information into custom scenarios or public trace exports. The included customers, addresses, orders, and secret marker are fictional.

For suspected vulnerabilities, open a minimal issue without credentials or private traces. This project has no dedicated private vulnerability intake or response SLA.
