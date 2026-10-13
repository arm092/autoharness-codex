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

## Later: not included in 1.1.0

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
