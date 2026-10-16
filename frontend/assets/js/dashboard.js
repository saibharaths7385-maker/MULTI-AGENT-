const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const AGENTS = ["planner", "engineer", "tester", "reviewer"];
let currentProject = null;
let eventSource = null;
let activeTab = "files";
let project = null;
let agentStates = {};

async function api(path, options) {
  const response = await fetch(path, options);
  if (response.status === 401) {
    location.replace("/login");
    throw new Error("Your session has expired.");
  }
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed (${response.status}).`);
  }
  return response.json();
}

async function refreshList() {
  const projects = await api("/api/projects");
  $("#list").innerHTML = projects.map((item) => `
    <div class="pi ${item.id === currentProject ? "on" : ""}" data-project="${item.id}">
      ${esc(item.name)}
      <small><span class="chip ${item.status}">${esc(item.status.replace("_", " "))}</span>
      <span>${item.tokens} tok</span></small>
    </div>`).join("") || '<div class="muted">No projects yet</div>';
  document.querySelectorAll("[data-project]").forEach((element) => {
    element.addEventListener("click", () => openProject(element.dataset.project));
  });
}

async function initialize() {
  const config = await api("/api/config");
  $("#cfg").innerHTML = `${esc(config.model)}<br>sandbox: ${esc(config.sandbox)} · approval: ${config.approval ? "on" : "off"}`
    + (config.has_key ? "" : '<br><b class="error">No LLM_API_KEY set</b>');
  await refreshList();
  showNewProjectForm();
  setInterval(() => refreshList().catch(handleError), 4000);
}

function showNewProjectForm() {
  if (eventSource) eventSource.close();
  currentProject = null;
  $("#main").innerHTML = `<div class="card" style="max-width:720px">
    <h2>What should the agents build?</h2>
    <p class="muted">Describe a small Python project. Agents plan, code, test in a sandbox, fix failures and review it.</p>
    <input id="name" placeholder="Project name (optional)">
    <textarea id="idea" rows="5" placeholder="e.g. A CLI expense tracker with categories, monthly summaries and CSV export"></textarea>
    <input id="constraints" placeholder="Constraints (optional): stdlib only, Python 3.11…">
    <button class="primary" id="launch">Launch agents →</button>
  </div>`;
  $("#launch").addEventListener("click", createProject);
  refreshList().catch(handleError);
}

async function createProject() {
  const idea = $("#idea").value.trim();
  if (!idea) return;
  const created = await api("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      idea,
      name: $("#name").value,
      constraints: $("#constraints").value,
    }),
  });
  await openProject(created.id);
}

async function openProject(id) {
  if (eventSource) eventSource.close();
  currentProject = id;
  agentStates = {};
  activeTab = "files";
  $("#main").innerHTML = `<div id="head"></div><div id="banner"></div><div class="steps" id="steps"></div>
    <div class="grid">
      <div class="card"><b>Execution log</b><div id="log"></div></div>
      <div class="card"><div class="tabs" id="tabs"></div><div id="pane"></div></div>
    </div>`;
  await refreshProject();
  eventSource = new EventSource(`/api/projects/${id}/events`);
  eventSource.onmessage = (event) => {
    addEvent(JSON.parse(event.data));
    refreshProject().catch(handleError);
  };
  eventSource.addEventListener("end", () => {
    eventSource.close();
    refreshProject().catch(handleError);
  });
  eventSource.onerror = () => {
    api("/api/auth/status").then((status) => {
      if (!status.authenticated) location.replace("/login");
    }).catch(handleError);
  };
  await refreshList();
}

async function refreshProject() {
  if (!currentProject) return;
  project = await api(`/api/projects/${currentProject}`);
  const status = project.status;
  $("#head").innerHTML = `<div class="header-row">
    <div><h2>${esc(project.name)}</h2><span class="chip ${status}">${esc(status.replace("_", " "))}</span>
    <span class="muted">${project.tokens} tokens · ${project.fix_rounds} fix rounds</span></div>
    <div class="button-row"><a href="/api/projects/${currentProject}/download"><button>⬇ Download zip</button></a>
    ${["running", "awaiting_approval"].includes(status) ? '<button class="danger" id="stop">Stop</button>' : ""}
    <button class="danger" id="delete">Delete</button></div></div>`;
  $("#stop")?.addEventListener("click", () => projectAction("cancel"));
  $("#delete")?.addEventListener("click", deleteProject);
  $("#banner").innerHTML = status === "awaiting_approval"
    ? `<div class="banner"><div><b>Approval needed.</b> Review the plan, then let the engineer start.</div>
      <div class="button-row"><button class="primary" id="approve">Approve</button>
      <button class="danger" id="reject">Reject</button></div></div>` : "";
  $("#approve")?.addEventListener("click", () => projectAction("approve"));
  $("#reject")?.addEventListener("click", () => projectAction("reject"));
  renderSteps();
  renderTabs();
  await renderPane();
}

function renderSteps() {
  const element = $("#steps");
  if (element) element.innerHTML = AGENTS.map((agent) =>
    `<div class="st ${agentStates[agent] || ""}">${agent}</div>`).join("");
}

function renderTabs() {
  const element = $("#tabs");
  if (!element) return;
  element.innerHTML = ["files", "plan", "report"].map((tab) =>
    `<button class="${activeTab === tab ? "active" : ""}" data-tab="${tab}">${tab}</button>`).join("");
  element.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      activeTab = button.dataset.tab;
      refreshProject().catch(handleError);
    });
  });
}

async function renderPane() {
  const pane = $("#pane");
  if (!pane || !project) return;
  if (activeTab === "files") {
    pane.innerHTML = project.files.map((file) =>
      `<div class="file-item" data-file="${esc(file)}">📄 ${esc(file)}</div>`).join("")
      + '<pre id="file-content" hidden></pre>';
    pane.querySelectorAll("[data-file]").forEach((element) => {
      element.addEventListener("click", () => showFile(element.dataset.file));
    });
    return;
  }
  if (activeTab === "plan") {
    const plan = project.plan;
    pane.innerHTML = plan ? `<p>${esc(plan.summary)}</p><b>Tasks</b>
      <ul>${(plan.tasks || []).map((task) => `<li>${esc(task.title)} <span class="chip">${esc(task.owner)}</span></li>`).join("")}</ul>
      <b>Acceptance criteria</b><ul>${(plan.acceptance || []).map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
      ${(plan.uncertain || []).length ? `<b>⚠ Flagged as uncertain</b><ul>${plan.uncertain.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}`
      : '<span class="muted">Planner is working…</span>';
    return;
  }
  if (!project.files.includes("REPORT.md")) {
    pane.innerHTML = '<span class="muted">Report is generated when the run ends.</span>';
    return;
  }
  pane.innerHTML = '<pre id="file-content"></pre>';
  await showFile("REPORT.md");
}

async function showFile(path) {
  const response = await fetch(`/api/projects/${currentProject}/file?path=${encodeURIComponent(path)}`);
  if (response.status === 401) {
    location.replace("/login");
    return;
  }
  if (!response.ok) throw new Error(await response.text());
  const content = await response.text();
  const element = $("#file-content");
  element.hidden = false;
  element.textContent = content;
}

function addEvent(event) {
  if (AGENTS.includes(event.agent)) {
    if (event.kind === "start") agentStates[event.agent] = "running";
    if (event.kind === "done") agentStates[event.agent] = "done";
  }
  if (event.kind === "error") {
    for (const agent of AGENTS) {
      if (agentStates[agent] === "running") agentStates[agent] = "error";
    }
  }
  const data = event.data ? JSON.parse(event.data) : null;
  const time = new Date(event.ts * 1000).toLocaleTimeString();
  $("#log").insertAdjacentHTML("beforeend", `<div class="ev"><span class="time">${time}</span>
    <b>${esc(event.agent)}</b> ${esc(event.message)}
    ${data?.output ? `<pre>${esc(data.output)}</pre>` : ""}</div>`);
  $("#log").lastElementChild?.scrollIntoView({ block: "nearest" });
  renderSteps();
}

async function projectAction(action) {
  await api(`/api/projects/${currentProject}/${action}`, { method: "POST" });
  await refreshProject();
}

async function deleteProject() {
  if (!confirm("Delete this project?")) return;
  await api(`/api/projects/${currentProject}`, { method: "DELETE" });
  showNewProjectForm();
}

function handleError(error) {
  if (error.message !== "Your session has expired.") console.error(error);
}

$("#new-project").addEventListener("click", showNewProjectForm);
$("#logout").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  location.replace("/login");
});
initialize().catch(handleError);
