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

"""FastAPI Server for GCP Spot Capacity & Quant Grid Advisor Dashboard."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from spot_engine import (
    DEFAULT_PROJECT,
    DEFAULT_SELECTED_FAMILIES,
    REGION_CATALOG,
    SPOT_UNSUPPORTED_SERIES,
    get_live_inventory,
    run_fleet_scan,
    run_pecking_order_drilldown,
)

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "frontend" / "dist"
SCANNER_SCRIPT_PATH = BASE_DIR / "spot_advisor_scanner.py"

app = FastAPI(
    title="GCP Spot Capacity & Quant Grid Advisor",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _warmup_inventory() -> None:
    if DEFAULT_PROJECT:
        threading.Thread(
            target=get_live_inventory, args=(DEFAULT_PROJECT, False), daemon=True
        ).start()


class ScanRequest(BaseModel):
    project: str = Field(default=DEFAULT_PROJECT)
    regions: list[str] = Field(
        default_factory=lambda: [
            r["id"] for r in REGION_CATALOG if r["default_selected"]
        ]
    )
    families: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SELECTED_FAMILIES)
    )
    per_zone_unlock: bool = Field(default=True)
    min_score: float = Field(default=0.5, ge=0.1, le=0.95)
    shape_profile: str = Field(default="standard")
    force_refresh: bool = Field(default=False)


@app.get("/api/catalog")
def api_catalog(
    project: str = Query(default=DEFAULT_PROJECT),
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    script_source = (
        SCANNER_SCRIPT_PATH.read_text(encoding="utf-8")
        if SCANNER_SCRIPT_PATH.exists()
        else ""
    )
    eff_project = project.strip() or DEFAULT_PROJECT
    inv = get_live_inventory(eff_project, force_refresh=refresh)
    ordered_families = []
    for f in sorted(inv["families"].values(), key=lambda x: x["default_rank"]):
        lean_shapes = [
            {
                "type": sh["type"],
                "vcpus": sh["vcpus"],
                "memory_gb": sh["memory_gb"],
                "shape_class": sh.get("shape_class", "standard"),
            }
            for sh in f["shapes"]
        ]
        ordered_families.append({**f, "shapes": lean_shapes})

    return {
        "default_project": DEFAULT_PROJECT,
        "default_families": DEFAULT_SELECTED_FAMILIES,
        "inventory_live": inv["live"],
        "stats": inv["stats"],
        "regions": inv["regions"],
        "families": ordered_families,
        "spot_unsupported_series": SPOT_UNSUPPORTED_SERIES,
        "cli_script": script_source,
        "links": {
            "spot_advisor_docs": "https://cloud.google.com/compute/docs/instances/view-vm-availability",
            "bulk_insert_docs": "https://cloud.google.com/compute/docs/instances/create-vms-in-bulk",
            "spot_docs": "https://cloud.google.com/compute/docs/instances/spot",
            "anywhere_cache_docs": "https://cloud.google.com/storage/docs/anywhere-cache",
        },
    }


@app.post("/api/scan")
def api_scan(req: ScanRequest) -> dict[str, Any]:
    proj = req.project.strip() or DEFAULT_PROJECT
    if not proj:
        raise HTTPException(
            status_code=400,
            detail="Set a GCP Project ID in the top header (or export GOOGLE_CLOUD_PROJECT) before scanning.",
        )
    if not req.regions:
        raise HTTPException(status_code=400, detail="Select at least one region.")
    if not req.families:
        raise HTTPException(status_code=400, detail="Select at least one family.")
    try:
        return run_fleet_scan(
            project=proj,
            regions=req.regions,
            families=req.families,
            per_zone_unlock=req.per_zone_unlock,
            min_score=req.min_score,
            shape_profile=req.shape_profile,
            force_refresh=req.force_refresh,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/pecking-order")
def api_pecking_order(
    region: str = Query(...),
    family: str = Query(...),
    project: str = Query(default=DEFAULT_PROJECT),
    min_score: float = Query(default=0.5),
    shape_profile: str = Query(default="standard"),
    machine_type: str | None = Query(default=None),
) -> dict[str, Any]:
    proj = project.strip() or DEFAULT_PROJECT
    if not proj:
        raise HTTPException(
            status_code=400,
            detail="Set a GCP Project ID before running a pecking-order drilldown.",
        )
    inv = get_live_inventory(proj)
    fam = family.upper()
    if fam not in inv["families"]:
        raise HTTPException(status_code=400, detail=f"Unknown family: {fam}")
    try:
        return run_pecking_order_drilldown(
            project=proj,
            region_id=region,
            family_id=fam,
            min_score=min_score,
            shape_profile=shape_profile,
            machine_type=machine_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


if DIST_DIR.exists():
    assets_dir = DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str) -> FileResponse:
        candidate = DIST_DIR / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(
            str(DIST_DIR / "index.html"),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
