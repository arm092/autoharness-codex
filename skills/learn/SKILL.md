---
name: learn
description: Use when the user asks to remember a lesson, learn from this session, or run AutoHarness learning now.
---
Call learn_episode with the current session_id provided by the AutoHarness hook context.
The tool queues the registered transcript, not a reconstructed story. Never invent a quote.
If hooks have not registered this session, explain that trusted hooks must run first.
Report queued status and job id. Use library_status to inspect applied/rejected results later.
Do not claim learning succeeded merely because the job was queued or staged.
Do not modify built-in Codex memories or skills installed by other plugins.

Pass the current context_token from AutoHarness hook context in every MCP call. Never use another chat's token.
