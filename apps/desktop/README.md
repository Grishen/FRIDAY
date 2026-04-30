# FRIDAY desktop shell (Phase 8)

Lightweight **[Electron](https://www.electronjs.org/)** host for the **`apps/web`** Next.js assistant. The packaged window loads the UI from **`http://127.0.0.1:3000`** by default so you can keep using `next dev` with hot reload.

Future work (not in this slice): global hotkey, tray, screen/window capture, and native context bridges — all behind the same API with audit hooks (see product vision).

## Prerequisites

- Node 20+
- **`apps/web`** running (`npm run dev`) unless you point to another URL

## Install

```bash
cd apps/desktop
npm install
```

## Run

In one terminal, start the web app:

```bash
cd apps/web && npm run dev
```

In another:

```bash
cd apps/desktop && npm run dev
```

### Custom origin

If the UI runs elsewhere (e.g. another port or deployed preview):

```bash
FRIDAY_WEB_URL=http://127.0.0.1:3001 npm run dev
```

Environment variable **`FRIDAY_WEB_URL`** overrides the default.

Before opening the Electron window, the shell **polls until the UI answers HTTP**. If Next.js is not running (or wrong port), you get a dialog instead of an empty window:

> “Could not reach the web UI” — start **`cd apps/web && npm run dev`** first.

Advanced: **`FRIDAY_WAIT_SERVER_MS=0`** skips the readiness poll (defaults to **`120000`** ms).

### Troubleshooting empty window / nothing loads

1. **`npm run dev` in `apps/web`** — must be reachable at the URL Electron uses (**`127.0.0.1:3000`** by default).
2. Watch **stderr**: lines like **`waiting for UI at …`** mean the desktop app is polling; once Next is up, it loads automatically.

## Embed bridge

Electron **`preload`** exposes `window.fridayDesktop = { platform }`. The Next root layout renders a **`Desktop shell`** badge when `fridayDesktop` is present (`apps/web`).

## Security

Electron is pinned to a **maintained minor** (`^41.3.x` as of Phase 8) so `npm audit` stays clean against known Electron CVEs. Bump with `npm install electron@latest --save-dev` when you adopt a new baseline.

## Packaging (optional later)

Electron Builder / Forge can wrap this crate for installers; omitted here to avoid heavy CI coupling.
