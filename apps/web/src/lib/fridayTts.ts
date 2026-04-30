/** Browser TTS for FRIDAY replies (Web Speech API). */

export function speakFriday(text: string, onEnd?: () => void): void {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(clean);
  u.rate = 1;
  u.pitch = 1;
  if (onEnd) {
    u.onend = () => {
      window.setTimeout(() => onEnd(), 0);
    };
  }
  window.speechSynthesis.speak(u);
}

export function stopFridaySpeech(): void {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
}
