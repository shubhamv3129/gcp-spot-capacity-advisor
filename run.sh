#!/usr/bin/env bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PORT="${PORT:-8585}"

if [[ -z "${GOOGLE_CLOUD_PROJECT:-}" ]] && command -v gcloud >/dev/null 2>&1; then
  DETECTED_PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
  if [[ -n "$DETECTED_PROJECT" && "$DETECTED_PROJECT" != "(unset)" ]]; then
    export GOOGLE_CLOUD_PROJECT="$DETECTED_PROJECT"
  fi
fi

echo "==> GCP Spot Capacity & Quant Grid Advisor"
echo "    Project : ${GOOGLE_CLOUD_PROJECT:-(not set — enter in UI or export GOOGLE_CLOUD_PROJECT)}"
echo "    Port    : http://127.0.0.1:${PORT}"

if [[ ! -d ".venv" ]]; then
  echo "==> Creating Python virtual environment (.venv)..."
  python3 -m venv .venv
fi

echo "==> Installing Python dependencies..."
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if [[ ! -f "frontend/dist/index.html" ]]; then
  echo "==> Building React UI (frontend/dist)..."
  (cd frontend && npm install && npm run build)
fi

echo "==> Starting FastAPI dashboard at http://127.0.0.1:${PORT}"
exec .venv/bin/uvicorn app:app --host 0.0.0.0 --port "$PORT"
