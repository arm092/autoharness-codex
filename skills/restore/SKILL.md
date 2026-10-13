---
name: restore
description: Use when the user asks to undo an AutoHarness change or restore a previous managed skill version.
---
Read library_history and library_read to identify the requested version and current hash.
Call library_restore with name, version, expected_hash after the user identifies the change to undo.
If the current hash changed, inspect the newer version and explain the conflict; never force overwrite.
Report the returned content. Do not delete previous version files.

Pass the current context_token from AutoHarness hook context in every MCP call. Never use another chat's token.
