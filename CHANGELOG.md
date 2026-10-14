# Changelog

## 1.2.1 – 2026-10-14

- Add default-checked Restart Codex and Open AutoHarness plugin page options after successful interactive Setup.
- Defer desktop actions until Finish; skip them for silent, failed, or canceled installations.
- Request graceful desktop shutdown through Windows Restart Manager, without forced termination, and wait before relaunch.
- Detect the installed MSIX desktop dynamically; retain manual restart when shutdown is refused or app/profile discovery is uncertain.
- Open the documented local plugin detail link; hook review/trust remains manual through `/hooks` in Codex CLI.

## 1.2.0 – 2026-10-14

- Add a per-user Windows x64 Setup.exe with Russian/English wizard, CLI/profile selection, repair/update, and uninstall.
- Bundle pinned official CPython 3.13.16; installed users do not need system Python or administrator permissions.
- Check compatibility and registration ownership before installing; retain recoverable pending install state.
- Refresh Codex's native plugin cache during repair and update; record the selected CLI without changing PATH.
- Unregister only after uninstall confirmation; preserve the knowledge library and unrelated marketplaces.
- Verify embedded hooks, MCP, and detached workers with system Python absent from PATH.

## 1.1.0 – 2026-10-14

- Distinguish direct user instructions, quoted material, tool observations, assistant claims, and manual lessons.
- Bind quotations to typed source record ids and preserve provenance through history and restore.
- Add local technical retrieval for English, Russian, Armenian, French, and Spanish, including accents and aliases.
- Add library_search MCP and CLI search with relevance thresholds and inspectable matched terms.
- Reduce reflector payloads through source selection and complete relevant skill packages under byte limits.
- Account for CLI-reported input, cached input, and output separately from conservative estimates.
- Reserve per-scope daily token budgets transactionally; preserve jobs deferred by budgets.
- Keep reported usage even when proposal parsing fails; source-less episodes avoid a model call.
- Retain the product roadmap in ROADMAP.md and the installation ZIP.

## 1.0.0 – 2026-10-14

- Automatic episode reflection and manual learning through Codex CLI.
- Native Codex hooks, four workflow skills, and eleven MCP tools.
- Context-bound project libraries and opt-in global scope.
- Verified evidence quotations, ownership checks, optimistic concurrency, and atomic merge batches.
- Immutable versions, archive recovery, scope-only curator snapshots, and pins.
- Durable proposals, committed-receipt recovery, worker leases, retry and model-call budgets.
- No runtime third-party dependencies. Windows package command quoting is verified.
