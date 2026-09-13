# Ora Vibe Coder Technical Documentation

## System purpose

Ora Vibe Coder is a local document workspace and handoff composer. It reads explicitly associated project Markdown, assembles a complete stage-specific request, saves one outgoing snapshot, and optionally launches a supported interactive coding tool. It is deliberately not an agent runtime, model router, workflow database, or project scanner.

The system separates three truths: project files describe the product and status; packaged frameworks describe the method; the selected coding tool performs conversation and execution under its own permissions. The browser does not promote launch or process state into project completion.

## Repository layout

| Path | Responsibility |
|---|---|
| `ora_vibe_coder/` | Local server, project model, packet construction, host launch, installation, and static interface. |
| `plugins/ora-vibe-coder/` | Native Vibe plugin entries, canonical stage frameworks, shared references, and generated Loop resources. |
| `components/programming-loop/` | Standalone canonical Programming Loop distribution and installer. |
| `scripts/assemble_resources.py` | One-way assembler from the canonical Loop into the Vibe plugin. |
| `docs/` | Public user, technical, and product documentation. |
| `tests/` | Focused application, handoff, installer, and framework delivery checks. |

The canonical Loop and generated plugin mirror are separate distribution locations, not two maintained methods. Authored Loop changes begin in `components/programming-loop`; the assembler replaces `plugins/ora-vibe-coder/resources/programming-loop` and writes exact source hashes.

## Runtime architecture

### Launcher and process lock

`ora_vibe_coder.__main__` parses the optional projects directory, settings path, install mode, install home, and no-browser flag. Normal launch reads the saved projects home, acquires one application lock for that settings location, writes a permission-restricted local running record, starts the HTTP server, and normally opens the loopback URL.

If another instance owns the lock, the launcher attempts to open the existing recorded local URL. An invalid or symbolic-link launch record is not trusted. Shutdown removes the running record and releases the lock.

The server runs in one process with a bounded serving thread. It binds to `127.0.0.1`; it is not a remotely hosted web application.

### Local HTTP server

`ora_vibe_coder.server.LocalServer` serves the static interface and small JSON operations for project selection, reading, association, preparation, copying, continuation, and shutdown. Requests are constrained to local origins and expected routes. File operations are mediated by the project layer instead of accepting arbitrary browser file URLs.

The interface is plain HTML, CSS, and JavaScript. Vendored markdown-it renders trusted local Markdown display content; its license remains in the vendor directory and root Notice.

### Project model

`ora_vibe_coder.project.Project` resolves one explicit project root. It reads `Project.md`, document associations, associated artifacts, and one `Handoff.md`. The project root is never inferred from packet text.

Associations distinguish these states:

- a role is not linked;
- a linked path is missing;
- a linked file is readable;
- a path is rejected because it resolves outside permitted project handling or collides with a special role; and
- the outgoing file changed since the displayed snapshot.

Atomic writes create a temporary sibling, flush it, and replace the destination. A failed stage preserves the previous destination. The project model does not invent backup archives or timestamped handoff copies.

### Settings

Settings store the chosen projects home and local launch state. They are application preferences, not a project database. Projects and artifacts remain ordinary directories and Markdown files.

## Document model

### Project overview

`Project.md` is a small optional association and status overview. It can contain project description, goals, linked document paths, and the separately owned `Programming` and `Verification` fields.

Ground truth remains the actual product and documents. An overview field reports state; it does not certify a current revision, replace user approval, or suppress a real artifact that the overview cannot represent.

### Source roles

The supported reader roles are Request, Specification, Plan, User Guide, Technical Documentation, Product Overview, and Report. Existing filenames can be associated explicitly. The default numbered names are conveniences for guided projects, not a discovery heuristic.

`Project.md` and `Handoff.md` cannot be selected as ordinary source roles. The former has dedicated overview semantics. The latter is the outgoing snapshot and is excluded to prevent recursive packet growth.

### Status parsing

`ora_vibe_coder.status` reads one field in the opening metadata block. It normalizes Markdown decoration, line endings, trailing spaces, and hard breaks, but does not search body prose or reinterpret arbitrary synonyms.

Specification and Planning use `Status` with `DRAFT`, `IN PROGRESS`, `AWAITING APPROVAL`, or `APPROVED`, plus the narrowly recognized legacy values. Programming reads `Programming` from `Project.md`. Verification reads `Verification` there. Missing, duplicate, malformed, or unrecognized values become unreported or unknown.

The UI never writes a successful status because a stage was opened, prepared, copied, or launched.

## Framework delivery

### Maintained Vibe method

The plugin maintains five framework bodies: Specification, Planning, Programming, Verification, and the guided lifecycle. `references/shared-contract.md` supplies common content and handoff rules. `references/role-and-assignment.md` defines the coordinator, custodian, executor, verifier, and complete assignment contract.

Each native skill file is intentionally thin. It loads the shared contract, role source, and exactly one canonical framework. The guided loader also exposes all four stage bodies because guided coordination may need to select the earliest responsible stage.

The Programming framework is a readiness and handoff layer. It does not duplicate the Programming Loop. The packet supplies the canonical generated Loop framework and exactly one host adapter when Programming or guided use requires it.

### Programming Loop source and mirror

`components/programming-loop` is the maintained standalone source. It contains:

- one universal framework;
- six initiating-host adapters;
- one native skill entry;
- reviewer profiles for Claude Code, ZCode, and Qwen Code;
- a transactional installer;
- CC0 and notice files; and
- a semantic version.

`scripts/assemble_resources.py` enumerates the exact public resource set, validates non-empty regular files, reads the neutral version, synchronizes Vibe plugin manifest versions, assembles a sibling staging directory, verifies every byte, and atomically replaces the plugin resource target.

The generated `SOURCE.json` names `programming-loop`, records the component version, and maps every copied relative path to its SHA-256 digest. This proves byte identity with the declared source; it is not a review certificate or runtime status.

Maintainers must never edit the generated resource directory by hand. Regenerate it from the canonical component and inspect both the source diff and generated parity.

### Host selection

The packet builder normalizes the selected destination to one of six hosts. It includes only that initiating host's adapter. Selecting a review model from a different vendor does not change the adapter, because the initiating coding tool owns subagent dispatch, result collection, and waiting.

If the destination is free-form or no supported adapter can be established, the packet remains manually deliverable but must not claim native Programming Loop host wiring.

## Handoff construction

`ora_vibe_coder.handoff.prepare_request` validates the stage and receiving harness, then constructs one ordered Markdown packet:

1. the user's exact input;
2. a visible boundary before framework instructions;
3. shared contract, role source, selected framework, and when applicable the canonical Loop plus one adapter;
4. project, authority, protected state, output, and assignment facts;
5. only stage-appropriate current materials; and
6. known gaps and the next bounded result.

Guided packets contain the guided coordinator and all four actual stage bodies exactly once. Standalone packets contain only their selected stage body. Programming and guided packets contain the Loop; other stage packets do not.

The Request is embedded when its role belongs at the destination. Earlier outgoing text, raw planning discussion, reviewer transcripts, and irrelevant stage history are excluded. A missing association is disclosed separately from an unreadable or missing associated file.

The prepared snapshot includes the package version so a recipient can identify the method revision. It also states that preparation made no model call and delivered no text.

## Save, display, and copy integrity

Preparation writes `Handoff.md` atomically and returns the exact saved text for display. The browser stores the prepared snapshot it showed. Copy compares that displayed text with the current saved file before writing to the system clipboard.

If another process changes the saved handoff, Copy raises a conflict and returns the current content. The user must inspect it and prepare again or deliberately select the expected version. The system never copies a hidden new version or only the visible portion of the textarea.

This comparison protects the handoff boundary without maintaining a version database. The current file and displayed snapshot are sufficient.

## Interactive host routes

`ora_vibe_coder.hosts` detects these executables:

| Host | Command identity | Interactive route |
|---|---|---|
| Codex | `codex` | Prompt in a visible terminal, rooted in the project. |
| Claude Code | `claude` | Prompt in a visible terminal, rooted in the project. |
| ZCode | `zcode` or inspected macOS application entry | Bounded no-change receipt, then normal interactive TUI. |
| Hermes | `hermes` | Interactive TUI query route. |
| Qwen Code | `qwen` | Prompt-interactive route. |
| MiniMax Code | `mcode` or its user-local executable | Prompt in a visible terminal. |

The complete assignment is written to a permission-restricted temporary operation directory. The command receives a short prompt pointing to that UTF-8 file, which avoids shell interpretation and command-line length limits. The host reads the file as the user's assignment and returns work in its own conversation.

macOS uses Terminal and a task-owned command wrapper. Windows creates a new console. Linux chooses a supported desktop terminal. If none is found, Continue fails visibly and leaves Copy available.

Validation occurs before operation files are created. Launch failures remove task-owned temporary material. Once launched, the visible terminal owns the assignment copy until the coding tool exits, then the operation directory is removed.

The route reports `launch_requested`, not completed execution. It does not monitor the tool, import its transcript, or infer that process exit means project success.

## Installation architecture

### Vibe installer

The root installer copies the application, launcher, selected native Vibe entries, and selected Programming Loop host resources. It validates required sources and host operations before changing the destination.

The companion boundary is deliberate. Gear 3 and Gear 4 are separately installed requirements for Specification and Planning; the Vibe installer does not install them, so an unavailable or mismatched Gear stops that stage until the user follows Gear's own install, enable, or update instructions for a supported engine. The Programming Loop is installed for each host selected in Vibe setup; if it is missing or out of date, stop Programming, rerun the supplied Vibe setup with that host selected, and restart the host. Agent Bridge is optional: absence disables only the selected external-review route, and must not be reported as external diversity or silently replaced; a qualified fresh internal or complete manual review route remains usable where the stage provides it.

Updates and removals use one in-process transaction across the selected product targets. Existing owned files are compared with installation metadata. Changed, missing, unowned, or symbolic-link content is preserved or causes a visible refusal rather than silent overwrite.

Removal deletes only installation-owned content. Projects, documents, credentials, unrelated host files, and user-modified entries remain. The result lists retained additions.

### Standalone Loop installer

`components/programming-loop/scripts/install.py` supports `install`, `remove`, `status`, `recover`, `install-check`, and `remove-check`. It accepts a host and either the normal user home or an explicit host root.

Installation writes a versioned release under a component-owned directory, records source hashes, and switches only the selected host's entry points. Hosts with reviewer profiles receive only their matching selected profile. Failure between staging and switching preserves the prior release and exposes recovery.

Removal compares installed ownership and preserves modified entries. It never contacts a model or provider.

## Security and privacy boundaries

The application is local, but local does not mean every project file is safe to transmit. The system does not scan for secrets, classify sensitive content, or decide a coding tool's data policy.

Relevant controls include:

- loopback-only server binding;
- local-origin and route validation;
- explicit project and document selection;
- atomic destination replacement;
- symbolic-link rejection on protected installation and launch surfaces;
- permission-restricted launch records and assignment copies;
- shell-safe argument construction rather than interpolated user text;
- exact displayed-versus-saved copy comparison; and
- no stored provider credential or embedded model client.

The receiving tool's permissions, provider settings, retention, and network behavior remain outside Vibe. Documentation and notices must preserve that boundary.

## Failure and recovery behavior

| Failure | Preserved state | Recovery |
|---|---|---|
| Browser does not open | Server and printed local URL | Open the printed URL. |
| Saved projects home is unavailable | Settings and projects | Select the current existing folder. |
| Document association is absent or broken | Other associations and files | Link or restore the intended file. |
| Handoff save fails | Previous `Handoff.md` | Correct the reported filesystem issue and Prepare Again. |
| Handoff changes after display | Both displayed and current content | Inspect current text, then deliberately prepare/copy again. |
| Host executable is missing | Saved packet and Copy | Install/enable the selected tool or use manual Copy. |
| Terminal launch fails | Saved packet; operation staging is removed | Use Copy or correct the terminal environment. |
| Installer validation fails | Previous installation | Preserve reported content, resolve ownership, then retry. |
| Generated Loop assembly fails | Previous generated resource directory | Correct canonical inputs and rerun the assembler. |

No recovery step silently selects another coding tool or provider.

## Testing boundaries

The focused suites use temporary projects, temporary homes, fake executables, and controlled launch functions. They verify packet ordering and exact inclusion, status parsing, atomic conflict handling, host argument construction, installation ownership, transactional recovery, standalone Loop distribution, and canonical-to-generated byte parity.

These checks do not make live model calls, validate provider credentials, accept visual design on behalf of a user, or prove every third-party host release. Public compatibility claims distinguish deterministic package coverage from live qualification.

When changing the system, choose the smallest checks that judge the material changed surface and follow any explicit testing ceiling in the task. Do not add tests for internal serialization merely to duplicate an already proven user-visible behavior.

## Safe maintenance

### Change a Vibe stage method

Edit the owning framework or shared reference, not the five thin loaders. Enumerate every packet that consumes shared text and keep links valid. Preserve the distinction between stage ownership: Specification defines WHAT, Planning defines HOW, Programming hands off to the Loop, and Verification remains independent and read-only.

### Change Programming Loop behavior

Edit `components/programming-loop/frameworks/programming-loop.md` and the minimum adapter or entry files required. Do not place universal rules in host adapters. Run the approved assembler to replace the embedded resource copy, then verify generated identity and focused distribution behavior.

### Add a host

First establish a real initiating-host mechanism for fresh execution, separate review, complete result retrieval, bounded waiting, and safe installation/removal. Add one small adapter naming only those mechanics, installer mapping, and a focused distribution expectation. Do not add a universal launcher or imply live qualification from a fixture.

### Change the interface

Keep notice and failure messages visible, modals usable at the supported viewport, and nested pickers above their parent dialogs. Maintain keyboard and accessible labeling. UI work needs direct visual inspection when acceptance depends on appearance; DOM tests alone do not prove visual quality.

### Release discipline

Update neutral version sources, regenerate derived resources, inspect the complete staged diff, and keep notices truthful. Do not hand-edit `SOURCE.json`, generated mirrors, or native manifest versions that the assembler owns.

Use Git as the rollback mechanism. Remove task-owned staging and background processes before declaring work complete.

## License and notices

## End-to-end control flow

1. **Launch:** the Python entry reads local settings, verifies the saved projects directory if present, acquires the settings-scoped lock, creates a permission-restricted running record, binds the loopback server, and opens or prints the URL. No project is selected or changed merely by starting the process.
2. **Project selection:** the browser asks the server to list direct child directories of the chosen projects home or opens one explicit existing path. New Project is a distinct operation. The resulting `Project` object becomes the sole root for associations, reads, and outgoing replacement.
3. **Document association:** the user maps document roles to existing project-relative artifacts. The project layer rejects special-file collisions and reports absent targets. Association changes update the small overview without rewriting the associated documents or searching for alternative filenames.
4. **Composition:** the browser holds draft instruction, destination, authority, protected-work, reference, and reference-only choices. Switching views preserves that tab-local draft; closing the tab is not a save guarantee. No provider sees composition state.
5. **Packet assembly:** the server loads the exact maintained shared sources, selected stage, role assignment, stage-appropriate project artifacts, and for Programming or guided use the generated Loop plus one normalized host adapter. It places the exact user text first and emits one deterministic Markdown body.
6. **Atomic save:** the project layer checks outgoing selection and any expected prior content, writes a temporary sibling, flushes it, and replaces `Handoff.md`. The returned bytes become the displayed snapshot. A failure removes owned staging and leaves the earlier destination in place.
7. **Copy or Continue:** Copy re-reads and compares the snapshot before touching the clipboard. Continue performs the same comparison, validates the selected executable and platform launch route, writes a mode-0600 temporary assignment, and opens a visible terminal rooted at the project.
8. **External work:** the coding tool reads the immutable assignment copy and applies its normal conversation, account, model, repository, and approval rules. Vibe neither receives tool events nor writes project status in response to them. The terminal cleans its operation directory when the tool exits.
9. **Return:** the user saves real artifacts through the coding tool and selects Refresh files. Vibe re-reads associated content and recognized status fields. Later source changes do not mutate the old prepared snapshot; a new recipient requires Prepare Again.
10. **Shutdown:** Stop app asks the local server to end; launcher cleanup removes its running record and releases the lock. Coding tools opened in separate terminals have independent lifetimes and must be ended through their own interface.

## Invariants maintainers must preserve

- Exact user input precedes all packaged instruction text, and a visible boundary distinguishes the two. A refactor that normalizes or summarizes the input changes the product contract even if the resulting prose seems equivalent.
- Displayed, saved, and copied packet content agree byte-for-text after the documented newline handling. A stale display never authorizes replacement or copy of a newly changed outgoing file.
- Each packet contains the shared contract and role source once, the intended stage bodies once, and no prior outgoing packet. Programming and guided packets alone contain the Loop; they contain one initiating-host adapter, never an adapter collection.
- Source identity for the embedded Loop describes the exact canonical bytes. Version and hashes are regenerated facts. They cannot be edited to bless a divergent mirror, and their presence does not replace substantive review.
- Missing metadata fails open only where truthful partial representation remains possible. It must not become a fabricated approval or hide a readable real artifact. Security, ownership, replacement, and publication boundaries continue to fail explicitly.
- Host launch text is inert data, never a shell program. Long Markdown stays in a file with restrictive permissions, arguments are constructed as arrays or safely quoted wrappers, and an unsupported terminal leaves the saved handoff and Copy path intact.
- Native entries remain loaders. Universal lifecycle behavior belongs in canonical frameworks, and host-specific Programming mechanics belong only in adapters. A new entry that restates the method creates a drift surface and should be consolidated before release.
- Installation is reversible from owned state. Updates never overwrite unowned or modified files silently, removals never delete projects or credentials, and a failed multi-target transaction restores the previous selected product set.

First-party source and documentation are dedicated under CC0 1.0 Universal. The root `NOTICE.md` retains the vendored markdown-it copyright and MIT terms. Host product names are compatibility identifiers and do not imply endorsement.
