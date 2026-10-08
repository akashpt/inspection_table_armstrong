let bridge = null;
let bridgeReady = false;
let toastTimer = null;
let automaticShift = "";

const fieldIds = {
  roll_id: "settingsRollId",
  shift: "settingsShift",
  operator_name: "settingsOperatorName",
  machine_number: "settingsMachineNumber",
  fabric_type: "settingsFabricType",
  block_confidence: "blockConfidence",
  vertical_confidence: "verticalConfidence",
  horizontal_confidence: "horizontalConfidence",
  new_vertical_confidence: "newVerticalConfidence",
  new_horizontal_confidence: "newHorizontalConfidence",
  threshold_value: "thresholdValue",
};

const cameraFieldIds = {
  camera_indexes: "cameraIndexes",
  capture_step_mm: "captureStepMm",
  exposure: "cameraExposure",
  min_exposure: "minExposure",
  max_exposure: "maxExposure",
};

function $(id) {
  return document.getElementById(id);
}

function toast(message) {
  const el = $("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2000);
}

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

function readSettings() {
  const settings = {};
  Object.keys(fieldIds).forEach((key) => {
    settings[key] = $(fieldIds[key]).value.trim();
  });
  settings.shift = automaticShift || settings.shift;

  return settings;
}

function readCameraSettings() {
  const settings = {};
  Object.entries(cameraFieldIds).forEach(([key, id]) => {
    const element = $(id);
    if (element) {
      settings[key] = element.value.trim();
    }
  });
  return settings;
}

function applySettings(settings = {}) {
  Object.entries(fieldIds).forEach(([key, id]) => {
    if (settings[key] !== undefined) {
      if (key === "operator_name") {
        const value = String(settings[key] || "").trim();
        $(id).value = Array.from($(id).options).some((option) => option.value === value) ? value : "";
        return;
      }
      if (key === "shift") {
        const value = String(automaticShift || settings[key] || "").trim();
        $(id).value = Array.from($(id).options).some((option) => option.value === value) ? value : "";
        return;
      }
      if (key === "threshold_value") {
        const value = String(settings[key] || "").replace("%", "").trim() || "100";
        $(id).value = Array.from($(id).options).some((option) => option.value === value) ? value : "100";
        return;
      }
      $(id).value = settings[key];
    }
  });
}

function applyCameraSettings(settings = {}) {
  Object.entries(cameraFieldIds).forEach(([key, id]) => {
    const element = $(id);
    if (!element || settings[key] === undefined) return;

    if (key === "camera_indexes" && Array.isArray(settings[key])) {
      element.value = settings[key].join(", ");
      return;
    }

    element.value = settings[key];
  });
}

async function loadCameraSettings() {
  const b = await initBridge();
  if (!b || !b.settings_json) return;

  try {
    const raw = await callBridge("settings_json");
    const data = JSON.parse(raw || "{}");
    if (data.ok && data.settings) {
      applyCameraSettings(data.settings);
    }
  } catch (error) {
    console.error("Camera settings load failed:", error);
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

function setOperatorOptions(names = [], selectedName = "") {
  const select = $("settingsOperatorName");
  const selected = String(selectedName || select.value || "").trim();
  const values = Array.from(new Set((names || []).map((name) => String(name || "").trim()).filter(Boolean)));

  select.innerHTML = '<option value="">-- Select operator --</option>';
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  select.value = values.includes(selected) ? selected : "";
}

function setShiftOptions(shifts = [], selectedShift = "") {
  const select = $("settingsShift");
  if (!select) return;

  const selected = String(selectedShift || select.value || "").trim();
  const items = (Array.isArray(shifts) ? shifts : [])
    .map((item) => {
      if (typeof item === "object") {
        const value = String(item.shift || item.name || item.value || "").trim();
        return {
          value,
          label: String(item.display || item.label || value).trim(),
        };
      }
      const value = String(item || "").trim();
      return { value, label: value };
    })
    .filter((item) => item.value);

  select.innerHTML = '<option value="">-- Select shift --</option>';
  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    select.appendChild(option);
  });

  select.value = items.some((item) => item.value === selected) ? selected : "";
}

async function loadShifts(selectedShift = "") {
  const b = await initBridge();
  let currentShift = "";
  if (b && b.currentShift) {
    try {
      const raw = await callBridge("currentShift");
      const data = JSON.parse(raw || "{}");
      currentShift = String(data.shift && data.shift.shift || "").trim();
      automaticShift = currentShift;
    } catch (error) {
      console.error("Current shift load failed:", error);
    }
  }
  const preferredShift = currentShift || selectedShift;

  if (b && b.listShifts) {
    try {
      const raw = await callBridge("listShifts");
      const data = JSON.parse(raw || "{}");
      if (data.ok && Array.isArray(data.shifts)) {
        setShiftOptions(data.shifts, preferredShift);
        return data.shifts;
      }
    } catch (error) {
      console.error("Shift list load failed:", error);
    }
  }

  setShiftOptions(["A", "B", "C"], preferredShift);
  return [];
}

function renderOperatorList(names = []) {
  const list = $("settingsOperatorList");
  if (!list) return;

  list.innerHTML = "";
  const values = Array.from(new Set((names || []).map((name) => String(name || "").trim()).filter(Boolean)));
  list.classList.toggle("empty", values.length === 0);

  if (!values.length) {
    list.textContent = "No operators saved";
    return;
  }

  values.forEach((name) => {
    const pill = document.createElement("div");
    pill.className = "operator-pill";

    const label = document.createElement("span");
    label.textContent = name;

    const button = document.createElement("button");
    button.className = "operator-delete";
    button.type = "button";
    button.title = "Delete operator";
    button.textContent = "x";
    button.addEventListener("click", () => deleteOperatorName(name));

    pill.appendChild(label);
    pill.appendChild(button);
    list.appendChild(pill);
  });
}

async function loadOperatorNames(selectedName = "") {
  const currentJob = $("settingsConfigSelect") ? $("settingsConfigSelect").value.trim() : "";
  let names = getCachedOperatorNames(currentJob);

  const b = await initBridge();
  if (b && b.listOperatorNames) {
    try {
      const raw = await callBridge("listOperatorNames");
      const data = JSON.parse(raw || "{}");
      if (data.ok && Array.isArray(data.operators)) {
        names = data.operators;
        rememberOperatorNames(names, currentJob);
      }
    } catch (error) {
      console.error("Operator list load failed:", error);
    }
  }

  setOperatorOptions(names, selectedName);
  renderOperatorList(names);
  return names;
}

async function addOperatorName() {
  const input = $("settingsNewOperatorName");
  const name = input.value.trim();
  if (!name) {
    toast("Enter operator name");
    return;
  }

  const b = await initBridge();
  if (b && b.saveOperatorName) {
    const raw = await callBridge("saveOperatorName", name);
    const data = JSON.parse(raw || "{}");
    if (!data.ok) {
      toast(data.message || "Operator save failed");
      return;
    }
    input.value = "";
    await loadOperatorNames(name);
    toast("Operator saved");
    return;
  }

  const names = Array.from(new Set([...getCachedOperatorNames($("settingsConfigSelect").value.trim()), name]));
  rememberOperatorNames(names, $("settingsConfigSelect").value.trim());
  input.value = "";
  setOperatorOptions(names, name);
  renderOperatorList(names);
  toast("Operator saved");
}

async function deleteOperatorName(name) {
  if (!window.confirm("Delete operator " + name + "?")) {
    return;
  }

  const selected = $("settingsOperatorName").value.trim();
  const b = await initBridge();
  if (b && b.deleteOperatorName) {
    const raw = await callBridge("deleteOperatorName", name);
    const data = JSON.parse(raw || "{}");
    if (!data.ok) {
      toast(data.message || "Operator delete failed");
      return;
    }
    forgetOperatorName(name);
    if (selected === name) {
      await clearSelectedOperatorReference(name);
    }
    await loadOperatorNames(selected === name ? "" : selected);
    toast(data.message || "Operator deleted");
    return;
  }

  const currentJob = $("settingsConfigSelect").value.trim();
  const names = getCachedOperatorNames(currentJob).filter((value) => value !== name);
  rememberOperatorNames(names, currentJob);
  forgetOperatorName(name);
  setOperatorOptions(names, selected === name ? "" : selected);
  renderOperatorList(names);
  toast("Operator deleted");
}

function forgetOperatorName(name) {
  const deleted = String(name || "").trim();
  if (!deleted) return;

  try {
    const data = JSON.parse(localStorage.getItem("operatorNames") || "{}");
    Object.keys(data).forEach((key) => {
      if (Array.isArray(data[key])) {
        data[key] = data[key].filter((value) => String(value || "").trim() !== deleted);
      }
    });
    localStorage.setItem("operatorNames", JSON.stringify(data));

    const details = JSON.parse(localStorage.getItem("rollDetails") || "{}");
    if (String(details.operator_name || "").trim() === deleted) {
      details.operator_name = "";
      localStorage.setItem("rollDetails", JSON.stringify(details));
    }
  } catch (error) {
    console.error("Operator cache cleanup failed:", error);
  }
}

async function clearSelectedOperatorReference(name) {
  const selectedJob = $("settingsConfigSelect").value.trim();
  if (!selectedJob) return;

  try {
    const details = JSON.parse(localStorage.getItem("rollDetails") || "{}");
    details.job_id = selectedJob;
    details.operator_name = "";
    localStorage.setItem("rollDetails", JSON.stringify(details));
  } catch (error) {
    console.error("Roll cache cleanup failed:", error);
  }

  if (bridge && bridge.save_selected_config) {
    try {
      await callBridge("save_selected_config", selectedJob, JSON.stringify({ operator_name: "" }));
    } catch (error) {
      console.error("Operator config cleanup failed:", error);
    }
  }
}

async function deleteSelectedOperatorName() {
  const name = $("settingsOperatorName").value.trim();
  if (!name) {
    toast("Select operator to delete");
    return;
  }

  await deleteOperatorName(name);
}

function rememberRollDetails(settings, jobId = "") {
  const rollDetails = {
    job_id: String(jobId || "").trim(),
    roll_id: settings.roll_id || "",
    shift: settings.shift || "",
    operator_name: settings.operator_name || "",
    machine_number: settings.machine_number || "",
    fabric_type: settings.fabric_type || "",
    threshold_value: settings.threshold_value || "100",
  };

  try {
    localStorage.setItem("rollDetails", JSON.stringify(rollDetails));
  } catch (error) {
    console.error("Roll cache failed:", error);
  }
}

function rememberSelectedJob(jobId) {
  const value = String(jobId || "").trim();
  if (!value) return;

  try {
    localStorage.setItem("selectedJobId", value);
  } catch (error) {
    console.error("Selected job cache failed:", error);
  }
}

async function loadConfigOptions() {
  const select = $("settingsConfigSelect");
  select.innerHTML = '<option value="">-- Select configuration --</option>';

  const b = await initBridge();
  if (!b || !b.config_options) return;

  try {
    const raw = await callBridge("config_options");
    const parsed = JSON.parse(raw || "[]");
    const values = (Array.isArray(parsed) ? parsed : [])
      .map((item) => (typeof item === "object" ? item.job_id || item.Job_ID || item.value : item))
      .map((value) => String(value || "").trim())
      .filter(Boolean);

    Array.from(new Set(values)).forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });

    const selectedRaw = await callBridge("selected_config");
    const selectedData = JSON.parse(selectedRaw || "{}");
    const selected = String(selectedData.selected || "").trim();
    if (selected && Array.from(select.options).some((option) => option.value === selected)) {
      select.value = selected;
      rememberSelectedJob(selected);
      await loadConfigSettings();
    }
  } catch (error) {
    console.error("Settings options failed:", error);
    toast("Unable to load settings");
  }
}

async function loadConfigSettings() {
  const selected = $("settingsConfigSelect").value.trim();
  if (!selected || !bridge || !bridge.get_config) return;

  try {
    const raw = await callBridge("get_config", selected);
    const data = JSON.parse(raw || "{}");
    if (data.ok && data.config) {
      const settings = data.config.settings || {};
      await loadShifts(settings.shift || getCachedRollDetails(selected).shift || "");
      applySettings({ ...getCachedRollDetails(selected), ...settings });
      await loadOperatorNames(settings.operator_name || "");
    }
  } catch (error) {
    console.error("Config load failed:", error);
  }
}

async function saveSelectedSettings() {
  const selected = $("settingsConfigSelect").value.trim();
  const settings = readSettings();

  const b = await initBridge();
  if (selected && settings.operator_name && b && b.saveOperatorName) {
    const operatorRaw = await callBridge("saveOperatorName", settings.operator_name);
    const operatorData = JSON.parse(operatorRaw || "{}");
    if (!operatorData.ok) {
      toast(operatorData.message || "Operator save failed");
      return;
    }
  }

  if (selected && b && b.save_selected_config) {
    const raw = await callBridge("save_selected_config", selected, JSON.stringify(settings));
    const data = JSON.parse(raw || "{}");

    if (!data.ok) {
      toast(data.message || "Unable to save settings");
      return;
    }
  }

  if (b && b.save_settings_json) {
    const raw = await callBridge("save_settings_json", JSON.stringify(readCameraSettings()));
    const data = JSON.parse(raw || "{}");

    if (!data.ok) {
      toast(data.message || "Unable to save JSON settings");
      return;
    }

    if (data.settings) {
      applyCameraSettings(data.settings);
    }
  }

  if (selected) {
    rememberSelectedJob(selected);
    rememberRollDetails(settings, selected);
    await loadOperatorNames(settings.operator_name || "");
    toast("Settings saved: " + selected);
  } else {
    toast(b && b.save_settings_json ? "JSON settings saved" : "Please select a configuration");
  }
  setTimeout(goHome, 300);
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

window.addEventListener("load", async () => {
  let cachedJob = "";
  try {
    cachedJob = localStorage.getItem("selectedJobId") || "";
  } catch {
    cachedJob = "";
  }
  await initBridge();
  await loadShifts(getCachedRollDetails(cachedJob).shift || "");
  applySettings(getCachedRollDetails(cachedJob));
  await loadCameraSettings();
  await loadOperatorNames(getCachedRollDetails(cachedJob).operator_name || "");
  await loadConfigOptions();
  $("settingsConfigSelect").addEventListener("change", loadConfigSettings);
  $("settingsOkBtn").addEventListener("click", saveSelectedSettings);
  $("settingsAddOperatorBtn").addEventListener("click", addOperatorName);
  $("settingsDeleteOperatorBtn").addEventListener("click", deleteSelectedOperatorName);
  $("settingsNewOperatorName").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addOperatorName();
    }
  });
});
