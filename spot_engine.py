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

"""Spot Capacity & Grid Advisor Engine for GCP Compute Engine.

Implements:
1. Live GCE dynamic inventory discovery across all 43+ GCP regions, 130+ zones,
   and all 34 Spot-supported Compute Engine VM families (plus all non-metal
   shape classes: standard, highmem, highcpu, lssd, ultramem/megamem, gpu).
2. Top-Down Max-Shape Pecking-Order API strategy to bypass the 1,000-VM Spot
   Advisor console/API cap (with explicit host-pool overlap guardrails).
3. Per-Zone Independent Binary Search (1..1000 VMs per zone) across zones that
   actually support each machine shape to unlock multi-thousand-VM regional pools.
4. Live 30-day Spot preemption rate & multi-month floating Spot price history
   via POST /compute/beta/projects/{project}/regions/{region}/advice/capacityHistory.
"""

from __future__ import annotations

import concurrent.futures
import os
import shutil
import subprocess
import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from cloud_pricing import (
    CLOUD_REGION_MAP,
    AZURE_SERIES_TO_SKUS,
    _azure_series_ladder,
    enrich_pools_with_multicloud_spot,
    get_aws_live_spot_data,
    prefetch_azure_spot_prices,
)

GCLOUD_BIN = os.environ.get("GCLOUD_BIN") or shutil.which("gcloud") or "gcloud"


def _detect_default_project() -> str:
    env_proj = (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCLOUD_PROJECT")
        or ""
    ).strip()
    if env_proj:
        return env_proj
    try:
        import google.auth

        _, proj = google.auth.default()
        if proj:
            return str(proj).strip()
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            [GCLOUD_BIN, "config", "get-value", "project"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        if out and out != "(unset)":
            return out
    except Exception:
        pass
    return ""


DEFAULT_PROJECT = _detect_default_project()
COMPUTE_V1_BASE = "https://compute.googleapis.com/compute/v1"
COMPUTE_BETA_BASE = "https://compute.googleapis.com/compute/beta"

# Thread-local keep-alive HTTP sessions for high concurrency scans.
_thread_local = threading.local()

# Token cache to avoid spawning gcloud on every concurrent thread.
_token_lock = threading.Lock()
_cached_token: str | None = None
_token_expiry: float = 0.0

# Live inventory cache (regions, zones, machineTypes).
_inventory_lock = threading.Lock()
_inventory_cache: dict[str, tuple[float, dict[str, Any]]] = {}
INVENTORY_TTL_SECONDS = 1800.0

# Scan result cache keyed by parameters for snappy UI interactions.
_scan_cache_lock = threading.Lock()
_scan_cache: dict[str, tuple[float, dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 300.0

# Bare-metal-only & TPU machine series rejected by Spot / Advice API.
SPOT_UNSUPPORTED_SERIES: dict[str, str] = {
    "X4": "Bare-metal only (megamem-metal) — Spot VMs not supported",
    "X5": "Bare-metal only (SAP/memory metal) — Spot VMs not supported",
    "A4X": "GB200/GB300 NVL — Spot / Capacity Advice API not supported",
    "CT3": "Cloud TPU v3 — Spot Advice API not supported",
    "CT3P": "Cloud TPU v3 Pod — Spot Advice API not supported",
    "CT5L": "Cloud TPU v5e — Spot Advice API not supported",
    "CT5LP": "Cloud TPU v5e Pod — Spot Advice API not supported",
    "CT5P": "Cloud TPU v5p — Spot Advice API not supported",
    "CT6E": "Cloud TPU v6e (Trillium) — Spot Advice API not supported",
    "TPU7": "Cloud TPU v7 — Spot Advice API not supported",
    "TPU7X": "Cloud TPU v7x — Spot Advice API not supported",
}

DEFAULT_SELECTED_REGIONS = {
    "asia-southeast1",
    "asia-northeast1",
    "asia-northeast2",
    "asia-east1",
    "asia-south1",
    "australia-southeast1",
    "europe-west4",
    "europe-west1",
}

DEFAULT_SELECTED_FAMILIES = ["N4", "C4D", "C4", "N2D", "C3D", "N2"]

# Complete metadata across all 43 live GCP regions.
_REGION_METADATA: dict[str, dict[str, Any]] = {
    # APAC (12)
    "asia-southeast1": {
        "city": "Singapore",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["asia-southeast1-a", "asia-southeast1-b", "asia-southeast1-c"],
        "note": "Matches AWS ap-southeast-1 APAC footprint",
    },
    "asia-northeast1": {
        "city": "Tokyo",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["asia-northeast1-a", "asia-northeast1-b", "asia-northeast1-c"],
        "note": "Major APAC low-preemption compute hub",
    },
    "asia-northeast2": {
        "city": "Osaka",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["asia-northeast2-a", "asia-northeast2-b", "asia-northeast2-c"],
        "note": "Secondary Japan region with strong Spot diversity",
    },
    "asia-northeast3": {
        "city": "Seoul",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["asia-northeast3-a", "asia-northeast3-b", "asia-northeast3-c"],
        "note": "APAC compute & low-latency Korea hub",
    },
    "asia-east1": {
        "city": "Taiwan",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["asia-east1-a", "asia-east1-b", "asia-east1-c"],
        "note": "Deepest East Asia multi-family compute pool",
    },
    "asia-east2": {
        "city": "Hong Kong",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["asia-east2-a", "asia-east2-b", "asia-east2-c"],
        "note": "APAC financial markets hub",
    },
    "asia-south1": {
        "city": "Mumbai",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["asia-south1-a", "asia-south1-b", "asia-south1-c"],
        "note": "India primary region",
    },
    "asia-south2": {
        "city": "Delhi",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["asia-south2-a", "asia-south2-b", "asia-south2-c"],
        "note": "India NCR secondary region",
    },
    "asia-southeast2": {
        "city": "Jakarta",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["asia-southeast2-a", "asia-southeast2-b", "asia-southeast2-c"],
        "note": "ASEAN expansion region",
    },
    "asia-southeast3": {
        "city": "Bangkok",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["asia-southeast3-a", "asia-southeast3-b", "asia-southeast3-c"],
        "note": "ASEAN Mainland region (newest APAC capacity)",
    },
    "australia-southeast1": {
        "city": "Sydney",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["australia-southeast1-a", "australia-southeast1-b", "australia-southeast1-c"],
        "note": "APAC counter-cyclical timezone window",
    },
    "australia-southeast2": {
        "city": "Melbourne",
        "geo": "APAC",
        "subgeo": "APAC",
        "zones": ["australia-southeast2-a", "australia-southeast2-b", "australia-southeast2-c"],
        "note": "Secondary ANZ region",
    },
    # EMEA - Europe (13), Middle East (3), Africa (1)
    "europe-west4": {
        "city": "Netherlands",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-west4-a", "europe-west4-b", "europe-west4-c", "europe-west4-ai1a"],
        "note": "Flagship EU compute & GCS bandwidth hub",
    },
    "europe-west1": {
        "city": "Belgium",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-west1-b", "europe-west1-c", "europe-west1-d"],
        "note": "Large multi-family EU Spot pool",
    },
    "europe-west2": {
        "city": "London",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-west2-a", "europe-west2-b", "europe-west2-c"],
        "note": "UK financial markets hub",
    },
    "europe-west3": {
        "city": "Frankfurt",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-west3-a", "europe-west3-b", "europe-west3-c"],
        "note": "Central European financial hub",
    },
    "europe-west6": {
        "city": "Zurich",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-west6-a", "europe-west6-b", "europe-west6-c"],
        "note": "Switzerland sovereign/financial region",
    },
    "europe-west8": {
        "city": "Milan",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-west8-a", "europe-west8-b", "europe-west8-c"],
        "note": "Southern Europe region",
    },
    "europe-west9": {
        "city": "Paris",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-west9-a", "europe-west9-b", "europe-west9-c"],
        "note": "France compute region",
    },
    "europe-west10": {
        "city": "Berlin",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-west10-a", "europe-west10-b", "europe-west10-c"],
        "note": "Germany secondary compute hub",
    },
    "europe-west12": {
        "city": "Turin",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-west12-a", "europe-west12-b", "europe-west12-c"],
        "note": "Italy secondary compute hub",
    },
    "europe-north1": {
        "city": "Finland",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-north1-a", "europe-north1-b", "europe-north1-c"],
        "note": "Cool-climate EU batch/HPC region",
    },
    "europe-north2": {
        "city": "Stockholm",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-north2-a", "europe-north2-b", "europe-north2-c"],
        "note": "Nordic clean-energy compute hub",
    },
    "europe-central2": {
        "city": "Warsaw",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-central2-a", "europe-central2-b", "europe-central2-c"],
        "note": "Eastern Europe compute hub",
    },
    "europe-southwest1": {
        "city": "Madrid",
        "geo": "EMEA",
        "subgeo": "Europe",
        "zones": ["europe-southwest1-a", "europe-southwest1-b", "europe-southwest1-c"],
        "note": "Iberian compute hub",
    },
    "me-central1": {
        "city": "Doha",
        "geo": "EMEA",
        "subgeo": "Middle East",
        "zones": ["me-central1-a", "me-central1-b", "me-central1-c"],
        "note": "Middle East compute region",
    },
    "me-central2": {
        "city": "Dammam",
        "geo": "EMEA",
        "subgeo": "Middle East",
        "zones": ["me-central2-a", "me-central2-b", "me-central2-c"],
        "note": "Saudi Arabia compute region",
    },
    "me-west1": {
        "city": "Tel Aviv",
        "geo": "EMEA",
        "subgeo": "Middle East",
        "zones": ["me-west1-a", "me-west1-b", "me-west1-c"],
        "note": "Eastern Mediterranean compute region",
    },
    "africa-south1": {
        "city": "Johannesburg",
        "geo": "EMEA",
        "subgeo": "Africa",
        "zones": ["africa-south1-a", "africa-south1-b", "africa-south1-c"],
        "note": "South Africa regional compute hub",
    },
    # AMER - US (9), North America Non-US (3), South America (2)
    "us-central1": {
        "city": "Iowa",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["us-central1-a", "us-central1-b", "us-central1-c", "us-central1-f"],
        "note": "High-capacity US mega-region (watch peak Q4 enterprise demand)",
    },
    "us-east1": {
        "city": "South Carolina",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["us-east1-b", "us-east1-c", "us-east1-d"],
        "note": "Large US East batch/compute mega-region",
    },
    "us-east4": {
        "city": "Northern Virginia",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["us-east4-a", "us-east4-b", "us-east4-c"],
        "note": "Primary US East enterprise & financial hub",
    },
    "us-east5": {
        "city": "Columbus",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["us-east5-a", "us-east5-b", "us-east5-c"],
        "note": "US Midwest capacity & Chicago-corridor proximity",
    },
    "us-south1": {
        "city": "Dallas",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["us-south1-a", "us-south1-b", "us-south1-c", "us-south1-ai1b"],
        "note": "US South compute & AI region",
    },
    "us-west1": {
        "city": "Oregon",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["us-west1-a", "us-west1-b", "us-west1-c"],
        "note": "Flagship US West low-carbon compute mega-region",
    },
    "us-west2": {
        "city": "Los Angeles",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["us-west2-a", "us-west2-b", "us-west2-c"],
        "note": "Southern California metro region",
    },
    "us-west3": {
        "city": "Salt Lake City",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["us-west3-a", "us-west3-b", "us-west3-c"],
        "note": "US Mountain West region",
    },
    "us-west4": {
        "city": "Las Vegas",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["us-west4-a", "us-west4-b", "us-west4-c"],
        "note": "US Southwest capacity expansion hub",
    },
    "northamerica-northeast1": {
        "city": "Montreal",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["northamerica-northeast1-a", "northamerica-northeast1-b", "northamerica-northeast1-c"],
        "note": "Canada East hydro-powered region",
    },
    "northamerica-northeast2": {
        "city": "Toronto",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["northamerica-northeast2-a", "northamerica-northeast2-b", "northamerica-northeast2-c"],
        "note": "Canadian financial center region",
    },
    "northamerica-south1": {
        "city": "Mexico (Queretaro)",
        "geo": "AMER",
        "subgeo": "North America",
        "zones": ["northamerica-south1-a", "northamerica-south1-b", "northamerica-south1-c"],
        "note": "Latin America North capacity hub",
    },
    "southamerica-east1": {
        "city": "Sao Paulo",
        "geo": "AMER",
        "subgeo": "South America",
        "zones": ["southamerica-east1-a", "southamerica-east1-b", "southamerica-east1-c"],
        "note": "South America East financial/batch hub",
    },
    "southamerica-west1": {
        "city": "Santiago",
        "geo": "AMER",
        "subgeo": "South America",
        "zones": ["southamerica-west1-a", "southamerica-west1-b", "southamerica-west1-c"],
        "note": "South America Pacific region",
    },
}


def _infer_region_meta(region_id: str, live_zones: list[str] | None = None) -> dict[str, Any]:
    meta = _REGION_METADATA.get(region_id)
    if meta:
        city = meta["city"]
        geo = meta["geo"]
        subgeo = meta["subgeo"]
        zones = sorted(live_zones) if live_zones else meta["zones"]
        note = meta["note"]
    else:
        city = region_id
        if region_id.startswith(("asia-", "australia-")):
            geo, subgeo = "APAC", "APAC"
        elif region_id.startswith(("europe-",)):
            geo, subgeo = "EMEA", "Europe"
        elif region_id.startswith(("me-",)):
            geo, subgeo = "EMEA", "Middle East"
        elif region_id.startswith(("africa-",)):
            geo, subgeo = "EMEA", "Africa"
        elif region_id.startswith(("southamerica-",)):
            geo, subgeo = "AMER", "South America"
        else:
            geo, subgeo = "AMER", "North America"
        zones = sorted(live_zones) if live_zones else []
        note = f"GCP {subgeo} region"

    return {
        "id": region_id,
        "label": f"{city} ({region_id})",
        "geo": geo,
        "subgeo": subgeo,
        "zones": zones,
        "default_selected": region_id in DEFAULT_SELECTED_REGIONS,
        "note": note,
    }


REGION_CATALOG: list[dict[str, Any]] = [
    _infer_region_meta(rid) for rid in _REGION_METADATA
]
REGION_MAP: dict[str, dict[str, Any]] = {r["id"]: r for r in REGION_CATALOG}


def _make_family(
    fid: str,
    name: str,
    category: str,
    arch: str,
    aws_mapping: str,
    lifecycle: str,
    lifecycle_label: str,
    lifecycle_note: str,
    default_rank: int,
    shapes: list[tuple[str, int, float]],
) -> dict[str, Any]:
    return {
        "id": fid,
        "name": name,
        "category": category,
        "arch": arch,
        "aws_mapping": aws_mapping,
        "lifecycle": lifecycle,
        "lifecycle_label": lifecycle_label,
        "lifecycle_note": lifecycle_note,
        "default_rank": default_rank,
        "default_selected": fid in DEFAULT_SELECTED_FAMILIES,
        "shapes": [
            {
                "type": t,
                "vcpus": v,
                "memory_gb": m,
                "shape_class": _classify_shape(t),
            }
            for t, v, m in shapes
        ],
    }


def _classify_shape(name: str) -> str:
    low = name.lower()
    if "-metal" in low:
        return "metal"
    if any(k in low for k in ("-highgpu", "-ultragpu", "-megagpu", "-edgegpu")):
        return "gpu"
    if any(k in low for k in ("-ultramem", "-megamem", "-hypermem")):
        return "highmem"
    if "-lssd" in low or "standardlssd" in low or "highlssd" in low:
        return "lssd"
    if "-highmem" in low:
        return "highmem"
    if "-highcpu" in low:
        return "highcpu"
    return "standard"


# All 34 Spot-supported Compute Engine VM families across all categories.
FAMILY_CATALOG: dict[str, dict[str, Any]] = {
    f["id"]: f
    for f in [
        _make_family(
            "N4",
            "N4 (Intel Emerald Rapids — Balanced)",
            "General Purpose",
            "x86_64 Intel",
            "m7i.16xlarge / m7i.24xlarge / c7i.24xlarge",
            "RECOMMENDED",
                        "Current-Gen Primary",
            "Strong balanced price-performance & modern Intel Xeon generation. Primary anchor for CUD + Spot tiers.",
            1,
            [
                ("n4-standard-80", 80, 320),
                ("n4-standard-64", 64, 256),
                ("n4-standard-48", 48, 192),
                ("n4-standard-32", 32, 128),
                ("n4-highmem-80", 80, 640),
                ("n4-highcpu-80", 80, 160),
            ],
        ),
        _make_family(
            "C4D",
            "C4D (AMD EPYC Turin — Compute-Optimized)",
            "Compute-Optimized",
            "x86_64 AMD",
            "c7a.48xlarge / c8a.48xlarge / m7a.48xlarge",
            "RECOMMENDED",
                        "High-Density Grid",
            "Up to 384 vCPUs/VM (AMD EPYC Turin) — yields up to 384k vCPUs per 1,000-VM Capacity Advice API query.",
            2,
            [
                ("c4d-standard-384", 384, 1488),
                ("c4d-standard-192", 192, 744),
                ("c4d-standard-96", 96, 372),
                ("c4d-standard-64", 64, 248),
                ("c4d-highmem-384", 384, 2976),
                ("c4d-highcpu-384", 384, 744),
            ],
        ),
        _make_family(
            "C4",
            "C4 (Intel Granite Rapids — Compute-Optimized)",
            "Compute-Optimized",
            "x86_64 Intel",
            "c7i.48xlarge / m7i.48xlarge",
            "RECOMMENDED",
                        "Compute-Optimized",
            "Up to 288 vCPUs/VM (Intel Granite Rapids). High single-thread throughput available across 40+ regions.",
            3,
            [
                ("c4-standard-288", 288, 1080),
                ("c4-standard-192", 192, 720),
                ("c4-standard-96", 96, 360),
                ("c4-standard-48", 48, 180),
                ("c4-highmem-288", 288, 2232),
                ("c4-highcpu-288", 288, 576),
            ],
        ),
        _make_family(
            "N2D",
            "N2D (AMD EPYC Milan — General Purpose)",
            "General Purpose",
            "x86_64 AMD",
            "m6a.48xlarge / c6a.48xlarge",
            "DIVERSIFICATION",
                        "Spot Diversification",
            "Deep multi-region AMD EPYC Milan Spot capacity for high-concurrency burst diversification alongside N4 and C4D.",
            4,
            [
                ("n2d-standard-224", 224, 896),
                ("n2d-standard-128", 128, 512),
                ("n2d-standard-96", 96, 384),
                ("n2d-standard-80", 80, 320),
                ("n2d-highmem-96", 96, 768),
                ("n2d-highcpu-224", 224, 224),
            ],
        ),
        _make_family(
            "C3D",
            "C3D (AMD EPYC Genoa — Compute-Optimized)",
            "Compute-Optimized",
            "x86_64 AMD",
            "c7a.36xlarge / m7a.36xlarge",
            "DIVERSIFICATION",
                        "Secondary Overflow",
            "High core-count (360 vCPU) AMD EPYC Genoa overflow option for instanceFlexibilityPolicy when primary pools saturate.",
            5,
            [
                ("c3d-standard-360", 360, 1440),
                ("c3d-standard-180", 180, 720),
                ("c3d-standard-90", 90, 360),
                ("c3d-standard-60", 60, 240),
            ],
        ),
        _make_family(
            "N2",
            "N2 (Intel Cascade/Ice Lake — General Purpose)",
            "General Purpose",
            "x86_64 Intel",
            "m6i.32xlarge / c6i.32xlarge",
            "LEGACY",
                        "Previous Gen",
            "Previous-generation Intel fleet; newer deployments are recommended to standardize on N4/C4 for better price-performance.",
            6,
            [
                ("n2-standard-128", 128, 512),
                ("n2-standard-96", 96, 384),
                ("n2-standard-80", 80, 320),
                ("n2-standard-64", 64, 256),
            ],
        ),
        _make_family(
            "N4D",
            "N4D (AMD EPYC Turin — General Purpose)",
            "General Purpose",
            "x86_64 AMD",
            "m7a.24xlarge / m8a.24xlarge",
            "RECOMMENDED",
                        "New-Gen AMD Balanced",
            "New-generation AMD EPYC Turin balanced VMs (up to 96 vCPUs) across general-purpose regional deployments.",
            7,
            [
                ("n4d-standard-96", 96, 384),
                ("n4d-standard-80", 80, 320),
                ("n4d-standard-64", 64, 256),
                ("n4d-standard-48", 48, 192),
            ],
        ),
        _make_family(
            "N4A",
            "N4A (Google Axion ARM64 — Balanced)",
            "General Purpose",
            "ARM64 Axion",
            "m8g.16xlarge / m7g.16xlarge",
            "RECOMMENDED",
                        "Axion ARM Balanced",
            "Google Axion ARM64 balanced general-purpose family (up to 64 vCPUs) for ARM-compiled workloads.",
            8,
            [
                ("n4a-standard-64", 64, 256),
                ("n4a-standard-48", 48, 192),
                ("n4a-standard-32", 32, 128),
            ],
        ),
        _make_family(
            "C4A",
            "C4A (Google Axion ARM64 — Compute)",
            "Compute-Optimized",
            "ARM64 Axion",
            "c8g.24xlarge / c7g.16xlarge",
            "RECOMMENDED",
                        "Axion ARM Compute",
            "Google Axion ARM64 compute-optimized VMs available across 35+ regions with compelling $/vCPU-hr economics.",
            9,
            [
                ("c4a-standard-72", 72, 288),
                ("c4a-standard-64", 64, 256),
                ("c4a-standard-48", 48, 192),
                ("c4a-standard-32", 32, 128),
            ],
        ),
        _make_family(
            "C4N",
            "C4N (Network-Optimized 200Gbps Compute)",
            "Compute-Optimized",
            "x86_64 Intel",
            "c7in.32xlarge / c7in.metal",
            "RECOMMENDED",
                        "Network-Optimized",
            "Network-optimized 4th-gen compute VMs (up to 192 vCPUs) built for high-bandwidth distributed reads.",
            10,
            [
                ("c4n-standard-192", 192, 720),
                ("c4n-standard-96", 96, 360),
                ("c4n-standard-48", 48, 180),
            ],
        ),
        _make_family(
            "C3",
            "C3 (Intel Sapphire Rapids — Compute)",
            "Compute-Optimized",
            "x86_64 Intel",
            "c7i.44xlarge / m7i.44xlarge",
            "RECOMMENDED",
                        "Enterprise Compute",
            "Intel Sapphire Rapids VMs up to 176 vCPUs/VM with consistent network and block throughput.",
            11,
            [
                ("c3-standard-176", 176, 704),
                ("c3-standard-88", 88, 352),
                ("c3-standard-44", 44, 176),
            ],
        ),
        _make_family(
            "C2D",
            "C2D (AMD EPYC Milan — Compute)",
            "Compute-Optimized",
            "x86_64 AMD",
            "c6a.24xlarge / c6a.48xlarge",
            "DIVERSIFICATION",
                        "Compute Diversification",
            "32-region AMD EPYC Milan compute family (up to 112 vCPUs) adding extra regional Spot depth.",
            12,
            [
                ("c2d-standard-112", 112, 448),
                ("c2d-standard-56", 56, 224),
                ("c2d-standard-32", 32, 128),
            ],
        ),
        _make_family(
            "C2",
            "C2 (Intel Cascade Lake — Compute)",
            "Compute-Optimized",
            "x86_64 Intel",
            "c5.18xlarge / c5.24xlarge",
            "DIVERSIFICATION",
                        "Previous-Gen Compute",
            "Previous-generation 60-vCPU compute-optimized VMs across 28 regions.",
            13,
            [
                ("c2-standard-60", 60, 240),
                ("c2-standard-30", 30, 120),
                ("c2-standard-16", 16, 64),
            ],
        ),
        _make_family(
            "H4D",
            "H4D (AMD EPYC Turin — HPC Cloud RDMA)",
            "HPC & Scale-Out",
            "x86_64 AMD",
            "hpc7a.96xlarge",
            "RECOMMENDED",
                        "HPC / Cloud RDMA",
            "192-vCPU AMD EPYC Turin HPC fleet tailored for tightly coupled simulations and Cloud RDMA.",
            14,
            [
                ("h4d-standard-192", 192, 720),
                ("h4d-highmem-192", 192, 1488),
            ],
        ),
        _make_family(
            "H3",
            "H3 (Intel Sapphire Rapids — HPC)",
            "HPC & Scale-Out",
            "x86_64 Intel",
            "hpc6id.32xlarge",
            "RECOMMENDED",
                        "HPC-Optimized",
            "88-vCPU HPC-optimized VMs tuned for batch engineering & tightly coupled workloads.",
            15,
            [("h3-standard-88", 88, 352)],
        ),
        _make_family(
            "T2D",
            "T2D (AMD EPYC Milan — Scale-Out)",
            "HPC & Scale-Out",
            "x86_64 AMD",
            "c6a.16xlarge / m6a.16xlarge",
            "DIVERSIFICATION",
                        "Scale-Out Web/Batch",
            "Scale-out 1-thread-per-vCPU AMD EPYC Milan VMs available across 39 global regions.",
            16,
            [
                ("t2d-standard-60", 60, 240),
                ("t2d-standard-48", 48, 192),
                ("t2d-standard-32", 32, 128),
            ],
        ),
        _make_family(
            "T2A",
            "T2A (Ampere Altra ARM64 — Scale-Out)",
            "HPC & Scale-Out",
            "ARM64 Ampere",
            "t4g / m6g.12xlarge",
            "DIVERSIFICATION",
                        "Legacy ARM Scale-Out",
            "Ampere Altra ARM64 VMs across select regions; newer ARM deployments typically prefer C4A/N4A.",
            17,
            [("t2a-standard-48", 48, 192), ("t2a-standard-32", 32, 128)],
        ),
        _make_family(
            "E2",
            "E2 (Cost-Optimized Multi-Arch)",
            "General Purpose",
            "x86_64 Shared/Multi",
            "m5a / t3a / m6i",
            "DIVERSIFICATION",
                        "Cost-Optimized",
            "Budget general-purpose VMs (up to 32 vCPUs) across 42 regions with dynamic CPU platform backing.",
            18,
            [
                ("e2-standard-32", 32, 128),
                ("e2-standard-16", 16, 64),
                ("e2-standard-8", 8, 32),
            ],
        ),
        _make_family(
            "N1",
            "N1 (Skylake/Broadwell — Legacy GP)",
            "General Purpose",
            "x86_64 Intel",
            "m4 / m5 / c5",
            "LEGACY",
                        "Legacy Generation",
            "First-generation general-purpose VMs (up to 96 vCPUs); newer workloads are recommended on N4/N4D.",
            19,
            [
                ("n1-standard-96", 96, 360),
                ("n1-standard-64", 64, 240),
                ("n1-standard-32", 32, 120),
            ],
        ),
        _make_family(
            "Z4D",
            "Z4D (AMD Turin + High-Speed LSSD Storage)",
            "Storage-Optimized",
            "x86_64 AMD",
            "i4i / i7ie",
            "RECOMMENDED",
                        "High-IOPS Storage VM",
            "Next-generation AMD storage-optimized VMs combining up to 384 vCPUs with local NVMe SSD tiers.",
            20,
            [
                ("z4d-highmem-384-standardlssd", 384, 3024),
                ("z4d-highmem-192-standardlssd", 192, 1512),
                ("z4d-highmem-96-standardlssd", 96, 756),
            ],
        ),
        _make_family(
            "Z4M",
            "Z4M (Titanium High-Memory Storage VM)",
            "Storage-Optimized",
            "x86_64 Intel",
            "i4i.metal / i3en",
            "RECOMMENDED",
                        "Storage-Optimized",
            "Storage-optimized VMs pairing high RAM (up to 1.5 TB) with local SSD acceleration.",
            21,
            [
                ("z4m-highmem-192-cd", 192, 1488),
                ("z4m-highmem-192", 192, 1488),
                ("z4m-highmem-48", 48, 366),
            ],
        ),
        _make_family(
            "Z3",
            "Z3 (Intel Sapphire Rapids + Titanium LSSD)",
            "Storage-Optimized",
            "x86_64 Intel",
            "i4i.32xlarge / i3en",
            "RECOMMENDED",
                        "Local NVMe Storage",
            "Titanium-offloaded Local NVMe storage VMs (up to 176 vCPUs) across 18 regions for scratch tick unpacking.",
            22,
            [
                ("z3-highmem-176-standardlssd", 176, 1408),
                ("z3-highmem-176", 176, 1408),
                ("z3-highmem-88-standardlssd", 88, 704),
            ],
        ),
        _make_family(
            "M4",
            "M4 (High-Memory Ultramem / Megamem)",
            "Memory-Optimized",
            "x86_64 Intel",
            "r7i / u7i / x2idn",
            "RECOMMENDED",
                        "Memory-Optimized",
            "Memory-optimized VMs scaling up to 224 vCPUs and ~6 TB RAM for large in-memory tick indices.",
            23,
            [
                ("m4-ultramem-224", 224, 5952),
                ("m4-megamem-224", 224, 2976),
                ("m4-ultramem-112", 112, 2976),
            ],
        ),
        _make_family(
            "M4N",
            "M4N (Network-Enhanced High-Memory)",
            "Memory-Optimized",
            "x86_64 Intel",
            "x2idn.32xlarge",
            "RECOMMENDED",
                        "Network + High-Mem",
            "Network-enhanced memory-optimized VMs up to 224 vCPUs and ~6 TB RAM.",
            24,
            [
                ("m4n-ultramem-224", 224, 5952),
                ("m4n-megamem-224", 224, 2976),
                ("m4n-ultramem-112", 112, 2976),
            ],
        ),
        _make_family(
            "M3",
            "M3 (Intel Ice Lake — 35-Region High-Mem)",
            "Memory-Optimized",
            "x86_64 Intel",
            "x2iezn / r6i",
            "RECOMMENDED",
                        "Global High-Memory",
            "Wide 35-region memory-optimized VMs offering up to 3.9 TB RAM for large order-book state.",
            25,
            [
                ("m3-ultramem-128", 128, 3904),
                ("m3-megamem-128", 128, 1952),
                ("m3-ultramem-64", 64, 1952),
            ],
        ),
        _make_family(
            "M2",
            "M2 (Ultra-Memory up to 11.5 TB)",
            "Memory-Optimized",
            "x86_64 Intel",
            "u-12tb1 / x1e",
            "DIVERSIFICATION",
                        "Ultra-Memory",
            "Extreme-memory VMs up to 416 vCPUs and 11.5 TB RAM for massive single-node graph state.",
            26,
            [
                ("m2-ultramem-416", 416, 11776),
                ("m2-hypermem-416", 416, 8832),
                ("m2-megamem-416", 416, 5888),
            ],
        ),
        _make_family(
            "M1",
            "M1 (Skylake — Memory-Optimized)",
            "Memory-Optimized",
            "x86_64 Intel",
            "x1.32xlarge",
            "DIVERSIFICATION",
                        "Previous-Gen Memory",
            "Previous-generation memory-optimized VMs up to 160 vCPUs and 3.8 TB RAM.",
            27,
            [
                ("m1-ultramem-160", 160, 3844),
                ("m1-megamem-96", 96, 1433.6),
            ],
        ),
        _make_family(
            "G4",
            "G4 (NVIDIA RTX PRO 6000 Blackwell GPU)",
            "GPU / AI",
            "GPU NVIDIA",
            "g6e / g5",
            "RECOMMENDED",
                        "RTX PRO 6000 GPU",
            "Latest-gen NVIDIA RTX PRO 6000 GPU instances across 24 regions for AI alpha training & inference.",
            28,
            [
                ("g4-standard-384", 384, 1440),
                ("g4-standard-192", 192, 720),
                ("g4-standard-96", 96, 360),
                ("g4-standard-48", 48, 180),
            ],
        ),
        _make_family(
            "G2",
            "G2 (NVIDIA L4 Tensor Core GPU)",
            "GPU / AI",
            "GPU NVIDIA",
            "g6 / g5",
            "RECOMMENDED",
                        "L4 AI / Graphics GPU",
            "NVIDIA L4 Tensor Core GPU instances across 18 regions; pairs seamlessly with Spot & DWS Flex-Start.",
            29,
            [
                ("g2-standard-96", 96, 384),
                ("g2-standard-48", 48, 192),
                ("g2-standard-24", 24, 96),
            ],
        ),
        _make_family(
            "A4",
            "A4 (NVIDIA B200 HGX — Frontier AI)",
            "GPU / AI",
            "GPU NVIDIA B200",
            "p6-b200",
            "RECOMMENDED",
                        "Frontier B200 GPU",
            "8x NVIDIA B200 GPU nodes for frontier deep-learning alpha training; ideal with DWS Flex-Start.",
            30,
            [("a4-highgpu-8g", 224, 3968)],
        ),
        _make_family(
            "A3",
            "A3 (NVIDIA H100 / H200 HGX)",
            "GPU / AI",
            "GPU NVIDIA H100/H200",
            "p5.48xlarge / p5en",
            "RECOMMENDED",
                        "H100 / H200 GPU",
            "8x NVIDIA H100/H200 GPU instances for multi-node quant foundation models & simulation acceleration.",
            31,
            [
                ("a3-ultragpu-8g", 224, 2952),
                ("a3-megagpu-8g", 208, 1872),
                ("a3-highgpu-8g", 208, 1872),
                ("a3-highgpu-4g", 104, 936),
            ],
        ),
        _make_family(
            "A2",
            "A2 (NVIDIA A100 GPU)",
            "GPU / AI",
            "GPU NVIDIA A100",
            "p4d / p4de",
            "DIVERSIFICATION",
                        "A100 GPU",
            "NVIDIA A100 GPU VMs (up to 16x A100) for deep learning research.",
            32,
            [
                ("a2-ultragpu-8g", 96, 1360),
                ("a2-megagpu-16g", 96, 1360),
                ("a2-highgpu-8g", 96, 680),
            ],
        ),
        _make_family(
            "G1",
            "G1 (Shared-Core Small Legacy)",
            "Shared-Core Legacy",
            "x86_64 Legacy",
            "t2.small",
            "LEGACY",
                        "Legacy Shared-Core",
            "Legacy shared-core micro instance; standardize quant research on N4/C4D/C4.",
            33,
            [("g1-small", 1, 1.7)],
        ),
        _make_family(
            "F1",
            "F1 (Shared-Core Micro Legacy)",
            "Shared-Core Legacy",
            "x86_64 Legacy",
            "t2.micro",
            "LEGACY",
                        "Legacy Shared-Core",
            "Legacy shared-core 0.6 GB micro instance.",
            34,
            [("f1-micro", 1, 0.6)],
        ),
    ]
}


def _get_session() -> requests.Session:
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16)
        sess.mount("https://", adapter)
        _thread_local.session = sess
    return sess


def get_access_token(force_refresh: bool = False) -> str:
    """Gets a GCP OAuth2 access token via ADC or gcloud."""
    global _cached_token, _token_expiry
    now = time.time()
    with _token_lock:
        if not force_refresh and _cached_token and now < _token_expiry:
            return _cached_token

        try:
            import google.auth
            import google.auth.transport.requests

            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(google.auth.transport.requests.Request())
            if creds.token:
                _cached_token = creds.token
                _token_expiry = now + 2400
                return _cached_token
        except Exception:
            pass

        gcloud_cmd = shutil.which(GCLOUD_BIN) or GCLOUD_BIN
        out = subprocess.check_output(
            [gcloud_cmd, "auth", "print-access-token"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        ).strip()
        if not out:
            raise RuntimeError("Empty token returned by gcloud auth.")
        _cached_token = out
        _token_expiry = now + 2400
        return _cached_token


def get_live_inventory(
    project: str, force_refresh: bool = False
) -> dict[str, Any]:
    """Discovers all live GCP regions, zones, and non-metal machineTypes in ~3.5s.

    Caches per project for 30 minutes and falls back gracefully to the complete
    static 43-region x 34-family catalog if offline.
    """
    now = time.time()
    with _inventory_lock:
        cached = _inventory_cache.get(project)
        if (
            not force_refresh
            and cached
            and (now - cached[0]) < INVENTORY_TTL_SECONDS
        ):
            return cached[1]

    if not project:
        families_fb = {
            fid: {
                **f,
                "shapes": [{**sh, "zones_by_region": {}} for sh in f["shapes"]],
                "supported_regions": [r["id"] for r in REGION_CATALOG],
                "region_count": len(REGION_CATALOG),
                "shape_count": len(f["shapes"]),
            }
            for fid, f in FAMILY_CATALOG.items()
        }
        return {
            "live": False,
            "regions": REGION_CATALOG,
            "region_map": REGION_MAP,
            "families": families_fb,
            "stats": {
                "total_regions": len(REGION_CATALOG),
                "total_zones": sum(len(r["zones"]) for r in REGION_CATALOG),
                "total_families": len(families_fb),
                "total_shapes": sum(len(f["shapes"]) for f in families_fb.values()),
            },
        }

    try:
        token = get_access_token(force_refresh=force_refresh)
        sess = _get_session()
        headers = {"Authorization": f"Bearer {token}"}

        reg_resp = sess.get(
            f"{COMPUTE_V1_BASE}/projects/{project}/regions",
            headers=headers,
            timeout=20,
        )
        reg_resp.raise_for_status()
        live_regions: dict[str, dict[str, Any]] = {}
        all_zones: list[tuple[str, str]] = []
        for reg in reg_resp.json().get("items", []):
            rid = reg["name"]
            znames = sorted(z.split("/")[-1] for z in reg.get("zones", []))
            live_regions[rid] = _infer_region_meta(rid, live_zones=znames)
            for zn in znames:
                all_zones.append((rid, zn))

        # Ensure every static fallback region is also present cleanly if missing.
        for rid, rmeta in REGION_MAP.items():
            if rid not in live_regions:
                live_regions[rid] = rmeta

        def _fetch_zone_mts(pair: tuple[str, str]) -> tuple[str, str, list[dict[str, Any]]]:
            rid, zname = pair
            zsess = _get_session()
            items: list[dict[str, Any]] = []
            page_tok = None
            while True:
                params: dict[str, Any] = {
                    "maxResults": 500,
                    "fields": "nextPageToken,items(name,guestCpus,memoryMb,isSharedCpu)",
                }
                if page_tok:
                    params["pageToken"] = page_tok
                r = zsess.get(
                    f"{COMPUTE_V1_BASE}/projects/{project}/zones/{zname}/machineTypes",
                    headers=headers,
                    params=params,
                    timeout=15,
                )
                if r.status_code != 200:
                    break
                d = r.json()
                items.extend(d.get("items", []))
                page_tok = d.get("nextPageToken")
                if not page_tok:
                    break
            return rid, zname, items

        zone_rows: list[tuple[str, str, list[dict[str, Any]]]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=48) as zpool:
            zone_rows = list(zpool.map(_fetch_zone_mts, all_zones))

        # series -> machine_type -> shape dict
        series_shapes: dict[str, dict[str, dict[str, Any]]] = {}
        for rid, zname, items in zone_rows:
            for mt in items:
                mname = mt["name"]
                if "-metal" in mname:
                    continue
                series = mname.split("-")[0].upper()
                if series in SPOT_UNSUPPORTED_SERIES:
                    continue
                sdict = series_shapes.setdefault(series, {})
                if mname not in sdict:
                    sdict[mname] = {
                        "type": mname,
                        "vcpus": int(mt.get("guestCpus", 0) or 0),
                        "memory_gb": round(float(mt.get("memoryMb", 0) or 0) / 1024.0, 2),
                        "shape_class": _classify_shape(mname),
                        "zones_by_region": {},
                    }
                zmap = sdict[mname]["zones_by_region"]
                zmap.setdefault(rid, []).append(zname)

        families_out: dict[str, dict[str, Any]] = {}
        max_rank = len(FAMILY_CATALOG) + 1
        all_series_ids = sorted(
            set(FAMILY_CATALOG.keys()) | set(series_shapes.keys()),
            key=lambda fid: FAMILY_CATALOG.get(fid, {}).get("default_rank", max_rank),
        )

        unique_shape_count = 0
        for rank_idx, fid in enumerate(all_series_ids, start=1):
            base = FAMILY_CATALOG.get(fid)
            if base is None:
                base = _make_family(
                    fid,
                    f"{fid} Compute Series",
                    "General Purpose",
                    "x86_64",
                    "Dynamic GCE Series",
                    "RECOMMENDED",
                    "Compute Family",
                    f"Compute Engine {fid} VM series.",
                    rank_idx,
                    [],
                )
            discovered_map = series_shapes.get(fid, {})
            if discovered_map:
                merged_shapes = sorted(
                    [
                        {
                            **sh,
                            "zones_by_region": {
                                r: sorted(zs) for r, zs in sh["zones_by_region"].items()
                            },
                        }
                        for sh in discovered_map.values()
                    ],
                    key=lambda x: (x["vcpus"], x["memory_gb"], x["type"]),
                    reverse=True,
                )
            else:
                merged_shapes = [
                    {**sh, "zones_by_region": {}} for sh in base["shapes"]
                ]

            reg_set = sorted(
                {r for sh in merged_shapes for r in sh.get("zones_by_region", {})}
            )
            unique_shape_count += len(merged_shapes)
            families_out[fid] = {
                **base,
                "shapes": merged_shapes,
                "supported_regions": reg_set,
                "region_count": len(reg_set),
                "shape_count": len(merged_shapes),
            }

        regions_list = sorted(live_regions.values(), key=lambda r: (r["geo"], r["id"]))
        inv = {
            "live": True,
            "regions": regions_list,
            "region_map": live_regions,
            "families": families_out,
            "stats": {
                "total_regions": len(regions_list),
                "total_zones": len(all_zones),
                "total_families": len(families_out),
                "total_shapes": unique_shape_count,
            },
        }
        with _inventory_lock:
            _inventory_cache[project] = (time.time(), inv)
        return inv
    except Exception:
        # Seamless fallback to complete 43-region x 34-family static catalog.
        families_fb = {
            fid: {
                **f,
                "shapes": [{**sh, "zones_by_region": {}} for sh in f["shapes"]],
                "supported_regions": [r["id"] for r in REGION_CATALOG],
                "region_count": len(REGION_CATALOG),
                "shape_count": len(f["shapes"]),
            }
            for fid, f in FAMILY_CATALOG.items()
        }
        return {
            "live": False,
            "regions": REGION_CATALOG,
            "region_map": REGION_MAP,
            "families": families_fb,
            "stats": {
                "total_regions": len(REGION_CATALOG),
                "total_zones": sum(len(r["zones"]) for r in REGION_CATALOG),
                "total_families": len(families_fb),
                "total_shapes": sum(len(f["shapes"]) for f in families_fb.values()),
            },
        }


def _select_candidate_shapes(
    all_shapes: list[dict[str, Any]],
    region_id: str,
    shape_profile: str = "standard",
    inventory_live: bool = False,
) -> list[dict[str, Any]]:
    """Orders shapes in `region_id` according to `shape_profile`."""
    in_region = [
        sh
        for sh in all_shapes
        if not sh.get("zones_by_region") or region_id in sh["zones_by_region"]
    ]
    if inventory_live and any(sh.get("zones_by_region") for sh in all_shapes):
        # Strictly trust live zone inventory when available.
        in_region = [
            sh for sh in all_shapes if region_id in sh.get("zones_by_region", {})
        ]
    if not in_region:
        return []

    prof = (shape_profile or "standard").lower()

    def _pref_key(sh: dict[str, Any]) -> tuple[int, int, float, str]:
        sc = sh.get("shape_class", _classify_shape(sh["type"]))
        is_std = sc == "standard"
        is_hm = sc == "highmem"
        is_hc = sc == "highcpu"
        is_lssd = sc == "lssd"
        is_gpu = sc == "gpu"
        if prof == "highmem":
            bucket = 3 if is_hm else (2 if is_std else 1)
        elif prof == "highcpu":
            bucket = 3 if is_hc else (2 if is_std else 1)
        elif prof == "lssd":
            bucket = 3 if is_lssd else (2 if not is_hm else 1)
        elif prof == "largest":
            bucket = 1
        else:  # "standard" default
            bucket = 3 if (is_std or is_gpu) else (2 if not is_lssd else 1)
        return (bucket, sh["vcpus"], sh["memory_gb"], sh["type"])

    return sorted(in_region, key=_pref_key, reverse=True)


def _label_obtainability(score: float) -> str:
    if score < 0.5:
        return "LOW"
    if score <= 0.7:
        return "MEDIUM"
    return "HIGH"


def _label_uptime(uptime_str: str) -> str:
    if uptime_str == "3600s":
        return "LOW Risk (1h+)"
    if uptime_str == "600s":
        return "MEDIUM Risk (~10m)"
    if uptime_str == "60s":
        return "HIGH Risk (~1m)"
    return uptime_str or "UNKNOWN"


def _money_to_float(money: dict[str, Any] | None) -> float | None:
    if not money:
        return None
    units = float(money.get("units", 0) or 0)
    nanos = float(money.get("nanos", 0) or 0) / 1e9
    return round(units + nanos, 5)


def query_capacity_advice_once(
    session: requests.Session,
    token: str,
    project: str,
    region: str,
    machine_type: str,
    size: int,
    zones: list[str] | None = None,
    target_shape: str = "ANY",
) -> dict[str, Any]:
    """Single POST call to /compute/beta/.../advice/capacity with backoff."""
    url = f"{COMPUTE_BETA_BASE}/projects/{project}/regions/{region}/advice/capacity"
    dist_policy: dict[str, Any] = {"targetShape": target_shape}
    if zones:
        dist_policy["zones"] = [{"zone": f"zones/{z}"} for z in zones]

    payload = {
        "instanceProperties": {
            "scheduling": {"provisioningModel": "SPOT"}
        },
        "instanceFlexibilityPolicy": {
            "instanceSelections": {
                "default": {"machineTypes": [machine_type]}
            }
        },
        "distributionPolicy": dist_policy,
        "size": max(1, min(1000, int(size))),
    }

    resp = None
    for attempt in range(3):
        resp = session.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        if resp.status_code in (429, 500, 502, 503) and attempt < 2:
            time.sleep(0.25 * (2**attempt))
            continue
        break

    assert resp is not None
    if resp.status_code != 200:
        try:
            err_msg = resp.json().get("error", {}).get("message", resp.text)
        except Exception:
            err_msg = resp.text
        low_err = err_msg.lower()
        unsupported = any(
            k in low_err
            for k in (
                "not supported",
                "cannot recognize machine type",
                "bare metal",
                "invalid value for field",
            )
        )
        return {
            "supported": not unsupported,
            "error": err_msg,
            "obtainability": 0.0,
            "obtainability_label": "UNSUPPORTED" if unsupported else "ERROR",
            "estimated_uptime": "",
            "preemption_risk_label": "N/A",
            "shards": [],
        }

    data = resp.json()
    recs = data.get("recommendations", [])
    if not recs:
        return {
            "supported": True,
            "obtainability": 0.0,
            "obtainability_label": "LOW",
            "estimated_uptime": "",
            "preemption_risk_label": "HIGH Risk",
            "shards": [],
        }

    rec = recs[0]
    scores = rec.get("scores", {})
    obt = float(scores.get("obtainability", 0.0) or 0.0)
    uptime = scores.get("estimatedUptime", "")
    shards = []
    for sh in rec.get("shards", []):
        z_raw = sh.get("zone", "")
        z_short = z_raw.split("/")[-1] if z_raw else ""
        shards.append(
            {
                "zone": z_short,
                "machine_type": sh.get("machineType", machine_type),
                "instance_count": int(sh.get("instanceCount", 0) or 0),
            }
        )
    return {
        "supported": True,
        "obtainability": round(obt, 3),
        "obtainability_label": _label_obtainability(obt),
        "estimated_uptime": uptime,
        "preemption_risk_label": _label_uptime(uptime),
        "shards": shards,
    }


def query_capacity_history(
    session: requests.Session,
    token: str,
    project: str,
    region: str,
    machine_type: str,
) -> dict[str, Any]:
    """Queries 30-day preemption rate and multi-month Spot price history."""
    url = f"{COMPUTE_BETA_BASE}/projects/{project}/regions/{region}/advice/capacityHistory"
    payload = {
        "instanceProperties": {
            "machineType": machine_type,
            "scheduling": {"provisioningModel": "SPOT"},
        },
        "types": ["PREEMPTION", "PRICE"],
    }
    try:
        resp = None
        for attempt in range(2):
            resp = session.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=12,
            )
            if resp.status_code in (429, 500, 502, 503) and attempt == 0:
                time.sleep(0.25)
                continue
            break
        if resp is None or resp.status_code != 200:
            return {
                "preemption_rate_30d": None,
                "latest_spot_price_usd": None,
                "price_history": [],
                "preemption_history": [],
            }
        data = resp.json()
        preemptions = data.get("preemptionHistory", [])
        prices = data.get("priceHistory", [])

        latest_preemption = None
        parsed_preemptions = []
        for p in preemptions:
            rate = p.get("preemptionRate")
            if rate is not None:
                latest_preemption = round(float(rate) * 100.0, 2)
                parsed_preemptions.append(
                    {
                        "start": p.get("interval", {}).get("startTime", ""),
                        "end": p.get("interval", {}).get("endTime", ""),
                        "rate_pct": latest_preemption,
                    }
                )

        parsed_prices = []
        for pr in prices:
            val = _money_to_float(pr.get("listPrice"))
            if val is not None:
                parsed_prices.append(
                    {
                        "start": pr.get("interval", {}).get("startTime", ""),
                        "end": pr.get("interval", {}).get("endTime", ""),
                        "usd_per_hr": val,
                    }
                )
        parsed_prices.sort(key=lambda x: x["start"])
        latest_price = parsed_prices[-1]["usd_per_hr"] if parsed_prices else None

        return {
            "preemption_rate_30d": latest_preemption,
            "latest_spot_price_usd": latest_price,
            "price_history": parsed_prices,
            "preemption_history": parsed_preemptions,
        }
    except Exception:
        return {
            "preemption_rate_30d": None,
            "latest_spot_price_usd": None,
            "price_history": [],
            "preemption_history": [],
        }


def find_max_obtainable_vms(
    session: requests.Session,
    token: str,
    project: str,
    region: str,
    machine_type: str,
    zones: list[str] | None = None,
    min_score: float = 0.5,
    precision_vms: int = 25,
    check_single_fallback: bool = True,
) -> dict[str, Any]:
    """Finds the max obtainable Spot VMs in [0..1000] via fast binary search."""
    r1000 = query_capacity_advice_once(
        session, token, project, region, machine_type, 1000, zones=zones
    )
    if not r1000.get("supported", True) or r1000.get("error"):
        return {
            **r1000,
            "max_vms": 0,
            "capped_at_1000": False,
            "probes": 1,
        }
    if r1000["obtainability"] >= min_score:
        return {
            **r1000,
            "max_vms": 1000,
            "capped_at_1000": True,
            "probes": 1,
        }

    r10 = query_capacity_advice_once(
        session, token, project, region, machine_type, 10, zones=zones
    )
    probes = 2
    if r10["obtainability"] < min_score:
        if check_single_fallback:
            r1 = query_capacity_advice_once(
                session, token, project, region, machine_type, 1, zones=zones
            )
            probes += 1
            if r1["obtainability"] >= min_score:
                return {
                    **r1,
                    "max_vms": 1,
                    "capped_at_1000": False,
                    "probes": probes,
                }
        return {
            **r1000,
            "max_vms": 0,
            "capped_at_1000": False,
            "probes": probes,
        }

    low = 10
    high = 1000
    best = r10
    best_vms = 10

    while (high - low) > precision_vms:
        mid = (low + high) // 2
        rmid = query_capacity_advice_once(
            session, token, project, region, machine_type, mid, zones=zones
        )
        probes += 1
        if rmid["obtainability"] >= min_score:
            best = rmid
            best_vms = mid
            low = mid
        else:
            high = mid

    return {
        **best,
        "max_vms": best_vms,
        "capped_at_1000": False,
        "probes": probes,
    }


def _unsupported_pool_record(
    region_id: str,
    reg_info: dict[str, Any],
    fam: dict[str, Any],
    fallback_shape: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": f"{region_id}::{fam['id']}",
        "region": region_id,
        "region_label": reg_info["label"],
        "geo": reg_info["geo"],
        "subgeo": reg_info.get("subgeo", reg_info["geo"]),
        "region_note": reg_info.get("note", ""),
        "family": fam["id"],
        "family_name": fam["name"],
        "category": fam["category"],
        "arch": fam["arch"],
        "aws_mapping": fam["aws_mapping"],
        "lifecycle": fam["lifecycle"],
        "lifecycle_label": fam["lifecycle_label"],
        "lifecycle_note": fam["lifecycle_note"],
        "machine_type": fallback_shape["type"],
        "shape_class": fallback_shape.get("shape_class", "standard"),
        "vcpus_per_vm": fallback_shape["vcpus"],
        "memory_gb_per_vm": fallback_shape["memory_gb"],
        "available_shape_count": 0,
        "supported": False,
        "max_vms": 0,
        "max_vcpus": 0,
        "capped_at_limit": False,
        "obtainability": 0.0,
        "obtainability_label": "UNSUPPORTED",
        "estimated_uptime": "",
        "preemption_risk_label": "Unsupported in Region",
        "preemption_rate_30d": None,
        "spot_price_vm_hr": None,
        "spot_price_vcpu_hr": None,
        "zonal_shards": [],
        "price_history": [],
    }


def _evaluate_region_family(
    project: str,
    token: str,
    region_id: str,
    family_id: str,
    inventory: dict[str, Any],
    per_zone_unlock: bool,
    min_score: float,
    shape_profile: str,
    broad_scan: bool = False,
) -> dict[str, Any]:
    """Evaluates a (region, family) pair using top-down max-shape pecking order."""
    fam = inventory["families"][family_id]
    reg_info = inventory["region_map"].get(
        region_id, _infer_region_meta(region_id)
    )
    candidates = _select_candidate_shapes(
        fam["shapes"],
        region_id,
        shape_profile=shape_profile,
        inventory_live=inventory.get("live", False),
    )
    if not candidates:
        fallback_sh = (
            fam["shapes"][0]
            if fam["shapes"]
            else {"type": f"{family_id.lower()}-standard", "vcpus": 0, "memory_gb": 0, "shape_class": "standard"}
        )
        return _unsupported_pool_record(region_id, reg_info, fam, fallback_sh)

    session = _get_session()
    chosen_shape = None
    region_probe = None

    # Deduplicate same-vCPU-same-prefix variants when walking down to keep probing fast.
    walk_shapes: list[dict[str, Any]] = []
    seen_vcpus: set[tuple[str, int]] = set()
    for sh in candidates:
        key = (sh.get("shape_class", "standard"), sh["vcpus"])
        if key not in seen_vcpus:
            seen_vcpus.add(key)
            walk_shapes.append(sh)

    prec = 100 if broad_scan else 40
    max_walk = 3 if broad_scan else 6
    for shape in walk_shapes[:max_walk]:
        probe = find_max_obtainable_vms(
            session=session,
            token=token,
            project=project,
            region=region_id,
            machine_type=shape["type"],
            zones=None,
            min_score=min_score,
            precision_vms=prec,
            check_single_fallback=not broad_scan,
        )
        if probe.get("supported", True) and not probe.get("error"):
            chosen_shape = shape
            region_probe = probe
            # If the largest supported shape is zeroed out, also check a mid-size (~64-128 vCPU) slice.
            if probe["max_vms"] == 0 and shape["vcpus"] > 128:
                smaller_candidates = [s for s in walk_shapes if s["vcpus"] <= 128]
                if smaller_candidates:
                    sub_shape = smaller_candidates[0]
                    sub_probe = find_max_obtainable_vms(
                        session=session,
                        token=token,
                        project=project,
                        region=region_id,
                        machine_type=sub_shape["type"],
                        zones=None,
                        min_score=min_score,
                        precision_vms=prec,
                        check_single_fallback=not broad_scan,
                    )
                    if sub_probe.get("supported", True) and sub_probe["max_vms"] > 0:
                        chosen_shape = sub_shape
                        region_probe = sub_probe
            break

    if chosen_shape is None or region_probe is None:
        return _unsupported_pool_record(region_id, reg_info, fam, candidates[0])

    max_vms = region_probe["max_vms"]
    capped_flag = region_probe["capped_at_1000"]
    zonal_shards = region_probe.get("shards", [])
    best_obt = region_probe["obtainability"]
    best_uptime = region_probe["estimated_uptime"]

    # Probe exact zones where this chosen_shape exists (avoids invalid zone errors).
    shape_zones = (
        chosen_shape.get("zones_by_region", {}).get(region_id)
        or reg_info.get("zones", [])
    )

    def _probe_single_zone(z_name: str) -> tuple[str, dict[str, Any]]:
        z_sess = _get_session()
        return z_name, find_max_obtainable_vms(
            session=z_sess,
            token=token,
            project=project,
            region=region_id,
            machine_type=chosen_shape["type"],
            zones=[z_name],
            min_score=min_score,
            precision_vms=prec,
            check_single_fallback=not broad_scan,
        )

    # On broad global sweeps (>120 pairs), probe individual zones specifically
    # when the regional API hits or approaches the 1,000-VM cap to keep scans crisp.
    should_unlock_zones = (
        bool(shape_zones)
        and max_vms > 0
        and (
            capped_flag
            or (per_zone_unlock and (not broad_scan or max_vms >= 850))
        )
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as subpool:
        hist_fut = subpool.submit(
            query_capacity_history,
            _get_session(),
            token,
            project,
            region_id,
            chosen_shape["type"],
        )
        zone_futs = (
            [subpool.submit(_probe_single_zone, z) for z in shape_zones]
            if should_unlock_zones
            else []
        )
        hist = hist_fut.result()
        if zone_futs:
            zonal_total = 0
            unlocked_shards = []
            any_zone_capped = False
            weighted_obt = 0.0
            for zf in zone_futs:
                z, zp = zf.result()
                if zp["max_vms"] > 0:
                    zonal_total += zp["max_vms"]
                    weighted_obt += zp["obtainability"] * zp["max_vms"]
                    if zp["capped_at_1000"]:
                        any_zone_capped = True
                    unlocked_shards.append(
                        {
                            "zone": z,
                            "machine_type": chosen_shape["type"],
                            "instance_count": zp["max_vms"],
                            "capped_at_1000": zp["capped_at_1000"],
                            "obtainability": zp["obtainability"],
                        }
                    )
            if zonal_total >= max_vms and unlocked_shards:
                max_vms = zonal_total
                zonal_shards = unlocked_shards
                capped_flag = any_zone_capped
                best_obt = round(weighted_obt / max(1, zonal_total), 3)

    vcpus = chosen_shape["vcpus"]
    max_vcpus = max_vms * vcpus
    vm_price = hist["latest_spot_price_usd"]
    vcpu_price = round(vm_price / vcpus, 5) if (vm_price and vcpus > 0) else None

    return {
        "id": f"{region_id}::{family_id}",
        "region": region_id,
        "region_label": reg_info["label"],
        "geo": reg_info["geo"],
        "subgeo": reg_info.get("subgeo", reg_info["geo"]),
        "region_note": reg_info.get("note", ""),
        "family": family_id,
        "family_name": fam["name"],
        "category": fam["category"],
        "arch": fam["arch"],
        "aws_mapping": fam["aws_mapping"],
        "lifecycle": fam["lifecycle"],
        "lifecycle_label": fam["lifecycle_label"],
        "lifecycle_note": fam["lifecycle_note"],
        "machine_type": chosen_shape["type"],
        "shape_class": chosen_shape.get("shape_class", "standard"),
        "vcpus_per_vm": vcpus,
        "memory_gb_per_vm": chosen_shape["memory_gb"],
        "available_shape_count": len(candidates),
        "supported": True,
        "max_vms": max_vms,
        "max_vcpus": max_vcpus,
        "capped_at_limit": capped_flag,
        "obtainability": best_obt,
        "obtainability_label": _label_obtainability(best_obt)
        if max_vms > 0
        else "STOCKOUT",
        "estimated_uptime": best_uptime,
        "preemption_risk_label": _label_uptime(best_uptime)
        if max_vms > 0
        else "HIGH Risk (~1m)",
        "preemption_rate_30d": hist["preemption_rate_30d"],
        "spot_price_vm_hr": vm_price,
        "spot_price_vcpu_hr": vcpu_price,
        "zonal_shards": zonal_shards,
        "price_history": hist["price_history"],
    }


def run_fleet_scan(
    project: str,
    regions: list[str],
    families: list[str],
    per_zone_unlock: bool = True,
    min_score: float = 0.5,
    shape_profile: str = "standard",
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Concurrently scans all requested (region, family) pools."""
    norm_regions = sorted({r.strip() for r in regions if r.strip()})
    norm_families = sorted({f.strip().upper() for f in families if f.strip()})
    norm_prof = (shape_profile or "standard").strip().lower()
    cache_key = (
        f"{project}|{norm_prof}|{','.join(norm_regions)}|{','.join(norm_families)}"
        f"|{per_zone_unlock}|{min_score:.2f}"
    )
    now = time.time()
    if not force_refresh:
        with _scan_cache_lock:
            cached = _scan_cache.get(cache_key)
            if cached and (now - cached[0]) < CACHE_TTL_SECONDS:
                return {**cached[1], "cached": True}

    t0 = time.time()
    token = get_access_token(force_refresh=force_refresh)
    inventory = get_live_inventory(project, force_refresh=force_refresh)

    tasks: list[tuple[str, str]] = [
        (r, f)
        for r in norm_regions
        for f in norm_families
        if f in inventory["families"]
    ]

    broad_scan = len(tasks) > 120

    # Pre-warm live AWS & Azure public Spot pricing concurrently with the GCP scan
    # so multi-cloud enrichment adds near-zero wall-clock latency.
    azure_prefetch_pairs: set[tuple[str, str]] = set()
    for r, f in tasks:
        az_reg = CLOUD_REGION_MAP.get(r, {}).get("azure_region", "eastus")
        for skey in _azure_series_ladder(f, norm_prof):
            for sku in AZURE_SERIES_TO_SKUS.get(skey, []):
                azure_prefetch_pairs.add((az_reg, sku))

    bg_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    aws_pre_fut = bg_pool.submit(get_aws_live_spot_data, force_refresh)
    az_pre_fut = bg_pool.submit(
        prefetch_azure_spot_prices, azure_prefetch_pairs, force_refresh
    )

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        future_map = {
            pool.submit(
                _evaluate_region_family,
                project,
                token,
                r,
                f,
                inventory,
                per_zone_unlock,
                min_score,
                norm_prof,
                broad_scan,
            ): (r, f)
            for r, f in tasks
        }
        for fut in concurrent.futures.as_completed(future_map):
            results.append(fut.result())

    # Ensure concurrent prefetch completed (never fail GCP scan if vendor feeds hiccup).
    try:
        aws_pre_fut.result(timeout=15)
    except Exception:
        pass
    try:
        az_pre_fut.result(timeout=15)
    except Exception:
        pass
    bg_pool.shutdown(wait=False)

    pricing_meta = enrich_pools_with_multicloud_spot(results, force_refresh=False)

    results.sort(
        key=lambda x: (x["max_vcpus"], x["obtainability"]), reverse=True
    )

    elapsed_ms = int((time.time() - t0) * 1000)
    payload = {
        "project": project,
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_ms": elapsed_ms,
        "per_zone_unlock": per_zone_unlock,
        "min_score": min_score,
        "shape_profile": norm_prof,
        "cached": False,
        "pricing_meta": pricing_meta,
        "pools": results,
    }
    with _scan_cache_lock:
        _scan_cache[cache_key] = (time.time(), payload)
    return payload


def run_pecking_order_drilldown(
    project: str,
    region_id: str,
    family_id: str,
    min_score: float = 0.5,
    shape_profile: str = "standard",
    machine_type: str | None = None,
) -> dict[str, Any]:
    """Runs top-down max-shape ladder for (region, family) + exposes all shapes."""
    inventory = get_live_inventory(project)
    fam = inventory["families"][family_id]
    reg_info = inventory["region_map"].get(
        region_id, _infer_region_meta(region_id)
    )
    token = get_access_token()

    candidates = _select_candidate_shapes(
        fam["shapes"],
        region_id,
        shape_profile=shape_profile,
        inventory_live=inventory.get("live", False),
    )
    available_shapes = [
        {
            "type": sh["type"],
            "vcpus": sh["vcpus"],
            "memory_gb": sh["memory_gb"],
            "shape_class": sh.get("shape_class", _classify_shape(sh["type"])),
        }
        for sh in sorted(
            candidates,
            key=lambda x: (x["vcpus"], x["memory_gb"], x["type"]),
            reverse=True,
        )
    ]

    if machine_type:
        exact = [sh for sh in candidates if sh["type"] == machine_type]
        if not exact:
            exact = [sh for sh in fam["shapes"] if sh["type"] == machine_type]
        if not exact:
            exact = [
                {
                    "type": machine_type,
                    "vcpus": 1,
                    "memory_gb": 1,
                    "shape_class": _classify_shape(machine_type),
                    "zones_by_region": {},
                }
            ]
        rungs_to_probe = exact
    else:
        # Take up to 6 diverse rungs spanning top down to mid sizes.
        rungs_to_probe = []
        seen_pairs: set[tuple[str, int]] = set()
        for sh in candidates:
            key = (sh.get("shape_class", "standard"), sh["vcpus"])
            if key not in seen_pairs:
                seen_pairs.add(key)
                rungs_to_probe.append(sh)
            if len(rungs_to_probe) >= 6:
                break

    def _probe_rung(shape: dict[str, Any]) -> dict[str, Any]:
        sess = _get_session()
        reg_res = find_max_obtainable_vms(
            session=sess,
            token=token,
            project=project,
            region=region_id,
            machine_type=shape["type"],
            zones=None,
            min_score=min_score,
            precision_vms=15,
        )
        hist = query_capacity_history(
            session=sess,
            token=token,
            project=project,
            region=region_id,
            machine_type=shape["type"],
        )
        shape_zones = (
            shape.get("zones_by_region", {}).get(region_id)
            or reg_info.get("zones", [])
        )
        zone_breakdown = []
        if reg_res.get("supported", True) and not reg_res.get("error"):
            for z in shape_zones:
                zp = find_max_obtainable_vms(
                    session=sess,
                    token=token,
                    project=project,
                    region=region_id,
                    machine_type=shape["type"],
                    zones=[z],
                    min_score=min_score,
                    precision_vms=20,
                )
                zone_breakdown.append(
                    {
                        "zone": z,
                        "max_vms": zp["max_vms"],
                        "max_vcpus": zp["max_vms"] * shape["vcpus"],
                        "capped_at_1000": zp["capped_at_1000"],
                        "obtainability": zp["obtainability"],
                    }
                )
        zonal_sum_vms = sum(z["max_vms"] for z in zone_breakdown)
        effective_vms = max(reg_res["max_vms"], zonal_sum_vms)
        vm_price = hist["latest_spot_price_usd"]
        return {
            "machine_type": shape["type"],
            "shape_class": shape.get("shape_class", "standard"),
            "vcpus": shape["vcpus"],
            "memory_gb": shape["memory_gb"],
            "supported": reg_res.get("supported", True)
            and not bool(reg_res.get("error")),
            "regional_api_vms": reg_res["max_vms"],
            "per_zone_unlocked_vms": effective_vms,
            "effective_vcpus": effective_vms * shape["vcpus"],
            "obtainability": reg_res["obtainability"],
            "obtainability_label": reg_res["obtainability_label"],
            "preemption_risk_label": reg_res["preemption_risk_label"],
            "preemption_rate_30d": hist["preemption_rate_30d"],
            "spot_price_vm_hr": vm_price,
            "spot_price_vcpu_hr": round(vm_price / shape["vcpus"], 5)
            if (vm_price and shape["vcpus"] > 0)
            else None,
            "zone_breakdown": zone_breakdown,
            "price_history": hist["price_history"],
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        rungs = list(pool.map(_probe_rung, rungs_to_probe))

    # Enrich each drilldown rung with live AWS & Azure equivalent VM + Spot pricing.
    rung_proxies = [
        {
            "region": region_id,
            "family": family_id,
            "shape_class": r.get("shape_class", "standard"),
            "vcpus_per_vm": r.get("vcpus", 64),
            "spot_price_vcpu_hr": r.get("spot_price_vcpu_hr"),
        }
        for r in rungs
    ]
    enrich_pools_with_multicloud_spot(rung_proxies, force_refresh=False)
    for r, px in zip(rungs, rung_proxies):
        r["aws_equiv"] = px.get("aws_equiv")
        r["azure_equiv"] = px.get("azure_equiv")

    safe_family_ceiling_vcpus = max(
        (r["effective_vcpus"] for r in rungs), default=0
    )
    naive_sum_vcpus = sum(r["effective_vcpus"] for r in rungs)

    return {
        "project": project,
        "region": region_id,
        "region_label": reg_info["label"],
        "family": family_id,
        "family_name": fam["name"],
        "category": fam["category"],
        "arch": fam["arch"],
        "lifecycle": fam["lifecycle"],
        "lifecycle_label": fam["lifecycle_label"],
        "lifecycle_note": fam["lifecycle_note"],
        "aws_mapping": fam["aws_mapping"],
        "safe_non_overlapping_vcpus": safe_family_ceiling_vcpus,
        "naive_overlapping_sum_vcpus": naive_sum_vcpus,
        "available_shapes": available_shapes,
        "rungs": rungs,
    }
