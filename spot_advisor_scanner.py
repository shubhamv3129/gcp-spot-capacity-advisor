#!/usr/bin/env python3
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

"""GCP Spot Capacity Advisor — Top-Down Multi-Region & Per-Zone Scanner.

Queries Google Compute Engine's public Capacity Advice, Capacity History, and
live Compute Engine inventory APIs using Application Default Credentials (ADC):
  - GET  /compute/v1/projects/{project}/regions (discover all regions & zones)
  - GET  /compute/v1/projects/{project}/zones/{zone}/machineTypes (all VM shapes)
  - POST /compute/beta/projects/{project}/regions/{region}/advice/capacity
  - POST /compute/beta/projects/{project}/regions/{region}/advice/capacityHistory

Methodology:
  1. Discovers live non-metal Spot-supported VM shapes across all GCE series or
     selected families (--families ALL discovers all 34 Spot-capable series).
  2. Probes largest VM shapes top-down per family (e.g. 384 -> 192 -> 96) to
     quantify high-core pools even under the 1,000-VM single-request API limit.
  3. Queries individual zones supporting each shape independently via binary
     search [1..1000] to unlock multi-thousand-VM regional Spot headroom.
  4. Reports the safe non-overlapping ceiling per (region, family) so smaller
     host slices are never double-counted against larger shapes.

Prerequisites:
  pip install google-auth requests
  gcloud auth application-default login

Usage:
  python3 spot_advisor_scanner.py --project YOUR_GCP_PROJECT_ID \\
      --regions asia-east1,asia-south1,asia-southeast1,europe-west4 \\
      --families N4,C4D,C4,N2D --per-zone

  # Scan ALL live regions & ALL Spot-supported VM families (High-Memory tier):
  python3 spot_advisor_scanner.py --project YOUR_GCP_PROJECT_ID \\
      --regions ALL --families ALL --shape-profile highmem --per-zone
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import threading
import time
from typing import Any

import google.auth
import google.auth.transport.requests
import requests
from requests.adapters import HTTPAdapter

COMPUTE_V1 = "https://compute.googleapis.com/compute/v1"
COMPUTE_BETA = "https://compute.googleapis.com/compute/beta"

SPOT_UNSUPPORTED_SERIES = {
    "X4",
    "X5",
    "A4X",
    "CT3",
    "CT3P",
    "CT5L",
    "CT5LP",
    "CT5P",
    "CT6E",
    "TPU7",
    "TPU7X",
}

_thread_local = threading.local()


def _sess() -> requests.Session:
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        s.mount("https://", HTTPAdapter(pool_connections=16, pool_maxsize=16))
        _thread_local.session = s
    return s


def get_adc_token() -> str:
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    if not creds.token:
        raise RuntimeError(
            "Unable to obtain GCP access token via Application Default Credentials."
        )
    return creds.token


def _classify_shape(name: str) -> str:
    low = name.lower()
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


def discover_regions_and_shapes(
    token: str, project: str, region_filter: list[str] | None
) -> tuple[dict[str, list[str]], dict[str, list[dict[str, Any]]]]:
    headers = {"Authorization": f"Bearer {token}"}
    reg_resp = _sess().get(
        f"{COMPUTE_V1}/projects/{project}/regions", headers=headers, timeout=20
    )
    reg_resp.raise_for_status()
    zone_map: dict[str, list[str]] = {}
    pairs: list[tuple[str, str]] = []
    want_set = set(region_filter) if region_filter else None
    for reg in reg_resp.json().get("items", []):
        rname = reg["name"]
        if want_set is not None and rname not in want_set:
            continue
        zones = sorted(z.split("/")[-1] for z in reg.get("zones", []))
        zone_map[rname] = zones
        for z in zones:
            pairs.append((rname, z))

    def _fetch(pair: tuple[str, str]) -> tuple[str, str, list[dict[str, Any]]]:
        rname, z = pair
        items: list[dict[str, Any]] = []
        pt = None
        while True:
            params: dict[str, Any] = {
                "maxResults": 500,
                "fields": "nextPageToken,items(name,guestCpus,memoryMb)",
            }
            if pt:
                params["pageToken"] = pt
            r = _sess().get(
                f"{COMPUTE_V1}/projects/{project}/zones/{z}/machineTypes",
                headers=headers,
                params=params,
                timeout=15,
            )
            if r.status_code != 200:
                break
            d = r.json()
            items.extend(d.get("items", []))
            pt = d.get("nextPageToken")
            if not pt:
                break
        return rname, z, items

    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as pool:
        rows = list(pool.map(_fetch, pairs))

    series_map: dict[str, dict[str, dict[str, Any]]] = {}
    for rname, z, items in rows:
        for mt in items:
            mname = mt["name"]
            if "-metal" in mname:
                continue
            fam = mname.split("-")[0].upper()
            if fam in SPOT_UNSUPPORTED_SERIES:
                continue
            fdict = series_map.setdefault(fam, {})
            if mname not in fdict:
                fdict[mname] = {
                    "type": mname,
                    "vcpus": int(mt.get("guestCpus", 0) or 0),
                    "shape_class": _classify_shape(mname),
                    "zones_by_region": {},
                }
            fdict[mname]["zones_by_region"].setdefault(rname, []).append(z)

    out_shapes = {
        fam: sorted(
            vals.values(), key=lambda x: (x["vcpus"], x["type"]), reverse=True
        )
        for fam, vals in series_map.items()
    }
    return zone_map, out_shapes


def query_capacity(
    token: str,
    project: str,
    region: str,
    machine_type: str,
    size: int,
    zone: str | None = None,
) -> tuple[bool, float, str]:
    url = f"{COMPUTE_BETA}/projects/{project}/regions/{region}/advice/capacity"
    dist_policy: dict[str, Any] = {"targetShape": "ANY"}
    if zone:
        dist_policy["zones"] = [{"zone": f"zones/{zone}"}]

    body = {
        "instanceProperties": {"scheduling": {"provisioningModel": "SPOT"}},
        "instanceFlexibilityPolicy": {
            "instanceSelections": {"default": {"machineTypes": [machine_type]}}
        },
        "distributionPolicy": dist_policy,
        "size": max(1, min(1000, int(size))),
    }
    r = None
    for attempt in range(3):
        r = _sess().post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=15,
        )
        if r.status_code in (429, 500, 502, 503) and attempt < 2:
            time.sleep(0.25 * (2**attempt))
            continue
        break
    if r is None or r.status_code != 200:
        return False, 0.0, ""
    recs = r.json().get("recommendations", [])
    if not recs:
        return True, 0.0, ""
    scores = recs[0].get("scores", {})
    return (
        True,
        float(scores.get("obtainability", 0.0) or 0.0),
        scores.get("estimatedUptime", ""),
    )


def query_history(
    token: str, project: str, region: str, machine_type: str
) -> tuple[float | None, float | None]:
    url = f"{COMPUTE_BETA}/projects/{project}/regions/{region}/advice/capacityHistory"
    body = {
        "instanceProperties": {
            "machineType": machine_type,
            "scheduling": {"provisioningModel": "SPOT"},
        },
        "types": ["PREEMPTION", "PRICE"],
    }
    r = _sess().post(
        url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=12
    )
    if r.status_code != 200:
        return None, None
    data = r.json()
    preemptions = data.get("preemptionHistory", [])
    latest_preempt = (
        round(float(preemptions[-1]["preemptionRate"]) * 100.0, 2)
        if preemptions and preemptions[-1].get("preemptionRate") is not None
        else None
    )
    prices = sorted(
        data.get("priceHistory", []),
        key=lambda x: x.get("interval", {}).get("startTime", ""),
    )
    latest_price = None
    if prices:
        lp = prices[-1].get("listPrice", {})
        if lp:
            latest_price = round(
                float(lp.get("units", 0) or 0)
                + float(lp.get("nanos", 0) or 0) / 1e9,
                5,
            )
    return latest_preempt, latest_price


def binary_search_pool(
    token: str,
    project: str,
    region: str,
    machine_type: str,
    min_score: float,
    zone: str | None = None,
) -> tuple[bool, int, float, str]:
    ok, obt1000, up1000 = query_capacity(
        token, project, region, machine_type, 1000, zone=zone
    )
    if not ok:
        return False, 0, 0.0, ""
    if obt1000 >= min_score:
        return True, 1000, obt1000, up1000

    _, obt10, up10 = query_capacity(
        token, project, region, machine_type, 10, zone=zone
    )
    if obt10 < min_score:
        return True, 0, obt1000, up1000

    lo, hi, best_vms, best_obt, best_up = 10, 1000, 10, obt10, up10
    while (hi - lo) > 30:
        mid = (lo + hi) // 2
        _, obt, up = query_capacity(
            token, project, region, machine_type, mid, zone=zone
        )
        if obt >= min_score:
            lo, best_vms, best_obt, best_up = mid, mid, obt, up
        else:
            hi = mid
    return True, best_vms, best_obt, best_up


def scan_region_family(
    token: str,
    project: str,
    region: str,
    family: str,
    shapes: list[dict[str, Any]],
    min_score: float,
    per_zone: bool,
    shape_profile: str,
) -> dict[str, Any] | None:
    in_reg = [sh for sh in shapes if region in sh["zones_by_region"]]
    if not in_reg:
        return None

    def _pref(sh: dict[str, Any]) -> tuple[int, int, str]:
        sc = sh["shape_class"]
        if shape_profile == "highmem":
            b = 3 if sc == "highmem" else (2 if sc == "standard" else 1)
        elif shape_profile == "highcpu":
            b = 3 if sc == "highcpu" else (2 if sc == "standard" else 1)
        elif shape_profile == "lssd":
            b = 3 if sc == "lssd" else 1
        elif shape_profile == "largest":
            b = 1
        else:
            b = 3 if sc in ("standard", "gpu") else (2 if sc != "lssd" else 1)
        return (b, sh["vcpus"], sh["type"])

    ordered = sorted(in_reg, key=_pref, reverse=True)
    chosen = None
    reg_res = None

    seen: set[tuple[str, int]] = set()
    walk: list[dict[str, Any]] = []
    for sh in ordered:
        k = (sh["shape_class"], sh["vcpus"])
        if k not in seen:
            seen.add(k)
            walk.append(sh)

    for sh in walk[:5]:
        ok, max_vms, obt, uptime = binary_search_pool(
            token, project, region, sh["type"], min_score
        )
        if ok:
            chosen = sh
            reg_res = (max_vms, obt, uptime)
            if max_vms == 0 and sh["vcpus"] > 128:
                smaller = [s for s in walk if s["vcpus"] <= 128]
                if smaller:
                    ok2, v2, o2, u2 = binary_search_pool(
                        token, project, region, smaller[0]["type"], min_score
                    )
                    if ok2 and v2 > 0:
                        chosen = smaller[0]
                        reg_res = (v2, o2, u2)
            break

    if not chosen or not reg_res:
        return None

    mtype = chosen["type"]
    vcpus = chosen["vcpus"]
    total_vms, best_obt, uptime = reg_res
    zones = chosen["zones_by_region"].get(region, [])

    if per_zone and zones and total_vms > 0:
        z_total = 0
        weighted_obt = 0.0
        for z in sorted(zones):
            _, zvms, zobt, _ = binary_search_pool(
                token, project, region, mtype, min_score, zone=z
            )
            if zvms > 0:
                z_total += zvms
                weighted_obt += zobt * zvms
        if z_total > total_vms:
            total_vms = z_total
            best_obt = round(weighted_obt / z_total, 3)

    preempt_30d, vm_price_hr = query_history(token, project, region, mtype)
    vcpu_price_hr = (
        round(vm_price_hr / vcpus, 5) if (vm_price_hr and vcpus > 0) else None
    )

    return {
        "region": region,
        "family": family,
        "top_shape": mtype,
        "vcpus_per_vm": vcpus,
        "max_obtainable_vms": total_vms,
        "safe_obtainable_vcpus": total_vms * vcpus,
        "obtainability_score": best_obt,
        "preemption_rate_30d_pct": preempt_30d,
        "spot_usd_per_vcpu_hr": vcpu_price_hr,
        "estimated_uptime": uptime,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GCP Spot Capacity Advisor Top-Down Multi-Region Scanner"
    )
    parser.add_argument("--project", required=True, help="GCP Project ID")
    parser.add_argument(
        "--regions",
        default="asia-east1,asia-south1,asia-southeast1,asia-northeast1,asia-northeast2,europe-west4,europe-west1",
        help="Comma-separated GCP regions or ALL for every live GCP region",
    )
    parser.add_argument(
        "--families",
        default="N4,C4D,C4,N2D,C3D",
        help="Comma-separated machine families or ALL for all Spot-supported families",
    )
    parser.add_argument(
        "--shape-profile",
        default="standard",
        choices=["standard", "highmem", "highcpu", "lssd", "largest"],
        help="Shape tier preference per family (default: standard)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.5,
        help="Minimum obtainability score threshold (default: 0.5)",
    )
    parser.add_argument(
        "--per-zone",
        action="store_true",
        help="Unlock >1,000 VMs/region by probing individual zones independently",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    token = get_adc_token()
    reg_filter = (
        None
        if args.regions.strip().upper() == "ALL"
        else [r.strip() for r in args.regions.split(",") if r.strip()]
    )
    zone_map, all_shapes = discover_regions_and_shapes(
        token, args.project, reg_filter
    )
    regions = sorted(zone_map.keys())
    families = (
        sorted(all_shapes.keys())
        if args.families.strip().upper() == "ALL"
        else [f.strip().upper() for f in args.families.split(",") if f.strip()]
    )

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as pool:
        futs = [
            pool.submit(
                scan_region_family,
                token,
                args.project,
                r,
                fam,
                all_shapes.get(fam, []),
                args.min_score,
                args.per_zone,
                args.shape_profile,
            )
            for r in regions
            for fam in families
        ]
        for fut in concurrent.futures.as_completed(futs):
            row = fut.result()
            if row is not None:
                results.append(row)

    results.sort(
        key=lambda x: (x["safe_obtainable_vcpus"], x["obtainability_score"]),
        reverse=True,
    )

    if args.json:
        print(json.dumps(results, indent=2))
        return

    total_vcpus = sum(r["safe_obtainable_vcpus"] for r in results)
    print(
        f"\nSafe Non-Overlapping Spot vCPUs Across {len(regions)} Region(s) / "
        f"{len(families)} Family(ies): {total_vcpus:,}\n"
    )
    print(
        f"{'REGION':20s} {'FAM':5s} {'TOP SHAPE':26s} {'MAX VMs':>8s} "
        f"{'SAFE vCPUs':>12s} {'SCORE':>6s} {'30d PREEMPT':>12s} {'$/vCPU-hr':>10s}"
    )
    print("-" * 108)
    for r in results:
        p30 = (
            f"{r['preemption_rate_30d_pct']:.1f}%"
            if r["preemption_rate_30d_pct"] is not None
            else "—"
        )
        usd = (
            f"${r['spot_usd_per_vcpu_hr']:.4f}"
            if r["spot_usd_per_vcpu_hr"] is not None
            else "—"
        )
        print(
            f"{r['region']:20s} {r['family']:5s} {r['top_shape']:26s} "
            f"{r['max_obtainable_vms']:8,d} {r['safe_obtainable_vcpus']:12,d} "
            f"{r['obtainability_score']:6.2f} {p30:>12s} {usd:>10s}"
        )


if __name__ == "__main__":
    main()
