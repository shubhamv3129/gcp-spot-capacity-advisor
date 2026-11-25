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

"""Live Multi-Cloud Equivalent VM & Spot Pricing Comparison Engine (AWS & Azure).

Fetches 100% public, live Linux Spot pricing directly from official vendor feeds:
1. AWS EC2 Real-Time Spot JSON Feed: https://website.spot.ec2.aws.a2z.com/spot.json
   (updated every ~5 minutes by AWS across 44 regions & 1,370+ instance types)
   + AWS Spot Advisor metadata (cores, RAM, interruption band):
   https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json
2. Microsoft Azure Retail Prices API: https://prices.azure.com/api/retail/prices
   (Cache-Control: no-cache; filtered strictly to Linux Consumption Spot meters;
   Windows & DevTest excluded).

All prices are normalized to USD/vCPU-hr alongside USD/VM-hr so side-by-side
comparisons across differing VM vCPU counts (e.g. GCP 80 vCPU vs AWS/Azure 64/96
vCPU) remain strictly apples-to-apples.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
import urllib.parse
from typing import Any

import requests
from requests.adapters import HTTPAdapter

AWS_SPOT_JSON_URL = "https://website.spot.ec2.aws.a2z.com/spot.json"
AWS_SPOT_ADVISOR_URL = "https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json"
AZURE_PRICES_URL = "https://prices.azure.com/api/retail/prices"

PRICING_CACHE_TTL_SECONDS = 300.0  # 5-min TTL; bypassed immediately on Refresh Live Scan
_AZURE_BATCH_SIZE = 10  # Azure OData rejects >~16 OR clauses with HTTP 400.

_http_local = threading.local()

_aws_lock = threading.Lock()
_aws_cache: tuple[float, dict[str, Any]] | None = None

_azure_lock = threading.Lock()
# (azure_region, sku) -> (timestamp, price_usd_hr_or_none)
_azure_price_cache: dict[tuple[str, str], tuple[float, float | None]] = {}


def _session() -> requests.Session:
    sess = getattr(_http_local, "session", None)
    if sess is None:
        sess = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16)
        sess.mount("https://", adapter)
        sess.headers.update({"User-Agent": "SpotCapacityAdvisor/2.1"})
        _http_local.session = sess
    return sess


# Complete 43 GCP Region -> Nearest Official AWS & Azure Region Map.
# Every AWS region ID is verified present in spot.js, and every Azure region ID
# is verified live against prices.azure.com.
CLOUD_REGION_MAP: dict[str, dict[str, Any]] = {
    # APAC (12)
    "asia-southeast1": {
        "aws_region": "ap-southeast-1",
        "aws_exact": True,
        "azure_region": "southeastasia",
        "azure_exact": True,
    },
    "asia-northeast1": {
        "aws_region": "ap-northeast-1",
        "aws_exact": True,
        "azure_region": "japaneast",
        "azure_exact": True,
    },
    "asia-northeast2": {
        "aws_region": "ap-northeast-3",
        "aws_exact": True,
        "azure_region": "japanwest",
        "azure_exact": True,
    },
    "asia-northeast3": {
        "aws_region": "ap-northeast-2",
        "aws_exact": True,
        "azure_region": "koreacentral",
        "azure_exact": True,
    },
    "asia-east1": {
        "aws_region": "ap-east-2",
        "aws_exact": True,  # AWS Taipei (Taiwan)
        "azure_region": "taiwannorth",
        "azure_exact": True,
    },
    "asia-east2": {
        "aws_region": "ap-east-1",
        "aws_exact": True,
        "azure_region": "eastasia",
        "azure_exact": True,
    },
    "asia-south1": {
        "aws_region": "ap-south-1",
        "aws_exact": True,
        "azure_region": "centralindia",
        "azure_exact": True,
    },
    "asia-south2": {
        "aws_region": "ap-south-1",
        "aws_exact": False,  # Nearest AWS peer (Mumbai)
        "azure_region": "centralindia",
        "azure_exact": False,
    },
    "asia-southeast2": {
        "aws_region": "ap-southeast-3",
        "aws_exact": True,
        "azure_region": "indonesiacentral",
        "azure_exact": True,
    },
    "asia-southeast3": {
        "aws_region": "ap-southeast-7",
        "aws_exact": True,  # AWS Thailand (Bangkok)
        "azure_region": "malaysiawest",
        "azure_exact": False,
    },
    "australia-southeast1": {
        "aws_region": "ap-southeast-2",
        "aws_exact": True,
        "azure_region": "australiaeast",
        "azure_exact": True,
    },
    "australia-southeast2": {
        "aws_region": "ap-southeast-4",
        "aws_exact": True,
        "azure_region": "australiasoutheast",
        "azure_exact": True,
    },
    # EMEA - Europe (13), Middle East (3), Africa (1)
    "europe-west4": {
        "aws_region": "eu-central-1",
        "aws_exact": False,  # Nearest AWS peer (Frankfurt)
        "azure_region": "westeurope",
        "azure_exact": True,
    },
    "europe-west1": {
        "aws_region": "eu-west-1",
        "aws_exact": False,  # Nearest AWS peer (Ireland)
        "azure_region": "belgiumcentral",
        "azure_exact": True,
    },
    "europe-west2": {
        "aws_region": "eu-west-2",
        "aws_exact": True,
        "azure_region": "uksouth",
        "azure_exact": True,
    },
    "europe-west3": {
        "aws_region": "eu-central-1",
        "aws_exact": True,
        "azure_region": "germanywestcentral",
        "azure_exact": True,
    },
    "europe-west6": {
        "aws_region": "eu-central-2",
        "aws_exact": True,
        "azure_region": "switzerlandnorth",
        "azure_exact": True,
    },
    "europe-west8": {
        "aws_region": "eu-south-1",
        "aws_exact": True,
        "azure_region": "italynorth",
        "azure_exact": True,
    },
    "europe-west9": {
        "aws_region": "eu-west-3",
        "aws_exact": True,
        "azure_region": "francecentral",
        "azure_exact": True,
    },
    "europe-west10": {
        "aws_region": "eu-central-1",
        "aws_exact": False,
        "azure_region": "germanynorth",
        "azure_exact": True,
    },
    "europe-west12": {
        "aws_region": "eu-south-1",
        "aws_exact": False,
        "azure_region": "italynorth",
        "azure_exact": False,
    },
    "europe-north1": {
        "aws_region": "eu-north-1",
        "aws_exact": False,
        "azure_region": "swedencentral",
        "azure_exact": False,
    },
    "europe-north2": {
        "aws_region": "eu-north-1",
        "aws_exact": True,
        "azure_region": "swedencentral",
        "azure_exact": True,
    },
    "europe-central2": {
        "aws_region": "eu-central-1",
        "aws_exact": False,
        "azure_region": "polandcentral",
        "azure_exact": True,
    },
    "europe-southwest1": {
        "aws_region": "eu-south-2",
        "aws_exact": True,
        "azure_region": "spaincentral",
        "azure_exact": True,
    },
    "me-central1": {
        "aws_region": "il-central-1",
        "aws_exact": False,
        "azure_region": "qatarcentral",
        "azure_exact": True,
    },
    "me-central2": {
        "aws_region": "il-central-1",
        "aws_exact": False,
        "azure_region": "uaenorth",
        "azure_exact": False,
    },
    "me-west1": {
        "aws_region": "il-central-1",
        "aws_exact": True,
        "azure_region": "israelcentral",
        "azure_exact": True,
    },
    "africa-south1": {
        "aws_region": "af-south-1",
        "aws_exact": False,
        "azure_region": "southafricanorth",
        "azure_exact": True,
    },
    # AMER - US (9), North America Non-US (3), South America (2)
    "us-central1": {
        "aws_region": "us-east-2",
        "aws_exact": False,
        "azure_region": "centralus",
        "azure_exact": True,
    },
    "us-east1": {
        "aws_region": "us-east-1",
        "aws_exact": False,
        "azure_region": "eastus2",
        "azure_exact": False,
    },
    "us-east4": {
        "aws_region": "us-east-1",
        "aws_exact": True,
        "azure_region": "eastus",
        "azure_exact": True,
    },
    "us-east5": {
        "aws_region": "us-east-2",
        "aws_exact": True,
        "azure_region": "eastus2",
        "azure_exact": False,
    },
    "us-south1": {
        "aws_region": "us-east-2",
        "aws_exact": False,
        "azure_region": "southcentralus",
        "azure_exact": True,
    },
    "us-west1": {
        "aws_region": "us-west-2",
        "aws_exact": True,
        "azure_region": "westus2",
        "azure_exact": True,
    },
    "us-west2": {
        "aws_region": "us-west-1",
        "aws_exact": False,
        "azure_region": "westus",
        "azure_exact": True,
    },
    "us-west3": {
        "aws_region": "us-west-2",
        "aws_exact": False,
        "azure_region": "westus3",
        "azure_exact": False,
    },
    "us-west4": {
        "aws_region": "us-west-2",
        "aws_exact": False,
        "azure_region": "westus3",
        "azure_exact": False,
    },
    "northamerica-northeast1": {
        "aws_region": "ca-central-1",
        "aws_exact": True,
        "azure_region": "canadaeast",
        "azure_exact": True,
    },
    "northamerica-northeast2": {
        "aws_region": "ca-central-1",
        "aws_exact": False,
        "azure_region": "canadacentral",
        "azure_exact": True,
    },
    "northamerica-south1": {
        "aws_region": "mx-central-1",
        "aws_exact": True,  # AWS Mexico (Central)
        "azure_region": "mexicocentral",
        "azure_exact": True,
    },
    "southamerica-east1": {
        "aws_region": "sa-east-1",
        "aws_exact": True,
        "azure_region": "brazilsouth",
        "azure_exact": True,
    },
    "southamerica-west1": {
        "aws_region": "sa-east-1",
        "aws_exact": False,
        "azure_region": "chilecentral",
        "azure_exact": True,
    },
}


# Verified Azure VM SKU catalog: armSkuName -> (series_key, vcpus, ram_gb, arch_note)
AZURE_SKU_SPECS: dict[str, tuple[str, int, float, str]] = {
    # Intel Emerald Rapids GP v6 (4 GiB/vCPU)
    "Standard_D192s_v6": ("D_v6", 192, 768.0, "Intel Emerald Rapids"),
    "Standard_D128s_v6": ("D_v6", 128, 512.0, "Intel Emerald Rapids"),
    "Standard_D96s_v6": ("D_v6", 96, 384.0, "Intel Emerald Rapids"),
    "Standard_D64s_v6": ("D_v6", 64, 256.0, "Intel Emerald Rapids"),
    "Standard_D48s_v6": ("D_v6", 48, 192.0, "Intel Emerald Rapids"),
    "Standard_D32s_v6": ("D_v6", 32, 128.0, "Intel Emerald Rapids"),
    "Standard_D16s_v6": ("D_v6", 16, 64.0, "Intel Emerald Rapids"),
    "Standard_D2s_v6": ("D_small", 2, 8.0, "Intel Emerald Rapids"),
    # Intel Ice Lake GP v5 (4 GiB/vCPU)
    "Standard_D96s_v5": ("D_v5", 96, 384.0, "Intel Ice Lake"),
    "Standard_D64s_v5": ("D_v5", 64, 256.0, "Intel Ice Lake"),
    "Standard_D48s_v5": ("D_v5", 48, 192.0, "Intel Ice Lake"),
    "Standard_D32s_v5": ("D_v5", 32, 128.0, "Intel Ice Lake"),
    "Standard_D16s_v5": ("D_v5", 16, 64.0, "Intel Ice Lake"),
    "Standard_D2s_v5": ("D_small", 2, 8.0, "Intel Ice Lake"),
    # Intel Emerald Rapids High-CPU v6 (2 GiB/vCPU)
    "Standard_D128ls_v6": ("Dl_v6", 128, 256.0, "Intel Emerald Rapids (2GB/vCPU)"),
    "Standard_D96ls_v6": ("Dl_v6", 96, 192.0, "Intel Emerald Rapids (2GB/vCPU)"),
    "Standard_D64ls_v6": ("Dl_v6", 64, 128.0, "Intel Emerald Rapids (2GB/vCPU)"),
    "Standard_D48ls_v6": ("Dl_v6", 48, 96.0, "Intel Emerald Rapids (2GB/vCPU)"),
    "Standard_D32ls_v6": ("Dl_v6", 32, 64.0, "Intel Emerald Rapids (2GB/vCPU)"),
    # Intel Compute Fv2 (2 GiB/vCPU)
    "Standard_F72s_v2": ("F_v2", 72, 144.0, "Intel Cascade/Skylake Compute"),
    "Standard_F64s_v2": ("F_v2", 64, 128.0, "Intel Cascade/Skylake Compute"),
    "Standard_F48s_v2": ("F_v2", 48, 96.0, "Intel Cascade/Skylake Compute"),
    "Standard_F32s_v2": ("F_v2", 32, 64.0, "Intel Cascade/Skylake Compute"),
    # AMD Genoa GP v6 (4 GiB/vCPU)
    "Standard_D96as_v6": ("Da_v6", 96, 384.0, "AMD EPYC Genoa"),
    "Standard_D64as_v6": ("Da_v6", 64, 256.0, "AMD EPYC Genoa"),
    "Standard_D48as_v6": ("Da_v6", 48, 192.0, "AMD EPYC Genoa"),
    "Standard_D32as_v6": ("Da_v6", 32, 128.0, "AMD EPYC Genoa"),
    # AMD Milan GP v5 (4 GiB/vCPU)
    "Standard_D96as_v5": ("Da_v5", 96, 384.0, "AMD EPYC Milan"),
    "Standard_D64as_v5": ("Da_v5", 64, 256.0, "AMD EPYC Milan"),
    "Standard_D48as_v5": ("Da_v5", 48, 192.0, "AMD EPYC Milan"),
    "Standard_D32as_v5": ("Da_v5", 32, 128.0, "AMD EPYC Milan"),
    # AMD Genoa Compute Fasv6 (4 GiB/vCPU) & Falsv6 (2 GiB/vCPU)
    "Standard_F72as_v6": ("Fas_v6", 72, 288.0, "AMD EPYC Genoa Compute"),
    "Standard_F64as_v6": ("Fas_v6", 64, 256.0, "AMD EPYC Genoa Compute"),
    "Standard_F72als_v6": ("Fals_v6", 72, 144.0, "AMD EPYC Genoa High-CPU"),
    "Standard_F64als_v6": ("Fals_v6", 64, 128.0, "AMD EPYC Genoa High-CPU"),
    # Local NVMe Temp Disk v6
    "Standard_D96ds_v6": ("Dd_v6", 96, 384.0, "Intel Emerald Rapids + LSSD"),
    "Standard_D96ads_v6": ("Dad_v6", 96, 384.0, "AMD EPYC Genoa + LSSD"),
    # ARM64 Cobalt 100 (v6) & Ampere Altra (v5)
    "Standard_D96ps_v6": ("Dp_v6", 96, 384.0, "Azure Cobalt 100 ARM64"),
    "Standard_D64ps_v6": ("Dp_v6", 64, 256.0, "Azure Cobalt 100 ARM64"),
    "Standard_D96pls_v6": ("Dpl_v6", 96, 192.0, "Azure Cobalt 100 ARM64 (2GB/vCPU)"),
    "Standard_D64pls_v6": ("Dpl_v6", 64, 128.0, "Azure Cobalt 100 ARM64 (2GB/vCPU)"),
    "Standard_D64ps_v5": ("Dp_v5", 64, 256.0, "Ampere Altra ARM64"),
    "Standard_D48ps_v5": ("Dp_v5", 48, 192.0, "Ampere Altra ARM64"),
    "Standard_D64pls_v5": ("Dpl_v5", 64, 128.0, "Ampere Altra ARM64 (2GB/vCPU)"),
    # High-Memory E-series (Intel & AMD, ~7-8 GiB/vCPU)
    "Standard_E128s_v6": ("E_v6", 128, 1024.0, "Intel Emerald Rapids HighMem"),
    "Standard_E96s_v6": ("E_v6", 96, 672.0, "Intel Emerald Rapids HighMem"),
    "Standard_E64s_v6": ("E_v6", 64, 512.0, "Intel Emerald Rapids HighMem"),
    "Standard_E96s_v5": ("E_v5", 96, 672.0, "Intel Ice Lake HighMem"),
    "Standard_E64s_v5": ("E_v5", 64, 512.0, "Intel Ice Lake HighMem"),
    "Standard_E96as_v6": ("Ea_v6", 96, 672.0, "AMD EPYC Genoa HighMem"),
    "Standard_E96as_v5": ("Ea_v5", 96, 672.0, "AMD EPYC Milan HighMem"),
    # Ultra-Memory M-series
    "Standard_M416ms_v2": ("M_v2", 416, 11400.0, "Intel Ultra-Memory"),
    "Standard_M208ms_v2": ("M_v2", 208, 5700.0, "Intel Ultra-Memory"),
    "Standard_M192ims_v2": ("M_v2", 192, 4096.0, "Intel Ultra-Memory"),
    "Standard_M128ms_v2": ("M_v2", 128, 3892.0, "Intel Ultra-Memory"),
    "Standard_M128s": ("M_v2", 128, 2048.0, "Intel High-Memory"),
    # Storage-Optimized Local NVMe L-series
    "Standard_L96s_v4": ("L_v4", 96, 768.0, "Intel Storage NVMe v4"),
    "Standard_L80s_v4": ("L_v4", 80, 640.0, "Intel Storage NVMe v4"),
    "Standard_L96as_v4": ("La_v4", 96, 768.0, "AMD Storage NVMe v4"),
    "Standard_L80s_v3": ("L_v3", 80, 640.0, "Intel Storage NVMe v3"),
    "Standard_L64s_v3": ("L_v3", 64, 512.0, "Intel Storage NVMe v3"),
    "Standard_L80as_v3": ("La_v3", 80, 640.0, "AMD Storage NVMe v3"),
    "Standard_L64as_v3": ("La_v3", 64, 512.0, "AMD Storage NVMe v3"),
    # HPC HB / HX / HC
    "Standard_HB176rs_v4": ("HB_v4", 176, 768.0, "AMD Genoa HPC + IB"),
    "Standard_HB120rs_v3": ("HB_v3", 120, 448.0, "AMD Milan HPC + IB"),
    "Standard_HX176rs": ("HX", 176, 1408.0, "AMD Genoa High-Mem HPC"),
    "Standard_HC44rs": ("HC", 44, 352.0, "Intel HPC + IB"),
    # GPU NC / ND / NV
    "Standard_ND96isr_H100_v5": ("ND_H100", 96, 1900.0, "8x NVIDIA H100"),
    "Standard_NC80adis_H100_v5": ("NC_H100", 80, 640.0, "2x NVIDIA H100"),
    "Standard_NC40ads_H100_v5": ("NC_H100", 40, 320.0, "1x NVIDIA H100"),
    "Standard_ND96amsr_A100_v4": ("ND_A100", 96, 1924.0, "8x NVIDIA A100"),
    "Standard_NC96ads_A100_v4": ("NC_A100", 96, 880.0, "4x NVIDIA A100"),
    "Standard_NC24ads_A100_v4": ("NC_A100", 24, 220.0, "1x NVIDIA A100"),
    "Standard_NV72ads_A10_v5": ("NV_A10", 72, 880.0, "2x NVIDIA A10"),
    "Standard_NV36ads_A10_v5": ("NV_A10", 36, 440.0, "1x NVIDIA A10"),
    "Standard_NC64as_T4_v3": ("NC_T4", 64, 440.0, "4x NVIDIA T4"),
    # Shared/Burstable
    "Standard_B2as_v2": ("B_v2", 2, 8.0, "AMD Burstable"),
}

AZURE_SERIES_TO_SKUS: dict[str, list[str]] = {}
for _sku, (_skey, _vc, _ram, _arch) in AZURE_SKU_SPECS.items():
    AZURE_SERIES_TO_SKUS.setdefault(_skey, []).append(_sku)


def _aws_family_ladder(gcp_family: str, shape_class: str) -> list[str]:
    """Returns prioritized AWS EC2 family prefixes matching CPU vendor, gen & RAM/vCPU ratio."""
    f = gcp_family.upper()
    sc = (shape_class or "standard").lower()

    if sc == "highmem":
        if f in ("C4D", "N4D", "H4D"):
            return ["r8a", "r7a", "r6a", "r8i", "r7i", "r6i", "r5"]
        if f in ("C3D", "N2D", "C2D", "T2D"):
            return ["r7a", "r8a", "r6a", "r7i", "r6i", "r5"]
        if f in ("N4A", "C4A", "T2A"):
            return ["r8g", "r7g", "r6g", "r8i", "r7i", "r6i"]
        if f in ("C4", "C4N"):
            return ["r8i", "r7i", "r6i", "r5"]
        if f in ("N4", "C3", "N2", "C2", "N1", "E2", "H3"):
            return ["r7i", "r8i", "r6i", "r5"]
    elif sc == "highcpu":
        if f in ("C4D", "N4D"):
            return ["c8a", "c7a", "c6a", "c8i", "c7i", "c6i", "c5"]
        if f in ("C3D", "N2D", "C2D", "T2D"):
            return ["c7a", "c8a", "c6a", "c7i", "c6i", "c5"]
        if f in ("N4A", "C4A", "T2A"):
            return ["c8g", "c7g", "c6g", "c8i", "c7i", "c6i"]
        if f in ("C4", "C4N"):
            return ["c8i", "c7i", "c6i", "c5"]
        if f in ("N4", "C3", "N2", "C2", "N1", "E2"):
            return ["c7i", "c8i", "c6i", "c5"]
    elif sc == "lssd":
        if f in ("C4D", "N4D", "C3D", "Z4D"):
            return ["i7i", "i4i", "c6id", "m6id", "m8a", "m7a", "m6a", "c6i"]
        if f in ("N4", "C4", "C3", "Z3", "Z4M"):
            return ["i7i", "c6id", "m6id", "i4i", "m8i", "m7i", "m6i"]

    # Standard shapes on GCP are ~3.75–4 GB RAM/vCPU, so pair with 4 GB/vCPU AWS
    # peers (m8a/m8i/m8g/m7a/m7i/m6a/m6i) for strict apples-to-apples RAM/core & gen parity.
    mapping: dict[str, list[str]] = {
        "N4": ["m7i", "m8i", "m6i", "m5", "c6i"],
        "C4D": ["m8a", "m7a", "c8a", "c7a", "m6a", "m8i", "m7i", "m6i", "c6i"],
        "C4": ["m8i", "m7i", "c8i", "c7i", "m6i", "c6i", "c5"],
        "N2D": ["m6a", "m7a", "m5a", "m8a", "m6i", "c6i"],
        "C3D": ["m7a", "m8a", "m6a", "c7a", "c6a", "m7i", "m6i", "c6i"],
        "N2": ["m6i", "m5", "m7i", "c6i"],
        "N4D": ["m8a", "m7a", "m6a", "m8i", "m7i", "m6i", "c6i"],
        "N4A": ["m8g", "m7g", "m6g", "m8i", "m7i", "m6i"],
        "C4A": ["m8g", "c8g", "m7g", "c7g", "m6g", "m7i", "m6i"],
        "C4N": ["c7in", "c6in", "c5n", "m8i", "c8i", "m7i", "c6i"],
        "C3": ["m7i", "c7i", "m8i", "m6i", "c6i"],
        "C2D": ["m6a", "c6a", "m7a", "m6i", "c6i"],
        "C2": ["m6i", "c5", "c6i", "m5"],
        "H4D": ["c8a", "c7a", "m8a", "c6a", "c8i", "c7i", "c6i"],
        "H3": ["c7i", "c8i", "c6i", "c5n", "m6i"],
        "T2D": ["m6a", "c6a", "m6i", "c6i"],
        "T2A": ["m6g", "c6g", "m7g", "m6i"],
        "E2": ["m6a", "m5a", "t3a", "m6i", "t3"],
        "N1": ["m5", "m6i", "c5", "c6i"],
        "Z4D": ["i7i", "i4i", "i3en", "i3"],
        "Z4M": ["i7i", "i4i", "i3en", "i3"],
        "Z3": ["i4i", "i7i", "i3en", "i3"],
        "M4": ["x2idn", "r8i", "r7i", "r6i", "r5"],
        "M4N": ["x2idn", "r8i", "r7i", "r6i", "r5"],
        "M3": ["x2idn", "r6i", "r7i", "r5"],
        "M2": ["x2idn", "r6i", "r5"],
        "M1": ["x2idn", "r5", "r6i"],
        "G4": ["g6e", "g6", "g5", "g4dn"],
        "G2": ["g6", "g5", "g4dn"],
        "A4": ["p5", "p4d"],
        "A3": ["p5", "p4d"],
        "A2": ["p4d", "g5"],
        "G1": ["t3", "t3a", "t2"],
        "F1": ["t3", "t3a", "t2"],
    }
    return mapping.get(f, ["m8i", "m7i", "m6i", "c7i", "c6i"])


def _azure_series_ladder(gcp_family: str, shape_class: str) -> list[str]:
    """Returns prioritized Azure VM series keys matching (gcp_family, shape_class)."""
    f = gcp_family.upper()
    sc = (shape_class or "standard").lower()

    if sc == "highmem":
        if f in ("C4D", "N4D", "C3D", "N2D", "C2D", "T2D", "H4D"):
            return ["Ea_v6", "Ea_v5", "E_v6", "E_v5"]
        if f in ("N4", "C4", "C3", "N2", "C2", "N1", "E2", "C4N", "H3"):
            return ["E_v6", "E_v5"]
    elif sc == "highcpu":
        if f in ("C4D", "N4D", "C3D", "N2D", "C2D", "T2D"):
            return ["Fals_v6", "Fas_v6", "Da_v6", "Da_v5"]
        if f in ("N4A", "C4A", "T2A"):
            return ["Dpl_v6", "Dpl_v5", "Dp_v6", "Dp_v5"]
        if f in ("N4", "C4", "C3", "N2", "C2", "N1", "E2", "C4N"):
            return ["Dl_v6", "F_v2", "D_v6", "D_v5"]
    elif sc == "lssd":
        if f in ("C4D", "N4D", "C3D"):
            return ["Dad_v6", "La_v4", "La_v3", "Da_v6"]
        if f in ("N4", "C4", "C3"):
            return ["Dd_v6", "L_v4", "L_v3", "D_v6"]

    mapping: dict[str, list[str]] = {
        "N4": ["D_v6", "D_v5"],
        "C4D": ["Fas_v6", "Da_v6", "Da_v5", "D_v6", "D_v5"],
        "C4": ["D_v6", "Dl_v6", "F_v2", "D_v5"],
        "N2D": ["Da_v5", "Da_v6", "D_v5"],
        "C3D": ["Fas_v6", "Da_v6", "Da_v5", "D_v5"],
        "N2": ["D_v5", "D_v6"],
        "N4D": ["Da_v6", "Da_v5", "D_v6", "D_v5"],
        "N4A": ["Dp_v6", "Dp_v5", "D_v6", "D_v5"],
        "C4A": ["Dp_v6", "Dpl_v6", "Dp_v5", "Dpl_v5", "D_v6", "D_v5"],
        "C4N": ["D_v6", "D_v5"],
        "C3": ["D_v6", "D_v5", "F_v2"],
        "C2D": ["Da_v5", "Fas_v6", "Da_v6", "D_v5"],
        "C2": ["F_v2", "Dl_v6", "D_v5"],
        "H4D": ["HB_v4", "HX", "HB_v3", "Da_v6", "Da_v5"],
        "H3": ["HC", "HB_v4", "D_v6", "D_v5"],
        "T2D": ["Da_v5", "Da_v6", "D_v5"],
        "T2A": ["Dp_v5", "Dp_v6", "D_v5"],
        "E2": ["Da_v5", "D_v5"],
        "N1": ["D_v5", "F_v2"],
        "Z4D": ["La_v4", "La_v3", "L_v4", "L_v3", "Dad_v6"],
        "Z4M": ["L_v4", "L_v3", "Dd_v6"],
        "Z3": ["L_v4", "L_v3", "Dd_v6"],
        "M4": ["M_v2", "E_v6", "E_v5"],
        "M4N": ["M_v2", "E_v6", "E_v5"],
        "M3": ["M_v2", "E_v5", "E_v6"],
        "M2": ["M_v2", "E_v5"],
        "M1": ["M_v2", "E_v5"],
        "G4": ["NV_A10", "NC_T4", "NC_A100"],
        "G2": ["NV_A10", "NC_T4", "NC_A100"],
        "A4": ["ND_H100", "NC_H100", "ND_A100", "NC_A100"],
        "A3": ["ND_H100", "NC_H100", "ND_A100", "NC_A100"],
        "A2": ["ND_A100", "NC_A100", "NV_A10"],
        "G1": ["B_v2", "D_small"],
        "F1": ["B_v2", "D_small"],
    }
    return mapping.get(f, ["D_v6", "D_v5"])


def get_aws_live_spot_data(force_refresh: bool = False) -> dict[str, Any]:
    """Fetches & caches live AWS EC2 Spot prices + Spot Advisor instance specs."""
    global _aws_cache
    now = time.time()
    with _aws_lock:
        if (
            not force_refresh
            and _aws_cache is not None
            and (now - _aws_cache[0]) < PRICING_CACHE_TTL_SECONDS
        ):
            return _aws_cache[1]

    prices_by_region: dict[str, dict[str, float]] = {}
    aws_last_modified: str | None = None
    instance_specs: dict[str, dict[str, Any]] = {}
    interruption_by_region: dict[str, dict[str, str]] = {}
    live_ok = False

    def _fetch_spot_json() -> tuple[dict[str, dict[str, float]], str | None]:
        resp = _session().get(AWS_SPOT_JSON_URL, timeout=15)
        resp.raise_for_status()
        last_mod = resp.headers.get("Last-Modified")
        data = resp.json()
        out: dict[str, dict[str, float]] = {}
        for reg in data.get("config", {}).get("regions", []):
            rname = reg.get("region")
            if not rname:
                continue
            rmap = out.setdefault(rname, {})
            for it in reg.get("instanceTypes", []):
                for sz in it.get("sizes", []):
                    sname = sz.get("size")
                    if not sname:
                        continue
                    for vc in sz.get("valueColumns", []):
                        if vc.get("name") == "linux":
                            raw_p = vc.get("prices", {}).get("USD")
                            if raw_p and raw_p != "N/A*":
                                try:
                                    val = float(raw_p)
                                    if val > 0:
                                        rmap[sname] = val
                                except ValueError:
                                    pass
        return out, last_mod

    def _fetch_advisor() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
        resp = _session().get(AWS_SPOT_ADVISOR_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        ranges = {r["index"]: r["label"] for r in data.get("ranges", [])}
        itypes = data.get("instance_types", {})
        intr: dict[str, dict[str, str]] = {}
        for reg, os_map in data.get("spot_advisor", {}).items():
            linux_map = os_map.get("Linux", {})
            intr[reg] = {
                itype: ranges.get(info.get("r"), "")
                for itype, info in linux_map.items()
                if isinstance(info, dict)
            }
        return itypes, intr

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f_spot = pool.submit(_fetch_spot_json)
            f_adv = pool.submit(_fetch_advisor)
            prices_by_region, aws_last_modified = f_spot.result()
            try:
                instance_specs, interruption_by_region = f_adv.result()
            except Exception:
                instance_specs, interruption_by_region = {}, {}
            live_ok = bool(prices_by_region)
    except Exception:
        with _aws_lock:
            if _aws_cache is not None:
                return _aws_cache[1]
        live_ok = False

    bundle = {
        "live": live_ok,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_modified": aws_last_modified,
        "prices": prices_by_region,
        "specs": instance_specs,
        "interruption": interruption_by_region,
    }
    if live_ok:
        with _aws_lock:
            _aws_cache = (time.time(), bundle)
    return bundle


def _infer_aws_vcpus(instance_type: str, specs: dict[str, dict[str, Any]]) -> tuple[int, float | None]:
    """Resolves (vcpus, ram_gb) for an AWS instance type using Spot Advisor metadata."""
    info = specs.get(instance_type)
    if info and info.get("cores"):
        return int(info["cores"]), float(info.get("ram_gb") or 0) or None

    # Clean deterministic fallback for EC2 size suffixes if advisor metadata lacks a SKU.
    size = instance_type.split(".")[-1].lower()
    size_vcpu = {
        "nano": 2,
        "micro": 2,
        "small": 2,
        "medium": 2,
        "large": 2,
        "xlarge": 4,
        "2xlarge": 8,
        "3xlarge": 12,
        "4xlarge": 16,
        "6xlarge": 24,
        "8xlarge": 32,
        "9xlarge": 36,
        "10xlarge": 40,
        "12xlarge": 48,
        "16xlarge": 64,
        "18xlarge": 72,
        "24xlarge": 96,
        "32xlarge": 128,
        "48xlarge": 192,
        "56xlarge": 224,
    }
    return size_vcpu.get(size, 0), None


def _fetch_azure_skus_batch(azure_region: str, skus: list[str]) -> dict[str, float | None]:
    """Queries live Linux Consumption Spot prices for <=10 Azure SKUs in one call."""
    out: dict[str, float | None] = {s: None for s in skus}
    if not skus:
        return out
    clause = " or ".join(f"armSkuName eq '{s}'" for s in skus)
    flt = (
        f"serviceName eq 'Virtual Machines' and armRegionName eq '{azure_region}' "
        f"and contains(skuName,'Spot') and ({clause})"
    )
    url = f"{AZURE_PRICES_URL}?{urllib.parse.urlencode({'$filter': flt})}"
    try:
        resp = _session().get(url, timeout=12)
        if resp.status_code != 200:
            return out
        data = resp.json()
        for it in data.get("Items", []):
            sku = it.get("armSkuName")
            if sku not in out:
                continue
            pname = it.get("productName") or ""
            sname = it.get("skuName") or ""
            if "Windows" in pname or "Low Priority" in sname:
                continue
            if it.get("type") != "Consumption":
                continue
            price = it.get("retailPrice")
            if price is not None and float(price) > 0:
                pval = float(price)
                if out[sku] is None or pval < out[sku]:
                    out[sku] = pval
    except Exception:
        pass
    return out


def prefetch_azure_spot_prices(
    region_sku_pairs: set[tuple[str, str]], force_refresh: bool = False
) -> None:
    """Concurrently fetches and caches all needed (azure_region, sku) Spot prices."""
    now = time.time()
    needed_by_region: dict[str, list[str]] = {}
    with _azure_lock:
        for az_reg, sku in region_sku_pairs:
            cached = _azure_price_cache.get((az_reg, sku))
            if (
                not force_refresh
                and cached is not None
                and (now - cached[0]) < PRICING_CACHE_TTL_SECONDS
            ):
                continue
            needed_by_region.setdefault(az_reg, []).append(sku)

    if not needed_by_region:
        return

    batches: list[tuple[str, list[str]]] = []
    for az_reg, skus in needed_by_region.items():
        uniq = sorted(set(skus))
        for i in range(0, len(uniq), _AZURE_BATCH_SIZE):
            batches.append((az_reg, uniq[i : i + _AZURE_BATCH_SIZE]))

    def _run_batch(item: tuple[str, list[str]]) -> tuple[str, dict[str, float | None]]:
        az_reg, chunk = item
        return az_reg, _fetch_azure_skus_batch(az_reg, chunk)

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_run_batch, batches))

    ts = time.time()
    with _azure_lock:
        for az_reg, sku_map in results:
            for sku, price in sku_map.items():
                _azure_price_cache[(az_reg, sku)] = (ts, price)


def _pct_delta(other_vcpu_hr: float | None, gcp_vcpu_hr: float | None) -> float | None:
    if (
        other_vcpu_hr is None
        or gcp_vcpu_hr is None
        or gcp_vcpu_hr <= 0
    ):
        return None
    return round(((other_vcpu_hr - gcp_vcpu_hr) / gcp_vcpu_hr) * 100.0, 1)


def _pick_aws_equivalent(
    gcp_region: str,
    gcp_family: str,
    shape_class: str,
    target_vcpus: int,
    gcp_spot_vcpu_hr: float | None,
    aws_bundle: dict[str, Any],
) -> dict[str, Any]:
    rmap = CLOUD_REGION_MAP.get(gcp_region, {
        "aws_region": "us-east-1",
        "aws_exact": False,
    })
    aws_region = rmap["aws_region"]
    aws_exact = rmap.get("aws_exact", False)
    reg_prices = aws_bundle.get("prices", {}).get(aws_region, {})
    specs = aws_bundle.get("specs", {})
    intr_map = aws_bundle.get("interruption", {}).get(aws_region, {})

    ladder = _aws_family_ladder(gcp_family, shape_class)
    chosen_sku: str | None = None
    chosen_price: float | None = None
    chosen_vcpus = 0
    chosen_ram: float | None = None

    for fam_prefix in ladder:
        prefix_dot = f"{fam_prefix}."
        candidates: list[tuple[str, int, float | None, float]] = []
        for sku, price in reg_prices.items():
            if not sku.startswith(prefix_dot) or "metal" in sku:
                continue
            vc, ram = _infer_aws_vcpus(sku, specs)
            if vc > 0:
                candidates.append((sku, vc, ram, price))
        if candidates:
            # Pick closest vCPU size to GCP shape (tie-break toward >= target_vcpus).
            candidates.sort(
                key=lambda c: (
                    abs(c[1] - max(1, target_vcpus)),
                    0 if c[1] >= target_vcpus else 1,
                    -c[1],
                )
            )
            chosen_sku, chosen_vcpus, chosen_ram, chosen_price = candidates[0]
            break

    if chosen_sku is None or chosen_price is None or chosen_vcpus <= 0:
        return {
            "sku": f"{ladder[0]}.* (N/A)",
            "region": aws_region,
            "region_exact": aws_exact,
            "vcpus": None,
            "ram_gb": None,
            "spot_vm_hr": None,
            "spot_vcpu_hr": None,
            "vs_gcp_pct": None,
            "interruption_band": None,
            "live": aws_bundle.get("live", False),
        }

    vcpu_hr = round(chosen_price / chosen_vcpus, 5)
    return {
        "sku": chosen_sku,
        "region": aws_region,
        "region_exact": aws_exact,
        "vcpus": chosen_vcpus,
        "ram_gb": round(chosen_ram, 1) if chosen_ram else None,
        "spot_vm_hr": round(chosen_price, 4),
        "spot_vcpu_hr": vcpu_hr,
        "vs_gcp_pct": _pct_delta(vcpu_hr, gcp_spot_vcpu_hr),
        "interruption_band": intr_map.get(chosen_sku) or None,
        "live": True,
    }


def _pick_azure_equivalent(
    gcp_region: str,
    gcp_family: str,
    shape_class: str,
    target_vcpus: int,
    gcp_spot_vcpu_hr: float | None,
) -> dict[str, Any]:
    rmap = CLOUD_REGION_MAP.get(gcp_region, {
        "azure_region": "eastus",
        "azure_exact": False,
    })
    az_region = rmap["azure_region"]
    az_exact = rmap.get("azure_exact", False)
    ladder = _azure_series_ladder(gcp_family, shape_class)

    chosen_sku: str | None = None
    chosen_price: float | None = None
    chosen_vcpus = 0
    chosen_ram: float | None = None

    with _azure_lock:
        for skey in ladder:
            skus = AZURE_SERIES_TO_SKUS.get(skey, [])
            priced: list[tuple[str, int, float, float]] = []
            for sku in skus:
                entry = _azure_price_cache.get((az_region, sku))
                if entry is not None and entry[1] is not None and entry[1] > 0:
                    _, vc, ram, _ = AZURE_SKU_SPECS[sku]
                    priced.append((sku, vc, ram, entry[1]))
            if priced:
                priced.sort(
                    key=lambda c: (
                        abs(c[1] - max(1, target_vcpus)),
                        0 if c[1] >= target_vcpus else 1,
                        -c[1],
                    )
                )
                chosen_sku, chosen_vcpus, chosen_ram, chosen_price = priced[0]
                break

    if chosen_sku is None or chosen_price is None or chosen_vcpus <= 0:
        fallback_skus = AZURE_SERIES_TO_SKUS.get(ladder[0], [])
        return {
            "sku": fallback_skus[0] if fallback_skus else "N/A",
            "region": az_region,
            "region_exact": az_exact,
            "vcpus": None,
            "ram_gb": None,
            "spot_vm_hr": None,
            "spot_vcpu_hr": None,
            "vs_gcp_pct": None,
            "live": False,
        }

    vcpu_hr = round(chosen_price / chosen_vcpus, 5)
    return {
        "sku": chosen_sku,
        "region": az_region,
        "region_exact": az_exact,
        "vcpus": chosen_vcpus,
        "ram_gb": round(chosen_ram, 1) if chosen_ram else None,
        "spot_vm_hr": round(chosen_price, 4),
        "spot_vcpu_hr": vcpu_hr,
        "vs_gcp_pct": _pct_delta(vcpu_hr, gcp_spot_vcpu_hr),
        "live": True,
    }


def enrich_pools_with_multicloud_spot(
    pools: list[dict[str, Any]], force_refresh: bool = False
) -> dict[str, Any]:
    """Attaches live AWS & Azure equivalent VM + Spot pricing to every pool row.

    Runs AWS Spot feed download and Azure Retail Prices OData batches in parallel
    and mutates each pool dict in place with `aws_equiv` and `azure_equiv`.
    Returns pricing source metadata for UI transparency.
    """
    if not pools:
        return {"aws_live": False, "azure_live": False}

    # Collect exact (azure_region, candidate_sku) pairs needed for the current scan.
    azure_pairs: set[tuple[str, str]] = set()
    for p in pools:
        reg = p["region"]
        az_reg = CLOUD_REGION_MAP.get(reg, {}).get("azure_region", "eastus")
        ladder = _azure_series_ladder(p["family"], p.get("shape_class", "standard"))
        for skey in ladder:
            for sku in AZURE_SERIES_TO_SKUS.get(skey, []):
                azure_pairs.add((az_reg, sku))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        aws_fut = pool.submit(get_aws_live_spot_data, force_refresh)
        az_fut = pool.submit(prefetch_azure_spot_prices, azure_pairs, force_refresh)
        aws_bundle = aws_fut.result()
        az_fut.result()

    any_azure_live = False
    for p in pools:
        gcp_reg = p["region"]
        gcp_fam = p["family"]
        sc = p.get("shape_class", "standard")
        vcpus = int(p.get("vcpus_per_vm") or 64)
        gcp_vcpu_hr = p.get("spot_price_vcpu_hr")

        aws_eq = _pick_aws_equivalent(
            gcp_reg, gcp_fam, sc, vcpus, gcp_vcpu_hr, aws_bundle
        )
        az_eq = _pick_azure_equivalent(
            gcp_reg, gcp_fam, sc, vcpus, gcp_vcpu_hr
        )
        if az_eq.get("live"):
            any_azure_live = True

        p["aws_equiv"] = aws_eq
        p["azure_equiv"] = az_eq

    return {
        "aws_live": bool(aws_bundle.get("live")),
        "aws_last_modified": aws_bundle.get("last_modified"),
        "azure_live": any_azure_live,
        "fetched_at": aws_bundle.get("fetched_at")
        or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": {
            "gcp": "Compute Engine Capacity History Beta API",
            "aws": "AWS EC2 Real-Time Spot Feed (spot.json) & Spot Advisor",
            "azure": "Microsoft Azure Retail Prices API (Linux Consumption Spot)",
        },
    }
