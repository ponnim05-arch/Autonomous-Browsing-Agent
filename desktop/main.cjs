const { app, BrowserWindow, dialog, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const crypto = require("node:crypto");

app.setAppUserModelId("com.ponnim05.autonomousbrowseragent");

let backend;
let backendLog;
let controlToken;
let backendUrl;
let shuttingDown = false;

function parseEnvFile(content) {
  const values = {};
  for (const line of content.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match || match[1].startsWith("#")) continue;
    let value = match[2];
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }
  return values;
}

async function reserveLoopbackPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function waitForBackend(child, url, logPath) {
  const deadline = Date.now() + 90_000;
  let lastError;
  child.once("error", (error) => {
    lastError = error;
  });
  while (Date.now() < deadline) {
    if (lastError && child.pid === undefined) {
      throw new Error(`Backend could not be started: ${lastError}. See ${logPath}`);
    }
    if (child.exitCode !== null) {
      throw new Error(`Backend exited with code ${child.exitCode}. See ${logPath}`);
    }
    try {
      const response = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(1500) });
      if (response.ok) return;
      lastError = new Error(`Health endpoint returned HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  throw new Error(`Backend did not become ready: ${lastError}. See ${logPath}`);
}

async function createWindow() {
  const userData = app.getPath("userData");
  fs.mkdirSync(userData, { recursive: true });
  const envFile = path.join(userData, ".env");
  if (!fs.existsSync(envFile)) {
    fs.writeFileSync(
      envFile,
      [
        "# Add your LLM provider credentials here, then restart the app.",
        "LLM_PROVIDER=nvidia",
        "NVIDIA_API_KEY=",
        "NVIDIA_FAST_API_KEY=",
        "NVIDIA_REASONING_API_KEY=",
        "NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1",
        "LLM_MODEL=meta/llama-3.2-11b-vision-instruct",
        "FAST_MODEL=meta/llama-3.2-11b-vision-instruct",
        "REASONING_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "",
      ].join("\n"),
      { flag: "wx" },
    );
  }

  const config = parseEnvFile(fs.readFileSync(envFile, "utf8"));
  const port = await reserveLoopbackPort();
  backendUrl = `http://127.0.0.1:${port}`;
  controlToken = crypto.randomBytes(32).toString("hex");
  const backendDir = path.join(process.resourcesPath, "backend");
  const backendExe = path.join(backendDir, "agent-backend.exe");
  const frontendDir = path.join(process.resourcesPath, "frontend");
  const browserDir = path.join(process.resourcesPath, "ms-playwright");
  const logPath = path.join(userData, "backend.log");

  if (!fs.existsSync(backendExe) || !fs.existsSync(path.join(frontendDir, "index.html"))) {
    throw new Error("Desktop app resources are incomplete. Reinstall the application.");
  }

  backendLog = fs.createWriteStream(logPath, { flags: "a" });
  backend = spawn(backendExe, [], {
    cwd: userData,
    windowsHide: true,
    env: {
      ...process.env,
      ...config,
      PORT: String(port),
      APP_DATA_DIR: userData,
      APP_FRONTEND_DIST: frontendDir,
      PLAYWRIGHT_BROWSERS_PATH: browserDir,
      DESKTOP_CONTROL_TOKEN: controlToken,
      IS_SERVER: "false",
      BROWSER_MODE: config.BROWSER_MODE || "visible",
      HEADLESS: config.HEADLESS || "false",
      BROWSER_TYPE: config.BROWSER_TYPE || "chromium",
      KEEP_BROWSER_OPEN: "false",
      DB_PATH: config.DB_PATH || path.join(userData, "data", "experiments.db"),
      LOG_DIR: config.LOG_DIR || path.join(userData, "logs", "runs"),
      CORS_ORIGINS: backendUrl,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  backend.stdout.pipe(backendLog);
  backend.stderr.pipe(backendLog);

  await waitForBackend(backend, backendUrl, logPath);
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.once("ready-to-show", () => window.show());
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    try {
      if (new URL(url).origin !== new URL(backendUrl).origin) event.preventDefault();
    } catch {
      event.preventDefault();
    }
  });
  await window.loadURL(backendUrl);

  if (
    !config.NVIDIA_API_KEY &&
    !config.NVIDIA_FAST_API_KEY &&
    !config.NVIDIA_REASONING_API_KEY &&
    !config.GEMINI_API_KEY &&
    !config.OPENAI_API_KEY &&
    !config.ANTHROPIC_API_KEY
  ) {
    const { response } = await dialog.showMessageBox(window, {
      type: "info",
      title: "Configure an LLM provider",
      message: "Add an LLM provider API key to use agent planning and execution.",
      detail: `The private configuration file is:\n${envFile}\n\nIt will open after you close this message.`,
      buttons: ["Open configuration", "Later"],
      defaultId: 0,
      cancelId: 1,
    });
    if (response === 0) await shell.openPath(envFile);
  }
}

async function stopBackend() {
  if (shuttingDown) return;
  shuttingDown = true;
  if (!backend || backend.exitCode !== null) {
    backendLog?.end();
    return;
  }
  try {
    await fetch(`${backendUrl}/api/desktop/shutdown`, {
      method: "POST",
      headers: { "x-desktop-control-token": controlToken },
      signal: AbortSignal.timeout(3000),
    });
    await Promise.race([
      new Promise((resolve) => backend.once("exit", resolve)),
      new Promise((resolve) => setTimeout(resolve, 5000)),
    ]);
  } catch {
    // Terminate the local child if graceful shutdown was unavailable.
  }
  if (backend.exitCode === null) backend.kill();
  backendLog?.end();
}

app.whenReady().then(async () => {
  if (!app.requestSingleInstanceLock()) {
    app.quit();
    return;
  }
  app.on("second-instance", () => {
    const window = BrowserWindow.getAllWindows()[0];
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });
  try {
    await createWindow();
  } catch (error) {
    dialog.showErrorBox("Autonomous Browser Agent failed to start", error.message);
    await stopBackend();
    app.quit();
  }
});

app.on("before-quit", (event) => {
  if (!shuttingDown && backend && backend.exitCode === null) {
    event.preventDefault();
    stopBackend().finally(() => app.quit());
  }
});

app.on("window-all-closed", () => app.quit());
