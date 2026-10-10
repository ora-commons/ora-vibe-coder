# Ora Vibe Coder User Guide

## What Vibe does

Ora Vibe Coder gives a software project one calm local workspace. You open an ordinary project folder, choose the workspace that matches the next result you need, write a message, and talk to your coding tool inside Vibe. The button names the chosen tool and stage; your documents stay beside the conversation and refresh as they change.

Vibe does not replace Codex, Claude Code, ZCode, Hermes, Qwen Code, or MiniMax Code. Those tools still own login, model choice, permissions, and actual work; Vibe calls yours through the bundled Agent Bridge as an ordinary local command and records what actually happened. Vibe prepares trustworthy context, shows your project's Markdown read-only, and records assessment and result facts that the documents themselves carry. A simple question does not need a Specification; ask it in the project conversation.

## Before you begin

This release is for the Mac; the Windows and Linux routes are supplied but untested on those systems. You need:

- a Mac with Python 3.10 or later — the python.org macOS installer provides it if your Mac has none, and you reopen setup after installing it;
- a modern browser; and
- at least one supported coding tool for the conversation and Continue, or any recipient that can accept Markdown if you use Copy.

Vibe itself does not require a provider key and never asks for one. If a coding tool needs login or a subscription, complete that through the coding tool's normal interface.

The companions have distinct installation boundaries. Ora AI Boost (Gear 3 and Gear 4) is an optional extra for Specification and Planning — Vibe works without it, setup does not install it, and its releases are at [ora-commons/ora-adversarial-review](https://github.com/ora-commons/ora-adversarial-review/releases/latest). Programming uses Vibe's bundled Programming Loop 1.0.3 product-file snapshot, which setup installs into each coding tool you select. Agent Bridge 1.2.0 is bundled with Vibe: setup places its reviewed runtime beside the application, and the in-app conversation runs on it without any separate Bridge installation. Setup installs these bundled files alone; no other repository is contacted.

Of the six coding tools, this release was exercised with Codex CLI (the Bridge walkthrough used Codex CLI 0.155.1 on macOS, and the release checks also use Codex). Claude Code, ZCode, Hermes, Qwen Code, and MiniMax Code are implemented but were not exercised for this release.

## Five-minute start

1. **Install Vibe and choose your coding tools.** Download the release zip from the release page and unzip it; the unzipped folder is the release folder. On macOS, double-click `Install Ora Vibe Coder.command`; on Windows, double-click `Install Ora Vibe Coder.cmd`; on Linux, open `install.py` with Python, or run `python3 install.py` if your desktop has no Python action. Windows setup and launch are supplied but untested on Windows; the existing Linux route is untested on Linux. The first time you open the macOS setup, macOS may warn that it cannot check the installer for malicious software: on macOS 15 and later, choose **Done** on that warning, then open **System Settings → Privacy & Security**, scroll to the notice about the blocked item, and choose **Open Anyway**, confirming once more; the Terminal alternative is to run `python3 install.py` in the unzipped folder. The setup page lists Codex, Claude Code, ZCode, Hermes, Qwen Code, and MiniMax Code, reports whether each command was found, and links a not-found tool to its maker's install instructions where one exists. Select the tools you use and choose **Install or update Vibe and selected entries**. Setup installs Vibe and the bundled Programming Loop 1.0.3 entries for only those hosts, places the bundled Agent Bridge 1.2.0 runtime beside the application for the in-app conversation, and creates the **Ora Vibe Coder** launcher: an application in your personal Applications folder on macOS, a desktop shortcut on Windows, and a desktop entry on Linux. It installs from the bundled files alone, preserves unselected tools and account settings, and does not log in, choose a model, or install Ora AI Boost. When setup succeeds, close it and restart any selected coding tool that was already open.
2. **Open the launcher.** On Mac it opens the local workspace in your normal browser without a terminal window that must stay open; if the browser does not open, use the local `http://127.0.0.1:...` address it shows. Opening it again returns to the running workspace. Vibe searches the projects folder configured for this installation, or Documents when none is configured, including subfolders at any depth, for projects with a `Project.md` definition. No folder needs to be chosen first, and the search creates and changes nothing; if that root is unavailable, Vibe explains it instead of searching elsewhere.
3. **Open or create a project.** **Choose a project** lists the discovered active projects in list-position order where positions are saved; each position appears before the name, and a subproject displays as **Parent → Project name** with its complete lineage. Projects without positions follow by their displayed lineage and name, and identical names are distinguished by their folder paths. **Open existing** also offers **Refresh projects** to repeat the discovery search during a session, **Show archived projects** to add archived projects (clearly marked; opening one does not reactivate it), recent project folders, and free browsing for folders without a definition. A moved or missing folder stays a deliberate relocation: browse to its new location; nothing is created or renamed for you. **New project** is the only action that deliberately creates a project directory; its **Create under** chooser is restricted to the chosen discovery root and its descendants. The complete proposed destination is shown before creation, and an optional Parent is prefilled from the project you create beneath. Opening a folder creates no files; the last project and workspace reopen next launch with an empty instruction box, but an archived project never reopens by itself while the archive toggle is off.
4. **Read the project documents.** Opening a folder lists its saved documents in the reader automatically — no per-file loading and no overview are required. Vibe resolves the Specification and Plan for revision destinations and shows which file it chose.
5. **Pick the workspace.** Use **Specification** when the product is unclear, **Plan** when the product is decided but the implementation approach is not, and **Build & verify** when requirements and a Plan are ready to implement or a complete candidate needs independent inspection.
6. **Work with AI on this stage.** The screen numbers the route: 1 choose or start a project, 2 read project details, 3 choose a coding tool, and 4 work with AI. Write what you want done, attach pictures, or use **Add files** to select Markdown or text material for this one message, then press **Ask [tool] to work on [stage]** or Enter. Your message is saved before it is shown, and the complete answer appears at the end — no streaming. One turn runs per project at a time while reading and switching projects remain available. In Specification and Plan, step 5 **Review this document** starts a separate assessment session when you press **Review the Specification** or **Review the Plan**; step 6 prepares the next stage. In Build & verify, steps 5, 6, and 7 ask for the Programming Result, independent verification, and corrections. The document pane refreshes when files change.
7. **Prepare a portable request when needed.** Step 6 in Specification and Plan saves an inspectable `Handoff.md`, or `<Project name> — Implementation Request.md` for implementation. Use the selected tool's desktop button, **Open [tool] in Terminal**, or **Copy full request** to deliver it. Before any implementation request is delivered, **Before implementation** advises you when the Specification or Plan lacks a current COMPLETE review; **Continue with implementation** still proceeds. Every stage stays available throughout; assessments and reports are information, never gates.

**Source and maintainer fallback:** from a repository checkout, run `python3 -m ora_vibe_coder` to start the local server directly. Keep that terminal open and use the printed local address if needed. This bypasses the normal installation and created launcher; ordinary users should begin with the supplied setup above.

## Understanding the workspace

### Project information

The collapsible project card shows the selected project's name, folder, repository / code folder, description, and desired outcome. This information comes from the project's own documents — the saved overview, or Description/Mission/Goals sections found in the resolved Request or Product Overview when no overview exists — shown as saved, with the source file named. It is not synthesized from old chats, and absent information stays unreported.

Use **Edit project information** to edit the overview — including the optional Parent display lineage, the active/archived state, the repository / code folder, and the selected material. The overview retains saved document associations, but it does not overrule the actual product, files, or evidence. Project information edits require **Save**.

### The three workspaces

Three expandable vertical rails — **Specification**, **Plan**, **Build & verify** — select the workspace. The selected workspace places the conversation and document side by side on a wide screen. The status icon on each rail reports saved status; it does not judge quality, and styling never implies approval.

Specification and Plan read one `Status` field in their own resolved documents. The Build & verify rail's icon and the workspace verdict come from the saved Verification Report; the retained `Verification` field in `Project.md` is legacy history and never overrides it. Missing, duplicated, malformed, or unfamiliar labels show as unreported or unknown. Opening a workspace, sending a message, preparing text, copying, or launching a tool never changes status.

### Document discovery

Opening a folder and **Refresh** automatically find the project's ordinary Markdown documents and populate the panes. Discovery ranks candidates: a deliberate link first, then the expected filename, then a scalar `vibe_document` type label in closed opening frontmatter (for example `vibe_document: specification`) or ordinary opening metadata, then recognizable role words such as spec/specification or plan/planning in the filename. Among equally ranked candidates the most recently modified file wins, with stable filename order for an exact tie.

The chosen filename is displayed so you can see the selection. Files that explicitly identify conflicting roles, or carry duplicate type labels, are never selected for that role; Vibe shows the conflict and leaves the correction to you or an external edit while every readable document remains available in the reader. `Project.md`, prepared requests — ordinary `Handoff.md`, the named Implementation Request, and recognized renamed outgoing copies — and unrelated file types are excluded. Code, Checks, and Baseline stay deliberate selections; discovery never guesses them.

Discovery identifies documents; it never proves approval or completion. Names, labels, and file times are not results.

### Reading pane

Each workspace's Read menu lists the documents relevant to it. Stage Markdown is rendered read-only; Vibe has no stage editing. Images are not loaded in the pane and external content does not load. Saved files are reread from disk automatically as they change — including saves made by your coding tool or an external editor — preserving the selected file and your reading position, with a compact note naming the files that actually changed; **Refresh** remains the deliberate reread and preserves your workspace and unsent input. If nothing changed on disk, nothing changes in the pane.

### Conversation, split view, and automatic refresh

The conversation and document sit side by side on a wide window. Drag the divider to resize them; the width is remembered. On a narrow window, **Show document** and **Show conversation** switch between the panes. The selected file and reading position are preserved.

**Your message** is the exact user request — Vibe does not paraphrase it. **Ask [tool] to work on [stage]** submits your text, pictures, and selected Markdown or text files together; Enter sends, Shift+Enter adds a newline, and input-method composition is respected. **Attach images** accepts pasted or uploaded PNG/JPEG files as removable thumbnails (at most ten, each up to 8 MiB); the original bytes are retained with the turn under the project's `.vibe/` folder. **Add files** selects up to ten ordinary Markdown or text files, even outside the project; Vibe sends their contents with this message only, leaves the originals in place, and does not silently reuse the selection. If the route cannot accept an image or a selected file is invalid, the submission stops with the draft kept and an explanation — no silent omission and no model switch. Your unsent text is retained while a turn runs, and a second turn on the same project waits for the running one.

While a turn works you see a compact status — elapsed time and time since the last Bridge contact, never claimed model progress — and the complete answer appears when it finishes. A successful turn shows a plain completion line; Bridge diagnostics that need no action sit under collapsed **Technical details**. A failed turn names its reason, and notices that need your attention stay visible. If it is sign-in or a native permission, resolve it in the tool's own window and use **Recheck readiness**. The readiness chip reports, without any model call, whether the selected tool is ready and whether sign-in is required.

Each ordinary turn also maintains the Registry: the reply may end with one maintenance block the application validates and applies atomically to the Registry (or uses to create a missing one). The turn shows what actually happened — `Registry updated`, `Registry: no change needed`, or an honest not-applied notice — and an unapplied proposal is resupplied to later turns until it is applied or resolved, even after its source exchange ages out of the five-exchange context window.

**Review this document** assesses the current Specification or Plan in a fresh session when you press **Review the Specification** or **Review the Plan**. It does not run merely because you send a message. You can add a **Second opinion**: the authoring model writes a fresh assessment, a second harness you choose evaluates it, and the author revises its own work given the evaluation as a guide — with **Iterate to agreement** repeating the evaluate→revise cycle up to three rounds before reporting any residual disagreement, which you break. The reviewer dropdown lists work-capable harnesses and prefers a different harness when one is available; whether the two passes actually ran in different AI labs is stated honestly — different labs, same lab, or unconfirmed when the passes did not report their actual model/provider identity. One second opinion costs three model calls; full iteration up to seven. When direct review is unavailable, **Prepare external review file** offers a saved request for another AI.

**Create the Plan** and **Prepare implementation** prepare the next stage's saved request; every action stays available whatever the documents' state. **Correct the implementation** (Build & verify) carries actual findings and governing scope back through the Programming controller. **Before implementation** warns before delivery if either Specification or Plan lacks a COMPLETE review for its current version. **Continue with implementation** carries on; the warning never disables the action.

In the document pane header, centered between the document title and the Read control and just above the document, Specification and Plan show the prominent completeness display — the saved assessment in large bold text: **COMPLETE**, **INCOMPLETE — n noted deficiencies**, or **NOT REVIEWED** when none exists (an untouched starter template shows **NOT STARTED**). The count comes from the assessment's actual findings; clicking the display takes you to those findings in the document's Current review section. A later change to the assessed document identifies the assessment as applying to an earlier version. None of this ever disables an action.

### Outgoing file

`Handoff.md` holds the current ordinary outgoing snapshot of the portable handoff panel. **Prepare implementation** saves its snapshot to a separate `<Project name> — Implementation Request.md`. Automatic document discovery skips both saved requests, and `Handoff.md` cannot be selected as source material for a later handoff.

If an ordinary `Handoff.md` or implementation request already exists, the first press of the preparation button shows its current content and leaves it untouched. Review that content in the document pane, then press the same button again to replace it. If the file changes meanwhile, Vibe shows the newer content and asks you to review it again. These checks protect manually maintained or externally changed work from silent overwrite.

### Turn records

The conversation itself is retained under the project's reserved `.vibe/` folder: one folder per submitted turn, holding the exact user note (saved before dispatch), the original image bytes, the native Bridge session records, and the post-turn outcome including Registry maintenance. Opening a project shows the saved conversation immediately, and each fresh call receives the current Registry, the last five completed exchanges, your current message, and any unresolved maintenance — earlier decisions survive through the Registry, and nothing replays old request packets. The `.vibe/` name is reserved and never discovered as a project.

## Assessments

Specification and Plan keep one clearly marked **Current review** section in the document itself. The external reviewer saves one clear `Verdict` (COMPLETE or INCOMPLETE), its reasoning, and any noted deficiencies there, replacing superseded feedback without accumulating history; a reviewer that cannot write the document returns the section text for external saving. When Vibe runs the review, it records the stage and evidence basis itself, so the reviewer does not need to copy either one.

When a basis is recorded, it is a SHA-256 digest of the assessed document's own substantive content — with review text, recorded fields, and type labels excluded — so a document that changed after the assessment is identified: the assessment applies to an earlier version. That identification is information for you; it never disables an action, and unrelated Registry notes never affect it. A saved assessment without a usable basis stays visible but is honestly shown as unconfirmed. Assessments saved by earlier versions keep their own verdict vocabulary (such as PASSED or NOT PASSED), displayed exactly as saved with their applicability shown as unconfirmed. Sending or preparing a review request never completes the review; the display appears only after the assessment is saved and the document rereads. A second opinion saves its revised assessment into the Current review section itself, keeps the full evaluation in the turn records one disclosure away, and reports what changed and any residual disagreement.

Preparing the next stage is always available. A prepared assignment approves nothing. The implementation request hands the available documents, the separate code location, and the agreed checks named in the Plan to the implementing recipient; the Programming Loop, when used, retains its own execution approval.

## Choosing a workspace well

### Specification

Use Specification for questions such as: Who is this for? What must the user be able to do? What content or data must be kept? What failures need a visible response? What does “finished” mean?

The result is one current implementation-neutral Specification. Ordinary instructions revise the resolved Specification document, incorporating accepted answers while preserving unrelated requirements. Interface design is a second phase within Specification: consequential interactions are inspected, proportionate concrete evidence — including external mockups or marked screenshots supplied through supported handoffs — is proposed, and approval or named delegation is obtained before dependent implementation. The method separates assessment from your own acceptance: an assessment verdict is not your approval, and your approval is not a claim that an assessment passed.

Specification stops before choosing code structure, dependencies, or other ordinary implementation details unless you made one of those details part of the product requirement.

### Plan

Use Plan when you want an executable approach. Ordinary instructions revise the resolved Plan using the available Specification. The planner uses the current Request and Specification, or substantive equivalents you designate; when supplied sources contain genuinely conflicting versions and you have not chosen, the conflict is shown for your choice rather than silently combined. The planner inspects the real project, chooses the simplest fitting implementation, identifies affected components, protects existing work, assigns exact checks, and describes the complete delivery route. Run sizing splits only at stable boundaries for a real execution or dependency benefit, and cheaper models are considered within your selected configuration without an automatic downgrade.

Planning is read-only toward the target code. If it discovers a missing product decision, it returns that decision to Specification instead of silently choosing for you. The result is one current Implementation Plan, not a diary of alternatives or reviewer conversations.

### Build & verify

Implementation and independent Verification share this workspace's display while keeping separate responsibilities and results.

The Build & verify workspace makes the sequence visible: first work on the implementation, then use **Save the Programming Result** to record what was actually done, then request **Independent verification**, and finally request corrections when the Verification Report identifies material findings. Saving a Programming Result is report-only: it records completed and unfinished work, checks, delivery state, and remaining work; it does not start another implementation pass. For verification, choose an independent reviewer or ask the coordinator to show you the available choices. **Send in Vibe Coder** uses the selected coding tool to coordinate a fresh review; **Copy for an existing AI chat** works even if no coding tool is selected. Both carry your reviewer choice and the current Programming Result. The verifier must use a fresh session separate from the implementation agent; a different tool name alone does not prove a different AI provider.

Use **Prepare implementation** in Plan to hand the available Plan to the implementing recipient — the released Programming Loop when its companion is present, otherwise a direct implementation conversation under the tool's normal approvals. The Loop inspects the repository, presents a minimum honest scope, and waits for its own approval before edits; it uses a fresh executor and a separate fresh reviewer, runs only the agreed checks, corrects material defects, and reaches the agreed delivery endpoint. The AI saves a truthful **Programming Result** after actual work — including work that stops unfinished: work performed, code location, checks, delivery state, and remaining work.

**Independently verify the implementation** here requests current independent Verification — it never reviews the verifier. The verdict shown in Build & verify comes from the saved current **Verification Report**, which the AI saves after actual verification for passing, failing, and incomplete reviews alike; without one, the workspace shows **NOT VERIFIED**. Missing formal documents alone are not a verification failure — the report explains what can be checked and what cannot be established. Neither the report's existence nor an older passing result proves that newer code passed; a retained `Verification` field in `Project.md` is legacy history and does not override the report. Verified findings reach you with evidence and recommended fixes; unrelated findings are reported without extending repair authority. **Correct the implementation** carries actual findings and governing scope back through the existing Programming controller or a complete manual handoff.

## Reading project documents

The reading pane lists the saved Markdown and plain-text documents belonging to the selected project — the five standard working documents (Registry, Specification, Plan, Programming Result, Verification Report), any additional project documentation, and older documents retained from earlier versions. Outgoing handoffs, intake-only material, and documents belonging to nested subprojects are excluded; discovery stops at a subfolder that contains its own `Project.md`. Retained document associations from earlier versions keep their reading protections. Select any listed document to read it; the selected filename is shown. Refresh updates the list and contents without losing your typed instructions.

Older Request, Report, and Verification Findings documents remain recognized and readable; their presence never blocks work, and no manual linking workflow is required. Product code stays in its normal project structure; the project's **Repository / code folder** field records where it lives.

When a document is on another machine or inaccessible to the receiving tool, name it in the conversation. A local path is not useful to a remote recipient that cannot read it.

## What the portable handoff includes

The prepared request is the Desktop, Terminal, and external-recipient route; the ordinary path is the in-app **Ask [tool] to work on [stage]** button. Every prepared packet starts with your exact instruction and a visible boundary before framework instructions. It then contains the selected method, shared working contract, role assignment, project and authority facts, current stage-appropriate materials, known gaps, and the expected next result.

Specification, Plan, and **Create the Plan** packets name the revision destination — the resolved file to revise, or the expected name for a missing output — and show the type-label example an external save may carry. Assessment packets carry the evidence basis for the review and ask the reviewer to save one clear verdict, reasoning, and any noted deficiencies in the Current review section; Vibe records the stage and basis for its own review runs. Every packet names the project's documents folder and repository / code folder accurately — or states honestly that no code folder is selected, with the startup directory described as a conversation starting point.

Programming and **Prepare implementation** packets include the universal Programming Loop framework and exactly one adapter for the selected initiating host. Before building one, Vibe validates its bundled snapshot of the 17 Loop product files and their modes; the public release's separate delivery manifest is not part of that snapshot or the packet. Packets for other purposes do not include the Loop.

The packet excludes an earlier outgoing packet and materials that do not belong at the destination. Preparing is local and makes no provider call. A **Prepare implementation** request uses `<Project name> — Implementation Request.md`; ordinary prepared requests use `Handoff.md`. If either saved request already exists or changed since it was displayed, Vibe leaves it untouched and shows its current content before you prepare again.

## Desktop, Terminal, and Copy

These are the prepared request's delivery routes, beside the in-app conversation.

### Desktop

On macOS, the Desktop button is available only when Vibe finds the selected host's desktop app. For Codex and Claude Code, **Open [tool] desktop with request** asks the app to open a new visible chat with a prefilled, unsent prompt that names the saved request and selected code folder. For the other supported desktop apps, **Open [tool] app + copy request** copies the full request and opens the app so you can paste it into a new chat. In either case, inspect and send the request in the coding tool itself: Vibe does not claim that it was received or executed.

### Terminal

Terminal first confirms that the displayed packet still matches the saved file. It then looks for the selected local coding tool and opens a visible terminal session in the selected repository / code folder — the project documents folder when none is selected.

Codex, Claude Code, Hermes, Qwen Code, and MiniMax Code receive a prompt pointing to a permission-restricted temporary copy of the complete assignment. ZCode performs one bounded no-change receipt turn before opening its normal interactive interface. The temporary operation is cleaned after the coding tool exits.

The host keeps its normal login and approval behavior. Vibe does not auto-approve tool use, choose a hidden model, or inspect the resulting conversation.

### Copy

Copy is the universal delivery baseline. It copies the complete raw Markdown, including text below the visible reading area. Paste it into a fresh recipient that can access the candidate and source material.

If the saved file changed after Prepare, Copy stops and shows the current saved content. Review it, then use **Copy full request** again to copy that current file, or Prepare Again to create a new request. This prevents copying unseen changes.

### Choosing the destination

Choose the coding tool that will initiate and coordinate the work. If that tool later calls another model for an optional review, the initiating tool still determines the Programming Loop adapter.

Do not choose a destination merely because a reviewer model has that vendor's name. The adapter describes dispatch and result retrieval in the coordinating host, not the identity of a review target.

## Returning from a coding tool

Work started through a prepared request continues in the coding-tool window. Save real artifacts — revisions, review results, acceptance, findings, Reports — in the project folder. Conversation turns save their own replies and Registry maintenance into the `.vibe/` records as they complete.

The document panes reread resolved files automatically when they change on disk, preserving your selection and reading position; **Refresh** is the deliberate reread. Vibe does not import a chat transcript, monitor a model, or assume that a process finishing means the task is complete. The displayed verification verdict always comes from the saved current Verification Report.

If a new requirement changes a source document and you are using the portable route, Prepare Again before sending another request. Until then, the saved request remains the earlier prepared snapshot; it does not prove that anything was sent. Ordinary requests share one `Handoff.md`, so review its existing content before replacing it with another request; preserve history in Git or make a manual copy if you need it. An implementation request has its separate named file and receives the same existing-file protection.

## Quitting and desktop launch

Closing the browser leaves Vibe and your external AI work running. Reopen from the app icon to return to the running workspace.

Vibe's AI turns have no automatic time limit. **Stop Vibe**, and normal Mac app Quit (Dock Quit or Command-Q), warn with **Cancel / Quit anyway** when a turn is active, a text box contains unsent text, or files are selected for a message. If you continue, they interrupt Vibe's active turn and end Vibe's own server, the bundled Bridge, and its processes. Files the AI already changed remain, and the interrupted turn keeps its retained records; reopening shows it as unfinished without automatically replaying or retrying the request. No extra AI call occurs on quit, and separate external coding-tool sessions remain running. Actual failures are reported truthfully. After closing the browser on Windows, reopen the desktop shortcut and use Stop Vibe. This ordinary Quit behavior does not promise recovery after a force quit, power loss, or forced kill.

The browser's own tab-close warning is preserved and saves nothing. Unfinished instructions, notes, and project edits are not restored after closure; the last project and workspace reopen with an empty instruction box — except an archived project, which never reopens by itself while the archive toggle is off — and a saved Handoff remains available after input is lost.

Launch failures are shown as actionable dialogs without needing a console. The Windows launcher and desktop shortcut are delivered and covered by focused unit checks that run on macOS with the Windows shell faked, but Windows remains untested on Windows. The existing Linux launch route remains untested on Linux.

The footer shows the running version. **Check for updates** contacts GitHub only when you press it — nothing checks in the background — and answers one of four ways: a newer version is named with a link to its release page and the update steps; *same*, this copy is the newest public release; *ahead*, this copy is newer than the newest public release; or *can't tell*, when the check fails, is rate-limited, or returns an unreadable answer — never reported as up to date. The check downloads, installs, and replaces nothing. **Help** opens the workspace help panel.

## Common problems and recovery

### The browser did not open

Use the local address Vibe shows (in the launcher's dialog or the terminal for source runs). Vibe binds only to the local computer and does not provide a public web address.

### My projects folder or project moved

Projects are found wherever they currently sit inside the configured projects folder, or Documents when none is configured. After a move within that root, **Refresh projects** shows the project at its new location; a move outside it removes the project from the discovered menu. The saved overview's Parent text is display information and is not rewritten by a move. For a folder without a `Project.md` definition, use **Open existing** and browse to it deliberately; Vibe does not search the computer or guess another directory.

### My project is not in the menu

Press **Refresh projects** in **Open existing** first. A project appears when its folder under the selected discovery root contains a readable `Project.md`; an archived project appears only while **Show archived projects** is enabled. Folders without a definition stay reachable through **Open existing** and browsing, and saving project information in one deliberately creates its definition.

### A document is not shown or the wrong file is shown

Press **Refresh** first. Discovery displays the file it chose; restore a missing target rather than creating a blank replacement when valuable content exists elsewhere. The reader lists every saved document, so the content stays reachable either way.

### Two documents seem to claim one role

A file that names conflicting roles or carries duplicate type labels is never selected for that role. Vibe shows the conflict; correct the file externally. Multiple readable documents never block work — every listed document stays readable in the document reader, and assessments read the resolved Specification or Plan.

### The completeness display disagrees with what I expected

The display reads the resolved Specification or Plan document's saved Current review section. An untouched starter template shows NOT STARTED; no recorded assessment shows NOT REVIEWED; a verdict saved by an earlier version is shown exactly as saved. Press **Refresh** after the selected AI saves its assessment, and check that you are looking at the resolved document.

### Prepare refuses to replace Handoff.md

Review the existing content shown in the document pane, then press the same preparation button again. If another process changed it meanwhile, review the newer content and repeat. Vibe preserves the existing file on a failed atomic save.

### Continue says the coding tool was not found

Install or enable that tool through its official process, then retry, or use Copy immediately. The saved Markdown remains available and Vibe does not substitute another provider.

### A conversation turn failed

Read the failure's own reason beneath the turn. If it names sign-in or a native permission, resolve it in the tool's own window, then use **Recheck readiness** and send the message again. A slow turn is not a failed turn: elapsed time and last Bridge contact are shown while it works. The failed turn's exact message and any images remain in the `.vibe/` records; nothing was replayed behind your back.

### The Agent Bridge runtime was not found

The bundled Bridge ships beside the application and is never configured by hand. If it is reported missing, reinstall Vibe from a complete release through the supplied setup; no conversation turn is started against a guessed location.

### The instructions mention Gear and it is unavailable

Gear 3 and Gear 4 — together, Ora AI Boost — are an optional aid for Specification and Planning; no stage stops without them. The method states plainly that the companion was unavailable and continues the work directly, so nothing is left waiting on it. If you want it, install, enable, or update Ora AI Boost from its [releases page](https://github.com/ora-commons/ora-adversarial-review/releases/latest) for a supported engine, and restart the receiving coding tool if its instructions require it. The Vibe installer does not install it.

### The Programming Loop is unavailable or out of date

Programming never stops for the Loop: the in-app conversation and Copy remain available, and the implementing tool works directly under its normal approvals with the limitation reported. To refresh the bundled entries, stop Vibe, reopen the same supplied Vibe setup from the release folder, select the receiving coding tool, and choose **Install or update Vibe and selected entries**. This updates from Vibe's bundled product-file snapshot without requiring access to the private authoritative source. Restart that coding tool, reopen Vibe from its launcher, and prepare the request again. Standalone Loop users update through the public `ora-commons/ora-programming-loop` release. Do not treat the Loop text embedded in a handoff as proof that the installed companion ran.

### Readiness says the selected tool is not ready

The readiness check makes no model call; it reports the tool's own answer. A not-ready result names its reason — often sign-in or a missing command. Resolve it in the tool's own window, then use **Recheck readiness**. Vibe does not label every error a login failure, switch tools, or retry consequential work on its own.

### Continue opens a terminal but work does not begin

Read that terminal. The coding tool may need login, scope approval, a model choice, or clarification. A launched window is not proof of receipt.

### Copy says the snapshot changed

The saved request file no longer matches what was displayed. Vibe shows its current content. Review that full text, then use **Copy full request** again to copy it, or Prepare Again to make a new request. Do not bypass the warning by copying only visible fragments.

### A stage status looks wrong

Inspect the resolved document's opening metadata. There must be exactly one recognized field. Body prose such as “approved” is not a status. Correct the actual document only when you have authority to report the real state.

### Check for updates says can't tell

The check failed, was rate-limited, or returned an unreadable answer, so no update conclusion is offered — a *can't tell* answer is never reported as up to date. The check contacted GitHub only because you pressed the button, and it downloaded and installed nothing. Try again later, or read the release page yourself; updates arrive through the supplied installer from a new release.

### An installation update is refused

Setup never rolls back: if a newer Vibe or a newer installed Programming Loop is already present, setup changes nothing, names what is newer, and says that removing Vibe Coder first allows installing an older version. Installed product files may also have been changed, or a symbolic link may be present. Preserve those files and read the reported paths. The installer keeps the previous installation rather than overwriting uncertain user work.

For a normal update, download the new release zip and unzip it, stop the running app (**Stop Vibe**), then open the supplied setup from the new release folder, select the coding tools whose entries should be updated, and choose **Install or update Vibe and selected entries**. Restart those tools afterward. The version you are running is shown in the footer.

## Stop and remove

Choose **Stop Vibe** (in the page footer) to shut down the local server and Vibe-owned processes. It warns when a turn is active or there is unsent text or selected files; continuing interrupts the active turn, preserves files already changed and retained turn records, and does not automatically replay or retry the request. Normal Mac app Quit behaves the same way. Closing the browser alone leaves Vibe running; Windows users reopen the shortcut and use Stop Vibe.

Stopping Vibe does not stop a coding tool launched in another terminal. Finish or stop that tool through its own interface.

To remove Vibe, return to the release folder and reopen the same supplied setup used for installation: `Install Ora Vibe Coder.command` on macOS, `Install Ora Vibe Coder.cmd` on Windows, or `install.py` with Python on Linux. Select the coding tools whose Vibe and Programming Loop entries should be removed, then choose **Remove Vibe and selected entries**. Removal also removes the bundled Agent Bridge that was placed beside the application. It preserves projects, project documents, `.vibe/` turn records and images, settings, credentials, unrelated host configuration, and entries changed after installation. Read any retained-path notice before deciding whether further manual cleanup is appropriate. Ora AI Boost is a separate product and is not removed by Vibe setup.

## Privacy checklist

Before sending a message with the stage's **Ask [tool] to work on ...** button, opening a prepared request in a desktop app or Terminal, or choosing **Copy full request**:

1. Read what you are about to submit — the message with its attachments, or the complete raw Markdown.
2. Confirm the destination and the project directory.
3. Check which files are selected as material for this message or prepared request; remove any that should not be included.
4. Remove credentials or secrets from your text.
5. Confirm that the receiving tool can access every local path you rely on.
6. Review that tool's own privacy, provider, model, and approval settings.

Vibe provides the packet boundary; you and the receiving tool retain authority over what happens next.

## Worked journeys

- **A new personal tool:** Create or open a project, choose Specification, and describe the person using it, the problem, the visible result, and what “finished” means. Use Review this document when you want an assessment, correct what matters, then choose Create the Plan whenever you are ready — the assessment informs the decision; it does not gate it.
- **An existing project with a vague feature request:** Open the folder; discovery shows its current documents. Begin in Specification if “add sharing” or a similar phrase leaves users, permissions, content treatment, or failure behavior undecided. Planning should not choose those product facts merely because the code already has a likely place for them.
- **A feature with settled requirements:** Use Create the Plan to ask for an implementation plan grounded in the real repository, then Prepare implementation when you are ready to build; do not reuse the planner's chat as an executor prompt. State protected work and the exact intended delivery endpoint.
- **A planned change ready to build:** In Build & verify, name any dirty or protected paths and the testing ceiling. The Loop should present its own concise scope lock before editing, then return actual changed paths, checks, independent review, delivery, cleanup, and recovery evidence.
- **A candidate that needs a fresh audit:** Choose Independently verify the implementation in Build & verify and make the implementation, requirements, documentation, and relevant checks accessible. Ask for direct inspection of visual or external evidence where the requirement depends on it. A missing source remains an unverified risk; do not ask the verifier to infer a pass from the implementer's confidence.
- **A correction after failed Verification:** Keep the current finding list and use Correct the implementation, which routes each defect to the stage that owns it. Product mistakes return to Specification, implementation-direction mistakes to Planning, and code or documentation defects to Programming. After correction, run fresh whole-candidate Verification rather than reviewing only the latest patch.
- **Work interrupted in another coding tool:** Preserve the real branch, diff, files, and check output. Prepare a new instruction that names the accepted baseline, incomplete state, remaining work, and exact authority. The receiving session should inspect those facts; do not reconstruct completion from an old task title or status word.
- **A host is unavailable:** Keep the prepared request file, open Full raw Markdown, and use Copy. Paste into a fresh recipient that can access the project, or move the permitted project material deliberately. Say which paths are inaccessible. Manual delivery is fully supported, but Vibe should not claim native receipt or isolation it cannot observe.
- **You want a second model's opinion:** In Specification or Plan, open **Review this document**, select **Second opinion**, pick the reviewing harness (a different harness is preferred when one is available, and the run's label says what was actually confirmed — different labs, same lab, or unconfirmed), and decide whether to iterate to agreement — at most three rounds, then any residual disagreement is reported and you break the tie. One second opinion costs three model calls; full iteration up to seven.
- **You decide to stop:** Tell the active coding tool to stop, preserve useful current files and the branch, and report unresolved material findings plainly. Return to Vibe and press Refresh. Do not create a Report or set a successful status merely to close the workspace; honest incomplete state is a usable recovery point.
