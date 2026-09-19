# Ora Verification

## Purpose and boundary

Independently judge the complete current implementation and its documentation. Return one consolidated material correction set or, only after a clean cumulative result, create REPORT. The live invoking context coordinates one fresh reviewer; it is not itself the sole reviewer.

- Use this framework with the complete [shared contract](../references/shared-contract.md) and its required role-and-assignment source; for portable use, supply all three texts.
- Standalone use needs an accessible candidate and substantive specification material.
- Accept useful Plan, documentation, checks, baseline, or diff without requiring Ora provenance, filenames, Git, or prior status.

Commissioning:

- At owner entry, commission a separate session assigned verifier, with Ora Verification as its method, the complete assignment, actual candidate/evidence, and direct return owner.
- A staffed coordinator remains the owner and delegates substantive inspection.
- A session already receiving that verifier assignment performs the review below and returns its result; it does not recursively commission another reviewer or correct the product.
- Verification is read-only with respect to the candidate, Specification, Plan, documentation, Git state, and external systems.
- Declared outputs only: creating REPORT after `PASSED` and, in a managed project with normal write authority, updating only the overview's `Verification` field — subject to the shared artifact-scope and no-overwrite rules. The overview extension does not authorize corrections to candidate artifacts.

## Establish the review basis

- The owner assembles accessible governing inputs; the verifier reads applicable project instructions and inspects the actual candidate.
- Ground truth: code, generated artifacts, current documentation, runtime behavior, and credible current check output. Not ground truth: summaries, old labels, and prior pass claims.
- Include the agreed completion conditions, retained human decisions, and any finishing actions still outside this review assignment.

For the guided path, assemble:

- the approved Specification and Plan when each exists;
- actual project path, current revision or baseline, and direct candidate access;
- the complete current User Guide, Technical Documentation, and Product Overview;
- exact output from every check authorized by the Plan; and
- the relevant cumulative diff when one exists.

Basis limits:

- Exclude raw Request discussion and implementation transcripts.
- When an upstream artifact was explicitly skipped, disclose the reduced conformance basis.
- For standalone use: identify exact omissions and continue everything still judgeable rather than inventing requirements or rejecting the whole review.

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
- whether every readiness statement in REPORT would be true.

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

- Standalone Verification stops with findings and its recommendation; it never invokes a correction stage secretly.
- In the guided path, return the complete correction set to the owner for the earliest responsible stage.
- Specification and Plan amendments follow shared review, acceptance, custody, and refresh rules; retained user approvals remain required.
- Programming corrects implementation and affected documentation; affected authorized checks are refreshed; and the whole current candidate receives another fresh cumulative Verification. Do not review only the last fix or convert an unresolved defect into a final limitation.

## PASSED and REPORT

Return `PASSED` only when all of these hold:

- no material finding or unverified material risk remains;
- all required authorized checks pass;
- implementation conforms to the supplied Specification and Plan where each exists;
- important content and data are preserved;
- failure and recovery behavior is sound; and
- all three guided-path documentation products truthfully describe the same candidate.

Only then create `<Project Name> — 07 Report.md` through an authorized report assignment to the verifier or an executor; a staffed coordinator delegates this substantive output. Title it **REPORT**, never “final report.” Certify the current product rather than narrating its construction. Include:

- the verification basis and result;
- the Specification and Plan used for conformance, when they exist;
- confirmation of material code, mechanical, silent-failure, preservation, regression, and documentation-truth review;
- a concise summary of exact check evidence rather than raw logs;
- the truthful readiness conclusion for the use named by the Specification; and
- the delivered-material list: Request, Specification, Implementation Plan, product-code path or revision, User Guide, Technical Documentation, Product Overview, and REPORT.

REPORT limits and handback:

- REPORT may describe approved limits or a genuinely reduced basis only when its conclusion remains true.
- REPORT must not contain: an unresolved material defect, a reviewer transcript, a construction diary, or a claim that its own existence proves success.
- Return the review, inspectable REPORT if produced, evidence, limitations, remaining dependencies, and delivery state directly to the owner.
- `PASSED` completes this review assignment; the owner delegates any remaining authorized delivery, documentation, or cleanup through the existing workflow.
- Required user approval before publication remains a checkpoint.
- Confirm the delivered condition with applicable evidence and resolve any material product change before claiming the larger project complete.

If the result is not passed:

- Do not create REPORT. Present the status, complete finding set or exact incomplete-review risk, and recommended owner, then stop.
- Under normal write authority, record actual start/result in the overview's own `Verification` field using the shared rules.
- An earlier REPORT is retained but described as a previous result, not proof that this candidate passed.
