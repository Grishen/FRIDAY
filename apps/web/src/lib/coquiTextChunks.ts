/**
 * Split prose for hosted XTTS (English ~250 char practical limit).
 * Mirrors backend `chunk_xtts_english` loosely for deterministic client chunking.
 */
const ws = /\s+/g;

function burst(blob: string, maxChars: number): string[] {
  if (blob.length <= maxChars) return blob ? [blob] : [];
  const bits: string[] = [];
  let acc = "";
  for (const w of blob.split(" ")) {
    const tentative = acc ? `${acc} ${w}` : w;
    if (tentative.length <= maxChars) acc = tentative;
    else {
      if (acc) bits.push(acc);
      acc = w;
    }
  }
  if (acc) bits.push(acc);
  return bits;
}

export function chunkXttsEnglish(text: string, maxChars = 240): string[] {
  const normalized = text.replace(ws, " ").trim();
  if (!normalized) return [];

  const paragraphs = normalized
    .split(". ")
    .map((p) => p.trim())
    .filter(Boolean);
  if (!paragraphs.length) return normalized.length <= maxChars ? [normalized] : burst(normalized, maxChars);

  const buckets: string[] = [];
  let current = "";
  for (const p of paragraphs) {
    const piece = p.endsWith(".") ? p : `${p}.`;
    if (current.length + piece.length + (current ? 1 : 0) <= maxChars) {
      current = current ? `${current} ${piece}` : piece;
    } else {
      if (current) buckets.push(...burst(current, maxChars));
      current = piece;
    }
  }
  if (current) buckets.push(...burst(current, maxChars));
  return buckets.filter(Boolean);
}
