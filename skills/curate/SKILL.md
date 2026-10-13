---
name: curate
description: Use when the user asks to consolidate, deduplicate, organize, or clean up AutoHarness skills.
---
Call curate_library to queue consolidation of plugin-owned skills only.
Never use low frequency alone as a reason to remove knowledge.
Consolidation must move all relevant support files and instructions to the survivor before archiving its source.
Archive is recoverable. Never hard-delete history or modify another plugin's files.
Report the job id and queued status. Inspect library_status for the actual result.

Pass the current context_token from AutoHarness hook context in every MCP call. Never use another chat's token.
