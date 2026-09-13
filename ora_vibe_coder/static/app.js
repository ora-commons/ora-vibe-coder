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
let currentId = "", project = null, stage = "", roles = [], projectsHome = "", stopped = false;
let editorExpected = null, editorConflict = null, packetConflict = null;
let readerView = null;
let hostChoices = [], browseHome = "", folderChoice = null, folderState = null, fileChoice = null, fileDirectory = ".";
const drafts = new Map(), editDrafts = new Map();
const stageRoles = {specification: ["Specification"], planning: ["Plan"], programming: ["Programming Result", "User Guide", "Technical Documentation", "Product Overview"], verification: ["Verification Findings", "User Guide", "Technical Documentation", "Product Overview", "Report"], guided: ["Request"]};
const stageTitles = {specification: "Specification", planning: "Planning", programming: "Programming", verification: "Verification", guided: "Help me get started"};
function notice(message) { $("notice").textContent = message; }
function render(element, text) { element.innerHTML = md.render(text || "Not supplied yet."); }
function draft() {
  const key = `${currentId}:${stage}`;
  if (!drafts.has(key)) drafts.set(key, {input: "", destination: "", authority: "", protected: "", references: "", sensitive: [], saved: "", packet: null, packetDestination: "", expected: null, selected: false});
  return drafts.get(key);
}
function signature(d) { return JSON.stringify([d.input, d.destination, d.authority, d.protected, d.references, d.sensitive]); }
function observeHandoff(id, text) {
  // One outgoing file serves every stage. Retain input, but stop treating a
  // displaced packet as saved; another project's drafts are unaffected.
  for (const [key, d] of drafts) if (key.startsWith(`${id}:`) && d.packet !== text) d.saved = "";
}
function editorSignature(d) { return JSON.stringify([d.name, d.description, d.goals, d.paths]); }
function remember() {
  if (!currentId || !stage) return;
  const d = draft();
  for (const key of ["input", "destination", "authority", "protected", "references"]) d[key] = $(key).value;
  d.sensitive = [...document.querySelectorAll("#sensitive input:checked")].map(box => box.value);
  d.selected = $("existing").checked;
}
function rememberEditor() {
  if (!currentId || $("editor").hidden) return;
  editDrafts.set(currentId, {name: $("edit-name").value, description: $("edit-description").value, goals: $("edit-goals").value,
    paths: Object.fromEntries([...document.querySelectorAll("#paths input")].map(input => [input.dataset.role, input.value])), expected: editorExpected, dirty: true});
}
function dirty() {
  remember();
  return [...drafts.values()].some(d => signature(d) !== (d.saved || JSON.stringify(["", "", "", "", "", []]))) || [...editDrafts.values()].some(d => d.dirty) || ["new-name", "new-description", "new-goals", "new-directory"].some(id => $(id).value);
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
function updateHost() {
  const host = hostChoices.find(h => h.name === $("destination").value);
  $("host-note").textContent = host ? `${host.detected ? "Command found; login is checked by your coding tool." : "Command not found. Install or enable this coding tool to Continue."} ${host.notice}` : "Choose the coding tool that should receive this assignment. No model or provider is selected by Vibe.";
  if (!currentId || !stage) return;
  const d = draft();
  $("continue").textContent = `Continue in ${d.packetDestination || "coding tool"}`;
  $("continue").disabled = !host || !host.detected || !host.continuation || d.packetDestination !== host.name || d.packet === null;
}
async function initialize() {
  const data = await api("setup", {});
  hostChoices = data.hosts; browseHome = data.browse_home;
  $("destination").replaceChildren(new Option("Choose a coding tool", ""), ...hostChoices.map(h => new Option(h.name, h.name)));
  $("setup-hosts").replaceChildren(...hostChoices.map(h => { const p = document.createElement(data.installation ? "label" : "p"); p.textContent = `${h.name}: ${h.detected ? "command found — account access not checked" : "not found"}`; if (data.installation) { const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.value = h.id; p.prepend(checkbox); } return p; }));
  if (data.installation) {
    $("setup-introduction").textContent = "Choose the coding tools to configure. Setup installs Vibe, the maintained Programming Loop, and a launcher in your user folders. Unselected coding tools and their account settings are preserved. Specification and Planning also require the separately installed Gear companion.";
    $("choose-home").hidden = true; $("install-app").hidden = false; $("remove-app").hidden = false;
  }
  $("setup").hidden = !!data.home;
  for (const id of ["new", "open"]) $(id).disabled = !data.home;
  if (data.home) await loadProjects();
}
async function browseFolders(path) {
  const data = await api("folders", {path}); folderState = data;
  $("folder-path").value = data.path;
  $("folder-list").replaceChildren(...data.folders.map(folder => { const b = document.createElement("button"); b.textContent = `▸ ${folder.name}`; b.onclick = guard(() => browseFolders(folder.path)); return b; }));
  $("folder-note").textContent = data.limited ? "Showing the first 500 folders. Enter a location to select another." : "Only folders are listed. No project is created by browsing.";
}
async function pickFolder(title, callback, path = projectsHome || browseHome) {
  folderChoice = callback; $("folder-title").textContent = title;
  await browseFolders(path); $("folder-picker").hidden = false;
}
async function selectHome(path) {
  remember(); rememberEditor(); await api("select-home", {path});
  currentId = ""; stage = ""; project = null;
  $("setup").hidden = true; $("help-panel").hidden = true;
  for (const id of ["new", "open"]) $(id).disabled = false;
  await loadProjects(); await chooseProject(""); notice("Projects folder selected. Open existing work, or choose New project to create one deliberately.");
}
async function browseDocuments(directory) {
  const data = await api("documents", {id: currentId, directory}); fileDirectory = data.directory;
  $("file-location").textContent = `${project.root}/${data.directory}`;
  $("file-list").replaceChildren(...data.entries.map(entry => { const b = document.createElement("button"); b.textContent = `${entry.directory ? "▸ " : ""}${entry.name}`; b.onclick = guard(async () => { if (entry.directory) await browseDocuments(entry.path); else { fileChoice.value = entry.path; rememberEditor(); $("file-picker").hidden = true; notice("Document selected. Save project information to retain this link; the source document is unchanged."); } }); return b; }));
}
async function pickDocument(input) {
  fileChoice = input; $("file-title").textContent = `Link ${input.dataset.role}`;
  await browseDocuments("."); $("file-picker").hidden = false;
}
async function loadProjects() {
  const data = await api("projects", {});
  roles = data.roles; projectsHome = data.home;
  $("home").textContent = `Projects home: ${data.home}`;
  $("project").replaceChildren(new Option("Choose a project", ""), ...data.projects.map(p => new Option(p.name, p.id)));
  $("project").value = currentId;
  for (const role of roles.filter(role => role !== "Code" && ![...document.querySelectorAll("#sensitive input")].some(box => box.value === role))) {
    const label = document.createElement("label"), box = document.createElement("input"); box.type = "checkbox"; box.value = role;
    label.append(box, role); $("sensitive").append(label);
  }
}
function statuses() {
  for (const rail of document.querySelectorAll(".rail")) {
    const s = project.statuses[rail.dataset.stage];
    rail.querySelector(".status-icon").textContent = s.icon;
    rail.setAttribute("aria-label", `${stageTitles[rail.dataset.stage]} — reported ${s.label}; source ${s.source}`);
    rail.title = rail.getAttribute("aria-label");
    rail.setAttribute("aria-expanded", String(stage === rail.dataset.stage));
  }
}
async function refreshProject() {
  if (!currentId) return;
  const id = currentId;
  const refreshed = await api("project", {id});
  if (id !== currentId) return;
  project = refreshed;
  $("project-name").textContent = project.name; $("project-location").textContent = project.root;
  render($("description"), project.description); render($("goals"), project.goals); statuses();
  $("stages").hidden = false; $("reported-note").hidden = false;
  if (stage) {
    const s = project.statuses[stage];
    $("stage-status").textContent = s ? `Reported: ${s.label}` : "Guided entry · the same four stage methods";
    $("stage-status").title = s ? `Source: ${s.source}. Review quality and user approval are separate facts.` : "";
    $("outgoing").textContent = `Outgoing file: ${project.handoff_path}`;
    $("existing-label").hidden = !project.handoff_exists;
    $("code-location").textContent = `Code location (information only): ${project.paths.Code || "Not associated; document location does not imply code location."}`;
  }
}
async function material(role, element) {
  const view = readerView = {id: currentId, stage, role, element};
  element.textContent = `Loading ${role}…`;
  let result;
  try { result = await api("read", {id: view.id, role}); }
  catch (error) {
    if (readerView !== view) return;
    element.textContent = `Could not read ${role}. ${error.message}`;
    throw error;
  }
  if (readerView !== view) return;
  element.replaceChildren();
  const path = document.createElement("p"); path.textContent = result.path || `${role} is not associated.`; element.append(path);
  if (result.text !== null) { const body = document.createElement("div"); render(body, result.text); element.append(body); }
  else { const reason = document.createElement("p"); reason.textContent = result.reason; element.append(reason); }
  if (result.needs_selection) {
    const button = document.createElement("button"); button.textContent = "Select this outside-project reference and read it";
    button.onclick = guard(async () => {
      if (readerView !== view) return;
      try { await api("approve-reference", {id: view.id, role, path: result.path}); }
      catch (error) { if (readerView === view) throw error; return; }
      if (readerView !== view) return;
      await material(role, element); await refreshProject();
    }); element.append(button);
  }
  if (!result.path) { const button = document.createElement("button"); button.textContent = `Link an existing ${role} document`; button.onclick = guard(async () => { await openEditor(); $("association-details").open = true; const input = [...document.querySelectorAll("#paths input")].find(p => p.dataset.role === role); if (input) await pickDocument(input); }); element.append(button); }
}
async function readDocument(role = $("document").value) {
  if (!stage) return;
  $("packet-tools").hidden = true; $("raw").value = "";
  $("reader-caption").textContent = role === "Request" ? "Current Request — read-only" : role === "Report" && project.statuses.verification.literal !== "PASSED" ? "Previous REPORT — not evidence of a current pass." : "Current associated document — read-only";
  await material(role, $("reader"));
}
function showPacket(text) {
  readerView = {id: currentId, stage, role: null, element: $("reader")};
  render($("reader"), text); $("raw").value = text; $("packet-tools").hidden = false;
  $("reader-caption").textContent = "Prepared snapshot — full Markdown is available below; Copy checks the saved file";
  updateHost();
}
async function chooseProject(id) {
  remember(); rememberEditor(); currentId = id; project = null; stage = "";
  const view = readerView = {id, stage, role: "Request", element: $("request")};
  $("project").value = id;
  $("editor").hidden = true; $("stage-panel").hidden = true; $("project-overview").hidden = false;
  $("stages").hidden = true; $("reported-note").hidden = true; $("packet-tools").hidden = true;
  for (const field of ["project-location", "description", "goals", "reader", "reader-caption", "stage-status", "code-location", "outgoing"]) $(field).textContent = "";
  $("raw").value = "";
  $("project-name").textContent = id ? "Selected project is not loaded" : "Choose or create a project";
  $("request").textContent = id ? "No Request loaded for this project." : "No project selected.";
  if (!id) return;
  await refreshProject(); if (readerView !== view) return; await material("Request", $("request")); await chooseStage("specification"); notice("Project opened. Select any stage. Link existing documents without renaming them.");
}
async function chooseStage(next) {
  if (!currentId || !project) { notice("Choose or reopen a project successfully first."); return; }
  remember(); rememberEditor(); stage = next; $("editor").hidden = true; $("project-overview").hidden = false; $("project-overview").open = false;
  const view = readerView = {id: currentId, stage, role: null, element: $("reader")};
  const d = draft();
  for (const key of ["input", "destination", "authority", "protected", "references"]) $(key).value = d[key];
  for (const box of document.querySelectorAll("#sensitive input")) box.checked = d.sensitive.includes(box.value);
  $("existing").checked = d.selected;
  updateHost(); $("prepare").textContent = d.packet === null ? "Prepare request" : "Prepare Again";
  $("stage-title").textContent = stageTitles[stage];
  $("document").replaceChildren(...stageRoles[stage].map(role => new Option(role, role)));
  const rail = document.querySelector(`[data-stage="${stage}"]`) || document.querySelector(".rail");
  rail.after($("stage-panel")); $("stage-panel").hidden = false; $("packet-conflict").hidden = true;
  $("packet-tools").hidden = true; $("raw").value = ""; $("existing-label").hidden = true;
  for (const field of ["reader-caption", "code-location", "outgoing"]) $(field).textContent = "";
  $("stage-status").textContent = "Reported status unavailable until this stage is refreshed.";
  $("reader").textContent = `Loading ${stageTitles[stage]}…`;
  for (const button of document.querySelectorAll(".rail")) button.setAttribute("aria-expanded", String(stage === button.dataset.stage));
  try { await refreshProject(); }
  catch (error) {
    if (readerView !== view) return;
    $("stage-status").textContent = "Reported status unavailable — the project could not be refreshed.";
    $("reader").textContent = `Could not load ${stageTitles[stage]}. ${error.message}`;
    throw error;
  }
  if (readerView !== view) return;
  if (d.packet !== null) showPacket(d.packet); else await readDocument();
  notice("Input stays in this tab when you switch stages or projects.");
}
async function openEditor() {
  if (!currentId || !project) { notice("Choose or reopen a project successfully first."); return; }
  remember(); await refreshProject();
  const d = editDrafts.get(currentId) || {...project, expected: project.raw}; editorExpected = d.expected;
  for (const field of ["name", "description", "goals"]) $(`edit-${field}`).value = d[field];
  $("paths").replaceChildren();
  for (const role of roles) { const row = document.createElement("div"), label = document.createElement("label"), input = document.createElement("input"); row.className = "path-row"; label.textContent = role; input.dataset.role = role; input.value = d.paths[role] || ""; label.append(input); row.append(label); if (role !== "Code") { const button = document.createElement("button"); button.textContent = "Browse"; button.onclick = guard(() => pickDocument(input)); row.append(button); } $("paths").append(row); }
  $("edit-location").textContent = `${project.raw === null ? "Will create only: " : "Edit: "}${project.root}/Project.md`;
  $("editor").hidden = false; $("edit-conflict").hidden = true; $("editor").scrollIntoView({block: "start"});
}
$("project").onchange = guard(() => chooseProject($("project").value));
$("overview").onclick = guard(async () => {
  if (!currentId) return;
  $("project-overview").open = !$("project-overview").open;
});
for (const rail of document.querySelectorAll(".rail")) rail.onclick = guard(() => chooseStage(rail.dataset.stage));
$("guided").onclick = guard(() => chooseStage("guided"));
$("edit").onclick = guard(openEditor);
$("edit-close").onclick = () => { rememberEditor(); $("editor").hidden = true; notice("Your overview input is retained in this tab. It has not been saved."); };
$("editor").oninput = rememberEditor;
$("edit-save").onclick = guard(async () => {
  rememberEditor(); const id = currentId, d = editDrafts.get(id);
  $("edit-save").disabled = true;
  try {
    const savedProject = await api("save", {id, expected: editorExpected, name: d.name, description: d.description, goals: d.goals, paths: d.paths});
    const latest = editDrafts.get(id), newer = latest && editorSignature(latest) !== editorSignature(d);
    if (newer) latest.expected = savedProject.raw; else editDrafts.delete(id);
    if (currentId !== id) return;
    project = savedProject; editorExpected = savedProject.raw;
    if (!newer) $("editor").hidden = true;
    await refreshProject();
    if (stage && $("packet-tools").hidden) await readDocument();
    notice(newer ? "Project.md saved with the submitted values. Your newer overview edits are retained and still need Save." : "Project.md saved. Stage documents and result fields were preserved.");
  }
  catch (error) { if (error.status === 409 && currentId === id) { editorConflict = error.current; $("edit-current").textContent = error.current === null ? "Project.md is now absent." : error.current; $("edit-conflict").hidden = false; } throw error; }
  finally { $("edit-save").disabled = false; }
});
$("edit-reviewed").onclick = () => { editorExpected = editorConflict; rememberEditor(); $("edit-conflict").hidden = true; notice("Current saved overview acknowledged. Your input is unchanged; review it and use Save explicitly."); };
$("new").onclick = () => { $("create").hidden = false; $("new-location").textContent = `Under: ${projectsHome}`; };
$("new-directory").oninput = () => $("new-location").textContent = `Proposed directory: ${projectsHome}/${$("new-directory").value}`;
$("create-close").onclick = () => { $("create").hidden = true; };
$("create-save").onclick = guard(async () => {
  const fields = ["directory", "name", "description", "goals"], submitted = Object.fromEntries(fields.map(field => [field, $(`new-${field}`).value]));
  $("create-save").disabled = true;
  try {
    const result = await api("create", submitted);
    const newer = fields.some(field => $(`new-${field}`).value !== submitted[field]);
    if (!newer) { $("create").hidden = true; for (const field of fields) $(`new-${field}`).value = ""; }
    await loadProjects(); await chooseProject(result.id);
    if (newer) notice("Project created with the submitted values. Your newer New Project input is retained; it has not been saved to this project.");
  } finally { $("create-save").disabled = false; }
});
$("open").onclick = () => { $("open-form").hidden = false; };
$("open-close").onclick = () => { $("open-form").hidden = true; };
$("open-save").onclick = guard(async () => { const result = await api("open", {path: $("open-path").value}); $("open-form").hidden = true; await loadProjects(); await chooseProject(result.id); });
$("document").onchange = guard(readDocument);
$("back-document").onclick = guard(readDocument);
$("request-button").onclick = guard(() => readDocument("Request"));
$("refresh").onclick = guard(async () => {
  remember(); const view = readerView; await refreshProject();
  if (readerView !== view) return;
  if (!$("packet-tools").hidden) notice("Project fields refreshed. The displayed handoff remains its prepared snapshot; use Back to document or Prepare Again for current sources.");
  else await readDocument(view?.role || $("document").value);
});
$("inspect-handoff").onclick = guard(async () => {
  const d = draft(), id = currentId, selectedStage = stage;
  const saved = await api("handoff", {id});
  if (id !== currentId || selectedStage !== stage) return;
  observeHandoff(id, saved.text); d.expected = saved.text;
  $("packet-current").textContent = saved.text === null ? "No outgoing file exists yet." : saved.text;
  packetConflict = saved.text; $("packet-conflict").hidden = false;
});
$("packet-reviewed").onclick = () => { draft().expected = packetConflict; $("packet-conflict").hidden = true; notice("Current outgoing file acknowledged. Select the existing destination if applicable, then Prepare Again."); };
$("prepare").onclick = guard(async () => {
  remember(); const d = draft(), id = currentId, selectedStage = stage, submitted = signature(d), submittedDestination = d.destination; $("prepare").disabled = true;
  try {
    const result = await api("prepare", {id, stage: selectedStage, input: d.input, destination: d.destination, context: {authority: d.authority, protected: d.protected, references: d.references, sensitive: d.sensitive}, expected: d.expected, selected_existing: d.selected});
    observeHandoff(id, result.text);
    d.packet = result.text; d.packetDestination = submittedDestination; d.expected = result.text; d.saved = submitted;
    if (id !== currentId || selectedStage !== stage) return;
    showPacket(d.packet); $("prepare").textContent = "Prepare Again"; await refreshProject(); notice("Request saved as Handoff.md. Review the snapshot, then Continue in your coding tool or Copy the full Markdown.");
  }
  catch (error) {
    if (error.status === 409) {
      observeHandoff(id, error.current);
      if (id === currentId && selectedStage === stage) { packetConflict = error.current; $("packet-current").textContent = error.current === null ? "Handoff.md is now absent." : error.current; $("packet-conflict").hidden = false; $("outgoing-details").open = true; $("packet-conflict").scrollIntoView({block: "nearest"}); }
    }
    throw error;
  }
  finally { $("prepare").disabled = false; }
});
$("input").onkeydown = event => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) { event.preventDefault(); if (!$("prepare").disabled) $("prepare").onclick(); } };
$("copy").onclick = guard(async () => {
  const d = draft(), id = currentId, selectedStage = stage, view = readerView;
  try {
    const result = await api("copy", {id, displayed: d.packet});
    if (readerView !== view) return;
    try { await navigator.clipboard.writeText(result.text); if (readerView === view) notice("Full raw Markdown copied. Paste it into your selected coding tool; the app has not sent it."); }
    catch (_) { if (readerView !== view) return; $("raw-details").open = true; $("raw").focus(); $("raw").select(); notice("Clipboard access was denied or unavailable. The full raw Markdown is selected below; use your browser's Copy command. No copy success is claimed."); }
  } catch (error) {
    if (error.status === 409) {
      observeHandoff(id, error.current); d.expected = error.current;
      if (readerView !== view) return;
      if (id === currentId && selectedStage === stage && readerView === view) {
        if (typeof error.current === "string") { d.packet = error.current; d.packetDestination = ""; showPacket(error.current); $("raw-details").open = true; $("reader-caption").textContent = "Saved handoff changed — review this current file before another Copy. Prepare Again before Continue."; }
        else { $("reader-caption").textContent = "Handoff.md is now absent — the displayed snapshot and input remain in this tab only"; error.message = "Handoff.md is now absent. Your input is retained; use Prepare Again to save it. Nothing was copied."; }
      }
    }
    else if (readerView !== view) return;
    throw error;
  }
});
window.addEventListener("beforeunload", event => { if (dirty()) { event.preventDefault(); event.returnValue = ""; } });
$("destination").onchange = () => { remember(); updateHost(); if (currentId && stage && draft().packet) notice("Coding tool changed. Prepare Again to create a snapshot addressed to this tool."); };
$("continue").onclick = guard(async () => {
  remember(); const d = draft();
  if (!d.packet || d.packetDestination !== d.destination) throw new Error("Prepare Again for this coding tool before continuing.");
  $("continue").disabled = true;
  try { const result = await api("continue", {id: currentId, displayed: d.packet, destination: d.packetDestination}); notice(result.message); }
  catch (error) { if (error.status === 409) notice("The saved handoff changed. Use Copy to review the current saved text, or Prepare Again. Nothing was launched."); else throw error; }
  finally { updateHost(); }
});
$("help").onclick = () => { $("help-panel").hidden = false; };
$("install-app").onclick = guard(async () => {
  $("install-app").disabled = true;
  try { const result = await api("install", {hosts: [...document.querySelectorAll("#setup-hosts input:checked")].map(box => box.value)}); $("installation-result").textContent = `Installed Vibe ${result.version}. Open the Ora Vibe Coder launcher at ${result.launcher}. ${result.note}`; $("close-setup").hidden = false; notice("Installation finished. Open the launcher to choose your projects folder."); }
  finally { $("install-app").disabled = false; }
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
$("choose-home").onclick = $("change-home").onclick = guard(() => pickFolder("Choose your projects folder", selectHome));
$("folder-go").onclick = guard(() => browseFolders($("folder-path").value));
$("folder-up").onclick = guard(() => browseFolders(folderState.parent));
$("folder-select").onclick = guard(async () => { await folderChoice(folderState.path); $("folder-picker").hidden = true; });
$("folder-cancel").onclick = () => { $("folder-picker").hidden = true; notice("Folder selection cancelled. No project work started."); };
$("open-browse").onclick = guard(() => pickFolder("Choose an existing project", async path => { $("open-path").value = path; }));
$("file-cancel").onclick = () => { $("file-picker").hidden = true; };
$("file-up").onclick = guard(() => browseDocuments(fileDirectory.split("/").slice(0, -1).join("/") || "."));
window.addEventListener("focus", guard(async () => {
  if (!currentId || stopped) return;
  const view = readerView; await refreshProject();
  if (readerView !== view) return;
  if (stage && $("packet-tools").hidden) await readDocument(view?.role || $("document").value);
  else if (!stage) await material("Request", $("request"));
}));
$("stop").onclick = guard(async () => { if (dirty() && !confirm("There is unsaved input in this tab. Stop the server anyway? Text stays visible here, but reload or closing this tab will discard it.")) return; await api("stop", {}); stopped = true; notice("App stopped. Text remains available to select and copy in this tab. Saved project files were left in place."); });
guard(initialize)();
