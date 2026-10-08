let stream = null;
let bridge = null;
let bridgeReady = false;
let mode = "normal";
let activeJobId = "";
let countTimer = null;
let toastTimer = null;
let galleryImages = [];
let galleryIndex = 0;
let galleryJobId = "";
let polygonCaptureWaiting = false;
let polygonPoints = [];
let polygonImageSize = { width: 0, height: 0 };
let modelProgressImageCount = 0;
let modelProgressHideTimer = null;

const ids = {
  liveStart: "btnLiveStart",
  liveStop: "btnLiveStop",
  startTraining: "btnStartTraining",
  stopTraining: "btnStopTraining",
  cameraFeed: "cameraFeed",
  video: "video",
  noSignal: "noSignal",
  camWrap: "camWrap",
  jobSelect: "trainedModelSel",
  sessionCount: "trainingImageCount",
  folderCount: "trainingFolderCount",
  trainingJobId: "trainingJobId",
  trainingRollColor: "trainingRollColor",
  trainingPolygonSize: "trainingPolygonSize",
  trainingCombinedPreview: "trainingCombinedPreview",
  deleteModel: "btnDeleteModel",
  modelProgressPanel: "modelProgressPanel",
  modelProgressMessage: "modelProgressMessage",
  modelProgressPercent: "modelProgressPercent",
  modelProgressFill: "modelProgressFill",
  modelProgressCount: "modelProgressCount",
  modelProgressStatus: "modelProgressStatus",
  trainingCompleteOverlay: "trainingCompleteOverlay",
  trainingCompleteMessage: "trainingCompleteMessage",
  trainingCompleteOk: "btnTrainingCompleteOk",
  polygonOverlay: "polygonOverlay",
  polygonStage: "polygonStage",
  polygonImage: "polygonImage",
  polygonCanvas: "polygonCanvas",
  polygonHint: "polygonHint",
  polygonOk: "btnPolygonOk",
  polygonReset: "btnPolygonReset",
  polygonCancel: "btnPolygonCancel",
};

function $(id) {
  return document.getElementById(id);
}

function on(id, eventName, handler) {
  const el = typeof id === "string" ? $(id) : id;
  if (el) {
    el.addEventListener(eventName, handler);
  }
}

function toast(message, type = "ok") {
  const el = $("toast");
  if (!el) return;

  el.textContent = message;
  el.className = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
}

function setModelProgress(percent = 0, message = "Model training", running = false) {
  const panel = $(ids.modelProgressPanel);
  const fill = $(ids.modelProgressFill);
  const percentEl = $(ids.modelProgressPercent);
  const messageEl = $(ids.modelProgressMessage);
  const countEl = $(ids.modelProgressCount);
  const statusEl = $(ids.modelProgressStatus);
  if (!panel || !fill || !percentEl || !messageEl || !countEl || !statusEl) return;

  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  const text = String(message || "").trim();
  const visible = running || value > 0 || Boolean(text);
  const foundMatch = text.match(/Found\s+(\d+)\s+training images/i);

  if (running && value <= 1) {
    modelProgressImageCount = 0;
  }

  if (foundMatch) {
    modelProgressImageCount = Number(foundMatch[1]) || 0;
  }

  panel.classList.toggle("show", visible);
  panel.classList.toggle("done", !running && value >= 100);
  panel.classList.toggle("failed", !running && value < 100);
  panel.setAttribute("aria-hidden", visible ? "false" : "true");
  fill.style.width = `${value}%`;
  percentEl.textContent = `${value}%`;
  messageEl.textContent = running
    ? "Processing captured images and updating model..."
    : text || "Model training completed";
  countEl.textContent = `Found ${modelProgressImageCount} training images`;
  statusEl.textContent = running
    ? "Model: checking"
    : value >= 100
      ? "Model: saved"
      : "Model: failed";

  window.clearTimeout(modelProgressHideTimer);
  if (!running && value >= 100) {
    openTrainingCompleteModal(text || "Model training completed.");
  } else if (!running) {
    modelProgressHideTimer = window.setTimeout(() => {
      panel.classList.remove("show", "done", "failed");
      panel.setAttribute("aria-hidden", "true");
    }, 4500);
  }
}

function hideModelProgress() {
  const panel = $(ids.modelProgressPanel);
  if (!panel) return;

  window.clearTimeout(modelProgressHideTimer);
  panel.classList.remove("show", "done", "failed");
  panel.setAttribute("aria-hidden", "true");
}

function openTrainingCompleteModal(message = "Model training completed.") {
  const overlay = $(ids.trainingCompleteOverlay);
  const messageEl = $(ids.trainingCompleteMessage);
  if (!overlay || !messageEl) return;

  messageEl.textContent = message;
  overlay.classList.add("open");
  overlay.setAttribute("aria-hidden", "false");
}

function closeTrainingCompleteModal() {
  const overlay = $(ids.trainingCompleteOverlay);
  if (overlay) {
    overlay.classList.remove("open");
    overlay.setAttribute("aria-hidden", "true");
  }

  hideModelProgress();
  closeImages();
}

function initBridge() {
  if (bridgeReady) return Promise.resolve(bridge);

  return new Promise((resolve) => {
    if (typeof QWebChannel === "undefined" || typeof qt === "undefined") {
      resolve(null);
      return;
    }

    new QWebChannel(qt.webChannelTransport, (channel) => {
      bridge = channel.objects.bridge;
      bridgeReady = Boolean(bridge);

      if (bridgeReady && bridge.frame_signal) {
        bridge.frame_signal.connect(updateCameraFrame);
      }

      if (bridgeReady && bridge.camera_status_signal) {
        bridge.camera_status_signal.connect((ok, message) => {
          setCameraUi(ok);
          toast(message || (ok ? "Camera started" : "Camera stopped"));
        });
      }

      if (bridgeReady && bridge.model_training_signal) {
        bridge.model_training_signal.connect((percent, message, running) => {
          setModelProgress(percent, message, running);
          toast(`${message}${running ? ` (${percent}%)` : ""}`, running ? "warn" : "ok");
          if (!running) {
            refreshJobList();
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

function makeCombinedJobId(jobId, rollColor, polygonSize) {
  return [jobId, rollColor, polygonSize].map((value) => String(value || "").trim()).join("_");
}

function readTrainingConfigFields() {
  return {
    jobId: $(ids.trainingJobId).value.trim(),
    rollColor: $(ids.trainingRollColor).value.trim(),
    polygonSize: $(ids.trainingPolygonSize).value.trim(),
  };
}

function updateTrainingCombinedPreview() {
  const { jobId, rollColor, polygonSize } = readTrainingConfigFields();
  const preview = $(ids.trainingCombinedPreview);

  if (!jobId && !rollColor && !polygonSize) {
    preview.textContent = "";
    return;
  }

  preview.textContent = makeCombinedJobId(jobId, rollColor, polygonSize);
}

function updateCameraFrame(jpg) {
  const img = $(ids.cameraFeed);
  const video = $(ids.video);

  if (!jpg) {
    clearCameraFeed();
    return;
  }

  if (video) {
    video.srcObject = null;
    video.style.display = "none";
  }

  img.src = jpg.startsWith("data:") ? jpg : `data:image/jpeg;base64,${jpg}`;
  img.style.display = "block";
  setCameraUi(true);

  if (polygonCaptureWaiting) {
    openPolygonEditorFromCurrentFrame();
  }
}

async function startBrowserCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    $(ids.cameraFeed).style.display = "none";
    $(ids.video).style.display = "block";
    $(ids.video).srcObject = stream;
    setCameraUi(true);
    if (polygonCaptureWaiting) {
      captureBrowserPolygonFrame();
    }
    return true;
  } catch (error) {
    console.error("Browser camera failed:", error);
    toast("Camera access denied", "error");
    return false;
  }
}

function stopBrowserCamera() {
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }
}

function clearCameraFeed() {
  stopBrowserCamera();
  const img = $(ids.cameraFeed);
  const video = $(ids.video);

  if (img) {
    img.removeAttribute("src");
    img.style.display = "block";
  }

  if (video) {
    video.srcObject = null;
    video.style.display = "none";
  }

  setCameraUi(false);
}

function setCameraUi(on) {
  $(ids.noSignal).classList.toggle("hidden", on);
  $(ids.camWrap).classList.toggle("active", on);
}

function setMode(nextMode) {
  mode = nextMode;

  const isLive = mode === "live";
  const isTraining = mode === "training";
  const isPolygon = mode === "polygon";
  const isBusy = isLive || isTraining || isPolygon;

  $(ids.liveStart).disabled = isBusy;
  $(ids.liveStop).disabled = !isLive;
  $(ids.startTraining).disabled = isBusy;
  $(ids.stopTraining).disabled = !isTraining && !isPolygon;

  $(ids.liveStop).classList.toggle("inactive", !isLive);
  $(ids.stopTraining).classList.toggle("inactive", !isTraining && !isPolygon);
  $(ids.liveStart).classList.toggle("inactive", isBusy);
  $(ids.startTraining).classList.toggle("inactive", isBusy);
}

async function startLive() {
  const b = await initBridge();

  if (b && b.startCamera) {
    b.startCamera();
  } else if (!(await startBrowserCamera())) {
    return;
  }

  setMode("live");
  toast("Live Camera Started");
}

async function stopLive() {
  const b = await initBridge();

  if (b && b.stopCamera) {
    b.stopCamera();
  }

  clearCameraFeed();
  setMode("normal");
  toast("Live Camera Stopped", "warn");
}

async function startTraining() {
  // Populate the popup job list before showing
  await populateJobPickerList();
  openJobPickerModal();
}

async function populateJobPickerList() {
  const list = $("jobPickerList");
  list.innerHTML = '<option value="">-- Select Job ID --</option>';

  const b = await initBridge();
  let jobs = [];

  if (b && (b.trained_model_options || b.source_job_options || b.config_options || b.job_options)) {
    try {
      const hasTrainedOptions = Boolean(b.trained_model_options);
      const method = hasTrainedOptions
        ? "trained_model_options"
        : b.source_job_options
          ? "source_job_options"
          : b.config_options
            ? "config_options"
            : "job_options";
      const raw = await callBridge(method);
      const parsed = typeof raw === "string" ? JSON.parse(raw || "[]") : raw;
      jobs = (Array.isArray(parsed) ? parsed : [])
        .map((job) => (typeof job === "object" ? job.job_id || job.Job_ID || job.value : job))
        .map((job) => String(job || "").trim())
        .filter(Boolean);
    } catch (error) {
      console.error("Job list failed:", error);
    }
  }

  Array.from(new Set(jobs)).forEach((job) => {
    const option = document.createElement("option");
    option.value = job;
    option.textContent = job;
    list.appendChild(option);
  });

  // Pre-select current value if available
  const current = $(ids.jobSelect).value || activeJobId;
  if (current && Array.from(list.options).some((o) => o.value === current)) {
    list.value = current;
  }
}

function openJobPickerModal() {
  $("jobPickerOverlay").classList.add("open");
  $("jobPickerOverlay").setAttribute("aria-hidden", "false");
  $("jobPickerList").focus();
}

function closeJobPickerModal() {
  $("jobPickerOverlay").classList.remove("open");
  $("jobPickerOverlay").setAttribute("aria-hidden", "true");
}

// async function confirmJobAndStartTraining() {
//   const { jobId, rollColor, polygonSize } = readTrainingConfigFields();
//   let selected = $("jobPickerList").value.trim();

//   if (jobId || rollColor || polygonSize) {
//     if (!jobId || !rollColor || !polygonSize) {
//       toast("Enter JOB ID, ROLL COLOR and POLYGON SIZE", "warn");
//       return;
//     }

//     // const b = await initBridge();
//     const combined = makeCombinedJobId(jobId, rollColor, polygonSize);
//     selected = combined;

//     if (b && b.saveTrainingConfig) {
//       try {
//         const raw = await callBridge("saveTrainingConfig", jobId, rollColor, polygonSize);
//         const data = JSON.parse(raw || "{}");
//         if (!data.ok) {
//           toast(data.message || "Unable to save training configuration", "error");
//           return;
//         }
//         selected = data.combined || combined;
//       } catch (error) {
//         console.error("Training config save failed:", error);
//         toast("Unable to save training configuration", "error");
//         return;
//       }
//     }
//   }

//   if (!selected) {
//     toast("Please select a training configuration", "warn");
//     return;
//   }

//   closeJobPickerModal();

async function confirmJobAndStartTraining() {
  const { jobId, rollColor, polygonSize } =
    readTrainingConfigFields();

  let selected = $("jobPickerList").value.trim();


  if (jobId || rollColor || polygonSize) {
    if (!jobId || !rollColor || !polygonSize) {
      toast(
        "Enter JOB ID, ROLL COLOR and POLYGON SIZE",
        "warn"
      );
      return;
    }

    const combined = makeCombinedJobId(
      jobId,
      rollColor,
      polygonSize
    );

    selected = combined;

    temporaryTrainingConfig = {
      jobId: jobId.trim(),
      rollColor: rollColor.trim(),
      polygonSize: polygonSize.trim(),
      combinedJobId: combined
    };

    console.log(
      "Temporary training configuration:",
      temporaryTrainingConfig
    );
  } else if (selected) {
    // An existing configuration was selected
    temporaryTrainingConfig = {
      combinedJobId: selected,
      existingConfig: true
    };
  }

  if (!selected) {
    toast(
      "Please select or enter a training configuration",
      "warn"
    );
    return;
  }

  closeJobPickerModal();


  // Sync the main dropdown to the chosen job
  const mainSelect = $(ids.jobSelect);
  if (!Array.from(mainSelect.options).some((o) => o.value === selected)) {
    const opt = document.createElement("option");
    opt.value = selected;
    opt.textContent = selected;
    mainSelect.appendChild(opt);
  }
  mainSelect.value = selected;

  const b = await initBridge();
  activeJobId = selected;
  setCounts(0, 0);

  let hasPolygon = false;
  if (b && b.has_training_polygon) {
    try {
      const raw = await callBridge("has_training_polygon", activeJobId);
      const data = JSON.parse(raw || "{}");
      hasPolygon = Boolean(data.ok && data.has_polygon);
    } catch (error) {
      console.error("Polygon check failed:", error);
    }
  }

  if (hasPolygon) {
    polygonCaptureWaiting = false;
    if (b && b.startTraining) {
      b.startTraining(activeJobId);
    } else if (!(await startBrowserCamera())) {
      return;
    }
    setMode("training");
    startCountTimer();
    toast(`Training Started: ${activeJobId}`);
    return;
  }

  polygonCaptureWaiting = true;

  if (b && b.startCamera) {
    b.startCamera();
  } else if (!(await startBrowserCamera())) {
    polygonCaptureWaiting = false;
    return;
  }

  waitForPolygonFrameFallback();
  setMode("polygon");
  toast("Capturing first image for polygon");
}

function captureBrowserPolygonFrame() {
  const video = $(ids.video);
  if (!video) return;

  const capture = () => {
    if (!polygonCaptureWaiting || !video.videoWidth || !video.videoHeight) return;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    polygonCaptureWaiting = false;
    openPolygonEditor(canvas.toDataURL("image/jpeg", 0.9));
  };

  if (video.readyState >= 2) {
    setTimeout(capture, 100);
  } else {
    video.addEventListener("loadeddata", () => setTimeout(capture, 100), { once: true });
  }
}

function openPolygonEditorFromFrame(frame) {
  if (!frame) return false;

  polygonCaptureWaiting = false;
  openPolygonEditor(frame.startsWith("data:") ? frame : `data:image/jpeg;base64,${frame}`);
  return true;
}

function openPolygonEditorFromCurrentFrame() {
  const img = $(ids.cameraFeed);
  if (!img || !img.src) return false;

  return openPolygonEditorFromFrame(img.src);
}

function waitForPolygonFrameFallback() {
  let attempts = 0;

  const tryOpen = async () => {
    attempts += 1;

    if (polygonCaptureWaiting && openPolygonEditorFromCurrentFrame()) {
      return;
    }

    const b = await initBridge();
    if (polygonCaptureWaiting && b && b.latest_camera_frame) {
      try {
        const frame = await callBridge("latest_camera_frame");
        if (openPolygonEditorFromFrame(frame)) {
          return;
        }
      } catch (error) {
        console.error("Latest camera frame failed:", error);
      }
    }

    if (polygonCaptureWaiting && attempts < 8) {
      window.setTimeout(tryOpen, 500);
      return;
    }

    if (polygonCaptureWaiting) {
      toast("No camera image received for polygon", "error");
    }
  };

  window.setTimeout(tryOpen, 500);
}

function openPolygonEditor(imageSrc) {
  const image = $(ids.polygonImage);
  const overlay = $(ids.polygonOverlay);

  polygonPoints = [];
  polygonImageSize = { width: 0, height: 0 };
  $(ids.polygonHint).textContent = "Click on the image to add polygon points.";
  $(ids.polygonOk).disabled = true;

  image.onload = () => {
    polygonImageSize = {
      width: image.naturalWidth,
      height: image.naturalHeight,
    };
    resizePolygonCanvas();
    drawPolygon();
  };

  image.src = imageSrc;
  overlay.classList.add("open");
  overlay.setAttribute("aria-hidden", "false");
  setMode("polygon");
}

function closePolygonEditor() {
  $(ids.polygonOverlay).classList.remove("open");
  $(ids.polygonOverlay).setAttribute("aria-hidden", "true");
  polygonPoints = [];
  drawPolygon();
}

function resizePolygonCanvas() {
  const image = $(ids.polygonImage);
  const canvas = $(ids.polygonCanvas);
  const rect = image.getBoundingClientRect();

  canvas.style.width = `${rect.width}px`;
  canvas.style.height = `${rect.height}px`;
  canvas.width = Math.max(1, Math.round(rect.width));
  canvas.height = Math.max(1, Math.round(rect.height));
}

function canvasPointFromEvent(event) {
  const canvas = $(ids.polygonCanvas);
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(canvas.width, event.clientX - rect.left)),
    y: Math.max(0, Math.min(canvas.height, event.clientY - rect.top)),
  };
}

function imagePointFromCanvas(point) {
  const canvas = $(ids.polygonCanvas);
  return {
    x: Math.round((point.x / canvas.width) * polygonImageSize.width),
    y: Math.round((point.y / canvas.height) * polygonImageSize.height),
  };
}

function drawPolygon() {
  const canvas = $(ids.polygonCanvas);
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (!polygonPoints.length) return;

  ctx.lineWidth = 3;
  ctx.strokeStyle = "#22c55e";
  ctx.fillStyle = "rgba(34, 197, 94, 0.18)";
  ctx.beginPath();
  ctx.moveTo(polygonPoints[0].x, polygonPoints[0].y);
  polygonPoints.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
  if (polygonPoints.length >= 3) {
    ctx.closePath();
    ctx.fill();
  }
  ctx.stroke();

  polygonPoints.forEach((point, index) => {
    ctx.beginPath();
    ctx.arc(point.x, point.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = index === 0 ? "#facc15" : "#ffffff";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#16a34a";
    ctx.stroke();
  });
}

function addPolygonPoint(event) {
  polygonPoints.push(canvasPointFromEvent(event));
  $(ids.polygonOk).disabled = polygonPoints.length < 3;
  $(ids.polygonHint).textContent =
    polygonPoints.length < 3
      ? `Add ${3 - polygonPoints.length} more point(s).`
      : "Click OK to save polygon and start training.";
  drawPolygon();
}

function resetPolygon() {
  polygonPoints = [];
  $(ids.polygonOk).disabled = true;
  $(ids.polygonHint).textContent = "Click on the image to add polygon points.";
  drawPolygon();
}

async function cancelPolygonTraining() {
  polygonCaptureWaiting = false;
  closePolygonEditor();
  await stopTraining(false);
}

async function confirmPolygonAndStartCapture() {
  if (polygonPoints.length < 3) {
    toast("Draw at least 3 polygon points", "warn");
    return;
  }

  const points = polygonPoints.map(imagePointFromCanvas);
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const polygonWidth = maxX - minX;
  const polygonHeight = maxY - minY;
  const polygon = {
    image_width: polygonImageSize.width,
    image_height: polygonImageSize.height,
    polygon_width: polygonWidth,
    polygon_height: polygonHeight,
    points,
    x: minX,
    y: minY,
    width: polygonWidth,
    height: polygonHeight,
    x0: minX,
    y0: minY,
    x1: maxX,
    y1: minY,
    x2: minX,
    y2: maxY,
    x3: maxX,
    y3: maxY,
  };

  const b = await initBridge();
  if (b && b.save_training_polygon) {
    const raw = await callBridge("save_training_polygon", activeJobId, JSON.stringify(polygon));
    const data = JSON.parse(raw || "{}");
    if (!data.ok) {
      toast(data.message || "Unable to save polygon", "error");
      return;
    }
  }

  closePolygonEditor();

  if (b && b.startTraining) {
    b.startTraining(activeJobId);
  }

  setMode("training");
  startCountTimer();
  toast(`Training Started: ${activeJobId}`);
}

async function stopTraining(showImages = true) {
  stopCountTimer();

  const b = await initBridge();
  if (b && b.stopTraining) {
    b.stopTraining();
  } else {
    stopBrowserCamera();
  }

  clearCameraFeed();
  setMode("normal");
  await refreshCounts(activeJobId);
  await refreshJobList();
  toast("Training Stopped", "warn");

  if (showImages) {
    await openImages(activeJobId);
  }
}

async function startModelTrainingForJob(jobId) {
  const safeJob = String(jobId || "").trim();
  if (!safeJob) {
    toast("No Job ID selected for model training", "warn");
    return;
  }

  const b = await initBridge();
  if (!b || !b.startModelTraining) {
    toast("Model training is not available", "error");
    return;
  }

  try {
    setModelProgress(0, `Training model for ${safeJob}`, true);
    const raw = await callBridge("startModelTraining", safeJob);
    const data = JSON.parse(raw || "{}");
    if (!data.ok) {
      setModelProgress(0, data.message || "Model training failed", false);
    }
    toast(data.message || (data.ok ? "Model training started" : "Unable to start model training"), data.ok ? "warn" : "error");
  } catch (error) {
    console.error("Model training start failed:", error);
    setModelProgress(0, "Unable to start model training", false);
    toast("Unable to start model training", "error");
  }
}

function setCounts(sessionCount = 0, folderCount = 0) {
  $(ids.sessionCount).textContent = String(sessionCount);
  $(ids.folderCount).textContent = String(folderCount);
}

async function refreshCounts(jobId = $(ids.jobSelect).value.trim()) {
  if (!jobId) {
    setCounts(0, 0);
    return;
  }

  const b = await initBridge();
  if (!b || !b.getTrainingCaptureStatus) {
    setCounts(0, 0);
    return;
  }

  try {
    const raw = await callBridge("getTrainingCaptureStatus", jobId);
    const data = JSON.parse(raw || "{}");
    if (data.ok) {
      setCounts(data.session_count || 0, data.folder_count || 0);
    }
  } catch (error) {
    console.error("Count refresh failed:", error);
  }
}

function startCountTimer() {
  stopCountTimer();
  refreshCounts(activeJobId);
  countTimer = setInterval(() => refreshCounts(activeJobId), 1000);
}

function stopCountTimer() {
  if (countTimer) {
    clearInterval(countTimer);
    countTimer = null;
  }
}

async function refreshJobList() {
  const select = $(ids.jobSelect);
  const current = select.value || activeJobId;
  select.innerHTML = '<option value="">-- Select Job ID --</option>';

  const b = await initBridge();
  let jobs = [];

  if (b && (b.trained_model_options || b.job_options)) {
    try {
      const raw = await callBridge(b.trained_model_options ? "trained_model_options" : "job_options");
      const parsed = typeof raw === "string" ? JSON.parse(raw || "[]") : raw;
      jobs = (Array.isArray(parsed) ? parsed : [])
        .map((job) => (typeof job === "object" ? job.job_id || job.Job_ID || job.value : job))
        .map((job) => String(job || "").trim())
        .filter(Boolean);
    } catch (error) {
      console.error("Job list failed:", error);
    }
  }

  Array.from(new Set(jobs)).forEach((job) => {
    const option = document.createElement("option");
    option.value = job;
    option.textContent = job;
    select.appendChild(option);
  });

  if (current && Array.from(select.options).some((option) => option.value === current)) {
    select.value = current;
  }

  await refreshCounts(select.value);
}

async function openImages(jobId = $(ids.jobSelect).value.trim()) {
  if (jobId && typeof jobId === "object") {
    jobId = $(ids.jobSelect).value.trim();
  }

  jobId = String(jobId || "").trim();
  if (!jobId) {
    toast("Please select a Job ID", "warn");
    return;
  }

  const select = $(ids.jobSelect);
  if (select && !Array.from(select.options).some((option) => option.value === jobId)) {
    const option = document.createElement("option");
    option.value = jobId;
    option.textContent = jobId;
    select.appendChild(option);
  }
  if (select && Array.from(select.options).some((option) => option.value === jobId)) {
    select.value = jobId;
  }

  const b = await initBridge();
  if (!b || !b.getTrainingImageFilenames) {
    toast("Image list is not available", "error");
    return;
  }

  const raw = await callBridge("getTrainingImageFilenames", jobId);
  const data = JSON.parse(raw || "{}");
  galleryImages = data.ok ? data.filenames || [] : [];
  galleryIndex = 0;
  galleryJobId = jobId;

  $("imageModalTitle").textContent = `Training Images - ${jobId}`;
  $("imageOverlay").classList.add("open");
  $("imageOverlay").setAttribute("aria-hidden", "false");
  renderGallery();
}

async function renderGallery() {
  const preview = $("imagePreview");
  const counter = $("imageCounter");
  const prev = $("btnPrevImage");
  const next = $("btnNextImage");
  const deleteBtn = $("btnDeleteImage");
  const trainBtn = $("btnTrainImage");

  counter.textContent = `${galleryImages.length ? galleryIndex + 1 : 0} / ${galleryImages.length}`;
  prev.disabled = galleryIndex <= 0;
  next.disabled = galleryIndex >= galleryImages.length - 1;
  deleteBtn.disabled = galleryImages.length === 0;
  trainBtn.disabled = galleryImages.length === 0;

  if (galleryImages.length === 0) {
    preview.innerHTML = "<p>No images found for this job.</p>";
    return;
  }

  preview.innerHTML = `
    <div class="image-loading">
      <span aria-hidden="true"></span>
      <strong>Loading image</strong>
    </div>
  `;
  const jobId = galleryJobId || $(ids.jobSelect).value.trim();
  const b = await initBridge();
  const raw = await callBridge("getTrainingImage", jobId, galleryImages[galleryIndex]);
  const data = JSON.parse(raw || "{}");

  if (data.ok && data.data) {
    preview.innerHTML = "";
    const img = document.createElement("img");
    img.alt = galleryImages[galleryIndex];
    img.src = data.data;
    preview.appendChild(img);
  } else {
    preview.innerHTML = `<p>${data.message || "Unable to load this image."}</p>`;
  }
}

function closeImages() {
  $("imageOverlay").classList.remove("open");
  $("imageOverlay").setAttribute("aria-hidden", "true");
  galleryImages = [];
  galleryIndex = 0;
  galleryJobId = "";
}

async function deleteCurrentImage() {
  const jobId = galleryJobId || $(ids.jobSelect).value.trim();
  const filename = galleryImages[galleryIndex];
  if (!jobId || !filename) {
    toast("No image selected", "warn");
    return;
  }

  if (!window.confirm(`Delete image ${filename}?`)) {
    return;
  }

  const b = await initBridge();
  if (!b || !b.deleteTrainingImage) {
    toast("Image delete is not available", "error");
    return;
  }

  try {
    const raw = await callBridge("deleteTrainingImage", jobId, filename);
    const data = JSON.parse(raw || "{}");
    if (!data.ok) {
      toast(data.message || "Image delete failed", "error");
      return;
    }

    galleryImages.splice(galleryIndex, 1);
    if (galleryIndex >= galleryImages.length) {
      galleryIndex = Math.max(0, galleryImages.length - 1);
    }
    toast(data.message || "Image deleted");
    await renderGallery();
    await refreshCounts(jobId);
    await refreshJobList();
  } catch (error) {
    console.error("Image delete failed:", error);
    toast("Image delete failed", "error");
  }
}

async function trainCurrentImage() {
  const jobId = galleryJobId || $(ids.jobSelect).value.trim();
  const filename = galleryImages[galleryIndex];
  if (!jobId || !filename) {
    toast("No image selected", "warn");
    return;
  }

  const b = await initBridge();
  if (!b || !b.startModelTrainingImage) {
    toast("Image training is not available", "error");
    return;
  }

  try {
    setModelProgress(0, `Training ${filename}`, true);
    const raw = await callBridge("startModelTrainingImage", jobId, filename);
    const data = JSON.parse(raw || "{}");
    if (!data.ok) {
      setModelProgress(0, data.message || "Image training failed", false);
    }
    toast(data.message || (data.ok ? "Image training started" : "Image training failed"), data.ok ? "warn" : "error");
  } catch (error) {
    console.error("Image training failed:", error);
    setModelProgress(0, "Image training failed", false);
    toast("Image training failed", "error");
  }
}

async function deleteSelectedModel() {
  const jobId = $(ids.jobSelect).value.trim();
  if (!jobId) {
    toast("Please select a Job ID", "warn");
    return;
  }

  if (!window.confirm(`Delete training images and model for ${jobId}?`)) {
    return;
  }

  const b = await initBridge();
  if (!b || !b.deleteTrainingJob) {
    toast("Delete is not available", "error");
    return;
  }

  try {
    const raw = await callBridge("deleteTrainingJob", jobId);
    const data = JSON.parse(raw || "{}");
    if (!data.ok) {
      toast(data.message || "Delete failed", "error");
      return;
    }

    if (activeJobId === jobId) {
      activeJobId = "";
    }
    toast(data.message || "Deleted");
    await refreshJobList();
    await refreshCounts("");
  } catch (error) {
    console.error("Delete failed:", error);
    toast("Delete failed", "error");
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
  await refreshJobList();
  setMode("normal");

  on(ids.liveStart, "click", startLive);
  on(ids.liveStop, "click", stopLive);
  on(ids.startTraining, "click", startTraining);
  on(ids.stopTraining, "click", () => stopTraining(true));
  on("btnJobPickerOk", "click", confirmJobAndStartTraining);
  on("btnJobPickerCancel", "click", closeJobPickerModal);
  [ids.trainingJobId, ids.trainingRollColor, ids.trainingPolygonSize].forEach((id) => {
    on(id, "input", updateTrainingCombinedPreview);
  });
  on("jobPickerOverlay", "click", (e) => {
    if (e.target === $("jobPickerOverlay")) closeJobPickerModal();
  });
  on(ids.polygonCanvas, "click", addPolygonPoint);
  on(ids.polygonReset, "click", resetPolygon);
  on(ids.polygonCancel, "click", cancelPolygonTraining);
  on(ids.polygonOk, "click", confirmPolygonAndStartCapture);
  on(ids.polygonOverlay, "click", (e) => {
    if (e.target === $(ids.polygonOverlay)) cancelPolygonTraining();
  });
  window.addEventListener("resize", () => {
    if ($(ids.polygonOverlay).classList.contains("open")) {
      resizePolygonCanvas();
      drawPolygon();
    }
  });
  on(ids.jobSelect, "change", (event) => refreshCounts(event.target.value));
  on("btnViewImages", "click", () => openImages());
  on(ids.deleteModel, "click", deleteSelectedModel);
  on("btnCloseImages", "click", closeImages);
  on(ids.trainingCompleteOk, "click", closeTrainingCompleteModal);
  on("btnDeleteImage", "click", deleteCurrentImage);
  on("btnTrainImage", "click", trainCurrentImage);
  on("btnPrevImage", "click", async () => {
    if (galleryIndex > 0) {
      galleryIndex -= 1;
      await renderGallery();
    }
  });
  on("btnNextImage", "click", async () => {
    if (galleryIndex < galleryImages.length - 1) {
      galleryIndex += 1;
      await renderGallery();
    }
  });
});
