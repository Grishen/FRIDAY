/**
 * Minimal preload — safe bridge for future clipboard / capture APIs.
 */
import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("fridayDesktop", {
  platform: process.platform,
});
