# Ora Planning

## Purpose and boundary

Turn the available Specification — complete or not — or a substantive equivalent into one executable HOW for the actual project. Prevent a fresh Programming Loop from having to:

- redesign the solution;
- choose a consequential dependency;
- invent the affected scope;
- guess what risks deserve checks; or
- guess where the work finishes.

Use and authority:

- Use this framework with the complete [shared contract](../references/shared-contract.md) and its required role-and-assignment source; for portable use, supply all three texts.
- This entry works without Ora provenance or default filenames.
- Planning is read-only toward the target project; it may write only Request and Plan artifacts under applicable artifact authority.
- Do not implement the Plan.

Assignment:

- Assign the producing session the executor role using Ora Planning.
- As team designer, it reads the complete role catalogue and receives a complete assignment, including the agreed completion endpoint and document custodian.
- The architecture describes actual assignments under that contract; it invents no new worker roles.

## Inputs and readiness

Read the current Request and Specification when they exist, or the substantive equivalents the user explicitly designates. Evaluate product intent by content.

- When supplied sources contain genuinely conflicting versions and the user has not chosen among them, show the conflict for the user's choice; never silently choose, combine, or prefer the newer text.

If a material WHAT is absent, show:

1. the exact missing product decision;
2. the implementation choice that would otherwise be made for the user;
3. the likely consequence of guessing; and
4. the recommendation to use [Ora Specification](ora-specification.md).

Continuing on the available information:

- The user may proceed with whatever requirements exist. Do useful planning where the known requirements permit, record the exact limitation, and report it honestly; never present a Plan as fully grounded while a material WHAT is missing.
- The recommendation to specify first is advice. Ask useful questions and explain consequential gaps in the normal conversation; when the user chooses to proceed, do so and state the resulting limitations.
- For commissioned work, return a missing WHAT to the assignment owner for Specification under the shared correction route when the user wants that.

## Inspect before choosing HOW

Inspect enough of the real starting state to make evidence-based choices. Where relevant, read:

- repository or project instructions;
- current code, architecture, public interfaces, and affected call sites;
- behavior, content, and data that must remain intact;
- dependencies and platform constraints;
- focused existing checks and build or deployment behavior;
- Git and working-tree state, including unrelated user work to protect; and
- live automation or consequential external effects that shape the finish line.

Discovery rules:

- For a new project, inspect the actual target environment and supplied constraints.
- Stop discovery when facts are sufficient; another pass needs a specific unanswered question capable of materially changing the Plan.
- If choosing HOW would decide who the product serves, required visible behavior, accepted or produced content or data, essential failure behavior, permissions, product boundaries, material quality, or which substantively different product to build, return the smallest decision to Specification. Do not hide it in a recommendation.

## Choose and review the HOW

- Resolve ordinary reversible technical choices through professional judgment.
- Ask the user only when the choice materially changes outcome, scope, risk, cost, authority, external effects, a maintainability concern they care about, or the finish line. In interactive Planning production, use concise question bullets in the AI response with context, realistic options, consequences, and a recommendation; ask one decision at a time under applicable role and authority, and invent no questions.
- In that production work, when no user question remains, prepare the full, detailed, executable Plan ready for Programming within existing authority, and suggest review. Advisory assessments retain their required verdict/reasoning format.

Use the released Gear products through their available documented interface when they are available to you; they are optional aids, never a prerequisite for this work. A native command is only a convenience. Do not copy their implementation:

1. Check whether Gear 4 and Gear 3 are available.
2. When available, use Gear 4 once for meaningful ways to implement the same product. Even when the user has a preference, check for a materially simpler, safer, or better-supported route.
3. Move promptly to Gear 3 when evidence eliminates alternatives, the user chooses, or the Plan has one direction. Give each call the complete source material, inspected facts, current Plan, intended ending, and explicit peer choice.
4. Use Gear 3 to review the complete Plan for material gaps, contradictions, excess complexity, and executability.
5. Return to Gear 4 only when new evidence reopens a material implementation choice. On technical failure, preserve the Plan and disclose the failure. When a Gear product is unavailable, say so plainly and continue the work directly; an unavailable optional aid never stops the assignment.

## Design assignments and dependencies

Choose the smallest useful working pattern for each phase:

- An executor and separate verifier for bounded production and independent checking.
- A bounded consultant using the relevant skill for a distinct question, returning to the caller with useful execution context preserved.
- One writer for a coupled foundation until independent acceptance; then path-exclusive parallel lanes with one writer per shared integration surface. Freeze all edit lanes before cumulative review.

Each assignment supplies the role contract's complete brief, prerequisites, waiting dependencies, expected evidence, and next owner.

- Plan integration and verification where outputs join; show the critical path through finishing work.
- Use existing coordination to take only ready, unowned work; create no scheduler or parallel tracking system.

Balance and staffing:

- Balance possible parallel speed against handoff cost, coupling, duration, context needs, and independent-review requirements.
- Select capable models and harnesses according to current availability and authorized cost, separately from roles.
- Do not impose a fixed model, context/token threshold, permanent team size, or an extra coordinator/secretary where the existing loop and an explicit document custodian suffice.

## Review costly foundations early

- Identify foundations whose misunderstanding could discard substantial downstream work.
- For each: define a complete reviewable pass, the evidence needed to accept it, the responsible reviewer, and the work that waits for that acceptance.
- Use machine review for delegated technical judgment.
- Where visual or personal intent is consequential, provide realistic mockups, prototypes, or implemented slices; a conceptual diagram alone does not establish that intent.

Before unattended execution:

- Show the rework risk; offer and strongly recommend human review of such evidence.
- Establish whether the user retains the checkpoint or explicitly delegates its judgment; carry that choice into assignments.

Silence never waives a retained checkpoint; unaffected authorized work continues, and other phases need no automatic user gate.

## One project, one run

- Plan the whole project through its approved delivery endpoint, with one final project verdict.
- Work requiring a separate later delivery becomes a separate project before approval. Preserve every outcome in the appropriate Specification; route proposed scope changes through Specification and its approval.
- Context handoffs, phases, internal reviews, human checkpoints and recovery can remain inside one run. None establishes whole-project completion while required work remains.

Model tier:

- Stay within the user's selected model configuration. Consider a cheaper model within that configuration when a run needs less capability; never downgrade automatically to another configuration.
- A cheaper assignment requires all of: mechanical work; bounded context; literal references governing every precision requirement; no material unresolved choice; one writer per shared surface.

## Required Plan

Produce one current Plan with only useful project-specific content, in this order when applicable:

1. **Controlling product input** — the available Specification and the exact outcome and scope it controls, without copying the Request.
2. **Inspected starting state** — facts governing the approach and user work that must be protected.
3. **Chosen HOW** — the implementation approach and only consequential rationale.
4. **Execution sequence** — coherent phases and complete assignments, useful parallelism, dependencies, foundation evidence and review boundaries, integration, staffing, document custody, and affected components identified by inspection.
5. **Exact checks** — the complete authorized testing ceiling and the concrete material risk each check judges.
6. **Finish line** — the Specification's project-specific endpoint and the complete route through production, verification, documentation, authorized delivery, and cleanup, with responsible owners, evidence of the delivered condition, and retained approvals. A verification pass is a checkpoint when finishing work remains.
7. **Implementation safeguards** — include the exact block below without weakening it.

> **Implementation safeguards**
>
> Build only the product defined by the approved Specification, using the simplest implementation that fulfills it and fits the inspected project. Reject speculative features, future-proofing, generalized frameworks, compatibility layers, tracking systems, extension mechanisms, and edge-case machinery. Any proposed discretionary addition must satisfy the supplied shared contract’s proof rule; a named material risk is not sufficient.
>
> Every lasting component must enable a required behavior, truth guarantee, safety property, or necessary recovery capability. If it does none of those, remove it. A newly discovered missing WHAT returns to Specification for the user's decision; implementation must not silently choose it.
>
> The checks named in this Plan are the complete testing ceiling. A named test file does not authorize unlimited test additions or reruns. Additional or repeated checks, broad suites, and builds must satisfy the supplied shared contract’s proof rule and necessary authority. Run approved checks after coherent batches; count invocations in existing check output, without a tracker.
>
> Add or change tests only for user-visible behavior, a material regression, preservation of important content or data, or essential failure behavior. Stop testing when the approved checks pass and review is settled.
>
> Independent review follows the supplied shared contract's reviewer rule. A finding is actionable only with evidence of a result contrary to the Specification in a way that changes the result the user asked for, or a real error with identified harm. The builder fixes actionable findings the smallest way or rejects a finding with recorded reasons. A rejection stands, except on severe failures: unrecoverable data loss, security exposure, and unauthorized or erroneous spending, sending or publishing. Unresolved severe findings go to the owner.
>
> Continue through the approved execution sequence, exact checks, independent review, a recorded fix or reasoned rejection of every finding, one removal-only review before landing, truthful documentation, task-owned cleanup, and the declared finish line. Do not stop at code written, a partial milestone, or an unreviewed candidate.

State that repository or harness instructions may add necessary safety and delivery requirements but must not silently weaken the safeguards or enlarge product scope.

The missing-WHAT safeguard reserves user-owned product decisions; detail already delegated follows the shared amendment rules.

Plan content limits:

- Do not reproduce the Specification, preserve rejected designs, transcribe discussion, add a future backlog, or include generic advice that does not direct this implementation.
- Revise the Plan itself when it changes; do not append amendment history.

Correcting an inadequate Plan within delegated authority:

- Return the proposed amendment for independent review and owner acceptance under the shared custody rules.
- The accepted change must reach affected workers before resumption.
- Never let a consultation answer silently replace the governing Plan; never add a second correction loop around a self-contained workflow.

The Plan is complete enough for the intended work when all of these hold:

- it conforms to the available product input, with facts from inspection and no material WHAT hidden;
- consequential choices are resolved or safely delegated;
- complete assignments let a fresh executor proceed without redesign;
- checks and their risks are exact, and the delivery endpoint and its route are observable; and
- every component passes the irreducible-complexity test.

The user's workspace can commission a fresh independent assessment of whether the current Plan sufficiently guides the intended work; its verdict is advisory information and never blocks programming or revision. That assessment can also run as a second opinion — one model authors, a second harness evaluates, the author revises given the evaluation as a guide. One evaluation followed by one revision settles it: the author's recorded dispositions — every recommendation fixed or rejected with reasons — end the exchange, and remaining disagreement stays inside the revised assessment as advisory information rather than a tie-breaking request to the user. When the user selects Iterate, up to three rounds run, stopping early once an evaluation passes; remaining disagreement still stays inside the assessment. The different-lab or same-lab-fresh-session case is labeled honestly. The user may start programming whatever the state of the Plan. A Plan finding must show a user harm or a contradiction with the owner's decision.

## Output and stop

- Save opening YAML `status: DRAFT`, `IN PROGRESS` or `AWAITING APPROVAL` as actually applicable, with blank `review:` until assessed. Preserve existing vault metadata. A deliberate request to create this Plan approves the supplied Specification; a request to implement this Plan approves its supplied version, independently of review. Record that approval without asking for another entry. Material revisions after approval follow the shared change rules and preserve the earlier assessment.
- Retain one current Plan; present its truthful assessment status separately from the user's own acceptance.
- Revise the document the user's workspace resolved and displays, keeping its filename; use the expected default name only for a missing output.
- An external revision may carry a small type label in closed opening YAML frontmatter, for example `vibe_document: plan`; the same field is recognized in ordinary opening metadata, and a label never proves completeness.
- Where a workspace discovers documents automatically — a deliberate association first, then the expected name, a recognized `vibe_document` type label, then role words in the filename, newest within a rank — an explicit file choice overrides discovery. External saves appear when the user rereads the files; discovery identifies a document and never proves approval or completion.
- In standalone use: recommend [Ora Programming](ora-programming.md) and stop; the user may start programming at any time, whatever the state of this Plan.
- A commissioned executor returns the actual Plan or amendment, assessment evidence, accepted changes, affected dependencies, and any required decision to its owner.
