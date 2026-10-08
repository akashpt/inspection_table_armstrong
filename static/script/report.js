let bridge = null;
let bridgeReady = false;

function initBridge() {
  return new Promise((resolve) => {
    if (bridgeReady) {
      resolve(bridge);
      return;
    }

    if (typeof QWebChannel === "undefined" || typeof qt === "undefined") {
      resolve(null);
      return;
    }

    new QWebChannel(qt.webChannelTransport, (channel) => {
      bridge = channel.objects.bridge;
      bridgeReady = Boolean(bridge);
      resolve(bridge);
    });
  });
}

function callBridge(methodName, ...args) {
  return new Promise((resolve) => {
    if (!bridge || !bridge[methodName]) {
      resolve(null);
      return;
    }

    bridge[methodName](...args, resolve);
  });
}

async function loadReports() {
  const rows = document.getElementById("reportRows");
  const empty = document.getElementById("reportEmpty");
  rows.innerHTML = "";

  const b = await initBridge();
  if (!b || !b.job_options) {
    empty.style.display = "block";
    return;
  }

  const raw = await callBridge("job_options");
  const parsed = JSON.parse(raw || "[]");
  const jobs = (Array.isArray(parsed) ? parsed : [])
    .map((job) => (typeof job === "object" ? job.job_id || job.Job_ID || job.value : job))
    .map((job) => String(job || "").trim())
    .filter(Boolean);

  empty.style.display = jobs.length ? "none" : "block";

  Array.from(new Set(jobs)).forEach((job) => {
    const tr = document.createElement("tr");
    const jobCell = document.createElement("td");
    const statusCell = document.createElement("td");
    jobCell.textContent = job;
    statusCell.textContent = "Available";
    tr.appendChild(jobCell);
    tr.appendChild(statusCell);
    rows.appendChild(tr);
  });
}

function goTraining() {
  if (bridge && bridge.goTraining) bridge.goTraining();
}
function goHome() {
  if (bridge && bridge.goHome) bridge.goHome();
}
function openReport() {
  if (bridge && bridge.showReport) bridge.showReport();
}
function openController() {
  if (bridge && bridge.controller_page) bridge.controller_page();
}
function openSetting() {
  if (bridge && bridge.showSetting) bridge.showSetting();
}
function toggleReportDropdown() {

    const dropdown = document.getElementById("reportDropdown");

    if (!dropdown) {
        console.error("❌ reportDropdown not found");
        return;
    }

    if (dropdown.style.display === "none") {
        dropdown.style.display = "block";
    } else {
        dropdown.style.display = "none";
    }
}


window.addEventListener("load", loadReports);
