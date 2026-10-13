# AutoHarness for Codex

A self-maintaining skill library for Codex, inspired by [tigerless-labs/autoharness](https://github.com/tigerless-labs/autoharness).

AutoHarness learns reusable lessons from session transcripts, verifies their evidence, consolidates overlapping
skills, and keeps recoverable history. It manages only its own library.

Version 1.1 adds typed source provenance, five-language technical search, smaller context,
and visible daily token admission budgets. The retained development plan is [ROADMAP.md](ROADMAP.md).

## Requirements

Python 3.11+ and a signed-in Codex CLI with native plugins and hooks. No third-party runtime dependencies
or separate API key. Windows was verified with Python 3.12.1 and Codex CLI 0.159.0-alpha.12.1.
Background reflection consumes your Codex model allowance.

## Install

Clone this repository or extract the ZIP to a permanent folder. From that folder:

```powershell
python scripts/entry.py doctor
codex plugin marketplace add .
codex plugin add autoharness-codex@autoharness-codex-local
```

If the desktop CLI is not on PATH:

```powershell
$taskCodex = Join-Path $env:USERPROFILE '.codex/.sandbox-bin/codex.exe'
& $taskCodex plugin marketplace add .
& $taskCodex plugin add autoharness-codex@autoharness-codex-local
```

Start a fresh session and review/trust the five plugin hooks using `/hooks`.
Installation alone does not trust hooks. The plugin never bypasses trust.
This is a manual desktop/local package, not a public plugin directory submission.

The source resolves Python from PATH: python3 on Unix, python on Windows.
Prepared ZIPs pin the packaging machine's Python executable. Rebuild on another machine:

```powershell
python scripts/package.py --output ../autoharness-codex.zip
```

Choose a fresh output path. `--portable` retains PATH-based Python.

## Use

Work normally. After 50 completed tool calls, Stop queues a redacted episode.
SessionEnd queues remaining complete records. Reflection runs in a background worker.
SessionStart adds a bounded index; UserPromptSubmit surfaces a small relevant subset.

Ask Codex to learn from this session, inspect the library, consolidate skills, or restore a version.
Four packaged skills route these requests to twelve MCP tools.
All installed MCP calls include the current hook context_token, so the MCP plugin folder
cannot be mistaken for your project. A missing context means hooks must run first.

Staging is separate from applying. library_status reports queued, proposed, applied, rejected, and failed.
Loading counts as a view, not a successful outcome. Only explicit user confirmation counts as helpfulness.

### Knowledge sources and retrieval

Source roles come from supported transcript structure, never from a tool output saying "User: ...".
Direct user text, fenced/quoted material, tool results, assistant text, explicit manual input, and library observations
are attributed separately. Unknown formats are conservative: assistant/unknown/quoted-only episodes do not justify
new rules. Multipart user messages are parsed per text part so generated context does not hide the real request.

Every new structured proposal carries lesson_kind and evidence_ids. Quotations must match those records.
When citing several records, join one quotation per id in the same order with a newline, ---, and a newline.
User preferences require direct user text; a verified_technique pairs a user quotation with an observed zero-exit
tool result. This proves source pairing and exit status, not that the assistant's interpretation is correct.
Raw CLI episode files are explicitly manual lessons, not asserted native user instructions.
Existing 1.0 versions retain their original hashes and are labelled legacy_untyped rather than retroactively trusted.

library_search and CLI search support technical vocabulary in English, Russian, Armenian, French, and Spanish.
Unicode/accents and documented concept aliases help match related requests; this is local ranking, not a universal
translator or an embedding service. Unrelated/generic queries return no recommendations. matched_terms and
relevance explain a match. Hook recall and model candidate selection reuse this ranking.

## CLI

Global options precede the command. --cwd selects the project; --data selects owned storage.

```powershell
python scripts/entry.py --cwd C:/Projects/my-app status
python scripts/entry.py --cwd C:/Projects/my-app list
python scripts/entry.py --cwd C:/Projects/my-app search "ejecutar las pruebas de Laravel"
python scripts/entry.py --cwd C:/Projects/my-app learn --episode-file episode.txt --wait
python scripts/entry.py --cwd C:/Projects/my-app history skill-name
python scripts/entry.py --cwd C:/Projects/my-app pin skill-name
python scripts/entry.py --cwd C:/Projects/my-app restore skill-name --version 1 --expected-hash CURRENT_HASH
```

learn --episode-file processes explicitly supplied text; it does not scan other sessions.
Without --wait it queues background work. A wait reports the worker's result, including budget delays.
work drains eligible jobs; no daemon is installed. Backlogged jobs resume on later session hooks or manual work.
retry JOB_ID requeues failed/rejected jobs, still respecting budgets.
preview --job-id ID --proposal-file proposals.json validates without writing skills.
apply with the same arguments and --allow-scripts admits explicitly reviewed scripts; it never executes them.
Proposal files contain an array, or an object with a proposals array.

## Configuration

Set these variables for both hook and MCP processes and restart Codex.

| Variable | Default | Meaning |
| --- | --- | --- |
| AUTOHARNESS_CODEX_DATA | CODEX_HOME/autoharness-codex | Stable owned data namespace |
| AUTOHARNESS_CODEX_BIN | PATH or desktop fallback | Codex executable |
| AUTOHARNESS_CODEX_MODEL | CLI default | Optional reflector model |
| AUTOHARNESS_CODEX_AUTO | 1 | 0 disables automatic queueing |
| AUTOHARNESS_CODEX_CADENCE | 50 | Completed calls before reflection |
| AUTOHARNESS_CODEX_DEBOUNCE | 60 | Seconds between model calls |
| AUTOHARNESS_CODEX_HOURLY_LIMIT | 4 | Model attempts per project per hour |
| AUTOHARNESS_CODEX_TIMEOUT | 180 | Model timeout in seconds |
| AUTOHARNESS_CODEX_CONSOLIDATE | 250 | Completed replies between curator opportunities; 0 disables |
| AUTOHARNESS_CODEX_GLOBAL | 0 | Opt-in global library |
| AUTOHARNESS_CODEX_RETIRE | 0 | Opt-in usage-based compatibility retirement |
| AUTOHARNESS_CODEX_SOURCE_BYTES | 24000 | Selected episode JSON byte cap |
| AUTOHARNESS_CODEX_LIBRARY_BYTES | 32000 | Complete selected skill package byte cap |
| AUTOHARNESS_CODEX_PROMPT_BYTES | 64000 | Total reflector prompt byte cap |
| AUTOHARNESS_CODEX_OUTPUT_ALLOWANCE | 8192 | Tokens reserved for generation, not a hard provider limit |
| AUTOHARNESS_CODEX_DAILY_TOKENS | 200000 | Per-scope UTC-day admission budget |

With GLOBAL=1, use --scope global learn for explicit global learning.
Automatic reflection remains project-scoped; it does not promote rules globally by itself.
Git subdirectories share their checkout's identity. Linked worktrees remain separate.
Without Git, the canonical working folder identifies the project.
PLUGIN_DATA is intentionally not used: native hook and MCP environments may differ.

### Context and usage accounting

The model receives significant typed source records, related complete skill packages, and a small description index.
If a package is too large, it is omitted entirely; its support files are never silently dropped.
Truncated source excerpts keep their original ids, so their quoted text remains verifiable against stored evidence.
status reports selected/omitted records and skills, source/library/prompt bytes, and actual versus estimated usage.

Before a model attempt, SQLite reserves prompt/schema bytes plus a host allowance and OUTPUT_ALLOWANCE against
the scope's UTC-day budget. A deferred job stays queued. Later hooks or manual work retry eligible jobs.
CLI turn.completed usage settles input + output; cached input is reported separately and is not subtracted.
When reports are unavailable, or a process crashes, the conservative reservation remains charged.
Malformed proposals still account for reported tokens. These figures are not billing prices or account quotas.

The daily limit controls admission using an estimate. It cannot undo a call that reports more tokens than reserved;
overruns are visible and block further admission once the limit is exceeded. OUTPUT_ALLOWANCE does not impose
a provider-side maximum. User/config/model context can differ from estimates, which are never presented as exact.

## Storage and recovery

SQLite tracks ownership, jobs, evidence, versions, receipts, contexts, and counters.
New provenance and usage tables are additive; existing 1.0 data and history remain readable.
Directories under revisions/ are immutable versions, with support files and evidence.
One transaction publishes a complete batch. Failed merges leave live skills unchanged.
Committed receipts and staged proposals recover a worker crash without repeating learning.
The curator takes a scope-only snapshot before running; five snapshots are retained.

Skills are read through MCP and the hook index. Native hot discovery of generated skills is not required or claimed.
Built-in Codex memories, third-party skills, AGENTS.md, and application source are untouched.
Pins block archiving; unpin explicitly before merging a pinned source.
Archive is recoverable. Restore checks the current hash and adds history.
No hard deletion or automatic garbage collection is performed; storage can grow.

Auto retirement is off. Its opt-in compatibility policy uses 100 project replies / 300 global replies
for maturity and 50 / 20 mature used skills for capacity. Pins and explicit helpfulness protect knowledge.
Invocation frequency is not a quality score.

Uninstall with codex plugin remove autoharness-codex@autoharness-codex-local.
Owned data remains available for recovery. Read [SECURITY.md](SECURITY.md) for boundaries and limitations.

## Verification

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python -m compileall -q src scripts
```

CI runs tests on Windows and Ubuntu with Python 3.11, 3.12, and 3.13.
Tests use temporary data and mocked model calls. Local checks additionally exercised actual Codex
reflection, actual consolidation, recall, restore, native installation, and MCP startup.
Review [CHANGELOG.md](CHANGELOG.md).

The primary branch is master. Process files, transcripts, credentials, databases, and ZIPs stay outside the repo.
