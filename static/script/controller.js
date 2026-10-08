let bridge = null;
let bridgeReady = false;
let toastTimer = null;

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

function closeDefectModal() {
  const overlay = $("defectOverlay");
  if (overlay) {
    overlay.classList.remove("open");
    overlay.setAttribute("aria-hidden", "true");
  }
}

function resetFromDefectModal() {
  closeDefectModal();
  runBridgeAction("resetSystem", "System reset");
}

function showDefectModal(payload) {
  const status = String(payload.status || "").trim().toUpperCase();
  if (status !== "DEFECT" && status !== "BAD") return;

  const overlay = $("defectOverlay");
  const title = $("defectModalTitle");
  const image = $("defectModalImage");
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
      if (bridgeReady && bridge.camera_status_signal) {
        bridge.camera_status_signal.connect((ok, message) => {
          if (message) {
            toast(message);
          }
        });
      }
      if (bridgeReady && bridge.defect_signal) {
        bridge.defect_signal.connect((raw) => {
          try {
            showDefectModal(JSON.parse(raw || "{}"));
          } catch (error) {
            console.error("Defect signal parse failed:", error);
          }
        });
      }
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

async function runBridgeAction(methodName, statusText) {
  const b = await initBridge();
  if (!b || !b[methodName]) {
    toast("Controller bridge is not available");
    return;
  }

  b[methodName]();
  const status = $("controllerStatus");
  if (status) {
    status.textContent = statusText;
  }
  if (methodName !== "startDetection") {
    toast(statusText);
  }
}

async function loadExposureSettings() {
  const b = await initBridge();
  const input = $("controllerExposure");
  const currentText = $("controllerExposureText");
  const status = $("controllerStatus");

  if (!input) return;

  if (!b || !b.controllerCameraSettings) {
    toast("Controller bridge is not available");
    return;
  }

  try {
    const raw = await callBridge("controllerCameraSettings");
    const data = JSON.parse(raw || "{}");
    if (!data.ok) {
      toast(data.message || "Unable to load exposure");
      return;
    }

    input.value = data.exposure;
    input.min = data.min_exposure;
    input.max = data.max_exposure;
    if (currentText) {
      currentText.textContent = data.exposure;
    }
    if (status) {
      status.textContent = `Current Exposure: ${data.exposure}`;
    }
  } catch (error) {
    console.error("Exposure load failed:", error);
    toast("Unable to load exposure");
  }
}

async function loadPlcStatus() {
  const b = await initBridge();
  const statusText = $("plcStatusText");

  if (!statusText) return;

  if (!b || !b.plcStatus) {
    statusText.textContent = "Bridge not available";
    toast("Controller bridge is not available");
    return;
  }

  statusText.textContent = "Checking...";

  try {
    const raw = await callBridge("plcStatus");
    const data = JSON.parse(raw || "{}");
    statusText.textContent = data.connected ? "Connected" : "Not Connected";
    statusText.classList.toggle("ok", Boolean(data.connected));
    statusText.classList.toggle("bad", !data.connected);
  } catch (error) {
    console.error("PLC status check failed:", error);
    statusText.textContent = "Not Connected";
    statusText.classList.remove("ok");
    statusText.classList.add("bad");
  }
}

async function saveExposure() {
  const input = $("controllerExposure");
  const currentText = $("controllerExposureText");
  const status = $("controllerStatus");
  const value = input ? input.value.trim() : "";

  if (!value) {
    toast("Enter exposure value");
    return;
  }

  const b = await initBridge();
  if (!b || !b.saveControllerExposure) {
    toast("Controller bridge is not available");
    return;
  }

  try {
    const raw = await callBridge("saveControllerExposure", value);
    const data = JSON.parse(raw || "{}");
    if (!data.ok) {
      toast(data.message || "Unable to save exposure");
      return;
    }

    input.value = data.exposure;
    if (currentText) {
      currentText.textContent = data.exposure;
    }
    if (status) {
      status.textContent = `Current Exposure: ${data.exposure}`;
    }
    toast(data.message || "Exposure saved");
  } catch (error) {
    console.error("Exposure save failed:", error);
    toast("Unable to save exposure");
  }
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
  await initBridge();
  await loadPlcStatus();
  await loadExposureSettings();
  const saveBtn = $("btnSaveExposure");

  if (saveBtn) {
    saveBtn.addEventListener("click", saveExposure);
  }
  const exposureInput = $("controllerExposure");
  if (exposureInput) {
    exposureInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        saveExposure();
      }
    });
  }
  ["btnDefectClose"].forEach((id) => {
    const button = $(id);
    if (button) {
      button.addEventListener("click", closeDefectModal);
    }
  });
  const defectResetButton = $("btnDefectReset");
  if (defectResetButton) {
    defectResetButton.addEventListener("click", resetFromDefectModal);
  }
  const defectOverlay = $("defectOverlay");
  if (defectOverlay) {
    defectOverlay.addEventListener("click", (event) => {
      if (event.target === defectOverlay) closeDefectModal();
    });
  }
});
