/** Exposed by `apps/desktop/preload.mjs` when inside the Electron shell. */
export {};

declare global {
  interface Window {
    fridayDesktop?: {
      platform: string;
    };
  }
}
