# Ora Vibe Coder Product Overview

Ora Vibe Coder is for people who want to build software with an AI coding tool while keeping the project understandable and under deliberate control. It turns an idea or existing project into a sequence of clear, inspectable Markdown assignments: define the product, plan the implementation, build it with independent review, and verify the complete result. Vibe runs locally and prepares the handoff; your chosen coding tool still owns conversation, login, permissions, model use, and execution.

## The problem it solves

AI coding work often begins easily and becomes hard to govern. Product decisions get mixed with technical choices. Important constraints live in old chats. A new session cannot tell which version is current. “The model ran” gets mistaken for “the product is finished.” Reviews see a summary instead of the real candidate. A useful result can remain on a branch or in an unused document. Vibe addresses that problem with a small set of durable boundaries:

- current requirements and plans live in ordinary project documents;
- each lifecycle stage has one clear purpose;
- your exact instruction appears before framework text;
- the complete prepared assignment is visible before delivery;
- execution and review use separate contexts;
- status comes from explicit fields, not inferred activity; and
- preparation, launch, receipt, execution, review, and delivery remain distinct facts.

The goal is not more process. The goal is less hidden judgment and less confusion about what actually happened.
## Who it is for

### People with an idea but no technical plan

Start with Specification or **Help me get started**. The method helps turn intent into observable behavior and boundaries without requiring you to choose frameworks, code structure, or infrastructure prematurely.
### Project owners with an existing codebase

Open the directory, link its current requirements and documentation, and choose the stage that matches the real gap. Vibe does not require renaming files or migrating the repository into a proprietary project format.
### Developers using several coding tools

The same Vibe stages can prepare work for Codex, Claude Code, ZCode, Hermes, Qwen Code, or MiniMax Code. Host-specific mechanics stay in small adapters; the Programming Loop method remains the same.
### Teams that need an inspectable handoff

`Handoff.md` is a complete current snapshot that can be reviewed, copied, versioned, or delivered manually. It starts with the exact user request and labels instructions, project facts, source material, authority, and expected output.

## The product in one flow

```text
Idea or current project
        ↓
Specification — decide WHAT the product must be
        ↓
Planning — inspect the project and decide HOW to build it
        ↓
Programming — implement, check, review, correct, and deliver
        ↓
Verification — independently inspect the whole candidate
        ↓
Report only after PASS
```

The flow is fixed, but entry is flexible. A project can begin at the earliest stage its current evidence needs. Existing approved requirements do not need to be recreated. A complete candidate can go directly to Verification. Guided mode helps choose; it does not force every stage to run.
## What makes it different

### Local and file-based

Vibe's browser workspace is served from your computer. Projects remain normal directories. Requirements, plans, guides, and reports remain Markdown. There is no hosted project database or proprietary run record to export later.
### Preparation before delivery

The complete packet is saved and displayed before Continue or Copy. If the saved file changes, Vibe refuses to copy unseen content. This makes the handoff something you can inspect rather than a hidden prompt assembled at launch time.
### One method, several hosts

The Programming Loop has one universal workflow. Each initiating host gets only the instructions needed to create a fresh worker, retrieve its result, and wait safely. This avoids six drifting versions of what “implement and review” means.
### Independent review is structural

The Loop creates a fresh executor, then a different fresh reviewer that receives the approved plan, real cumulative diff, repository access, and exact check evidence. It does not receive the executor's conversation or intended conclusions.

### Truthful stopping

A prepared packet is not a sent packet. A launched window is not receipt. Process exit is not completion. Reviewer transport is not reviewer agreement. A Report is not created until current whole-candidate Verification passes. These distinctions keep confidence proportional to evidence.

## Typical uses

### Shape a new application

Use Specification to clarify intended users, visible workflows, data treatment, failures, and success. Use Planning to inspect the chosen environment and produce an executable route. Programming then builds the candidate and its real reader documentation. Verification judges the whole result.

### Add a bounded feature

Link the existing product requirement and plan, state the feature outcome and protected work, and hand it to Programming. The Loop proposes a small scope lock, uses exact relevant checks, and keeps unrelated repository changes out of the task.

### Recover a stalled AI coding task

Open the actual repository and current documents. Vibe's packet can state the preserved branch, incomplete diff, check evidence, findings, and next owner. The recipient resumes from real artifacts instead of a reconstructed chat summary.

### Audit a completed candidate

Use Verification with accessible requirements, implementation, documentation, and checks. The verifier reports material findings with evidence and the smallest correction, or creates the Report only after PASS.

### Move a prepared task between tools

Use Copy to deliver the same complete Markdown to a different capable recipient. Be explicit about access: a path on one machine is not evidence available to a remote session.

## Benefits

### For the project owner

- Consequential product decisions remain visible and yours.
- You see what will be sent before a tool receives it.
- Status labels are understandable and conservative.
- Missing documents and broken links are surfaced rather than guessed around.
- You can stop at any point without losing the current project files.

### For the coding agent

- Fresh sessions receive a complete assignment instead of assumed history.
- Requirements, implementation authority, protected work, and exact checks are explicit.
- The stage determines whether the task is defining WHAT, choosing HOW, building, or reviewing.
- Material defects are distinguished from style preferences.
- The expected return owner and completion endpoint are named.

### For maintainers

- The application uses ordinary Python and static browser assets.
- The lifecycle method is consolidated instead of copied into native entries.
- The Programming Loop has one canonical component and one generated embedded mirror.
- Installation and handoff replacement are transactional and preserve uncertain user content.
- Focused tests can prove deterministic packaging without provider calls.

## What Vibe deliberately does not do

Vibe is not:

- a hosted coding environment;
- a model provider, router, or subscription manager;
- a credential store;
- a chat importer or transcript archive;
- an autonomous background agent service;
- a replacement for Git;
- a secret scanner or data-classification system;
- a guarantee that a third-party host or model is available;
- a visual design judge; or
- proof that a launched process completed the project.

It does not silently install coding tools, authenticate, choose a paid route, publish, deploy, message other people, or bypass the selected tool's approvals.

## Prerequisites and conditions

Vibe requires Python 3.10 or later, a browser, and filesystem access to the chosen project directory. Continue additionally requires a supported coding-tool executable and a desktop terminal route. Copy works when Continue is unavailable.

Specification and Planning require the separately installed Gear 3 and Gear 4 companion; Vibe setup does not install it. Programming requires the Programming Loop, which Vibe setup installs or updates for each coding tool the user selects. If either required companion is unavailable or mismatched, the dependent stage stops honestly: use Gear's own setup instructions for Gear, or rerun Vibe setup with the receiving host selected and restart that host for the Loop. Agent Bridge is optional and serves only an explicitly selected external-review route; without it, that route is unavailable, not silently substituted or described as model diversity, while a qualified fresh internal or complete manual review route remains usable where the stage provides it.

The quality of a stage depends on accessible source material. A remote reviewer cannot inspect a local-only path. A visual requirement cannot be established from text alone. A live provider claim cannot be established by a fake test. Vibe preserves and labels these limits rather than converting them into success.

The product works best when the project owner keeps one current Request, Specification, and Plan rather than appending histories. Git owns construction history; reader documents describe the active product.

## Supported host boundary

Packaging and focused checks cover Codex, Claude Code, ZCode, Hermes, Qwen Code, and MiniMax Code destinations. The application detects their local command entries, prepares safe arguments, and keeps Copy available when detection or launch fails.

This is a mechanical compatibility claim. Individual host versions, operating systems, accounts, models, permission modes, and provider routes may still require live qualification. Vibe says so in the interface instead of treating an executable name as proof.

The standalone Programming Loop supplies a native adapter for each host and reviewer profiles where the host supports them. It never selects a provider on the user's behalf.

## Expected result

A successful Vibe project does not end with “an AI responded.” It ends at the completion condition the owner approved: the intended behavior exists, important content remains, focused checks and direct inspections support it, independent review is complete, truthful user and technical documentation describe the candidate, the authorized delivery endpoint has been reached, and temporary task work is cleaned up.

If that result cannot be reached within current authority, the expected output is equally clear: the candidate is preserved, the exact blocker or decision is stated, and no later status is claimed.

## Choosing whether to use it

Use Vibe when the work benefits from explicit stages, durable Markdown context, a visible handoff, and an executor/reviewer loop. For a tiny one-line edit with no meaningful ambiguity or review risk, a direct coding-tool conversation may be simpler.

Use Copy when you want the packet discipline without a native launch route. Use the standalone Programming Loop when requirements and a plan are already available and you do not need the local project workspace.

Do not use Vibe as a reason to share material a recipient should not receive. Its value is making the boundary inspectable so you can choose responsibly.

## Further reading

## A practical decision guide

- Choose **direct conversation** when the change is genuinely tiny, its desired result is already obvious, no important existing work is at risk, and independent review would add no material confidence. Vibe should reduce ambiguity, not manufacture ceremony.
- Choose **Specification** when two reasonable implementations could produce meaningfully different products, when users or permissions are unclear, when content or data treatment is unsettled, or when “done” cannot yet be observed. This keeps product choices out of the coder's hidden discretion.
- Choose **Planning** when the desired product is settled but the real repository, dependency choices, migration, checks, or delivery route require inspection. The Plan should make a fresh executor able to build without redesigning the solution.
- Choose **Programming** when the task has a usable outcome and implementation direction, including a deliberately acknowledged reduced basis. The Loop still presents a scope lock, protects state, and obtains approval; skipping an upstream quality stage never grants broader effects.
- Choose **Verification** when the candidate is complete enough to judge and the verifier can directly access the evidence. Use it before consequential release or when implementation confidence and independent evidence need to be separated.
- Choose **guided mode** when you cannot tell which of those conditions applies. It gives a recipient the full lifecycle vocabulary while preserving your control over approvals and external effects; it is not an “auto-run everything” button.
- Choose **manual Copy** when the coding tool is remote, unsupported, not detected, or should receive the packet through a channel you control. The same inspection benefit remains, but access and receipt must be stated honestly.
- Choose the **standalone Programming Loop** when you already have suitable requirements and a plan, do not need Vibe's local project reader, and want the executor/reviewer method installed directly in a supported initiating host.

- [User Guide](User%20Guide.md) for setup, ordinary use, document linking, delivery, recovery, stopping, and removal.
- [Technical Documentation](Technical%20Documentation.md) for architecture, trust boundaries, packet construction, host routes, installation, and maintenance.
- [Programming Loop component](../components/programming-loop/README.md) for standalone installation, host adapters, and extension guidance.
- [Repository README](../README.md) for the shortest start and package map.

## License

Vibe's first-party code, frameworks, and documentation are dedicated to the public domain under CC0 1.0 Universal. The vendored markdown-it copy retains its original MIT license; see the root `NOTICE.md`.
