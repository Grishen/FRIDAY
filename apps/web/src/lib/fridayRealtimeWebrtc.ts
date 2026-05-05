import { apiBase } from "@/lib/config";

/** Browser WebRTC + OpenAI Realtime unified SDP exchange (dual audio path). */
export async function negotiateFridayRealtimeDuplex(params: {
  sessionId: string;
  userId: string;
}): Promise<{
  pc: RTCPeerConnection;
  dataChannel: RTCDataChannel;
  stopTracks: () => void;
}> {
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });

  if (typeof document !== "undefined") {
    const el = document.createElement("audio");
    el.autoplay = true;
    pc.ontrack = (ev) => {
      el.srcObject = ev.streams[0];
    };
  }

  const dc = pc.createDataChannel("oai-events", { ordered: true });

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, noiseSuppression: true, echoCancellation: true },
  });
  stream.getTracks().forEach((t) => pc.addTrack(t, stream));

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  /** Prefer `offer.sdp` — `localDescription` can lag or be empty in some browsers right after setLocalDescription. */
  const sdpPayload = typeof offer.sdp === "string" && offer.sdp.length > 0 ? offer.sdp : (pc.localDescription?.sdp ?? "");
  if (!sdpPayload.trim()) {
    stream.getTracks().forEach((t) => t.stop());
    pc.close();
    throw new Error("WebRTC offer SDP empty — microphone or peer connection unavailable.");
  }

  const resp = await fetch(`${apiBase}/api/v1/sessions/${encodeURIComponent(params.sessionId)}/realtime/webrtc`, {
    method: "POST",
    headers: {
      "Content-Type": "application/sdp",
      Accept: "application/sdp,text/plain;q=0.9,*/*;q=0.8",
      "X-User-Id": params.userId,
    },
    body: sdpPayload,
  });

  const answerText = await resp.text();
  if (!resp.ok) {
    stream.getTracks().forEach((t) => t.stop());
    pc.close();
    throw new Error(answerText.trim() ? answerText.trim().slice(0, 640) : `webrtc sdp exchange failed (${resp.status})`);
  }

  await pc.setRemoteDescription({ type: "answer", sdp: answerText });

  const stopTracks = (): void => {
    stream.getTracks().forEach((t) => t.stop());
  };

  return { pc, dataChannel: dc, stopTracks };
}
