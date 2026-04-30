/** Soft wake heuristic: strip leading "Friday" / "Friday," so Web Speech transcripts act like a lightweight wake cue. */

export function stripFridayWakePrefix(text: string): string {
  let t = text.replace(/\s+/g, " ").trim();
  t = t.replace(/^friday[,:]?\s+/i, "");
  return t.trim();
}
