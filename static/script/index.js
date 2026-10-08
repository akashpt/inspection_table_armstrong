let stream = null;
let lengthTimer = null;
let lengthLoading = false;

async function legacyBrowserStartCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: false,
    });
    document.getElementById("video").srcObject = stream;
    document.getElementById("noSignal").classList.add("hidden");
    document.getElementById("camWrap").classList.add("active");
    setCams(true);
    toast("Camera started");
  } catch {
    toast("⚠️ Camera access denied");
  }
}

function legacyStopCamera() {
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  document.getElementById("video").srcObject = null;
  document.getElementById("noSignal").classList.remove("hidden");
  document.getElementById("camWrap").classList.remove("active");
  setCams(false);
  toast("Camera stopped");
}

function legacySetCams(on) {
  ["c1", "c2", "c3", "c4"].forEach((id, i) => {
    document.getElementById(id).className = "cam-pill" + (on ? " active" : "");
    document.getElementById("s" + (i + 1)).textContent = on
      ? "Running"
      : "Idle";
  });
}

function resetAll() {
  stopCamera();
  setLengthDisplay(null);
  toast("System reset");
}

function openJobId() {
  loadIndexConfigOptions();
  document.getElementById("jobModal").classList.add("open");
}

const jobDetailsStorageKey = "jobDetails";
const jobDetailFields = [
  ["jobBatchNumber", "batch_number"],
  ["jobShadeNumber", "shade_number"],
  ["jobFrn", "frn"],
  ["jobDcNumber", "dc_number"],
  ["jobColor", "color"],
  ["jobWeight", "weight"],
];

function readStoredJobDetails() {
  try {
    return JSON.parse(localStorage.getItem(jobDetailsStorageKey) || "{}");
  } catch {
    return {};
  }
}

function setJobDetailsReadonly(readonly) {
  jobDetailFields.forEach(([id]) => {
    const input = document.getElementById(id);
    if (input) {
      input.readOnly = readonly;
    }
  });
}

function applyJobDetails(details = {}) {
  jobDetailFields.forEach(([id, key]) => {
    const input = document.getElementById(id);
    if (input) {
      input.value = String(details[key] || "");
    }
  });
  setJobDetailsReadonly(Boolean(details.locked));
}

function readJobDetails() {
  return Object.fromEntries(
    jobDetailFields.map(([id, key]) => {
      const input = document.getElementById(id);
      return [key, input ? input.value.trim() : ""];
    })
  );
}

function openJobDetailsModal() {
  applyJobDetails(readStoredJobDetails());
  document.getElementById("jobDetailsModal").classList.add("open");
}

function saveJobDetails() {
  const details = {
    ...readJobDetails(),
    locked: true,
  };

  try {
    localStorage.setItem(jobDetailsStorageKey, JSON.stringify(details));
  } catch (error) {
    console.error("Job details cache failed:", error);
  }

  applyJobDetails(details);
  toast("Job details saved");
}

function resetJobDetails() {
  try {
    localStorage.removeItem(jobDetailsStorageKey);
  } catch (error) {
    console.error("Job details reset failed:", error);
  }

  applyJobDetails({});
  toast("Job details cleared");
}

async function openNewRoll() {
  const selectedJob = getCachedJobId();
  const details = getCachedRollDetails(selectedJob);
  await loadHomeOperatorNames(details.operator_name);
  applyRollDetails(getCachedRollDetails(getCachedJobId()), true);
  const operatorName = details.operator_name || "";
  const machineNumber = details.machine_number || "";

  bridge.createNewRoll(
    String(operatorName),
    String(machineNumber),
    String(selectedJob),
    function (response) {
      try {
        const result =
          typeof response === "string"
            ? JSON.parse(response)
            : response;

        if (!result.ok) {
          alert(result.message || "Unable to create new roll");
          return;
        }

        console.log("✅ New roll created:", result.roll_id);

        document
          .getElementById("rollModal")
          .classList.add("open");

      } catch (error) {
        console.error("❌ createNewRoll response error:", error);
        alert("Unable to create new roll");
      }
    }
  );
}
function closeModal(id) {
  document.getElementById(id).classList.remove("open");
}

document.querySelectorAll(".overlay").forEach((o) => {
  o.addEventListener("click", (e) => {
    if (e.target === o) o.classList.remove("open");
  });
});

function callBridge(methodName, ...args) {
  return new Promise((resolve) => {
    if (!bridge || !bridge[methodName]) {
      resolve(null);
      return;
    }

    bridge[methodName](...args, resolve);
  });
}

function setHomeJobId(jobId) {
  const value = String(jobId || "").trim();
  if (!value) return;

  const jobEl = document.getElementById("fJob");
  if (jobEl) {
    jobEl.textContent = value;
  }

  try {
    localStorage.setItem("selectedJobId", value);
  } catch (error) {
    console.error("Selected job cache failed:", error);
  }
}

function getCachedJobId() {
  try {
    return localStorage.getItem("selectedJobId") || "";
  } catch {
    return "";
  }
}

function getCachedRollDetails(jobId = "") {
  try {
    const details = JSON.parse(localStorage.getItem("rollDetails") || "{}");
    const cachedJob = String(details.job_id || "").trim();
    const requestedJob = String(jobId || "").trim();
    return requestedJob && cachedJob && cachedJob !== requestedJob ? {} : details;
  } catch {
    return {};
  }
}

function getCachedOperatorNames(jobId = "") {
  try {
    const data = JSON.parse(localStorage.getItem("operatorNames") || "{}");
    const key = String(jobId || "").trim() || "_default";
    return Array.isArray(data[key]) ? data[key] : [];
  } catch {
    return [];
  }
}

function rememberOperatorNames(names, jobId = "") {
  try {
    const data = JSON.parse(localStorage.getItem("operatorNames") || "{}");
    const key = String(jobId || "").trim() || "_default";
    data[key] = Array.from(new Set((names || []).map((name) => String(name || "").trim()).filter(Boolean)));
    localStorage.setItem("operatorNames", JSON.stringify(data));
  } catch (error) {
    console.error("Operator names cache failed:", error);
  }
}

function setHomeOperatorNameOptions(names = [], selectedName = "") {
  const selected = String(selectedName || "").trim();
  const values = Array.from(new Set((names || []).map((name) => String(name || "").trim()).filter(Boolean)));

  ["homeOperatorNameSelect", "nOperatorName"].forEach((id) => {
    const select = document.getElementById(id);
    if (!select) return;

    select.innerHTML = '<option value="">-- Select operator --</option>';
    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });
    select.value = values.includes(selected) ? selected : "";
  });
}

async function loadHomeOperatorNames(selectedName = "") {
  const selectedJob = getCachedJobId();
  let names = getCachedOperatorNames(selectedJob);

  if (bridgeReady && bridge.listOperatorNames) {
    try {
      const raw = await callBridge("listOperatorNames");
      const data = JSON.parse(raw || "{}");
      if (data.ok && Array.isArray(data.operators)) {
        names = data.operators;
        rememberOperatorNames(names, selectedJob);
      }
    } catch (error) {
      console.error("Operator list load failed:", error);
    }
  }

  setHomeOperatorNameOptions(names, selectedName);
  return names;
}

function rememberRollDetails(details, jobId = "") {
  const existing = getCachedRollDetails(jobId);
  try {
    localStorage.setItem("rollDetails", JSON.stringify({
      ...existing,
      ...Object.fromEntries(
        Object.entries(details).filter(([, value]) => value !== undefined)
      ),
      job_id: String(jobId || "").trim(),
    }));
  } catch (error) {
    console.error("Roll cache failed:", error);
  }
}

function readRollDetails() {
  return {
    operator_name: document.getElementById("nOperatorName").value.trim(),
    roll_id: document.getElementById("nRollNumber").value.trim(),
    roll_id_source: "manual",
  };
}

function setRollDisplay(rollId) {
  const rollEl = document.getElementById("fRoll");
  if (rollEl) {
    rollEl.textContent = String(rollId || "").trim() || "-";
  }
}

function applyRollDetails(details = {}, includeForm = false) {
  const rollId = String(details.roll_id || "").trim();
  const shift = String(details.shift || "").trim();
  const operatorName = String(details.operator_name || "").trim();
  const fabricType = String(details.fabric_type || "").trim();

  if (includeForm) {
    const operatorSelect = document.getElementById("nOperatorName");
    if (operatorSelect) {
      operatorSelect.value = operatorName;
    }
    const rollNumberInput = document.getElementById("nRollNumber");
    if (rollNumberInput) {
      rollNumberInput.value = details.roll_id_source === "manual" ? rollId : "";
    }
  }

  if (details.roll_id_source === "manual") {
    setRollDisplay(rollId);
  }
  if (shift) {
    document.getElementById("fShift").textContent = shift;
  }
}

async function selectedJobFromBridge() {
  if (!bridgeReady || !bridge.selected_config) {
    return "";
  }

  try {
    const raw = await callBridge("selected_config");
    const data = JSON.parse(raw || "{}");
    return String(data.selected || "").trim();
  } catch (error) {
    console.error("Selected configuration read failed:", error);
    return "";
  }
}

async function loadIndexConfigOptions() {
  const select = document.getElementById("selJobId");
  if (!select) return;

  const current = select.value || getCachedJobId();
  select.innerHTML = '<option value="">-- Select configuration --</option>';

  if (!bridgeReady || (!bridge.config_options && !bridge.job_options)) {
    setHomeJobId(current);
    return;
  }

  try {
    const raw = await callBridge(bridge.config_options ? "config_options" : "job_options");
    const parsed = JSON.parse(raw || "[]");
    const values = (Array.isArray(parsed) ? parsed : [])
      .map((item) => (typeof item === "object" ? item.job_id || item.value : item))
      .map((value) => String(value || "").trim())
      .filter(Boolean);

    Array.from(new Set(values)).forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });

    const selectedRaw = bridge.selected_config ? await callBridge("selected_config") : "";
    const selectedData = selectedRaw ? JSON.parse(selectedRaw || "{}") : {};
    const selected = selectedData.selected || current;

    if (selected && Array.from(select.options).some((option) => option.value === selected)) {
      select.value = selected;
      setHomeJobId(selected);
    }
  } catch (error) {
    console.error("Job configuration load failed:", error);
    setHomeJobId(current);
  }
}

async function saveJob() {
  const id = document.getElementById("selJobId").value;
  if (!id) {
    toast("Select a configuration first");
    return;
  }

  if (bridgeReady && bridge.save_selected_config) {
    const raw = await callBridge("save_selected_config", id, "{}");
    const data = JSON.parse(raw || "{}");
    if (!data.ok) {
      toast(data.message || "Configuration save failed");
      return;
    }
  }

  setHomeJobId(id);
  closeModal("jobModal");
  toast("Configuration saved: " + id);
}

async function saveRoll() {
  const details = readRollDetails();
  if (!details.operator_name) {
    toast("Enter Operator Name");
    return;
  }

  applyRollDetails(details);
  const selectedJob = getCachedJobId() || (await selectedJobFromBridge());

  rememberRollDetails(details, selectedJob);
  await loadHomeOperatorNames(details.operator_name);

  if (bridgeReady && bridge.saveOperatorName) {
    try {
      const operatorRaw = await callBridge("saveOperatorName", details.operator_name);
      const operatorData = JSON.parse(operatorRaw || "{}");
      if (!operatorData.ok) {
        toast(operatorData.message || "Operator save failed");
        return;
      }
      if (Array.isArray(operatorData.operators)) {
        rememberOperatorNames(operatorData.operators, selectedJob);
        setHomeOperatorNameOptions(operatorData.operators, details.operator_name);
      }
    } catch (error) {
      console.error("Operator save failed:", error);
      toast("Operator save failed");
      return;
    }
  }

  if (selectedJob && bridgeReady && bridge.save_selected_config) {
    try {
      const raw = await callBridge("save_selected_config", selectedJob, JSON.stringify(details));
      const data = JSON.parse(raw || "{}");
      if (!data.ok) {
        toast(data.message || "Roll save failed");
        return;
      }
      setHomeJobId(selectedJob);
    } catch (error) {
      console.error("Roll save failed:", error);
      toast("Roll save failed");
      return;
    }
  }

  closeModal("rollModal");
  toast("Operator " + details.operator_name + " saved");
}

let _t;
function toast(msg) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(_t);
  _t = setTimeout(() => el.classList.remove("show"), 2000);
}

function closeDefectModal() {
  const overlay = document.getElementById("defectOverlay");
  if (overlay) {
    overlay.classList.remove("open");
    overlay.setAttribute("aria-hidden", "true");
  }
}

function setLengthDisplay(lengthMm) {
  const element = document.getElementById("fLength");
  if (!element) return;

  if (lengthMm === null || lengthMm === undefined || String(lengthMm).trim() === "") {
    element.textContent = "-- m";
    return;
  }

  const value = Number(lengthMm);
  if (!Number.isFinite(value)) {
    element.textContent = "-- m";
    return;
  }

  element.textContent = (value / 1000).toFixed(2) + " m";
}

async function loadCurrentLength() {
  if (lengthLoading || !bridgeReady || !bridge.currentLength) {
    return;
  }

  lengthLoading = true;
  try {
    const raw = await callBridge("currentLength");
    const data = JSON.parse(raw || "{}");
    if (data.ok) {
      setLengthDisplay(data.length_mm);
    }
  } catch (error) {
    console.error("Length load failed:", error);
  } finally {
    lengthLoading = false;
  }
}

function startLengthPolling() {
  if (lengthTimer) {
    clearInterval(lengthTimer);
  }

  loadCurrentLength();
  lengthTimer = setInterval(loadCurrentLength, 1000);
}

function resetFromDefectModal() {
  closeDefectModal();
  bridge.resetSystem()
  resetAll();
}

function showDefectModal(payload) {
  const status = String(payload.status || "").trim().toUpperCase();
  if (status !== "DEFECT" && status !== "BAD") return;

  const overlay = document.getElementById("defectOverlay");
  const title = document.getElementById("defectModalTitle");
  const image = document.getElementById("defectModalImage");
  const imageWrap = document.querySelector(".defect-image-wrap");
  if (!overlay || !title || !image || !imageWrap) return;

  title.textContent = payload.code
    ? `Defect Image - ${payload.code}`
    : "Defect Image";

  if (payload.image_data) {
    image.src = payload.image_data;
    imageWrap.classList.remove("empty");
  } else {
    image.removeAttribute("src");
    imageWrap.classList.add("empty");
  }

  overlay.classList.add("open");
  overlay.setAttribute("aria-hidden", "false");
}

let bridge = null;
let bridgeReady = false;

function initBridge() {
  if (typeof QWebChannel === "undefined" || typeof qt === "undefined") {
    return;
  }

  new QWebChannel(qt.webChannelTransport, function (channel) {
    bridge = channel.objects.bridge;
    bridgeReady = Boolean(bridge);

    if (!bridgeReady) {
      return;
    }

    bridge.frame_signal.connect(function (jpg) {
      if (!jpg) {
        clearCameraFeed();
        return;
      }

      document.getElementById("video").style.display = "none";
      document.getElementById("cameraFeed").style.display = "block";
      document.getElementById("cameraFeed").src =
        "data:image/jpeg;base64," + jpg;
      setCameraUi(true, "Running");
    });

    if (bridge.camera_status_signal) {
      bridge.camera_status_signal.connect(function (ok, message) {
        setCameraUi(ok, ok ? "Running" : "Idle");
        toast(message || (ok ? "Camera started" : "Camera stopped"));
      });
    }

    if (bridge.defect_signal) {
      bridge.defect_signal.connect(function (raw) {
        try {
          showDefectModal(JSON.parse(raw || "{}"));
        } catch (error) {
          console.error("Defect signal parse failed:", error);
        }
      });
    }

    loadIndexConfigOptions();
    loadSelectedRollDetails();
    loadCurrentShiftDisplay();
    startLengthPolling();
  });
}

async function loadSelectedRollDetails() {
  const selectedJob = getCachedJobId() || (await selectedJobFromBridge());
  if (!selectedJob || !bridgeReady || !bridge.get_config) {
    applyRollDetails(getCachedRollDetails(selectedJob));
    await loadHomeOperatorNames(getCachedRollDetails(selectedJob).operator_name);
    return;
  }

  try {
    const raw = await callBridge("get_config", selectedJob);
    const data = JSON.parse(raw || "{}");
    const settings = data.ok && data.config ? data.config.settings || {} : {};
    const details = { ...getCachedRollDetails(selectedJob), ...settings };
    applyRollDetails(details);
    await loadHomeOperatorNames(details.operator_name);
    rememberRollDetails(details, selectedJob);
  } catch (error) {
    console.error("Roll details load failed:", error);
    applyRollDetails(getCachedRollDetails(selectedJob));
    await loadHomeOperatorNames(getCachedRollDetails(selectedJob).operator_name);
  }
}

async function loadCurrentShiftDisplay() {
  if (!bridgeReady || !bridge.currentShift) {
    return;
  }

  try {
    const raw = await callBridge("currentShift");
    const data = JSON.parse(raw || "{}");
    const shift = data.shift || {};
    const display = String(shift.display || shift.shift || "").trim();
    if (display) {
      document.getElementById("fShift").textContent = display;
    }
  } catch (error) {
    console.error("Current shift display failed:", error);
  }
}

async function selectOperatorName() {
  const select = document.getElementById("homeOperatorNameSelect");
  const operatorName = select ? select.value.trim() : "";
  const selectedJob = getCachedJobId() || (await selectedJobFromBridge());
  const details = {
    ...getCachedRollDetails(selectedJob),
    operator_name: operatorName,
  };

  rememberRollDetails(details, selectedJob);

  if (selectedJob && bridgeReady && bridge.save_selected_config) {
    try {
      const raw = await callBridge("save_selected_config", selectedJob, JSON.stringify({
        operator_name: operatorName,
      }));
      const data = JSON.parse(raw || "{}");
      if (!data.ok) {
        toast(data.message || "Operator save failed");
        return;
      }
    } catch (error) {
      console.error("Operator save failed:", error);
      toast("Operator save failed");
      return;
    }
  }

  toast(operatorName ? "Operator selected: " + operatorName : "Operator selection cleared");
}

async function canStartWithPlc() {
  if (!bridgeReady || !bridge.plcStatus) {
    toast("PLC status is not available");
    return false;
  }

  try {
    const raw = await callBridge("plcStatus");
    const data = JSON.parse(raw || "{}");
    if (!data.connected) {
      toast(data.message || "PLC not connected");
      setCameraUi(false, "Idle");
      return false;
    }
    return true;
  } catch (error) {
    console.error("PLC status check failed:", error);
    toast("PLC not connected");
    setCameraUi(false, "Idle");
    return false;
  }
}

async function startCamera() {
  if (bridgeReady && bridge.startCamera) {
    setCams(false, "Checking PLC");
    if (!(await canStartWithPlc())) {
      return;
    }

    setHomeControlState(true);
    setCams(false, "Connecting");
    // bridge.startCamera();
    bridge.startDetection()
    return;
  }

  startBrowserCamera();
}

async function startBrowserCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: false,
    });
    document.getElementById("cameraFeed").style.display = "none";
    document.getElementById("video").style.display = "block";
    document.getElementById("video").srcObject = stream;
    setCameraUi(true, "Running");
    toast("Camera started");
  } catch (error) {
    setCameraUi(false, "Idle");
    toast("Camera access denied");
    console.error("Camera start failed:", error);
  }
}

function stopCamera() {
  if (bridgeReady && bridge.stopCamera) {
    bridge.stopCamera();
    clearCameraFeed();
    return;
  }

  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  document.getElementById("video").srcObject = null;
  clearCameraFeed();
  toast("Camera stopped");
}

function clearCameraFeed() {
  document.getElementById("cameraFeed").removeAttribute("src");
  document.getElementById("video").style.display = "none";
  document.getElementById("cameraFeed").style.display = "block";
  setCameraUi(false, "Idle");
}

function setCameraUi(on, label) {
  document.getElementById("noSignal").classList.toggle("hidden", on);
  document.getElementById("camWrap").classList.toggle("active", on);
  setHomeControlState(on);
  setCams(on, label);
}

function setHomeControlState(running) {
  const newRollButton = document.getElementById("btnNewRoll");
  const startButton = document.getElementById("btnStartCamera");
  const stopButton = document.getElementById("btnStopCamera");

  if (newRollButton) {
    newRollButton.disabled = running;
  }
  if (startButton) {
    startButton.disabled = running;
  }
  if (stopButton) {
    stopButton.disabled = !running;
  }
}

function setCams(on, label) {
  ["c1", "c2", "c3", "c4"].forEach((id, i) => {
    document.getElementById(id).className = "cam-pill" + (on ? " active" : "");
    document.getElementById("s" + (i + 1)).textContent =
      label || (on ? "Running" : "Idle");
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
setHomeJobId(getCachedJobId());
applyRollDetails(getCachedRollDetails(getCachedJobId()));
setHomeOperatorNameOptions(getCachedOperatorNames(getCachedJobId()), getCachedRollDetails(getCachedJobId()).operator_name);
setHomeControlState(false);
initBridge();
["btnDefectClose"].forEach(function (id) {
  const button = document.getElementById(id);
  if (button) {
    button.addEventListener("click", closeDefectModal);
  }
});
const defectResetButton = document.getElementById("btnDefectReset");
if (defectResetButton) {
  defectResetButton.addEventListener("click", resetFromDefectModal);
}
const defectOverlay = document.getElementById("defectOverlay");
if (defectOverlay) {
  defectOverlay.addEventListener("click", function (event) {
    if (event.target === defectOverlay) closeDefectModal();
  });
}
const rollNumberInput = document.getElementById("nRollNumber");
if (rollNumberInput) {
  rollNumberInput.addEventListener("input", function () {
    setRollDisplay(rollNumberInput.value);
  });
}
