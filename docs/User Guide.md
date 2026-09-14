# Ora Vibe Coder User Guide

## What Vibe does

Ora Vibe Coder gives a software project one calm local workspace. You choose the project, choose the kind of thinking or work needed next, write an instruction, and inspect the complete assignment before handing it to your coding tool.

Vibe does not replace Codex, Claude Code, ZCode, Hermes, Qwen Code, or MiniMax Code. Those tools still own the conversation, login, model choice, permissions, and actual work. Vibe prepares trustworthy context and makes the project's Markdown documents easy to read.

## Before you begin

You need:

- Python 3.10 or later;
- an existing folder where projects can be found or created;
- a modern browser; and
- at least one supported coding tool for Continue, or any recipient that can accept Markdown if you use Copy.

Vibe itself does not require a provider key and never asks for one. If a coding tool needs login or a subscription, complete that through the coding tool's normal interface.

The companions have distinct installation boundaries. Specification and Planning require the separately installed Gear 3 and Gear 4 product; install or update it through Gear's own setup instructions for a supported engine. Vibe setup does not install Gear. Programming uses Vibe's bundled Programming Loop product-file snapshot, which setup installs into each coding tool you select. Agent Bridge is optional and is used only when you explicitly choose an external-review route.

## Five-minute start

1. **Install Vibe and choose your coding tools.** Open the downloaded release folder. On macOS, double-click `Install Ora Vibe Coder.command`; on Windows, double-click `Install Ora Vibe Coder.cmd`; on Linux, open `install.py` with Python, or run `python3 install.py` if your desktop has no Python action. The setup page lists Codex, Claude Code, ZCode, Hermes, Qwen Code, and MiniMax Code and reports whether each command was found. Select the tools you use and choose **Install or update Vibe and selected entries**. Setup installs Vibe and the Programming Loop entries for only those hosts. It preserves unselected tools and account settings and does not log in, choose a model, or install Gear or Bridge. When setup succeeds, close it and restart any selected coding tool that was already open.
2. **Open the created launcher and choose your projects folder.** Open the **Ora Vibe Coder** launcher at the location shown by the successful setup result. It normally opens the local workspace in your browser; if not, use the local `http://127.0.0.1:...` address shown by the launcher. If another copy is already running, Vibe tries to open it rather than starting another server. On first use, choose the existing folder where you keep projects. Vibe remembers it but does not create, rename, scan, or modify a project. Direct child projects appear in the Project menu; use **Open existing** for a project stored elsewhere.
3. **Open or create a project and link its documents.** Choose a listed project, use **Open existing** and enter its directory, or select **New project**. New Project is the only action that deliberately creates a project directory. Opening existing work does not guess document roles, so use **Link documents / edit** to associate its current files without renaming them.
4. **Pick the next stage.** Use **Specification** when the product is unclear, **Planning** when the product is decided but the implementation approach is not, **Programming** when requirements and a Plan are ready, or **Verification** when a complete candidate needs independent inspection. Choose **Help me get started** if you are unsure. Guided mode provides all four methods to the recipient, but only the stage supported by the evidence should run.
5. **Prepare, deliver, and complete the stage.** Write what you want the stage to do, choose the receiving coding tool, and select **Prepare request** or press Control+Enter / Command+Enter. Vibe saves and shows one complete `Handoff.md`; read it, then choose **Continue** for a normal interactive window in the installed tool or **Copy full Markdown** for manual delivery. Continue is not proof of receipt or work. In the coding-tool window, confirm receipt, answer questions, approve when required, and follow the stage through its named result. Save that result in the project: Specification and Planning require explicit approval of the complete document, Programming finishes at the approved delivery endpoint, and Verification returns findings or creates a Report only after PASS. Return to Vibe, choose **Refresh files**, and read the saved artifact and reported status before treating the stage as complete.

**Source and maintainer fallback:** from a repository checkout, `python3 -m ora_vibe_coder` starts the server directly. Keep that terminal open and use the printed local address if needed. This bypasses the normal installation and created launcher; ordinary users should begin with the supplied setup above.

## Understanding the workspace

### Project information

The top project card shows the selected project's purpose, goals, and Request. This information comes from the project's associated Markdown files. It is not synthesized from old chats.

Use **Project information** to edit the small overview. The overview can associate documents and report Programming or Verification status, but it does not overrule the actual product, files, or evidence.

### Stage rail

Each stage button opens a reading and composition workspace. The status icon reports a recognized field from the associated document; it does not judge quality.

Specification and Planning read one `Status` field in their own documents. Programming and Verification read their own named fields in `Project.md`. Missing, duplicated, malformed, or unfamiliar labels show as unreported or unknown.

Opening a stage, preparing text, copying, or launching a tool never changes status.

### Reading pane

The Read menu lets you switch among documents relevant to the selected stage. **Refresh files** rereads them from disk after your coding tool saves work.

The **Document** and **Request** buttons help you return to the primary artifact or the current product request. The caption states which file is shown and whether it is missing or unlinked.

### Composition pane

**Your next instruction** is the exact user request placed first in the packet. Vibe does not paraphrase it.

The expanded **Authority, protected work, and references** area lets you state:

- what effects and checks are authorized;
- files or work that must not be changed;
- extra reference locations and access limitations; and
- associated sources that should remain references instead of being embedded.

Use these fields for facts the recipient needs. Do not paste credentials or private keys.

### Outgoing file

`Handoff.md` is the current outgoing snapshot. It is deliberately not treated as a source document for a later handoff, because including it would nest an earlier packet inside the new one.

If an existing `Handoff.md` is present, Vibe asks you to select it explicitly before replacement. **Inspect existing Handoff.md** shows the current content. This protects manually maintained or externally changed work from silent overwrite.

## Choosing a stage well

### Specification

Use Specification for questions such as: Who is this for? What must the user be able to do? What content or data must be kept? What failures need a visible response? What does “finished” mean?

The result is one current Request and one implementation-neutral Specification. The method separates review quality from user approval. A reviewer pass is not your approval, and your approval is not a claim that independent review passed.

Specification stops before choosing code structure, dependencies, or other ordinary implementation details unless you made one of those details part of the product requirement.

### Planning

Use Planning after the product outcome is clear. The planner inspects the real project, chooses the simplest fitting implementation, identifies affected components, protects existing work, assigns exact checks, and describes the complete delivery route.

Planning is read-only toward the target code. If it discovers a missing product decision, it should return that decision to Specification instead of silently choosing for you.

The result is one current Implementation Plan, not a diary of alternatives or reviewer conversations.

### Programming

Use Programming to hand a current requirement and implementation plan to the released Programming Loop. The Loop inspects the repository, presents a minimum honest scope lock, and waits for approval before edits.

After approval, the Loop uses a fresh executor and a separate fresh reviewer, runs only the agreed checks, corrects material defects, and reaches the agreed Git or delivery endpoint. It preserves unrelated work and uses Git for rollback when the project uses Git.

If you deliberately continue without a complete Specification or Plan, the packet records that reduced basis. The Loop still requires its own scope approval and cannot invent authority for publishing, payment, credentials, or destructive work.

### Verification

Use Verification only when a complete candidate and enough requirements are accessible. Verification reads the implementation, documentation, checks, and relevant evidence independently.

A PASS means no material finding or unverified material risk remains under the supplied contract. A previous report, fallback review, inaccessible artifact, or unrepeated review after a correction is not a current PASS.

Verification is read-only. In guided use it returns findings to the earliest stage that owns the defect. A Report is created only after PASS.

## Linking documents

Select **Link documents / edit**. For each role, choose the real file that currently serves it. You may link existing filenames; Vibe does not require renaming to its default names.

The common roles are Request, Specification, Plan, User Guide, Technical Documentation, Product Overview, and Report. Product code stays in its normal project structure rather than being copied into Markdown.

An **unlinked** role means no association was chosen. A **missing** file means an association exists but its target is unavailable. These states have different remedies: link the right existing file for the first; restore, relink, or deliberately create the expected artifact for the second.

Do not link `Project.md` or the current `Handoff.md` as a source artifact. They have special association and outgoing roles.

When a document is on another machine or inaccessible to the receiving tool, add an access note. A local path is not useful to a remote recipient that cannot read it.

## What Prepare includes

Every prepared packet starts with your exact instruction and a visible boundary before framework instructions. It then contains the selected method, shared working contract, role assignment, project and authority facts, current stage-appropriate materials, known gaps, and the expected next result.

Programming and guided packets include the universal Programming Loop framework and exactly one adapter for the selected initiating host. Before building either packet, Vibe validates its bundled snapshot of the 17 Loop product files and their modes; the public release's separate delivery manifest is not part of that snapshot or the packet. Packets for other stages do not include the Loop. Guided packets include all four Vibe stage bodies exactly once.

The packet excludes an earlier outgoing packet and stage materials that do not belong at the destination. This keeps the request complete without turning it into an archive.

Preparing is local and makes no provider call.

## Continue and Copy

### Continue

Continue first confirms that the displayed packet still matches the saved file. It then looks for the selected local coding tool and opens a visible terminal session rooted in the project directory.

Codex, Claude Code, Hermes, Qwen Code, and MiniMax Code receive a prompt pointing to a permission-restricted temporary copy of the complete assignment. ZCode performs one bounded no-change receipt turn before opening its normal interactive interface. The temporary operation is cleaned after the coding tool exits.

The host keeps its normal login and approval behavior. Vibe does not auto-approve tool use, choose a hidden model, or inspect the resulting conversation.

### Copy

Copy is the universal delivery baseline. It copies the complete raw Markdown, including text below the visible reading area. Paste it into a fresh recipient that can access the candidate and source material.

If the saved file changed after Prepare, Copy stops and shows the current saved content. Review it, then Prepare Again or acknowledge the expected version and deliberately retry. This prevents copying unseen changes.

### Choosing the destination

Choose the coding tool that will initiate and coordinate the stage. If that tool later calls another model for an optional review, the initiating tool still determines the Programming Loop adapter.

Do not choose a destination merely because a reviewer model has that vendor's name. The adapter describes dispatch and result retrieval in the coordinating host, not the identity of a review target.

## Returning from a coding tool

Work continues in the coding-tool window. Save real artifacts in the project directory. When the stage returns a result, come back to Vibe and select **Refresh files**.

Vibe rereads the associated files. It does not import a chat transcript, monitor a model, or assume that the process finishing means the task is complete.

If a new requirement changes a source document, Prepare Again before sending another stage. Until then, `Handoff.md` remains the earlier prepared snapshot; it does not prove that anything was sent. Prepare Again deliberately replaces the selected single `Handoff.md`, so preserve history in Git or make a manual copy first if you need it.

## Common problems and recovery

### The browser did not open

Open the local URL printed in the terminal. If no URL appears, read the terminal error. Vibe binds only to the local computer and does not provide a public web address.

### My projects folder moved

Vibe reports that the saved folder is unavailable. Choose its current location. It does not search the computer or guess another directory.

### My project is not in the menu

Use **Open existing** and select its directory. Only direct children of the selected projects folder are listed automatically.

### A document is not shown

Open **Link documents / edit**. Confirm that the role is linked and that the target file exists. Restore or relink a missing target; do not create a blank replacement if valuable content exists elsewhere.

### Prepare refuses to replace Handoff.md

Inspect the existing file and explicitly select it as the outgoing destination. If another process changed it, review the new content first. Vibe preserves the existing file on a failed atomic save.

### Continue says the coding tool was not found

Install or enable that tool through its official process, then retry, or use Copy immediately. The saved Markdown remains available and Vibe does not substitute another provider.

### Specification or Planning says Gear is unavailable

Stop that stage rather than accepting an imitation. Install, enable, or update the separate Gear 3 and Gear 4 product through Gear's own setup instructions for a supported engine, restart the receiving coding tool if its instructions require it, and retry. The Vibe installer does not install Gear.

### Programming says the Programming Loop is unavailable or out of date

Stop the companion-dependent work. Choose **Stop app**, reopen the same supplied Vibe setup from the release folder, select the receiving coding tool, and choose **Install or update Vibe and selected entries**. This updates from Vibe's bundled product-file snapshot without requiring access to the private authoritative source. Restart that coding tool, reopen Vibe from its launcher, and prepare the Programming request again. Standalone Loop users update through the public `ora-commons/ora-programming-loop` release. Do not treat the Loop text embedded in a handoff as proof that the installed companion ran.

### Agent Bridge is unavailable

Bridge is optional. Its external-review route cannot run until Bridge is installed and ready through its own instructions, but Vibe's legitimate fresh internal review remains available where the stage provides it. Use that route or a complete manual handoff to a qualified fresh reviewer, and report which route actually ran; do not claim external model diversity when Bridge was unavailable. If no qualified independent route is available, Verification remains incomplete.

### Continue opens a terminal but work does not begin

Read that terminal. The coding tool may need login, scope approval, a model choice, or clarification. A launched window is not proof of receipt.

### Copy says the snapshot changed

The saved `Handoff.md` no longer matches what is displayed. Review the current saved content, then Prepare Again. Do not bypass the warning by copying only visible fragments.

### A stage status looks wrong

Inspect the associated document's opening metadata. There must be exactly one recognized field. Body prose such as “approved” is not a status. Correct the actual document only when you have authority to report the real state.

### An installation update is refused

Installed product files may have been changed or a symbolic link may be present. Preserve those files and read the reported paths. The installer keeps the previous installation rather than overwriting uncertain user work.

For a normal update, first choose **Stop app**, then reopen the supplied setup from the new release folder, select the coding tools whose entries should be updated, and choose **Install or update Vibe and selected entries**. Restart those tools afterward.

## Stop and remove

Choose **Stop app** to shut down the local server cleanly. Closing the browser tab alone does not stop the terminal process.

Stopping the app does not stop a coding tool launched in another terminal. Finish or stop that tool through its own interface.

To remove Vibe, return to the release folder and reopen the same supplied setup used for installation: `Install Ora Vibe Coder.command` on macOS, `Install Ora Vibe Coder.cmd` on Windows, or `install.py` with Python on Linux. Select the coding tools whose Vibe and Programming Loop entries should be removed, then choose **Remove Vibe and selected entries**. Removal preserves projects, project documents, settings, credentials, unrelated host configuration, and entries changed after installation. Read any retained-path notice before deciding whether further manual cleanup is appropriate. Gear and Bridge are separate products and are not removed by Vibe setup.

## Privacy checklist

Before Continue or Copy:

1. Read the complete raw Markdown.
2. Confirm the destination and the project directory.
3. Keep sensitive sources reference-only when embedding them is unnecessary.
4. Remove credentials or secrets from the instruction.
5. Confirm that the receiving tool can access every local path you rely on.
6. Review that tool's own privacy, provider, model, and approval settings.

Vibe provides the packet boundary; you and the receiving tool retain authority over what happens next.

## Worked journeys

- **A new personal tool:** Create or open an empty project, choose Specification, and describe the person using it, the problem, the visible result, and what “finished” means. Approve the complete Specification only after it says what must happen without choosing unnecessary code. Use Planning next, then Programming after the implementation route and checks are clear.
- **An existing project with a vague feature request:** Open the repository, link its current product material, and begin with Specification if “add sharing” or a similar phrase leaves users, permissions, content treatment, or failure behavior undecided. Planning should not choose those product facts merely because the code already has a likely place for them.
- **A feature with approved requirements:** Link the Specification and any current Request, choose Planning, and ask for an implementation plan grounded in the real repository. State protected work and the exact intended delivery endpoint. After approval, prepare a new Programming packet; do not reuse the planner's chat as an executor prompt.
- **A planned change ready to build:** Choose Programming, associate the approved Specification and Plan, name any dirty or protected paths, and state the testing ceiling. The recipient should present its own concise scope lock before editing, then return actual changed paths, checks, independent review, delivery, cleanup, and recovery evidence.
- **A candidate that needs a fresh audit:** Choose Verification and make the implementation, requirements, documentation, and relevant checks accessible. Ask for direct inspection of visual or external evidence where the requirement depends on it. A missing source remains an unverified risk; do not ask the verifier to infer a pass from the implementer's confidence.
- **A correction after failed Verification:** Keep the current finding list and route each defect to the earliest stage that owns it. Product mistakes return to Specification, implementation-direction mistakes to Planning, and code or documentation defects to Programming. After correction, run fresh whole-candidate Verification rather than reviewing only the latest patch.
- **Work interrupted in another coding tool:** Preserve the real branch, diff, files, and check output. Prepare a new instruction that names the accepted baseline, incomplete state, remaining work, and exact authority. The receiving session should inspect those facts; do not reconstruct completion from an old task title or status word.
- **A host is unavailable:** Keep the prepared `Handoff.md`, open Full raw Markdown, and use Copy. Paste into a fresh recipient that can access the project, or move the permitted project material deliberately. Say which paths are inaccessible. Manual delivery is fully supported, but Vibe should not claim native receipt or isolation it cannot observe.
- **You want a second model's opinion:** Keep the coding tool that coordinates the work selected as the destination. Authorize the external reviewer route, cost, and permissible content explicitly in the plan. The Programming Loop uses the initiating host adapter to send and collect that review; a reviewer vendor name does not change the dispatcher.
- **You decide to stop:** Tell the active coding tool to stop, preserve useful current files and the branch, and report unresolved material findings plainly. Return to Vibe and refresh. Do not create a Report or set a successful status merely to close the workspace; honest incomplete state is a usable recovery point.
