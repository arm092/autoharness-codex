# Data and security boundaries

The plugin writes only its own data namespace. It does not edit AGENTS.md, native Codex memories,
user-authored skills, or skills belonging to other plugins. MCP project selection uses an opaque
hook context token; the installed server refuses calls without the current chat context.

Default data: CODEX_HOME/autoharness-codex (usually ~/.codex/autoharness-codex).
Both hooks and MCP use this stable namespace; PLUGIN_DATA is intentionally not used because
the hook and MCP environments can differ. Override with AUTOHARNESS_CODEX_DATA consistently
for both processes. Keep this directory private: it contains redacted evidence and learned text.

A reflector is a read-only, ephemeral Codex CLI process with user config, rules, hooks, plugins,
host skill discovery, shell, browser, computer-use, and collaboration tools disabled.
It uses the existing Codex credential store; this plugin does not read or copy credentials.
The child does not inherit unrelated environment secrets or OPENAI_API_KEY.

History text and generated skills are untrusted. Secret redaction and dangerous-pattern checks
are heuristic filters. A valid evidence quote proves provenance, not truth or safety.
Supported source roles and source ids are assigned by the plugin. Tool/assistant/unknown text cannot
be presented as a direct user preference. Quotes from multiple ids must support each selected source.
An exit code of zero is a mechanical observation, not proof of task success or semantic validity.
Current user instructions and permissions take precedence over learned instructions.
New or changed scripts require manual CLI admission with --allow-scripts; the validator never executes them.

Immutable versions are prepared before a SQLite transaction publishes pointers. A failed transaction
cannot partly publish a merge. Unreferenced prepared versions are retained after a crash; no automatic
garbage collection deletes evidence. Publication receipts and durable proposals recover interrupted jobs.
The storage rejects existing symlink and Windows reparse-point path components. This is not protection
against an adversary with concurrent write access to the same OS account or data directory.

Daily token admission reserves estimates transactionally in the same owned database. Exact CLI usage,
when available, is recorded even if the generated proposal is rejected or malformed. Crash/missing-report
reservations remain conservatively charged. This is not a monetary cap or a provider-side output limit.

Installing this package does not establish hook trust. Review definitions with /hooks in Codex.
The plugin never bypasses hook trust or the model sandbox. Review again after changes.
