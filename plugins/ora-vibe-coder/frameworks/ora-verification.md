# Ora Verification

## Purpose and boundary

Independently judge the accessible current implementation and its available requirements, and record the result truthfully in one Verification Report. The live invoking context coordinates one fresh reviewer; it is not itself the sole reviewer.

- Use this framework with the complete [shared contract](../references/shared-contract.md) and its required role-and-assignment source; for portable use, supply all three texts.
- Standalone use needs an accessible candidate; requirements of whatever completeness are supplied as available.
- Accept useful Plan, documentation, checks, baseline, or diff without requiring Ora provenance, filenames, Git, or prior status.

Commissioning:

- At owner entry, commission a separate session assigned verifier, with Ora Verification as its method, the complete assignment, actual candidate/evidence, and direct return owner.
- A staffed coordinator remains the owner and delegates substantive inspection.
- A session already receiving that verifier assignment performs the review below and returns its result; it does not recursively commission another reviewer or correct the product.
- Verification is read-only with respect to the candidate, Specification, Plan, documentation, Git state, and external systems.
- Declared outputs only: the Verification Report, and in a managed project with normal write authority the overview's own `Verification` field. The overview extension does not authorize corrections to candidate artifacts.

## Establish the review basis

- The owner assembles accessible governing inputs; the verifier reads applicable project instructions and inspects the actual candidate.
- Ground truth: code, generated artifacts, current documentation, runtime behavior, and credible current check output. Not ground truth: summaries, old labels, and prior pass claims.
- Include the agreed completion conditions, retained human decisions, and any finishing actions still outside this review assignment.

Assemble what exists:

- the available Specification and Plan;
- the Programming Result's recorded implementation location or delivered revision, and direct candidate access;
- any project documentation, exact check output, and the relevant cumulative diff; and
- any available baseline.

Basis limits:

- Missing formal documents alone are not a verification failure. Explain what can be checked and what cannot be established — for example, whether working code meets an intention that was never sufficiently defined.
- Exclude raw Request discussion and implementation transcripts.
- When an upstream artifact was skipped or is thin, disclose the reduced conformance basis and judge everything still judgeable rather than inventing requirements or rejecting the whole review.

## Obtain one fresh independent review

Prefer one user-selected, ready, project-capable external target through the released Agent Bridge Format 2 interface when that route is available. Use Bridge only as a courier:

1. If the user already supplied a target, check that target's current readiness and project capability.
2. Otherwise use current Bridge readiness results to show the ready project-capable choices, recommend one with provenance different from the implementation agent, explain why, and ask for one selection. Do not create a default ranking, choose silently, or rotate peers.
3. Create one project session bound to that peer with the inert initiator `ora-verification`. Give it Project access only when the peer is qualified for project work.
4. Send one complete inert Markdown review request. Include the entire basis, role source, verifier assignment and return destination, and material finding and status contract under the shared packet rules; never assume an earlier Bridge message is context.
5. Run the bounded session, read the returned response, and retain its temporary record only while correction or recovery needs it.

Bridge constraints:

- Bridge must not choose the reviewer, interpret findings, retry, approve, or route work.
- Do not copy connector facts, model catalogs, authentication rules, timeouts, or qualification tables into this framework.

If the external route is unavailable:

- Disclose the exact missing companion or transport failure and use one qualified isolated fresh reviewer with equivalent read-only access.
- An available native reviewer is one delivery method; a complete manual handoff to a separate qualified fresh recipient is another. Show what to open, what to paste, the candidate access it needs, and the expected returned review.
- Do not assume that a pasted local path is accessible remotely.
- Wait for the actual independent response; preparing or copying the request is not a completed review.
- Do not call the fallback model-diverse or portray a transport failure as reviewer disagreement.
- If no qualified independent path is available, return `NOT PASSED — REVIEW INCOMPLETE` and state the exact missing prerequisite.
- Never imitate an unavailable companion or use the invoking context as its own sole reviewer.

## Reviewer contract

Require direct inspection of the whole current candidate for:

- conformance to supplied requirements and to the approved Plan when one exists;
- material code, mechanical, and runtime errors;
- silent failure and failures that falsely appear successful;
- loss, corruption, or unintended replacement of important content or data;
- essential failure behavior and necessary recovery;
- material regressions where an actual baseline exists;
- unauthorized scope or consequential effects;
- consistency between implementation and every supplied documentation product; and
- whether every readiness statement in the Verification Report would be true.

These are obligations, not finding quotas. Preferences about wording, abstraction, tracking, extra tests, documentation style, or speculative improvements are not findings. Any actual material defect forces `NOT PASSED`.

Each material finding must state the observed defect or exact unverified risk, direct evidence, material consequence, smallest correction, and earliest owning stage:

- Specification owns a missing or wrong WHAT.
- Planning owns a correction that changes or invalidates the approved HOW, affected architecture, consequential dependency, execution sequence, risk coverage, or finish line.
- Programming owns implementation or documentation that violates an otherwise adequate Specification and Plan.

The fresh reviewer returns either no material findings or one consolidated current set.

## Checks and correction

- In the guided path: use only the Plan's exact authorized checks and require all of them to pass; do not widen the ceiling for reassurance.

In standalone use:

- Begin read-only inspection immediately.
- Any proposed additional or repeated check must satisfy the shared contract's proof rule; use credible current evidence first. Show the smallest necessary check; a proposal is not permission to run it.
- If required evidence remains unavailable: continue the rest of the review and mark the affected criterion `NOT PASSED — REVIEW INCOMPLETE`.

Correction routing:

- Verified findings survive continuation and reach the user with their evidence and recommended fixes. Report findings outside the reviewed scope without extending repair authority; do not silently repair them.
- Standalone Verification stops with findings and its recommendation; it never invokes a correction stage secretly.
- In the guided path, return the complete correction set to the owner for the earliest responsible stage.
- Specification and Plan amendments follow shared review, acceptance, custody, and refresh rules; retained user approvals remain required.
- Programming corrects implementation and affected documentation; affected authorized checks are refreshed; and the whole current candidate receives another fresh cumulative Verification. Do not review only the last fix or convert an unresolved defect into a final limitation.

## Verdict and the Verification Report

Record the actual verdict — for example `PASSED`, `NOT PASSED`, or a not-passed verdict with its exact reason such as `NOT PASSED — REVIEW INCOMPLETE`. Truthfulness rules:

- `PASSED` only when no material finding or unverified material risk remains, the authorized checks that exist pass, the implementation conforms to the available requirements where they exist, important content and data are preserved, and failure and recovery behavior is sound.
- Neither the report's existence nor an older passing result proves that newer code passed. A saved verdict describes the implementation actually inspected, not automatically newer code.
- A fallback, unrepeated, or transport-failed review is never recorded as a completed passing review.

Save or update one current Verification Report after actual verification — for passing, failing, and incomplete reviews alike. Update the current report after subsequent verification rather than accumulating superseded ones. It records:

- the implementation and available requirements inspected;
- the actual verdict and the supporting check evidence;
- findings and recommended corrections;
- incomplete evidence and remaining work; and
- a truthful readiness conclusion and the relevant delivered materials.

Report limits and handback:

- A report may describe approved limits or a genuinely reduced basis only when its conclusion remains true.
- The report must not contain a false readiness claim or a claim that its own existence proves success.
- Return the review, the report, evidence, limitations, remaining dependencies, and delivery state directly to the owner.
- Required user approval before publication remains a checkpoint.
- An earlier saved verdict is retained as history; it is not evidence that the current candidate passed.

If the result is not passed, still save the report with its truthful verdict and findings; present the complete finding set or exact incomplete-review risk and the recommended owner. Under normal write authority, record the actual result in the overview's own `Verification` field using the shared rules.
