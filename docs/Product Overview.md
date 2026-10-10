# Ora Vibe Coder Product Overview

Ora Vibe Coder is for people who want to build software with an AI coding tool while keeping the project understandable and under deliberate control. It turns an idea or existing project into a sequence of clear, inspectable stages: define the product, plan the implementation, build it with independent review, and verify the complete result — presented as three workspaces, Specification, Plan, and Build & verify. You talk to your coding tool inside Vibe — the button naming your tool and stage delivers your message through the bundled Agent Bridge while your documents stay visible beside the conversation — and a complete portable Markdown handoff remains available for terminal recovery and external recipients. Vibe runs locally; your chosen coding tool still owns login, permissions, model use, and execution.

## The problem it solves

AI coding work often begins easily and becomes hard to govern. Product decisions get mixed with technical choices. Important constraints live in old chats. A new session cannot tell which version is current. “The model ran” gets mistaken for “the product is finished.” Reviews see a summary instead of the real candidate. A useful result can remain on a branch or in an unused document. Vibe addresses that problem with a small set of durable boundaries:

- your projects are found automatically in the configured projects folder, or Documents when none is configured, through their own `Project.md` definition, and current requirements and plans live in ordinary project documents, found automatically when you open the folder;
- each workspace has one clear purpose backed by a portable method;
- your exact message is saved before it is shown, and your exact instruction appears before framework text in every prepared packet;
- the conversation, documents, and results sit in one resizable split that refreshes as files change;
- execution and review use separate contexts, and assessment verdicts are recorded separately from your own acceptance;
- status comes from explicit fields, not inferred activity; and
- sending, launch, receipt, execution, review, approval, and delivery remain distinct facts.

The goal is not more process. The goal is less hidden judgment and less confusion about what actually happened.
## Who it is for

### People with an idea but no technical plan

Start in the Specification workspace. The method helps turn intent into observable behavior and boundaries without requiring you to choose frameworks, code structure, or infrastructure prematurely. A simple question does not need a Specification at all — ask it in the project conversation.
### Project owners with an existing codebase

Open the directory; Vibe finds its Markdown documents automatically and shows which file it chose, with a manual override. Vibe does not require renaming files or migrating the repository into a proprietary project format.
### Developers using several coding tools

The same Vibe methods can prepare work for Codex, Claude Code, ZCode, Hermes, Qwen Code, or MiniMax Code. Host-specific mechanics stay in small adapters; every host receives the same reviewed Programming Loop method plus its matching adapter from the vendored product files.
### Teams that need an inspectable handoff

`Handoff.md` is a complete current snapshot that can be reviewed, copied, versioned, or delivered manually. It starts with the exact user request and labels instructions, project facts, source material, authority, and expected output.

## The product in one flow

```text
Idea or current project
        ↓
Specification workspace — decide WHAT the product must be
        ↓  (optional Review this document assessment: COMPLETE / INCOMPLETE)
Plan workspace — inspect the project and decide HOW to build it
        ↓  (optional Review this document assessment: COMPLETE / INCOMPLETE)
Build & verify workspace — implement, check, review, correct, and deliver
        ↓
Verification — independently inspect the accessible candidate
        ↓
Verification Report — saved for passing, failing, and incomplete reviews alike
```

Every stage stays available throughout: you may create a Plan with an incomplete or missing Specification, start programming with an incomplete or missing Plan, and request verification with whatever evidence exists. A project can begin at whichever workspace its current evidence needs, and existing requirements never need to be recreated. The conversation is available in every workspace. **Review this document** in Specification and Plan starts a fresh assessment only when you request it, with an optional second opinion; its saved verdict informs your decision. **Before implementation** advises you when either document lacks a current COMPLETE review, and **Continue with implementation** remains available.

The screen numbers project choice, project details, coding tool, and AI work as steps 1–4. Specification and Plan add review and next-stage preparation as steps 5–6; Build & verify instead adds Programming Result, independent verification, and correction as steps 5–7. Conversation and document panes sit side by side with a draggable divider, or switch through **Show document** and **Show conversation** on a narrow screen.
## What makes it different

### Conversation inside the workspace

The coding tool works through the bundled Agent Bridge inside Vibe: **Ask [tool] to work on [stage]** submits text, up to ten pictures, and up to ten selected Markdown or text files for this message only. The originals stay in place. The message is saved before it is shown, and the complete answer appears when the turn finishes — honest working status, no streaming. Successful completion is plain, Bridge diagnostics that need no action sit under collapsed Technical details, and failures or write problems remain visible. The turn records live under the project's `.vibe/` folder and are reopened with the current Registry plus the last five completed exchanges; each ordinary turn may also carry one validated Registry update the app applies or honestly reports as unapplied. The tool's own login, model, permissions, and approvals are untouched.
### Local and file-based

Vibe's browser workspace is served from your computer and opens from a normal desktop launcher on macOS without a terminal that must stay open. Windows and Linux routes are supplied but remain untested on those platforms. Projects remain normal directories in the configured projects folder, or Documents when none is configured, found through their own `Project.md` definition rather than imported into a library. Requirements, plans, guides, and reports remain Markdown. There is no hosted project database or proprietary run record to export later.
### Preparation before delivery

For the portable route, the complete packet is saved and displayed before Continue or Copy; if the saved file changes, Vibe refuses to copy unseen content. For the in-app route, the parallel guarantee is durability and honesty: the message is saved before it is shown, the answer appears only when complete, and the Registry is rewritten only by a validated block. Nothing is sent, claimed, or applied behind your back.
### One method, several hosts

The Programming Loop has one universal workflow maintained in its dedicated source and published through its public release. Vibe bundles the matching 17 product files and modes for offline setup and handoffs; the public release separately includes its delivery manifest. Each initiating host gets only the instructions needed to create a fresh worker, retrieve its result, and wait safely. This avoids six drifting versions of what “implement and review” means without turning the Vibe snapshot into another maintained source.
### Independent review is structural

The Loop creates a fresh executor, then a different fresh reviewer that receives the available plan, real cumulative diff, repository access, and exact check evidence. It does not receive the executor's conversation or intended conclusions. Specification and Plan documents carry their own Current review assessment, so a technical verdict and your own acceptance never blur into one fact. The Loop is offered as one structured method; without it, the implementing tool works directly under its normal approvals.

### Truthful stopping

A prepared packet is not a sent packet. A launched window is not receipt. Process exit is not completion. Reviewer transport is not reviewer agreement. A Verification Report is saved for every actual verification outcome — passing, failing, and incomplete reviews alike — and an older Report is previous evidence, never proof that newer code passed. These distinctions keep confidence proportional to evidence.

## Typical uses

### Shape a new application

Use Specification to clarify intended users, visible workflows, data treatment, failures, and success. Use Planning to inspect the chosen environment and produce an executable route. Programming then builds the candidate and its real reader documentation. Verification judges the whole result.

### Add a bounded feature

With the product requirement and plan in place, state the feature outcome and protected work, and hand it to Programming in Build & verify. The Loop proposes a small scope lock, uses exact relevant checks, and keeps unrelated repository changes out of the task.

### Recover a stalled AI coding task

Open the actual repository and current documents. Vibe's packet can state the preserved branch, incomplete diff, check evidence, findings, and next owner. The recipient resumes from real artifacts instead of a reconstructed chat summary.

### Audit a completed candidate

Use Verification with accessible requirements, implementation, documentation, and checks. The verifier reports material findings with evidence and the smallest correction, and saves a truthful Verification Report — for passing, failing, and incomplete reviews alike. Missing formal documents alone are not a failure: the report states what can be checked and what cannot be established.

### Move a prepared task between tools

Use Copy to deliver the same complete Markdown to a different capable recipient. Be explicit about access: a path on one machine is not evidence available to a remote session.

## Benefits

### For the project owner

- Consequential product decisions remain visible and yours.
- You see what will be sent before a tool receives it.
- Assessment verdicts and your own acceptance are recorded separately, and neither ever blocks a stage.
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
- The Programming Loop has one authoritative source and public release; Vibe's component subtree and generated resources contain the same 17 product files and modes as that release, whose delivery manifest remains separate.
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

Vibe requires Python 3.10 or later, a browser, and filesystem access to the configured projects folder, or Documents when none is configured. The conversation and prepared request delivery additionally require a supported coding-tool executable; the Terminal route needs a desktop terminal, while Copy works when it is unavailable.

Desktop launch works from the app icon on macOS without a terminal that must stay open. The Windows shortcut is delivered and covered by focused unit checks using a faked Windows shell on macOS, but Windows is untested on Windows. The existing Linux launch route is untested on Linux. The footer's Check for updates contacts GitHub only when pressed — nothing checks in the background — and answers newer, same, ahead, or can't tell; a failed or rate-limited check is never reported as up to date, and nothing is downloaded or installed by it.

Ora AI Boost — Gear 3 and Gear 4 together — remains an optional, separately installed companion for Specification and Planning; Vibe setup does not install it, and every stage stays available without it — the methods state plainly when an optional aid was unavailable and continue the work directly. Its releases are at [ora-commons/ora-adversarial-review](https://github.com/ora-commons/ora-adversarial-review/releases/latest). The Programming Loop is bundled: Vibe setup installs or updates it from its bundled product-file snapshot for each coding tool the user selects, and it is offered as one structured method — without it, the implementing tool works directly under its normal approvals. The in-app conversation requires the bundled Agent Bridge runtime, which Vibe setup installs and updates beside the application and runs on the interpreter already running Vibe — no separate Bridge installation exists. A missing or mismatched bundled runtime disables the in-app conversation honestly; add Ora AI Boost from its releases when you want it, or rerun Vibe setup with the receiving host selected and restart that host to refresh the Loop. These ordinary update routes do not require access to the private authoritative repository.

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

Use Copy when you want the packet discipline without a native launch route. Use the standalone Programming Loop from its public `ora-commons/ora-programming-loop` release when requirements and a plan are already available and you do not need the local project workspace.

Do not use Vibe as a reason to share material a recipient should not receive. Its value is making the boundary inspectable so you can choose responsibly.

## A practical decision guide

- Choose **the project conversation** when the change is genuinely tiny, its desired result is already obvious, no important existing work is at risk, and independent review would add no material confidence. It is the ordinary route in every workspace; Vibe should reduce ambiguity, not manufacture ceremony.
- Choose the **Specification workspace** when two reasonable implementations could produce meaningfully different products, when users or permissions are unclear, when content or data treatment is unsettled, or when “done” cannot yet be observed. This keeps product choices out of the coder's hidden discretion.
- Choose the **Plan workspace** when the desired product is settled but the real repository, dependency choices, migration, checks, or delivery route require inspection. The Plan should make a fresh executor able to build without redesigning the solution.
- Choose **Build & verify** when the task has a usable outcome and implementation direction — or when you want to build ahead of complete documents and let the conversation surface what matters. The implementing tool still presents its scope, protects state, and obtains its normal approvals; proceeding on partial information never grants broader effects.
- Choose **Review this document** in Specification or Plan when you want a fresh assessment before deciding how to proceed. In Build & verify, step 6 requests current independent Verification. Without a saved Verification Report, its verdict shows **NOT VERIFIED**.
- Choose **manual Copy** when the coding tool is remote, unsupported, not detected, or should receive the packet through a channel you control. The same inspection benefit remains, but access and receipt must be stated honestly.
- Choose the **standalone Programming Loop** when you already have suitable requirements and a plan, do not need Vibe's local project reader, and want the executor/reviewer method installed directly in a supported initiating host.

## Further reading

- [User Guide](User%20Guide.md) for setup, ordinary use, document linking, delivery, recovery, stopping, and removal.
- [Technical Documentation](Technical%20Documentation.md) for architecture, trust boundaries, packet construction, host routes, installation, and maintenance.
- [Vendored Programming Loop README](../components/programming-loop/README.md) for the same standalone installation, host-adapter, and extension guidance published with the public Loop release.
- [Repository README](../README.md) for the shortest start and package map.

## License

Vibe's first-party code, frameworks, and documentation are dedicated to the public domain under CC0 1.0 Universal. The vendored markdown-it copy retains its original MIT license; see the root `NOTICE.md`.
