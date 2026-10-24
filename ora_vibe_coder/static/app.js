"use strict";
const $ = id => document.getElementById(id);
const token = location.hash.slice(1);
const md = window.markdownit({html: false, linkify: false, typographer: false});
md.renderer.rules.image = (tokens, index) => md.utils.escapeHtml(`[Image not loaded: ${tokens[index].content}]`);
const linkOpen = md.renderer.rules.link_open || ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const href = tokens[idx].attrGet("href") || "";
  if (!/^(https?:\/\/|mailto:)/i.test(href)) tokens[idx].attrs = (tokens[idx].attrs || []).filter(([name]) => name !== "href");
  else { tokens[idx].attrSet("target", "_blank"); tokens[idx].attrSet("rel", "noreferrer noopener"); }
  return linkOpen(tokens, idx, options, env, self);
};
let currentId = "", project = null, workspace = "", roles = [], projectsHome = "", projectPaths = {}, projectEntries = [], scanNotices = [], showArchived = false, stopped = false;
let editorExpected = null, editorConflict = null;
let selectorRescan = null, projectScanTimer = null, projectScanning = false, projectScanComplete = false, startupProject = null;
let readerView = null;
let navigationGeneration = 0, projectOpeningGeneration = 0;
let workspaceAnimations = [];
let workspaceReveal = null;
const workspaceMotion = matchMedia("(prefers-reduced-motion: reduce)");
let hostChoices = [], browseHome = "", browseFallback = "", browseNote = "", folderChoice = null, folderState = null, folderLimit = null, fileState = null;
let createUnder = "", parentAutoFill = "", createCode = "", createMaterial = [];
let lastVisibleInput = null, pendingLocal = Promise.resolve();
let appSettings = {warn_skip_review: true, best_guess: false, hide_advisory: false, role_defaults: {}};
let runActive = null, runLast = null, pendingRunConfig = null;
const notifiedRuns = new Set();
const judgmentsSeen = new Set(), sortingSeen = new Set();
const drafts = new Map(), editDrafts = new Map(), materialDrafts = new Map(), messageFileDrafts = new Map(), projectTools = new Map(), buildReplyStages = new Map();
let filePickerTarget = "project";
// Conversation, split view, readiness, and the reliability engine.
let splitMode = "chat", splitFraction = 0.42;
let conversationTurns = [], reviewRuns = [], attachments = [], conversationLoaded = false;
let lastOperation = null, lastFiles = null, pollTimer = null, readinessState = {checking: false, peers: null};
// The live operation state the last conversation render was drawn under, so
// a poll redraws an unfinished turn's message only when that state changed.
let conversationLiveMark = "";
// The run, step and running turn the last poll observed. A run's driver
// starts its next step's turn as soon as the previous one finishes, so a poll
// can miss every terminal operation while the run continues; the mark names
// when the observed run moved, so the conversation can reload the completed
// replies from the retained records.
let conversationRunMark = "";
let reviewerChosen = false, stepReviewerChosen = false, stepReviewerInitialized = false, readinessChain = 0, contactLost = false;
// The acknowledged submissions of running turns, kept per originating project
// and turn until that turn's outcome is known: a failed or capability-rejected
// turn restores its own project's text and images to the composer, and another
// project's send never displaces that recovery.
const pendingDrafts = new Map();
// The composer's draft identity: bumped on every user edit, project switch, or
// restored draft. An acknowledgement consumes the composer only while this is
// still the draft that was submitted — never merely because the text now shown
// happens to equal it, which would let one project's acknowledgement clear
// another project's identical unsent text.
let composerGeneration = 0;
const workspaces = {
  specification: {title: "Specification", purpose: "specification", review: "review-specification", forward: "create-plan", assessment: "specification", transition: "Create Plan", defaultRole: "Specification"},
  plan: {title: "Plan", purpose: "planning", review: "review-plan", forward: "implement-plan", assessment: "planning", transition: "Implement Plan", defaultRole: "Plan"},
  build: {title: "Build & Verify", purpose: "programming", review: "verification", forward: null, assessment: null, transition: "Request repairs", defaultRole: "Verification Report"},
};
// The step-request defaults live on the server (ora_vibe_coder/run.py), shared
// with Run to Completion, so manual and automated requests cannot drift apart.
const firstSpecificationMessage = "Read the relevant documents already in this project folder, including notes, draft requirements, earlier conversations, and recorded errors, plus any files I attached to this message. Check any draft Specification against the current code if a code folder is selected. Identify new facts or conflicts, then update the Specification and Registry as appropriate. Ask me before choosing between contradictory requirements. Do not start the Plan or implementation.";
// The one status function: every last-action result, warning, and running
// operation report lands in the header status bar. Nothing else renders status.
function status(message, kind = "") {
  const bar = $("status-bar");
  bar.textContent = message || "";
  bar.className = kind === "warning" ? "warning" : "";
  renderStatusActivity();
}
function renderStatusActivity() {
  const bar = $("status-bar");
  const endedRunTurn = runLast?.steps?.some(step => step.turn === lastOperation?.turn);
  const active = runActive ? ["starting", "running"].includes(runActive.state)
    : ["starting", "running"].includes(lastOperation?.state) && !endedRunTurn;
  bar.classList.toggle("active", active && !contactLost && !stopped && !bar.classList.contains("warning"));
}
function render(element, text) { element.innerHTML = md.render(text || "Not supplied yet."); }
function draft() {
  const key = `${currentId}:${workspace}`;
  if (!drafts.has(key)) drafts.set(key, {input: "", destination: "", verifier: "", saved: "", packet: null, packetPurpose: "", packetDestination: "", packetPath: "", packetCurrentOnly: false, recoveryPacket: null});
  return drafts.get(key);
}
function messageStage() { return workspace === "build" ? $("build-reply-stage").value : workspaces[workspace]?.purpose; }
function material() {
  if (!currentId) return [];
  if (!materialDrafts.has(currentId)) materialDrafts.set(currentId, []);
  return materialDrafts.get(currentId);
}
function messageFilesFor(id, stage) {
  const key = `${id}:${stage}`;
  if (!messageFileDrafts.has(key)) messageFileDrafts.set(key, []);
  return messageFileDrafts.get(key);
}
function messageFiles() { return currentId && workspace ? messageFilesFor(currentId, workspace) : []; }
function suggestedMessage() {
  return workspace === "specification" && !conversationTurns.some(turn => turn.stage === "specification")
    && !reviewRuns.some(run => run.stage === "specification") ? firstSpecificationMessage : "";
}
function effectiveMessage() { return $("message").value || suggestedMessage(); }
function updateMessageSuggestion() {
  $("message").placeholder = suggestedMessage();
  $("message-suggestion-note").hidden = !suggestedMessage() || !!$("message").value;
  $("message").classList.toggle("has-suggestion", !!suggestedMessage() && !$("message").value);
}
function signature(d) { return JSON.stringify([d.destination, material().map(item => item.path)]); }
const emptySignature = JSON.stringify(["", []]);
function observePacket(id, path, text, keep = null) {
  // A new save only displaces previews of the same outgoing file.
  for (const [key, d] of drafts) if (key.startsWith(`${id}:`) && d !== keep && d.packetPath === path && d.packet !== text) {
    d.saved = ""; d.packet = null; d.packetPurpose = ""; d.packetDestination = ""; d.packetPath = ""; d.packetCurrentOnly = false; d.recoveryPacket = null;
  }
}
function editorSignature(d) { return JSON.stringify([d.name, d.description, d.goals, d.parent, d.state, d.code]); }
function renderProjectDetailsLabel() {
  const unsaved = !!editDrafts.get(currentId)?.dirty;
  $("project-unsaved").hidden = !unsaved;
  $("project-card").setAttribute("aria-label", `Project details${$("project-completion").hidden ? "" : " — reported complete"}${unsaved ? " — unsaved changes" : ""}`);
}
function sizeEditorTextareas() {
  for (const id of ["edit-name", "edit-parent", "edit-description", "edit-goals"]) {
    const field = $(id);
    field.style.height = "auto";
    field.style.height = `${field.scrollHeight + field.offsetHeight - field.clientHeight}px`;
  }
}
function remember() {
  if (!currentId || !workspace) return;
  const d = draft();
  d.destination = $("destination").value;
  if (workspace === "build") d.verifier = $("verification-verifier").value;
  projectTools.set(currentId, d.destination);
  syncVisibleInput();
}
function rememberEditor() {
  if (!currentId || $("editor").hidden) return;
  const d = editDrafts.get(currentId);
  if (!d) return;
  d.name = $("edit-name").value; d.description = $("edit-description").value; d.goals = $("edit-goals").value;
  d.parent = $("edit-parent").value; d.state = $("edit-state").value; d.code = $("edit-code-location").dataset.path || d.code;
  d.expected = editorExpected; d.dirty = editorSignature(d) !== d.saved;
  renderProjectDetailsLabel();
}
function dirty() {
  remember();
  return [...drafts.values()].some(d => signature(d) !== (d.saved || emptySignature)) || [...editDrafts.values()].some(d => d.dirty)
    || ["new-name", "new-description", "new-goals", "new-directory"].some(id => $(id).value) || createCode || createMaterial.length
    || !!$("message").value.trim() || attachments.length > 0 || [...messageFileDrafts.values()].some(files => files.length);
}
async function api(path, data) {
  let response;
  try { response = await fetch(`/api/${path}`, {method: "POST", headers: {"Content-Type": "application/json", "X-Ora-Token": token}, body: JSON.stringify(data)}); }
  catch (_) { throw new Error("The local server is disconnected. Your text is still here: copy it before reopening the app. This page will not reload itself."); }
  const body = await response.json();
  if (!response.ok) { const error = new Error(body.error || "The operation failed; input was retained."); error.current = body.current; error.status = response.status; throw error; }
  return body;
}
function guard(fn) { return async () => { try { await fn(); } catch (error) { status(error.message, "warning"); } }; }
function local(fn) { const run = guard(fn); return () => { pendingLocal = run(); return pendingLocal; }; }
function sendVisibleInput(visible, keepalive) {
  try {
    fetch("/api/input-state", {method: "POST", keepalive: !!keepalive,
      headers: {"Content-Type": "application/json", "X-Ora-Token": token}, body: JSON.stringify({visible})}).catch(() => {});
  } catch (_) { /* best effort only */ }
}
function syncVisibleInput() {
  const visible = !!($("message").value.trim() || attachments.length
    || [...messageFileDrafts.values()].some(files => files.length));
  if (visible === lastVisibleInput) return;
  lastVisibleInput = visible;
  sendVisibleInput(visible);
}
function updateHost() {
  const host = hostChoices.find(h => h.name === $("destination").value);
  // The tool's routine caveats ask nothing of the user, so they live in More.
  $("host-note").textContent = host
    ? `${host.detected ? `${host.name} terminal tool found on this computer.` : `${host.name} terminal tool was not found; Copy still works.`} ${host.notice}`
    : "Choose the coding tool that should receive this assignment. No model or provider is selected by Vibe.";
  $("more-tool").hidden = false;
  renderReadiness();
  applyTitleShift();  // The readiness text sizes the step-3 card the title must clear.
  renderReviewerChoices();
  updateTransitionLabel();
  updateSendState();
  if (!currentId || !workspace) return;
  const d = draft();
  // An external assessment belongs to its saved Reviewer, independently of
  // the stage's writer and any later change to the configured defaults.
  const externalReview = ["review-specification", "review-plan"].includes(d.packetPurpose);
  const recipient = externalReview ? hostChoices.find(h => h.name === d.packetDestination) : host;
  const addressed = !!recipient && d.packetDestination === recipient.name && d.packet !== null;
  const ready = externalReview ? peerFacts(recipient?.id) : selectedReadiness();
  $("continue").textContent = recipient?.desktop_request === "prefilled"
    ? `Open ${recipient.name} desktop with request` : `Open ${recipient?.name || "selected"} app + copy request`;
  $("continue").disabled = !addressed || !recipient.desktop;
  $("continue").title = !recipient?.desktop ? `${recipient?.name || "The selected tool"} desktop app was not found on this computer.`
    : recipient.desktop_request === "prefilled" ? "Opens a new visible desktop chat with a short pointer to the saved full request. Review and send it there."
    : "Copies the full request, then opens the app. Paste it into a new chat there.";
  $("terminal").textContent = `Open ${recipient?.name || "selected tool"} in Terminal`;
  $("terminal").disabled = !addressed || !recipient.detected || !ready?.ready || ready.authentication === "required";
  $("terminal").title = ready?.ready && ready.authentication === "unknown"
    ? "Sign-in is unconfirmed. The terminal tool may ask you to sign in."
    : "Opens the selected tool in Terminal with the saved request when readiness is confirmed.";
  $("prepared-status").textContent = d.packetCurrentOnly
    ? "No new request was saved. Review this file before preparing again; Copy uses this displayed file."
    : d.packet && !addressed
      ? `Prepared for ${d.packetDestination || "another tool"}. Prepare Again for ${host?.name || "the selected tool"}; Copy still uses the displayed request.`
      : "Nothing has been sent. Choose a visible app, Terminal, or Copy.";
}
async function initialize() {
  const data = await api("setup", {});
  hostChoices = data.hosts; browseHome = data.browse_home; browseFallback = data.browse_fallback || browseHome; browseNote = data.browse_note || "";
  appSettings = data.app_settings || appSettings;

  splitFraction = typeof data.split_fraction === "number" ? Math.min(.95, Math.max(.05, data.split_fraction)) : .42;
  applySplit();
  $("version").textContent = data.version || "";
  $("destination").replaceChildren(new Option("Choose a coding tool", ""), ...hostChoices.map(h => new Option(h.name, h.name)));
  $("verification-verifier").replaceChildren(new Option("Ask coordinator to show choices", ""),
    ...hostChoices.map(h => new Option(h.name, h.name)));
  $("setup-hosts").replaceChildren(...hostChoices.map(h => {
    const p = document.createElement(data.installation ? "label" : "p");
    p.append(`${h.name}: ${h.detected ? "command found — account access not checked" : "not found"}`);
    if (!h.detected) {
      // A tool that is missing gets its maker's own install instructions when
      // an established maker page exists; no invented substitute is offered.
      if (h.instructions) {
        p.append(" — ");
        const guide = document.createElement("a");
        guide.href = h.instructions;
        guide.target = "_blank";
        guide.rel = "noopener noreferrer";
        guide.textContent = "install instructions";
        p.append(guide);
      }
    }
    if (data.installation) { const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.value = h.id; p.prepend(checkbox); }
    return p;
  }));
  if (data.installation && hostChoices.length && hostChoices.every(h => !h.detected)) {
    const copy = document.createElement("p");
    copy.textContent = "No coding tool was found. Copy still works without one.";
    $("setup-hosts").append(copy);
  }
  if (data.installation) {
    $("setup-introduction").textContent = "Choose the coding tools to configure. Setup installs Vibe, its bundled Programming Loop product-file snapshot, the bundled Agent Bridge and Ora AI Boost runtimes, and the Ora Vibe Coder launcher — in the shared Applications folder with a Desktop link on macOS. Unselected coding tools and their account settings are preserved.";
    $("install-app").hidden = false; $("remove-app").hidden = false;
  }
  $("setup").hidden = !!data.home;
  for (const id of ["new", "open"]) $(id).disabled = !data.home;
  if (!data.home) return;
  startupProject = data.last_project ? {path: data.last_project} : null;
  await loadProjects();
  if (!currentId && (projectScanning || scanNotices.length))
    status("Project discovery is still checking or could not read some paths. Open shows the paths and Refresh projects retries them.", "warning");
}
async function browseRequest(operation, path, limit = null) {
  try { return await api(operation, limit ? {path, limit} : {path}); }
  catch (error) {
    // A deliberate manual chooser retains its old home-folder fallback. No
    // filesystem probe or fallback search is part of automatic discovery.
    if (limit || path !== browseHome || browseFallback === path || ![400, 403].includes(error.status)) throw error;
    const data = await api(operation, {path: browseFallback});
    status(`Documents could not be read; browsing starts at ${browseFallback}. Project discovery stays in ${projectsHome}.`, "warning");
    return data;
  }
}
async function browseFolders(path) {
  const data = await browseRequest("folders", path, folderLimit); folderState = data;
  $("folder-path").value = data.path;
  $("folder-list").replaceChildren(...data.folders.map(folder => { const b = document.createElement("button"); b.textContent = `▸ ${folder.name}`; b.onclick = guard(() => browseFolders(folder.path)); return b; }));
  $("folder-note").textContent = data.limited ? "Showing the first 500 folders. Enter a location to select another." : "Only folders are listed. No project is created by browsing.";
}
async function pickFolder(title, callback, path = browseHome, limit = null, focusCreate = false) {
  folderChoice = callback; folderLimit = limit; $("folder-title").textContent = title;
  $("folder-new-name").value = "";
  await browseFolders(path); $("folder-picker").hidden = false;
  if (focusCreate) $("folder-new-name").focus();
}
function activeMaterial() {
  if (filePickerTarget === "message") return currentId ? messageFiles() : null;
  // The material chooser serves the open create form; otherwise the project.
  if (!$("create").hidden) return createMaterial;
  return currentId ? material() : null;
}
function renderMaterialChosen() {
  const chosen = activeMaterial();
  const projectList = $("create").hidden ? (currentId ? material() : null) : createMaterial;
  const messageList = messageFiles();
  $("message-files").hidden = !messageList.length;
  for (const [holder, list] of [[$("material-chosen"), chosen], [[$("new-material-list"), $("edit-material-list")][$("create").hidden ? 1 : 0], projectList], [$("message-files"), messageList]]) {
    holder.replaceChildren();
    if (!list) continue;
    if (!list.length && holder.id === "material-chosen") holder.append(Object.assign(document.createElement("p"), {className: "hint", textContent: "No files selected yet."}));
    for (const item of list) {
      const row = document.createElement("div"); row.className = "material-item";
      const name = document.createElement("span"); name.textContent = item.name; name.title = item.path;
      const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "Remove";
      remove.onclick = guard(() => { const at = list.indexOf(item); if (at >= 0) list.splice(at, 1); composerGeneration += 1; renderMaterialChosen(); });
      row.append(name, remove); holder.append(row);
    }
  }
  syncVisibleInput();
}
async function browseMaterialFiles(path = browseHome) {
  const data = await browseRequest("browse-files", path); fileState = data;
  $("file-path").value = data.path;
  $("file-location").textContent = data.path;
  $("file-list").replaceChildren(...data.entries.map(entry => { const b = document.createElement("button"); b.textContent = `${entry.directory ? "▸ " : ""}${entry.name}`; b.onclick = guard(async () => {
    if (entry.directory) { await browseMaterialFiles(entry.path); return; }
    const list = activeMaterial();
    if (list && !list.some(item => item.path === entry.path)) { list.push({name: entry.name, path: entry.path}); composerGeneration += 1; renderMaterialChosen(); }
    status(`${entry.name} selected. Choose more, or choose Done.`);
  }); return b; }));
  $("file-note").textContent = data.limited ? "Showing the first 500 entries. Open a folder to see more." : "Folders open; files are selected. Source files are never changed or moved.";
}
async function openMaterialPicker(target = "project") {
  filePickerTarget = target;
  $("file-title").textContent = target === "message" ? "Add files to this message" : "Add existing material";
  $("file-explain").textContent = target === "message"
    ? "Choose Markdown or text files for the next AI message, including files outside this project folder. Their contents accompany only that message; the originals stay where they are."
    : "Choose notes or documents for AI to organize into this project's Registry, Specification, or Plan. Files stay where they are; nothing is copied or sent until you prepare a request.";
  if (activeMaterial() === null) { status("Choose or create a project first; material belongs to a project."); return; }
  await browseMaterialFiles(browseHome); renderMaterialChosen(); $("file-picker").hidden = false;
}
async function loadProjects(rescan = false) {
  const data = await api(rescan ? "rescan" : "projects", {});
  roles = data.roles; projectsHome = data.home;
  projectEntries = data.projects;
  scanNotices = data.notices || [];
  projectScanning = !!data.scanning; projectScanComplete = !!data.complete;
  projectPaths = Object.fromEntries(data.projects.map(entry => [entry.id, entry.path]));
  $("home").textContent = `Projects are discovered in: ${data.home}`;
  renderProjectOptions();
  if (!$("open-form").hidden) renderOpenList();
  clearTimeout(projectScanTimer);
  // Observe only the scan already in progress; this never starts a new scan.
  if (projectScanning && !stopped) projectScanTimer = setTimeout(() => {
    loadProjects().catch(error => status(error.message, "warning"));
  }, 300);
  if (startupProject && !currentId) {
    const entry = projectEntries.find(p => p.path === startupProject.path && p.available !== false);
    if (entry) {
      startupProject = null;
      if (!entry.archived) {
        try {
          const opened = await api("open", {path: entry.path});
          await chooseProject(opened.id);
        } catch (_) { /* A disappeared project remains available through deliberate Open. */ }
      }
    } else if (!projectScanning) startupProject = null;
  }
}
function visibleProjects() { return projectEntries.filter(p => showArchived || !p.archived); }
function renderProjectOptions() {
  // The server supplies the composed lineage labels and their order; the
  // browser only renders them, marking archives and duplicate names' paths.
  // A currently open archived project stays named until the user leaves it.
  const visible = projectEntries.filter(p => showArchived || !p.archived || p.id === currentId);
  const duplicates = new Set(visible.filter((p, index) => visible.some((q, other) => other !== index && q.label === p.label)).map(p => p.label));
  $("project").replaceChildren(new Option(projectScanning ? "Finding projects…" : !projectScanComplete && scanNotices.length ? "Choose a project — some paths unavailable" : "Choose a project", ""), ...visible.map(p => {
    const option = new Option(p.label + (p.archived ? " — Archived" : "") + (p.available === false ? " — Unavailable; refresh to retry" : "") + (duplicates.has(p.label) ? ` — ${p.path}` : ""), p.id);
    option.disabled = p.available === false;
    option.title = p.notice ? `${p.path} — ${p.notice}` : p.path;
    return option;
  }));
  if (currentId && !visible.some(p => p.id === currentId) && project) {
    const option = new Option(`${project.name} — Open folder`, currentId);
    option.title = project.root;
    $("project").add(option);
    projectPaths[currentId] = project.root;
  }
  $("project").value = currentId;  // Refreshing never silently switches projects.
}
function renderOpenList() {
  const list = $("project-list");
  list.replaceChildren();
  const visible = visibleProjects();
  if (!visible.length) list.append(Object.assign(document.createElement("p"), {textContent: projectScanComplete
    ? `No ${showArchived ? "" : "active "}projects with a Project.md definition were found under ${projectsHome || "the selected projects folder"}.`
    : "No readable projects are currently listed. Discovery is still running or could not read every path; see below and use Refresh projects to retry."}));
  for (const entry of visible) {
    const item = document.createElement("button");
    item.append(Object.assign(document.createElement("span"), {className: "entry-label", textContent: entry.label + (entry.archived ? " — Archived" : "") + (entry.available === false ? " — Unavailable; refresh to retry" : "")}));
    item.append(Object.assign(document.createElement("span"), {className: "entry-location", textContent: entry.notice ? `${entry.path} — ${entry.notice}` : entry.path}));
    item.disabled = entry.available === false;
    item.onclick = guard(async () => {
      const result = await api("open", {path: entry.path});
      $("open-form").hidden = true; await loadProjects(); await chooseProject(result.id);
    });
    list.append(item);
  }
  $("scan-notices").textContent = scanNotices.join(" ");
}
function statuses() {
  for (const rail of document.querySelectorAll(".rail")) {
    const key = {specification: "specification", plan: "planning", build: "verification"}[rail.dataset.stage];
    const s = rail.dataset.stage === "build" ? project.verification.status : project.statuses[key];
    rail.querySelector(".status-icon").textContent = s.icon;
    rail.setAttribute("aria-label", `${workspaces[rail.dataset.stage].title} — reported ${s.label}; source ${s.source}`);
    const a = project?.assessments?.[key];
    if (a?.approval_unknown) rail.setAttribute("aria-label", `${rail.getAttribute("aria-label")}. The approved version was not retained; its applicability is unconfirmed.`);
    else if (a?.change?.state === "pending") rail.setAttribute("aria-label", `${rail.getAttribute("aria-label")}. Change comparison pending; approval applicability is unconfirmed.`);
    rail.title = rail.getAttribute("aria-label");
    rail.setAttribute("aria-expanded", String(workspace === rail.dataset.stage));
  }
}
function renderOverviewSources() {
  const holder = $("overview-sources");
  holder.replaceChildren();
  holder.hidden = project.raw !== null || !Array.isArray(project.overview_sources) || !project.overview_sources.length;
  if (holder.hidden) return;
  const heading = document.createElement("h3"); heading.textContent = "Existing information in this folder"; holder.append(heading);
  for (const source of project.overview_sources) {
    for (const [name, text] of Object.entries(source.sections)) {
      const block = document.createElement("div"); block.className = "overview-source";
      const label = document.createElement("p"); label.className = "source-name";
      label.textContent = `${name} — from ${source.name} (${source.role}), shown as saved`;
      const body = document.createElement("div"); render(body, text);
      block.append(label, body); holder.append(block);
    }
  }
}
function renderConflicts() {
  const existing = $("discovery-conflicts");
  existing?.remove();
  if (!project.discovery_conflicts?.length) return;
  const noteElement = document.createElement("p");
  noteElement.id = "discovery-conflicts"; noteElement.className = "hint conflicts";
  noteElement.textContent = `Document conflicts: ${project.discovery_conflicts.join(" ")}`;
  document.querySelector(".status-row").after(noteElement);
}
function assessmentText(a) {
  if (a?.unreadable) return {label: "COULD NOT READ", kind: "working", note: a.unreadable};
  if (!a || (!a.present && !a.untouched)) return {label: "NOT REVIEWED", kind: "neutral", note: a?.change?.reason || "No assessment has been recorded."};
  if (a.untouched) return {label: "NOT STARTED", kind: "neutral", note: "The starter template has not been filled in."};
  if (!a.verdict || a.issues?.length) return {label: "REPORT ERROR", kind: "working", note: (a.issues || []).join(" ") || a.reason || "The saved review has no clear verdict."};
  const upper = (a.outcome || a.verdict).toUpperCase();
  const label = upper === "COMPLETE" ? "PASSED" : upper;
  const kind = label === "PASSED" ? "complete" : label === "NOT PASSED" ? "incomplete" : "working";
  const note = a.applies === "earlier" ? "The saved review describes an earlier version. Its assessment and findings remain in Current review."
    : a.change?.reason ? a.change.reason
    : a.applies === "unconfirmed" ? "The verdict is saved; its applicability to the current document version is unconfirmed."
    : "Click to see the recorded assessment in the document.";
  return {label, kind, note};
}
function reportStatusText(status, missing) {
  if (!status) return missing;
  if (status.unreadable) return "COULD NOT READ";
  if (status.label.startsWith("Unknown") || status.label === "REPORT ERROR") return "REPORT ERROR";
  if (status.untouched) return "NOT STARTED";
  if (status.label === "Not reported") return "VERDICT MISSING";
  if (/^NOT PASSED — (REVIEW|REVISION) INCOMPLETE/.test(status.label)) return "INCOMPLETE";
  if (status.label === "COMPLETE") return "PASSED";
  if (status.label.startsWith("NOT PASSED")) return "NOT PASSED";
  return status.label.toUpperCase();
}
function verdictKind(label) {
  return label === "PASSED" ? "complete" : label === "NOT PASSED" ? "incomplete"
    : ["INCOMPLETE", "CHANGED", "REPORT ERROR", "VERDICT MISSING", "COULD NOT READ"].includes(label) ? "working" : "neutral";
}
function verificationVerdict(status, path) {
  if (!path || !status) return {label: "NOT VERIFIED", kind: "neutral"};
  const label = reportStatusText(status, "NOT VERIFIED");
  return {label, kind: verdictKind(label)};
}
function showStatusExplanation(id, path, reason, evidence = []) {
  const element = $(id);
  element.replaceChildren();
  element.hidden = false;
  if (reason) {
    const note = document.createElement("p"); note.textContent = reason; element.append(note);
  }
  for (const excerpt of evidence) {
    const quote = document.createElement("blockquote");
    quote.textContent = typeof excerpt === "string" ? excerpt : excerpt.text || excerpt.literal || "";
    if (quote.textContent) element.append(quote);
  }
  if (path) {
    const source = document.createElement("details"), title = document.createElement("summary"), location = document.createElement("p");
    title.textContent = `Source: ${path.split("/").pop()}`;
    location.textContent = path;
    source.append(title, location); element.append(source);
  }
}
function showReportStatus(element, report, path, missing) {
  const verdict = element.id === "assessment" ? verificationVerdict(report, path)
    : {label: path ? reportStatusText(report, missing) : missing, kind: verdictKind(path ? reportStatusText(report, missing) : missing)};
  element.textContent = verdict.label;
  element.className = `assessment ${verdict.kind}`;
  element.title = path ? `${report?.unreadable || report?.literal || report?.label || "Status unavailable"}\nSource: ${path}` : missing;
  showStatusExplanation(element.id === "result-status" ? "result-status-note" : "assessment-note", path,
    report?.unreadable || report?.reason || (path ? report?.basis_note || "The saved conclusion describes the work inspected; it does not verify later changes." : missing === "NO RESULT" ? "No Programming Result is selected or found." : "No Verification Report is selected or found."),
    report?.kind === "neutral" ? report?.evidence || [] : []);
  const open = guard(async () => {
    const entry = project?.reader?.find(file => file.path === path || `${project.root}/${file.path}` === path);
    if (!entry) return;
    readerAnchor = entry.path;
    $("document").value = entry.path;
    await readDocument(entry.path);
  });
  element.onclick = path ? event => { event.preventDefault(); event.stopPropagation(); return open(); } : null;
  element.onkeydown = path ? event => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault(); event.stopPropagation(); element.click();
  } : null;
  element.tabIndex = path ? 0 : -1;
}
function confirmImplementationBasis() {
  const concerns = [];
  for (const [key, label, consequence] of [
    ["specification", "Specification", "Verification may lack a clear account of the intended behavior."],
    ["planning", "Plan", "The coding tool may make inconsistent implementation choices."]
  ]) {
    const assessment = project?.assessments?.[key];
    if (["PASSED", "COMPLETE"].includes((assessment?.outcome || assessment?.verdict)?.toUpperCase()) && ["current", "unconfirmed"].includes(assessment.applies) && !assessment.unreadable && !assessment.issues?.length) continue;
    const state = assessment?.unreadable ? "could not be read"
      : assessment?.issues?.length ? "has an unclear review record"
      : assessment?.applies === "earlier" ? "was changed after its review"
      : (assessment?.outcome || assessment?.verdict) === "NOT PASSED" ? "was reviewed as NOT PASSED"
      : "has no PASSED review for its current version";
    concerns.push(`${label} ${state}. ${consequence}`);
  }
  if (!concerns.length) return Promise.resolve(true);
  const dialog = $("implementation-warning"), content = $("implementation-warning-text");
  content.replaceChildren(...concerns.map(value => Object.assign(document.createElement("p"), {textContent: value})));
  return new Promise(resolve => {
    const back = $("implementation-back"), proceed = $("implementation-proceed");
    function finish(accepted) {
      back.removeEventListener("click", cancel); proceed.removeEventListener("click", accept);
      dialog.removeEventListener("cancel", cancel);
      dialog.close(); resolve(accepted);
    }
    function cancel(event) { event?.preventDefault(); finish(false); }
    function accept() { finish(true); }
    back.addEventListener("click", cancel); proceed.addEventListener("click", accept);
    dialog.addEventListener("cancel", cancel); dialog.showModal();
  });
}
function deliversImplementation(purpose) { return purpose === "implement-plan" || purpose === "programming"; }
function renderAssessment() {
  const element = $("assessment");
  const config = workspaces[workspace];
  if (!config?.assessment) {
    $("review-step-title").textContent = "Independently verify the implementation";
    showReportStatus($("result-status"), project?.programming_result?.status,
                     project?.programming_result?.path, "NO RESULT");
    showReportStatus(element, project?.verification?.status,
                     project?.verification?.path, "NOT VERIFIED");
    return;
  }
  const assessment = project?.assessments?.[config.assessment];
  let {label, kind, note} = assessmentText(assessment);
  $("result-status-note").hidden = true;
  showStatusExplanation("assessment-note", assessment?.path, note + (project?.plan_notice && workspace === "plan" ? " " + project.plan_notice : ""), assessment?.issues?.length ? assessment.evidence || [] : []);
  $("review-step-title").textContent = `Review the ${config.title}`;
  element.textContent = label;
  element.className = `assessment ${kind}`;
  element.title = note;
  const openAssessment = guard(async () => {
    const a = project?.assessments?.[config.assessment];
    const path = a?.path;
    if (path && project?.reader?.some(file => file.path === path || `${project.root}/${file.path}` === path)) {
      const entry = project.reader.find(file => file.path === path || `${project.root}/${file.path}` === path);
      if ($("document").value !== entry.path) $("document").value = entry.path;
      const opened = await readDocument(entry.path);
      // The same reader-identity protection, after the read finishes: a
      // document selected while this read was underway owns the reader and
      // its reading position, so the completing action scrolls neither.
      if (readerView !== opened) return;
    }
    const heading = [...$("reader").querySelectorAll("h2")].find(h => h.textContent.trim().toLowerCase() === "current review");
    if (heading) { $("reader").scrollTo({top: 0}); heading.scrollIntoView({block: "start", behavior: "smooth"}); }
    else status(a?.unreadable ? `The assessed document could not be read, so whether it records an assessment is unknown. ${a.unreadable}`
              : a?.present ? "The recorded assessment has no Current review heading to show." : "No assessment has been recorded in this document yet.");
  });
  element.onclick = event => { event.preventDefault(); event.stopPropagation(); return openAssessment(); };
  element.onkeydown = event => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault(); event.stopPropagation(); element.click();
  };
}
// Approval is the user's decision, independent of the review's outcome.
function updateApprovePlan() {
  const button = $("approve-plan"), config = workspaces[workspace];
  if (!config?.assessment) { button.hidden = true; return; }
  button.hidden = false;
  const a = project?.assessments?.[config.assessment];
  const approved = ["APPROVED", "Approved Implementation Plan", "Approved product specification"].includes(project?.statuses?.[config.assessment]?.label);
  button.textContent = approved && !a?.change && !a?.approval_unknown ? `${config.title} approved` : `Approve the ${config.title}`;
  button.disabled = (approved && !a?.change && !a?.approval_unknown) || !a?.path || a?.expected == null || !!a.unreadable;
  button.title = approved ? `The ${config.title} records status: APPROVED.`
    : `Save your approval of the displayed ${config.title}, whatever its review says.`;
}
function readerDefault() {
  const config = workspaces[workspace];
  const files = project?.reader || [];
  const roles = workspace === "build" ? ["Verification Report", "Programming Result"] : [config.defaultRole];
  for (const role of roles) {
    const rolePath = project?.documents?.[role]?.path;
    const match = rolePath ? files.find(file => file.path === rolePath || `${project.root}/${file.path}` === rolePath) : null;
    if (match) return match.path;
  }
  return "";
}
let readerAnchor = null;
function renderReader() {
  const select = $("document");
  const files = project?.reader || [];
  const held = readerAnchor && files.some(file => file.path === readerAnchor) ? readerAnchor : readerDefault();
  // The document comes first, then the project, so the document type stays
  // visible even when the project name is long.
  const prefixes = project ? [project.name, project.root.split(/[\\/]/).pop()].sort((a, b) => b.length - a.length) : [];
  select.replaceChildren(...files.map(file => {
    const prefix = prefixes.find(name => file.name.startsWith(`${name} — `));
    const name = (prefix ? file.name.slice(prefix.length + 3) : file.name).replace(/\.(md|markdown|txt)$/i, "");
    return new Option(`${name}${file.not_started ? " — Not started" : ""} — ${project.name}`, file.path);
  }));
  select.value = held || "";
}
async function refreshProject() {
  if (!currentId) return;
  const id = currentId;
  const refreshed = await api("project", {id});
  if (id !== currentId) return;
  project = refreshed;
  compareChangedDocuments();
  renderProjectOptions();
  $("project-name").textContent = project.name;
  renderOverviewSources(); renderConflicts(); statuses();
  const complete = ["COMPLETE", "PASSED"].includes(project.programming_result?.status?.label) && project.verification?.status?.label === "PASSED";
  $("project-completion").hidden = !complete;
  renderProjectDetailsLabel();
  $("project-completion").title = complete ? "The selected reports say programming PASSED and verification PASSED for the work they describe. This is not user approval or verification of later changes." : "";
  $("rails").hidden = false;
  $("workspace-head").hidden = false;
  if (workspace) {
    if ($("packet-tools").hidden) $("prepared-path").value = project.handoff_path;
    renderMoreRequest();
    renderAssessment();
    updateApprovePlan();
    renderReader();
    $("transition").disabled = false;
    renderRepairs();
    renderQuestions();
    // A saved verification result decides Build's step-7 direction, so a
    // report that changed while the workspace was open moves it here too.
    if (workspace === "build") updateBuildNextStep();
  }
}
async function readFile(path, element) {
  const view = readerView = {id: currentId, workspace, path, element};
  // This read's own identity: it is returned to the caller so whoever started
  // the read can tell, once it finishes, whether the reader they see is still
  // the one this read produced — the same comparison the guards below make
  // internally. Every non-throwing exit returns the identity, landed or
  // superseded; comparing it against the live readerView is the caller's test.
  const entry = (project?.reader || []).find(file => file.path === path);
  if (!path) {
    // No document is resolved yet: an empty reader adds no sentence, because
    // the document picker above it already says what can be opened.
    element.replaceChildren();
    return view;
  }
  if (!entry) {
    // The requested document is no longer part of the project — typically
    // deleted on disk. The pane clears honestly instead of reporting a
    // failed read of a file the project no longer lists, and the anchor lets
    // go so the next render falls back to the workspace default.
    if (readerView !== view) return view;
    element.replaceChildren();
    const message = document.createElement("p");
    message.textContent = `${path.split("/").pop()} is no longer present in this project; it may have been deleted outside the app. Choose another document to read.`;
    element.append(message);
    readerAnchor = null;
    return view;
  }
  element.textContent = `Loading ${entry.name}…`;
  let result;
  try { result = await api("read-file", {id: view.id, path}); }
  catch (error) {
    if (readerView !== view) return view;
    element.textContent = `Could not read ${entry.name}. ${error.message}`;
    throw error;
  }
  if (readerView !== view) return view;
  element.replaceChildren();
  const caption = document.createElement("p"); caption.className = "reader-caption";
  caption.textContent = `File: ${result.path}${result.not_started ? " — Not started" : ""}`;
  element.append(caption);
  if (result.text !== null) { const body = document.createElement("div"); render(body, result.text); element.append(body); }
  else { const reason = document.createElement("p"); reason.textContent = result.reason; element.append(reason); }
  if (result.needs_selection) {
    const button = document.createElement("button"); button.textContent = "Select this outside-project reference and read it";
    button.onclick = guard(async () => {
      if (readerView !== view) return;
      try { await api("approve-reference", {id: view.id, role: result.role, path: result.path}); }
      catch (error) { if (readerView === view) throw error; return; }
      if (readerView !== view) return;
      await readFile(path, element); await refreshProject();
    }); element.append(button);
  }
  return view;
}
async function readDocument(path = $("document").value) {
  if (!workspace) return;
  $("packet-tools").hidden = true; $("raw").value = "";
  return await readFile(path, $("reader"));
}
function showPacket(text, purpose) {
  const currentOnly = draft().packetCurrentOnly;
  readerView = {id: currentId, workspace, role: null, kind: "packet", element: $("reader")};
  render($("reader"), text); $("raw").value = text; $("packet-tools").hidden = false;
  $("raw-details").hidden = false;
  $("delivery-note").textContent = currentOnly
    ? `This is the current saved file (${{"create-plan": "request to create the Plan", "implement-plan": "implementation request", "review-specification": "external Specification review request", "review-plan": "external Plan review request", verification: "independent verification request", programming: "programming or correction request"}[purpose] || `${workspaces[workspace].title} request`}); no new request was prepared. Review it, then Prepare again to replace it. Copy uses this displayed file.`
    : "Saved request. The delivery actions are under More: Desktop opens a visible app, Terminal opens its command-line tool, and Copy lets you paste elsewhere. Confirm receipt and execution in the coding tool.";
  $("prepared-path").value = draft().packetPath || project?.handoff_path || "";
  renderMoreRequest();
  updateHost();
}
function showAbsentPacket() {
  const recovery = draft().recoveryPacket || "";
  readerView = {id: currentId, workspace, role: null, kind: "absent", element: $("reader")};
  $("reader").textContent = "The saved request is no longer present. Prepare again to save a new request.";
  $("packet-tools").hidden = false;
  $("raw").value = recovery;
  $("raw-details").hidden = !recovery;
  $("raw-details").open = !!recovery;
  $("delivery-note").textContent = recovery
    ? "The earlier displayed Markdown is retained below for recovery. It is not the current saved file, so the delivery buttons are unavailable. Prepare again to save a new request."
    : "No earlier Markdown is available in this tab. Prepare again to save a new request.";
  renderMoreRequest();
  updateHost();
}
// The saved-request section of More appears whenever a request path is known.
function renderMoreRequest() { $("more-request").hidden = !$("prepared-path").value; }
function openingWorkspace(state) {
  // A prepared outgoing request is not work on its destination stage. Only
  // actual document content and the existing live/retained work records count.
  const stageRank = stage => ({planning: 1, plan: 1, "review-plan": 1,
    build: 2, programming: 2, implementation: 2, "programming-result": 2,
    result: 2, verification: 2, correction: 2}[stage] || 0);
  const plan = project.assessments?.planning;
  let rank = plan?.path && plan.expected != null && !plan.untouched ? 1 : 0;
  for (const result of [project.programming_result, project.verification]) {
    if (result?.path && !result.status?.untouched && !result.status?.unreadable) rank = 2;
  }
  for (const stage of ["programming", "verification"]) {
    const progress = project.statuses?.[stage]?.label;
    if (progress && !["NOT STARTED", "Not reported"].includes(progress) && !progress.startsWith("Unknown")) rank = 2;
  }
  for (const record of [...conversationTurns, ...reviewRuns, state.run?.active || {},
    ...(state.run?.last?.steps || []), state.operation || {}]) {
    rank = Math.max(rank, stageRank(record.stage || record.step));
  }
  return ["specification", "plan", "build"][rank];
}
function finishWorkspaceReveal() {
  for (const animation of workspaceAnimations) animation.cancel();
  workspaceAnimations = [];
  if (!workspaceReveal) return;
  workspaceReveal.snapshot.remove();
  workspaceReveal.page.style.clipPath = workspaceReveal.clip;
  workspaceReveal.page.style.pointerEvents = workspaceReveal.pointerEvents;
  workspaceReveal = null;
}
function positionRails(animate = false) {
  const rails = [...document.querySelectorAll(".rail")];
  // Capture the visible position before cancelling: a rapid second click
  // continues from where the rail actually is, without jumping backwards.
  const before = rails.map(rail => rail.getBoundingClientRect().left);
  finishWorkspaceReveal();
  const page = document.querySelector(".main-col"), oldBox = page.getBoundingClientRect();
  let snapshot = null, frozen = null;
  if (animate && !workspaceMotion.matches) {
    // The inert shadow tree reuses the existing styles, but its IDs and
    // controls are isolated from the real page. cloneNode copies no handlers.
    snapshot = document.createElement("div");
    snapshot.className = "workspace-snapshot";
    snapshot.inert = true; snapshot.setAttribute("aria-hidden", "true");
    const shadow = snapshot.attachShadow({mode: "closed"}), styles = new CSSStyleSheet();
    styles.replaceSync([...document.styleSheets].map(sheet => [...sheet.cssRules].map(rule => rule.cssText).join("\n")).join("\n"));
    shadow.adoptedStyleSheets = [styles];
    frozen = page.cloneNode(true);
    Object.assign(frozen.style, {width: "100%", height: "100%"});
    shadow.append(document.querySelector(".glyph-defs").cloneNode(true), frozen);
    for (const name of ["--spine-cols", "--title-shift"]) snapshot.style.setProperty(name, getComputedStyle(page).getPropertyValue(name));
    const originals = [page, ...page.querySelectorAll("*")];
    const copies = [frozen, ...frozen.querySelectorAll("*")];
    originals.forEach((source, index) => {
      const copy = copies[index];
      if (source instanceof HTMLTextAreaElement || source instanceof HTMLSelectElement
          || source instanceof HTMLInputElement && source.type !== "file") copy.value = source.value;
    });
    Object.assign(snapshot.style, {position: "fixed", left: `${oldBox.left}px`, top: `${oldBox.top}px`,
      width: `${oldBox.width}px`, height: `${oldBox.height}px`, margin: "0", zIndex: "1", pointerEvents: "none",
      overflow: "hidden", background: getComputedStyle(document.querySelector(".app")).backgroundColor});
    document.body.append(snapshot);
    originals.forEach((source, index) => { copies[index].scrollTop = source.scrollTop; copies[index].scrollLeft = source.scrollLeft; });
  }
  page.style.order = String(Math.max(0, Object.keys(workspaces).indexOf(workspace)) * 2 + 1);
  for (const rail of rails) rail.setAttribute("aria-expanded", String(workspace === rail.dataset.stage));
  if (!snapshot) return;
  const after = rails.map(rail => rail.getBoundingClientRect().left);
  const moving = rails.map((rail, index) => ({rail, index})).filter(({index}) => Math.abs(before[index] - after[index]) >= 1);
  if (!moving.length) { snapshot.remove(); return; }
  const forward = before[moving[0].index] > after[moving[0].index];
  const edge = positions => forward
    ? Math.min(...moving.map(({index}) => positions[index]))
    : Math.max(...moving.map(({rail, index}) => positions[index] + rail.offsetWidth));
  const clip = (box, boundary, old) => {
    const left = forward !== old;
    const amount = left ? boundary - box.left : box.right - boundary;
    return left ? `inset(0px 0px 0px ${amount}px)` : `inset(0px ${amount}px 0px 0px)`;
  };
  const reveal = workspaceReveal = {snapshot, frozen, page, clip: page.style.clipPath, pointerEvents: page.style.pointerEvents};
  page.style.pointerEvents = "none";  // A click on the old view cannot activate a different new action.
  const timing = {duration: 1000, easing: "ease-in-out", fill: "both"};
  rails.forEach((rail, index) => {
    const distance = before[index] - after[index];
    if (Math.abs(distance) < 1) return;
    workspaceAnimations.push(rail.animate([{transform: `translateX(${distance}px)`}, {transform: "translateX(0)"}],
      timing));
  });
  const newBox = page.getBoundingClientRect();
  for (const [element, box, old] of [[snapshot, oldBox, true], [page, newBox, false]]) {
    workspaceAnimations.push(element.animate([{clipPath: clip(box, edge(before), old)}, {clipPath: clip(box, edge(after), old)}], timing));
  }
  // Loading happens behind the complete old page. Start only when its caller
  // has refreshed the stage and finished the new document (or its error view).
  for (const animation of workspaceAnimations) { animation.pause(); animation.currentTime = 0; }
  reveal.animations = workspaceAnimations;
  return reveal;
}
function startWorkspaceReveal(reveal) {
  if (!reveal || workspaceReveal !== reveal) return;
  for (const animation of reveal.animations) animation.play();
  Promise.all(reveal.animations.map(animation => animation.finished)).then(() => {
    if (workspaceReveal === reveal) finishWorkspaceReveal();
  }).catch(() => {});  // A later choice owns cancellation and cleanup.
}
workspaceMotion.addEventListener("change", () => { if (workspaceMotion.matches) finishWorkspaceReveal(); });
document.addEventListener("keydown", event => {
  if (!workspaceReveal) return;
  const covered = workspaceReveal.page.contains(event.target);
  finishWorkspaceReveal();  // Keyboard work always sees the selected real page first.
  const typing = event.target instanceof HTMLTextAreaElement
    || event.target instanceof HTMLInputElement && !["button", "submit", "reset", "checkbox", "radio", "file", "range", "color"].includes(event.target.type)
    || event.target.isContentEditable;
  const activation = event.key === "Enter" && !(typing && (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey || event.isComposing))
    || event.key === " " && !typing;
  if (covered && activation) {
    // This action was aimed at the covered page. Require a fresh activation;
    // ordinary typing (including spaces and newlines) still reaches its field.
    event.preventDefault(); event.stopImmediatePropagation();
  }
}, true);
async function chooseProject(id) {
  const opening = ++projectOpeningGeneration, generation = ++navigationGeneration;
  startupProject = null;
  remember(); rememberEditor();
  if (id !== currentId) pendingRunConfig = null;
  currentId = id; project = null; workspace = "";
  positionRails();
  renderProjectOptions();
  conversationTurns = []; reviewRuns = []; conversationLoaded = false; $("file-picker").hidden = true; filePickerTarget = "project";
  runActive = null; runLast = null; judgments.clear(); sortingState.clear(); judgmentsSeen.clear(); sortingSeen.clear();
  $("run-banner").hidden = true; $("questions-box").hidden = true; $("repairs-box").hidden = true;
  composerGeneration += 1;  // The composer now holds another project's draft context.
  // undefined means unobserved; only a successful status read may report idle (null).
  stopPolling(); readinessChain += 1; lastOperation = undefined; lastFiles = null; contactLost = false; conversationLiveMark = ""; conversationRunMark = "";
  $("status-bar").dataset.operationKey = "";
  status("");
  renderRunBanner();
  $("project").value = id;
  $("editor").hidden = true; $("stage-panel").hidden = true;
  $("rails").hidden = true; $("workspace-head").hidden = true;
  $("packet-tools").hidden = true;
  $("project-completion").hidden = true;
  renderProjectDetailsLabel();
  for (const field of ["reader", "assessment", "result-status"]) $(field).textContent = "";
  $("prepared-path").value = ""; renderMoreRequest();
  $("overview-sources").replaceChildren(); $("overview-sources").hidden = true;
  $("raw").value = "";
  $("project-name").textContent = id ? "Selected project is not loaded" : "Choose or create a project";
  renderConversation();
  if (!id) { renderReadiness(); return; }
  await refreshProject();
  if (opening !== projectOpeningGeneration) return;
  const notices = [];
  try { await loadConversation(); }
  catch (error) {
    if (opening !== projectOpeningGeneration) return;
    notices.push(`Conversation history could not be loaded: ${error.message} Automatic refresh will try again.`);
  }
  if (opening !== projectOpeningGeneration) return;
  let state = {};
  try { state = await api("turn-state", {id}); }
  catch (error) {
    if (opening !== projectOpeningGeneration) return;
    notices.push(`Live work status could not be loaded: ${error.message} Whether work is running is unknown; automatic refresh will check again.`);
  }
  if (opening !== projectOpeningGeneration) return;
  // An early rail click owns the page choice, while this project opening
  // still owns startup. Only a later project opening cancels that startup.
  if (generation === navigationGeneration) await chooseWorkspace(openingWorkspace(state));
  if (opening !== projectOpeningGeneration) return;
  if ("operation" in state) {
    updateRunState(state.run);
    updateOperation(state.operation);
  }
  if (notices.length) status(`${notices.join(" ")} Available project documents remain open.`, "warning");
  startPolling();
  // Startup explicitly initiates this project's first readiness check; the
  // poll chain that follows only reads, so it ends when the check finishes
  // rather than restarting the worker on every poll.
  refreshReadiness(true).catch(() => {});
}
async function chooseWorkspace(next) {
  if (!currentId || !project) { status("Choose or reopen a project successfully first."); return; }
  if (!(next in workspaces)) return;
  const generation = ++navigationGeneration, id = currentId, previous = workspace;
  remember(); rememberEditor(); workspace = next; $("editor").hidden = true;
  readerView = null;  // Any older document read no longer owns this stage.
  const reveal = positionRails(!!previous && previous !== next);
  readerAnchor = null;  // Each workspace starts from its own default document.
  const config = workspaces[workspace];
  const d = draft();
  // The coding tool belongs to the project, while each stage keeps its own
  // message and prepared handoff. A changed tool leaves an old packet stale.
  if (projectTools.has(currentId)) d.destination = projectTools.get(currentId);
  $("destination").value = d.destination;
  if (workspace === "build") $("verification-verifier").value = d.verifier || "";
  updateMessageSuggestion(); renderMaterialChosen();
  $("build-reply-choice").hidden = workspace !== "build";
  $("build-reply-stage").value = buildReplyStages.get(currentId) || "programming";
  applyStageDefaults();
  $("stage-title").textContent = config.title;
  $("work-step-title").textContent = `Work with AI on ${workspace === "build" ? "the implementation" : `the ${config.title}`}`;
  $("result-step").hidden = workspace !== "build";
  $("review-step-number").textContent = workspace === "build" ? "6" : "5";
  $("next-step-number").textContent = workspace === "build" ? "7" : "6";
  updateTransitionLabel();
  $("next-step-title").textContent = {specification: "Create the Plan", plan: "Implement the Plan", build: "Correct the implementation"}[workspace];
  $("next-explain").textContent = {
    specification: `Prepare a complete request to create or revise the Plan from this Specification. Your unsent step 4 message and its attached files are included.`,
    plan: "Prepare a saved implementation request containing the Specification, Plan, and Ora Programming instructions. Your unsent step 4 message names a narrower part when you want one; it is included with its attached files.",
    build: "Ask the implementation AI to correct the findings in the Verification Report. Send in Vibe Coder, or copy the complete request into your existing implementation chat."
  }[workspace];
  $("review-explain").textContent = config.assessment
    ? `Ask the selected tool to assess whether the current ${config.title} sufficiently guides the next work. Its advisory verdict is saved in this document.`
    : "Ask an AI coordinator to arrange a fresh, independent Ora Verification review and save a truthful Verification Report. Send in Vibe Coder, or copy the complete request into another AI chat. The implementation AI must not verify its own work.";
  $("more-review").hidden = !config.assessment;
  $("stage-panel").hidden = false;
  applySplit();  // The title-over-spine shift can only be measured once the row is visible.
  $("packet-tools").hidden = true; $("raw").value = "";
  $("reader").textContent = `Loading ${config.title}…`;
  updateSecondOpinion();
  updateApprovePlan();
  api("workspace", {workspace}).catch(() => {});
  syncVisibleInput();
  try {
    try { await refreshProject(); }
    catch (error) {
      if (generation !== navigationGeneration || id !== currentId) return;
      $("reader").textContent = `Could not load ${config.title}. ${error.message}`;
      throw error;
    }
    if (generation !== navigationGeneration || id !== currentId) return;
    if (d.packet !== null) showPacket(d.packet, d.packetPurpose);
    else if (d.recoveryPacket !== null) showAbsentPacket();
    else await readDocument();
  } finally {
    if (generation === navigationGeneration && id === currentId) startWorkspaceReveal(reveal);
  }
}
function codeLine(element, path) {
  element.dataset.path = path || "";
  element.textContent = path ? `Selected: ${path}` : "No code folder selected.";
}
async function openEditor() {
  if (!currentId || !project) { status("Choose or reopen a project successfully first."); return; }
  remember(); await refreshProject();
  const held = editDrafts.get(currentId);
  const d = held?.dirty ? held : {name: project.name, description: project.description, goals: project.goals,
    parent: project.parent || "", state: project.archived ? "ARCHIVED" : "ACTIVE",
    code: project.paths.Code || "", expected: project.raw, dirty: false};
  if (!held?.dirty) d.saved = editorSignature(d);
  editDrafts.set(currentId, d);
  editorExpected = d.expected;
  for (const field of ["name", "description", "goals", "parent"]) $(`edit-${field}`).value = d[field];
  $("edit-state").value = d.state;
  codeLine($("edit-code-location"), d.code);
  $("edit-location").textContent = `${project.raw === null ? "Will create only: " : "Edit: "}${project.root}/Project.md`;
  $("editor").hidden = false; $("edit-conflict").hidden = true;
  sizeEditorTextareas();
  renderMaterialChosen();
  $("editor").scrollTop = 0;
}
function refreshSelector() {
  if (!selectorRescan) {
    // Opening the picker rescans before showing the list. A failed rescan
    // keeps the last usable list and says it may be out of date; the
    // selection and any unsent work are never touched.
    selectorRescan = loadProjects(true)
      .catch(() => status("The project list could not be refreshed; the last list is kept and may be out of date.", "warning"))
      .finally(() => { selectorRescan = null; });
  }
  return selectorRescan;
}
for (const type of ["focus", "pointerdown"]) $("project").addEventListener(type, guard(refreshSelector));
$("project").addEventListener("keydown", event => {
  if (["Enter", " "].includes(event.key)) guard(refreshSelector)();
});
$("project").onchange = guard(async () => {
  // Route the dropdown through the same open path as "Open existing", so the
  // chosen project is remembered and restored after a restart.
  const id = $("project").value;
  const previousPath = projectPaths[id];
  if (selectorRescan) await selectorRescan;
  if (!id) { await chooseProject(""); return; }
  const result = await api("open", {path: projectPaths[id] || previousPath});
  await chooseProject(result.id);
});
for (const rail of document.querySelectorAll(".rail")) rail.onclick = guard(() => chooseWorkspace(rail.dataset.stage));
$("project-card").onclick = guard(() => openEditor());
$("edit-close").onclick = () => { rememberEditor(); $("editor").hidden = true; };
$("editor").addEventListener("beforeinput", event => {
  if (["edit-name", "edit-parent"].includes(event.target.id) &&
      ["insertLineBreak", "insertParagraph"].includes(event.inputType)) event.preventDefault();
});
$("editor").oninput = event => {
  if (["edit-name", "edit-parent"].includes(event.target.id))
    event.target.value = event.target.value.replace(/[\r\n]+/g, " ");
  rememberEditor(); sizeEditorTextareas();
};
window.addEventListener("resize", () => { if (!$("editor").hidden) sizeEditorTextareas(); });
function setEditorCode(path) {
  codeLine($("edit-code-location"), path);
  const d = editDrafts.get(currentId);
  if (d) { d.code = path; d.dirty = editorSignature(d) !== d.saved; renderProjectDetailsLabel(); }
}
$("edit-code-browse").onclick = guard(() => pickFolder("Choose the repository / code folder", path => { rememberEditor(); setEditorCode(path); }, project.code_folder ? project.code_folder.split("/").slice(0, -1).join("/") : browseHome));
$("edit-code-create").onclick = guard(() => pickFolder("Create the repository / code folder", path => { rememberEditor(); setEditorCode(path); }, project.code_folder || browseHome, null, true));
$("edit-code-none").onclick = guard(async () => { rememberEditor(); setEditorCode(""); });
$("edit-material").onclick = guard(() => openMaterialPicker());
$("edit-save").onclick = guard(async () => {
  rememberEditor(); const id = currentId, d = editDrafts.get(id);
  const submitted = {...d}, expected = editorExpected;
  $("edit-save").disabled = true;
  try {
    const savedProject = await api("save", {id, expected, name: submitted.name, description: submitted.description, goals: submitted.goals,
      paths: {...(project?.paths || {}), Code: submitted.code || ""}, parent: submitted.parent, state: submitted.state});
    const latest = editDrafts.get(id), newer = latest && editorSignature(latest) !== editorSignature(submitted);
    if (newer) { latest.expected = savedProject.raw; latest.saved = editorSignature(submitted); latest.dirty = true; }
    else editDrafts.delete(id);
    await loadProjects();  // The single updated entry rerenders the selector; the open project is not switched.
    if (currentId !== id) return;
    project = savedProject; editorExpected = savedProject.raw;
    if (!newer) $("editor").hidden = true;
    renderProjectDetailsLabel();
    await refreshProject();
    if (workspace && $("packet-tools").hidden) await readDocument();
    status(newer ? "Project.md saved with the submitted values. Your newer edits are retained and still need Save." : "Project.md saved. Stage documents and result fields were preserved.");
  }
  catch (error) { if (error.status === 409 && currentId === id) { editorConflict = error.current; $("edit-current").textContent = error.current === null ? "Project.md is now absent." : error.current; $("edit-conflict").hidden = false; } throw error; }
  finally { $("edit-save").disabled = false; }
});
$("edit-reviewed").onclick = () => { editorExpected = editorConflict; rememberEditor(); $("edit-conflict").hidden = true; status("Current saved overview acknowledged. Your input is unchanged; review it and use Save explicitly."); };
function parentLineageFor(path) {
  const entry = projectEntries.find(p => p.path === path);
  return entry ? (entry.lineage || entry.label) : "";
}
function applyCreateUnder(path) {
  createUnder = path;
  $("new-under").value = path;
  // Prefill Parent from that project's complete display lineage; the user
  // may change or clear it before creating.
  const next = parentLineageFor(path);
  if (!$("new-parent").value || $("new-parent").value === parentAutoFill) {
    parentAutoFill = next;
    $("new-parent").value = next;
  }
}
function updateNewProposed() { $("new-location").textContent = `Proposed directory: ${createUnder || projectsHome}/${$("new-directory").value}`; }
$("new").onclick = () => {
  startupProject = null;
  applyCreateUnder(projectsHome); updateNewProposed();
  codeLine($("new-code-location"), createCode);
  renderMaterialChosen();
  $("create").hidden = false;
};
$("new-under-browse").onclick = guard(() => pickFolder("Choose the folder to create under", async path => { applyCreateUnder(path); updateNewProposed(); }, projectsHome, projectsHome));
$("new-code-browse").onclick = guard(() => pickFolder("Choose the repository / code folder", path => { createCode = path; codeLine($("new-code-location"), createCode); }, browseHome));
$("new-code-create").onclick = guard(() => pickFolder("Create the repository / code folder", path => { createCode = path; codeLine($("new-code-location"), createCode); }, browseHome, null, true));
$("new-code-none").onclick = guard(() => { createCode = ""; codeLine($("new-code-location"), ""); });
$("new-material").onclick = guard(() => openMaterialPicker());
$("new-directory").oninput = updateNewProposed;
$("create-close").onclick = () => { $("create").hidden = true; };
$("create-save").onclick = guard(async () => {
  const fields = ["directory", "name", "description", "goals"], submitted = Object.fromEntries(fields.map(field => [field, $(`new-${field}`).value]));
  submitted.parent = $("new-parent").value; submitted.under = createUnder || projectsHome; submitted.code = createCode;
  $("create-save").disabled = true;
  try {
    const result = await api("create", submitted);
    materialDrafts.set(result.id, createMaterial.slice());
    const newer = fields.some(field => $(`new-${field}`).value !== submitted[field]) || $("new-parent").value !== submitted.parent || createCode !== submitted.code || createMaterial.length !== (materialDrafts.get(result.id) || []).length;
    if (!newer) { $("create").hidden = true; for (const field of fields) $(`new-${field}`).value = ""; $("new-parent").value = ""; parentAutoFill = ""; createCode = ""; createMaterial = []; codeLine($("new-code-location"), ""); }
    await loadProjects(); await chooseProject(result.id);
    if (newer) status("Project created with the submitted values. Your newer New Project input is retained; it has not been saved to this project.");
  } finally { $("create-save").disabled = false; }
});
$("open").onclick = guard(async () => {
  startupProject = null;
  const data = await api("setup", {});
  renderOpenList();
  const list = $("recent-projects");
  list.replaceChildren();
  if (!data.recent_projects.length) list.append(Object.assign(document.createElement("p"), {textContent: "No recent project folders yet."}));
  for (const path of data.recent_projects) {
    const item = document.createElement("button"); item.textContent = path;
    item.onclick = guard(async () => {
      const result = await api("open", {path});
      $("open-form").hidden = true; await loadProjects(); await chooseProject(result.id);
    });
    list.append(item);
  }
  $("open-form").hidden = false;
});
$("open-close").onclick = () => { $("open-form").hidden = true; };
$("show-archived").onchange = () => { showArchived = $("show-archived").checked; renderProjectOptions(); renderOpenList(); };
$("refresh-projects").onclick = guard(async () => {
  // Rescanning preserves the selection, workspace, and unsent input; it never switches projects.
  await loadProjects(true);
  status(projectScanning ? "Refreshing projects. Open shows paths still being checked; readable projects appear as they are found."
    : scanNotices.length ? "Some project paths could not be read. Open shows the paths; Refresh projects retries them."
      : "Projects refreshed. Unsent input and the selected workspace are unchanged.");
});
$("open-browse").onclick = guard(() => pickFolder("Choose an existing project", async path => { $("open-form").hidden = true; const result = await api("open", {path}); await loadProjects(); await chooseProject(result.id); }));
$("document").onchange = guard(async () => { readerAnchor = $("document").value; await readDocument(); });
$("back-document").onclick = guard(async () => { await readDocument(); });
$("copy-path").onclick = guard(async () => {
  const path = $("prepared-path").value;
  if (!path) throw new Error("Prepare a request first to see its saved file path.");
  try { await navigator.clipboard.writeText(path); status("Saved file path copied. Paste it into your coding tool or file browser."); }
  catch (_) { $("prepared-path").focus(); $("prepared-path").select(); status("Clipboard access was unavailable. The saved file path is selected; use your browser's Copy command."); }
});
// The visible unsent step 4 text and its attached files travel with the
// prepared request now that the separate instruction box is gone. Step-forward
// defaults live server-side; the external review file carries its own explicit
// instruction.
function composerInstruction() {
  return $("message").value.trim();
}
function composerMaterial(stage, id) {
  return [...new Set([...(id === currentId ? material() : []), ...messageFilesFor(id, stage)].map(item => item.path))];
}
async function preparePurpose(purpose, instruction = null) {
  remember(); const d = draft(), id = currentId, selectedWorkspace = workspace, submitted = signature(d), view = readerView;
  const externalReview = ["review-specification", "review-plan"].includes(purpose);
  const submittedDestination = externalReview
    ? hostChoices.find(h => h.id === $("step-reviewer").value)?.name || "" : d.destination;
  if (!submittedDestination) throw new Error(externalReview ? "Choose the Reviewer first." : "Choose a coding tool first.");
  const path = purpose === "implement-plan" ? project?.implementation_request_path : project?.handoff_path;
  $("prepare").disabled = true; $("review").disabled = true; $("transition").disabled = true;
  try {
    const result = await api("prepare", {id, stage: purpose, input: instruction === null ? composerInstruction() : instruction, destination: submittedDestination,
      context: {material: composerMaterial(selectedWorkspace, id)},
      upstream: (() => { const a = project?.assessments?.[purpose === "create-plan" ? "specification" : purpose === "implement-plan" ? "planning" : ""]; return a?.path && a.expected != null ? {path: a.path, expected: a.expected} : null; })(),
      expected: d.packetPath === path ? d.packet : null});
    if (id === currentId && result.file_state) lastFiles = result.file_state;
    observePacket(id, result.path, result.text);
    d.packet = result.text; d.packetPurpose = purpose; d.packetDestination = submittedDestination; d.packetPath = result.path; d.packetCurrentOnly = false; d.recoveryPacket = null;
    if (instruction === null) d.saved = submitted;
    if (id !== currentId || selectedWorkspace !== workspace) return;
    let shownView = null;
    if (readerView === view) { showPacket(d.packet, purpose); shownView = readerView; }
    await refreshProject();
    status(!shownView || readerView !== shownView ? "Request saved. Your selected document remains open; choose this workspace again to view the saved request."
      : purpose === workspaces[selectedWorkspace].review
      ? "External review file saved; its path is under More. Preparing it did not run the review; the reviewer must save its verdict in the document."
      : "Request saved; the path and delivery actions are under More. Review it, then open your coding tool with it or copy the full Markdown.");
  }
  catch (error) {
    if (error.status !== 409) throw error;
    const name = purpose === "implement-plan" ? "implementation request" : "Handoff.md";
    observePacket(id, path, error.current, d);
    d.recoveryPacket = typeof error.current === "string" ? null : (d.packet ?? "");
    d.packet = typeof error.current === "string" ? error.current : null;
    d.packetPurpose = purpose; d.packetDestination = ""; d.packetPath = path; d.packetCurrentOnly = typeof error.current === "string";
    if (id !== currentId || selectedWorkspace !== workspace) return;
    if (readerView !== view) { status("The saved request changed while you chose another document. Your selected document remains open; choose this workspace again to review the current request."); return; }
    if (typeof error.current === "string") {
      showPacket(error.current, purpose);
      status(`The saved ${name} already exists or changed. Review it, then choose Prepare again to replace it. Nothing was overwritten.`);
    } else {
      showAbsentPacket();
      status(`The saved ${name} was removed. ${d.recoveryPacket ? "The earlier Markdown is retained below; " : ""}Choose Prepare again to save a new request.`);
    }
  }
  finally { $("prepare").disabled = false; updateSecondOpinion(); $("transition").disabled = false; }
}
$("prepare").onclick = local(() => preparePurpose(workspaces[workspace].review, `Review the current ${workspaces[workspace].title} and record the assessment.`));
$("review").onclick = local(runReview);
// Step 6's one-click handoff: Send to the step-3 tool (or Open in Terminal for
// Hermes and Qwen Code), with Copy request beside it. Build's steps keep their
// explanatory dialog and reuse the same delivery path.
$("transition").onclick = local(() => {
  const config = workspaces[workspace];
  if (!config) return Promise.resolve();
  // Build's step 7 follows the saved verification result: correction after a
  // completed NOT PASSED, verification again while the review is unfinished.
  if (workspace === "build") return buildStepDialog(buildNextAction());
  return deliverStep(config.forward);
});
$("copy-request").onclick = local(() => {
  const config = workspaces[workspace];
  if (!config) return Promise.resolve();
  if (workspace === "build") return buildStepDialog(buildNextAction());
  return deliverStep(config.forward, "copy");
});
$("request-result").onclick = local(() => buildStepDialog("result"));
$("build-reply-stage").onchange = () => { buildReplyStages.set(currentId, $("build-reply-stage").value); composerGeneration += 1; applyStageDefaults(); renderReadiness(); updateSendState(); };
$("add-message-files").onclick = guard(() => openMaterialPicker("message"));
$("approve-plan").onclick = local(async () => {
  if (!currentId) return;
  const id = currentId;
  $("approve-plan").disabled = true;
  try {
    const config = workspaces[workspace], assessment = project?.assessments?.[config.assessment];
    const result = await api("approve-document", {id, stage: config.assessment, expected: assessment.expected, document: assessment.path});
    if (id !== currentId) return;
    if (result.file_state) lastFiles = result.file_state;
    // The confirmation and the refreshed Plan appear only after the save
    // succeeded, which the server has confirmed by reading the file back.
    await refreshProject();
    if (id !== currentId) return;
    await readDocument();
    status(`${config.title} approved: status: APPROVED saved in ${String(result.document).split("/").pop()}. Approval leaves the review unchanged.${result.warning ? " " + result.warning : ""}`);
  } finally { if (id === currentId) updateApprovePlan(); }
});
$("copy").onclick = local(async () => {
  const d = draft(), id = currentId, selectedWorkspace = workspace, view = readerView;
  if (deliversImplementation(d.packetPurpose)) {
    await refreshProject();
    if (id !== currentId || selectedWorkspace !== workspace || view !== readerView) return;
    if (!await confirmImplementationBasis()) return;
    if (id !== currentId || selectedWorkspace !== workspace || view !== readerView) return;
  }
  try {
    const result = await api("copy", {id, displayed: d.packet, purpose: d.packetPurpose === "implement-plan" ? "implement-plan" : null});
    if (readerView !== view) return;
    try { await navigator.clipboard.writeText(result.text); if (readerView === view) status("Full raw Markdown copied from the displayed saved request. Paste it where you intend to use it; the app has not sent it."); }
    catch (_) { if (readerView !== view) return; $("raw-details").open = true; $("raw").focus(); $("raw").select(); status("Clipboard access was denied or unavailable. The full raw Markdown is selected below; use your browser's Copy command. No copy success is claimed."); }
  } catch (error) {
    if (error.status === 409) {
      observePacket(id, d.packetPath, error.current, d);
      d.packetDestination = "";
      d.recoveryPacket = typeof error.current === "string" ? null : (d.packet ?? "");
      d.packet = typeof error.current === "string" ? error.current : null;
      d.packetCurrentOnly = typeof error.current === "string";
      if (readerView !== view) return;
      if (id === currentId && selectedWorkspace === workspace && readerView === view) {
        if (typeof error.current === "string") { showPacket(error.current, d.packetPurpose); $("raw-details").open = true; status("The saved request changed — review this current file before another Copy. Prepare again before delivering it."); }
        else { showAbsentPacket(); error.message = "The saved request is now absent. Your input and the earlier Markdown are retained; use Prepare Again to save a new request. Nothing was copied."; }
      }
    }
    else if (readerView !== view) return;
    throw error;
  }
});
$("copy-current").onclick = local(async () => {
  if (!currentId || !workspace) throw new Error("Choose a project and stage first.");
  const instruction = effectiveMessage();
  const destination = $("destination").value;
  const stage = messageStage();
  if (!destination) throw new Error("Choose a coding tool first.");
  if (!instruction.trim()) throw new Error("Write the instruction you want to copy first.");
  const id = currentId, selectedWorkspace = workspace;
  const selectedMaterial = [...new Set([...material(), ...messageFiles()].map(item => item.path))];
  const sameRequest = () => id === currentId && selectedWorkspace === workspace && effectiveMessage() === instruction
    && $("destination").value === destination && messageStage() === stage
    && JSON.stringify([...new Set([...material(), ...messageFiles()].map(item => item.path))]) === JSON.stringify(selectedMaterial);
  if (stage === "programming") {
    await refreshProject();
    if (!sameRequest()) return;
    if (!await confirmImplementationBasis()) return;
    if (!sameRequest()) return;
  }
  const result = await api("preview", {id, stage, input: instruction,
    destination, context: {material: selectedMaterial}});
  if (!sameRequest()) { if (id === currentId && selectedWorkspace === workspace) status("The instruction, coding tool, or selected files changed while the request was prepared. Copy again for the current choices."); return; }
  try {
    await navigator.clipboard.writeText(result.text);
    if (!sameRequest()) return;
    status(`Full ${workspaces[workspace].title} request copied. Paste it into a visible AI conversation; no file was replaced and nothing was sent.${attachments.length ? " Attach your images separately." : ""}`);
  } catch (_) {
    if (!sameRequest()) return;
    readerView = {id, workspace, role: null, element: $("reader")};
    render($("reader"), result.text); $("raw").value = result.text;
    $("packet-tools").hidden = false; $("raw-details").hidden = false; $("raw-details").open = true;
    $("delivery-note").textContent = `Copy-ready ${workspaces[workspace].title} request for another AI. This request was not saved or sent, and it did not replace the saved request file.`;
    $("raw").focus(); $("raw").select();
    status("Clipboard access was unavailable. The full request is selected in the document pane; copy it there. No file was replaced or sent.");
  }
});
window.addEventListener("beforeunload", event => { if (dirty()) { event.preventDefault(); event.returnValue = ""; } });
window.addEventListener("pagehide", () => { stopPolling(); if (!stopped) sendVisibleInput(false, true); });
$("destination").onchange = () => { remember(); updateHost(); if (currentId && workspace && draft().packet) status("Coding tool changed. Prepare Again to create a snapshot addressed to this tool."); };
async function deliverPrepared(route) {
  remember(); const d = draft(), id = currentId, selectedWorkspace = workspace, packet = d.packet, destination = d.packetDestination;
  const externalReview = ["review-specification", "review-plan"].includes(d.packetPurpose);
  if (!d.packet || !destination || (!externalReview && destination !== d.destination)) throw new Error("Prepare Again for this coding tool before opening it.");
  const host = hostChoices.find(item => item.name === destination);
  const samePacket = () => id === currentId && selectedWorkspace === workspace && packet === d.packet
    && destination === d.packetDestination && (externalReview || destination === $("destination").value);
  if (deliversImplementation(d.packetPurpose)) {
    await refreshProject();
    if (!samePacket()) return;
    if (!await confirmImplementationBasis()) return;
    if (!samePacket()) return;
  }
  const button = $(route === "desktop" ? "continue" : "terminal");
  button.disabled = true;
  try {
    if (route === "desktop" && host.desktop_request === "copy") {
      const copied = await api("copy", {id, displayed: packet, purpose: d.packetPurpose === "implement-plan" ? "implement-plan" : null});
      if (!samePacket()) return;
      try { await navigator.clipboard.writeText(copied.text); }
      catch (_) { throw new Error("Clipboard access was unavailable. Use Copy full request to select the text, then open the app yourself. Nothing was launched."); }
      if (!samePacket()) return;
    }
    const result = await api("continue", {id, displayed: packet, destination,
      purpose: d.packetPurpose === "implement-plan" ? "implement-plan" : null, route});
    status(result.message);
  }
  catch (error) { if (error.status === 409) status("The saved request changed. Use Copy to review the current saved text, or Prepare Again. Nothing was launched."); else throw error; }
  finally { updateHost(); }
}
$("continue").onclick = local(() => deliverPrepared("desktop"));
$("terminal").onclick = local(() => deliverPrepared("terminal"));
$("help").onclick = () => { $("help-panel").hidden = false; };
$("check-updates").onclick = guard(async () => {
  $("check-updates").disabled = true;
  try {
    const result = await api("check-updates", {});
    // The result line carries the answer itself, plus the release-page link
    // when there is one; nothing was downloaded or installed by the check.
    const status = $("update-status");
    status.replaceChildren();
    status.append(result.label);
    if (result.url) {
      status.append(" ");
      const link = document.createElement("a");
      link.href = result.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Release page";
      status.append(link);
    }
    status(result.note);
  } finally { $("check-updates").disabled = false; }
});
function themeMode() { return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); }
function updateThemeToggle() { $("theme-toggle").textContent = themeMode() === "dark" ? "Light mode" : "Dark mode"; }
$("theme-toggle").onclick = () => {
  const mode = themeMode() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = mode;
  try { localStorage.setItem("ovc-theme", mode); } catch (_) { /* storage unavailable: the choice applies to this tab only */ }
  updateThemeToggle();
};
updateThemeToggle();
$("install-app").onclick = guard(async () => {
  $("install-app").disabled = true;
  try {
    const result = await api("install", {hosts: [...document.querySelectorAll("#setup-hosts input:checked")].map(box => box.value)}); $("installation-result").textContent = `Installed Vibe ${result.version}. Open the Ora Vibe Coder launcher at ${result.launcher}. ${result.note}`; $("close-setup").hidden = false; status("Installation finished. Open the launcher; Vibe then finds your projects in your Documents folder.");
  } finally { $("install-app").disabled = false; }
});
$("remove-app").onclick = guard(async () => {
  if (!confirm("Remove the installed Vibe application and the selected coding-tool entries? Projects, documents, settings, credentials, and unrelated files are preserved; your Desktop link is removed with them, while the shared Applications launcher is kept because another account may use it.")) return;
  $("remove-app").disabled = true;
  try {
    const result = await api("remove", {hosts: [...document.querySelectorAll("#setup-hosts input:checked")].map(box => box.value)});
    $("installation-result").textContent = result.retained.length ? `Removal finished. User additions or edits were retained at: ${result.retained.join(", ")}` : "Removal finished. Projects, documents, settings, credentials, and unrelated coding-tool files were preserved.";
    $("close-setup").hidden = false; status("Removal finished. Close this source installer when you are ready.");
  } finally { $("remove-app").disabled = false; }
});
$("close-setup").onclick = guard(async () => { await api("stop", {}); stopped = true; status("Installer stopped. Open Ora Vibe Coder from its launcher."); });
$("help-close").onclick = () => { $("help-panel").hidden = true; };
$("folder-go").onclick = guard(() => browseFolders($("folder-path").value));
$("folder-up").onclick = guard(() => browseFolders(folderState.parent));
$("folder-create").onclick = guard(async () => {
  const name = $("folder-new-name").value.trim();
  const result = await api("create-folder", {parent: folderState.path, name});
  $("folder-new-name").value = "";
  status(`Created ${result.path}.`);
  await browseFolders(result.path);
});
$("folder-select").onclick = guard(async () => { await folderChoice(folderState.path); $("folder-picker").hidden = true; });
$("folder-cancel").onclick = () => { $("folder-picker").hidden = true; status("Folder selection cancelled. No project work started."); };
$("file-cancel").onclick = () => { $("file-picker").hidden = true; filePickerTarget = "project"; renderMaterialChosen(); };
$("file-go").onclick = guard(() => browseMaterialFiles($("file-path").value));
$("file-up").onclick = guard(() => browseMaterialFiles(fileState.parent));
$("stop").onclick = guard(async () => {
  // Await in-flight local operations before warning about unsent input.
  await pendingLocal.catch(() => {});
  const unsent = [$("message").value.trim() && "message text",
    (attachments.length || [...messageFileDrafts.values()].some(files => files.length)) && "files selected for a message"].filter(Boolean);
  const state = await api("quit-state", {});
  const active = state.active_turns || 0;
  if ((unsent.length || active) && !confirm(`${active ? `${active} AI turn${active === 1 ? " is" : "s are"} still working. Stopping Vibe now interrupts that work; files already changed remain.\n\n` : ""}${unsent.length ? `You have unsent ${unsent.join(", ")}. The text and file choices remain visible in this tab until you close it.\n\n` : ""}Choose Cancel to keep working, or OK to stop Vibe now.`)) return;
  let result;
  try { result = await api("stop", {}); }
  catch (error) { status(error.message); return; }
  stopped = true;
  clearTimeout(projectScanTimer);
  stopPolling();
  if (result.interrupted) {
    status(`Vibe is closing: ${result.note}`);
    watchClosing();
  } else {
    status("Vibe stopped. Text remains available to select and copy in this tab. Saved project files were left in place; external AI work was not touched.");
  }
});
// --- Conversation, split view, readiness, and the reliability engine ---------

let docScrollPosition = 0, docWasVisible = true;
const SPINE_WIDTH = 58;
function applySplit() {
  const split = $("split");
  const narrow = window.innerWidth <= 900;
  const mode = narrow ? splitMode : "split";
  const docVisible = mode !== "chat";
  const body = document.querySelector(".result-body");
  // Hiding a pane resets its scroll; the reading position travels with the
  // pane instead of being lost.
  if (!docVisible && docWasVisible) docScrollPosition = body ? body.scrollTop : 0;
  split.dataset.orientation = "split";
  split.dataset.mode = mode;
  // One shared column template drives the work area and header row 3, so the
  // stage title stays centered over the spine at any divider position. On a
  // narrow window one pane shows at a time beside the spine, never stacked.
  let columns;
  if (mode === "split") {
    const lead = (splitFraction * 100).toFixed(2), rest = ((1 - splitFraction) * 100).toFixed(2);
    columns = `minmax(200px, ${lead}fr) ${SPINE_WIDTH}px minmax(200px, ${rest}fr)`;
  } else if (mode === "chat") columns = `minmax(0, 1fr) ${SPINE_WIDTH}px`;
  else columns = `${SPINE_WIDTH}px minmax(0, 1fr)`;
  document.documentElement.style.setProperty("--spine-cols", columns);
  applyTitleShift();
  if (docVisible && !docWasVisible && body) body.scrollTop = docScrollPosition;
  docWasVisible = docVisible;
  $("single-toggle").textContent = mode === "doc" ? "Show conversation" : "Show document";
}
// The stage title stays centered over the spine itself, wherever the divider
// currently sits; on a narrow window it centers over its own row. When the
// row is crowded, the centered title shifts into the free space between the
// step-3 card and the run actions, so neither ever covers it.
function applyTitleShift() {
  const head = $("workspace-head"), title = $("stage-title");
  document.documentElement.style.setProperty("--title-shift", "0px");
  if (head.hidden || !title.textContent.trim()) return;
  const headBox = head.getBoundingClientRect();
  if (!headBox.width) return;
  const rowCenter = headBox.left + headBox.width / 2;
  const spineBox = $("spine").getBoundingClientRect();
  let center = $("split").dataset.mode === "split" && spineBox.width
    ? spineBox.left + spineBox.width / 2 : rowCenter;
  const textRange = document.createRange();
  textRange.selectNodeContents(title);
  const textBox = textRange.getBoundingClientRect();
  const first = document.querySelector(".first-step").getBoundingClientRect();
  const actions = document.querySelector(".head-actions").getBoundingClientRect();
  const beside = element => element.width && textBox.top < element.bottom - 1 && element.top < textBox.bottom + 1;
  if (beside(first) || beside(actions)) {
    const half = textBox.width / 2 + 6;
    const low = first.right + half, high = actions.left - half;
    center = low <= high ? Math.min(Math.max(center, low), high) : (low + high) / 2;
  }
  document.documentElement.style.setProperty("--title-shift", `${(center - rowCenter).toFixed(1)}px`);
}
function rememberSplit() {
  api("preferences", {split_fraction: splitFraction}).catch(() => {});
}
$("single-toggle").onclick = () => { splitMode = splitMode === "doc" ? "chat" : "doc"; applySplit(); };
window.addEventListener("resize", () => { finishWorkspaceReveal(); applySplit(); });
{
  // The branded spine is the divider between AI Work and the document.
  const divider = $("spine");
  let dragging = false;
  divider.addEventListener("pointerdown", event => {
    if ($("split").dataset.mode !== "split") return;
    dragging = true;
    try { divider.setPointerCapture(event.pointerId); } catch (_) { /* the pointer is gone; dragging still tracks */ }
    event.preventDefault();
  });
  divider.addEventListener("pointermove", event => {
    if (!dragging) return;
    const box = $("split").getBoundingClientRect();
    const raw = (event.clientX - box.left) / box.width;
    splitFraction = Math.min(.95, Math.max(.05, raw));
    applySplit();
  });
  const release = () => { if (dragging) { dragging = false; rememberSplit(); } };
  divider.addEventListener("pointerup", release);
  divider.addEventListener("pointercancel", () => { dragging = false; });
  divider.addEventListener("keydown", event => {
    const step = event.shiftKey ? .1 : .02;
    if (event.key === "ArrowRight") splitFraction = Math.min(.95, splitFraction + step);
    else if (event.key === "ArrowLeft") splitFraction = Math.max(.05, splitFraction - step);
    else return;
    event.preventDefault();
    applySplit();
    rememberSplit();
  });
}
{
  const divider = $("conversation-divider"), conversation = $("conversation"), pane = $("work-step-body");
  let dragging = false, fraction = null;
  function sizeConversation(next) {
    fraction = Math.min(.8, Math.max(.15, next));
    conversation.classList.add("resized");
    conversation.style.setProperty("--conversation-size", `${(fraction * 100).toFixed(2)}%`);
    divider.setAttribute("aria-valuenow", String(Math.round(fraction * 100)));
  }
  divider.addEventListener("pointerdown", event => {
    dragging = true;
    divider.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  divider.addEventListener("pointermove", event => {
    if (!dragging) return;
    const box = pane.getBoundingClientRect();
    sizeConversation((event.clientY - box.top) / box.height);
  });
  const release = () => { dragging = false; };
  divider.addEventListener("pointerup", release);
  divider.addEventListener("pointercancel", release);
  divider.addEventListener("keydown", event => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const current = fraction ?? conversation.clientHeight / pane.clientHeight;
    sizeConversation(current + (event.key === "ArrowDown" ? .05 : -.05));
  });
}

// Attachments: paste and upload share one path; originals are delivered whole.
function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).slice(String(reader.result).indexOf(",") + 1));
    reader.onerror = () => reject(new Error("The image could not be read."));
    reader.readAsDataURL(file);
  });
}
async function addAttachment(file) {
  if (attachments.length >= 10) { status("Attach at most 10 images with one message."); return; }
  if (!/^image\/(png|jpeg)$/.test(file.type) && !/\.(png|jpe?g)$/i.test(file.name)) {
    status("Attach PNG or JPEG images; other file types are not delivered by this route.");
    return;
  }
  if (file.size > 8 * 1024 * 1024) { status("One image is larger than 8 MiB and cannot be attached."); return; }
  attachments.push({name: file.name || "image.png", data: await fileToBase64(file), url: URL.createObjectURL(file)});
  renderAttachments();
}
function renderAttachments() {
  const bar = $("attachment-bar");
  bar.hidden = !attachments.length;
  bar.replaceChildren();
  for (const item of attachments) {
    const chip = document.createElement("div"); chip.className = "attachment";
    const image = document.createElement("img"); image.src = item.url; image.alt = item.name;
    const remove = document.createElement("button"); remove.type = "button";
    remove.textContent = "Remove"; remove.setAttribute("aria-label", `Remove ${item.name}`);
    remove.onclick = () => {
      attachments = attachments.filter(held => held !== item);
      URL.revokeObjectURL(item.url);
      renderAttachments();
    };
    chip.append(image, remove);
    bar.append(chip);
  }
  syncVisibleInput();
}
$("attach").onclick = () => $("image-input").click();
$("image-input").onchange = async () => {
  const files = [...$("image-input").files];
  $("image-input").value = "";
  for (const file of files) await addAttachment(file);
};
function selectedToolId() {
  // The dropdown shows display names; Bridge routes by the peer id.
  const host = hostChoices.find(h => h.name === $("destination").value);
  return host ? host.id : "";
}
$("message").addEventListener("paste", event => {
  const files = [...(event.clipboardData?.items || [])].filter(item => item.kind === "file")
    .map(item => item.getAsFile()).filter(Boolean);
  if (!files.length) return;
  event.preventDefault();
  for (const file of files) addAttachment(file).catch(error => status(error.message));
});
$("message").oninput = () => { composerGeneration += 1; updateMessageSuggestion(); syncVisibleInput(); };

function originLabel(id) {
  // The selector's own name for a project, to attribute another project's
  // outcome while a different one is displayed.
  return projectEntries.find(entry => entry.id === id)?.label || projectPaths[id] || "its originating project";
}
async function send() {
  if (!currentId || !project) { status("Choose or create a project first."); return; }
  // During a run the composer cannot start a separate turn or add to the
  // running brief; it can only answer a pause.
  if (runActive) {
    if (runActive.state !== "paused-question") { status("A Run to Completion is active; the composer can only answer its pause, or stop the run."); return; }
    const answer = $("message").value.trim();
    if (!answer && !attachments.length && !messageFiles().length) { status("Write the answer to the run's questions first."); return; }
    const id = currentId;
    $("send").disabled = true;
    try {
      const result = await api("run-answer", {id, text: $("message").value});
      if (id !== currentId) return;
      updateRunState(result.run);
      $("message").value = ""; composerGeneration += 1;
      attachments = []; renderAttachments();
      for (const item of messageFiles().slice()) { const list = messageFiles(); const at = list.indexOf(item); if (at >= 0) list.splice(at, 1); }
      renderMaterialChosen(); syncVisibleInput();
      status("Answer sent into the run; it resumes the same step.");
    } finally { if (id === currentId) updateSendState(); }
    return;
  }
  const tool = selectedToolId();
  if (!tool) { status("Choose the coding tool for this conversation, then send."); return; }
  const blocked = routeBlock(tool);
  if (blocked) { status(`${blocked.reason}. ${blocked.remedy}`, "warning"); return; }
  // The originating project and the composer's draft identity are captured
  // before dispatch: a switch or an edit while the acknowledgement is awaited
  // must never reassign this submission, its result, or its consumption of
  // the composer to the project or draft now displayed.
  const originId = currentId;
  const originWorkspace = workspace;
  const generation = composerGeneration;
  const text = effectiveMessage();
  const submittedFiles = messageFiles().slice();
  if (!text.trim() && !attachments.length && !submittedFiles.length) { status("Write a message or attach an image or file before sending."); return; }
  const stage = messageStage() || "specification";
  const submitted = attachments.slice();  // Exactly what leaves with this message.
  if (stage === "programming") {
    await refreshProject();
    if (originId !== currentId || originWorkspace !== workspace || generation !== composerGeneration || tool !== selectedToolId() || stage !== messageStage()) return;
    if (!await confirmImplementationBasis()) return;
    if (originId !== currentId || originWorkspace !== workspace || generation !== composerGeneration || tool !== selectedToolId() || stage !== messageStage()) return;
  }
  $("send").disabled = true;
  status("");
  let result;
  try {
    try {
      // The server saves the submission durably before dispatch and answers
      // only once the bounded worker has started.
      result = await api("converse", {id: originId, tool, stage, text, files: submittedFiles.map(item => item.path),
                                      images: submitted.map(item => ({name: item.name, data: item.data}))});
    } catch (error) {
      // Pre-acknowledgement, in two distinct states. The server answered with
      // a rejection: nothing was dispatched. No answer at all: delivery is
      // unknown, never denied — the submission may already be recorded and
      // working, and resending it blind could repeat consequential work. The
      // notice belongs to the originating project: after a switch it names
      // that project instead of posing as the displayed one's own state.
      if (currentId === originId) {
        status(error.status
          ? `${error.message} Your message and attachments are retained here; nothing was sent.`
          : `${error.message} Your message and attachments are retained here; whether the submission reached the local server is unknown. Reopen this project and check its recorded turns before sending it again.`);
      } else {
        const label = originLabel(originId);
        status(error.status
          ? `${error.message} The message and attachments sent from ${label} were not dispatched; nothing was sent.`
          : `${error.message} Whether the message sent from ${label} reached the local server is unknown. Reopen ${label} and check its recorded turns before sending that message again.`);
      }
      return;
    }
    // Acknowledged: the turn is submitted and durable. Until its outcome is
    // known, its submission stays restorable for its own project: an
    // unsupported route or a failed turn must not consume it silently, and
    // another project's send never replaces it. The server's retained names
    // identify the saved originals for same-origin redelivery.
    pendingDrafts.set(originId, {turn: result.turn, text, workspace: originWorkspace, files: submittedFiles,
                                 images: submitted.map((item, index) => (
                                   {name: (result.images || [])[index] || item.name, data: item.data}))});
    // The dispatched attachments leave the composer by identity, whatever is
    // displayed — they were sent with this message. The text is consumed only
    // when the originating project is still displayed and this is still the
    // same draft: another project's identical unsent text is a different
    // draft and stays untouched.
    attachments = attachments.filter(held => !submitted.includes(held));
    const originFiles = messageFilesFor(originId, originWorkspace);
    for (const item of submittedFiles) { const index = originFiles.indexOf(item); if (index >= 0) originFiles.splice(index, 1); }
    for (const item of submitted) if (!attachments.includes(item)) URL.revokeObjectURL(item.url);
    if (currentId === originId && composerGeneration === generation) $("message").value = "";
    renderAttachments();
    renderMaterialChosen();
    syncVisibleInput();
    if (currentId !== originId) return;  // The switch already routed this page to the other project.
    lastOperation = result.operation;
    await loadConversation();
    if (currentId !== originId) return;  // Ownership rechecked after the await.
    updateOperation(result.operation);
  } catch (error) {
    // Only acknowledged steps can fail here. The turn is submitted and keeps
    // working on its own; this reports the display failure without denying
    // dispatch, so work that already left is not resent. After a switch the
    // report is suppressed: the turn is recorded in its originating project,
    // whose own conversation and polls carry it, and this view belongs to
    // another project.
    if (currentId === originId) {
      status(`The message was submitted${result ? ` as turn ${result.turn}` : ""}, but updating this view failed: ${error.message} The turn's state is viewable after reopening or switching back to this project; sending the message again would start a second turn.`);
    }
  } finally {
    updateSendState();
  }
}
$("send").onclick = guard(send);
$("message").addEventListener("keydown", event => {
  // Enter sends — never during input-method composition; Shift+Enter is a newline.
  if (event.key === "Enter" && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey && !event.isComposing) {
    event.preventDefault();
    guard(send)();
  }
});
function updateSendState() {
  const busy = (!!lastOperation && ["starting", "running"].includes(lastOperation.state)
                && !lastOperation.stage?.startsWith("materiality-"))
    || (runActive && ["starting", "running"].includes(runActive.state));
  if (runActive) {
    $("send").disabled = runActive.state !== "paused-question";
    $("send").textContent = runActive.state === "paused-question"
      ? "Send the answer into the run"
      : "Run active — the composer answers pauses";
    return;
  }
  $("message-label").textContent = workspace === "build"
    ? (messageStage() === "verification" ? "Reply to the verification coordinator" : "What should the AI change or explain in the implementation?")
    : `What should the AI change or explain in the ${workspaces[workspace]?.title || "current stage"}?`;
  const blocked = routeBlock(selectedToolId());
  $("send").disabled = !currentId || !selectedToolId() || busy || !!blocked;
  $("send").title = blocked
    ? `${blocked.reason}. ${blocked.remedy} Your draft, attachments and project stay as they are; nothing is switched.`
    : "";
  $("send").textContent = blocked
    ? "In-app turn unavailable for this tool"
    : busy ? "AI is working — one turn at a time" : `Ask ${$("destination").value || "AI"} to work on ${workspace === "build" ? (messageStage() === "verification" ? "independent verification" : "the implementation") : `the ${workspaces[workspace]?.title || "current stage"}`}`;
}

// The saved conversation and the retained review runs, derived from records.
async function loadConversation() {
  if (!currentId) { conversationTurns = []; reviewRuns = []; renderConversation(); return; }
  const id = currentId, opening = projectOpeningGeneration;
  let data;
  try { data = await api("conversation", {id}); }
  catch (error) {
    if (id !== currentId || opening !== projectOpeningGeneration) return;
    conversationLoaded = false;
    throw error;
  }
  if (id !== currentId || opening !== projectOpeningGeneration) return;
  conversationLoaded = true;
  conversationTurns = data.turns || [];
  reviewRuns = data.runs || [];
  updateMessageSuggestion();
  resolvePendingDraft(null);
  renderConversation();
  renderQuestions();
  reviewSuggestion();
}
function turnMeta(kind, tool, stage) {
  const meta = document.createElement("p"); meta.className = "msg-meta";
  meta.textContent = `${kind} · ${tool || "unknown tool"}${stage ? ` · ${stage}` : ""}`;
  return meta;
}
function messageCard(turn) {
  const card = document.createElement("article"); card.className = "exchange";
  const user = document.createElement("div"); user.className = "msg user";
  const text = document.createElement("div"); text.textContent = turn.text || "";
  user.append(text);
  if (turn.images?.length) {
    const images = document.createElement("p"); images.className = "msg-meta";
    images.style.whiteSpace = "normal";
    images.textContent = `Images delivered with this message: ${turn.images.join(", ")}`;
    user.append(images);
  }
  if (turn.files?.length) {
    const files = document.createElement("p"); files.className = "msg-meta";
    files.style.whiteSpace = "normal";
    files.textContent = `Files included with this message: ${turn.files.join(", ")}`;
    user.append(files);
  }
  card.append(user, turnMeta("message", turn.tool, turn.stage));
  const observed = lastOperation && lastOperation.turn === turn.turn ? lastOperation : null;
  if (turn.state === "open") {
    const note = document.createElement("div"); note.className = "msg ai";
    // The unfinished message reconciles with the observed operation for this
    // same turn: live means working, terminal means a saved outcome exists —
    // neither is an interruption, and neither invites sending it again.
    if (!observed || ["starting", "running"].includes(observed.state)) {
      note.textContent = observed
        ? "Working… the complete answer appears here when the turn finishes; no streaming."
        : "Unfinished — no final reply was saved. Files may already have changed. Inspect the recorded request and current work before deciding to retry; nothing is replayed automatically.";
    } else if (observed.state === "finished") {
      note.textContent = "This turn has finished; its complete saved reply appears here when the conversation loads it.";
    } else if (observed.state === "interrupted") {
      note.textContent = `Interrupted: ${observed.reason || "Stopped before a final reply. Files already changed remain; inspect the current work before retrying."}`;
    } else {
      note.textContent = `This turn failed: ${observed.reason || "no reason was recorded."}`;
    }
    card.append(note);
  } else {
    // A reply preserved before a later post-turn failure stays visible; the
    // failure notice appears beneath it, never instead of it.
    if (turn.reply !== null && turn.reply !== undefined) {
      const reply = document.createElement("div"); reply.className = "msg ai";
      const body = document.createElement("div");
      render(body, turn.reply);
      reply.append(body);
      card.append(reply);
    }
    if (["failed", "interrupted"].includes(turn.state)) {
      const failed = document.createElement("div"); failed.className = "msg ai msg-failed";
      const reason = document.createElement("div");
      reason.textContent = `${turn.state === "interrupted" ? "Interrupted" : "The turn failed"}: ${turn.maintenance?.notice || "no reason was recorded."}`;
      failed.append(reason);
      const recovery = document.createElement("p"); recovery.className = "msg-meta"; recovery.style.whiteSpace = "normal";
      recovery.textContent = "Files may already have changed. Inspect the saved request and current work before deciding to retry. Nothing is retried automatically.";
      failed.append(recovery);
      card.append(failed);
    }
  }
  appendArtifactReadback(card, turn.artifact);
  // The turn's Bridge diagnostics are secondary detail: they appear only under
  // More through renderMoreTurn, never as a Technical details expander here.
  if (turn.maintenance && !["failed", "interrupted"].includes(turn.state)) {
    const chip = document.createElement("span");
    chip.className = `maintenance-chip${turn.maintenance.unsaved ? " unsaved" : ""}`;
    const outcomes = {applied: "Registry updated", "no-change": "Registry: no change needed",
                      missing: "Registry not re-evaluated", malformed: "Registry update malformed",
                      stale: "Registry update not applied — changed since", conflict: "Registry update not applied — conflict",
                      unconfirmed: "Registry update unconfirmed — interrupted"};
    chip.textContent = outcomes[turn.maintenance.outcome] || `Registry: ${turn.maintenance.outcome}`;
    chip.title = turn.maintenance.notice || "";
    card.append(chip);
  }
  return card;
}
function agreementLine(run) {
  if (!run.reviewer) return "";
  if (["failed", "interrupted"].includes(run.state)) return "";
  if (!run.iterate) return `Evaluator round 1: ${run.verdict || "unclear"}. The revision was not re-evaluated (iteration was off).`;
  if (run.agreement === "pass") return `Agreed: the final evaluation passed the revised assessment (round ${run.rounds}).`;
  return `Residual disagreement after ${run.rounds} round${run.rounds === 1 ? "" : "s"}: the evaluator's last verdict was ${run.verdict || run.agreement}. You break remaining ties.`;
}
function runCard(run) {
  const card = document.createElement("article"); card.className = "exchange";
  const stageName = run.stage === "review-specification" ? "Specification" : run.stage === "review-plan" ? "Plan" : run.stage;
  const head = document.createElement("p"); head.className = "run-head";
  const label = document.createElement("strong"); label.textContent = `${run.reviewer ? "Second opinion" : "Review"} — ${stageName}`;
  const tag = document.createElement("span"); tag.className = "run-tag";
  // Lab diversity is stated only when both passes' own events reported their
  // provider identity; otherwise it is honestly unknown, never guessed from
  // the harness names.
  tag.textContent = run.same_lab === true ? "same lab, fresh session"
    : run.same_lab === false ? "different labs" : "lab diversity unconfirmed";
  tag.title = run.same_lab == null
    ? "Neither pass reported its actual model/provider identity, so whether the author and evaluator ran in different labs is unknown."
    : run.same_lab ? "Both passes reported the same provider." : "The passes reported different providers.";
  head.append(label);
  if (run.reviewer) head.append(tag);
  card.append(head, turnMeta("review run", run.tool, run.reviewer ? `${run.reviewer} reviewed` : "one model"));
  if (["failed", "interrupted"].includes(run.state)) {
    const failed = document.createElement("div"); failed.className = "msg ai msg-failed";
    failed.textContent = `${run.state === "interrupted" ? "Review interrupted" : "The run failed"}: ${run.notice || "no reason was recorded."} Completed passes remain in the turn records; no assessment was applied.`;
    card.append(failed);
  }
  if (run.output) {
    const output = document.createElement("div"); output.className = "msg ai";
    const body = document.createElement("div");
    render(body, `## Current review\n\n${run.output}`);
    output.append(body);
    card.append(output);
    const saved = document.createElement("p"); saved.className = "run-summary";
    saved.textContent = run.assessment === "applied"
      ? "This assessment was saved into the document's Current review section."
      : `The assessment was not written to the document: ${run.notice || run.assessment}. It is retained here in the turn records.`;
    card.append(saved);
  }
  if (run.changes) {
    const changes = document.createElement("p"); changes.className = "run-summary";
    changes.textContent = `What changed: ${run.changes}`;
    card.append(changes);
  }
  const agreement = agreementLine(run);
  if (agreement) {
    const line = document.createElement("p"); line.className = "run-summary";
    line.textContent = agreement;
    card.append(line);
  }
  if (run.evaluation) {
    const details = document.createElement("details"); details.className = "full-evaluation";
    const summary = document.createElement("summary");
    summary.textContent = `Full evaluation by ${run.reviewer} (round ${run.rounds || 1})`;
    const body = document.createElement("div");
    render(body, run.evaluation);
    details.append(summary, body);
    card.append(details);
  }
  appendArtifactReadback(card, run.artifact);
  // Review-run Bridge diagnostics live only under More, like every turn's.
  return card;
}
// A readback that merely confirms a routine successful save is secondary
// detail: it lives under More (renderMoreTurn) beside the turn it belongs to
// and in the underlying records, never as a second receipt on the card — and
// the local file's location lives there too. Only a readback the user can act
// on stays visible beside the reply: no document, an unreadable one, or a
// selection that moved under the turn.
function appendArtifactReadback(element, artifact) {
  if (!artifact || ["changed", "unchanged"].includes(artifact.outcome)) return;
  const line = document.createElement("p"); line.className = "artifact-readback";
  const outcomes = {missing: "No document is available at the selected local path.",
    unreadable: "The selected local document could not be read back.",
    "selection-changed": "The selected document changed during this turn; its result is not confirmed."};
  line.textContent = [artifact.role, artifact.reason || outcomes[artifact.outcome], artifact.applies === "earlier" ? "This assessment covers an earlier document version." : ""].filter(Boolean).join(" — ");
  element.append(line);
}
function renderConversation() {
  const holder = $("conversation");
  if (!holder) return;
  // This render already reconciles the live operation it is drawn under;
  // polling compares against it before redrawing an unfinished turn.
  if (lastOperation && ["starting", "running"].includes(lastOperation.state)) conversationLiveMark = `${lastOperation.turn}:${lastOperation.state}`;
  const nearBottom = holder.scrollHeight - holder.scrollTop - holder.clientHeight < 90;
  holder.replaceChildren();
  if (!currentId) return;
  const entries = [
    ...conversationTurns.map(turn => ({order: turn.turn, card: () => messageCard(turn)})),
    ...reviewRuns.map(run => ({order: run.run, card: () => runCard(run)})),
  ].sort((a, b) => String(a.order).localeCompare(String(b.order)));
  for (const entry of entries) holder.append(entry.card());
  if (nearBottom) holder.scrollTop = holder.scrollHeight;
}

// Live operation status: elapsed time and recent Bridge contact, never progress.
// A retained original is redelivered through the app's own same-origin
// attachment route — the one image-delivery mechanism the page's narrowly
// scoped policy permits. The token travels in the query because an image
// load cannot carry the tab's token header; the host and origin checks on
// that route are the same as every other route's.
function attachmentUrl(turn, name) {
  return `/api/attachment?token=${encodeURIComponent(token)}&id=${encodeURIComponent(currentId)}&turn=${encodeURIComponent(turn)}&name=${encodeURIComponent(name)}`;
}
function restorePendingDraft(draft, reason) {
  // The failed or capability-rejected turn leaves the user's text and images
  // in the composer with the failure reason. Newer composer edits are never
  // overwritten: only an empty composer takes the submitted text back.
  if (!$("message").value.trim()) { $("message").value = draft.text; composerGeneration += 1; }
  for (const image of draft.images) {
    if (!attachments.some(held => held.name === image.name && held.data === image.data))
      attachments.push({name: image.name, data: image.data, url: attachmentUrl(draft.turn, image.name)});
  }
  const selected = messageFilesFor(currentId, draft.workspace);
  for (const file of draft.files || []) if (!selected.some(item => item.path === file.path)) selected.push(file);
  renderAttachments();
  renderMaterialChosen();
  syncVisibleInput();
  status(`The turn failed; your message and attachments are available to edit and resend.${reason ? ` ${reason}` : ""}`);
}
function resolvePendingDraft(operation) {
  const draft = pendingDrafts.get(currentId);
  if (!draft) return;
  if (operation) {
    if (operation.turn !== draft.turn) return;
    if (["finished", "interrupted"].includes(operation.state)) pendingDrafts.delete(currentId);
    else if (operation.state === "failed") { pendingDrafts.delete(currentId); restorePendingDraft(draft, operation.reason); }
    return;
  }
  // After a reopen or a switch back, the turn records hold the outcome the
  // polls never saw; only this project's own records resolve its draft, and
  // another project's pending submission is never touched by them.
  const turn = conversationTurns.find(item => item.turn === draft.turn);
  if (!turn) return;
  if (["complete", "finished", "interrupted"].includes(turn.state)) pendingDrafts.delete(currentId);
  else if (turn.state === "failed") { pendingDrafts.delete(currentId); restorePendingDraft(draft, turn.maintenance?.notice); }
}
function updateOperation(operation) {
  const wasUnknown = lastOperation === undefined;
  resolvePendingDraft(operation);
  const bar = $("status-bar");
  if (operation && !["starting", "running"].includes(operation.state)) {
    const key = JSON.stringify([operation.project, operation.turn, operation.state, operation.elapsed_seconds,
      operation.reason, operation.maintenance, operation.maintenance_reason, operation.warnings,
      operation.bridge_diagnostics, operation.visible_warnings, operation.artifact]);
    if (bar.dataset.operationKey === key) {
      lastOperation = operation;
      renderStatusActivity();
      updateSendState();
      return;
    }
    bar.dataset.operationKey = key;
  } else {
    bar.dataset.operationKey = "";
  }
  lastOperation = operation;
  let summary = "";
  let warned = false;
  if (!operation) {
    summary = conversationTurns.some(turn => turn.state === "open")
      ? "An earlier turn is unfinished: it was interrupted, nothing is running now, and nothing is replayed automatically."
      : "";
  } else if (["starting", "running"].includes(operation.state)) {
    summary = `Working — ${Math.round(operation.elapsed_seconds)}s elapsed, last Bridge contact ${Math.max(0, Math.round(operation.last_contact_seconds))}s ago.`;
  } else if (["failed", "interrupted"].includes(operation.state)) {
    summary = `${operation.state === "interrupted" ? "Interrupted" : "The turn failed"}: ${operation.reason || "no reason was recorded."}`;
    warned = true;
  } else if (operation.state === "finished") {
    const maintenance = operation.maintenance;
    if (["review-specification", "review-plan"].includes(operation.stage)) {
      const assessment = maintenance === "applied" ? " Assessment saved."
        : ` Assessment not saved.${operation.maintenance_reason ? ` ${operation.maintenance_reason}` : ""}`;
      summary = `Review completed in ${Math.round(operation.elapsed_seconds)}s.${assessment}`;
      if (maintenance !== "applied") warned = true;
    } else {
      const registry = maintenance === "applied" ? " Registry updated."
        : maintenance === "no-change" ? " Registry: no change needed."
        : maintenance && maintenance !== "none" ? ` Registry update not applied (${maintenance}).${operation.maintenance_reason ? ` ${operation.maintenance_reason}` : ""}`
        : "";
      summary = `Reply complete in ${Math.round(operation.elapsed_seconds)}s.${registry}`;
      if (maintenance && !["applied", "no-change", "none"].includes(maintenance)) {
        warned = true;
      }
    }
  }
  if (operation && !["starting", "running"].includes(operation.state)) {
    const diagnostics = operation.bridge_diagnostics || [];
    const visible = operation.visible_warnings || [];
    const classified = new Set([...diagnostics, ...visible]);
    // Unknown warning sources remain in full view; only Bridge event warnings
    // have been identified as diagnostics that require no action, so those
    // sit under More while anything needing attention joins the status text.
    const notices = [...new Set([...visible, ...(operation.warnings || []).filter(item => !classified.has(item))])];
    if (notices.length) { summary = `${summary} ${notices.join(" ")}`; warned = true; }
    renderMoreTurn(operation, diagnostics);
  } else {
    renderMoreTurn(null, []);
  }
  if (summary) status(summary, warned ? "warning" : "");
  else renderStatusActivity();
  if (wasUnknown) { updateSecondOpinion(); renderRunBanner(); }
  updateSendState();
}
// Secondary detail of the last turn: the saved-file readback and the Bridge
// diagnostics that ask nothing of the user, kept in the More area.
function renderMoreTurn(operation, diagnostics) {
  const section = $("more-turn"), artifactLine = $("more-artifact"), list = $("more-diagnostics");
  const artifact = operation?.artifact;
  const outcomes = {changed: "The selected local document changed and was read back.",
    unchanged: "The selected local document was read back unchanged.",
    missing: "No document is available at the selected local path.",
    unreadable: "The selected local document could not be read back.",
    "selection-changed": "The selected document changed during this turn; its result is not confirmed."};
  artifactLine.replaceChildren();
  if (artifact) {
    artifactLine.textContent = [artifact.role, artifact.reason || outcomes[artifact.outcome],
      artifact.applies === "earlier" ? "This assessment covers an earlier document version." : "",
      artifact.path ? `Local file: ${artifact.path}` : ""].filter(Boolean).join(" — ");
  }
  list.replaceChildren();
  for (const value of diagnostics || []) {
    const item = document.createElement("li");
    item.textContent = value;
    list.append(item);
  }
  section.hidden = !artifact && !(diagnostics || []).length;
}

// Background readiness: no model call, one poll chain per project. Only a
// recheck (startup's first check and the Recheck button) asks the server to
// start the worker; the chain's own polls just read the report, so the chain
// ends when checking turns false instead of restarting the worker forever.
async function refreshReadiness(recheck = false) {
  if (recheck) modelInventories.clear();
  if (!currentId || stopped) return;
  const id = currentId, chain = ++readinessChain;
  let data;
  try { data = await api("readiness", {recheck}); }
  catch (error) { if (id === currentId) status(error.message, "warning"); return; }
  if (id !== currentId || chain !== readinessChain || stopped) return;
  readinessState = data;
  // Recheck refreshes discovery as well as readiness: a tool installed,
  // removed, updated or signed into since page load is reflected here.
  if (Array.isArray(data.hosts) && data.hosts.length) {
    const held = $("destination").value;
    hostChoices = data.hosts;
    $("destination").replaceChildren(new Option("Choose a coding tool", ""), ...hostChoices.map(h => new Option(h.name, h.name)));
    $("destination").value = hostChoices.some(h => h.name === held) ? held : "";
  }
  updateHost();
  renderReviewerChoices();
  if (data.checking) {
    setTimeout(() => { if (chain === readinessChain && currentId === id && !stopped) refreshReadiness(); }, 1500);
  }
}
function selectedReadiness() {
  const facts = (readinessState.peers || []).find(peer => peer.peer === selectedToolId()) || null;
  if (messageStage() === "programming" && facts?.peer === "zcode") {
    return facts.programming ? {...facts.programming, label: facts.label}
      : {...facts, ready: false, effective_permission: null,
         reason: "Programming Full access readiness has not been checked."};
  }
  return facts;
}
function peerFacts(id) {
  return (readinessState.peers || []).find(peer => peer.peer === id) || null;
}
// Why one tool's in-app work route is unavailable right now, or null when it
// is not blocked. Component truth first (the bundled copy actually used),
// then the tool's own Bridge capability; authentication never blocks here —
// a missing sign-in does not erase an implemented capability.
function routeBlock(id) {
  if (lastOperation === undefined)
    return {reason: "This project's work status is unknown",
            remedy: "Automatic refresh will check again before new work can start. Available documents and your draft stay here."};
  const host = hostChoices.find(h => h.id === id);
  if (!id || !host) return null;
  const bridge = readinessState.components?.bridge;
  if (bridge && bridge.status && bridge.status !== "ok")
    return {reason: `the bundled Agent Bridge is ${bridge.status === "missing" ? "missing" : "not readable"}${bridge.reason ? `: ${bridge.reason}` : ""}`,
            remedy: bridge.remedy || "Reinstall Ora Vibe Coder from a complete release, then Recheck."};
  const facts = peerFacts(id);
  if (facts && facts.work === "unsupported")
    return {reason: `${host.name} has no Agent Bridge work mode`,
            remedy: "Open in Terminal and Copy request stay available for this tool."};
  if (facts && facts.work !== "supported")
    return {reason: `${host.name}'s in-app compatibility is unknown${facts.reason ? `: ${facts.reason}` : ""}`,
            remedy: `${facts.next_action ? facts.next_action + " " : ""}Recheck refreshes readiness and discovery.`};
  if (!facts && host.conversation === false)
    return {reason: `${host.name} has no in-app conversation route`,
            remedy: "Use Open in Terminal or Copy request."};
  return null;
}
// The step-6 / dialog label follows the same truth: Send for a work-capable
// tool, Open in Terminal for a courier-only one.
function routeLabelHost(id = selectedToolId()) {
  const host = hostChoices.find(host => host.id === id);
  if (!host) return host;
  const facts = peerFacts(host.id);
  const conversation = facts ? facts.work === "supported" : host.conversation !== false;
  return {...host, conversation};
}
// The bundled Loop adapter gate for Build-family routes (in-app Build, the
// run's build entry). Returns null when not blocked.
function buildBlock(id) {
  const loop = readinessState.components?.loop;
  const host = hostChoices.find(h => h.id === id);
  if (!loop || !host) return null;
  if (loop.status && loop.status !== "ok")
    return {reason: loop.reason || "the bundled Programming Loop package is not readable",
            remedy: loop.remedy || "Reinstall Ora Vibe Coder from a complete release, then Recheck."};
  if (Array.isArray(loop.adapters) && !loop.adapters.includes(id))
    return {reason: `the bundled Programming Loop has no ${host.name} adapter`,
            remedy: "Reinstall Ora Vibe Coder from a complete release, then Recheck."};
  return null;
}
function renderReadiness() {
  const chip = $("readiness"), button = $("recheck"), info = $("readiness-detail");
  if (!currentId) { chip.hidden = true; button.hidden = true; $("more-tool").hidden = true; chip.setAttribute("aria-expanded", "false"); return; }
  button.hidden = false;
  chip.hidden = false;
  const full = chip.querySelector(".readiness-full"), short = chip.querySelector(".readiness-short");
  if (readinessState.checking && !readinessState.peers) { full.textContent = "Checking Bridge readiness…"; short.textContent = "Checking…"; chip.title = info.textContent = "A background check that makes no model call."; return; }
  const facts = selectedReadiness();
  if (!facts) { full.textContent = "Readiness not checked yet"; short.textContent = "Unchecked"; chip.title = info.textContent = "Readiness has not been checked for the selected tool."; return; }
  const label = facts.label || facts.peer;
  // A no-model-call readiness check establishes transport facts only. Even
  // an older Bridge result cannot prove acceptance of Codex's next request,
  // which reads the user's current model/account settings when it starts.
  const codex = facts.peer === "codex";
  const zcode = facts.peer === "zcode";
  const fullAccess = zcode && facts.ready && facts.effective_permission === "full-access";
  const programming = zcode && (readinessState.peers || []).find(peer => peer.peer === "zcode")?.programming;
  const programmingReady = programming?.ready && programming.effective_permission === "full-access";
  const authentication = facts.authentication === "confirmed" ? "Sign-in: confirmed."
    : facts.authentication === "required" ? "Sign-in: required." : "Sign-in: unconfirmed.";
  full.textContent = facts.ready
    ? `${label}: ${fullAccess ? "Full access for programming" : zcode ? `Edit${programmingReady ? " · programming: Full access" : " · programming not ready"}` : codex ? "available — model unverified" : "ready"}${facts.authentication === "required" ? " — sign-in required" : facts.authentication === "unknown" ? " — sign-in unconfirmed" : ""}`
    : `${label}: not ready`;
  short.textContent = !facts.ready ? "Not ready" : fullAccess ? "Full access" : zcode ? `Edit / ${programmingReady ? "Full access" : "not ready"}` : facts.authentication === "required" ? "Sign in" : facts.authentication === "unknown" ? "Sign-in?" : codex ? "Model unverified" : "Ready";
  const gear = facts.gear;
  const gearLine = !gear ? "" : gear.available
    ? `Gear (optional): available — primary ${gear.primary ? "yes" : "no"}, peer ${gear.peer ? "yes" : "no"} (bundled Ora AI Boost ${gear.version || "version unreported"}).`
    : `Gear (optional): unavailable — ${gear.reason || "the bundled Ora AI Boost does not serve this tool"}. ${gear.remedy || ""}`;
  const components = readinessState.components || {};
  const componentLines = [
    components.bridge ? `Bundled Agent Bridge: ${components.bridge.status === "ok" ? `${components.bridge.version} at ${components.bridge.path}` : `${components.bridge.status} — ${components.bridge.reason} ${components.bridge.remedy}`}` : "",
    components.loop ? `Bundled Programming Loop: ${components.loop.status === "ok" ? `${components.loop.version} (adapters: ${(components.loop.adapters || []).join(", ") || "none"})` : `${components.loop.status} — ${components.loop.reason} ${components.loop.remedy}`}` : "",
    components.boost ? `Bundled Ora AI Boost: ${components.boost.status === "ok" ? `${components.boost.version} at ${components.boost.path}` : `${components.boost.status} — ${components.boost.reason} ${components.boost.remedy}`}` : "",
  ];
  info.textContent = [...new Set([full.textContent, facts.message, authentication,
    facts.compatibility ? `Agent Bridge compatibility of the installed ${label}: ${facts.compatibility}${facts.compatibility === "unknown" ? " (outside the exercised release evidence; the check's warnings name what is known)" : ""}.` : "",
    gearLine,
    `Executable: ${facts.executable || "not reported by Agent Bridge"}`,
    `Version: ${facts.version || "not reported by Agent Bridge"}`,
    zcode ? `Current stage permission: ${fullAccess ? "Full access under your account" : messageStage() === "programming" ? "Full access requested; readiness not established" : facts.effective_permission === "edit" ? "Edit (document edits; approval-needing shell work cannot run headlessly)" : "not established"}.` : "",
    zcode ? `Programming and code repairs: ${programmingReady ? "Full access under your account; Git and tests can run without an approval connection" : "Full access readiness has not been established"}. Other stages and document assessments keep Edit. No global setting changes.` : "",
    zcode ? "This readiness check makes no model call and executes no Git command or test; actual execution remains unverified." : "",
    zcode && !programmingReady ? programming?.reason : "",
    codex ? "The selected model's acceptance is unverified. This check makes no model call. Each request uses Codex's current model and account settings." : "",
    ...componentLines,
    facts.reason, facts.next_action, ...(facts.warnings || [])].filter(Boolean))].join("\n");
  chip.title = `${info.textContent}\nSelect to show these details under More.`;
}
// Readiness stays beside the coding tool; its details open under More.
$("readiness").onclick = () => {
  const more = $("more");
  more.open = true;
  $("more-tool").hidden = false;
  $("readiness-detail").scrollIntoView({block: "nearest"});
};
$("recheck").onclick = guard(() => refreshReadiness(true));

// Step 5's own Reviewer picker is independent of the step 3 coding tool: it
// starts out matching it, and afterwards changing either changes only itself.
// An unavailable saved selection is preserved — greyed as a disabled option
// with its reason under the picker — never silently switched or erased.
function reviewerOptions() {
  const peers = readinessState.peers;
  if (peers) {
    return peers.map(peer => ({id: peer.peer, label: peer.label || peer.peer,
                               capable: peer.work === "supported",
                               reason: peer.work === "unsupported"
                                 ? `${peer.label || peer.peer} has no Agent Bridge work mode; it cannot assess in-app.`
                                 : peer.work === "supported" ? "" : `${peer.label || peer.peer}'s in-app compatibility is unknown${peer.reason ? `: ${peer.reason}` : ""}. Recheck refreshes readiness and discovery.`}));
  }
  return hostChoices.map(host => ({id: host.id, label: host.name,
                                   capable: host.conversation !== false,
                                   reason: host.conversation === false ? `${host.name} has no in-app conversation route.` : ""}));
}
function renderReviewerChoices() {
  const entries = reviewerOptions();
  const heldReason = id => entries.find(entry => entry.id === id && !entry.capable)?.reason || "";
  const fill = (select, entryList) => {
    select.replaceChildren(...entryList.map(entry => {
      const option = new Option(entry.label, entry.id);
      option.disabled = !entry.capable;
      return option;
    }));
  };
  const capable = entries.filter(entry => entry.capable);
  const stepSelect = $("step-reviewer");
  const held = stepSelect.value;
  // With no work-capable route at all, a held choice keeps its own (disabled)
  // option — staying selected and greyed with its reason — so a later Recheck
  // restores exactly what was chosen instead of resetting to defaults; only a
  // picker holding no recognizable choice shows the placeholder.
  if (!capable.length && !entries.some(entry => entry.id === held)) {
    stepSelect.replaceChildren(new Option("No work-capable harness found", ""));
  } else {
    fill(stepSelect, entries);
  }
  const tool = selectedToolId();
  const preferred = (capable.find(entry => entry.id === tool) || capable[0] || {}).id || "";
  // The picker starts out matching the step-3 tool; afterwards changing
  // either one changes only itself, so the held choice survives — including
  // an unavailable one, which stays selected and greyed with its reason.
  const heldKnown = entries.some(entry => entry.id === held) ? held : "";
  stepSelect.value = heldKnown || preferred;
  stepReviewerInitialized = true;
  const select = $("reviewer");
  const peerHeld = select.value;
  // The explicitly chosen peer is retained the same way: it stays among its
  // own disabled options while every route is down, and recovery restores it.
  if (!capable.length && !(reviewerChosen && entries.some(entry => entry.id === peerHeld))) {
    select.replaceChildren(new Option("No work-capable harness found", ""));
  } else {
    fill(select, entries);
  }
  // The second-opinion peer defaults to a different HARNESS — an honest,
  // checkable fact. Whether that is a different lab is confirmed only by what
  // the run's own passes report. An explicitly chosen peer is kept even when
  // it has become unavailable, greyed with its reason.
  const stepReviewer = stepSelect.value;
  const peerPreferred = (capable.find(entry => entry.id !== stepReviewer) || capable[0] || {}).id || "";
  const peerHeldKnown = entries.some(entry => entry.id === peerHeld) ? peerHeld : "";
  select.value = reviewerChosen && peerHeldKnown ? peerHeldKnown : peerPreferred;
  updateOpinionNote();
  unavailableReviewerNote(heldReason(stepSelect.value), heldReason(select.value));
  updateSecondOpinion();
}
function unavailableReviewerNote(authorReason, reviewerReason) {
  const note = $("reviewer-unavailable");
  if (!note) return;
  const lines = [authorReason ? `Reviewer: ${authorReason}` : "",
                 reviewerReason ? `Second-opinion peer: ${reviewerReason}` : ""].filter(Boolean);
  note.textContent = lines.join(" ");
  note.hidden = !lines.length;
}
function updateOpinionNote() {
  const select = $("reviewer"), note = $("opinion-note");
  const tool = $("step-reviewer").value;
  const same = !!select.value && select.value === tool;
  note.textContent = [
    select.value ? (same
      ? "the second opinion runs in the same harness in a fresh session; whether that is the same lab is known only from what the run reports"
      : "the second opinion runs in a different harness; whether that is a different AI lab is known only from what the run reports") : "",
    "One second opinion costs 3 model calls; full iteration up to 7.",
  ].filter(Boolean).join(" · ");
}
$("step-reviewer").onchange = () => { stepReviewerChosen = true; renderReviewerChoices(); };
$("reviewer").onchange = () => { reviewerChosen = true; updateOpinionNote(); };

function updateSecondOpinion() {
  const available = workspace === "specification" || workspace === "plan";
  $("second-opinion").hidden = !available;
  $("verification-choice").hidden = workspace !== "build";
  const on = available && $("opinion-toggle").checked;
  $("reviewer").hidden = !on;
  $("reviewer-label").hidden = !on;
  $("iterate-label").hidden = !on;
  $("reviewer").disabled = !on;
  $("iterate-toggle").disabled = !on;
  $("review").textContent = !available ? "Run independent verification" : on ? "Run review with second opinion" : `Review the ${workspaces[workspace].title}`;
  $("review").title = !available ? "Sends or copies the complete Ora Verification request through one click." : on
    ? "Runs the three-pass pipeline through Bridge: the Reviewer assesses, the second harness evaluates, the Reviewer revises."
    : "Runs one independent assessment through the selected Reviewer and saves its verdict to the document.";
  // Both second-opinion roles need a work-capable route: the button greys
  // with its reason while the held selections stay exactly as chosen.
  if (available) {
    const block = routeBlock($("step-reviewer").value) || (on ? routeBlock($("reviewer").value) : null);
    if (block && $("step-reviewer").value) {
      $("review").disabled = true;
      $("review").title = `${block.reason}. ${block.remedy} The chosen selections, draft and project context stay as they are.`;
    } else {
      $("review").disabled = false;
    }
  }
  updateOpinionNote();
}
$("opinion-toggle").onchange = updateSecondOpinion;
$("iterate-toggle").onchange = updateSecondOpinion;

async function runReview() {
  const config = workspaces[workspace];
  if (!config || !currentId) return;
  if (config.assessment) {
    // The step-5 Reviewer picker names the assessing tool; it is independent
    // of the step 3 coding tool. The second-opinion picker stays the peer.
    const tool = $("step-reviewer").value, secondOpinion = $("opinion-toggle").checked;
    const reviewer = secondOpinion ? $("reviewer").value : "";
    if (!tool || (secondOpinion && !reviewer)) { status("Choose the Reviewer and, for a second opinion, a work-capable peer first."); return; }
    const blocked = routeBlock(tool);
    if (blocked) { status(`${blocked.reason}. ${blocked.remedy}`, "warning"); return; }
    const id = currentId;
    let result;
    try {
      // The workspace's assessment-stage key ("specification"/"planning") is
      // the one stage name the whole review route accepts and records. The
      // originating project is captured before dispatch, so a switch while
      // the acknowledgement is awaited never shows this run under the other
      // project.
      result = await api("review", {id, tool, reviewer, stage: config.assessment,
                                    iterate: secondOpinion && $("iterate-toggle").checked});
      if (currentId !== id) return;
      lastOperation = result.operation;
      await loadConversation();
      if (currentId !== id) return;  // A switch during the load never shows this run under the other project.
      updateOperation(result.operation);
      status(secondOpinion
        ? `Second opinion running: the author (${tool}) assesses, ${reviewer} evaluates, then ${tool} revises. Each pass is a separate recorded call; nothing counts as conversation history.`
        : `Review running in ${tool}. Its assessment will be saved to the document when the run finishes.`);
    } catch (error) {
      // The failure belongs to the originating project. After a switch, a
      // rejected or unconfirmed dispatch is attributed by name — starting it
      // again could repeat its model calls — while a post-acknowledgement
      // view failure is suppressed: the submitted run is already recorded in
      // its project and carried by that project's own display.
      if (currentId !== id) {
        if (!result) {
          const label = originLabel(id);
          status(error.status
            ? `${error.message} The review from ${label} was not started; nothing was sent.`
            : `${error.message} Whether the review from ${label} reached the local server is unknown. Reopen ${label} and check its recorded runs before starting it again.`);
        }
        return;
      }
      status(error.message);
    }
    return;
  }
  await buildStepDialog("verification");
}

// --- One-click stage handoffs -------------------------------------------------
// The step instructions live on the server (ora_vibe_coder/run.py), shared with
// Run to Completion, so manual and automated requests cannot drift apart. Send
// prepares and saves the complete request through the existing builders, then
// starts the next stage's in-app turn; Copy prepares, saves and writes the
// clipboard; Terminal opens the tool's own window for Hermes and Qwen Code.

const DELIVERY_STEPS = {
  "create-plan": {title: "Create the Plan", stage: "planning"},
  "implement-plan": {title: "Implement the Plan", stage: "programming"},
  "result": {title: "Save the Programming Result", stage: "programming-result"},
  "verification": {title: "Independently verify the implementation", stage: "verification"},
  "correction": {title: "Correct the implementation", stage: "programming"},
};
const BUILD_NOTES = {
  result: "Send runs without an automatic time limit and shows the final reply here. You cannot interact with the coding tool during that turn. Copy request delivers the same complete request into your existing implementation chat.",
  verification: "Send asks an AI coordinator here to arrange a separate fresh reviewer; it is not an automatic background review. Copy request delivers it to a separate AI chat when the work is outside Vibe Coder. The implementation AI must not verify its own work.",
  correction: "Send starts a correction turn that continues until the AI finishes or you stop Vibe Coder. If implementation is already under way in another AI chat, Copy request delivers the complete request there. After the Programming Result is updated, use step 6 for fresh independent verification.",
};
async function buildStepDialog(step) {
  const action = await chooseDelivery(step, BUILD_NOTES[step]);
  if (action) await deliverStep(step, action);
}

function selectedHost() { return hostChoices.find(h => h.id === selectedToolId()) || null; }

// Build's step 7 follows the saved verification result, not only the verdict
// heading: a completed NOT PASSED keeps the correction direction, while a
// REVIEW INCOMPLETE result — including a legacy combined label — offers
// finishing or rerunning the verification that never completed instead.
function buildNextAction() {
  if (workspace !== "build") return "correction";
  const verdict = verificationVerdict(project?.verification?.status, project?.verification?.path);
  return verdict.label === "INCOMPLETE" ? "verification" : "correction";
}
function updateBuildNextStep() {
  const unfinished = buildNextAction() === "verification";
  $("next-step-title").textContent = unfinished ? "Finish or rerun the verification" : "Correct the implementation";
  $("next-explain").textContent = unfinished
    ? "The saved Verification Report's review did not finish. Send or copy the independent verification request again to complete it; an unfinished assessment directs no source repairs."
    : "Ask the implementation AI to correct the findings in the Verification Report. Send in Vibe Coder, or copy the complete request into your existing implementation chat.";
  updateTransitionLabel();
}

// The step-6 button names the delivery: Send to the selected tool, or Open in
// Terminal for Hermes and Qwen Code, which have no in-app conversation.
function deliveryTool(step) {
  const role = {"create-plan": "planning", "implement-plan": "implementation", result: "implementation", verification: "verification", correction: "correction"}[step];
  return stageChoice(role).tool || selectedToolId();
}
function updateTransitionLabel() {
  if (!workspace) return;
  const host = routeLabelHost(deliveryTool(workspace === "build" ? buildNextAction() : workspaces[workspace].forward));
  $("transition").textContent = workspace === "build"
    ? (buildNextAction() === "verification" ? "Finish verification" : "Request repairs")
    : host && host.conversation !== false ? `Send to ${host.name}`
    : `Open ${host?.name || "the tool"} in Terminal`;
}

function chooseDelivery(step, note) {
  // Build's steps keep their explanatory dialog; the named buttons carry the
  // one-click actions. Hermes and Qwen Code get Open in Terminal as primary.
  const dialog = $("build-action-dialog");
  const tool = deliveryTool(step), host = routeLabelHost(tool);
  $("build-action-title").textContent = DELIVERY_STEPS[step]?.title || step;
  const blocked = routeBlock(tool);
  $("build-action-note").textContent = note
    + (host ? "" : " Choose a coding tool in step 3 to Send; Copy works without one.")
    + (blocked && host ? ` ${blocked.reason}. ${blocked.remedy}` : "");
  const send = $("build-action-send"), terminal = $("build-action-terminal");
  const capable = !!host && host.conversation !== false;
  send.hidden = !capable;
  send.textContent = capable ? `Send to ${host.name}` : "Send";
  send.disabled = !capable || !!blocked;
  send.title = blocked ? `${blocked.reason}. ${blocked.remedy} Copy request still delivers this step.` : "";
  terminal.hidden = !!capable;
  terminal.disabled = !host?.detected;
  return new Promise(resolve => {
    const cancel = $("build-action-cancel"), copy = $("build-action-copy");
    function finish(choice) {
      cancel.removeEventListener("click", onCancel); copy.removeEventListener("click", onCopy);
      send.removeEventListener("click", onSend); terminal.removeEventListener("click", onTerminal);
      dialog.removeEventListener("cancel", onCancel);
      dialog.close(); resolve(choice);
    }
    function onCancel(event) { event?.preventDefault(); finish(null); }
    function onCopy() { finish("copy"); }
    function onSend() { finish("send"); }
    function onTerminal() { finish("terminal"); }
    cancel.addEventListener("click", onCancel); copy.addEventListener("click", onCopy);
    send.addEventListener("click", onSend); terminal.addEventListener("click", onTerminal);
    dialog.addEventListener("cancel", onCancel);
    dialog.showModal();
  });
}

async function deliverStep(step, action = null, note = "") {
  if (!currentId || !workspace) return;
  const tool = deliveryTool(step);
  // A manual Copy request works without an in-app coding tool, as the step
  // dialog says: the server prepares and saves the packet for an external
  // chat without starting a tool. Send and the terminal route keep the
  // step-3 requirement.
  if (!tool && action !== "copy") { status("Choose the coding tool in step 3 first; Copy works only from a prepared request."); return; }
  const host = routeLabelHost(tool);
  if (!action) {
    action = host && host.conversation !== false ? "send" : "terminal";
    if (host && host.conversation === false && !host.detected) action = "copy";
  }
  if (action !== "copy" && lastOperation === undefined) {
    const blocked = routeBlock(tool);
    status(`${blocked.reason}. ${blocked.remedy}`, "warning"); return;
  }
  const id = currentId, selectedWorkspace = workspace;
  const upstreamStage = step === "create-plan" ? "specification" : step === "implement-plan" ? "planning" : null;
  const observedUpstream = upstreamStage ? project?.assessments?.[upstreamStage] : null;
  const upstream = observedUpstream?.path && observedUpstream.expected != null ? {path: observedUpstream.path, expected: observedUpstream.expected} : null;
  const text = $("message").value.trim();
  // The request carries the visible unsent step-4 text and the currently
  // attached files: project material plus this message's file choices.
  const files = workspace === "build"
    ? [...new Set([...(id === currentId ? material() : []), ...messageFilesFor(id, "build")].map(item => item.path))]
        .map(path => ({path}))
    : messageFiles().slice();
  const verifier = step === "verification" ? $("verification-verifier").value : "";
  const submittedAttachments = attachments.slice();
  if (step === "verification" && !verifier) {
    status("Choose the independent verifier for step 6, or leave it for the coordinator to ask.");
  }
  if (["implement-plan", "correction"].includes(step)) {
    await refreshProject();
    if (id !== currentId || selectedWorkspace !== workspace) return;
    if (!await confirmImplementationBasis()) return;
    if (id !== currentId || selectedWorkspace !== workspace) return;
  }
  status(`Preparing the ${DELIVERY_STEPS[step]?.title || step} request…`);
  const filePaths = files.map(item => item.path);
  let result;
  try {
    result = await api("deliver", {id, step, action, tool, text,
      files: filePaths,
      images: action === "send" ? submittedAttachments.map(item => ({name: item.name, data: item.data}))
                                : submittedAttachments.map(item => ({name: item.name})),
      verifier, upstream});
  } catch (error) {
    if (id === currentId) status(`${error.message} Your unsent text and files are retained; nothing was sent.`);
    return;
  }
  if (id !== currentId) return;
  if (result.file_state) { lastFiles = result.file_state; await refreshProject(); }
  if (result.path) { $("prepared-path").value = result.path; renderMoreRequest(); }
  if (action === "copy") {
    try {
      await navigator.clipboard.writeText(result.text);
      // The request is delivered through the clipboard: the unsent text and
      // the embedded files are consumed. Pictures cannot ride a copy, so they
      // stay in the composer for a route that can carry them.
      const originFiles = messageFilesFor(id, selectedWorkspace);
      for (const path of filePaths) {
        const item = originFiles.find(entry => entry.path === path);
        if (item) { const at = originFiles.indexOf(item); originFiles.splice(at, 1); }
      }
      if (currentId === id && workspace === selectedWorkspace && $("message").value.trim() === text) {
        $("message").value = "";
        composerGeneration += 1;
      }
      renderMaterialChosen();
      syncVisibleInput();
      const pictures = (result.pictures || []).join(", ");
      status(`Full ${DELIVERY_STEPS[step]?.title || step} request copied and saved. Paste it into the receiving AI chat; the app has not sent it.${pictures ? ` Pictures are not carried by a copy: ${pictures}.` : ""}`);
    } catch (_) {
      readerView = {id, workspace, role: null, element: $("reader")};
      render($("reader"), result.text); $("raw").value = result.text;
      $("packet-tools").hidden = false; $("raw-details").hidden = false; $("raw-details").open = true;
      $("delivery-note").textContent = `Saved ${DELIVERY_STEPS[step]?.title || step} request. Clipboard access was unavailable; the complete request is selected below for manual copy.`;
      $("raw").focus(); $("raw").select();
      status("Clipboard access was unavailable. The full saved request is selected in the document pane; use your browser's Copy command. Nothing was sent.");
    }
    renderMoreRequest();
    return;
  }
  if (action === "terminal") {
    status(result.message);
    return;
  }
  // Send: the server confirmed the turn was saved and started, so the unsent
  // step-4 text and its attachments are consumed exactly once.
  const originFiles = messageFilesFor(id, selectedWorkspace);
  for (const path of filePaths) {
    const item = originFiles.find(entry => entry.path === path);
    if (item) { const at = originFiles.indexOf(item); originFiles.splice(at, 1); }
  }
  attachments = attachments.filter(held => !submittedAttachments.includes(held));
  for (const item of submittedAttachments) if (!attachments.includes(item)) URL.revokeObjectURL(item.url);
  if (currentId === id && workspace === selectedWorkspace && $("message").value.trim() === text) {
    $("message").value = "";
    composerGeneration += 1;
  }
  renderAttachments();
  renderMaterialChosen();
  syncVisibleInput();
  lastOperation = result.operation;
  const replyStage = DELIVERY_STEPS[step]?.stage === "verification" ? "verification" : "programming";
  if (workspace === "build") {
    buildReplyStages.set(id, replyStage);
    $("build-reply-stage").value = replyStage;
    renderReadiness();
  }
  try { await loadConversation(); if (id === currentId) updateOperation(result.operation); }
  catch (error) { if (id === currentId) status(`Turn ${result.turn} was submitted, but this view could not refresh: ${error.message} Check the recorded turn before sending again.`); }
  updateSendState();
  status(`Sent to ${host?.name || tool} as turn ${result.turn}: the ${DELIVERY_STEPS[step]?.title || step} request is running. Watch the status bar; the complete answer appears in the conversation when it finishes.`);
}


// --- Questions at the response box, repairs, and the run banner ---------------

// The bare questions of the newest entry that ended with a "Questions for you"
// section, or of a run paused for them. With no such section, nothing shows:
// questions are never guessed from free text.
function currentQuestions() {
  if (runActive?.state === "paused-question") return runActive.questions || [];
  const entries = [...conversationTurns.map(turn => ({order: turn.turn, questions: turn.questions || []})),
                   ...reviewRuns.map(run => ({order: run.run, questions: []}))]
    .sort((a, b) => String(a.order).localeCompare(String(b.order)));
  const last = entries[entries.length - 1];
  return last?.questions || [];
}
function renderQuestions() {
  const box = $("questions-box");
  const questions = currentQuestions();
  box.hidden = !questions.length;
  if (!questions.length) return;
  box.replaceChildren();
  const title = document.createElement("strong");
  title.textContent = runActive?.state === "paused-question" ? "Answer to continue the run" : "Answer to continue";
  const list = document.createElement("ul");
  for (const question of questions) {
    const item = document.createElement("li");
    item.textContent = question;
    list.append(item);
  }
  box.append(title, list);
}

// When a turn saved the stage document and asked no questions, the status bar
// points to step 5 Review. The saved-file readback already observed the save.
function reviewSuggestion() {
  if (!workspace || runActive) return;
  const role = {specification: "Specification", plan: "Plan", build: "Programming Result"}[workspace];
  const last = conversationTurns[conversationTurns.length - 1];
  if (!last || last.state !== "complete" || (last.questions || []).length) return;
  if (last.artifact?.role !== role || last.artifact?.outcome !== "changed") return;
  if (!["finished", "complete"].includes(lastOperation?.state || "")) return;
  status(`${role} saved. Review it in step ${workspace === "build" ? "6" : "5"} when you are ready; reviewing is your choice, never a gate.`);
}

// Sorting an INCOMPLETE review's or a NOT PASSED report's findings into
// AI-can-fix and needs-input lists: one remembered read-only call, retried
// only through its Retry button, never turned into a verdict or a question.
const sortingState = new Map();
function sortingTrigger() {
  if (workspace === "build") {
    const verification = project?.verification;
    const label = verification?.status?.label || "";
    if (verification?.path && !verification.status?.unreadable && label.startsWith("NOT PASSED")
        && !/^NOT PASSED — (REVIEW|REVISION) INCOMPLETE/.test(label)) return {stage: "verification", key: `${verification.path}:${label}`};
    return null;
  }
  const key = workspace === "specification" ? "specification" : "planning";
  const assessment = project?.assessments?.[key];
  if ((assessment?.outcome || assessment?.verdict) === "NOT PASSED" && !assessment.issues?.length && !assessment.unreadable
      && ["current", "unconfirmed"].includes(assessment.applies)) return {stage: key, key: `${assessment.path}:${assessment.verdict}:${assessment.applies}`};
  return null;
}
async function reviewPointer() {
  const note = $("assessment-note");
  note?.querySelector(".repairs-pointer")?.remove();
  if (!currentId || !workspace || !sortingTrigger()) return;
  const pointer = document.createElement("p");
  pointer.className = "repairs-pointer";
  pointer.textContent = workspace === "build" ? "Repairs in Implementation AI Work (step 7)."
    : `Repairs in ${workspaces[workspace].title} AI Work (step 4).`;
  note.append(pointer);
}
async function renderRepairs() {
  const box = $("repairs-box");
  const trigger = currentId && workspace ? sortingTrigger() : null;
  reviewPointer();
  if (!trigger) { sortingState.clear(); box.hidden = true; box.replaceChildren(); return; }
  const cached = sortingState.get(trigger.key);
  if (cached) { renderRepairsResult(trigger, cached); return; }
  box.hidden = false;
  box.textContent = "Sorting the findings into AI-can-fix and needs-your-input…";
  let result;
  try { result = await api("sort-findings", {id: currentId, stage: trigger.stage}); }
  catch (error) { renderRepairsResult(trigger, {state: "failed", reason: error.message}); return; }
  if (!currentId || !workspace || !sortingTrigger() || sortingTrigger().key !== trigger.key) return;
  renderRepairsResult(trigger, result);
  if (result.state === "working") setTimeout(() => { sortingState.delete(trigger.key); if (currentId) refreshRepairs(); }, 2500);
}
function refreshRepairs() { if (currentId && workspace) renderRepairs(); }
function renderRepairsResult(trigger, result) {
  const box = $("repairs-box");
  sortingState.set(trigger.key, result);
  box.hidden = false;
  box.replaceChildren();
  if (result.state === "answered") {
    const ai = result.answer?.ai || [], user = result.answer?.user || [];
    const title = document.createElement("p");
    title.className = "repairs-title";
    const label = document.createElement("span");
    label.textContent = workspace === "build" ? "Findings the AI can fix" : "Review findings the AI can fix";
    title.append(label);
    if (ai.length && workspace !== "build") {
      const repair = document.createElement("button");
      repair.type = "button";
      repair.className = "primary";
      repair.textContent = "Request repairs";
      repair.title = "Sends the AI-fixable findings to the step-3 tool as one work turn on this stage.";
      repair.onclick = guard(async () => {
        if (!currentId) return;
        const tool = selectedToolId();
        if (!tool) { status("Choose the coding tool in step 3 first."); return; }
        const blocked = routeBlock(tool);
        if (blocked) { status(`${blocked.reason}. ${blocked.remedy}`, "warning"); return; }
        const result = await api("repair", {id: currentId, stage: trigger.stage, tool});
        lastOperation = result.operation;
        await loadConversation();
        if (currentId) updateOperation(result.operation);
      });
      title.append(repair);
    }
    box.append(title);
    if (ai.length) {
      const list = document.createElement("ul");
      for (const finding of ai) { const item = document.createElement("li"); item.textContent = finding; list.append(item); }
      box.append(list);
    } else {
      const none = document.createElement("p"); none.className = "repairs-hint";
      none.textContent = "No findings are AI-fixable on their own.";
      box.append(none);
    }
    if (user.length) {
      const askTitle = document.createElement("p"); askTitle.className = "repairs-title";
      askTitle.textContent = "Needs your input";
      box.append(askTitle);
      const list = document.createElement("ul");
      for (const finding of user) { const item = document.createElement("li"); item.textContent = finding; list.append(item); }
      box.append(list);
    }
    if (workspace === "build" && ai.length) {
      const hint = document.createElement("p"); hint.className = "repairs-hint";
      hint.textContent = "Step 7 Request repairs sends these findings with the correction request.";
      box.append(hint);
    }
    return;
  }
  if (result.state === "working") { box.textContent = "Sorting the findings into AI-can-fix and needs-your-input…"; return; }
  const failed = document.createElement("p");
  failed.className = "repairs-title";
  failed.textContent = "Findings sorting failed";
  box.append(failed);
  const reason = document.createElement("p"); reason.className = "repairs-hint";
  reason.textContent = result.reason || result.error || "The sorting call failed.";
  box.append(reason);
  const retry = document.createElement("button");
  retry.type = "button";
  retry.textContent = "Retry sorting";
  retry.onclick = guard(() => { sortingState.delete(trigger.key); renderRepairs(); });
  box.append(retry);
}

// One remembered read-only judgment when a saved record's wording leaves the
// binary verdict genuinely unclear. A failed call shows a reading error —
// never RECORD UNCLEAR beside an otherwise clear verdict.
const judgments = new Map();
function resolveUnclearVerdict(assessment, stageKey, attempt = 0) {
  // One remembered judgment per content key; a working call is polled until
  // it answers or fails, and a failed call shows a reading error.
  const key = `${assessment.path}:${assessment.reason || assessment.issues?.join(" ")}`;
  if (judgments.has(key)) return Promise.resolve(judgments.get(key));
  const tool = $("step-reviewer")?.value || selectedToolId() || "codex";
  return api("judgment", {id: currentId, stage: stageKey, tool})
    .catch(error => ({state: "error", reason: error.message}))
    .then(result => {
      if (result.state === "answered" || result.state === "error" || result.state === "failed") {
        judgments.set(key, result);
        return result;
      }
      if (attempt > 60) return {state: "error", reason: "The judgment call did not answer."};
      return new Promise(resolve => setTimeout(
        () => resolve(resolveUnclearVerdict(assessment, stageKey, attempt + 1)), 2500));
    });
}

const materialityChecks = new Map();
function compareChangedDocuments() {
  // An optional comparison must not compete with a deliberate turn or an
  // automatic run. A foreground request can also safely retire a comparison
  // already running when the user chooses to proceed.
  if (runActive || (lastOperation && ["starting", "running"].includes(lastOperation.state)
                    && !lastOperation.stage?.startsWith("materiality-"))) return;
  const id = currentId;
  for (const stage of ["specification", "planning"]) {
    const change = project?.assessments?.[stage]?.change;
    if (change?.state !== "pending") continue;
    const remembered = materialityChecks.get(`${id}:${change.key}`);
    if (remembered) {
      if (remembered.state === "failed" || remembered.state === "error") {
        change.state = "failed";
        change.reason = `The change comparison could not finish: ${remembered.reason || "No supported conclusion."} Approval applicability remains unconfirmed. You can still approve or advance.`;
      }
      continue;
    }
    const key = `${id}:${change.key}`, tool = selectedToolId();
    if (!tool) continue;
    materialityChecks.set(key, "working");
    const inspect = async () => {
      if (id !== currentId) return;
      let result;
      try { result = await api("materiality", {id, stage, tool}); }
      catch (error) { result = {state: "failed", reason: error.message}; }
      if (id !== currentId) return;
      if (result.state === "working") { setTimeout(inspect, 2500); return; }
      materialityChecks.set(key, result);
      if (result.state === "answered") await refreshProject();
      else {
        const a = project?.assessments?.[stage];
        if (a?.change) a.change.reason = `The change comparison could not finish: ${result.reason || "No supported conclusion."} Approval applicability remains unconfirmed. You can still approve or advance.`;
        renderAssessment();
      }
    };
    inspect();
  }
}

// --- Run to Completion -------------------------------------------------------

const STEP_NAMES = {specification: "Specification", planning: "Plan", build: "Build",
                     verification: "Independent verification", correction: "Correction"};
function runBannerText(run) {
  const step = STEP_NAMES[run.step] || run.step;
  const elapsed = run.elapsed_seconds != null ? ` · ${Math.round(run.elapsed_seconds)}s` : "";
  const contact = run.last_contact_seconds != null ? ` · last Bridge contact ${Math.max(0, Math.round(run.last_contact_seconds))}s ago` : "";
  const model = run.model ? ` · ${run.model}` : "";
  const reported = run.reported_model && run.reported_model !== "" ? ` (reported: ${run.reported_model})` : "";
  if (run.state === "running") return {head: `Run to Completion — ${step}${elapsed}${contact}${model}${reported}`, detail: run.observation || ""};
  if (run.state === "paused-question") return {head: `Run paused on ${step} — answer to continue`, detail: run.observation || ""};
  if (run.state === "paused-failure") return {head: `Run paused on ${step} — operational failure`, detail: run.reason || ""};
  if (run.state === "complete") return {head: "Run complete — verification passed", detail: run.observation || ""};
  return {head: "Run unfinished", detail: run.reason || run.observation || ""};
}
function renderRunBanner() {
  const banner = $("run-banner");
  const button = $("run-completion");
  if (!currentId) { banner.hidden = true; button.textContent = "Run to Completion"; return; }
  if (runActive) {
    const text = runBannerText(runActive);
    banner.hidden = false;
    banner.replaceChildren();
    const head = document.createElement("span"); head.className = "run-text";
    const strong = document.createElement("strong"); strong.textContent = text.head;
    head.append(strong, document.createElement("br"), text.detail);
    banner.append(head);
    button.textContent = "Stop Run";
    button.disabled = false;
    if (runActive.state === "paused-failure") {
      const resume = document.createElement("button"); resume.textContent = "Resume run";
      resume.onclick = guard(async () => {
        const id = currentId, result = await api("run-resume", {id});
        if (id !== currentId) return;
        updateRunState(result.run);
        status("Run resumed.");
      });
      banner.append(resume);
    }
    if (runActive.state.startsWith("paused")) {
      const copy = document.createElement("button"); copy.textContent = "Copy request";
      copy.title = "Prepares and saves this paused step's complete request for manual delivery.";
      copy.onclick = guard(async () => {
        const result = await api("run-copy", {id: currentId});
        try {
          await navigator.clipboard.writeText(result.text);
          // A copy cannot carry the brief's pictures, so the packet and the
          // status both name each one as not included.
          const pictures = (result.pictures || []).join(", ");
          status(`Paused step's request copied and saved. Paste it into the tool yourself; the app has not sent it.${pictures ? ` Pictures are not carried by a copy: ${pictures}.` : ""}`);
        } catch (_) { status("Clipboard access was unavailable. Use More to reach the saved request file and copy it there."); }
        $("prepared-path").value = result.path; renderMoreRequest();
      });
      banner.append(copy);
    }
    const stop = document.createElement("button"); stop.textContent = "Stop Run";
    stop.onclick = guard(async () => {
      status("Stopping the run; the active step is cancelled through the ordinary turn cancel…");
      const result = await api("run-stop", {id: currentId});
      updateRunState(result.run);
      status("Run stopped: recorded unfinished. Files already changed remain; nothing replays by itself.");
    });
    banner.append(stop);
    return;
  }
  banner.hidden = true;
  button.textContent = "Run to Completion";
  // Run stays unavailable while the step-3 tool cannot exchange turns in-app;
  // nothing is silently substituted. Configure Path offers the alternatives.
  const host = selectedHost();
  const blocked = routeBlock(selectedToolId());
  const loopBlocked = !blocked && workspace === "build" ? buildBlock(selectedToolId()) : null;
  const capable = !!host && !blocked && !loopBlocked;
  button.disabled = !currentId || !capable;
  button.title = blocked
    ? `${host?.name || "The step-3 tool"} cannot exchange turns in-app (${blocked.reason}). ${blocked.remedy} Choose a supported tool in step 3 or Configure Path; Copy and Terminal handoffs stay available.`
    : loopBlocked
    ? `${host?.name || "The step-3 tool"} cannot run this build entry: ${loopBlocked.reason}. ${loopBlocked.remedy}`
    : capable ? "" : `${host?.name || "The step-3 tool"} cannot exchange turns in-app, so an unattended run cannot use it. Choose a supported tool in step 3 or Configure Path; Copy and Terminal handoffs stay available.`;
  if (runLast && runLast.state === "open" && !notifiedRuns.has(runLast.run)) {
    notifiedRuns.add(runLast.run);
    status("The last Run to Completion shows unfinished: it was interrupted, and it does not resume by itself.");
  }
}
function updateRunState(report) {
  runActive = report?.run ? report : report?.active || null;
  runLast = report?.last || null;
  renderStatusActivity();
  renderRunBanner();
  renderQuestions();
  updateSendState();
}
const CONFIG_ROLES = [
  ["specification", "Specification"], ["specification_review", "Specification Review"],
  ["specification_second_opinion", "Specification Review Second Opinion"],
  ["planning", "Planning"], ["planning_review", "Planning Review"],
  ["planning_second_opinion", "Planning Review Second Opinion"],
  ["implementation", "Implementation"], ["review", "Implementation Review"],
  ["verification", "Verification"], ["correction", "Correction"],
];
const modelInventories = new Map();
const optionalRole = role => role.endsWith("_second_opinion");
function configurationRole() {
  return workspace === "specification" ? "specification" : workspace === "plan" ? "planning" : messageStage() === "verification" ? "verification" : "implementation";
}
function stageChoice(role) {
  return appSettings.role_defaults?.[role] || {};
}
function applyStageDefaults() {
  const choice = stageChoice(configurationRole());
  if (choice.tool) $("destination").value = hostChoices.find(h => h.id === choice.tool)?.name || "";
  const verification = stageChoice("verification");
  if (verification.tool) $("verification-verifier").value = verification.tool;
  updateHost();
  const reviewRole = workspace === "plan" ? "planning" : "specification";
  const reviewer = stageChoice(`${reviewRole}_review`), peer = stageChoice(`${reviewRole}_second_opinion`);
  $("step-reviewer").value = reviewer.tool || selectedToolId();
  stepReviewerChosen = !!reviewer.tool;
  $("opinion-toggle").checked = !!peer.tool;
  if (peer.tool) { $("reviewer").value = peer.tool; reviewerChosen = true; }
  renderReviewerChoices();
}

function inventory(tool) {
  if (!modelInventories.has(tool)) {
    modelInventories.set(tool, api("harness-models", {tool}).catch(() => ({models: [], reason: "Native choices could not be read. Use harness default follows the harness’s own model and effort. Saved choices are preserved."})));
  }
  return modelInventories.get(tool);
}
function retainedOption(select, value, label) {
  if (value && ![...select.options].some(option => option.value === value)) select.add(new Option(label || `${value} — saved choice (not in current inventory)`, value));
  select.value = value || "";
}
function roleRow(role, label, choice) {
  const row = document.createElement("div"); row.className = "role-row"; row.dataset.role = role;
  const heading = document.createElement("label"); heading.textContent = label;
  const tool = document.createElement("select"); tool.className = "role-tool"; tool.setAttribute("aria-label", `${label} harness`);
  const model = document.createElement("select"); model.className = "role-model"; model.setAttribute("aria-label", `${label} model`);
  const effort = document.createElement("select"); effort.className = "role-effort"; effort.setAttribute("aria-label", `${label} effort`);
  const note = document.createElement("small"); note.className = "role-origin";
  row.append(heading);
  for (const [title, select] of [["Harness", tool], ["Model", model], ["Effort", effort]]) {
    const field = document.createElement("div"); field.className = "role-choice";
    const fieldLabel = document.createElement("span"); fieldLabel.className = "role-field-label"; fieldLabel.textContent = title;
    field.append(fieldLabel, select); row.append(field);
  }
  row.append(note);
  tool.replaceChildren(new Option(optionalRole(role) ? "Off" : "Use selected harness", ""), ...hostChoices.map(h => new Option(h.name + (h.detected ? "" : " — unavailable"), h.id)));
  retainedOption(tool, choice.tool || "");
  const load = async (fresh = false) => {
    const selected = tool.value;
    const heldModel = fresh ? "" : choice.model || "", heldEffort = fresh ? "" : choice.effort || "";
    model.replaceChildren(new Option("Use harness default", ""));
    effort.replaceChildren(new Option("Use harness default", ""));
    retainedOption(model, heldModel); retainedOption(effort, heldEffort);
    model.disabled = effort.disabled = !selected;
    note.textContent = selected ? "Reading native model choices…" : optionalRole(role) ? "No second opinion will run." : "Uses the harness selected for the active stage, with its own defaults.";
    if (!selected) return;
    const facts = await inventory(selected);
    if (tool.value !== selected || !row.isConnected) return;
    const models = facts.models || [];
    const configured = facts.configured_model || "";
    model.replaceChildren(new Option(`Use harness default${configured ? ` (${configured})` : ""}`, ""), ...models.map(m => new Option(m.label || m.id, m.id)));
    retainedOption(model, fresh ? (models.some(m => m.id === configured) ? configured : "") : heldModel);
    const fillEfforts = value => {
      const selectedModel = models.find(m => m.id === (model.value || configured));
      const configuredEffort = facts.configured_effort || "";
      effort.replaceChildren(new Option(`Use harness default${configuredEffort ? ` (${configuredEffort})` : ""}`, ""), ...(selectedModel?.efforts || []).map(e => new Option(e === selectedModel.default_effort ? `${e} — model recommendation` : e, e)));
      retainedOption(effort, value);
    };
    fillEfforts(heldEffort);
    model.onchange = () => fillEfforts("");
    note.textContent = facts.reason || "Native harness choices; saved choices remain available.";
  };
  tool.onchange = () => { choice = {tool: tool.value}; load(true); };
  // Run after the row has been attached; discovery is optional and cannot block Save.
  queueMicrotask(() => load());
  return row;
}
function renderRoleRows(holder, values) {
  holder.replaceChildren();
  const header = document.createElement("div"); header.className = "role-row role-header";
  for (const title of ["Role", "Harness", "Model", "Effort"]) { const cell = document.createElement("strong"); cell.textContent = title; header.append(cell); }
  holder.append(header);
  for (const [role, label] of CONFIG_ROLES) holder.append(roleRow(role, label, values?.[role] || {}));
}
function readRoleRows(holder) {
  const values = {};
  for (const row of holder.querySelectorAll(".role-row[data-role]")) {
    const tool = row.querySelector(".role-tool").value;
    values[row.dataset.role] = {tool, model: tool ? row.querySelector(".role-model").value : "", effort: tool ? row.querySelector(".role-effort").value : ""};
  }
  return values;
}
function openConfiguration(forRun = false) {
  const config = forRun ? runActive?.config || pendingRunConfig || {} : {};
  const values = forRun && runActive ? runActive.effective_roles : {...appSettings.role_defaults, ...(config.roles || {})};
  renderRoleRows($("settings-roles"), values);
  $("settings-best-guess").checked = config.best_guess ?? appSettings.best_guess ?? false;
  $("settings-hide-advisory").checked = config.hide_advisory ?? savedHideAdvisory();
  $("configure-save").disabled = !currentId;
  $("configure-clear").disabled = !currentId;
  $("settings-location").textContent = appSettings.settings_path ? `Saved in ${appSettings.settings_path}` : "Saved in this installation’s settings.json.";
  $("configure-explain").textContent = forRun && runActive
    ? "Showing this run’s effective choices. Changes apply after any call already in progress. Save defaults applies to every project and future run; Apply to this run only leaves those defaults unchanged."
    : "Saved defaults apply to every project and future run until you change them. Apply to this run only is optional. Nothing here starts work.";
  $("settings-panel").hidden = false;
}
$("settings").onclick = guard(() => openConfiguration());
$("configure-path").onclick = guard(() => openConfiguration(true));
$("settings-close").onclick = () => { $("settings-panel").hidden = true; };
function savedHideAdvisory() {
  // Preserve the effective preference saved by either of the former warning controls.
  return !!appSettings.hide_advisory || appSettings.warn_skip_review === false;
}
$("settings-save").onclick = guard(async () => {
  appSettings = await api("settings", {warn_skip_review: !$("settings-hide-advisory").checked,
    best_guess: $("settings-best-guess").checked, hide_advisory: $("settings-hide-advisory").checked,
    role_defaults: readRoleRows($("settings-roles"))});
  if (currentId && workspace && !lastOperation?.active) applyStageDefaults();
  $("settings-panel").hidden = true;
  status("Defaults saved for all projects and future runs. Work already in progress keeps its current choices.");
});
async function saveRunConfiguration(config) {
  if (runActive) {
    const result = await api("run-configure", {id: currentId, config});
    updateRunState(result.run);
  } else pendingRunConfig = config;
  $("settings-panel").hidden = true;
}
$("configure-save").onclick = guard(async () => {
  await saveRunConfiguration({roles: readRoleRows($("settings-roles")), best_guess: $("settings-best-guess").checked,
    hide_advisory: $("settings-hide-advisory").checked});
  status("Choices applied to this run only. Saved defaults for all projects are unchanged.");
});
$("configure-clear").onclick = guard(async () => {
  // An active run captured its defaults on entry; explicitly using saved defaults refreshes that snapshot through overrides.
  await saveRunConfiguration({roles: runActive ? appSettings.role_defaults : {}, best_guess: !!appSettings.best_guess, hide_advisory: savedHideAdvisory()});
  status("This run now uses saved defaults. Global defaults are unchanged.");
});
$("run-completion").onclick = guard(async () => {
  if (!currentId || !workspace) { status("Choose or create a project first."); return; }
  if (runActive) {
    // The header's active-run action is the same stop as the banner's own
    // button: cancel the active step through the ordinary turn cancel and
    // record the run's truthful unfinished outcome.
    status("Stopping the run; the active step is cancelled through the ordinary turn cancel…");
    const result = await api("run-stop", {id: currentId});
    updateRunState(result.run);
    status("Run stopped: recorded unfinished. Files already changed remain; nothing replays by itself.");
    return;
  }
  const config = pendingRunConfig || {roles: {}, best_guess: !!appSettings.best_guess, hide_advisory: savedHideAdvisory()};
  // The skip-review warning is advisory; Continue is one click, and the
  // saved or run-only hide-advisory preference removes it.
  const spec = project?.assessments?.specification, plan = project?.assessments?.planning;
  const missing = [ ["Specification", spec], ["Plan", plan] ].filter(([_, a]) =>
    !(["COMPLETE", "PASSED"].includes(a?.outcome || a?.verdict) && ["current", "unconfirmed"].includes(a.applies) && !a.issues?.length && !a.unreadable));
  if (missing.length && !config.hide_advisory) {
    const proceed = await new Promise(resolve => {
      const dialog = $("run-warning");
      $("run-warning-text").replaceChildren(...missing.map(([label, _]) => {
        const line = document.createElement("p");
        line.textContent = `The ${label} has no current PASSED review; the run will skip that review.`;
        return line;
      }));
      const back = $("run-warning-back"), cont = $("run-warning-continue");
      function finish(choice) { back.removeEventListener("click", onBack); cont.removeEventListener("click", onGo); dialog.removeEventListener("cancel", onBack); dialog.close(); resolve(choice); }
      function onBack(event) { event?.preventDefault(); finish(false); }
      function onGo() { finish(true); }
      back.addEventListener("click", onBack); cont.addEventListener("click", onGo); dialog.addEventListener("cancel", onBack);
      dialog.showModal();
    });
    if (!proceed) return;
  }
  const brief = $("message").value;
  const files = messageFiles().slice().map(item => item.path);
  const images = attachments.slice().map(item => ({name: item.name, data: item.data}));
  const tool = selectedToolId();
  if (!tool) { status("Choose the step-3 coding tool for the active stage before starting a run."); return; }
  const blocked = routeBlock(tool);
  if (blocked) { status(`${blocked.reason}. ${blocked.remedy}`, "warning"); return; }
  status("Saving the brief and starting the run…");
  let result;
  try {
    result = await api("run-start", {id: currentId, entry: workspace === "plan" ? "planning" : workspace === "build" ? "build" : "specification",
                                     text: brief, images, files, config, tool});
  } catch (error) {
    status(`${error.message} The run did not start; your brief stays here for retry.`);
    return;
  }
  // The brief was saved with the run; the composer lets it go only now.
  $("message").value = "";
  composerGeneration += 1;
  attachments = [];
  renderAttachments();
  for (const item of messageFiles().slice()) { const list = messageFiles(); const at = list.indexOf(item); if (at >= 0) list.splice(at, 1); }
  renderMaterialChosen();
  syncVisibleInput();
  pendingRunConfig = null;
  updateRunState(result.run);
  status("Run to Completion started. The status bar carries the current step; the composer answers pauses only.");
});

// Automatic refresh: poll operation state and file changes; never rescan Documents.
function fileSignature(file) { return `${file.path}:${file.size}:${file.modified}`; }
function changedPaths(before, after) {
  // A change is an addition or modification (a fresh signature) or a
  // deletion (a known signature whose file is gone from the current list).
  const held = new Set((before || []).map(fileSignature));
  const fresh = new Set((after || []).map(fileSignature));
  const changed = (after || []).filter(file => !held.has(fileSignature(file))).map(file => file.path);
  for (const file of before || []) if (!fresh.has(fileSignature(file))) changed.push(file.path);
  return changed;
}
function lostContact() {
  // A connection error is never silent: the last working status may be stale,
  // and the honest display says the current state is unknown.
  if (contactLost) return;
  contactLost = true;
  const bar = $("status-bar");
  bar.dataset.operationKey = "";
  status("Lost contact with the local server — the status shown may be stale; the turn's current state is unknown until contact returns.", "warning");
}
function contactRestored() {
  if (!contactLost) return;
  contactLost = false;
  status("Contact with the local server returned; live status resumes.");
}
function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollTick, 2500);
  pollTick();
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  lastFiles = null;
}
async function pollTick() {
  if (!currentId || stopped || document.visibilityState === "hidden") return;
  const id = currentId, opening = projectOpeningGeneration;
  let state;
  try { state = await api("turn-state", {id}); }
  catch (error) {
    // The failed poll belonged to the project captured above. After a switch
    // or stop, the displayed project's own polling reports current truth; a
    // stale origin error must never pose as the displayed project's state.
    if (id !== currentId || opening !== projectOpeningGeneration || stopped) return;
    if (!error.status) lostContact();  // The server did not answer at all.
    else status(lastOperation === undefined
      ? `Live work status could not be loaded: ${error.message} Whether work is running is unknown; automatic refresh will check again.`
      : error.message, "warning");  // It answered with an error; it is not lost.
    return;
  }
  if (id !== currentId || opening !== projectOpeningGeneration || stopped) return;
  contactRestored();
  updateRunState(state.run);
  const wasUnknown = lastOperation === undefined, previous = lastOperation?.state;
  updateOperation(state.operation);
  if (wasUnknown && !state.operation && !runActive)
    status("Live work status is available again; no work is running in this project.");
  const reloadConversation = async () => {
    try { await loadConversation(); }
    catch (error) {
      if (id === currentId && opening === projectOpeningGeneration && !stopped)
        status(`Conversation history could not be loaded: ${error.message} Automatic refresh will try again; available documents remain open.`, "warning");
    }
  };
  if (!conversationLoaded) {
    await reloadConversation();
    if (id !== currentId || opening !== projectOpeningGeneration || stopped) return;
  }
  const operation = state.operation;
  // A run moves to its next step's turn without this poll ever observing a
  // terminal operation, so a completed step's saved reply would stay missing
  // from the conversation until the run ends. Whenever the observed run, its
  // current step, or the running turn changes, the conversation reloads from
  // the retained records — through the same loadConversation that preserves
  // unsent drafts and this project's switch protection.
  const runMark = runActive ? `${runActive.run}:${runActive.step}:${operation?.turn || ""}` : "";
  if (runMark !== conversationRunMark) {
    conversationRunMark = runMark;
    if (runMark) {
      await reloadConversation();
      if (id !== currentId || opening !== projectOpeningGeneration || stopped) return;  // The switch owns the view now.
      await refreshChanged([], {silent: true});
      return;
    }
  }
  if (operation) {
    // A terminal operation must be reflected in the displayed conversation:
    // refresh when its retained record still shows the turn or run open —
    // the first poll after opening a project has no previous state to
    // transition from, so a turn that finished before that poll would
    // otherwise keep its "Unfinished" message forever — or when a live state
    // transitioned to it.
    const turn = conversationTurns.find(item => item.turn === operation.turn);
    const run = reviewRuns.find(item => item.run === operation.turn);
    const openRecord = (turn && turn.state === "open") || (run && run.state === "open");
    // A terminal operation is reflected in the display only when the record
    // it reads from carries its outcome. An ordinary turn completes on its
    // saved reply while its maintenance outcome is one more note, so a view
    // loaded between those two saves shows the turn complete with a derived,
    // unconfirmed maintenance state — and the outcome recorded after that
    // load never reaches it without a reload. The same holds when the turn
    // or run is not displayed at all: the record exists, the display merely
    // predates it.
    const outcomeUnreflected = (turn && !turn.outcome_recorded) || (!turn && !run && !!operation.turn);
    // An operation that reports its own outcome note could not be recorded can
    // never be reflected in the retained records, so refetching on an open or
    // unreflected record would never converge; the live status line and its
    // warning stay the honest display of that unrecorded outcome.
    const outcomeKnownRecordable = operation.outcome_recorded !== false;
    if (["finished", "failed", "interrupted"].includes(operation.state)
        && ((openRecord || outcomeUnreflected) && outcomeKnownRecordable || (previous && previous !== operation.state))) {
      await reloadConversation();
      if (id !== currentId || opening !== projectOpeningGeneration || stopped) return;  // The switch owns the view now; its own polling refreshes it.
      await refreshChanged([], {silent: true});
      return;
    }
    // A live operation reconciles the unfinished message: a card drawn while
    // no operation was known must not keep claiming an interruption.
    if (openRecord && ["starting", "running"].includes(operation.state)
        && conversationLiveMark !== `${operation.turn}:${operation.state}`) {
      renderConversation();
    }
  }
  if (lastFiles === null) { lastFiles = state.files; return; }
  const changed = changedPaths(lastFiles, state.files);
  lastFiles = state.files;
  if (changed.length) await refreshChanged(changed, {});
}
async function refreshChanged(changed, {silent = false} = {}) {
  const id = currentId;
  const space = workspace;
  const view = readerView;
  const body = document.querySelector(".result-body");
  const top = body ? body.scrollTop : 0;
  const anchor = readerAnchor;
  await refreshProject();
  if (id !== currentId) return;  // The switch owns the view: this project's changed-file notice and its saved document selection never apply to the displayed project.
  // One place names which files changed: the status bar.
  if (!silent && changed.length) status(`Changed on disk: ${[...new Set(changed.map(path => path.split("/").pop()))].join(", ")}`);
  if (!$("packet-tools").hidden) return;  // A request or recovery view stays in place until the user opens a document.
  // A document or workspace selection made in this same project while the
  // refresh was underway owns the reader now; this refresh never rereads its
  // captured selection over the newer one.
  if (workspace !== space || readerView !== view) return;
  const opened = await readDocument(anchor || $("document").value);
  if (id !== currentId) return;  // Nor does the previously displayed project's reading position.
  // The same reader-identity protection, applied once the read finishes and
  // before the position is restored: a document or workspace selected while
  // this refresh's own read was underway owns the reader now, and its reading
  // position is never moved by the completing refresh.
  if (workspace !== space || readerView !== opened) return;
  if (body) body.scrollTop = top;  // Selection and reading position survive the refresh.
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") pollTick(); });
$("refresh").onclick = guard(async () => {
  remember(); const view = readerView; const id = currentId; const space = workspace;
  try {
    await refreshProject();
    if (id !== currentId) return;  // The switch owns the reader; the previously displayed project's document is not reread into it.
    if (!$("packet-tools").hidden) status(readerView?.kind === "absent"
      ? "Saved files reread. The earlier Markdown remains here for recovery; use Back to document or Prepare Again to check the request file."
      : "Saved files reread. The displayed handoff remains its prepared snapshot; use Back to document or Prepare Again for current sources.");
    else if (workspace !== space || readerView !== view) return;  // A document or workspace selection made while this refresh ran owns the reader now.
    else await readDocument(readerAnchor || $("document").value);
  } catch (error) {
    // A manual refresh is a view reread of the project it was started in; it
    // submits no work of its own. While that project is still displayed the
    // failure is reported here. After a switch it is suppressed, matching the
    // post-acknowledgement view failures: the displayed project's state was
    // never touched by another project's failed reread, and the origin
    // project's own records, refresh, and polling carry its truth.
    if (id === currentId) throw error;
  }
});

// Closing: watch the draining server until its final exit, then report only
// what was actually observed from this page.
function watchClosing() {
  const timer = setInterval(async () => {
    const id = currentId;
    if (!id) { clearInterval(timer); return; }
    try {
      const state = await api("turn-state", {id});
      if (id !== currentId) return;  // The displayed project changed during the wait; its operation is never shown here.
      if (state.operation) updateOperation(state.operation);
    } catch (error) {
      if (error.status) return;  // The server answered; keep watching until it exits.
      clearInterval(timer);
      // Describe only observed outcomes. The server stopping answering is
      // expected at exit but is not observed confirmation of it, and this
      // page observed only the selected project — so application-wide saving
      // and owned-process cleanup are explicitly left unconfirmed. Durable
      // recording of the last turn's outcome is likewise asserted only when
      // the outcome note's write was confirmed; a recording failure keeps
      // its warning in the closing text instead of false assurance.
      const last = lastOperation;
      const recording = !last || ["starting", "running"].includes(last.state) ? "" :
        last.outcome_recorded === true
          ? " The outcome note is recorded in the retained records."
          : last.outcome_recorded === false
            ? ` ${(last.warnings || []).find(item => item.startsWith("The outcome note could not be recorded")) || "Its outcome note could not be recorded."} Durable recording of this outcome is unconfirmed; reopen the project to see what its records hold.`
            : " No outcome note was confirmed as recorded for this turn.";
      let observed;
      if (!last) observed = "No work turn was observed running in this project.";
      else if (["starting", "running"].includes(last.state))
        observed = "This project's turn was still working at the last observation; its final outcome is unconfirmed.";
      else if (["failed", "interrupted"].includes(last.state))
        observed = `This project's last observed turn ${last.state}: ${last.reason || "no reason was recorded."}${recording}`;
      else if (last.maintenance && !["applied", "no-change", "none", ""].includes(last.maintenance))
        observed = `This project's last observed turn finished, but its Registry maintenance did not apply (${last.maintenance}); the reply itself remains in the turn records.${recording}`;
      else
        observed = `This project's last observed turn had finished, with Registry maintenance ${last.maintenance || "none"} observed on this page.${recording}`;
      status(`The local server stopped responding while closing; its exit was not observed from this page. ${observed} Saving of work in other projects and the ending of owned processes remain unconfirmed. Reopen from the launcher — each project's retained records reopen with it.`);
    }
  }, 2000);
}

guard(initialize)();
