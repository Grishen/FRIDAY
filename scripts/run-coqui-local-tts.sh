#!/usr/bin/env bash
# Local Coqui TTS sidecar for FRIDAY. Use a dedicated venv with PyTorch + Coqui TTS installed.
#
# Typical setup:
#   cd services/coqui-local-tts
#   python3.11 -m venv .venv && source .venv/bin/activate
#   pip install -U pip wheel
#   # Install PyTorch for your platform (CPU or CUDA): https://pytorch.org/
#   pip install torch torchaudio
#   pip install -e "."
#   pip install 'TTS @ git+https://github.com/coqui-ai/TTS.git'
#   # or: pip install -e /path/to/your/TTS-checkout
#
# Env (minimum for the sidecar process):
#   COQUI_SPEAKER_WAV=/absolute/path/to/ref.wav   # short clean speech clip for XTTS
# Optional:
#   COQUI_LOCAL_PORT=8787
#   COQUI_XTTS_MODEL=tts_models/multilingual/multi-dataset/xtts_v2
#   COQUI_USE_GPU=false
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CDIR="$ROOT/services/coqui-local-tts"
export PYTHONPATH="${CDIR}/src:${PYTHONPATH:-}"
PORT="${COQUI_LOCAL_PORT:-8787}"
exec python -m uvicorn coqui_local_tts.app:app --host 127.0.0.1 --port "$PORT"
