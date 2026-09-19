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

A **material** issue causes or is highly likely to cause any of: a wrong user-visible result; lost content or data; a false claim or misattribution; a real runtime or deployment failure; unauthorized scope or effects; a broken atomic operation; a failed necessary recovery; a security exposure; or failure to fulfill the user's stated goal. Style preferences and speculative improvements are not material.

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

The default retained filenames are:

1. `<Project Name> — 01 Request.md`
2. `<Project Name> — 02 Specification.md`
3. `<Project Name> — 03 Implementation Plan.md`
4. `<Project Name> — 04 User Guide.md`
5. `<Project Name> — 05 Technical Documentation.md`
6. `<Project Name> — 06 Product Overview.md`
7. `<Project Name> — 07 Report.md`

- Product code stays in its real project structure.
- Before writing: show the resolved directory and intended create-or-update paths, and obtain the approval required by the active harness.
- Check colliding default filenames.
- For a clear continuation, revise the current artifact in place so it remains one complete source of truth.
- For a new-project collision, ask for another project name or directory.
- Never silently overwrite; never invent a timestamp, ID, suffix, version folder, archive, registry, or retention system.

Keeping the Request current:

- Update the Request when the user supplies or corrects a material goal, requirement, boundary, fact, authority, or approval during an interactive stage.
- Organize decisions by subject and preserve enough surrounding meaning to understand the instruction; never turn the Request into a chronological transcript of every turn, analysis, Gear exchange, rejected draft, implementation action, test event, or status poll.
- Update the current Specification or Plan too when the correction changes its controlling meaning; keep each as one current synthesis, not an amendment log.

Authorship and custody:

- Name the substantive author, acceptance owner, and document custodian in the existing assignment or current project documents.
- The secretary, when assigned, handles custody under the role contract.
- Record consequential accepted decisions and unresolved material findings as they arise in the relevant existing documents; routine discussion stays out.
- When substantive documentation is missing or wrong, assign its creation or correction to an executor with the appropriate skill.

Amendments:

- Keep proposed amendments distinct from governing text until the author, required independent review, and applicable approval are established.
- Initial Specification and Plan approval remain explicit user decisions.
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
| Verification | Accessible candidate and specification material; Plan, documentation, credible checks, baseline or diff when they exist; every guided-path product | Raw Request history, implementation transcript, prior claims offered as proof |
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

- Status labels report separate facts; they are not independent validation or current-revision certification.
- For managed projects use one field in the opening metadata block, before body sections, for each displayed stage.
- Do not search body prose, quotations, examples, or code for a success word.
- Plain `Status: APPROVED` and decorated `**Status:** APPROVED` are equivalent labels; normalize line endings, trailing spaces, and Markdown hard breaks — never the meaning of a value.

| Stage | Sole display source | Exact recognized values |
|---|---|---|
| Specification | `Status` in the designated Specification | `DRAFT`, `IN PROGRESS`, `AWAITING APPROVAL`, `APPROVED`; legacy `Approved product specification` means reported approval |
| Planning | `Status` in the designated Plan | `DRAFT`, `IN PROGRESS`, `AWAITING APPROVAL`, `APPROVED`; legacy `Approved Implementation Plan` means reported approval |
| Programming | `Programming` in `Project.md` | `NOT STARTED`, `IN PROGRESS`, `COMPLETE`, `INCOMPLETE`, `CLOSED BY USER — UNRESOLVED FINDINGS` |
| Verification | `Verification` in `Project.md` | `NOT STARTED`, `IN PROGRESS`, the quality vocabulary below, and `CLOSED BY USER — UNRESOLVED FINDINGS` |

Recognized fields:

- Require exactly one recognized field.
- Missing, duplicate, malformed, or unrecognized labels mean Not reported or Unknown — never success; they do not block reading, preparation, copying, or selecting any stage.
- No other legacy text maps to approval.
- Specification and Planning review quality stays separate from their approval field: `PASSED` from Gear is not user approval, and `APPROVED` is not a claim that review passed.

Setting values:

- Set actual start/result state, not a forecast. Opening, reading, selecting a stage, preparing, and copying never change status.
- Initial Specification and Plan approval, and revisions requiring a new user decision, use `IN PROGRESS` while revising and `AWAITING APPROVAL` when presented; only actual user approval sets `APPROVED`.
- A reviewed amendment accepted wholly within already delegated discretion may retain the governing approval under the custody rules above; it is not a claim of fresh user approval.
- An unaccepted proposal never governs downstream work.
- Programming becomes `COMPLETE` only at its approved execution finish line.
- Verification becomes `PASSED` only under its independent whole-candidate passing contract; a fallback or unrepeated review is never a final `PASSED` result.

Overview field updates:

- Under normal write authority, Programming and Verification may update only their own named overview result field.
- Reread `Project.md` immediately before the minimal update and preserve its other result, description, goals, associations, and all unowned text.
- Do not overwrite changes observed since reading; simultaneous app/harness overview writes are unsupported.
- This grants no permission to correct the candidate, Specification, Plan, or documentation during Verification.
- If the brief is absent or writing is unavailable or unauthorized: report the result in conversation and leave the UI status unreported without blocking permitted work.

Earlier REPORT:

- After a later unsuccessful or incomplete Verification, retain an earlier REPORT without deletion or archival; identify it as a previous report, not current-pass evidence.
- Stopping is not successful completion.
- No status file, consent record, database, hash history, or certification service is required.

## Keep status and stopping truthful

- Carry completion from Specification through the Plan and every assignment using the role contract's delivery rules.
- Distinguish a completed review or draft assignment from the larger project's endpoint.
- Assign remaining authorized delivery and cleanup to responsible workers; obtain evidence of the output in its intended location and condition.
- A changed delivered product needs applicable verification of the material difference.
- A local passing result, REPORT, or worker handback alone cannot close the project.

Use established status meanings without treating status as user approval or authority. Where applicable, the recognized quality statuses are `PASSED`, `ONE PASS COMPLETE — REVISED, NOT RE-REVIEWED`, `NOT PASSED`, `NOT PASSED — REVIEW INCOMPLETE`, `NOT PASSED — REVISION INCOMPLETE`, and `GEAR 4 UNAVAILABLE — GEAR 3 FALLBACK`. A revised-but-unreviewed result is not passed. A transport failure is not reviewer disagreement. A fallback is not a completed Gear 4 run.

- Silence causes no calls, no cleanup beyond already authorized work, no status change, no REPORT, and no manufactured closure.
- On resumption, inspect the actual retained artifacts, candidate, findings, check output, and Git state; never infer a pass from a file or old label.
- If the user explicitly abandons work with unresolved material findings, the only closure label is `CLOSED BY USER — UNRESOLVED FINDINGS`; do not create REPORT or call the work complete, verified, passed, ready, or successful.
