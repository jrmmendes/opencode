---
description: Run a thorough, source-heavy investigation on a topic and produce a durable research brief with inline citations.
agent: feynman
---
Run deep research for: $ARGUMENTS

## Required Artifacts

Derive a short slug from the topic: lowercase, hyphenated, no filler words, at most 5 words.

Every run must leave these files on disk:
- `<slug>/outputs/.plans/<slug>.md`
- `<slug>/outputs/.drafts/<slug>-draft.md`
- `<slug>/outputs/.drafts/<slug>-cited.md`
- `<slug>/outputs/<slug>.md` or `<slug>/papers/<slug>.md`
- `<slug>/outputs/<slug>.provenance.md` or `<slug>/papers/<slug>.provenance.md`

Do not create placeholder drafts, final outputs, or provenance files before their stage. If any capability fails, continue in degraded mode and still write a blocked or partial final output and provenance sidecar. Never end with chat-only output or with only an explanation in chat. Use `Verification: BLOCKED` when verification could not be completed.

## Step 1: Plan

Create `<slug>/outputs/.plans/<slug>.md` immediately. The plan must include:
- Key questions
- Evidence needed
- Scale decision
- Task ledger
- Verification log
- Decision log

Make the scale decision before assigning owners in the plan. If the topic is a narrow "what is X" explainer, the plan must use lead-owned direct search tasks only; do not allocate researcher subagents in the task ledger.

After writing the plan, summarize it in a few lines and continue immediately in the same turn with the next tool call; never end a turn with a message that only announces what you will do next. Stop for confirmation only when the user explicitly asked to review the plan first; then ask `Proceed with this deep research plan? Reply "yes" to continue, or tell me what to change.`, and if they request changes, update `<slug>/outputs/.plans/<slug>.md` before asking again.

## Step 2: Scale

Use direct search for:
- Single fact or narrow question, including "what is X" explainers
- Work you can answer with 3-10 tool calls

For "what is X" explainer topics, you MUST NOT spawn researcher subagents unless the user explicitly asks for comprehensive coverage, current landscape, benchmarks, or production deployment.
Do not inflate a simple explainer into a multi-agent survey.

Use subagents only when decomposition clearly helps:
- Direct comparison of 2-3 items: 2 `researcher` subagents
- Broad survey or multi-faceted topic: 3-4 `researcher` subagents
- Complex multi-domain research: 4-6 `researcher` subagents

## Step 3: Gather Evidence

Prefer abstracts, HTML pages, official docs, and paper metadata. Read full text only for the few papers the conclusions depend on.

If direct search was chosen:
- Skip researcher spawning entirely.
- Search and fetch sources yourself.
- Use multiple search terms/angles before drafting. Minimum: 3 distinct queries for direct-mode research, covering definition/history, mechanism/formula, and current usage/comparison when relevant.
- Record the exact search terms used in `<slug>/outputs/.drafts/<slug>-research-direct.md`.
- Write notes to `<slug>/outputs/.drafts/<slug>-research-direct.md`.
- Continue to synthesis.

If subagents were chosen:
- Write a per-researcher brief first, such as `<slug>/outputs/.plans/<slug>-T1.md`.
- Dispatch one `subagent` call per researcher (agent `researcher`), with the brief path and the exact output path (`<slug>/outputs/.drafts/<slug>-research-<key>.md`) inside the prompt. Issue independent calls in the same block to run them in parallel; for long runs use `background: true`.
- The `subagent` tool takes `agent`, `description`, `prompt`, and optionally `background`/`model`; there is no JSON metadata, no `output` key and no workflow script.
- Read each child's returned result and verify every declared artifact exists on disk. Do not assume a file exists because a child says it wrote it.
- Prefer broad guidance such as "use paper search and web search"; if a PDF parser or paper fetch fails, the researcher must continue from metadata, abstracts, and web sources and mark PDF parsing as blocked.

Continue independent work while background children run, then collect every result before synthesis. Each child writes the path you gave it; verify each file on disk and treat a missing file as a failed task, not as a launch receipt. After evidence gathering, update the plan ledger and verification log. If research failed, record exactly what failed and proceed with a blocked or partial draft.

## Step 4: Draft

Write the report yourself. Do not delegate synthesis.

Save to `<slug>/outputs/.drafts/<slug>-draft.md`.

Include:
- Executive summary
- Findings organized by question/theme
- Evidence-backed caveats and disagreements
- Open questions
- No invented sources, results, figures, benchmarks, images, charts, or tables

Before citation, sweep the draft:
- Every critical claim, number, figure, table, or benchmark must map to a source URL, research note, raw artifact path, or command/script output.
- Remove or downgrade unsupported claims.
- Mark inferences as inferences.

## Step 5: Cite

If direct search/no researcher subagents was chosen:
- Do citation yourself.
- Verify reachable HTML/doc URLs with available fetch/search tools.
- Copy or rewrite `<slug>/outputs/.drafts/<slug>-draft.md` to `<slug>/outputs/.drafts/<slug>-cited.md` with inline citations and a Sources section.
- Do not spawn the `verifier` subagent for simple direct-search runs.

If researcher subagents were used, run the `verifier` agent after the draft exists. This step is mandatory and must complete before any reviewer runs. Do not run the `verifier` and `reviewer` in the same parallel `subagent` call.

Use this call shape:

`subagent({ agent: "verifier", description: "Cite draft", prompt: "Add inline citations to <slug>/outputs/.drafts/<slug>-draft.md using the research files as source material. Verify every URL. Write the complete cited brief to <slug>/outputs/.drafts/<slug>-cited.md." })`

Wait for the verifier's result before review; a background launch is not a result. Verify on disk that `<slug>/outputs/.drafts/<slug>-cited.md` exists. If it is missing, use the returned output reference to find the cited file and copy it there.

## Step 6: Review

If direct search/no researcher subagents was chosen:
- Review the cited draft yourself.
- Write `<slug>/outputs/.drafts/<slug>-verification.md` with FATAL / MAJOR / MINOR findings and the checks performed.
- Fix FATAL issues before delivery.
- Do not spawn the `reviewer` subagent for simple direct-search runs.

If researcher subagents were used, only after `<slug>/outputs/.drafts/<slug>-cited.md` exists, run the `reviewer` agent against it.

Use this call shape:

`subagent({ agent: "reviewer", description: "Verify cited draft", prompt: "Verify <slug>/outputs/.drafts/<slug>-cited.md. Flag unsupported claims, logical gaps, single-source critical claims, and overstated confidence. This is a verification pass, not a peer review. Write findings to <slug>/outputs/.drafts/<slug>-verification.md." })`

Read the reviewer's returned result and the verification file before proceeding. If the reviewer flags FATAL issues, fix them before delivery and run one more review pass. Note MAJOR issues in Open Questions. Accept MINOR issues.

When applying reviewer fixes, do not issue one giant `edit` tool call with many replacements. Use small localized edits only for 1-3 simple corrections. For section rewrites, table rewrites, or more than 3 substantive fixes, read the cited draft and write a corrected full file to `<slug>/outputs/.drafts/<slug>-revised.md` instead.

The final candidate is `<slug>/outputs/.drafts/<slug>-revised.md` if it exists; otherwise it is `<slug>/outputs/.drafts/<slug>-cited.md`.

## Step 7: Deliver

Copy the final candidate to:
- `<slug>/papers/<slug>.md` for paper-style drafts
- `<slug>/outputs/<slug>.md` for everything else

Write provenance next to it as `<slug>.provenance.md`:

```markdown
# Provenance: [topic]

- **Date:** [date]
- **Rounds:** [number of research rounds]
- **Sources consulted:** [count and/or list]
- **Sources accepted:** [count and/or list]
- **Sources rejected:** [dead, unverifiable, or removed]
- **Verification:** [PASS / PASS WITH NOTES / BLOCKED]
- **Plan:** <slug>/outputs/.plans/<slug>.md
- **Research files:** [files used]
```

Before responding, verify on disk that all required artifacts exist. If verification could not be completed, set `Verification: BLOCKED` or `PASS WITH NOTES` and list the missing checks.

Final response should be brief: link the final file, provenance file, and any blocked checks.
