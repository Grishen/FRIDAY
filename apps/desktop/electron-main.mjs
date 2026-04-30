/**
 * FRIDAY Electron shell — loads the Next.js app from a configurable origin.
 *
 * Env:
 * - FRIDAY_WEB_URL — default http://127.0.0.1:3000 (match `npm run dev` in apps/web)
 * - FRIDAY_WAIT_SERVER_MS — max time to retry connection (default 120000). Set 0 to skip wait.
 */
import { BrowserWindow, app, dialog } from "electron";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @param {unknown} detail */
function dbg(detail) {
  process.stderr.write(`${JSON.stringify({ source: "friday-desktop", detail })}\n`);
}

function desktopUrl() {
  const u = process.env.FRIDAY_WEB_URL?.trim() || "";
  return u.startsWith("http") ? u : "http://127.0.0.1:3000";
}

function waitBudgetMs() {
  const raw = process.env.FRIDAY_WAIT_SERVER_MS?.trim();
  if (raw === "0") return 0;
  const n = raw ? Number.parseInt(raw, 10) : 120000;
  return Number.isFinite(n) && n >= 0 ? n : 120000;
}

/** @param {string} urlStr */
function checkReachable(urlStr) {
  return new Promise((resolve) => {
    let u;
    try {
      u = new URL(urlStr);
    } catch {
      resolve(false);
      return;
    }
    const lib = u.protocol === "https:" ? https : http;
    const port = u.port ? Number(u.port) : u.protocol === "https:" ? 443 : 80;
    const req = lib.request(
      {
        hostname: u.hostname,
        port,
        method: "GET",
        path: `${u.pathname || "/"}${u.search || ""}`,
        timeout: 2500,
        headers: { Accept: "text/html", Connection: "close" },
      },
      (res) => {
        res.resume();
        resolve(res.statusCode !== undefined && res.statusCode < 500);
      },
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
    req.end();
  });
}

/**
 * Poll until the dev server answers (avoids a blank window on ERR_CONNECTION_REFUSED).
 * @param {string} urlStr
 */
async function waitForServer(urlStr) {
  const maxWaitMs = waitBudgetMs();
  if (maxWaitMs === 0) {
    dbg("skipping dev server wait (FRIDAY_WAIT_SERVER_MS=0)");
    return;
  }
  const start = Date.now();
  let lastLog = 0;
  while (Date.now() - start < maxWaitMs) {
    if (await checkReachable(urlStr)) {
      dbg(`dev server ready at ${urlStr}`);
      return;
    }
    const elapsed = Math.round((Date.now() - start) / 1000);
    if (Date.now() - lastLog > 2000) {
      dbg(`waiting for UI at ${urlStr} (${elapsed}s) — run: cd apps/web && npm run dev`);
      lastLog = Date.now();
    }
    await new Promise((r) => setTimeout(r, 750));
  }
  throw new Error(`Not reachable within ${maxWaitMs}ms`);
}

/** @returns {Electron.BrowserWindow} */
function createWindow(loadUrl) {
  const win = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#09090b",
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    webPreferences: {
      preload: path.join(__dirname, "preload.mjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.webContents.on("did-fail-load", (event, errorCode, errorDescription, validatedURL) => {
    dbg({ did_fail_load: { errorCode, errorDescription, validatedURL } });
    if (errorCode === -106) {
      dbg({ hint: "ERR_INTERNET_DISCONNECTED — check FRIDAY_WEB_URL and that the UI process is listening" });
    }
    if (errorCode === -102) {
      dbg({ hint: "ERR_CONNECTION_REFUSED — start apps/web (npm run dev) or fix the port" });
    }
  });

  win.loadURL(loadUrl).catch((err) => {
    dbg({ load_error: String(err), hint: "Start apps/web with npm run dev, or set FRIDAY_WEB_URL" });
  });

  win.webContents.setWindowOpenHandler(() => ({
    action: "deny",
  }));

  return win;
}

async function waitAndOpenWindow(quitsAppIfUnreachable) {
  const url = desktopUrl();
  try {
    await waitForServer(url);
  } catch (e) {
    dbg({ wait_failed: String(e), url });
    await dialog.showMessageBox({
      type: "error",
      title: "FRIDAY Desktop",
      message: "Could not reach the web UI",
      detail:
        `Nothing is responding at:\n${url}\n\n` +
        "Start Next.js first, then reopen the desktop shell:\n" +
        "  cd apps/web && npm run dev\n\n" +
        "Or point FRIDAY_WEB_URL at a running server.\n\n" +
        "(Use FRIDAY_WAIT_SERVER_MS=0 to skip this check.)",
    });
    if (quitsAppIfUnreachable) {
      app.quit();
    }
    return;
  }
  createWindow(url);
}

app.whenReady().then(async () => {
  await waitAndOpenWindow(true);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void waitAndOpenWindow(false);
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
