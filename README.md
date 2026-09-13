# Ora Vibe Coder

Ora Vibe Coder is a local workspace for taking a software idea through four clear stages: Specification, Planning, Programming, and Verification. It prepares complete Markdown assignments for the coding tool you choose, keeps your project documents visible, and leaves conversation, login, approval, and execution inside that tool.

Vibe is useful when you want AI help without turning a pile of chats into the project record. Your ordinary Markdown files and source repository remain the durable work. The application does not run an agent service, store credentials, choose a model, upload a project, or declare a stage complete because a window opened.

## What you get

- A browser workspace that runs only on your computer at a loopback address.
- Four reusable methods for deciding what to build, deciding how, implementing it, and independently verifying it.
- A guided entry when you are unsure which stage your project needs next.
- Complete, inspectable `Handoff.md` packets that start with your exact request.
- Continue routes for Codex, Claude Code, ZCode, Hermes, Qwen Code, and MiniMax Code.
- Copy-and-paste delivery for any compatible recipient.
- A portable Programming Loop with fresh executor and reviewer contexts.
- Explicit status reporting from project documents rather than inferred chat activity.

## Start here

You need Python 3.10 or later, a modern browser, and at least one supported coding tool if you want to use Continue. Copy remains available without a detected tool.

Open the downloaded release folder and start the supplied setup:

- on macOS, double-click `Install Ora Vibe Coder.command`;
- on Windows, double-click `Install Ora Vibe Coder.cmd`; or
- on Linux, open `install.py` with Python (or run `python3 install.py` if the desktop does not offer that action).

The setup page shows the six supported coding tools. Select the ones you use, then choose **Install or update Vibe and selected entries**. Setup installs the Vibe entries and Programming Loop for those selected hosts and creates a launcher named **Ora Vibe Coder**. It does not install the coding tools themselves. When setup finishes, close the installer and open the new launcher; you should not need a terminal command for normal use.

Specification and Planning also require the separately installed Gear 3 and Gear 4 companion. Install or update Gear through that product's own instructions before using either stage; Vibe setup does not install it. Agent Bridge is optional and is needed only for an explicitly selected external-review route.

On first use:

1. Choose an existing folder that will contain or identify your projects.
2. Open an existing project directory or choose **New project**.
3. Link existing documents to their roles with **Link documents / edit**.
4. Pick the stage that matches the next result you need.
5. Write your instruction, choose a coding tool, and select **Prepare request**.
6. Read the prepared assignment, then choose **Continue** or **Copy full Markdown**.
7. In the coding tool, follow the stage through its named result and save that result in the project. Return to Vibe and choose **Refresh files** to read it. Specification and Planning finish only after you explicitly approve their complete documents; Verification creates a Report only after PASS.

Preparing saves a complete snapshot to the project's `Handoff.md`. It does not send the request. Continue asks the selected local coding tool to open the exact saved snapshot, but Vibe cannot claim receipt or execution; the new coding-tool window owns that conversation and its normal approvals.

**Source and maintainer fallback:** from a repository checkout, `python3 -m ora_vibe_coder` starts the local server directly. Keep that terminal open and use its printed local URL if the browser does not open. This bypasses the normal per-user installation and created launcher; it is not the ordinary first-use route.

For the full walkthrough, recovery help, and document-role guide, read [User Guide](docs/User%20Guide.md).

## The four stages

| Stage | Use it for | Main retained result |
|---|---|---|
| Specification | Define the product, users, behavior, boundaries, and observable success. | Request and approved Specification |
| Planning | Inspect the project and choose one executable implementation approach. | Approved Implementation Plan |
| Programming | Implement the approved outcome with protected state, exact checks, and independent review. | Working candidate and truthful documentation |
| Verification | Independently inspect the whole candidate against the approved requirements. | Findings, or a Report only after PASS |

**Help me get started** packages the same four methods for guided use. It does not silently run every stage. The receiving coding tool determines the earliest useful stage from the evidence and asks for approval where the method requires it.

## Project files

Vibe works with normal files in the directory you select. A managed project may use these defaults:

```text
Project.md
Handoff.md
<Project Name> — 01 Request.md
<Project Name> — 02 Specification.md
<Project Name> — 03 Implementation Plan.md
<Project Name> — 04 User Guide.md
<Project Name> — 05 Technical Documentation.md
<Project Name> — 06 Product Overview.md
<Project Name> — 07 Report.md
```

The names are defaults, not prerequisites for direct use. Existing documents can be linked to roles without renaming them. Vibe distinguishes an unlinked role from a linked file that is missing, and it never silently chooses among colliding files.

`Project.md` contains the project description, goals, document associations, and the separately reported Programming and Verification fields. `Handoff.md` is one current outgoing snapshot. It is not a requirements authority and is deliberately excluded as an input to the next packet so handoffs never nest recursively.

## Honest delivery boundaries

Vibe prepares and displays text before delivery. The displayed packet, saved `Handoff.md`, and copied Markdown must match. If the saved file changes after preparation, Vibe shows the conflict and requires another deliberate Prepare or Copy action rather than overwriting unseen work.

Continue is a convenience route into a normal interactive coding-tool session. It does not install that tool, log in, select a model, grant permissions, bypass repository rules, or monitor the resulting work. Host and account combinations are described as implemented but live qualification is separate. When Continue is unavailable, the complete saved Markdown and manual Copy route remain usable.

No stage status is inferred from opening, preparing, copying, launching, or process exit. Specification and Planning status come from one recognized `Status` field in their associated documents. Programming and Verification status come from their named fields in `Project.md`. Missing, duplicate, or unfamiliar values remain unreported rather than being guessed.

## Installation, updates, and removal

For normal installation, use the supplied platform setup described in **Start here**, select the coding tools to configure, and open the launcher it creates. To update, first choose **Stop app**, then reopen the same supplied setup from the new release, select the hosts whose entries should be updated, and choose **Install or update Vibe and selected entries**. Restart those coding tools afterward so they reload the installed Vibe and Programming Loop entries.

Maintainers can invoke the same shared installer from Python:

```sh
python3 -m ora_vibe_coder.installer install --host codex
```

Repeat `--host` to select more than one supported coding tool. Installation copies the local application, launcher, selected Vibe entries, and the matching Programming Loop resources. It validates source files and uses transactional replacement so a failed update preserves the prior installation.

For normal removal, stop the installed app, reopen that same supplied setup, select the hosts whose Vibe and Programming Loop entries should be removed, and choose **Remove Vibe and selected entries**. The equivalent maintainer command is:

```sh
python3 -m ora_vibe_coder.installer remove --host codex
```

Read the installer result for any retained user-owned additions. Do not delete retained paths merely to make removal look complete.

## Programming Loop

The canonical portable component is at [`components/programming-loop`](components/programming-loop). It contains one universal workflow and six small initiating-host adapters. Its plugin resource copy is generated by `scripts/assemble_resources.py` and carries a `SOURCE.json` map of exact source hashes.

The Loop coordinates one fresh executor and a different fresh reviewer. It protects the starting repository, runs only agreed checks, corrects material defects, and reaches only the delivery endpoint the user approved. It uses conversation, working tree, Git, and check output as evidence; it creates no run database or hidden agent service.

The initiating host determines the adapter. A model or service selected as an optional review target does not change the dispatcher adapter. No adapter authorizes a provider call or a paid fallback.

See the component's own [`README.md`](components/programming-loop/README.md) for standalone installation and extension guidance.

## Documentation

- [User Guide](docs/User%20Guide.md) — setup, normal use, document linking, delivery, recovery, stopping, and removal.
- [Technical Documentation](docs/Technical%20Documentation.md) — architecture, trust boundaries, packet construction, storage, host routes, installation, tests, and maintenance.
- [Product Overview](docs/Product%20Overview.md) — who Vibe is for, the problem it solves, benefits, limits, prerequisites, and expected results.

These documents describe the active local product. They do not contain provider credentials, private operating policy, implementation history, internal review transcripts, or future-roadmap promises.

## Development checks

Focused tests cover packet construction, document-role handling, generated Programming Loop parity, host-specific inclusion, installer transactions, and the local application boundary. Tests use temporary directories and fake host operations; they do not call live models or certify third-party subscriptions.

Run only the checks appropriate to the surface you change. The repository's task instructions may set a narrower testing ceiling; follow that ceiling instead of automatically running every test or build.

## Safety and privacy

The browser server binds to `127.0.0.1`, validates local origins and navigation, and keeps its launch record in user-local settings. Your project files remain ordinary local files. Continue creates a short-lived, permission-restricted assignment copy for the receiving terminal and cleans it after the coding tool exits.

Vibe does not scan a project for secrets or decide what may be shared. Review the complete prepared Markdown before copying or continuing, use the reference-only controls for material that should not be embedded, and follow the selected coding tool's privacy and permission settings.

## License

First-party material is dedicated to the public domain under CC0 1.0 Universal. The vendored markdown-it copy retains its MIT license. See [`LICENSE`](LICENSE) and [`NOTICE.md`](NOTICE.md).
