# Shared contract

Read and apply this contract and the [role-and-assignment contract](role-and-assignment.md) before doing substantive work with any Ora Vibe Coder framework. That document is the sole role catalogue and assignment definition; the selected canonical framework supplies its method, output, and stopping point. For direct Markdown use, supply this complete text, the complete role source, and the selected framework; inaccessible links are insufficient. Native skills load these same sources.

## Assign responsibility before work

- At entry, identify the receiving session's role, method, assignment owner, and return destination.
- Use the stage's entry assignment below and the role contract's six-part brief, including the project-specific completion endpoint.
- Load common rules and the assigned role; coordinators and team designers read the complete catalogue.
- Stage names and app document categories are not agent roles.

Dispatch and messaging:

- Use the receiving host's existing dispatch and messaging when authorized and available.
- Supply in the actual dispatch request: accessible governing sources or identified source copies; the selected skill; the complete assignment; current accepted inputs; dependencies; limits; and the direct return owner.
- Confirm the available capability before invoking it.
- A packet describing a team is not an assignment until delivered to a receiving session.
- Unavailable dispatch requires a disclosed complete manual handoff, never an invented runner.
- When Codex's collaboration tools are available, create the worker with `collaboration.spawn_agent`, `fork_turns: "none"`, and that complete brief in `message`; use `send_message` for direct updates/handback and `followup_task` to resume a waiting worker with current instructions; read its actual returned result. On another host, use its documented equivalent or manual delivery. These are host operations, never app runtime or permanent model bindings.

Refresh and scope:

- Apply the role contract's startup, compaction, resumption, changed-assignment, and changed-input refresh rules.
- Identify the governing accepted documents and package revision.
- Return precise gaps to the owner and continue independent authorized work.
- Small work may use an existing self-contained loop without an extra coordinator or dedicated secretary; name the document custodian either way.
- A staffed coordinator keeps the catalogue's role boundaries throughout the lifecycle.

## Build only what matters

For every question, suggestion, artifact, check, and process element, ask:

> If this did not exist, which required behavior, truth guarantee, safety property, or recovery capability would become impossible?

- Omit anything justified only by tracking, possible future use, architectural elegance, optional polish, or reviewer convenience. Prevent both under-specification (the AI silently chooses part of the product) and over-construction (it adds machinery or scope that does not advance the user's goal or prevent a material failure).
- Before proposing a discretionary addition, restriction, extra or repeated check, broad suite, or build, the proposer must supply all four:
  1. the specific approved requirement;
  2. verifiable evidence it fails or cannot be met without the addition;
  3. why the existing simpler approach cannot meet it; and
  4. the necessary authority.

  Otherwise reject the proposal. Apply this rule to planning and reviewer demands too.
- “Material risk,” hypothetical catastrophe, rarity, “hardening,” safety, quality, and future usefulness do not substitute for that proof. Do not propose optional hardening to the user.
- A justified restriction must identify: its smallest reversible change; affected paths; user friction; compatibility and maintenance cost; extra testing; new failure modes; and removal path.
- Optional enrichment paths fail open with loud reporting; existing security, authentication, authority, publication, and data-integrity controls retain their required failure behavior.

A finding is actionable only with evidence of a result contrary to the Specification (or the approved Plan, for implementation work) in a way that changes the result the user asked for, or a real error with identified harm. Every finding states: input or situation; actual result; expected result; evidence (command output or a traced code path); who is harmed and how; size of the smallest fix.

Severe failures are unrecoverable data loss, security exposure, and unauthorized or erroneous spending, sending or publishing. Identify every severe finding; for these a traced path from an actual permitted input to the harm is sufficient — do not cause the harm to prove it. A severe finding settles only through a recorded fix with evidence that its harmful path was removed; a rejection does not stand.

Not actionable, so record it and move on: "could", "might" or "in theory" with no demonstrated case; rare conditions with unimportant results; errors nobody would notice and nothing depends on; fixes bigger than the harm, except on severe failures; hardening or style with no proven harm.

## Reviewer rule and dispositions

This one rule governs every review, verification and correction in this lifecycle. The frameworks refer to it; none restates a different threshold.

**Reviewer's job.** Examine widely. Record potential issues and why they do or do not warrant a change, including close calls. Good work means finding real errors and explaining why other issues don't justify code or a test. "No findings" is full success.

**Builder.** Fix actionable findings the smallest way. You may reject a finding as unnecessary, recording your reasons; a rejection stands, except on severe failures. A finding does not expand authority or require a test.

When a reviewer disagrees with a decision, it gives its reasoning and, if one is available, a reasonable alternative. The alternative must not add bloat or unnecessary tests, and must not contradict the Specification or the user's stated goal. The builder adopts it or rejects it with reasons; a rejection stands, except on severe failures.

**Tests.** Simple checks that something happened or didn't are fine. Do not add elaborate tests for rare, unimportant outcomes. A finding alone does not justify a test. Judge a test's whole addition, setup included.

**Final verification and correction.** Verification checks the record as a third reader and may recommend reversing any decision, with reasons. Final correction fixes or rejects each recommendation with reasons. Rejected non-severe findings do not force another review or prevent completion. Unresolved severe findings go to the owner.

**Delete pass.** Before landing, one fresh reviewer's only job is to recommend what can be removed while still meeting the stated user function. The builder applies each one or rejects it with reasons. Whichever method performs the programming commissions this pass exactly once, at the programming handoff — the Programming Loop's own route when it programs, otherwise the implementing host before Git landing; Vibe adds no second delete-pass engine.

**Spec and Plan reviews.** A finding against a Specification or Plan must show a user harm or a contradiction with the owner's decision. Do not invent requirements; recommend removing unnecessary ones or correcting contradictions with the owner's decisions. Ordinary disagreements are settled by the recorded builder dispositions — they are not routed to the user as tie-breaking requests.

**Record.** Findings, rejections, pushback and reversals are retained as ordinary project files committed to Git, with the supplied instructions and conversations. Add no separate persistence system. Include no credentials or secrets. They are not sent to the owner.

**Dispositions.** Every completed review report and correction result the automatic run produces also records its routing decision in the same opening YAML:

```text
disposition: SETTLED
```

- `SETTLED` — review finished; every finding was fixed or rejected with reasons; no unresolved severe finding remains. Continue toward delivery.
- `CORRECTION` — review finished and findings require builder decisions. Run correction.
- `SEVERE` — a demonstrated severe finding remains unresolved. Preserve the candidate and return the necessary decision to the owner. Never complete.
- `INCOMPLETE` — review or correction did not finish. Preserve its work; use the existing operational recovery route.
- `ASK USER` — missing authority or an unresolved product choice requires the owner. Preserve this route.

The reader takes the `disposition:` field of the **current completed report's** opening YAML, decided after the work is finished. Missing, duplicate, unknown or off-list values mean `INCOMPLETE` — never settled. "No severe finding stated" means an affirmative, completed `SETTLED` or `CORRECTION` value, whose instructions expressly require identifying every severe finding; it never means an absent severity value. Completion after final correction says **completed after correction**, without inventing a subsequent verification pass.

## Understand before asking

Read all supplied material and use available inspection before asking the user anything. State in plain language:

- the current understanding of the user's goal;
- useful inferences from the evidence;
- consequential assumptions;
- the exact insufficiency, if one remains;
- the recommendation and its reason; and
- the live alternatives when a real choice remains.

Asking:

- Ask only for a user-owned decision or fact that inspection, safe inference, or reversible professional judgment cannot responsibly supply. Ask one decision at a time.
- Before asking, show: what is being decided; why it matters; what each live option does; its concrete cost or risk; whether it is reversible; and the recommended option.
- Match technical depth to the user's interest while keeping every consequential choice visible.

User material:

- Preserve the user's terminology, values, boundaries, corrections, and intentionally unresolved ambiguity.
- A later direct correction controls over an earlier statement; show a real conflict rather than silently combining versions.
- Tie every proposed requirement or implementation option to the user’s goal; discretionary additions must also satisfy the proof rule above.
- Recommend the simpler route when it fulfills the same result.

## Establish reference meaning

- Specification records each approved reference as **literal** (binding source and observable result), **adaptive** (only named aspects may change), or **conceptual** (an idea, not a binding implementation). Planning and Programming apply that classification without reclassifying; resolve consequential uncertainty through Specification before dependent planning.
- For a literal executable reference, use its source as the starting implementation; every observable object, state, interaction, and behavior is binding. A similar rewrite is insufficient. Before coding, Planning maps that source to required behavior in the existing Plan. Report a material incompatibility or proposed deviation before rewriting.

## Keep WHAT and HOW with their owners

- Specification owns: what is being built; who it serves; required behavior and outputs; content and data treatment; product boundaries; essential failure behavior; consequential permissions; and observable success.
- Planning owns how the approved product will be implemented in the inspected project.
- A method belongs in Specification only when the user made it part of the required outcome or it is a genuine product constraint.
- Route missing or incorrect WHAT to an executor using Specification; route inadequate HOW to an executor using Planning.
- Use the role contract's correction route: delegated detail can receive review and acceptance within existing authority; changing a goal, hard constraint, reserved decision, or authorized effect requires the user's decision.
- Never disguise either as an ordinary implementation choice; never treat consultation alone as an accepted amendment.

## Treat readiness as advice, not hidden authority

- Evaluate inputs by substance, not filename, template, creator, harness, prior status, or Ora history.
- When upstream material is weak, name exactly what is missing, the concrete likely consequence, and the earliest useful stage.
- The user may explicitly continue on that reduced quality basis. Record the reduced basis in the conversation and relevant current artifact; create no waiver, receipt, gate record, or special state.
- A quality override never bypasses Programming's own scope approval and never grants: editing; installation; authentication; credentials; disclosure; destructive or irreversible work; publication; deployment; purchases; messaging; broader scope; or any other consequential effect.
- An artifact label, Gear result, reviewer result, or stage approval grants no such authority either.
- If a required companion is missing or materially out of date: state the exact install-or-enable need and stop that companion-dependent work; do not imitate it. A complete handoff to a recipient where that companion is available may still be prepared, without claiming execution or review occurred.

## Keep artifacts truthful and together

- Use the directory the user explicitly supplies; otherwise use the current working directory.
- Resolve it to an absolute path; do not create a project folder implicitly for the Markdown artifacts.
- The optional app may create a project directory only through the user's explicit New Project action; that does not change direct Markdown use.
- Infer the project name from supplied material where that is safe.

The standard working documents are:

1. `<Project Name>/Registry.md` — notes, background, decisions, and open questions
2. `<Project Name>/Specification.md` — intended behavior, requirements, and outcomes
3. `<Project Name>/Plan.md` — implementation approach, steps, and checks
4. `Programming Result` — saved after actual programming work, including work that stops unfinished
5. `Verification Report` — saved after actual verification, for passing, failing, and incomplete reviews alike

- These documents are working aids; their presence or completion is never a prerequisite for using a stage.
- Older documents under names such as `<Project Name> — 01 Request.md` through `<Project Name> — 07 Report.md` remain recognized where they exist; they need no migration or cleanup.
- Product code stays in its real project structure.
- Produce additional documentation only when the project calls for it, and maintain existing documentation affected by changes.
- Before writing: show the resolved directory and intended create-or-update paths, and obtain the approval required by the active harness.
- Check colliding default filenames.
- For a clear continuation, revise the current artifact in place so it remains one complete source of truth.
- For a new-project collision, ask for another project name or directory.
- Never silently overwrite; never invent a timestamp, ID, suffix, version folder, archive, registry, or retention system.

Keeping the current documents useful:

- Update the Registry when the user supplies or corrects a material goal, requirement, boundary, fact, authority, or decision during an interactive stage.
- Organize decisions by subject and preserve enough surrounding meaning to understand the instruction; never turn a document into a chronological transcript of every turn, analysis, Gear exchange, rejected draft, implementation action, test event, or status poll.
- Update the current Specification or Plan too when the correction changes its controlling meaning; keep each as one current synthesis, not an amendment log.

Authorship and custody:

- Name the substantive author, acceptance owner, and document custodian in the existing assignment or current project documents.
- The secretary, when assigned, handles custody under the role contract.
- Record consequential accepted decisions and unresolved material findings as they arise in the relevant existing documents; routine discussion stays out.
- When substantive documentation is missing or wrong, assign its creation or correction to an executor with the appropriate skill.

Amendments:

- Keep proposed amendments distinct from governing text until the author, required independent review, and applicable approval are established.
- Initial Specification and Plan approval remain user decisions, recorded by Approve or the deliberate next-stage request under the reported-field rules below; no passing review is a prerequisite.
- The owner may accept a reviewed amendment within discretion already delegated by the user; changes beyond it return the actual conflict and recommendation to the user.
- The custodian incorporates accepted meaning into the current synthesis and notifies the coordinator and affected workers.
- The coordinator and affected workers refresh their governing inputs before affected work resumes; unaffected authorized work continues.
- Never settle a disagreement through a silent rewrite; never import a consultant's whole discussion.

Managed project files:

- Managed projects may also have a small `Project.md` overview and one current `Handoff.md`; these are associations and an outgoing snapshot, not competing requirement authorities.
- Use explicitly designated current files rather than guessing from filenames, dates, or modification times; adequate existing files need not be renamed.
- Disclose a missing, unreadable, or ambiguous association with a file-selection remedy; never treat it as an empty successful result.
- Direct framework use requires neither app file, its naming, nor Ora history.

Temporary material:

- Temporary unless the user requests an extra: Bridge sessions, Gear working records, reviewer prompts, disposable projects, and atomic staging files.
- Keep task-owned temporary material only while correction, resumption, or rollback needs it; then remove it without deleting user files, another task's work, or companion qualification records.
- If work stops unfinished, retain what is genuinely needed to resume.

## Give clean, complete handoffs

### Keep portable methods and host operations separate

- A portable method states the outcome, roles, evidence, authority, and failure rules that remain true everywhere.
- A host adapter states only how the initiating host creates a fresh worker, limits tools, retrieves the complete result, and waits safely.
- Do not copy the method into adapters or native skill entries; use one canonical framework and thin loaders so corrections have one owner.
- Choose an adapter from the host receiving and coordinating the assignment — never from a reviewer model's vendor, an optional provider, the source of a cited document, or a Bridge target.
- An optional external reviewer remains a bounded recipient of the review packet.
- The initiating host continues to own dispatch, evidence collection, correction, and delivery.

Distribution truth:

- Package identity and live capability are separate facts.
- Exact files, valid links, source hashes, installation destinations, transactional recovery, and fake host fixtures can establish distribution integrity without contacting a model.
- That evidence cannot establish: live login, account access, provider selection, model identity, permission behavior, or end-to-end qualification.
- State the strongest fact the evidence proves and no stronger.
- When a live route reports model or provider attribution, preserve the exact returned attribution beside the requested selector. Never infer an effective model from an alias, command option, launch acknowledgement, or intended route. Missing, ambiguous, multiple, or mismatched attribution leaves that identity unverified. This truth rule authorizes no call, credential use, or paid fallback.
- Generated copies report, rather than create, truth: retain the canonical source identity and exact file hashes; generate through the one approved assembler; never repair a mirror by hand. If the source and mirror differ, correct the canonical input or generator and regenerate. A hash match proves byte parity, not semantic quality or runtime success.
- Native delivery is a convenience. A visible, complete manual Markdown handoff remains the portable baseline when a native operation is absent, inaccessible, or unsuitable. Disclose which context or artifact the manual recipient cannot access; preparing or copying it still does not prove receipt or execution.

Reviewer profiles and independence:

- A selected reviewer profile is a useful default, not a security boundary or proof of independence.
- The coordinator must: inspect the host's effective tool and permission behavior; state the review-only authority in the assignment; and inspect the resulting repository state.
- A profile that omits ordinary authoring tools may still expose a shell capable of changes; a parent automatic mode may broaden a child; a remote worker may lack the local candidate entirely. Preserve those facts instead of claiming that the filename or declared allowlist enforced them.
- Independence requires a fresh context separate from the executor plus direct access to the plan, cumulative candidate, and authorized evidence.
- When any of those facts cannot be established, return the exact unverified limitation and the smallest usable manual or local alternative.
- Never weaken the review contract, silently reuse the executor, or add a provider call to manufacture diversity.
- When a supported host changes its native operation, update only the owning adapter, installer mapping, focused distribution expectation, and truthful public compatibility note; the universal method and other host adapters remain unchanged unless the underlying cross-host requirement truly changed.

Assemble a complete Markdown body for each fresh stage, Gear, Bridge, independent-reviewer, or Programming recipient. Never assume earlier messages enter a fresh context. Use the smallest complete basis:

| Destination | Include | Exclude |
|---|---|---|
| Specification | User idea, current Request, existing requirements, relevant corrections | Planning or code choices not required by the outcome |
| Planning | Current Request, approved Specification, project path, applicable instructions, inspected facts | Rejected designs, review transcripts, unrelated history |
| Programming | Approved Specification and Plan when available; otherwise current requirements, exact gaps and assumptions; project path and protected state | Raw Request history, planning discussion, Gear deliberation |
| Verification | Accessible candidate and available requirements; Plan, Programming Result, documentation, credible checks, baseline or diff when they exist | Raw Request history, implementation transcript, prior claims offered as proof |
| Correction | Consolidated current material findings, controlling artifacts, actual candidate, and evidence needed by the owning stage | Superseded findings and unrelated review commentary |

- Give every executor and reviewer the exact current governing instructions, Specification, Plan, approved references, retained decisions, acceptance criteria, baseline, permitted effects, and test ceiling applicable to the assignment. Preserve explicitly approved omissions.
- Before dependent work, require the receiver to open each required item and report any access failure to its owner. Bridge requests must be self-contained and grant the required reading access.

Prepare the visible packet in this order:

1. **User request:** place the user's exact input first, clearly labeled and preserved without paraphrase. Mark a clear boundary before framework instructions.
2. **Framework instructions:** identify the selected stage and canonical package version or revision; include this complete shared contract, the complete role-and-assignment source exactly once, and complete selected framework text. Identify the role source separately from the packaged frameworks and shared contract. Guided packets also include all four stage bodies for use at their relevant stage, not automatic execution.
3. **Project and authority:** identify the actual project and candidate locations, selected destination, applicable supplied instructions, factual protected state, authority limits, output paths, exact authorized checks, completion endpoint, and retained approvals. Include the assigned role, skill, owner, return destination, dependencies, resource limits, and delegated discretion under the role contract. State what has and has not been authorized; request preparation grants no authority to execute.
4. **Current material:** supply only the destination-appropriate content in the table, with each item's role, source, and access limitation. Label quoted project data separately from instructions. The recipient must apply its own instruction hierarchy, permissions, and companion checks.
5. **Gaps and next result:** identify every known missing input, consequential unresolved assumption, reduced basis, required companion, and the next bounded assignment and inspectable handback expected by its owner. Preserve the governing completion conditions downstream. Do not imply omitted material was supplied.

Packet access:

- A local path is usable only when the recipient can actually access it.
- Disclose local paths unavailable remotely, and unreadable, oversized, binary, remote, or user-designated sensitive material.
- Supply honest references and access limits instead of unsuitable attachments; retain all useful permitted context.
- During packet preparation, never silently truncate, upload, fetch remote content, scan for secrets, discover unselected harnesses, or transform the user's text into shell commands.
- A reading-size ceiling is not a promise that a model can accept the packet's entire context.
- Missing optional material must not block a useful reduced-basis handoff.

Outgoing snapshot:

- Build one current outgoing snapshot from the exact input and designated sources; never append or include an earlier outgoing packet, even when it was accidentally associated with another document role.
- Preserve source documents.
- Before writing, confirm the outgoing destination is selected and does not collide with a source or overview, including aliases and symbolic links; existing outgoing content requires explicit selection before replacement.
- Use a temporary sibling and atomic replacement. On failure: retain the user's input and prior saved handoff; remove only operation-owned staging; do not report success.
- Never invent archives, suffixes, renames, or deletion as a fallback.

Delivery baseline:

- Copy-and-paste is the fully supported delivery baseline: show what to open, what complete raw Markdown to paste, and the expected next result.
- Native entries are a convenience only when available.
- Preparing, saving, displaying, or copying is not sending, beginning execution, completing review, or approving a stage; a process or window opening does not prove delivery.
- While preparing a packet, never install, authenticate, select a hidden fallback target, or initiate a model call.

App display agreement:

- The app's displayed prepared source, saved handoff, and copied Markdown must agree, including content below the visible pane.
- Before copying, compare the prepared snapshot with the saved file; if changed, show the current content and require another Copy action rather than copying unseen changes.
- A failed save or copy preserves input and the previous recoverable packet and is not success.
- Later source changes need Prepare Again, not silent incorporation.
- Work continues in the chosen harness and saves real artifacts; the app rereads them without importing chats, monitoring agents, or treating process exit as completion.

## Reported fields in ordinary Markdown

Use a small opening YAML block for new current documents. A standalone Specification or Plan needs only `status` and `review`; a Programming Result or Verification Report needs only `status`. Preserve pre-existing vault metadata such as nexus, type and tags. Never add fingerprints, serialized audit records, approval ledgers or duplicate finding counts to the YAML.

| Document | Workflow `status` | Assessment `review` |
|---|---|---|
| Specification and Plan | `DRAFT`, `IN PROGRESS`, `AWAITING APPROVAL`, `APPROVED` | Blank when unreviewed; otherwise `PASSED`, `NOT PASSED`, `INCOMPLETE`, or `CHANGED` |
| Programming Result and Verification Report | `PASSED`, `NOT PASSED`, `INCOMPLETE`, or `CLOSED BY USER — UNRESOLVED FINDINGS` | No separate review field |

The assessment/result verdicts have one meaning across stages:

- `PASSED`: the assigned scope was successfully completed and no required deficiency remains unresolved. Programming describes the execution and approved delivery endpoint; Verification describes an independent inspection. Neither substitutes for the other.
- `NOT PASSED`: a completed assessment found required deficiencies. Keep their substantive explanation and recommended corrections in the document.
- `INCOMPLETE`: the work or assessment cannot reach a supported conclusion because evidence, a tool, an essential decision, or required work is missing. Explain exactly what remains and who can resolve it.
- `CLOSED BY USER — UNRESOLVED FINDINGS`: the user explicitly closed the work with unresolved material findings; never complete, verified or successful.

The verdict is the YAML field alone, matched exactly against the lists above, decided after the work is finished. Show PASSED in green, NOT PASSED in red, and INCOMPLETE in amber. A saved verdict describes only its actual scope and inspected delivery; an older passing result does not establish that later work passed. Keep the full assessment and findings under one `## Current review` in a Specification or Plan; it explains the YAML review value. Do not replace the explanation with metadata or counts.

Approval is the user's decision and is independent of every review state. Pressing Approve, or deliberately requesting the next stage, approves the actual upstream document supplied: Create Plan approves the Specification, and Implement Plan approves the Plan. This holds when the review is absent, NOT PASSED, INCOMPLETE or CHANGED. Record `status: APPROVED` directly in the supplied document; no extra user note or AI inference is needed. Approval does not turn a review into PASSED. Opening a disclosure, selecting a workspace, previewing a request or refreshing files is not approval. The app records approval before dispatch; a later dispatch failure does not undo that real decision. In standalone conversations, an explicit request to create the Plan or implement it is the same approval; preserve the supplied version and report any unavailable write honestly.

Approval binds the substantive version accepted. If requirements, scope, acceptance conditions, implementation approach, checks or delivery change materially, an approved Specification or Plan returns to `status: AWAITING APPROVAL`. If it had a review, set `review: CHANGED` and show it in amber: the actual earlier assessment and findings remain visible in Current review and apply to the earlier version. CHANGED is an applicability state, not a fourth assessment verdict. A new next-stage request approves the current supplied version while leaving CHANGED intact. An unreviewed edited document stays unreviewed. A material Specification change warns that the Plan may need updating; it does not declare the Plan failed.

Recording status, review, dates, Markdown layout and meaning-preserving typo corrections do not withdraw approval or stale a review. Compare actual prior content; changed bytes or a hash mismatch alone cannot establish materiality. Preserve code casing, link destinations and all meaningful obligations. Use retained version snapshots and the existing read-only semantic comparison where needed. If the earlier version is unavailable, or the comparison is pending or fails, say that applicability is unconfirmed; do not invent a change or claim equivalence. Keep all stages available. When editing a document yourself, apply these material-change rules as part of the revision and preserve the actual prior assessment.

Reading existing documents:

- The verdict is the opening YAML field alone, matched exactly. The report body never decides, changes or contradicts a verdict: no reading of history, examples, quoted instructions, code or prose overrides the YAML value, and a contradiction in the prose changes nothing.
- A Specification or Plan with no `status` shows no status, neutrally; with a blank or missing `review` it shows NOT REVIEWED. A substantive result or report with no `status` shows VERDICT MISSING in amber. A malformed, duplicate or off-list value shows REPORT ERROR naming the value.
- Untouched empty templates show NOT STARTED neutrally. No Programming Result shows NO RESULT; no Verification Report shows NOT VERIFIED. An unreadable file shows COULD NOT READ and its actual reason. `status: INCOMPLETE` (and `review: INCOMPLETE`) shows REVIEW INCOMPLETE.
- Do not silently migrate or rewrite existing projects just to adopt the new fields. Optional Programming and Verification fields in Project.md remain overview history and never override the current saved result/report.

Overview field updates:

- Under normal write authority, Programming may update its own named overview result field.
- Reread `Project.md` immediately before the minimal update and preserve its other result, description, goals, associations, and all unowned text.
- Do not overwrite changes observed since reading; simultaneous app/harness overview writes are unsupported.
- This grants no permission to correct the candidate, Specification, Plan, or documentation during Verification.
- If the brief is absent or writing is unavailable or unauthorized: report the result in conversation and leave the UI status unreported without blocking permitted work.

Verification Report:

- Save or update one current report after actual verification — passing, failing, or incomplete alike.
- An earlier saved verdict is retained as history and never treated as current-pass evidence for newer code.
- Stopping is not successful completion.
- No status file, consent record, database, hash history, or certification service is required.

## Keep status and stopping truthful

- Carry completion from Specification through the Plan and every assignment using the role contract's delivery rules.
- Distinguish a completed review or draft assignment from the larger project's endpoint. The final project verdict covers the whole delivery; a worker or stage result covers only its own assignment.
- Assign remaining authorized delivery and cleanup to responsible workers; obtain evidence of the output in its intended location and condition.
- A changed delivered product needs applicable verification of the material difference.
- A local passing result, saved report, or worker handback alone cannot close the project.

Use established status meanings without treating status as user approval or authority. The recognized result and report statuses are exactly `PASSED`, `NOT PASSED`, `INCOMPLETE` and `CLOSED BY USER — UNRESOLVED FINDINGS`; the run's routing values are the `disposition` list above. A settled correction completes the work as completed after correction without a further verification pass. A transport failure is not reviewer disagreement. A fallback is not a completed Gear 4 run. A severe-unresolved disposition never reports success.

- Silence causes no calls, no cleanup beyond already authorized work, no status change, no manufactured report, and no manufactured closure.
- On resumption, inspect the actual retained artifacts, candidate, findings, check output, and Git state; never infer a pass from a file or old label.
- If the user explicitly abandons work with unresolved material findings, the only closure label is `CLOSED BY USER — UNRESOLVED FINDINGS`; record the abandonment truthfully in the Verification Report and do not call the work complete, verified, passed, ready, or successful.
