# Ora Vibe Coder Technical Documentation

## System purpose

Ora Vibe Coder is a local conversation and document workspace. It resolves project Markdown — from deliberate associations or automatic folder discovery — runs an in-project conversation with the selected coding tool through the bundled Agent Bridge, applies validated Registry maintenance, and keeps a complete portable handoff composer for terminal recovery and external recipients. It presents four portable methods (Specification, Planning, Programming, Verification) behind three workspaces: Specification, Plan, and Build & verify. It is deliberately not an agent runtime, model router, workflow database, or project scanner.

The system separates three truths: project files describe the product, status, review, and approval; packaged frameworks describe the method; the selected coding tool performs conversation and execution under its own permissions, invoked as an ordinary local command through Bridge. The browser does not promote launch or process state into project completion.

## Repository layout

| Path | Responsibility |
|---|---|
| `ora_vibe_coder/` | Local server, project model, conversation runtime, packet construction, host launch, installation, and static interface. |
| `ora_vibe_coder/conversation.py` | In-app work turns as native Bridge sessions under `.vibe/`, Registry maintenance, and the second-opinion pipeline. |
| `ora_vibe_coder/reliability.py` | The second-opinion pipeline's vendored instruction texts and their pinned Ora provenance. |
| `ora_vibe_coder/loop_integrity.py` | Single reviewed authority pins and shared offline Git-tree verification for the Programming Loop and the Agent Bridge runtime. |
| `plugins/ora-vibe-coder/` | Native Vibe plugin entries, canonical Vibe stage frameworks, shared references, and generated Loop resources. |
| `components/programming-loop/` | Vendored copy of the 17 Programming Loop product files retained for offline Vibe installation. |
| `components/agent-bridge/` | Vendored copy of the 19 reviewed Agent Bridge runtime files (the `bridge/` package, license, notice, README) bundled once beside the installed application. |
| `scripts/assemble_resources.py` | One-way assembler from the vendored Loop snapshot into the Vibe plugin. |
| `docs/` | Public user, technical, and product documentation. |
| `tests/` | Focused application, conversation, handoff, installer, and framework delivery checks. |

Programming Loop is authored in the dedicated private source repository `Golfplan18/ora-programming-loop` and released publicly through `ora-commons/ora-programming-loop`. Vibe's component subtree and generated plugin resources are two vendored distribution locations, not maintained methods. Ordinary users install or update through Vibe setup or the public Loop release; neither route requires private-repository access. Agent Bridge is authored and released publicly at `ora-commons/agent-bridge`; Vibe vendors its reviewed runtime files once and calls them locally.

## Runtime architecture

### Launcher and process lock

`ora_vibe_coder.__main__` parses the optional projects directory, settings path, install mode, install home, no-browser flag, and the wrapper, reopen, and quit paths used by desktop launch. Normal launch verifies that the user's Documents folder exists and is readable — reporting one specific sentence and stopping otherwise — then uses it as the discovery root; the optional projects directory remains as temporary-root injection for disposable installations and tests, and no saved projects-home setting takes part in startup. It acquires one application lock for that settings location, writes a permission-restricted local running record, starts the HTTP server, and normally opens the loopback URL. Console-free startup errors and browser-open failures surface through native dialogs (`native_alert`) when launched by the desktop wrapper, with the local address shown for a running server whose browser failed to open.

If another instance owns the lock, `--reopen` (and any wrapper launch) opens the existing recorded local URL and exits with a dedicated status so the Mac Dock icon stays without a second server. An invalid or symbolic-link launch record is not trusted. Shutdown removes the running record and releases the lock.

The Mac launcher is a stay-open application generated at install time with `osacompile` from a JXA source: it owns the Python child through native `NSTask` argument passing (no shells, no polling), handles reopen by rerunning the child with `--reopen`, exits on child-termination notification, and routes Dock Quit or Command-Q through a `--quit` helper that performs the visible-input warning before stopping the server. Its icon is generated locally from the bundled Ora logo through `sips` and `iconutil`. The Windows launcher is a desktop `.lnk` created through built-in PowerShell/WScript.Shell, targeting the matching `pythonw.exe` with the launch entry and settings path passed as data, plus a locally generated `.ico`; the shortcut reopens the running workspace, and Stop Vibe remains the quit route. The Linux desktop-entry route is preserved. The Windows launcher code is covered by focused unit checks that run on macOS with the Windows shell faked, covering shortcut argument quoting for spaced install paths, the icon container, and transactional shortcut-file creation and rollback; no native Windows qualification has been performed.

The server runs in one process with a bounded serving thread. It binds to `127.0.0.1`; it is not a remotely hosted web application.

### Local HTTP server

`ora_vibe_coder.server.LocalServer` serves the static interface and small JSON operations for setup, project selection, workspace selection, reading, association, preparation, copying, continuation, conversation (`/api/converse`, `/api/turn-state`, `/api/conversation`, `/api/review`), readiness, update checking, quit state, and shutdown. Requests are constrained to local origins and expected routes. File operations are mediated by the project layer instead of accepting arbitrary browser file URLs.

The server keeps one in-memory boolean — whether a displayed text input currently holds unsent text — updated through authenticated browser events and read by the native quit path. It never stores the text itself. Update checking reports unavailable until the release owner connects truthful lookup; it performs no network call and installs nothing.

The interface is plain HTML, CSS, and JavaScript with three workspace rails, a conversation pane and a document pane in a resizable split (side-by-side or stacked, either pane expandable, single-pane in narrow windows), and the portable handoff panel below the composer. The browser polls small operation and file-change state — never streamed model output — and stops polling when the page closes. Vendored markdown-it renders local Markdown display content with HTML disabled, images replaced by placeholders, and non-web links stripped; the brand mark is an inline SVG wordmark colored by the theme tokens, and the page loads no image files. Its license remains in the vendor directory and root Notice.

### Conversation runtime

`ora_vibe_coder.conversation` runs one submitted turn as one native Bridge session folder under the project's reserved `.vibe/` directory. The exact user text is written as an inert note before dispatch, images are validated (PNG/JPEG, at most ten, 8 MiB each) and their original bytes retained with the turn, and the worker launches the bundled Bridge as a foreground subprocess with a fixed `[sys.executable, "-m", "bridge", ...]` argument vector — never by importing Bridge's signal-handling runner into a server thread. Each call receives the current Registry, the last five completed real exchanges (a real exchange is a submitted work-purpose message plus its final answer; reliability passes and review calls never count), the current message once, and any unresolved maintenance, which stays supplied beyond the five-turn window until applied or resolved.

`bridge_root()` resolves the runtime at every invocation: the repository's own vendored `components/agent-bridge` first, so a source-tree run always uses the reviewed copy the repository pins, with the copy bundled beside the installed application serving the installed layout — a developer checkout beside the source tree is never preferred; an explicit `BRIDGE_HOME` (tests) overrides the search, and a missing runtime is reported instead of guessed. Live operation handles are held in memory only, bound to their originating project, and admit one work turn per project while serializing turns that share a resolved code or documents location; the records on disk remain the truth for routing, display, and reopening. A late reply and its maintenance always apply to the originating project.

The reply's delimited Registry maintenance block is validated against the app-selected Registry — update blocks carry one or more narrow `find`/`replace` spans, each of which must match the current content exactly once (an empty replacement deletes its span), all spans validate in memory before a single atomic write, and create blocks require no existing Registry; the path is always the application's own resolution, anywhere inside the project folder but never a link or outside it. A valid update or an accepted no-change may dispose of earlier unresolved proposals by naming their exact turn identifiers on the block's optional `resolved:` line — identifiers the request did not supply invalidate the whole block, and anything not named stays supplied. Missing, malformed, stale, or conflicting blocks preserve the document with an unsaved-update notice recorded in the turn records; no second AI call is made for maintenance. Quit drains in-flight turns within their deadline, saves their outcome, then ends owned Bridge children; an interrupted turn keeps its records and is never replayed automatically.

The second-opinion pipeline (Specification and Plan Review stage) runs as its own retained passes under the same records: the authoring model writes a fresh assessment, a second harness evaluates it, and the author revises — optionally iterating the evaluate→revise cycle up to three rounds, reporting residual disagreement honestly. The instructions are vendored text in `ora_vibe_coder/reliability.py`, pinned to `/Users/oracle/ora` revision `526a7379…` with per-file SHA-256 digests: the behavioral preamble, the shared-criteria block supplied identically to all three passes, and the evaluate/revise scaffolds with web verification omitted. Lab diversity is labeled only from model/provider identity the peers' own lifecycle events report — same lab, different labs, or honestly unconfirmed when neither reported it — never inferred from harness names; the reviewer dropdown's default prefers a different harness, labeled with that same honesty. The user breaks remaining ties.

### Project model

`ora_vibe_coder.project.Project` resolves one explicit project root. It reads the optional `Project.md`, document associations, resolved artifacts, and one `Handoff.md`. The project root is never inferred from packet text.

`ProjectStore` owns the project inventory: one recursive read-only walk (`os.walk` with `followlinks=False`, so folder links and traversal loops are never followed) of the discovery root at store creation and on each **Refresh projects** rescan, locating files named exactly `Project.md` at any depth, including directly in the root and beneath archived projects. Each definition's name, parent lineage, and active/archived state are read from its opening metadata; Specifications and other substantive documents are never opened for the inventory. The walk builds the inventory in memory — there is no registry, database, or persistent scan cache — and display labels (`Parent → Name`, complete names preserved) plus the sort order (displayed lineage, folder path as the stable tie-breaker) are composed in Python for the browser to render. Unreadable folders and definitions (permission failures, oversize or badly encoded files, linked definitions) produce per-entry notices while every readable project remains available. The `projects` dict is the handle store and handles are never discarded, so a rescan that removes an entry from the selectable inventory leaves an open session — and its unsent input — attached to its project. A successful overview save or creation updates that single inventory entry from the saved definition without a rescan; a manual folder's first deliberate save thereby adds it to the inventory.

Discovery (`Project.discover`) resolves stage documents from the selected folder's ordinary Markdown. Ranking: a deliberate association whose file exists, then the expected default filename, then a scalar `vibe_document` type label in closed opening frontmatter or ordinary opening metadata, then whole-word role matches in the filename (spec/specification, plan/planning and similar, without unrelated substrings). Within a rank the newest modification time wins, with stable filename order for an exact tie. `Project.md`, `Handoff.md`, recognized renamed outgoing packets (the packet-shape recognizer in `is_outgoing_packet`), duplicate type labels, and files naming conflicting roles are never selected; conflicts are reported for external correction or a deliberate saved association while other documents resolve normally. Code, Checks, and Baseline stay deliberate associations. Discovery identifies documents; it never reports approval.

No lifecycle gate exists anywhere in the application: document completeness, assessment verdicts, approval records, and document fingerprints never control permission to proceed. For Specification and Plan, `status.assessment_facts` reads the document's saved Current review assessment — `Stage`, `Verdict` (COMPLETE or INCOMPLETE), `Basis`, and the noted-deficiency list — and computes applicability against a standard-library SHA-256 (`status.review_basis`) over the assessed document's own substantive content only: normalized line endings, excluding the Current review section, recorded fields, type markers, and their otherwise-empty wrappers. A changed document identifies the assessment as applying to an earlier version; it never disables an action. Assessments saved by earlier versions keep their saved verdict vocabulary untranslated, and because their recorded basis covered several documents, their applicability reads as unconfirmed. A missing findings list displays no count rather than zero.

Associations distinguish these states:

- a role is not linked;
- a linked path is missing (discovery may then resolve the role);
- a linked file is readable;
- a path is rejected because it resolves outside permitted project handling or collides with a special role; and
- the outgoing file changed since the displayed snapshot.

Atomic writes create a temporary sibling, flush it, and replace the destination. A failed stage preserves the previous destination. The project model does not invent backup archives or timestamped handoff copies.

### Settings

Settings store recent resolved project folders and the last project and workspace. They are application preferences, not a project database; no instruction text, drafts, or project edits are stored or restored, and they never determine the project inventory — a missing, moved, or archived recent entry is never reintroduced into the selection list. Projects and artifacts remain ordinary directories and Markdown files.

## Document model

### Project overview

`Project.md` is a small optional association and status overview. It can contain the project name, an optional `Parent` display lineage, the `Project state` field (`ACTIVE` or `ARCHIVED`; a missing state means active and the file is not rewritten for it, and only an unambiguous case-insensitive `ARCHIVED` archives a project), the project description, desired outcome, linked document paths, the repository / code folder, and the separately owned `Programming` field; a retained `Verification` field is legacy history. New projects create `Project.md`, `Registry.md`, `Specification.md`, and `Plan.md` from minimal starter templates, and a failed creation removes only the files that attempt created. Duplicate or unrecognized new metadata is reported on that project's entry and never hides it; saving over such duplicates is refused in the same style as a duplicate `Name`. Opening a folder without one resolves documents normally; description, mission, and goals sections found in the resolved Request or Product Overview are shown as saved, with their source named, without synthesizing a summary.

Ground truth remains the actual product and documents. An overview field reports state; it does not certify a current revision, replace user approval, or suppress a real artifact that the overview cannot represent.

### Source roles

The discoverable roles are the five standard working documents — Registry, Specification, Plan, Programming Result, Verification Report — plus the recognized legacy vocabulary: Request, User Guide, Technical Documentation, Product Overview, Verification Findings, and Report. Existing filenames are kept; explicit association overrides discovery; a bare starter name (`Specification.md`) and the older numbered name are both top discovery rank. The document reader separately lists every saved Markdown/plain-text file beneath the project folder, stopping at nested project roots (a subfolder with its own `Project.md`), plus retained associations with their reading protections; outgoing handoffs and packet-shaped files are excluded, and an untouched starter template is marked Not started.

`Project.md` and `Handoff.md` cannot be selected as ordinary source roles. The former has dedicated overview semantics. The latter is the outgoing snapshot and is excluded — including recognized renamed copies — to prevent recursive packet growth.

### Type labels, review, and approval

`ora_vibe_coder.status` reads a scalar `vibe_document` marker from closed opening YAML frontmatter (parsed without a YAML dependency) or ordinary opening metadata. The label participates in discovery only; it never confers approval.

For Specification and Plan, one `Current review` section holds the external reviewer's saved assessment fields plus the noted-deficiency list; duplicate sections, missing or duplicated fields, wrong-stage names, and malformed bases are reported as issues and never read as a verdict. Preparing or sending a review request never completes the review; the display appears only after the reviewer saves the assessment.

### Status parsing

`ora_vibe_coder.status` reads one field in the opening metadata block. It normalizes Markdown decoration, line endings, trailing spaces, and hard breaks, but does not search body prose or reinterpret arbitrary synonyms.

Specification and Planning use `Status` with `DRAFT`, `IN PROGRESS`, `AWAITING APPROVAL`, or `APPROVED`, plus the narrowly recognized legacy values. Programming reads `Programming` from `Project.md`. The displayed verification verdict comes from the `Verdict` field of the saved current Verification Report; without a report, Build & verify shows "No saved verification result yet." A retained `Verification` field in `Project.md` is labeled legacy and does not override the report. Missing, duplicate, malformed, or unrecognized values become unreported or unknown, and a saved verdict describes the inspected implementation — never automatically newer code.

The UI never writes a successful status because a stage was opened, prepared, copied, or launched.

## Framework delivery

### Maintained Vibe method

The plugin maintains five framework bodies: Specification, Planning, Programming, Verification, and the guided lifecycle. `references/shared-contract.md` supplies common content and handoff rules, including the exact materiality threshold ("causes or is highly likely to cause"; never "can cause"). `references/role-and-assignment.md` defines the coordinator, document secretary, executor, and verifier, and the complete assignment contract. Corrections that the accepted Specification names — source conflicts, discovery/output alignment, optional structured methods, interface design as a second phase within Specification, run sizing within the selected model configuration, and Verification start/result with findings and recommended fixes — are carried in these canonical bodies, never in the thin loaders or duplicated host copies.

Each native skill file is intentionally thin. It loads the shared contract, role source, and exactly one canonical framework. The guided loader also exposes all four stage bodies because guided coordination may need to select the earliest responsible stage. The guided packet remains a supported server capability, but the accepted three-workspace layout no longer presents it as a UI entry.

The Programming framework is a readiness and handoff layer. It does not duplicate the Programming Loop. The packet supplies the generated vendored Loop framework and exactly one host adapter when Programming, guided, or Implement Plan use requires it.

### Programming Loop source and vendored snapshots

The authoritative source is `Golfplan18/ora-programming-loop`; its public release is `ora-commons/ora-programming-loop`. Vibe retains a reviewed copy of the 17 product files at `components/programming-loop` so setup and handoff assembly work offline. Those files and their executable modes match the corresponding public-release product files. The public release separately carries `.ora-public-release-manifest.json`, which describes delivery and is not part of Vibe's vendored product-files tree. The snapshot contains:

- one universal framework;
- six initiating-host adapters;
- one native skill entry;
- reviewer profiles for Claude Code, ZCode, and Qwen Code;
- a transactional installer;
- CC0 and notice files; and
- a semantic version.

The snapshot contains 17 files. Its unchanged upstream README names `Golfplan18/ora-programming-loop` as the sole authoritative source and `ora-commons/ora-programming-loop` as the public source and update route; the Vibe subtree is neither.

`ora_vibe_coder/loop_integrity.py` is the single metadata owner for the authoritative repository, public release repository, imported revision, source tree, and vendored path. It also defines the exact 17-file inventory and calculates Git-compatible blob and nested-tree identities from file bytes and executable modes. Both assembly and handoff import this owner, so a reviewed revision/tree advance has one metadata edit and no stale second pin.

`scripts/assemble_resources.py` reads all 17 regular files, rejects missing, extra, symbolic-link, empty, byte-divergent, or mode-divergent input when its calculated Git tree differs from the reviewed pin, and does so before resource replacement. It then reads the neutral version, synchronizes Vibe plugin manifest versions, assembles a sibling staging directory with the same bytes and modes, verifies its tree, and atomically replaces the plugin resource target. Its optional revision argument can only assert the centrally reviewed revision, not stamp a different one.

### Agent Bridge source and vendored runtime

The authoritative and public source is `ora-commons/agent-bridge`. Vibe retains the reviewed 19 runtime files — the 16-file `bridge/` Python package plus `LICENSE`, `NOTICE`, and `README.md` — at `components/agent-bridge`. `ora_vibe_coder/loop_integrity.py` owns the `BRIDGE_AUTHORITY` pin (authoritative/public repository, imported revision, source tree, vendored path) beside the Loop's, reusing the same Git blob and nested-tree computation; `read_bridge_snapshot` verifies the exact file set, bytes, and modes, tolerates the generated Python caches (`__pycache__` directories and `.pyc` files) a running runtime creates, and rejects extra files, non-cache content inside a cache directory, and symbolic links. The installer verifies that tree before preparing any replacement and installs the one runtime copy beside the application — never into every skill directory — where it runs on the interpreter already running Vibe. Source-tree runs resolve the vendored component of the checkout, which wins over anything beside the source tree; an installed run uses the bundled copy beside the application, and neither consults any developer checkout.

The generated `SOURCE.json` preserves `source: programming-loop` for the standalone installer's compatibility marker. It also records the authoritative repository and exact revision/tree, the public release repository without binding Vibe to a branch-specific public commit, the vendored snapshot path, the component version, and every copied relative path's SHA-256 digest. Handoff checks those generated facts against the shared authority pin, recalculates the complete 17-file Git tree from the packaged bytes and modes, and refuses a divergent snapshot even when its SHA-256 map was regenerated to match the divergence. This identity is not a review certificate or runtime status.

Maintainers must never author changes in either vendored location or edit the generated resource directory by hand. The smallest refresh is manual and reviewed: replace the 17 files under `components/programming-loop` from one authoritative checkout, update the `AUTHORITY` revision and tree in `ora_vibe_coder/loop_integrity.py`, then run `python3 scripts/assemble_resources.py --loop-source components/programming-loop`. Inspect the imported bytes, modes, generated diff, and focused offline parity test together. No service or synchronizer is required.

### Host selection

The packet builder normalizes the selected destination to one of six hosts. It includes only that initiating host's adapter. Selecting a review model from a different vendor does not change the adapter, because the initiating coding tool owns subagent dispatch, result collection, and waiting.

If the destination is free-form or no supported adapter can be established, the packet remains manually deliverable but must not claim native Programming Loop host wiring.

## Handoff construction

`ora_vibe_coder.handoff.prepare_request` validates the purpose and receiving harness, then constructs one ordered Markdown packet:

1. the user's exact input;
2. a visible boundary before framework instructions;
3. shared contract, role source, selected framework, and when applicable the universal Loop framework plus one adapter; Vibe validates the separate vendored 17-file snapshot before assembly;
4. project, authority, protected state, output, and assignment facts;
5. only purpose-appropriate current materials; and
6. known gaps and the next bounded result.

The supported purposes map to the three workspaces: `specification` and `planning` revise the resolved documents; `review-specification` and `review-plan` commission fresh independent assessments; `create-plan` and `implement-plan` prepare forward assignments like any other — no purpose is gated; `programming` and `verification` serve Build & verify (with `Prepare correction` reusing the programming purpose); the guided packet remains available server-side. Revision packets carry the resolved revision destination — the displayed file to revise, or the expected name for a missing output — plus the closed-frontmatter type-label example (`vibe_document: specification` / `vibe_document: plan`). Assessment packets carry the document's current evidence basis and the exact shape of the Current review section the reviewer saves. Every packet names the documents folder and the repository / code folder (or states honestly that none is selected, with the startup directory described as a conversation starting point) and lists any explicitly selected intake material with its destinations. Continue verifies the saved packet still names the current code location before launching in it.

Guided packets contain the guided coordinator and all four actual stage bodies exactly once. Standalone packets contain only their selected stage body. Programming, guided, and Implement Plan packets contain the Loop; other stage packets do not.

The Request is embedded when its role belongs at the destination. Earlier outgoing text, raw planning discussion, reviewer transcripts, and irrelevant stage history are excluded. A missing resolution is disclosed separately from an unreadable file.

The prepared snapshot includes the package version so a recipient can identify the method revision. It also states that preparation made no model call and delivered no text.

## Save, display, and copy integrity

Preparation writes `Handoff.md` atomically and returns the exact saved text for display. The browser stores the prepared snapshot it showed. Copy compares that displayed text with the current saved file before writing to the system clipboard.

If another process changes the saved handoff, Copy raises a conflict and returns the current content. The user must inspect it and prepare again or deliberately select the expected version. The system never copies a hidden new version or only the visible portion of the textarea.

This comparison protects the handoff boundary without maintaining a version database. The current file and displayed snapshot are sufficient.

## Interactive host routes

`ora_vibe_coder.hosts` detects these executables:

| Host | Command identity | Interactive route |
|---|---|---|
| Codex | `codex` | Prompt in a visible terminal, in the selected code folder or the project documents folder. |
| Claude Code | `claude` | Prompt in a visible terminal, in the selected code folder or the project documents folder. |
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

The root installer copies the application, launcher, selected native Vibe entries, selected Programming Loop host resources, and the bundled Agent Bridge runtime — one copy installed beside the application with its own ownership identity inside the same transaction. It validates required sources, the pinned Bridge tree, and host operations before changing the destination; nothing is placed in the Bridge location's hands that a skill directory also receives.

The launcher is platform-specific. On macOS the installer generates the stay-open JXA application (see Launcher and process lock) into the user's Applications folder. On Windows it writes the locally generated `.ico` inside the installation and creates the desktop `.lnk` through built-in PowerShell, targeting the matching `pythonw.exe`; the shortcut is inside the installer's transactional ownership and rollback, and removal deletes it when it is still the installed shortcut. Linux keeps the existing desktop-entry route. Generated launchers are disposable outputs of installation; normal packaging and distribution belong to the separate release work.

The companion boundary is deliberate. Gear 3 and Gear 4 are a separately installed optional aid for Specification and Planning; the Vibe installer does not install them, and no stage depends on them — the methods disclose an unavailable companion and continue the work directly, so nothing stops while Gear is absent or mismatched. The Programming Loop is installed for each host selected in Vibe setup and offered as one structured method; without it the implementing tool works directly under its normal approvals, and refreshing the bundled entries is done by rerunning the supplied Vibe setup with that host selected and restarting the host. Agent Bridge is bundled: setup installs and updates its reviewed runtime beside the application and removes it with the application. A missing bundled runtime disables the in-app conversation honestly — the failure names the missing runtime and no turn is started — and the portable handoff remains available; no other location is guessed.

Updates and removals use one in-process transaction across the selected product targets. Existing owned files are compared with installation metadata. Changed, missing, unowned, or symbolic-link content is preserved or causes a visible refusal rather than silent overwrite.

Removal deletes only installation-owned content. Projects, documents, credentials, unrelated host files, and user-modified entries remain. The result lists retained additions.

### Standalone Loop installer

The vendored `components/programming-loop/scripts/install.py` supports `install`, `remove`, `status`, `recover`, `install-check`, and `remove-check`. It accepts a host and either the normal user home or an explicit host root.

Installation writes a versioned release under a component-owned directory, records source hashes, and switches only the selected host's entry points. Hosts with reviewer profiles receive only their matching selected profile. Failure between staging and switching preserves the prior release and exposes recovery.

Removal compares installed ownership and preserves modified entries. It never contacts a model or provider.

## Security and privacy boundaries

The application is local, but local does not mean every project file is safe to transmit. The system does not scan for secrets, classify sensitive content, or decide a coding tool's data policy.

Relevant controls include:

- loopback-only server binding;
- local-origin and route validation;
- explicit project selection, folder-scoped discovery, and deliberate associations;
- Bridge calls as fixed argument vectors on the bundled runtime, with per-project turn serialization and drained shutdown;
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
| Browser does not open | Server, printed local URL, native dialog | Open the shown local address. |
| Documents folder is unavailable at startup | All project files | Open Vibe again once Documents exists and can be read; nothing is searched in its place. |
| A folder or definition is unreadable during discovery | Every readable project | The entry-level notice names the location; fix access externally and press Refresh projects. |
| Document resolution is absent or broken | Other resolved documents and files | Refresh, then link the intended file or correct the conflicting document. |
| Completeness display shows an unexpected verdict | Document reader | The display reads the resolved document's saved Current review section; it appears after the assessment is saved and the document rereads. |
| A conversation turn fails (sign-in, native permission, tool refusal) | The exact message, images, and request in the `.vibe/` turn records | The failure names its own reason; resolve sign-in or permissions in the tool's own window (the portable handoff can open it there), recheck readiness, and send again. |
| A Registry maintenance block is missing, malformed, stale, or conflicting | The current Registry and the visible answer | Nothing is applied and the notice says so; the proposal stays supplied to later turns until applied or resolved. |
| Vibe is interrupted mid-turn (forced quit, power loss) | Retained `.vibe/` records and documents | Reopening shows the turn as unfinished; nothing is replayed automatically. Resend deliberately if still wanted. |
| The bundled Bridge runtime is missing or divergent | Previous installation and all project data | Reinstall Vibe from a complete release; the installer refuses to replace on a tree mismatch. |
| Handoff save fails | Previous `Handoff.md` | Correct the reported filesystem issue and Prepare Again. |
| Handoff changes after display | Both displayed and current content | Inspect current text, then deliberately prepare/copy again. |
| Host executable is missing | Saved packet and Copy | Install/enable the selected tool or use manual Copy. |
| Terminal launch fails | Saved packet; operation staging is removed | Use Copy or correct the terminal environment. |
| Installer validation fails | Previous installation | Preserve reported content, resolve ownership, then retry. |
| Generated Loop assembly fails | Previous generated resource directory | Maintainers correct the reviewed vendored inputs or pinned provenance and rerun the assembler. |

No recovery step silently selects another coding tool or provider, and no failure marks a stage complete.

## Testing boundaries

The focused suites use temporary projects, temporary homes, fake executables, a fake Bridge runtime, and controlled launch functions. They verify packet ordering and exact inclusion, folder discovery and override, assessment facts and applicability, status parsing, atomic conflict handling, host argument construction and working-directory selection, installation ownership including the generated Mac applet and Windows shortcut logic with faked operations on macOS, transactional recovery, standalone Loop distribution, canonical-to-generated byte parity, the conversation lifecycle (durable records, five-exchange context, routing and serialization, maintenance preservation, quit and reopen), and the second-opinion pipeline's routing, labeling, and bounds.

These checks do not make live model calls, validate provider credentials, accept visual design on behalf of a user, or prove every third-party host release. No native Windows qualification has been performed; the Windows launcher is established by unit checks with faked operations running on macOS only. Public compatibility claims distinguish deterministic package coverage from live qualification.

When changing the system, choose the smallest checks that judge the material changed surface and follow any explicit testing ceiling in the task. Do not add tests for internal serialization merely to duplicate an already proven user-visible behavior.

## Safe maintenance

### Change a Vibe stage method

Edit the owning framework or shared reference, not the five thin loaders. Enumerate every packet that consumes shared text and keep links valid. Preserve the distinction between stage ownership: Specification defines WHAT, Planning defines HOW, Programming hands off to the Loop, and Verification remains independent and read-only.

### Import a Programming Loop change

Make and review Loop behavior changes in `Golfplan18/ora-programming-loop`, then release them through `ora-commons/ora-programming-loop`. To update Vibe, replace all 17 vendored files from that reviewed authoritative revision, update the single `AUTHORITY` revision/tree in `ora_vibe_coder/loop_integrity.py`, and regenerate the embedded resources. Do not hand-edit the Vibe snapshot as though it were an owning source.

### Import an Agent Bridge change

Make and review Bridge changes in `ora-commons/agent-bridge`, then update Vibe the same way: replace the 19 vendored runtime files under `components/agent-bridge` from one reviewed checkout, update the single `BRIDGE_AUTHORITY` revision/tree in `ora_vibe_coder/loop_integrity.py`, and rerun the installer checks. The runtime is not regenerated by `assemble_resources.py` and has no generated mirror; the vendored component and the installed copy beside the application are the only two locations.

### Add a host

First establish a real initiating-host mechanism for fresh execution, separate review, complete result retrieval, bounded waiting, and safe installation/removal. Add one small adapter naming only those mechanics, installer mapping, and a focused distribution expectation. Do not add a universal launcher or imply live qualification from a fixture.

### Change the interface

Keep notice and failure messages visible, modals usable at the supported viewport, and nested pickers above their parent dialogs. Maintain keyboard and accessible labeling. UI work needs direct visual inspection when acceptance depends on appearance; DOM tests alone do not prove visual quality.

### Release discipline

Update neutral version sources, regenerate derived resources, inspect the complete staged diff, and keep notices truthful. Do not hand-edit `SOURCE.json`, generated mirrors, or native manifest versions that the assembler owns.

Use Git as the rollback mechanism. Remove task-owned staging and background processes before declaring work complete.

## License and notices

First-party source and documentation are dedicated under CC0 1.0 Universal. The root `NOTICE.md` retains the vendored markdown-it copyright and MIT terms. Host product names are compatibility identifiers and do not imply endorsement.

## End-to-end control flow

1. **Launch:** the Python entry (owned by the desktop wrapper where present) reads local settings, verifies that Documents exists and is readable, acquires the settings-scoped lock, creates a permission-restricted running record, binds the loopback server, and opens or prints the URL. A second launch reopens the running instance. No project is selected or changed merely by starting the process.
2. **Project selection:** the server has already built the project inventory by walking Documents for `Project.md` definitions at startup; the browser renders the supplied labels and order, keeps archived projects out until the session's **Show archived projects** toggle is enabled, and restores the last project only when discovery currently offers it as active. **Refresh projects** repeats the walk while preserving the selection, workspace, and unsent input. Folders without a definition stay reachable through the explicit **Open existing** browse route; New Project is a distinct deliberate operation, restricted to creating one new child folder under a location inside Documents, and the chosen folder becomes the sole root for discovery, associations, reads, and outgoing replacement. The last project and workspace are remembered without restoring input.
3. **Document resolution:** deliberate associations win while their files exist; otherwise discovery ranks expected names, `vibe_document` labels, and filename role words, newest within a rank. Conflicting or duplicate identities are reported, not guessed. Stage Markdown is displayed read-only; no stage-save endpoint exists.
4. **Workspace and composition:** the browser holds the selected workspace, message draft with attachments, destination, and selected intake material. Switching workspaces or projects preserves that session input; closing the tab is not a save guarantee. No provider sees composition state.
5. **Conversation turn:** the server validates the submission, saves the user note and image originals into a new `.vibe/` turn folder before anything is dispatched, and returns promptly while a bounded worker starts. The worker assembles the request — exact user text first, work-turn instructions and stage framework, current Registry and stage materials, the last five completed exchanges, unresolved maintenance, locations — and runs the bundled Bridge runtime as a foreground subprocess from `bridge_root()`'s resolved location, observing its event stream for aliveness and phase. The handler never blocks on the peer call; the browser polls operation and file-change state.
6. **Reply and maintenance:** the published reply's body is preserved, the visible answer separated from its maintenance block, the block validated against the app-selected Registry, and an update or creation applied atomically. The outcome — including an honest unsaved-update notice — is recorded as one more note in the same session. A second opinion runs the same machinery as purpose-marked passes (author, evaluate, revise) that never count as conversation.
7. **Automatic refresh:** polling rereads changed files, preserves the selected document and reading position, and names the changed files; a displayed prepared snapshot stays its own snapshot. The user's documents remain the display truth; process state never becomes project status.
8. **Portable packet assembly (on request):** the server loads the exact maintained shared sources, selected purpose, role assignment, purpose-appropriate project artifacts, and for Programming, guided, or Implement Plan use the generated Loop plus one normalized host adapter. It places the exact user text first and emits one deterministic Markdown body; no purpose is gated on document state.
9. **Atomic save:** the project layer checks outgoing selection and any expected prior content, writes a temporary sibling, flushes it, and replaces `Handoff.md`. The returned bytes become the displayed snapshot. A failure removes owned staging and leaves the earlier destination in place.
10. **Copy or Continue:** Copy re-reads and compares the snapshot before touching the clipboard. Continue performs the same comparison, validates the selected executable and platform launch route, writes a mode-0600 temporary assignment, and opens a visible terminal in the selected repository / code folder — the project documents folder when none is selected.
11. **External work:** the coding tool applies its normal conversation, account, model, repository, and approval rules. Reviewers save verdicts in the document's Current review section; the document custodian records approval separately. Vibe neither receives tool events nor writes project status in response to them.
12. **Return:** saved artifacts appear through the automatic refresh (or a deliberate Refresh). Vibe re-reads resolved content, review and approval facts, and recognized status fields. Later source changes do not mutate the old prepared snapshot; a new recipient requires Prepare Again.
13. **Shutdown:** Stop Vibe — and Mac app Quit, which first checks the in-memory visible-input flag through the quit state — drains the in-flight conversation turn within its deadline, saving its reply, maintenance, and records, then ends owned Bridge children and the local server; launcher cleanup removes its running record and releases the lock. Closing the browser leaves the server running. Coding tools opened in separate terminals have independent lifetimes and must be ended through their own interface.

## Invariants maintainers must preserve

- Exact user input precedes all packaged instruction text, and a visible boundary distinguishes the two. A refactor that normalizes or summarizes the input changes the product contract even if the resulting prose seems equivalent.
- Displayed, saved, and copied packet content agree byte-for-text after the documented newline handling. A stale display never authorizes replacement or copy of a newly changed outgoing file.
- Each packet contains the shared contract and role source once, the intended stage bodies once, and no prior outgoing packet. Programming, guided, and Implement Plan packets alone contain the Loop; they contain one initiating-host adapter, never an adapter collection.
- Discovery proposes documents; it never proves completeness or approval, never overwrites a conflicting identity, and never targets `Project.md` or the outgoing snapshot. A deliberate association always wins while its file exists. Assessments are advisory recorded facts with an evidence basis over the assessed document's substantive content; a basis mismatch means the assessment applies to an earlier version (or reads as unconfirmed for legacy records), never that work is blocked. Shipped instruction updates alone never invalidate recorded project evidence. Only explicitly chooser-selected files are embedded as material; a path merely found in saved project text is not the user's choice.
- Stage Markdown stays read-only in the application; Vibe writes only the overview, associations, the single outgoing snapshot, and the Registry maintenance its own turns validate. Every conversation turn is saved to the `.vibe/` records before dispatch, replies apply to their originating project only, and unresolved maintenance stays supplied until applied — never silently dropped or resolved by a second AI call.
- The bundled Agent Bridge runtime is one copy, resolved beside the installed application first and from the repository's vendored component only for source-tree runs. Its pinned revision and Git tree gate installation, and a divergent or missing runtime is reported, never guessed around or copied into skill directories.
- One work turn runs per project at a time, turns sharing a resolved code or documents location serialize, and quit drains the in-flight turn within its deadline before ending owned processes. Process life, elapsed time, and last Bridge contact are aliveness facts, never model progress or project completion.
- Source identity for the embedded Loop names the dedicated authority, its exact imported revision/tree, the corresponding public release repository, and the matching 17-file Vibe snapshot. The public delivery manifest is separate from that product-files tree. The shared authority pin controls acceptance; generated version and hashes are supporting facts and cannot bless bytes or modes whose calculated Git tree diverges. Identity checks do not replace substantive review.
- Missing metadata fails open only where truthful partial representation remains possible. It must not become a fabricated approval or hide a readable real artifact. Security, ownership, replacement, and publication boundaries continue to fail explicitly.
- Host launch text is inert data, never a shell program. Long Markdown stays in a file with restrictive permissions, arguments are constructed as arrays or safely quoted wrappers, and an unsupported terminal leaves the saved handoff and Copy path intact.
- Native entries remain loaders. Universal lifecycle behavior belongs in canonical frameworks, and host-specific Programming mechanics belong only in adapters. A new entry that restates the method creates a drift surface and should be consolidated before release.
- Installation is reversible from owned state. Updates never overwrite unowned or modified files silently, removals never delete projects or credentials, and a failed multi-target transaction restores the previous selected product set.
