# Ora Planning

## Purpose and boundary

Turn an approved Specification or substantive equivalent into one executable HOW for the actual project. Prevent a fresh Programming Loop from having to:

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

Read the current Request and Specification when they exist, or the substantive equivalents the user supplies. Evaluate product intent by content.

If a material WHAT is absent, show:

1. the exact missing product decision;
2. the implementation choice that would otherwise be made for the user;
3. the likely consequence of guessing; and
4. the recommendation to use [Ora Specification](ora-specification.md).

Reduced basis and commissioned work:

- The user may explicitly ask to continue on a reduced basis; do useful planning where the known requirements permit, record the exact limitation, and never call a Plan passed or executable while the missing WHAT still prevents responsible execution.
- For commissioned work, return a missing WHAT to the assignment owner for Specification under the shared correction route. Reviewed detail within delegated discretion does not automatically require user interruption; changes to reserved decisions still do.

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
- Ask the user only when the choice materially changes outcome, scope, risk, cost, authority, external effects, a maintainability concern they care about, or the finish line.

Use the released Gear products through their available documented interface, or prepare a complete handoff to a recipient where they are available. A native command is only a convenience. Do not copy their implementation:

1. Check only Gear 4 and Gear 3 availability for this stage.
2. Use Gear 4 once for meaningful ways to implement the same approved product. Even when the user has a preference, check for a materially simpler, safer, or better-supported route.
3. Move promptly to Gear 3 when evidence eliminates alternatives, the user chooses, or the Plan has one direction. Give each call the complete source material, inspected facts, current Plan, intended ending, and explicit peer choice.
4. Use Gear 3 to review the complete Plan for material gaps, contradictions, excess complexity, and executability. Use its bounded consensus form when the user has no further substantive input.
5. Return to Gear 4 only when new evidence reopens a material implementation choice. On technical failure, preserve the Plan, disclose the failure, and use only Gear's own fallback. If the required Gear product is unavailable, state the exact install-or-enable need and stop rather than imitating it.

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

## Size the run

Deliver the approved scope in the fewest runs that can each succeed and be independently verified. Every split adds handoff, review, and replanning cost.

Split when any of these holds:

- a material choice or foundation must be settled before dependent work; or
- independently testable outcomes have a stable boundary between them.

Keep work together when either holds:

- its behavior can only be verified jointly; or
- the interface between parts would be defined by the implementation itself.

When both a split condition and a keep-together condition apply, the keep-together conditions win; settle the required choice or foundation at a checkpoint inside the run.

Weigh against splitting:

- a shared edit surface;
- a fragment whose check would only restate its diff; or
- a split that saves neither context nor capability.

Checkpoints and run boundaries:

- A runnable or inspectable intermediate state is a checkpoint inside the run.
- It becomes its own run only when it also forms a stable boundary for planning and verifying what follows.

When the approved scope exceeds one run:

- rank the natural finish lines;
- record which finish line this Plan delivers and what returns for later planning; and
- design a verification point into any run that would otherwise reach completion unchecked.

Model tier:

- Assign each run the least capable model that can execute it.
- A cheaper tier requires all of: mechanical work; bounded context; literal references governing every precision requirement; no material unresolved choice; one writer per shared surface.

## Required Plan

Produce one current Plan with only useful project-specific content, in this order when applicable:

1. **Controlling product input** — the approved Specification and exact outcome and scope it controls, without copying the Request.
2. **Inspected starting state** — facts governing the approach and user work that must be protected.
3. **Chosen HOW** — the implementation approach and only consequential rationale.
4. **Execution sequence** — coherent phases and complete assignments, useful parallelism, dependencies, foundation evidence and review boundaries, integration, staffing, document custody, and affected components identified by inspection.
5. **Exact checks** — the complete authorized testing ceiling and the concrete material risk each check judges.
6. **Finish line** — the Specification's project-specific endpoint and the complete route through production, verification, documentation, authorized delivery, and cleanup, with responsible owners, evidence of the delivered condition, and retained approvals — or, when Size the run limits this Plan to part of the approved scope, the recorded finish line for this run and the scope returned for later planning, which is not a future backlog. A verification pass is a checkpoint when finishing work remains.
7. **Implementation safeguards** — include the exact block below without weakening it.

> **Implementation safeguards**
>
> Build only the product defined by the approved Specification, using the simplest implementation that fulfills it and fits the inspected project. Reject speculative features, future-proofing, generalized frameworks, compatibility layers, tracking systems, extension mechanisms, and edge-case machinery. Any proposed discretionary addition must satisfy the supplied shared contract’s proof rule; a named material risk is not sufficient.
>
> Every lasting component must enable a required behavior, truth guarantee, safety property, or necessary recovery capability. If it does none of those, remove it. A newly discovered missing WHAT returns to Specification for the user's decision; implementation must not silently choose it.
>
> The checks named in this Plan are the complete testing ceiling. A named test file does not authorize unlimited test additions or reruns. Additional or repeated checks, broad suites, and builds must satisfy the supplied shared contract’s proof rule and necessary authority. Run approved checks after coherent batches; count invocations in existing check output, without a tracker.
>
> Add or change tests only for user-visible behavior, a material regression, preservation of important content or data, or essential failure behavior. Stop testing when the approved checks pass and material review is satisfied.
>
> Independent review may reject only for a material defect: wrong user-visible behavior, unmet approved criteria, content or data loss, falsehood, a real runtime or deployment failure, unauthorized scope or effects, broken atomicity, failed necessary recovery, security exposure, or a required check that does not pass. Preferences about abstraction, style, tracking, or unrequested generality are not defects.
>
> Continue through the approved execution sequence, exact checks, independent review, correction of every in-scope material finding, truthful documentation, task-owned cleanup, and the declared finish line. Do not stop at code written, a partial milestone, or an unreviewed candidate.

State that repository or harness instructions may add necessary safety and delivery requirements but must not silently weaken the safeguards or enlarge product scope.

The missing-WHAT safeguard reserves user-owned product decisions; detail already delegated follows the shared amendment rules.

Plan content limits:

- Do not reproduce the Specification, preserve rejected designs, transcribe discussion, add a future backlog, or include generic advice that does not direct this implementation.
- Revise the Plan itself when it changes; do not append amendment history.

Correcting an inadequate Plan within delegated authority:

- Return the proposed amendment for independent review and owner acceptance under the shared custody rules.
- The accepted change must reach affected workers before resumption.
- Never let a consultation answer silently replace the governing Plan; never add a second correction loop around a self-contained workflow.

The Plan is complete only when all of these hold:

- it conforms to the approved product, with facts from inspection and no material WHAT hidden;
- consequential choices are resolved or safely delegated;
- complete assignments let a fresh Programming Loop execute without redesign;
- checks and their risks are exact, and the delivery endpoint and its route are observable;
- every component passes the irreducible-complexity test;
- bounded material review is complete; and
- the full Plan has the required approval under the shared rules.

## Output and stop

- Retain one current Implementation Plan; present its truthful review status separately from user approval.
- In standalone use: after approval, recommend [Ora Programming](ora-programming.md) and stop; do not invoke it secretly.
- A commissioned executor returns the actual Plan or amendment, review evidence, accepted changes, affected dependencies, and any required decision to its owner.
- Supply the complete Programming handoff when needed; only authorized guided coordination advances the lifecycle.
