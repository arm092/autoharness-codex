---
name: library-status
description: Use when inspecting AutoHarness skills, learning results, failed jobs, history, or usefulness.
---
Call library_status and library_list. Identify applied, queued, proposed, rejected, and failed separately.
Read a relevant skill with library_read before using it; current user instructions override learned guidance.
library_read increments views. Record uses only when applying a skill; helpful only after explicit user confirmation.
Use library_history to inspect provenance. Never equate loading or a model-generated claim with verified success.
Global scope requires deployment opt-in. Never fall back to another project's data.

Pass the current context_token from AutoHarness hook context in every MCP call. Never use another chat's token.
