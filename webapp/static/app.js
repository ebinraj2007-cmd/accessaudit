const wizard = document.getElementById("wizard");
const mainView = document.getElementById("mainView");
const mainActions = document.getElementById("mainActions");
const wizardError = document.getElementById("wizardError");
const sampleDataBtn = document.getElementById("sampleDataBtn");

const queue = document.getElementById("queue");
const emptyState = document.getElementById("emptyState");
const checkBtn = document.getElementById("checkBtn");
const clearBtn = document.getElementById("clearBtn");
const logBtn = document.getElementById("logBtn");
const closeLog = document.getElementById("closeLog");
const logDrawer = document.getElementById("logDrawer");
const drawerBackdrop = document.getElementById("drawerBackdrop");
const logBody = document.getElementById("logBody");

const ISSUE_LABELS = {
  orphaned_access: "Orphaned Access",
  excessive_privilege: "Excessive Privilege",
  dormant_access: "Dormant Access",
};

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function showDashboard() {
  wizard.style.display = "none";
  mainView.style.display = "block";
  mainActions.style.display = "flex";
  refreshAll();
}

function showWizard() {
  wizard.style.display = "flex";
  mainView.style.display = "none";
  mainActions.style.display = "none";
}

// ---------- Wizard: drag & drop upload ----------

function setupDropzone(zoneId, fileInputId, kind) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(fileInputId);
  const statusEl = zone.querySelector(".dropzone-status");

  zone.addEventListener("click", () => input.click());

  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    if (e.dataTransfer.files.length) uploadFile(kind, e.dataTransfer.files[0], zone, statusEl);
  });

  input.addEventListener("change", () => {
    if (input.files.length) uploadFile(kind, input.files[0], zone, statusEl);
  });
}

async function uploadFile(kind, file, zone, statusEl) {
  zone.classList.remove("is-done", "is-error");
  statusEl.textContent = `Uploading ${file.name}…`;
  wizardError.textContent = "";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`/api/upload/${kind}`, { method: "POST", body: formData });
    const data = await res.json();

    if (!res.ok || data.error) {
      zone.classList.add("is-error");
      statusEl.textContent = "Upload failed";
      wizardError.textContent = data.error || "Something went wrong reading that file.";
      return;
    }

    zone.classList.add("is-done");
    statusEl.textContent = `✓ ${file.name} (${data.row_count} rows)`;

    if (data.ready_to_check) {
      showDashboard();
    }
  } catch (err) {
    zone.classList.add("is-error");
    statusEl.textContent = "Upload failed";
    wizardError.textContent = "Network error while uploading. Is the server running?";
  }
}

setupDropzone("dropEmployees", "fileEmployees", "employees");
setupDropzone("dropAccess", "fileAccess", "access");

sampleDataBtn.addEventListener("click", async () => {
  sampleDataBtn.disabled = true;
  sampleDataBtn.textContent = "Loading sample data…";
  try {
    await fetch("/api/use-sample-data", { method: "POST" });
    showDashboard();
  } finally {
    sampleDataBtn.disabled = false;
    sampleDataBtn.textContent = "Try it now with sample company data";
  }
});

// ---------- Dashboard ----------

function renderFindingCard(row, index) {
  const s = row.severity;
  const resolved = row.status !== "open";
  const card = document.createElement("div");
  card.className = "finding-card" + (resolved ? " is-resolved" : "");
  card.style.animationDelay = `${index * 35}ms`;
  card.dataset.id = row.id;

  const title = row.issue_type === "orphaned_access"
    ? `${row.employee_name} still has access after leaving`
    : ISSUE_LABELS[row.issue_type] || row.issue_type;

  card.innerHTML = `
    <div class="severity-rail s${s}"></div>
    <div class="finding-body">
      <div class="finding-top">
        <p class="finding-title">${escapeHtml(title)}</p>
        <span class="finding-meta">${escapeHtml(row.detected_at || "")}</span>
      </div>
      <p class="finding-sub">${escapeHtml(row.employee_email)} → ${escapeHtml(row.system)} (${escapeHtml(row.access_level)})</p>
      <div class="badge-row">
        <span class="badge badge-sev s${s}">S${s}</span>
        <span class="badge">${ISSUE_LABELS[row.issue_type] || row.issue_type}</span>
        <span class="badge badge-engine">${row.engine}</span>
        ${resolved ? `<span class="badge badge-status">${row.status.replace("_", " ")}</span>` : ""}
      </div>
      <p class="finding-reasoning">${escapeHtml(row.reasoning)}</p>
      <div class="action-row">
        ${resolved ? "" : `
          <button class="btn btn-danger btn-small" data-action="revoke">Revoke Access</button>
          <button class="btn btn-outline btn-small" data-action="reset">Reset Password</button>
          <button class="btn btn-ghost btn-small" data-action="dismiss">Dismiss</button>
        `}
      </div>
    </div>
  `;

  if (!resolved) {
    card.querySelector('[data-action="revoke"]').addEventListener("click", () => doAction(row.id, "revoke"));
    card.querySelector('[data-action="reset"]').addEventListener("click", () => doAction(row.id, "reset"));
    card.querySelector('[data-action="dismiss"]').addEventListener("click", () => doAction(row.id, "dismiss"));
  }

  return card;
}

async function doAction(findingId, kind) {
  const endpoint = kind === "revoke" ? "revoke" : kind === "reset" ? "reset-password" : "dismiss";
  await fetch(`/api/findings/${findingId}/${endpoint}`, { method: "POST" });
  await refreshAll();
}

async function loadFindings() {
  const res = await fetch("/api/findings");
  const rows = await res.json();

  queue.querySelectorAll(".finding-card").forEach((el) => el.remove());

  const openRows = rows.filter(r => r.status === "open");
  emptyState.style.display = (rows.length === 0 || openRows.length === 0) ? "block" : "none";
  if (rows.length === 0) {
    emptyState.querySelector("p").textContent = "No open findings.";
  }
  rows.forEach((row, i) => queue.appendChild(renderFindingCard(row, i)));
}

async function loadStats() {
  const res = await fetch("/api/stats");
  const data = await res.json();
  document.getElementById("statOpen").textContent = data.open_total;
  document.getElementById("statCritical").textContent = data.critical_open;
  document.getElementById("statOrphaned").textContent = data.by_issue_type.orphaned_access || 0;
  document.getElementById("statExcessive").textContent = data.by_issue_type.excessive_privilege || 0;
  document.getElementById("statDormant").textContent = data.by_issue_type.dormant_access || 0;
}

async function loadLog() {
  const res = await fetch("/api/action-log");
  const rows = await res.json();
  if (rows.length === 0) {
    logBody.innerHTML = `<p style="color: var(--text-faint); font-size: 13px;">No actions taken yet.</p>`;
    return;
  }
  logBody.innerHTML = rows.map(r => `
    <div class="log-entry">
      <strong>${escapeHtml(r.action.replace("_", " "))}</strong> — ${escapeHtml(r.user_email)}<br>
      ${escapeHtml(r.system)} · ${escapeHtml(r.performed_at)}<br>
      ${escapeHtml(r.note || "")}
    </div>
  `).join("");
}

async function refreshAll() {
  await Promise.all([loadFindings(), loadStats(), loadLog()]);
}

checkBtn.addEventListener("click", async () => {
  checkBtn.disabled = true;
  checkBtn.textContent = "Checking…";
  try {
    await fetch("/api/use-sample-data", { method: "POST" });
    await refreshAll();
  } finally {
    checkBtn.disabled = false;
    checkBtn.textContent = "Re-run Check";
  }
});

clearBtn.addEventListener("click", async () => {
  await fetch("/api/clear", { method: "POST" });
  showWizard();
  document.querySelectorAll(".dropzone").forEach(z => z.classList.remove("is-done", "is-error"));
  document.getElementById("statusEmployees").textContent = "Drop file or click to browse";
  document.getElementById("statusAccess").textContent = "Drop file or click to browse";
});

logBtn.addEventListener("click", async () => {
  await loadLog();
  logDrawer.classList.add("open");
  drawerBackdrop.classList.add("open");
});

function closeLogDrawer() {
  logDrawer.classList.remove("open");
  drawerBackdrop.classList.remove("open");
}
closeLog.addEventListener("click", closeLogDrawer);
drawerBackdrop.addEventListener("click", closeLogDrawer);

// ---------- Initial load: check whether data already exists ----------
(async function init() {
  const res = await fetch("/api/setup-status");
  const status = await res.json();
  if (status.has_data) {
    showDashboard();
  } else {
    showWizard();
  }
})();
