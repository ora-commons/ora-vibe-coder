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
let readerView = null;
let hostChoices = [], browseHome = "", browseNote = "", folderChoice = null, folderState = null, folderLimit = null, fileState = null;
let createUnder = "", parentAutoFill = "", createCode = "", createMaterial = [];
let lastVisibleInput = null, pendingLocal = Promise.resolve();
const drafts = new Map(), editDrafts = new Map(), materialDrafts = new Map(), messageFileDrafts = new Map(), projectTools = new Map(), buildReplyStages = new Map();
let filePickerTarget = "project";
// Conversation, split view, readiness, and the reliability engine.
let splitMode = "chat", splitFraction = 0.42;
let conversationTurns = [], reviewRuns = [], attachments = [];
let lastOperation = null, lastFiles = null, pollTimer = null, readinessState = {checking: false, peers: null};
// The live operation state the last conversation render was drawn under, so
// a poll redraws an unfinished turn's message only when that state changed.
let conversationLiveMark = "";
let reviewerChosen = false, readinessChain = 0, contactLost = false;
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
  specification: {title: "Specification", purpose: "specification", review: "review-specification", forward: "create-plan", assessment: "specification", transition: "Prepare Plan request", defaultRole: "Specification"},
  plan: {title: "Plan", purpose: "planning", review: "review-plan", forward: "implement-plan", assessment: "planning", transition: "Prepare implementation request", defaultRole: "Plan"},
  build: {title: "Build & Verify", purpose: "programming", review: "verification", forward: null, assessment: null, transition: "Request corrections", defaultRole: "Verification Report"},
};
const defaultForwardRequest = {
  specification: "Create the Plan from the current Specification.",
  plan: "Implement the current Plan, using the Specification to judge the intended behavior.",
  build: "Correct the implementation using the current Verification Report and project documents.",
};
const firstSpecificationMessage = "Read the relevant documents already in this project folder, including notes, draft requirements, earlier conversations, and recorded errors, plus any files I attached to this message. Check any draft Specification against the current code if a code folder is selected. Identify new facts or conflicts, then update the Specification and Registry as appropriate. Ask me before choosing between contradictory requirements. Do not start the Plan or implementation.";
function notice(message) { $("notice").textContent = message; }
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
function signature(d) { return JSON.stringify([d.input, d.destination, material().map(item => item.path)]); }
const emptySignature = JSON.stringify(["", "", []]);
function observePacket(id, path, text, keep = null) {
  // A new save only displaces previews of the same outgoing file.
  for (const [key, d] of drafts) if (key.startsWith(`${id}:`) && d !== keep && d.packetPath === path && d.packet !== text) {
    d.saved = ""; d.packet = null; d.packetPurpose = ""; d.packetDestination = ""; d.packetPath = ""; d.packetCurrentOnly = false; d.recoveryPacket = null;
  }
}
function editorSignature(d) { return JSON.stringify([d.name, d.description, d.goals, d.parent, d.state, d.code]); }
function remember() {
  if (!currentId || !workspace) return;
  const d = draft();
  for (const key of ["input", "destination"]) d[key] = $(key).value;
  if (workspace === "build") d.verifier = $("verification-verifier").value;
  projectTools.set(currentId, d.destination);
  syncVisibleInput();
}
function rememberEditor() {
  if (!currentId || $("editor").hidden) return;
  const d = editDrafts.get(currentId) || {name: "", description: "", goals: "", parent: "", state: "ACTIVE", code: "", expected: null, dirty: true};
  d.name = $("edit-name").value; d.description = $("edit-description").value; d.goals = $("edit-goals").value;
  d.parent = $("edit-parent").value; d.state = $("edit-state").value; d.code = $("edit-code-location").dataset.path || d.code;
  d.expected = editorExpected; d.dirty = true;
  editDrafts.set(currentId, d);
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
function guard(fn) { return async () => { try { await fn(); } catch (error) { notice(error.message); } }; }
function local(fn) { const run = guard(fn); return () => { pendingLocal = run(); return pendingLocal; }; }
function sendVisibleInput(visible, keepalive) {
  try {
    fetch("/api/input-state", {method: "POST", keepalive: !!keepalive,
      headers: {"Content-Type": "application/json", "X-Ora-Token": token}, body: JSON.stringify({visible})}).catch(() => {});
  } catch (_) { /* best effort only */ }
}
function syncVisibleInput() {
  const visible = !!($("input").value.trim() || $("message").value.trim() || attachments.length
    || [...messageFileDrafts.values()].some(files => files.length));
  if (visible === lastVisibleInput) return;
  lastVisibleInput = visible;
  sendVisibleInput(visible);
}
function updateHost() {
  const host = hostChoices.find(h => h.name === $("destination").value);
  $("host-note").textContent = host
    ? `${host.detected ? `${host.name} terminal tool found on this computer.` : `${host.name} terminal tool was not found; Copy still works.`} ${host.notice}`
    : "Choose the coding tool that should receive this assignment. No model or provider is selected by Vibe.";
  renderReadiness();
  if (!reviewerChosen) renderReviewerChoices();
  updateSendState();
  if (!currentId || !workspace) return;
  const d = draft();
  const addressed = !!host && d.packetDestination === host.name && d.packet !== null;
  const ready = selectedReadiness();
  $("continue").textContent = host?.desktop_request === "prefilled"
    ? `Open ${host.name} desktop with request` : `Open ${host?.name || "selected"} app + copy request`;
  $("continue").disabled = !addressed || !host.desktop;
  $("continue").title = !host?.desktop ? `${host?.name || "The selected tool"} desktop app was not found on this computer.`
    : host.desktop_request === "prefilled" ? "Opens a new visible desktop chat with a short pointer to the saved full request. Review and send it there."
    : "Copies the full request, then opens the app. Paste it into a new chat there.";
  $("terminal").textContent = `Open ${host?.name || "selected tool"} in Terminal`;
  $("terminal").disabled = !addressed || !host.detected || !ready?.ready || ready.authentication === "required";
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
  hostChoices = data.hosts; browseHome = data.browse_home; browseNote = data.browse_note || "";
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
    $("setup-introduction").textContent = "Choose the coding tools to configure. Setup installs Vibe, its bundled Programming Loop product-file snapshot, and a launcher in your user folders. Unselected coding tools and their account settings are preserved.";
    $("install-app").hidden = false; $("remove-app").hidden = false;
  }
  $("setup").hidden = !!data.home;
  for (const id of ["new", "open"]) $(id).disabled = !data.home;
  if (!data.home) return;
  await loadProjects();
  if (data.last_project) {
    // Restore only what discovery currently offers as active: an archived
    // project is never silently reopened while the archive toggle is off.
    const entry = projectEntries.find(p => p.path === data.last_project);
    if (!entry || !entry.archived) {
      try {
        const opened = await api("open", {path: data.last_project});
        await chooseProject(opened.id, data.last_workspace in workspaces ? data.last_workspace : "specification");
        return;
      } catch (_) { /* the saved project folder is unavailable; normal first-use flow applies */ }
    }
  }
}
async function browseFolders(path) {
  const data = await api("folders", folderLimit ? {path, limit: folderLimit} : {path}); folderState = data;
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
      remove.onclick = guard(() => { const at = list.indexOf(item); if (at >= 0) list.splice(at, 1); composerGeneration += 1; renderMaterialChosen(); updateFilesNote(); });
      row.append(name, remove); holder.append(row);
    }
  }
  updateFilesNote();
  syncVisibleInput();
}
async function browseMaterialFiles(path = browseHome) {
  const data = await api("browse-files", {path}); fileState = data;
  $("file-path").value = data.path;
  $("file-location").textContent = data.path;
  $("file-list").replaceChildren(...data.entries.map(entry => { const b = document.createElement("button"); b.textContent = `${entry.directory ? "▸ " : ""}${entry.name}`; b.onclick = guard(async () => {
    if (entry.directory) { await browseMaterialFiles(entry.path); return; }
    const list = activeMaterial();
    if (list && !list.some(item => item.path === entry.path)) { list.push({name: entry.name, path: entry.path}); composerGeneration += 1; renderMaterialChosen(); }
    notice(`${entry.name} selected. Choose more, or choose Done.`);
  }); return b; }));
  $("file-note").textContent = data.limited ? "Showing the first 500 entries. Open a folder to see more." : "Folders open; files are selected. Source files are never changed or moved.";
}
async function openMaterialPicker(target = "project") {
  filePickerTarget = target;
  $("file-title").textContent = target === "message" ? "Add files to this message" : "Add existing material";
  $("file-explain").textContent = target === "message"
    ? "Choose Markdown or text files for the next AI message, including files outside this project folder. Their contents accompany only that message; the originals stay where they are."
    : "Choose notes or documents for AI to organize into this project's Registry, Specification, or Plan. Files stay where they are; nothing is copied or sent until you prepare a request.";
  if (activeMaterial() === null) { notice("Choose or create a project first; material belongs to a project."); return; }
  await browseMaterialFiles(browseHome); renderMaterialChosen(); $("file-picker").hidden = false;
}
async function loadProjects(rescan = false) {
  const data = await api(rescan ? "rescan" : "projects", {});
  roles = data.roles; projectsHome = data.home;
  projectEntries = data.projects;
  scanNotices = data.notices || [];
  projectPaths = Object.fromEntries(data.projects.map(entry => [entry.id, entry.path]));
  $("home").textContent = `Projects are discovered in: ${data.home}`;
  renderProjectOptions();
  if (!$("open-form").hidden) renderOpenList();
}
function visibleProjects() { return projectEntries.filter(p => showArchived || !p.archived); }
function setProjectControls(expanded = false) {
  const selected = !!(currentId && project);
  if (selected && !expanded) $("project-card").open = false;
  $("project-compact").hidden = !selected;
  $("project-controls").hidden = selected && !expanded;
  $("top").classList.toggle("compact", selected && !expanded);
  $("project-options").setAttribute("aria-expanded", String(selected && expanded));
  $("project-options").textContent = expanded ? "Hide project options" : "Project options";
  $("project-options").setAttribute("aria-label", expanded ? "Hide project controls" : "Change project or view project details");
}
function renderProjectOptions() {
  // The server supplies the composed lineage labels and their order; the
  // browser only renders them, marking archives and duplicate names' paths.
  const visible = visibleProjects();
  const duplicates = new Set(visible.filter((p, index) => visible.some((q, other) => other !== index && q.label === p.label)).map(p => p.label));
  $("project").replaceChildren(new Option("Choose a project", ""), ...visible.map(p => {
    const option = new Option(p.label + (p.archived ? " — Archived" : "") + (duplicates.has(p.label) ? ` — ${p.path}` : ""), p.id);
    option.title = p.notice ? `${p.path} — ${p.notice}` : p.path;
    return option;
  }));
  $("project").value = currentId;  // Refreshing never silently switches projects.
}
function renderOpenList() {
  const list = $("project-list");
  list.replaceChildren();
  const visible = visibleProjects();
  if (!visible.length) list.append(Object.assign(document.createElement("p"), {textContent: `No projects with a Project.md definition were found under ${projectsHome || "the selected projects folder"}.`}));
  for (const entry of visible) {
    const item = document.createElement("button");
    item.append(Object.assign(document.createElement("span"), {className: "entry-label", textContent: entry.label + (entry.archived ? " — Archived" : "")}));
    item.append(Object.assign(document.createElement("span"), {className: "entry-location", textContent: entry.notice ? `${entry.path} — ${entry.notice}` : entry.path}));
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
    rail.title = rail.getAttribute("aria-label");
    rail.setAttribute("aria-expanded", String(workspace === rail.dataset.stage));
  }
}
function renderOverviewSources() {
  const holder = $("overview-sources");
  holder.replaceChildren();
  if (project.raw !== null || !Array.isArray(project.overview_sources)) return;
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
  $("project-controls").after(noteElement);
}
function assessmentText(a) {
  if (a?.unreadable) return {label: "UNREADABLE", kind: "neutral", note: a.unreadable};
  if (!a || (!a.present && !a.untouched)) return {label: "NOT REVIEWED", kind: "neutral", note: "No assessment has been recorded."};
  if (a.untouched) return {label: "NOT STARTED", kind: "neutral", note: "The starter template has not been filled in."};
  if (!a.verdict || a.issues?.length) return {label: a.reason?.toLowerCase().includes("conflict") ? "CONFLICTING CONCLUSIONS" : "RECORD UNCLEAR", kind: "neutral", note: a.reason || (a.issues || []).join(" ")};
  const label = a.verdict.toUpperCase() === "INCOMPLETE" && a.findings
    ? `INCOMPLETE — ${a.findings} noted ${a.findings === 1 ? "deficiency" : "deficiencies"}` : a.verdict.toUpperCase();
  const kind = a.verdict.toUpperCase() === "COMPLETE" ? "complete" : a.verdict.toUpperCase() === "INCOMPLETE" ? "incomplete" : "neutral";
  const note = a.applies === "earlier" ? "The assessed document changed after this assessment; it applies to an earlier version."
    : a.applies === "unconfirmed" ? "The verdict is saved, but this review does not identify which document version it assessed."
    : a.issues.length ? a.issues.join(" ") : "Click to see the recorded assessment in the document.";
  return {label, kind, note};
}
function reportStatusText(status, missing) {
  if (!status) return missing;
  if (status.unreadable) return "COULD NOT READ";
  if (status.label === "Not reported") return missing === "NO RESULT" ? "RESULT UNCLEAR" : "VERDICT UNCLEAR";
  if (status.label.startsWith("Unknown")) return status.reason?.toLowerCase().includes("conflict") ? "CONFLICTING CONCLUSIONS" : "CONCLUSION UNCLEAR";
  return status.label.toUpperCase();
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
function showReportStatus(element, status, path, missing) {
  element.textContent = path ? reportStatusText(status, missing) : missing;
  element.className = `assessment ${{positive: "complete", working: "working", attention: "incomplete"}[status?.kind] || "neutral"}`;
  element.title = path ? `${status?.unreadable || status?.literal || status?.label || "Status unavailable"}\nSource: ${path}` : missing;
  showStatusExplanation(element.id === "result-status" ? "result-status-note" : "assessment-note", path,
    status?.unreadable || status?.reason || (path ? status?.basis_note || "The saved conclusion describes the work inspected; it does not verify later changes." : missing === "NO RESULT" ? "No Programming Result is selected or found." : "No Verification Report is selected or found."),
    status?.kind === "neutral" ? status?.evidence || [] : []);
  const open = guard(async () => {
    const entry = project?.reader?.find(file => file.path === path || `${project.root}/${file.path}` === path);
    if (!entry) return;
    $("prepared").hidden = true;
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
    if (assessment?.verdict?.toUpperCase() === "COMPLETE" && ["current", "unconfirmed"].includes(assessment.applies) && !assessment.unreadable && !assessment.issues?.length) continue;
    const state = assessment?.unreadable ? "could not be read"
      : assessment?.issues?.length ? "has an unclear review record"
      : assessment?.applies === "earlier" ? "was changed after its review"
      : assessment?.verdict?.toUpperCase() === "INCOMPLETE" ? "was reviewed as INCOMPLETE"
      : "has no COMPLETE review for its current version";
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
  const {label, kind, note} = assessmentText(project?.assessments?.[config.assessment]);
  $("result-status-note").hidden = true;
  const assessment = project?.assessments?.[config.assessment];
  showStatusExplanation("assessment-note", assessment?.path, note, assessment?.issues?.length ? assessment.evidence || [] : []);
  $("review-step-title").textContent = `Review the ${config.title}`;
  element.textContent = label;
  element.className = `assessment ${kind}`;
  element.title = note;
  const openAssessment = guard(async () => {
    const a = project?.assessments?.[config.assessment];
    const path = a?.path;
    $("prepared").hidden = true;  // The findings live in the document, not the packet.
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
    else notice(a?.unreadable ? `The assessed document could not be read, so whether it records an assessment is unknown. ${a.unreadable}`
              : a?.present ? "The recorded assessment has no Current review heading to show." : "No assessment has been recorded in this document yet.");
  });
  element.onclick = event => { event.preventDefault(); event.stopPropagation(); return openAssessment(); };
  element.onkeydown = event => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault(); event.stopPropagation(); element.click();
  };
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
  select.replaceChildren(...files.map(file => new Option(file.name + (file.not_started ? " — Not started" : ""), file.path)));
  select.value = held || "";
}
async function refreshProject() {
  if (!currentId) return;
  const id = currentId;
  const refreshed = await api("project", {id});
  if (id !== currentId) return;
  project = refreshed;
  $("project-name").textContent = project.name; $("project-location").textContent = project.root;
  $("project-compact-name").textContent = projectEntries.find(entry => entry.id === currentId)?.label || project.name;
  $("project-code").textContent = `Repository / code folder: ${project.code_folder || "No code folder selected."}`;
  render($("description"), project.description); render($("goals"), project.goals);
  renderOverviewSources(); renderConflicts(); statuses();
  const complete = project.programming_result?.status?.label === "COMPLETE" && project.verification?.status?.label === "PASSED";
  $("project-completion").hidden = !complete;
  $("project-completion").textContent = "REPORTED COMPLETE";
  $("project-completion").title = complete ? "The selected reports say implementation COMPLETE and verification PASSED for the work they describe. This is not user approval or verification of later changes." : "";
  $("stages").hidden = false;
  if (workspace) {
    if ($("prepared").hidden) $("prepared-path").value = project.handoff_path;
    renderAssessment();
    renderReader();
    updateFilesNote();
    $("transition").disabled = false;
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
    element.replaceChildren();
    const message = document.createElement("p");
    message.textContent = workspace === "build" ? "No saved Programming Result or Verification Report found." : `No ${workspaces[workspace].defaultRole} document is resolved yet.`;
    element.append(message);
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
  $("packet-tools").hidden = true; $("prepared").hidden = true; $("raw").value = "";
  const entry = (project?.reader || []).find(file => file.path === path);
  $("result-kind").textContent = entry ? (entry.origin === "association" ? "Associated document — read-only" : "Project document — read-only") : (workspace === "build" ? "Verification" : workspaces[workspace].title);
  $("result-title").textContent = entry?.name || workspaces[workspace].defaultRole;
  return await readFile(path, $("reader"));
}
function showPacket(text, purpose) {
  const currentOnly = draft().packetCurrentOnly;
  readerView = {id: currentId, workspace, role: null, kind: "packet", element: $("reader")};
  render($("reader"), text); $("raw").value = text; $("packet-tools").hidden = false;
  $("raw-details").hidden = false;
  $("result-kind").textContent = currentOnly ? "Existing saved request · Review before replacing" : "Prepared request · Not sent";
  $("result-title").textContent = currentOnly ? "Current saved request" : ({"create-plan": "Request to create the Plan", "implement-plan": "Implementation request", "review-specification": "External Specification review request", "review-plan": "External Plan review request", verification: "Independent verification request", programming: "Programming or correction request"}[purpose] || `${workspaces[workspace].title} request`);
  $("prepared").querySelector("strong").textContent = currentOnly ? "Existing saved request" : "Complete request prepared";
  $("delivery-note").textContent = currentOnly
    ? "This is the current saved file; no new request was prepared. Review it, then Prepare again to replace it. Copy uses this displayed file."
    : "Saved request. Desktop opens a visible app, Terminal opens its command-line tool, and Copy lets you paste elsewhere. Confirm receipt and execution in the coding tool.";
  $("prepared").hidden = false;
  $("prepared-path").value = draft().packetPath || project?.handoff_path || "";
  updateHost();
}
function showAbsentPacket() {
  const recovery = draft().recoveryPacket || "";
  readerView = {id: currentId, workspace, role: null, kind: "absent", element: $("reader")};
  $("reader").textContent = "The saved request is no longer present. Prepare again to save a new request.";
  $("result-kind").textContent = "Saved request absent";
  $("result-title").textContent = "Request file removed";
  $("prepared").hidden = true;
  $("packet-tools").hidden = false;
  $("raw").value = recovery;
  $("raw-details").hidden = !recovery;
  $("raw-details").open = !!recovery;
  $("delivery-note").textContent = recovery
    ? "The earlier displayed Markdown is retained below for recovery. It is not the current saved file, so the delivery buttons are unavailable. Prepare again to save a new request."
    : "No earlier Markdown is available in this tab. Prepare again to save a new request.";
  updateHost();
}
async function chooseProject(id, preferredWorkspace) {
  remember(); rememberEditor(); currentId = id; project = null; workspace = "";
  setProjectControls();
  conversationTurns = []; reviewRuns = []; $("file-picker").hidden = true; filePickerTarget = "project";
  composerGeneration += 1;  // The composer now holds another project's draft context.
  stopPolling(); readinessChain += 1; lastOperation = null; lastFiles = null; contactLost = false; conversationLiveMark = "";
  $("turn-note").textContent = ""; $("turn-note").dataset.operationKey = ""; $("files-changed").hidden = true;
  $("project").value = id;
  $("editor").hidden = true; $("stage-panel").hidden = true;
  $("stages").hidden = true; $("packet-tools").hidden = true; $("prepared").hidden = true;
  $("project-completion").hidden = true;
  for (const field of ["project-location", "project-code", "description", "goals", "reader", "result-kind", "result-title", "assessment", "result-status"]) $(field).textContent = "";
  $("prepared-path").value = "";
  $("overview-sources").replaceChildren();
  $("raw").value = "";
  $("project-name").textContent = id ? "Selected project is not loaded" : "Choose or create a project";
  renderConversation();
  if (!id) { render($("description"), ""); render($("goals"), ""); renderReadiness(); return; }
  await refreshProject();
  await chooseWorkspace(preferredWorkspace in workspaces ? preferredWorkspace : "specification");
  await loadConversation();
  startPolling();
  // Startup explicitly initiates this project's first readiness check; the
  // poll chain that follows only reads, so it ends when the check finishes
  // rather than restarting the worker on every poll.
  refreshReadiness(true).catch(() => {});
}
async function chooseWorkspace(next) {
  if (!currentId || !project) { notice("Choose or reopen a project successfully first."); return; }
  remember(); rememberEditor(); workspace = next; $("editor").hidden = true; $("project-card").open = false;
  setProjectControls();
  readerAnchor = null;  // Each workspace starts from its own default document.
  const config = workspaces[workspace];
  const d = draft();
  // The coding tool belongs to the project, while each stage keeps its own
  // message and prepared handoff. A changed tool leaves an old packet stale.
  if (projectTools.has(currentId)) d.destination = projectTools.get(currentId);
  for (const key of ["input", "destination"]) $(key).value = d[key];
  if (workspace === "build") $("verification-verifier").value = d.verifier || "";
  updateMessageSuggestion(); renderMaterialChosen();
  $("build-reply-choice").hidden = workspace !== "build";
  $("build-reply-stage").value = buildReplyStages.get(currentId) || "programming";
  updateHost();
  $("stage-title").textContent = config.title;
  $("work-step-title").textContent = `Work with AI on ${workspace === "build" ? "the implementation" : `the ${config.title}`}`;
  $("result-step").hidden = workspace !== "build";
  $("review-step-number").textContent = workspace === "build" ? "6" : "5";
  $("next-step-number").textContent = workspace === "build" ? "7" : "6";
  $("transition").textContent = config.transition;
  $("next-step-title").textContent = {specification: "Create the Plan", plan: "Prepare implementation", build: "Correct the implementation"}[workspace];
  $("next-explain").textContent = {
    specification: "Prepare a complete request to create or revise the Plan from this Specification. Read it, then open an interactive coding-tool session or copy the full request.",
    plan: "Prepare a saved implementation request containing the Specification, Plan, and Ora Programming instructions. Leave the instruction blank for the whole Plan, or name a narrower part. Inspect the request before opening an interactive coding-tool session; Vibe does not start background implementation here.",
    build: "Ask the implementation AI to correct the findings in the Verification Report. Send in Vibe Coder, or copy the complete request into your existing implementation chat."
  }[workspace];
  $("instruction-label").textContent = workspace === "plan" ? "Implementation instruction — optional" : "Instruction for this next action — optional";
  $("input").placeholder = defaultForwardRequest[workspace];
  $("review-explain").textContent = config.assessment
    ? `Ask the selected tool to assess whether the current ${config.title} sufficiently guides the next work. Its advisory verdict is saved in this document.`
    : "Ask an AI coordinator to arrange a fresh, independent Ora Verification review and save a truthful Verification Report. Send in Vibe Coder, or copy the complete request into another AI chat. The implementation AI must not verify its own work.";
  $("portable-handoff").hidden = !config.assessment;
  $("stage-panel").hidden = false;
  $("packet-tools").hidden = true; $("prepared").hidden = true; $("raw").value = "";
  for (const field of ["result-kind", "result-title"]) $(field).textContent = "";
  $("reader").textContent = `Loading ${config.title}…`;
  for (const button of document.querySelectorAll(".rail")) button.setAttribute("aria-expanded", String(workspace === button.dataset.stage));
  updateSecondOpinion();
  api("workspace", {workspace}).catch(() => {});
  syncVisibleInput();
  try { await refreshProject(); }
  catch (error) {
    $("reader").textContent = `Could not load ${config.title}. ${error.message}`;
    throw error;
  }
  if (d.packet !== null) showPacket(d.packet, d.packetPurpose);
  else if (d.recoveryPacket !== null) showAbsentPacket();
  else await readDocument();
}
function codeLine(element, path) {
  element.dataset.path = path || "";
  element.textContent = path ? `Selected: ${path}` : "No code folder selected.";
}
async function openEditor() {
  if (!currentId || !project) { notice("Choose or reopen a project successfully first."); return; }
  remember(); await refreshProject();
  const d = editDrafts.get(currentId) || {name: project.name, description: project.description, goals: project.goals,
    parent: project.parent || "", state: project.archived ? "ARCHIVED" : "ACTIVE",
    code: project.paths.Code || "", expected: project.raw, dirty: false};
  editorExpected = d.expected;
  for (const field of ["name", "description", "goals", "parent"]) $(`edit-${field}`).value = d[field];
  $("edit-state").value = d.state;
  codeLine($("edit-code-location"), d.code);
  $("edit-location").textContent = `${project.raw === null ? "Will create only: " : "Edit: "}${project.root}/Project.md`;
  $("editor").hidden = false; $("edit-conflict").hidden = true;
  renderMaterialChosen();
}
$("project").onchange = guard(async () => {
  // Route the dropdown through the same open path as "Open existing", so the
  // chosen project is remembered and restored after a restart.
  const id = $("project").value;
  if (!id) { await chooseProject(""); return; }
  const result = await api("open", {path: projectPaths[id]});
  await chooseProject(result.id);
});
$("project-options").onclick = () => {
  const expanded = $("project-controls").hidden;
  setProjectControls(expanded);
  if (expanded) $("project").focus();
};
for (const rail of document.querySelectorAll(".rail")) rail.onclick = guard(() => chooseWorkspace(rail.dataset.stage));
$("edit-info").onclick = guard(() => openEditor());
$("edit-close").onclick = () => { rememberEditor(); $("editor").hidden = true; notice("Your project information input is retained in this tab. It has not been saved."); };
$("editor").oninput = rememberEditor;
$("edit-code-browse").onclick = guard(() => pickFolder("Choose the repository / code folder", path => { rememberEditor(); const d = editDrafts.get(currentId); if (d) d.code = path; codeLine($("edit-code-location"), path); }, project.code_folder ? project.code_folder.split("/").slice(0, -1).join("/") : browseHome));
$("edit-code-create").onclick = guard(() => pickFolder("Create the repository / code folder", path => { rememberEditor(); const d = editDrafts.get(currentId); if (d) d.code = path; codeLine($("edit-code-location"), path); }, project.code_folder || browseHome, null, true));
$("edit-code-none").onclick = guard(async () => { rememberEditor(); const d = editDrafts.get(currentId); if (d) d.code = ""; codeLine($("edit-code-location"), ""); });
$("edit-material").onclick = guard(() => openMaterialPicker());
$("edit-save").onclick = guard(async () => {
  rememberEditor(); const id = currentId, d = editDrafts.get(id);
  $("edit-save").disabled = true;
  try {
    const savedProject = await api("save", {id, expected: editorExpected, name: d.name, description: d.description, goals: d.goals,
      paths: {...(project?.paths || {}), Code: d.code || ""}, parent: d.parent, state: d.state});
    const latest = editDrafts.get(id), newer = latest && editorSignature(latest) !== editorSignature(d);
    if (newer) latest.expected = savedProject.raw; else editDrafts.delete(id);
    await loadProjects();  // The single updated entry rerenders the selector; the open project is not switched.
    if (currentId !== id) return;
    project = savedProject; editorExpected = savedProject.raw;
    if (!newer) $("editor").hidden = true;
    await refreshProject();
    if (workspace && $("packet-tools").hidden) await readDocument();
    notice(newer ? "Project.md saved with the submitted values. Your newer edits are retained and still need Save." : "Project.md saved. Stage documents and result fields were preserved.");
  }
  catch (error) { if (error.status === 409 && currentId === id) { editorConflict = error.current; $("edit-current").textContent = error.current === null ? "Project.md is now absent." : error.current; $("edit-conflict").hidden = false; } throw error; }
  finally { $("edit-save").disabled = false; }
});
$("edit-reviewed").onclick = () => { editorExpected = editorConflict; rememberEditor(); $("edit-conflict").hidden = true; notice("Current saved overview acknowledged. Your input is unchanged; review it and use Save explicitly."); };
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
    if (newer) notice("Project created with the submitted values. Your newer New Project input is retained; it has not been saved to this project.");
  } finally { $("create-save").disabled = false; }
});
$("open").onclick = guard(async () => {
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
  notice("Projects refreshed. Unsent input and the selected workspace are unchanged.");
});
$("open-browse").onclick = guard(() => pickFolder("Choose an existing project", async path => { $("open-form").hidden = true; const result = await api("open", {path}); await loadProjects(); await chooseProject(result.id); }));
$("document").onchange = guard(async () => { readerAnchor = $("document").value; await readDocument(); });
$("back-document").onclick = guard(async () => { $("prepared").hidden = true; await readDocument(); });
$("copy-path").onclick = guard(async () => {
  const path = $("prepared-path").value;
  if (!path) throw new Error("Prepare a request first to see its saved file path.");
  try { await navigator.clipboard.writeText(path); notice("Saved file path copied. Paste it into your coding tool or file browser."); }
  catch (_) { $("prepared-path").focus(); $("prepared-path").select(); notice("Clipboard access was unavailable. The saved file path is selected; use your browser's Copy command."); }
});
async function preparePurpose(purpose, instruction = null) {
  remember(); const d = draft(), id = currentId, selectedWorkspace = workspace, submitted = signature(d), submittedDestination = d.destination, view = readerView;
  const path = purpose === "implement-plan" ? project?.implementation_request_path : project?.handoff_path;
  $("prepare").disabled = true; $("review").disabled = true; $("transition").disabled = true;
  try {
    const result = await api("prepare", {id, stage: purpose, input: instruction === null ? (d.input.trim() || defaultForwardRequest[selectedWorkspace]) : instruction, destination: d.destination,
      context: {material: material().map(item => item.path)},
      expected: d.packetPath === path ? d.packet : null});
    observePacket(id, result.path, result.text);
    d.packet = result.text; d.packetPurpose = purpose; d.packetDestination = submittedDestination; d.packetPath = result.path; d.packetCurrentOnly = false; d.recoveryPacket = null;
    if (instruction === null) d.saved = submitted;
    if (id !== currentId || selectedWorkspace !== workspace) return;
    let shownView = null;
    if (readerView === view) { showPacket(d.packet, purpose); shownView = readerView; }
    await refreshProject();
    notice(!shownView || readerView !== shownView ? "Request saved. Your selected document remains open; choose this workspace again to view the saved request."
      : purpose === workspaces[selectedWorkspace].review
      ? "External review file saved at the path shown in the document pane. Preparing it did not run the review; the reviewer must save its verdict in the document."
      : "Request saved at the path shown in the document pane. Review it, then open your coding tool with it or copy the full Markdown.");
  }
  catch (error) {
    if (error.status !== 409) throw error;
    const name = purpose === "implement-plan" ? "implementation request" : "Handoff.md";
    observePacket(id, path, error.current, d);
    d.recoveryPacket = typeof error.current === "string" ? null : (d.packet ?? "");
    d.packet = typeof error.current === "string" ? error.current : null;
    d.packetPurpose = purpose; d.packetDestination = ""; d.packetPath = path; d.packetCurrentOnly = typeof error.current === "string";
    if (id !== currentId || selectedWorkspace !== workspace) return;
    if (readerView !== view) { notice("The saved request changed while you chose another document. Your selected document remains open; choose this workspace again to review the current request."); return; }
    if (typeof error.current === "string") {
      showPacket(error.current, purpose);
      $("result-kind").textContent = `Existing ${name} · Review before replacing`;
      notice(`The saved ${name} already exists or changed. Review it, then choose Prepare again to replace it. Nothing was overwritten.`);
    } else {
      showAbsentPacket();
      notice(`The saved ${name} was removed. ${d.recoveryPacket ? "The earlier Markdown is retained below; " : ""}Choose Prepare again to save a new request.`);
    }
  }
  finally { $("prepare").disabled = false; $("review").disabled = false; $("transition").disabled = false; }
}
$("prepare").onclick = local(() => preparePurpose(workspaces[workspace].review, `Review the current ${workspaces[workspace].title} and record the assessment.`));
$("review").onclick = local(runReview);
$("transition").onclick = local(() => {
  const config = workspaces[workspace];
  if (!config) return Promise.resolve();
  if (workspace === "build") return runBuildAction("correct");
  return preparePurpose(config.forward || config.purpose);
});
$("request-result").onclick = local(() => runBuildAction("result"));
$("input").onkeydown = event => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) { event.preventDefault(); $("transition").onclick(); } };
$("input").oninput = syncVisibleInput;
$("build-reply-stage").onchange = () => { buildReplyStages.set(currentId, $("build-reply-stage").value); composerGeneration += 1; updateSendState(); };
$("add-files").onclick = guard(() => openMaterialPicker());
$("add-message-files").onclick = guard(() => openMaterialPicker("message"));
function updateFilesNote() {
  const list = currentId && $("create").hidden ? material() : ($("create").hidden ? null : createMaterial);
  const count = list ? list.length : 0;
  $("files-note").textContent = count ? `${count} ${count === 1 ? "file" : "files"} selected as material` : "No additional files";
}
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
    try { await navigator.clipboard.writeText(result.text); if (readerView === view) notice("Full raw Markdown copied from the displayed saved request. Paste it where you intend to use it; the app has not sent it."); }
    catch (_) { if (readerView !== view) return; $("raw-details").open = true; $("raw").focus(); $("raw").select(); notice("Clipboard access was denied or unavailable. The full raw Markdown is selected below; use your browser's Copy command. No copy success is claimed."); }
  } catch (error) {
    if (error.status === 409) {
      observePacket(id, d.packetPath, error.current, d);
      d.packetDestination = "";
      d.recoveryPacket = typeof error.current === "string" ? null : (d.packet ?? "");
      d.packet = typeof error.current === "string" ? error.current : null;
      d.packetCurrentOnly = typeof error.current === "string";
      if (readerView !== view) return;
      if (id === currentId && selectedWorkspace === workspace && readerView === view) {
        if (typeof error.current === "string") { showPacket(error.current, d.packetPurpose); $("raw-details").open = true; $("result-kind").textContent = "Saved request changed — review this current file before another Copy. Prepare Again before Continue."; }
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
  if (!sameRequest()) { if (id === currentId && selectedWorkspace === workspace) notice("The instruction, coding tool, or selected files changed while the request was prepared. Copy again for the current choices."); return; }
  try {
    await navigator.clipboard.writeText(result.text);
    if (!sameRequest()) return;
    notice(`Full ${workspaces[workspace].title} request copied. Paste it into a visible AI conversation; no file was replaced and nothing was sent.${attachments.length ? " Attach your images separately." : ""}`);
  } catch (_) {
    if (!sameRequest()) return;
    readerView = {id, workspace, role: null, element: $("reader")};
    render($("reader"), result.text); $("raw").value = result.text;
    $("result-kind").textContent = "Copy-ready request · Not saved or sent";
    $("result-title").textContent = `${workspaces[workspace].title} request for another AI`;
    $("packet-tools").hidden = false; $("prepared").hidden = true; $("raw-details").hidden = false; $("raw-details").open = true;
    $("delivery-note").textContent = "Copy-ready preview. This request was not saved or sent, and it did not replace the saved request file.";
    $("raw").focus(); $("raw").select();
    notice("Clipboard access was unavailable. The full request is selected in the document pane; copy it there. No file was replaced or sent.");
  }
});
window.addEventListener("beforeunload", event => { if (dirty()) { event.preventDefault(); event.returnValue = ""; } });
window.addEventListener("pagehide", () => { stopPolling(); if (!stopped) sendVisibleInput(false, true); });
$("destination").onchange = () => { remember(); updateHost(); if (currentId && workspace && draft().packet) notice("Coding tool changed. Prepare Again to create a snapshot addressed to this tool."); };
async function deliverPrepared(route) {
  remember(); const d = draft(), id = currentId, selectedWorkspace = workspace, packet = d.packet, destination = d.packetDestination;
  if (!d.packet || d.packetDestination !== d.destination) throw new Error("Prepare Again for this coding tool before opening it.");
  const host = hostChoices.find(item => item.name === destination);
  const samePacket = () => id === currentId && selectedWorkspace === workspace && packet === d.packet
    && destination === d.packetDestination && destination === $("destination").value;
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
    notice(result.message);
  }
  catch (error) { if (error.status === 409) notice("The saved request changed. Use Copy to review the current saved text, or Prepare Again. Nothing was launched."); else throw error; }
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
    notice(result.note);
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
    const result = await api("install", {hosts: [...document.querySelectorAll("#setup-hosts input:checked")].map(box => box.value)}); $("installation-result").textContent = `Installed Vibe ${result.version}. Open the Ora Vibe Coder launcher at ${result.launcher}. ${result.note}`; $("close-setup").hidden = false; notice("Installation finished. Open the launcher; Vibe then finds your projects in your Documents folder.");
  } finally { $("install-app").disabled = false; }
});
$("remove-app").onclick = guard(async () => {
  if (!confirm("Remove the installed Vibe application, launcher, and the selected coding-tool entries? Projects, documents, settings, credentials, and unrelated files are preserved.")) return;
  $("remove-app").disabled = true;
  try {
    const result = await api("remove", {hosts: [...document.querySelectorAll("#setup-hosts input:checked")].map(box => box.value)});
    $("installation-result").textContent = result.retained.length ? `Removal finished. User additions or edits were retained at: ${result.retained.join(", ")}` : "Removal finished. Projects, documents, settings, credentials, and unrelated coding-tool files were preserved.";
    $("close-setup").hidden = false; notice("Removal finished. Close this source installer when you are ready.");
  } finally { $("remove-app").disabled = false; }
});
$("close-setup").onclick = guard(async () => { await api("stop", {}); stopped = true; notice("Installer stopped. Open Ora Vibe Coder from its launcher."); });
$("help-close").onclick = () => { $("help-panel").hidden = true; };
$("folder-go").onclick = guard(() => browseFolders($("folder-path").value));
$("folder-up").onclick = guard(() => browseFolders(folderState.parent));
$("folder-create").onclick = guard(async () => {
  const name = $("folder-new-name").value.trim();
  const result = await api("create-folder", {parent: folderState.path, name});
  $("folder-new-name").value = "";
  notice(`Created ${result.path}.`);
  await browseFolders(result.path);
});
$("folder-select").onclick = guard(async () => { await folderChoice(folderState.path); $("folder-picker").hidden = true; });
$("folder-cancel").onclick = () => { $("folder-picker").hidden = true; notice("Folder selection cancelled. No project work started."); };
$("file-cancel").onclick = () => { $("file-picker").hidden = true; filePickerTarget = "project"; renderMaterialChosen(); };
$("file-go").onclick = guard(() => browseMaterialFiles($("file-path").value));
$("file-up").onclick = guard(() => browseMaterialFiles(fileState.parent));
$("stop").onclick = guard(async () => {
  // Await in-flight local operations before warning about unsent input.
  await pendingLocal.catch(() => {});
  const unsent = [$("message").value.trim() && "message text", $("input").value.trim() && "instruction text",
    (attachments.length || [...messageFileDrafts.values()].some(files => files.length)) && "files selected for a message"].filter(Boolean);
  const state = await api("quit-state", {});
  const active = state.active_turns || 0;
  if ((unsent.length || active) && !confirm(`${active ? `${active} AI turn${active === 1 ? " is" : "s are"} still working. Stopping Vibe now interrupts that work; files already changed remain.\n\n` : ""}${unsent.length ? `You have unsent ${unsent.join(", ")}. The text and file choices remain visible in this tab until you close it.\n\n` : ""}Choose Cancel to keep working, or OK to stop Vibe now.`)) return;
  let result;
  try { result = await api("stop", {}); }
  catch (error) { notice(error.message); return; }
  stopped = true;
  stopPolling();
  if (result.interrupted) {
    notice(`Vibe is closing: ${result.note}`);
    watchClosing();
  } else {
    notice("Vibe stopped. Text remains available to select and copy in this tab. Saved project files were left in place; external AI work was not touched.");
  }
});
// --- Conversation, split view, readiness, and the reliability engine ---------

let docScrollPosition = 0, docWasVisible = true;
function applySplit() {
  const split = $("split"), divider = $("split-divider");
  const narrow = window.innerWidth <= 900;
  const mode = narrow ? splitMode : "split";
  const docVisible = mode !== "chat";
  const body = document.querySelector(".result-body");
  // Hiding a pane resets its scroll; the reading position travels with the
  // pane instead of being lost.
  if (!docVisible && docWasVisible) docScrollPosition = body ? body.scrollTop : 0;
  split.dataset.orientation = "split";
  split.dataset.mode = mode;
  split.style.gridTemplateRows = "";
  if (mode !== "split") split.style.gridTemplateColumns = "";
  else {
    const lead = (splitFraction * 100).toFixed(2), rest = ((1 - splitFraction) * 100).toFixed(2);
    split.style.gridTemplateColumns = `minmax(200px, ${lead}fr) 6px minmax(200px, ${rest}fr)`;
  }
  if (docVisible && !docWasVisible && body) body.scrollTop = docScrollPosition;
  docWasVisible = docVisible;
  divider.setAttribute("aria-orientation", "vertical");
  $("single-toggle").textContent = mode === "doc" ? "Show conversation" : "Show document";
}
function rememberSplit() {
  api("preferences", {split_fraction: splitFraction}).catch(() => {});
}
$("single-toggle").onclick = () => { splitMode = splitMode === "doc" ? "chat" : "doc"; applySplit(); };
window.addEventListener("resize", applySplit);
{
  const divider = $("split-divider");
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
  if (attachments.length >= 10) { notice("Attach at most 10 images with one message."); return; }
  if (!/^image\/(png|jpeg)$/.test(file.type) && !/\.(png|jpe?g)$/i.test(file.name)) {
    notice("Attach PNG or JPEG images; other file types are not delivered by this route.");
    return;
  }
  if (file.size > 8 * 1024 * 1024) { notice("One image is larger than 8 MiB and cannot be attached."); return; }
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
  for (const file of files) addAttachment(file).catch(error => notice(error.message));
});
$("message").oninput = () => { composerGeneration += 1; updateMessageSuggestion(); syncVisibleInput(); };

function originLabel(id) {
  // The selector's own name for a project, to attribute another project's
  // outcome while a different one is displayed.
  return projectEntries.find(entry => entry.id === id)?.label || projectPaths[id] || "its originating project";
}
async function send() {
  if (!currentId || !project) { notice("Choose or create a project first."); return; }
  const tool = selectedToolId();
  if (!tool) { notice("Choose the coding tool for this conversation, then send."); return; }
  // The originating project and the composer's draft identity are captured
  // before dispatch: a switch or an edit while the acknowledgement is awaited
  // must never reassign this submission, its result, or its consumption of
  // the composer to the project or draft now displayed.
  const originId = currentId;
  const originWorkspace = workspace;
  const generation = composerGeneration;
  const text = effectiveMessage();
  const submittedFiles = messageFiles().slice();
  if (!text.trim() && !attachments.length && !submittedFiles.length) { notice("Write a message or attach an image or file before sending."); return; }
  const stage = messageStage() || "specification";
  const submitted = attachments.slice();  // Exactly what leaves with this message.
  if (stage === "programming") {
    await refreshProject();
    if (originId !== currentId || originWorkspace !== workspace || generation !== composerGeneration || tool !== selectedToolId() || stage !== messageStage()) return;
    if (!await confirmImplementationBasis()) return;
    if (originId !== currentId || originWorkspace !== workspace || generation !== composerGeneration || tool !== selectedToolId() || stage !== messageStage()) return;
  }
  $("send").disabled = true;
  notice("");
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
        notice(error.status
          ? `${error.message} Your message and attachments are retained here; nothing was sent.`
          : `${error.message} Your message and attachments are retained here; whether the submission reached the local server is unknown. Reopen this project and check its recorded turns before sending it again.`);
      } else {
        const label = originLabel(originId);
        notice(error.status
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
      notice(`The message was submitted${result ? ` as turn ${result.turn}` : ""}, but updating this view failed: ${error.message} The turn's state is viewable after reopening or switching back to this project; sending the message again would start a second turn.`);
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
  const busy = !!lastOperation && ["starting", "running"].includes(lastOperation.state);
  $("message-label").textContent = workspace === "build"
    ? (messageStage() === "verification" ? "Reply to the verification coordinator" : "What should the AI change or explain in the implementation?")
    : `What should the AI change or explain in the ${workspaces[workspace]?.title || "current stage"}?`;
  $("send").disabled = !currentId || !selectedToolId() || busy;
  $("send").textContent = busy ? "AI is working — one turn at a time" : `Ask ${$("destination").value || "AI"} to work on ${workspace === "build" ? (messageStage() === "verification" ? "independent verification" : "the implementation") : `the ${workspaces[workspace]?.title || "current stage"}`}`;
}

// The saved conversation and the retained review runs, derived from records.
async function loadConversation() {
  if (!currentId) { conversationTurns = []; reviewRuns = []; renderConversation(); return; }
  const id = currentId;
  const data = await api("conversation", {id});
  if (id !== currentId) return;
  conversationTurns = data.turns || [];
  reviewRuns = data.runs || [];
  updateMessageSuggestion();
  resolvePendingDraft(null);
  renderConversation();
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
  appendBridgeDetails(card, turn.bridge_diagnostics);
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
  appendBridgeDetails(card, run.bridge_diagnostics);
  return card;
}
function appendBridgeDetails(element, diagnostics) {
  if (!diagnostics?.length) return;
  const details = document.createElement("details"), title = document.createElement("summary"), list = document.createElement("ul");
  details.className = "bridge-details";
  title.textContent = `Technical details (${diagnostics.length})`;
  for (const value of diagnostics) {
    const item = document.createElement("li"); item.textContent = value; list.append(item);
  }
  details.append(title, list); element.append(details);
}
function appendArtifactReadback(element, artifact) {
  if (!artifact) return;
  const line = document.createElement("p"); line.className = "artifact-readback";
  const outcomes = {changed: "The selected local document changed and was read back.",
    unchanged: "The selected local document was read back unchanged.",
    missing: "No document is available at the selected local path.",
    unreadable: "The selected local document could not be read back.",
    "selection-changed": "The selected document changed during this turn; its result is not confirmed."};
  line.textContent = [artifact.role, artifact.reason || outcomes[artifact.outcome], artifact.applies === "earlier" ? "This assessment covers an earlier document version." : ""].filter(Boolean).join(" — ");
  element.append(line);
  if (artifact.path) {
    const source = document.createElement("details"), title = document.createElement("summary"), path = document.createElement("p");
    title.textContent = `Local file: ${artifact.path.split("/").pop()}`; path.textContent = artifact.path;
    source.append(title, path); element.append(source);
  }
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
  if (!conversationTurns.length && !reviewRuns.length) {
    const hint = document.createElement("p"); hint.className = "hint";
    hint.textContent = "No conversation recorded yet. Write a message and press the button naming your coding tool and stage — it works through Bridge while your documents stay visible beside it.";
    holder.append(hint);
  }
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
  notice(`The turn failed; your message and attachments are available to edit and resend.${reason ? ` ${reason}` : ""}`);
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
  resolvePendingDraft(operation);
  const note = $("turn-note");
  if (operation && !["starting", "running"].includes(operation.state)) {
    const key = JSON.stringify([operation.project, operation.turn, operation.state, operation.elapsed_seconds,
      operation.reason, operation.maintenance, operation.maintenance_reason, operation.warnings,
      operation.bridge_diagnostics, operation.visible_warnings, operation.artifact]);
    if (note.dataset.operationKey === key) {
      lastOperation = operation;
      updateSendState();
      return;
    }
    note.dataset.operationKey = key;
  } else {
    note.dataset.operationKey = "";
  }
  const detailsOpen = note.querySelector(".bridge-details")?.open || false;
  note.replaceChildren();
  note.classList.remove("has-visible-warning");
  lastOperation = operation;
  let summary = "";
  if (!operation) {
    summary = conversationTurns.some(turn => turn.state === "open")
      ? "An earlier turn is unfinished: it was interrupted, nothing is running now, and nothing is replayed automatically."
      : "";
  } else if (["starting", "running"].includes(operation.state)) {
    summary = `Working — ${Math.round(operation.elapsed_seconds)}s elapsed, last Bridge contact ${Math.max(0, Math.round(operation.last_contact_seconds))}s ago.`;
  } else if (["failed", "interrupted"].includes(operation.state)) {
    summary = `${operation.state === "interrupted" ? "Interrupted" : "The turn failed"}: ${operation.reason || "no reason was recorded."}`;
    note.classList.add("has-visible-warning");
  } else if (operation.state === "finished") {
    const maintenance = operation.maintenance;
    if (["review-specification", "review-plan"].includes(operation.stage)) {
      const assessment = maintenance === "applied" ? " Assessment saved."
        : ` Assessment not saved.${operation.maintenance_reason ? ` ${operation.maintenance_reason}` : ""}`;
      summary = `Review completed in ${Math.round(operation.elapsed_seconds)}s.${assessment}`;
      if (maintenance !== "applied") note.classList.add("has-visible-warning");
    } else {
      const registry = maintenance === "applied" ? " Registry updated."
        : maintenance === "no-change" ? " Registry: no change needed."
        : maintenance && maintenance !== "none" ? ` Registry update not applied (${maintenance}).${operation.maintenance_reason ? ` ${operation.maintenance_reason}` : ""}`
        : "";
      summary = `Reply complete in ${Math.round(operation.elapsed_seconds)}s.${registry}`;
      if (maintenance && !["applied", "no-change", "none"].includes(maintenance)) {
        note.classList.add("has-visible-warning");
      }
    }
  }
  if (summary) {
    const line = document.createElement("span");
    line.textContent = summary;
    note.append(line);
  }
  if (operation && !["starting", "running"].includes(operation.state)) {
    appendArtifactReadback(note, operation.artifact);
    const diagnostics = operation.bridge_diagnostics || [];
    const visible = operation.visible_warnings || [];
    const classified = new Set([...diagnostics, ...visible]);
    // Unknown warning sources remain in full view; only Bridge event warnings
    // have been identified as diagnostics that require no action.
    const notices = [...new Set([...visible, ...(operation.warnings || []).filter(item => !classified.has(item))])];
    if (notices.length) note.classList.add("has-visible-warning");
    for (const warning of notices) {
      const line = document.createElement("p");
      line.className = "turn-warning";
      line.textContent = warning;
      note.append(line);
    }
    if (diagnostics.length) {
      const details = document.createElement("details");
      details.className = "bridge-details";
      details.open = detailsOpen;
      const heading = document.createElement("summary");
      heading.textContent = `Technical details (${diagnostics.length})`;
      const list = document.createElement("ul");
      for (const warning of diagnostics) {
        const item = document.createElement("li");
        item.textContent = warning;
        list.append(item);
      }
      details.append(heading, list);
      note.append(details);
    }
  }
  updateSendState();
}

// Background readiness: no model call, one poll chain per project. Only a
// recheck (startup's first check and the Recheck button) asks the server to
// start the worker; the chain's own polls just read the report, so the chain
// ends when checking turns false instead of restarting the worker forever.
async function refreshReadiness(recheck = false) {
  if (!currentId || stopped) return;
  const id = currentId, chain = ++readinessChain;
  let data;
  try { data = await api("readiness", {recheck}); }
  catch (error) { if (id === currentId) notice(error.message); return; }
  if (id !== currentId || chain !== readinessChain || stopped) return;
  readinessState = data;
  updateHost();
  renderReviewerChoices();
  if (data.checking) {
    setTimeout(() => { if (chain === readinessChain && currentId === id && !stopped) refreshReadiness(); }, 1500);
  }
}
function selectedReadiness() {
  return (readinessState.peers || []).find(peer => peer.peer === selectedToolId()) || null;
}
function renderReadiness() {
  const chip = $("readiness"), button = $("recheck");
  if (!currentId) { chip.hidden = true; button.hidden = true; return; }
  button.hidden = false;
  chip.hidden = false;
  if (readinessState.checking && !readinessState.peers) { chip.textContent = "Checking Bridge readiness…"; chip.title = "A background check that makes no model call."; return; }
  const facts = selectedReadiness();
  if (!facts) { chip.textContent = "Readiness not checked yet"; chip.title = ""; return; }
  const label = facts.label || facts.peer;
  chip.textContent = facts.ready
    ? `${label}: ready${facts.authentication === "required" ? " — sign-in required" : facts.authentication === "unknown" ? " — sign-in unconfirmed" : ""}`
    : `${label}: not ready`;
  chip.title = [facts.reason, facts.next_action, ...(facts.warnings || [])].filter(Boolean).join(" · ") || chip.textContent;
}
$("recheck").onclick = guard(() => refreshReadiness(true));

function renderReviewerChoices() {
  const select = $("reviewer");
  const capable = (readinessState.peers || []).filter(peer => peer.work === "supported");
  const held = select.value;
  // Harness identity only: a harness name establishes neither its model nor
  // its provider, so no lab family is claimed next to any option.
  select.replaceChildren(...capable.map(peer => new Option(peer.label, peer.peer)));
  if (!capable.length) select.replaceChildren(new Option("No work-capable harness found", ""));
  const tool = selectedToolId();
  // The default prefers a different HARNESS — an honest, checkable fact.
  // Whether that is a different lab is confirmed only by what the run's own
  // passes report.
  const preferred = (capable.find(peer => peer.peer !== tool) || capable[0] || {}).peer || "";
  // Only the user's own choice is kept; an initial render never locks in the
  // first-listed harness over the different-harness default.
  select.value = reviewerChosen && capable.some(peer => peer.peer === held) ? held : preferred;
  updateOpinionNote();
}
function updateOpinionNote() {
  const select = $("reviewer"), note = $("opinion-note");
  const tool = selectedToolId();
  const same = !!select.value && select.value === tool;
  note.textContent = [
    select.value ? (same
      ? "the same harness in a fresh session with no prior context; whether that is the same lab is known only from what the run reports"
      : "a different harness from the selected coding tool; whether that is a different AI lab is known only from what the run reports") : "",
    "One second opinion costs 3 model calls; full iteration up to 7.",
  ].filter(Boolean).join(" · ");
}
$("reviewer").onchange = () => { reviewerChosen = true; updateOpinionNote(); };

function updateSecondOpinion() {
  const available = workspace === "specification" || workspace === "plan";
  $("second-opinion").hidden = !available;
  $("verification-choice").hidden = workspace !== "build";
  const on = available && $("opinion-toggle").checked;
  $("reviewer").disabled = !on;
  $("iterate-toggle").disabled = !on;
  $("review").textContent = !available ? "Prepare verification request" : on ? "Run review with second opinion" : `Review the ${workspaces[workspace].title}`;
  $("review").title = !available ? "Prepares the complete Ora Verification request. Deliver it to an interactive coding-tool session to run the independent review." : on
    ? "Runs the three-pass pipeline through Bridge: the author assesses, the second harness evaluates, the author revises."
    : "Runs one independent assessment through the selected coding tool and saves its verdict to the document.";
  updateOpinionNote();
}
$("opinion-toggle").onchange = updateSecondOpinion;
$("iterate-toggle").onchange = updateSecondOpinion;

async function runReview() {
  const config = workspaces[workspace];
  if (!config || !currentId) return;
  if (config.assessment) {
    const tool = selectedToolId(), secondOpinion = $("opinion-toggle").checked;
    const reviewer = secondOpinion ? $("reviewer").value : "";
    if (!tool || (secondOpinion && !reviewer)) { notice("Choose the coding tool and, for a second opinion, a work-capable reviewer first."); return; }
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
      notice(secondOpinion
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
          notice(error.status
            ? `${error.message} The review from ${label} was not started; nothing was sent.`
            : `${error.message} Whether the review from ${label} reached the local server is unknown. Reopen ${label} and check its recorded runs before starting it again.`);
        }
        return;
      }
      notice(error.message);
    }
    return;
  }
  await runBuildAction("verify");
}

const buildActions = {
  result: {
    title: "Save the Programming Result",
    stage: "programming-result",
    instruction: "Update the one current Programming Result from the implementation actually performed. Record what was built, the code location and delivered revisions, checks and review evidence, and remaining work. Do not create a numbered copy or claim unfinished work is complete.",
    note: "Send in Vibe Coder runs without an automatic time limit and shows its final reply here. You cannot interact with the coding tool during that turn. Copy the full request into your existing visible implementation chat to work there using its own run history."
  },
  verify: {
    title: "Independently verify the implementation",
    stage: "verification",
    instruction: "Coordinate a fresh, independent Ora Verification review of the current implementation against the Specification and Plan. The implementation agent must not be its own verifier. Save or update one truthful Verification Report, including findings and any incomplete checks, and return the result to the user.",
    note: "Send in Vibe Coder asks an AI coordinator here to arrange a separate fresh reviewer; it is not an automatic background review. Copy the full request for a separate AI chat when the work is outside Vibe Coder. A Vibe turn shows status and its final reply here, but an external chat stays visible only in that coding tool."
  },
  correct: {
    title: "Correct the implementation",
    stage: "programming",
    instruction: "Correct the in-scope material findings in the current Verification Report using the approved Specification and Plan. Perform the normal checks and implementation review needed for those corrections, then update the one current Programming Result with what changed, what was checked, and anything still outstanding. Stop there. Do not run or commission a new Ora Verification review or update the Verification Report in this turn; the user starts fresh independent verification separately with step 6. If no report exists, explain what evidence is missing before changing code.",
    note: "Send in Vibe Coder starts a correction turn that continues until the AI finishes or you stop Vibe Coder. If implementation is already under way in another AI chat, copy the full request into that chat. After the Programming Result is updated, use step 6 for fresh independent verification."
  }
};

function chooseBuildDelivery(action) {
  const dialog = $("build-action-dialog");
  $("build-action-title").textContent = action.title;
  $("build-action-note").textContent = action.note + (selectedToolId() ? "" : " Choose a coding tool in step 3 to Send; Copy works without one.");
  return new Promise(resolve => {
    const cancel = $("build-action-cancel"), copy = $("build-action-copy"), send = $("build-action-send");
    send.disabled = !selectedToolId();
    function finish(choice) {
      cancel.removeEventListener("click", onCancel); copy.removeEventListener("click", onCopy);
      send.removeEventListener("click", onSend); dialog.removeEventListener("cancel", onCancel);
      dialog.close(); resolve(choice);
    }
    function onCancel(event) { event?.preventDefault(); finish(null); }
    function onCopy() { finish("copy"); }
    function onSend() { finish("send"); }
    cancel.addEventListener("click", onCancel); copy.addEventListener("click", onCopy);
    send.addEventListener("click", onSend); dialog.addEventListener("cancel", onCancel);
    dialog.showModal();
  });
}

async function runBuildAction(kind) {
  if (workspace !== "build" || !currentId) return;
  const action = buildActions[kind];
  const id = currentId, tool = selectedToolId();
  const originalReplyStage = $("build-reply-stage").value;
  if (kind === "verify") await refreshProject();
  if (id !== currentId || workspace !== "build") return;
  const choice = await chooseBuildDelivery(action);
  if (!choice || id !== currentId || workspace !== "build" || tool !== selectedToolId()) return;
  const correctionDetail = kind === "correct" ? $("input").value.trim() : "";
  const verifier = kind === "verify" ? $("verification-verifier").value : "";
  const verifierDirection = !verifier
    ? "No independent verifier has been selected. Show the user the available qualified reviewers and ask them to choose before commissioning one. Do not silently select a reviewer."
    : `The user selected ${verifier} as the independent verifier. Commission a fresh ${verifier} session that did not implement this work. If this chat cannot launch that session, explain how the user can start it with this complete request. If the verifier is unavailable or cannot be separated from the implementation agent, report that and ask before substituting.`;
  const savedResult = project?.programming_result;
  const resultDirection = !savedResult?.path
    ? "No Programming Result was found. Continue with the available code and requirements, and disclose the missing report."
    : `The Programming Result was found at ${savedResult.path}. Its displayed status is ${savedResult.status?.label || "unclear"}; read the report and actual candidate directly rather than treating the badge as proof.`;
  const instruction = kind === "verify"
    ? `${action.instruction}\n\n${verifierDirection} Record the verifier's actual tool and model/provider when reported; a different harness name alone does not prove a different AI provider. Honor any cross-vendor requirement in the accepted project materials, or ask if it cannot be confirmed.\n\n${resultDirection}`
    : correctionDetail ? `${action.instruction}\n\nAdditional instruction: ${correctionDetail}` : action.instruction;
  const selectedMaterial = material().map(item => item.path);
  const sameRequest = () => id === currentId && workspace === "build" && tool === selectedToolId()
    && (kind !== "verify" || $("verification-verifier").value === verifier)
    && (kind !== "correct" || $("input").value.trim() === correctionDetail)
    && JSON.stringify(material().map(item => item.path)) === JSON.stringify(selectedMaterial);
  if (kind === "correct") {
    await refreshProject();
    if (!sameRequest()) return;
    if (!await confirmImplementationBasis()) return;
    if (!sameRequest()) return;
  }
  if (choice === "copy") {
    const result = await api("preview", {id, stage: action.stage, input: instruction,
      destination: tool || "External AI chat", context: {material: selectedMaterial}});
    if (!sameRequest()) { if (id === currentId) notice("The coding tool, verifier, instruction, or selected files changed while the request was prepared. Copy again for the current choices."); return; }
    try {
      await navigator.clipboard.writeText(result.text);
      notice(sameRequest()
        ? `Full ${action.title} request copied. Paste it into ${kind === "verify" ? "a separate AI chat that can arrange a fresh independent reviewer" : "your existing implementation chat"}; nothing was sent or saved by Vibe Coder.`
        : "The choices changed during copying. The clipboard has the earlier request; copy again for the current choices.");
    } catch (_) {
      if (!sameRequest()) return;
      readerView = {id, workspace, role: null, element: $("reader")};
      render($("reader"), result.text); $("raw").value = result.text;
      $("result-kind").textContent = "Copy-ready request · Not saved or sent";
      $("result-title").textContent = action.title;
      $("packet-tools").hidden = false; $("prepared").hidden = true; $("raw-details").hidden = false; $("raw-details").open = true;
      $("delivery-note").textContent = "Clipboard access was unavailable. The complete request is selected below for manual copy.";
      $("raw").focus(); $("raw").select();
      notice("Clipboard access was unavailable. Use your browser's Copy command on the selected request. Nothing was sent or saved.");
    }
    return;
  }
  let result;
  try {
    result = await api("converse", {id, tool, stage: action.stage, text: instruction, images: [], files: selectedMaterial});
  } catch (error) {
    if (id === currentId) notice(error.status
      ? `${error.message} Nothing was sent; use this step again when ready.`
      : `${error.message} Delivery is uncertain. Check this project's recorded turns before sending again.`);
    return;
  }
  if (id !== currentId) return;
  const replyStage = action.stage === "verification" ? "verification" : "programming";
  if (!$("message").value.trim() && !attachments.length && $("build-reply-stage").value === originalReplyStage) {
    buildReplyStages.set(id, replyStage);
    $("build-reply-stage").value = replyStage;
    updateSendState();
  } else notice(`Turn ${result.turn} was submitted. Your unsent step 4 message remains under its current role; choose ${replyStage === "verification" ? "Independent verification" : "Implementation"} before replying to this new request.`);
  lastOperation = result.operation;
  try { await loadConversation(); if (id === currentId) updateOperation(result.operation); }
  catch (error) { if (id === currentId) notice(`Turn ${result.turn} was submitted, but this view could not refresh: ${error.message} Check the recorded turn before sending again.`); }
}

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
  const note = $("turn-note");
  note.dataset.operationKey = "";
  note.classList.add("has-visible-warning");
  const warning = document.createElement("p");
  warning.className = "turn-warning";
  warning.textContent = "Lost contact with the local server — the status above may be stale; the turn's current state is unknown until contact returns.";
  note.append(warning);
}
function contactRestored() {
  if (!contactLost) return;
  contactLost = false;
  notice("Contact with the local server returned; live status resumes.");
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
  const id = currentId;
  let state;
  try { state = await api("turn-state", {id}); }
  catch (error) {
    // The failed poll belonged to the project captured above. After a switch
    // or stop, the displayed project's own polling reports current truth; a
    // stale origin error must never pose as the displayed project's state.
    if (id !== currentId || stopped) return;
    if (!error.status) lostContact();  // The server did not answer at all.
    else notice(error.message);         // It answered with an error; it is not lost.
    return;
  }
  if (id !== currentId || stopped) return;
  contactRestored();
  const previous = lastOperation?.state;
  updateOperation(state.operation);
  const operation = state.operation;
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
      await loadConversation();
      if (id !== currentId || stopped) return;  // The switch owns the view now; its own polling refreshes it.
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
  if (!silent && changed.length) {
    const chip = $("files-changed");
    chip.hidden = false;
    chip.textContent = `Changed on disk: ${[...new Set(changed.map(path => path.split("/").pop()))].join(", ")}`;
    chip.title = changed.join("\n");
  }
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
  $("files-changed").hidden = true;
  try {
    await refreshProject();
    if (id !== currentId) return;  // The switch owns the reader; the previously displayed project's document is not reread into it.
    if (!$("packet-tools").hidden) notice(readerView?.kind === "absent"
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
      notice(`The local server stopped responding while closing; its exit was not observed from this page. ${observed} Saving of work in other projects and the ending of owned processes remain unconfirmed. Reopen from the launcher — each project's retained records reopen with it.`);
    }
  }, 2000);
}

guard(initialize)();
