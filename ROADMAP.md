# AutoHarness for Codex roadmap

Updated: 2026-10-14. This is retained product documentation, not a temporary process log.

## Released: 1.0.0

Automatic/manual learning, plugin-owned libraries, quotation checks, immutable history, atomic merges,
recovery, pins, native Codex hooks, context-bound MCP, Windows packaging, and a six-configuration CI matrix.

## 1.1.0: implemented scope

### 1. Distinguish knowledge sources

- Classify direct user instructions, quoted/external material, observable tool results, assistant hypotheses,
  explicit manual lessons, and curator library observations.
- Verify proposal source ids and quotations against deterministic episode records.
- Prevent external/assistant-only text from becoming a user preference.
- Keep source metadata in version history without rewriting existing 1.0 versions.

### 3. Retrieve relevant skills

- Support English, Russian, Armenian, French, and Spanish technical requests.
- Use Unicode normalization, technical concept aliases, positive relevance thresholds, and inspectable rankings.
- Return no recommendations for unrelated requests; reuse ranking for model candidate selection.
- Keep retrieval local, without an embedding service or an additional API key.

### 4. Reduce context and account for costs

- Select significant episode events and complete related skill packages under configured context limits.
- Preserve a small description index so omitted bodies remain visible as candidates.
- Record actual CLI usage separately from estimates when exact usage is unavailable.
- Enforce transactional daily token budgets and retain jobs deferred by budgets.
- Surface selected/omitted context and usage in status and diagnostics.

Delivered through typed episode provenance, local technical aliases for five languages, library_search,
bounded complete packages, CLI turn.completed usage, and transactional per-scope UTC-day reservations.
Output allowance is an admission reserve, not a provider-enforced generation limit. Observations and source
attribution do not prove a rule's semantic correctness; usefulness evaluation remains item 6.

## 1.2.0: Windows installation

Per-user Russian/English Setup.exe with embedded runtime, native registration, repair/update and uninstall.
No separate Python installation or administrator permissions. Preserve knowledge and require native hook trust.
Pinned runtime checksum, build workflow and embedded hook/MCP/worker smoke checks.

1.2.1 adds default-checked graceful desktop restart and local plugin-page opening after interactive Finish.
Custom desktop profiles remain manual; direct hook navigation requires a supported host link that is not currently documented.

## 1.3.0: macOS packaging

Separate native Apple Silicon/Intel DMG installers with bundled standalone runtime, per-user immutable program releases,
owned registration/unregister and native CI. Signing uses ad-hoc integrity signatures; Developer ID/notarization and
automatic macOS desktop restart remain future work requiring the relevant credentials or host integration.

## Next release: correctness and reliability hardening

Based on the [complete comparison of 47 upstream issues](docs/UPSTREAM_ISSUE_AUDIT.md), reviewed against v1.3.0 on 2026-10-14.
Closed upstream reports remain useful regression scenarios; their state does not imply an unresolved upstream defect.

### P1: fix demonstrated gaps

- Replace mixed-quote stripping with matching outer-pair parsing. Specify the supported frontmatter subset; reject unsupported multiline/ambiguous fields. Preserve inner quotes and validate index metadata.
- Reduce legitimate `exec(`/`eval(` example rejection without permitting automatic scripts or loosening model execution boundaries. Add positive attack fixtures and negative instructional-code fixtures.
- Fail CI if discovery collects zero tests; report collected and skipped counts independently of exit status.
- Harden privacy fixtures for complete/incomplete PEM, escaped JSON, clipping and split records, and repeated redaction. Add validated credit-card detection with negative business-identifier fixtures; current rules do not cover cards.

Acceptance: reproduce the two policy defects first, demonstrate corrected results and retained safety gates, and exercise an intentionally empty test suite against the CI guard.

### P2: knowledge quality and operational visibility

- Detect semantically duplicate candidates across successive runs before promotion; do not equate replay idempotence with semantic deduplication.
- Define and expose scope identity for non-Git directories, Git submodules and linked worktrees. Keep ordinary Git subdirectory behavior and profile isolation covered.
- Add optional completion/rejection notifications with redacted summaries, bounded delivery and failure isolation. Notifications remain off by default.
- Ship an opt-in real-model lifecycle runbook and anonymized fixtures covering trusted host hooks, dispatch, learning, consolidation, recall and recovery. Keep offline/native smoke separate from real assistance evaluation.
- Strengthen behavioral coverage for large SessionStart indexes, metadata injection, all support-file directories, individual concurrent feedback counters and retirement-before-index ordering.

### P3: distribution and storage controls

- Consider configurable snapshot retention and safe collection of unpublished orphan revisions; never silently delete recoverable knowledge.
- Keep platform installation/update/uninstall instructions consistent. Consider external plugin listings as separately authorized publication work.
- Retain macOS Developer ID/notarization and graceful restart on the platform roadmap.

## Later: not included in 1.3.0

### 2. Trial status for new skills

Keep new rules as candidates, strengthen them with repeated evidence, and revise or reject them after user correction.
A successful one-off case should not automatically become a universal instruction.

### 5. Contradictions and expiration

Associate rules with environment/version conditions; detect contradictory rules and mark stale knowledge for review.
Example: a Homestead rule must not silently apply after a project moves to Docker.

### 6. Evaluate usefulness on real tasks

Maintain anonymized episode fixtures and measure lesson extraction, fabricated-rule rejection, retrieval,
and knowledge retention after consolidation. Separate software correctness from actual assistance quality.

### Platform compatibility

Expand automatic compatibility diagnostics after Codex updates. Transcript formats are not a stable hook interface;
prefer stable lifecycle fields where possible and keep unknown formats conservative.

## Development boundaries

No changes to unrelated projects, built-in Codex memories, or third-party skills. Process files remain outside master.
Keep source attribution honest, rare useful knowledge recoverable, and model costs visible.
Further roadmap items require a separate implementation request; their presence here is not authorization to ship them.
