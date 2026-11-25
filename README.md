# GCP Spot Capacity & Quant Grid Advisor

An interactive multi-region Spot VM capacity scanner, top-down machine shape explorer, and live multi-cloud (GCP vs. AWS vs. Azure) Spot unit-economics dashboard built on public Google Compute Engine APIs.

> **Disclaimer:** This is a non-production demonstration and evaluation tool provided **as-is** under the [Apache 2.0 License](LICENSE). It is not an officially supported Google Cloud product and carries no warranty or production SLA commitment.

---

## Key Capabilities

1. **Live Compute Engine Discovery (43+ Regions, 130+ Zones, 34 Spot-Capable Families)**
   - Dynamically discovers all non-metal Spot-supported machine types (`standard`, `highmem`, `highcpu`, `lssd`, `gpu`) via the Compute Engine REST API.
2. **Per-Zone Deep Unlock (Bypassing the 1,000-VM Single-Request API Limit)**
   - Probes largest VM shapes top-down (e.g., `c4d-standard-384`, `c4-standard-288`, `n2d-standard-224`, `n4-standard-80`) and runs independent per-zone binary searches (`1..1,000` VMs/zone) via `advice/capacity` without provisioning trial VMs.
3. **Host-Pool Overlap Guardrails**
   - Slide-in **Investigation Drawer** displays the full top-down shape ladder, per-zone shard distribution, 6-month floating Spot price chart (`advice/capacityHistory`), and safe non-overlapping family ceilings so sub-shapes are never double-counted.
4. **Live Multi-Cloud Spot Comparison (GCP vs. AWS vs. Azure)**
   - Side-by-side **AWS Equivalent VM**, **AWS Spot `$/vCPU-hr`**, **Azure Equivalent VM**, and **Azure Spot `$/vCPU-hr`** columns matched by CPU architecture, generation, closest vCPU size, and RAM/vCPU ratio.
   - Includes a toolbar **GCP Discount %** modeling input (e.g., `0%`, `20%`, `25%`, `30%`, or custom) and a one-click **Show/Hide AWS & Azure Peers** toggle.
5. **1M-vCPU Multi-Region Portfolio Planner & Standalone CLI**
   - Drag-and-drop machine family fallback priority ladder (`80/20` Spot vs. CUD/On-Demand modeling), interactive ECharts analytics, and a standalone zero-UI Python CLI (`spot_advisor_scanner.py`).

---

## Prerequisites

- **Python 3.10+** and **Node.js 18+ / npm** (for building the React UI locally; not required if using Docker or the CLI only).
- **Google Cloud SDK (`gcloud`)** authenticated with a GCP project where the **Compute Engine API (`compute.googleapis.com`)** is enabled.
- **IAM Permissions:** Standard read-only Compute Engine permissions (e.g., `roles/compute.viewer`, which covers `compute.regions.list`, `compute.machineTypes.list`, and Compute Engine Capacity Advice read calls).

---

## Quick Start (Local Machine or Google Cloud Shell)

### 1. Authenticate with GCP

```bash
gcloud auth application-default login
gcloud config set project YOUR_GCP_PROJECT_ID
export GOOGLE_CLOUD_PROJECT=YOUR_GCP_PROJECT_ID
```

### 2. Launch the Dashboard

```bash
chmod +x run.sh
./run.sh
```

Open **http://127.0.0.1:8585** in your browser (or use **Web Preview -> Port 8585** if running in Google Cloud Shell).

> You can also change or enter any GCP Project ID directly in the **Project** field in the top header and click **Refresh Live Scan**.

---

## Option B: Run with Docker (or Deploy to Cloud Run)

```bash
docker build -t gcp-spot-capacity-advisor .

# Run locally mounting your Application Default Credentials:
docker run --rm -p 8585:8585 \
  -e GOOGLE_CLOUD_PROJECT=YOUR_GCP_PROJECT_ID \
  -e GOOGLE_APPLICATION_CREDENTIALS=/tmp/adc.json \
  -v "$HOME/.config/gcloud/application_default_credentials.json:/tmp/adc.json:ro" \
  gcp-spot-capacity-advisor
```

---

## Option C: Headless CLI Only (`spot_advisor_scanner.py`)

If you prefer terminal/CSV/JSON automation without running the web UI:

```bash
pip install google-auth requests

# Scan core APAC & EMEA regions across key families:
python3 spot_advisor_scanner.py \
  --project YOUR_GCP_PROJECT_ID \
  --regions asia-east1,asia-south1,asia-southeast1,asia-northeast1,europe-west4 \
  --families N4,C4D,C4,N2D \
  --per-zone

# Scan ALL live GCP regions & ALL Spot-capable families:
python3 spot_advisor_scanner.py \
  --project YOUR_GCP_PROJECT_ID \
  --regions ALL \
  --families ALL \
  --shape-profile standard \
  --per-zone \
  --json > spot_scan.json
```

---

## Live Public Data & Pricing Sources

All capacity and pricing data are queried dynamically over HTTPS from official public vendor APIs (no hardcoded prices):

| Cloud | Public Endpoint | Notes |
| :--- | :--- | :--- |
| **GCP** | Compute Engine Beta `advice/capacity` & `advice/capacityHistory` | Live obtainability scores, 30-day preemption rates, and floating public Spot rates (cached 5 min; bypassed via **Refresh Live Scan**). |
| **AWS** | `https://website.spot.ec2.aws.a2z.com/spot.json` & `https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json` | Live Linux Spot rates across 44 AWS regions & 1,370+ EC2 shapes (refreshed every ~5 min by AWS) + AWS Spot Advisor interruption bands. |
| **Azure** | `https://prices.azure.com/api/retail/prices` | Official Microsoft Azure Retail Prices REST API filtered strictly to Linux `Consumption` `Spot` meters (Windows & DevTest excluded). |

---

## License

Copyright 2026 Google LLC. Licensed under the Apache License, Version 2.0 — see [LICENSE](LICENSE).
