# Ora Vibe Coder

Ora Vibe Coder is a local workspace for taking a software idea through a fixed route: Specification, Planning, Programming, and Verification, presented as three workspaces — **Specification → Plan → Build & verify**. You talk to your chosen coding tool inside the app — one **Send** delivers text and images through the bundled Agent Bridge, while your project documents stay visible beside the conversation and refresh as they change. A complete portable Markdown handoff remains available for terminal recovery and external recipients.

Vibe is useful when you want AI help without turning a pile of chats into the project record. Your ordinary Markdown files and source repository remain the durable work. The application does not run an agent service, store credentials, choose a model, upload a project, or declare a stage complete because a window opened. The selected coding tool still owns login, model choice, permissions, and execution; Vibe calls it as an ordinary local command through Bridge. A simple question does not need a Specification; ask it in the project conversation.

## What you get

- A browser workspace that runs only on your computer at a loopback address.
- An in-project conversation with your selected coding tool: one **Send** submits text and images together, your message is saved before it is shown, and the complete answer appears when the turn finishes — working status, no streaming. Enter sends; Shift+Enter inserts a newline.
- A resizable split between the conversation and your documents — side-by-side or stacked, either pane expandable — with saved files refreshed automatically as they change on disk, preserving your selection and reading position.
- Turn records retained under the project's reserved `.vibe/` folder: the exact message, image originals, and the published replies, reopened with the last five completed exchanges as context.
- Automatic Registry maintenance: each ordinary turn's reply may carry one validated Registry update the app applies atomically; unresolved proposals are resupplied to later turns until applied, with an honest unsaved-update notice whenever nothing was written.
- Three workspaces backed by four portable methods: deciding what to build, deciding how, implementing it, and independently verifying it. Every stage stays available whatever state the documents are in.
- Automatic project discovery: startup searches your Documents folder for projects with a `Project.md` definition, at any depth, with archived projects kept out of the way until you ask for them.
- Automatic document discovery and a complete project-document reader: opening an ordinary folder lists its saved Markdown documents, defaulting Build & verify to the current Verification Report.
- Prominent completeness display for Specification and Plan: the saved assessment — COMPLETE, INCOMPLETE with its noted deficiencies, or NOT REVIEWED — shown centered in the document pane header, just above the document, clickable to the findings.
- Read-only Markdown panes; revisions, assessments, and results are saved by the AI in the conversation or your editor and appear as the panes refresh.
- A visible repository / code folder: the conversation and assignments name it; documents and code may live in different places.
- Optional intake of existing material: selected files are named in assignments for AI to organize into the Registry, Specification, or Plan.
- A portable handoff panel in every workspace: complete, inspectable `Handoff.md` packets that start with your exact request, for terminal recovery and any external recipient.
- Continue routes for Codex, Claude Code, ZCode, Hermes, Qwen Code, and MiniMax Code.
- Copy-and-paste delivery for any compatible recipient.
- A portable Programming Loop with fresh executor and reviewer contexts, offered as one structured method.
- A second-opinion review pipeline in Specification and Plan: the authoring model assesses, a second harness of your choice evaluates, and the author revises — optionally iterating to agreement, at most three rounds, with any residual disagreement reported and you breaking the ties.
- Explicit status reporting from project documents rather than inferred chat activity.
- Desktop launch on macOS and Windows without a terminal that must stay open; the existing Linux route is preserved.

## Start here

You need Python 3.10 or later, a modern browser, and at least one supported coding tool if you want to use Continue. Copy remains available without a detected tool.

Open the downloaded release folder and start the supplied setup:

- on macOS, double-click `Install Ora Vibe Coder.command`;
- on Windows, double-click `Install Ora Vibe Coder.cmd`; or
- on Linux, open `install.py` with Python (or run `python3 install.py` if the desktop does not offer that action).

The setup page shows the six supported coding tools. Select the ones you use, then choose **Install or update Vibe and selected entries**. Setup installs the Vibe entries and Programming Loop for those selected hosts, places the bundled Agent Bridge runtime beside the application, and creates a launcher named **Ora Vibe Coder** — an application in your personal Applications folder on macOS, a desktop shortcut on Windows, and the existing desktop entry on Linux. It does not install the coding tools themselves. When setup finishes, close the installer and open the new launcher; you should not need a terminal command for normal use.

Specification and Planning work well with the separately installed Gear 3 and Gear 4 companion and use it when available; it is optional, and Vibe setup does not install it. Agent Bridge is bundled with Vibe and runs the in-app conversation through your selected coding tool; you never install or configure Bridge separately.

On first use:

1. Open the launcher. Vibe searches your Documents folder and its descendants automatically for files named `Project.md`; each folder that contains one is one project. A definition directly in Documents counts, and discovery continues beneath a project, including archived ones. No folder needs to be selected first, and discovery reads only the definitions — it creates nothing and does not open your stage documents. If Documents itself is unavailable, Vibe says so instead of searching elsewhere; **Refresh projects**, in **Open existing**, repeats the search during a session.
2. Choose a project from **Choose a project**, open a recent folder, browse to an existing directory, or choose **New project**. Subprojects display as **Parent → Project name** with their complete lineage; **Show archived projects** adds archived projects, clearly marked, when you need one — opening an archived project does not reactivate it. Opening a folder creates no files; the last project and workspace reopen with an empty instruction box, but never an archived project while the archive toggle is off.
3. Read the discovered documents. Vibe finds each document automatically — a deliberate link first, then the expected filename, a `vibe_document` type label, then recognizable role words such as spec or plan in the filename, newest within a rank — and shows which file it chose. A deliberate association saved in the project information overrides any selection.
4. Pick the workspace that matches the next result you need: **Specification**, **Plan**, or **Build & verify**.
5. Write your message, attach images if any, and press **Send** (or Enter). Your message is saved before it is shown; the selected coding tool then works through the bundled Bridge, a compact status is displayed while the turn runs, and the complete answer appears when it finishes — no streaming. AI questions arrive in the same conversation and are answered there; one work turn runs per project at a time, while reading files and switching projects stay available.
6. **Review stage** can run a second opinion (Specification and Plan): the authoring model assesses, a second harness of your choice evaluates, and the author revises — optionally iterating to agreement, at most three rounds. The interface states lab diversity honestly — different labs, same lab, or unconfirmed when the passes did not report their actual model/provider identity — and reports any disagreement that remains; you break the ties.
7. The portable handoff panel below the composer keeps the terminal route: **Prepare request** saves a complete `Handoff.md`, then **Continue in the selected tool** or **Copy full Markdown** delivers it. In the coding tool, follow the method through its named result and save that result in the project folder; the document pane shows it as the files change. Every stage stays available throughout; assessments and reports are information, never gates.

Sending saves the durable turn record under the project's `.vibe/` folder before dispatch. Preparing a portable packet saves a complete snapshot to the project's `Handoff.md`; it does not send the request. Continue asks the selected local coding tool to open the exact saved snapshot, but Vibe cannot claim receipt or execution; the new coding-tool window owns that conversation and its normal approvals.

**Source and maintainer fallback:** from a repository checkout, `python3 -m ora_vibe_coder` starts the local server directly. Keep that terminal open and use its printed local URL if the browser does not open. This bypasses the normal per-user installation and created launcher; it is not the ordinary first-use route.

For the full walkthrough, recovery help, and document-role guide, read [User Guide](docs/User%20Guide.md).

## The three workspaces

Four portable methods sit behind three workspaces. Implementation and independent Verification share one display area while keeping separate responsibilities and results.

| Workspace | Methods used | Use it for | Main retained result |
|---|---|---|---|
| Specification | Specification | Define the product, users, behavior, boundaries, and observable success. | Current Specification and its saved assessment |
| Plan | Planning | Inspect the project and choose one executable implementation approach. | Current Plan and its saved assessment |
| Build & verify | Programming and Verification | Implement the available outcome with protected state, exact checks, and independent review; then inspect the whole candidate independently. | Working candidate, Programming Result, and a truthful Verification Report |

Each of Specification and Plan offers a **Review stage** action. It can run an in-app second opinion: the authoring model writes a fresh assessment, a second harness you choose evaluates it, and the author revises its own output given the evaluation as a guide — a three-pass pipeline that can iterate to agreement (at most three evaluate→revise rounds, then any residual disagreement is reported and you break the ties; one second opinion costs three model calls, full iteration up to seven). It can instead prepare a portable request for an external reviewer. The saved verdict — COMPLETE or INCOMPLETE with its noted deficiencies, or NOT REVIEWED when none exists — is displayed prominently and never blocks anything. A later change to the assessed document identifies the assessment as applying to an earlier version, still without blocking. In Build & verify, **Review stage** requests current independent Verification and **Prepare correction** carries actual findings and governing scope back through the Programming controller.

## Project files

Vibe works with normal Markdown files in the folder you open. A new project creates a folder containing `Project.md`, `Registry.md`, `Specification.md`, and `Plan.md` from minimal starter templates — project identification and useful empty headings, with no invented requirements, sample decisions, approvals, or review results. Untouched templates show **Not started**. The five standard working documents are:

```text
Project.md
Handoff.md
Registry.md
Specification.md
Plan.md
Programming Result    saved after actual programming work, including work that stops unfinished
Verification Report   saved after actual verification — passing, failing, or incomplete
```

Beside them, each project's reserved `.vibe/` folder retains the conversation itself: one folder per submitted turn holding the exact user note, the original image bytes, the Bridge session records, and the post-turn outcome — including any unapplied Registry maintenance. The display conversation and each fresh call's context (the current Registry plus the last five completed exchanges) are derived from these records alone; there is no second transcript or index, and the folder is excluded from project discovery so retained records never create false projects.

These documents are working aids; their presence or completion is never a prerequisite for using a stage. Older documents under names such as `<Project Name> — 01 Request.md` through `<Project Name> — 07 Report.md` remain recognized where they exist, without migration or cleanup. `Project.md` remains the project definition file and `Handoff.md` the prepared assignment.

The names are defaults, not prerequisites. Existing documents keep their names: discovery prefers a deliberate link, then the expected filename, then a scalar `vibe_document` type label in closed opening frontmatter (for example `vibe_document: specification`) or ordinary opening metadata, then recognizable role words in the filename; among equally ranked candidates the most recently modified file wins. A file that names conflicting roles is never selected — Vibe shows the conflict and leaves the correction to external edits, while the document reader keeps every readable document available. `Project.md`, the outgoing `Handoff.md` (including recognized renamed copies), and documents that carry duplicate type labels are excluded from discovery, and Code, Checks, and Baseline stay deliberate selections. Discovery identifies a document; it never proves approval or completion.

Stage Markdown is read-only in Vibe. The AI in the conversation or your own editor saves revisions, assessments, and results; Vibe deliberately saves only project information and associations, the Registry maintenance blocks its own turns validate, and the outgoing `Handoff.md`. Saved changes appear as the document panes refresh automatically. A Specification or Plan document's `Current review` section holds the saved assessment — `Stage`, `Verdict` (COMPLETE or INCOMPLETE), `Basis`, and the noted deficiencies as a list; Vibe displays that verdict prominently with the deficiency count, and a document that changed since the assessment identifies it as applying to an earlier version. None of this ever blocks a stage.

`Project.md` contains the project name, an optional Parent display lineage, the active/archived state (`Project state: ACTIVE` or `ARCHIVED`; a missing state means active), the project description, desired outcome, document associations, the repository / code folder, and the separately reported Programming field; a retained Verification field is legacy history that does not override the saved Verification Report. Parent is human-readable display text such as `Ora → Experts`, not a filesystem path; moving or renaming folders does not rewrite it. `Handoff.md` is one current outgoing snapshot. It is not a requirements authority and is deliberately excluded as an input to the next packet so handoffs never nest recursively.

## Honest delivery boundaries

A submitted message is saved to the `.vibe/` records before it is displayed as sent, and the complete reply replaces the working status only when the turn finishes — there is no live output streaming, and process life is never proof of model progress. Elapsed time and the time since the last Bridge contact are shown; lost contact or a failure replaces a stale status, while slowness alone is not failure. The reply's Registry maintenance block is validated against the app-selected Registry before anything is applied; a missing, malformed, stale, or conflicting block preserves the document and the answer with an unsaved-update notice, and the proposal stays supplied to later turns until applied or resolved. No new information means no rewrite.

For sign-in or native-permission requirements, the failure names its own reason and offers the selected tool's normal terminal route through the portable handoff; recheck readiness after resolving it. Vibe preserves native permissions, adds no in-app permission framework, and does not label every error a login failure or automatically retry consequential work.

The portable route keeps its old guarantee: Vibe prepares and displays text before delivery. The displayed packet, saved `Handoff.md`, and copied Markdown must match. If the saved file changes after preparation, Vibe shows the conflict and requires another deliberate Prepare or Copy action rather than overwriting unseen work.

Continue is a convenience route into a normal interactive coding-tool session. It does not install that tool, log in, select a model, grant permissions, bypass repository rules, or monitor the resulting work. Host and account combinations are described as implemented but live qualification is separate. When Continue is unavailable, the complete saved Markdown and manual Copy route remain usable.

No stage status is inferred from opening, preparing, copying, launching, or process exit. Specification and Planning status come from one recognized `Status` field in their resolved documents; their completeness display comes from the saved Current review assessment. The displayed verification verdict comes from the saved current Verification Report; without one, Build & verify shows "No saved verification result yet." A saved verdict describes the inspected implementation — neither a report's existence nor an older passing result proves that newer code passed. Missing, duplicate, or unfamiliar values remain unreported rather than being guessed.

## Quitting and desktop launch

On macOS and Windows, the ordinary app icon opens Vibe in your normal browser without a Terminal or command window that must stay open; reopening returns to the running workspace instead of starting a second copy. Closing the browser leaves Vibe and external AI work running. **Stop Vibe** — and normal Mac app Quit from the Dock or Command-Q — finishes the in-flight conversation turn within its deadline, saving its reply, Registry maintenance, and records before ending Vibe's own processes; no extra AI call occurs on quit. They warn with **Cancel / Quit anyway** only when a text box contains unsent text; empty input quits without that warning. After closing the browser on Windows, reopen the desktop shortcut and use Stop Vibe. The browser's own tab-close warning is preserved and saves nothing.

Launch failures are shown as actionable dialogs without a console. When the browser does not open, Vibe shows the local address to open manually. The Windows launcher and desktop shortcut are delivered and covered by focused unit checks that run on macOS with the Windows shell faked, but no native Windows qualification has been performed; the existing Linux launch route is preserved without new desktop-launch claims for it.

The footer shows the running version. **Check for updates** is deliberate and reports the current state: in this build update lookup is not connected, so a check reports unavailable and installs, replaces, or downgrades nothing.

## Installation, updates, and removal

For normal installation, use the supplied platform setup described in **Start here**, select the coding tools to configure, and open the launcher it creates. To update, first stop the running app (**Stop Vibe**), then reopen the same supplied setup from the new release, select the hosts whose entries should be updated, and choose **Install or update Vibe and selected entries**. Restart those coding tools afterward so they reload the installed Vibe and Programming Loop entries.

Maintainers can invoke the same shared installer from Python:

```sh
python3 -m ora_vibe_coder.installer install --host codex
```

Repeat `--host` to select more than one supported coding tool. Installation copies the local application, launcher, selected Vibe entries, and the matching resources from Vibe's bundled Programming Loop product-file snapshot, and places the bundled Agent Bridge runtime beside the application (never inside every skill directory) so the in-app conversation runs on the interpreter already running Vibe. It validates source files and uses transactional replacement so a failed update preserves the prior installation.

For normal removal, stop the installed app, reopen that same supplied setup, select the hosts whose Vibe and Programming Loop entries should be removed, and choose **Remove Vibe and selected entries**. The equivalent maintainer command is:

```sh
python3 -m ora_vibe_coder.installer remove --host codex
```

Read the installer result for any retained user-owned additions. Do not delete retained paths merely to make removal look complete.

## Programming Loop

Programming Loop is maintained in the dedicated private source repository `Golfplan18/ora-programming-loop` and released publicly as `ora-commons/ora-programming-loop`. Ordinary users do not need the private repository: Vibe setup installs or updates the bundled product-file snapshot, and standalone users can install from the public Loop release.

For offline installation, Vibe vendors the 17 reviewed Programming Loop product files at [`components/programming-loop`](components/programming-loop). Their bytes, executable modes, and nested paths match the corresponding files in the public release; that release separately carries `.ora-public-release-manifest.json` as delivery metadata. `scripts/assemble_resources.py` generates the plugin resource copy from the vendored files and writes exact file hashes plus the authoritative repository, public release repository, source revision, source tree, and vendored path to `SOURCE.json`. Before replacing resources, it calculates the product-files Git tree and requires the reviewed tree identity. Handoff preparation repeats that tree check instead of trusting the generated hashes alone. Neither Vibe location is an independently maintained Loop source.

Maintainers refresh the snapshot by manually replacing its 17 files with one reviewed checkout of the authoritative repository, updating the `AUTHORITY` revision and tree in the single metadata owner `ora_vibe_coder/loop_integrity.py`, and running `python3 scripts/assemble_resources.py --loop-source components/programming-loop`. Review the import and generated diff together; no synchronizer is involved. The vendored standalone README identifies `Golfplan18/ora-programming-loop` as the sole authoritative source and `ora-commons/ora-programming-loop` as the public source and update route.

The Loop coordinates one fresh executor and a different fresh reviewer. It protects the starting repository, runs only agreed checks, corrects material defects, and reaches only the delivery endpoint the user approved. It uses conversation, working tree, Git, and check output as evidence; it creates no run database or hidden agent service.

The initiating host determines the adapter. A model or service selected as an optional review target does not change the dispatcher adapter. No adapter authorizes a provider call or a paid fallback.

See the vendored copy of the public Loop [`README.md`](components/programming-loop/README.md) for standalone installation and extension guidance.

## Agent Bridge

Agent Bridge is the small local runtime that carries Vibe's conversation turns to your selected coding tool as ordinary command-line calls — no shells, no service, no credentials. Vibe bundles the reviewed Bridge runtime once and calls it as a foreground subprocess on the interpreter already running Vibe. The application resolves its copy beside the installed application first; a repository-checkout run falls back to the vendored component in that checkout, and a run with no bundled copy reports the missing runtime honestly instead of guessing another location.

The runtime is authored and released publicly at `ora-commons/agent-bridge`. Vibe vendors the 19 reviewed runtime files — the `bridge/` Python package plus its license, notice, and README — at [`components/agent-bridge`](components/agent-bridge), pinned in the same metadata owner as the Loop (`ora_vibe_coder/loop_integrity.py`) by source revision, a Git tree identity over the exact files and modes, and the vendored path. The installer verifies that tree before replacing anything, installs the one copy beside the application, and removes it with the application. Maintainers refresh it exactly like the Loop: replace the 19 files from one reviewed checkout, update the `BRIDGE_AUTHORITY` revision and tree, and reinstall.

The second-opinion pipeline's instructions are vendored text, not a runtime, pinned beside the app in `ora_vibe_coder/reliability.py`: a constitution and standing-rules preamble adapted from Ora's injected behavioral preamble, the shared-criteria pattern supplied identically to author, evaluator, and reviser, and the evaluate/revise scaffolds adapted from Ora's F-Evaluate and F-Revise frameworks (web verification omitted; unverifiable externals surface as uncertainties). The pinned sources — revision `526a7379…` of `/Users/oracle/ora` with per-file SHA-256 digests — are recorded with the texts so any future change has a documented migration path.

## Documentation

- [User Guide](docs/User%20Guide.md) — setup, normal use, document linking, delivery, recovery, stopping, and removal.
- [Technical Documentation](docs/Technical%20Documentation.md) — architecture, conversation runtime, trust boundaries, packet construction, storage, host routes, installation, tests, and maintenance.
- [Product Overview](docs/Product%20Overview.md) — who Vibe is for, the problem it solves, benefits, limits, prerequisites, and expected results.

These documents describe the active local product. They do not contain provider credentials, private operating policy, implementation history, internal review transcripts, or future-roadmap promises.

## Development checks

Focused tests cover packet construction, document-role handling, generated Programming Loop parity, host-specific inclusion, installer transactions, the conversation lifecycle, and the local application boundary. Tests use temporary directories and fake Bridge and host operations; they do not call live models or certify third-party subscriptions.

Run only the checks appropriate to the surface you change. The repository's task instructions may set a narrower testing ceiling; follow that ceiling instead of automatically running every test or build.

## Safety and privacy

The browser server binds to `127.0.0.1`, validates local origins and navigation, and keeps its launch record in user-local settings. Your project files remain ordinary local files. Continue creates a short-lived, permission-restricted assignment copy for the receiving terminal and cleans it after the coding tool exits.

Vibe does not scan a project for secrets or decide what may be shared. What you send in the conversation — text and image pixels alike — goes to the selected coding tool under that tool's own privacy, provider, and permission settings; the retained `.vibe/` records stay local. For the portable route, review the complete prepared Markdown before copying or continuing — only explicitly selected material is embedded, and unreadable or unselected files are named rather than silently included.

## License

First-party material is dedicated to the public domain under CC0 1.0 Universal. The vendored markdown-it copy retains its MIT license. See [`LICENSE`](LICENSE) and [`NOTICE.md`](NOTICE.md).
