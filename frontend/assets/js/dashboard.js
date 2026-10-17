const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));

const AGENTS = ["planner", "engineer", "tester", "reviewer"];
const AGENT_NOTE = {
  planner: "Plans the work",
  engineer: "Writes the code",
  tester: "Runs the tests",
  reviewer: "Reviews the result",
};
const STARTERS = [
  ["Snake game", "A Snake game for the terminal with arrow-key style controls, a score, a saved high score, and pause/restart. Keep the game logic separate from the display so it can be tested."],
  ["Focus timer", "A focus timer with configurable work and break lengths, a session counter, and a daily log saved to a JSON file."],
  ["Expense tracker", "A personal expense tracker with categories, monthly summaries, search, and CSV export."],
];
const ACTIVE = ["queued", "running", "awaiting_approval"];

let currentProject = null;
let eventSource = null;
let activeTab = "files";
let project = null;
let agentStates = {};
let hasApiKey = false;
let listTimer = null;

async function api(path, options) {
  const response = await fetch(path, options);
  if (response.status === 401) {
    location.replace("/login");
    throw new Error("session-expired");
  }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch (_) { /* keep default */ }
    throw new Error(message);
  }
  return response.json();
}

const statusLabel = (status) => status.replace("_", " ");
const closeMenu = () => document.body.classList.remove("menu-open");

/* ---------- sidebar ---------- */
async function refreshList() {
  const projects = await api("/api/projects");
  $("#list").innerHTML = projects.map((item) => `
    <button class="pitem ${item.id === currentProject ? "on" : ""}" data-project="${item.id}">
      <span class="pname">${esc(item.name)}</span>
      <span class="pmeta"><span class="dot ${item.status}"></span>${esc(statusLabel(item.status))}<span>·</span>${item.tokens} tokens</span>
    </button>`).join("") || '<p class="side-empty">Nothing here yet. Start your first project.</p>';
  document.querySelectorAll("[data-project]").forEach((element) => {
    element.addEventListener("click", () => { closeMenu(); openProject(element.dataset.project); });
  });
  const recent = $("#recent");
  if (recent) renderRecent(projects);
  return projects;
}

function renderRecent(projects) {
  const box = $("#recent");
  if (!projects.length) { box.innerHTML = ""; return; }
  box.innerHTML = `<h2 class="section-title">Your projects</h2><div class="recent">${projects.slice(0, 6).map((item) => `
    <button class="rcard" data-project="${item.id}"><b>${esc(item.name)}</b>
      <span class="pill ${item.status}">${esc(statusLabel(item.status))}</span></button>`).join("")}</div>`;
  box.querySelectorAll("[data-project]").forEach((element) => {
    element.addEventListener("click", () => openProject(element.dataset.project));
  });
}

/* ---------- home / composer ---------- */
function showNewProjectForm() {
  if (eventSource) eventSource.close();
  currentProject = null;
  project = null;
  closeMenu();
  $("#main").innerHTML = `
    <h1 class="page-title">What should the agents build?</h1>
    <p class="page-sub">Describe a small Python project. Four agents plan it, write it, test it in a sandbox, fix failures and review the result.</p>
    <div id="app-notice" class="notice" role="status" hidden></div>
    <section class="composer">
      <div class="field">
        <label for="idea" style="display:block;margin-bottom:6px;font-weight:600;font-size:14px">Your idea</label>
        <textarea class="input" id="idea" placeholder="A habit tracker with daily check-ins, streaks and a weekly summary printed in the terminal…"></textarea>
      </div>
      <div class="row2">
        <input class="input" id="name" placeholder="Project name (optional)" aria-label="Project name" maxlength="120">
        <input class="input" id="constraints" placeholder="Constraints, e.g. Python 3.12, standard library only" aria-label="Constraints" maxlength="1000">
      </div>
      <div class="composer-foot">
        <div class="mini-track" aria-label="Agent order">Planner<i></i>Engineer<i></i>Tester<i></i>Reviewer</div>
        <button class="btn btn-primary" id="launch">Build my project</button>
      </div>
      <div class="starters"><span>Try one:</span>
        ${STARTERS.map(([title], index) => `<button class="chipbtn" data-starter="${index}">${esc(title)}</button>`).join("")}
      </div>
    </section>
    <div id="recent"></div>`;
  $("#launch").addEventListener("click", createProject);
  document.querySelectorAll("[data-starter]").forEach((button) => {
    button.addEventListener("click", () => {
      const [title, description] = STARTERS[Number(button.dataset.starter)];
      $("#idea").value = description;
      if (!$("#name").value.trim()) $("#name").value = title;
      $("#idea").focus();
    });
  });
  showKeyNotice();
  refreshList().catch(handleError);
}

function showKeyNotice() {
  const notice = $("#app-notice");
  if (notice && !hasApiKey) {
    notice.textContent = "The model key isn't set on this server yet, so agents can't start. Add LLM_API_KEY in the environment settings and redeploy.";
    notice.hidden = false;
  }
}

async function createProject() {
  const idea = $("#idea").value.trim();
  if (!idea) {
    $("#idea").setCustomValidity("Tell the agents what to build.");
    $("#idea").reportValidity();
    $("#idea").addEventListener("input", () => $("#idea").setCustomValidity(""), { once: true });
    return;
  }
  if (!hasApiKey) { showKeyNotice(); return; }
  const button = $("#launch");
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span> Starting';
  try {
    const created = await api("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idea, name: $("#name").value, constraints: $("#constraints").value }),
    });
    await openProject(created.id);
  } catch (error) {
    button.disabled = false;
    button.textContent = "Build my project";
    const notice = $("#app-notice");
    notice.textContent = error.message;
    notice.hidden = false;
  }
}

/* ---------- project view ---------- */
async function openProject(id) {
  if (eventSource) eventSource.close();
  currentProject = id;
  agentStates = {};
  activeTab = "files";
  $("#main").innerHTML = `
    <div id="head"></div><div id="banner"></div><div class="track" id="track"></div>
    <div class="cols">
      <section class="panel"><div class="panel-head">Activity</div>
        <div class="log" id="log"><p class="log-empty">Waiting for the first agent…</p></div></section>
      <section class="panel"><div class="tabs" id="tabs"></div><div class="pane" id="pane"></div></section>
    </div>`;
  try {
    await refreshProject();
  } catch (error) {
    handleError(error);
    return;
  }
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
  refreshList().catch(handleError);
}

async function refreshProject() {
  if (!currentProject) return;
  const id = currentProject;
  const data = await api(`/api/projects/${id}`);
  if (id !== currentProject) return; // switched away while loading
  project = data;
  const status = project.status;
  $("#head").innerHTML = `<div class="phead">
    <div><h2>${esc(project.name)}</h2>
      <div class="pmeta-line"><span class="pill ${status}">${esc(statusLabel(status))}</span>
      <span>${project.tokens} tokens</span><span>${project.fix_rounds} fix ${project.fix_rounds === 1 ? "round" : "rounds"}</span></div></div>
    <div class="actions">
      <a class="btn btn-sm" href="/api/projects/${id}/download">Download zip</a>
      ${ACTIVE.includes(status) ? '<button class="btn btn-sm btn-danger" id="stop">Stop</button>' : ""}
      <button class="btn btn-sm btn-danger" id="delete">Delete</button>
    </div></div>`;
  $("#stop")?.addEventListener("click", () => projectAction("cancel"));
  $("#delete")?.addEventListener("click", deleteProject);
  $("#banner").innerHTML = status === "awaiting_approval"
    ? `<div class="banner"><div><b>Your approval is needed.</b> Read the plan, then let the engineer start.</div>
       <div class="actions"><button class="btn btn-sm btn-primary" id="approve">Approve plan</button>
       <button class="btn btn-sm btn-danger" id="reject">Reject</button></div></div>` : "";
  $("#approve")?.addEventListener("click", () => projectAction("approve"));
  $("#reject")?.addEventListener("click", () => projectAction("reject"));
  renderTrack();
  renderTabs();
  await renderPane();
}

function renderTrack() {
  const element = $("#track");
  if (!element) return;
  const finished = project && ["passed", "failed"].includes(project.status);
  element.innerHTML = AGENTS.map((agent, index) => {
    let state = agentStates[agent] || "";
    if (!state && finished) state = "done";
    const mark = state === "done" ? "✓" : state === "error" ? "!" : index + 1;
    const note = state === "running" ? "Working now" : state === "done" ? "Done" : state === "error" ? "Failed" : AGENT_NOTE[agent];
    return `<div class="stage ${state}"><span class="node">${mark}</span><b>${agent}</b><small>${note}</small></div>`;
  }).join("");
}

function renderTabs() {
  const element = $("#tabs");
  if (!element) return;
  element.innerHTML = ["files", "plan", "report"].map((tab) =>
    `<button class="${activeTab === tab ? "active" : ""}" data-tab="${tab}">${tab}</button>`).join("");
  element.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      activeTab = button.dataset.tab;
      renderTabs();
      renderPane().catch(handleError);
    });
  });
}

async function renderPane() {
  const pane = $("#pane");
  if (!pane || !project) return;
  if (activeTab === "files") {
    if (!project.files.length) {
      pane.innerHTML = '<p class="muted">Files appear here as the engineer writes them.</p>';
      return;
    }
    const open = pane.dataset.open;
    pane.innerHTML = project.files.map((file) =>
      `<button class="fileitem ${file === open ? "on" : ""}" data-file="${esc(file)}">${esc(file)}</button>`).join("")
      + '<pre class="code" id="file-content" hidden></pre>';
    pane.querySelectorAll("[data-file]").forEach((element) => {
      element.addEventListener("click", () => {
        pane.dataset.open = element.dataset.file;
        pane.querySelectorAll(".fileitem").forEach((item) => item.classList.toggle("on", item === element));
        showFile(element.dataset.file).catch(handleError);
      });
    });
    if (open && project.files.includes(open)) await showFile(open);
    return;
  }
  if (activeTab === "plan") {
    const plan = project.plan;
    pane.innerHTML = plan ? `<p>${esc(plan.summary)}</p>
      <h3>Tasks</h3><ul>${(plan.tasks || []).map((task) => `<li>${esc(task.title)}<span class="tag">${esc(task.owner)}</span></li>`).join("")}</ul>
      <h3>Acceptance criteria</h3><ul>${(plan.acceptance || []).map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
      ${(plan.uncertain || []).length ? `<h3>The planner wasn't sure about</h3><ul>${plan.uncertain.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}`
      : '<p class="muted">The planner is still working.</p>';
    return;
  }
  if (!project.files.includes("REPORT.md")) {
    pane.innerHTML = '<p class="muted">The report appears when the run ends.</p>';
    return;
  }
  pane.innerHTML = '<pre class="code" id="file-content"></pre>';
  await showFile("REPORT.md");
}

async function showFile(path) {
  const id = currentProject;
  const response = await fetch(`/api/projects/${id}/file?path=${encodeURIComponent(path)}`);
  if (response.status === 401) { location.replace("/login"); return; }
  if (!response.ok) throw new Error("Couldn't open that file.");
  const content = await response.text();
  const element = $("#file-content");
  if (!element || id !== currentProject) return;
  element.hidden = false;
  element.textContent = content;
}

function addEvent(event) {
  if (AGENTS.includes(event.agent)) {
    if (event.kind === "start") agentStates[event.agent] = "running";
    if (event.kind === "done") agentStates[event.agent] = "done";
  }
  if (event.kind === "error") {
    for (const agent of AGENTS) if (agentStates[agent] === "running") agentStates[agent] = "error";
  }
  const log = $("#log");
  if (!log) return;
  log.querySelector(".log-empty")?.remove();
  const data = event.data ? JSON.parse(event.data) : null;
  const time = new Date(event.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  log.insertAdjacentHTML("beforeend", `<div class="ev ${event.kind === "error" ? "error" : ""}">
    <span class="t">${time}</span><span class="who">${esc(event.agent)}</span>${esc(event.message)}
    ${data?.output ? `<pre>${esc(data.output)}</pre>` : ""}</div>`);
  log.lastElementChild?.scrollIntoView({ block: "nearest" });
  renderTrack();
}

async function projectAction(action) {
  try {
    await api(`/api/projects/${currentProject}/${action}`, { method: "POST" });
    await refreshProject();
  } catch (error) {
    handleError(error);
  }
}

async function deleteProject() {
  if (!confirm("Delete this project and its files? This can't be undone.")) return;
  try {
    await api(`/api/projects/${currentProject}`, { method: "DELETE" });
    showNewProjectForm();
  } catch (error) {
    handleError(error);
  }
}

function handleError(error) {
  if (error.message === "session-expired") return;
  console.error(error);
  const notice = $("#app-notice");
  if (notice) {
    notice.textContent = error.message;
    notice.hidden = false;
    return;
  }
  $("#main").insertAdjacentHTML("afterbegin",
    `<div class="notice" role="alert">${esc(error.message)}</div>`);
}

/* ---------- start ---------- */
async function initialize() {
  try {
    const [status, config] = await Promise.all([api("/api/auth/status"), api("/api/config")]);
    $("#me-name").textContent = status.username;
    $("#me-email").textContent = status.email || "";
    $("#avatar").textContent = (status.username || "?").charAt(0).toUpperCase();
    hasApiKey = config.has_key;
  } catch (error) {
    if (error.message === "session-expired") return;
    $("#main").innerHTML = `<section class="offline"><h1>Can't reach the workspace</h1>
      <p class="muted" style="margin-bottom:20px">Synapse couldn't load. If the server just woke up, wait a few seconds and try again.</p>
      <button class="btn btn-primary" onclick="location.reload()">Try again</button></section>`;
    return;
  }
  showNewProjectForm();
  clearInterval(listTimer);
  listTimer = setInterval(() => refreshList().catch(() => {}), 5000);
}

$("#new-project").addEventListener("click", showNewProjectForm);
$("#menu").addEventListener("click", () => document.body.classList.toggle("menu-open"));
document.addEventListener("click", (event) => {
  if (document.body.classList.contains("menu-open") && !event.target.closest("#side, #menu")) closeMenu();
});
$("#logout").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  location.replace("/login");
});
initialize();
