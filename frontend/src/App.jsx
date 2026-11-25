/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import ReactECharts from 'echarts-for-react';
import { format, parseISO } from 'date-fns';
import {
  Activity,
  AlertTriangle,
  BookOpen,
  BarChart3,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Copy,
  Cpu,
  DollarSign,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  Globe,
  Layers,
  Monitor,
  Moon,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  Sliders,
  Sun,
  Terminal,
  XCircle,
  Zap,
} from 'lucide-react';
import { useLadder } from './context/LadderContext';
import SortableLadder from './components/SortableLadder';
import InvestigationDrawer from './components/InvestigationDrawer';

function formatScanTimestamp(isoStr) {
  if (!isoStr) return 'Pending scan...';
  try {
    return `${format(parseISO(isoStr), 'MMM dd, yyyy HH:mm')} UTC`;
  } catch {
    return isoStr;
  }
}

function LifecyclePill({ lifecycle, label }) {
  if (lifecycle === 'RECOMMENDED') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
        <CheckCircle2 className="w-3 h-3 shrink-0" />
        {label}
      </span>
    );
  }
  if (lifecycle === 'DIVERSIFICATION') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400">
        <AlertTriangle className="w-3 h-3 shrink-0" />
        {label}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400">
      <XCircle className="w-3 h-3 shrink-0" />
      {label}
    </span>
  );
}

function computeDeltaPct(peerVcpuHr, gcpVcpuHr) {
  if (
    peerVcpuHr === null ||
    peerVcpuHr === undefined ||
    gcpVcpuHr === null ||
    gcpVcpuHr === undefined ||
    gcpVcpuHr <= 0
  ) {
    return null;
  }
  return Math.round(((peerVcpuHr - gcpVcpuHr) / gcpVcpuHr) * 1000) / 10;
}

function PriceDeltaBadge({ pct }) {
  if (pct === null || pct === undefined) return null;
  if (Math.abs(pct) < 0.5) {
    return (
      <span
        className="inline-block px-1.5 py-0.2 rounded text-[10px] font-mono font-semibold bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
        title="Roughly parity with GCP Spot $/vCPU-hr"
      >
        ~0%
      </span>
    );
  }
  const gcpCheaper = pct > 0;
  return (
    <span
      className={`inline-block px-1.5 py-0.2 rounded text-[10px] font-mono font-semibold ${
        gcpCheaper
          ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
          : 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300'
      }`}
      title={
        gcpCheaper
          ? `Peer Spot $/vCPU-hr is ${pct.toFixed(1)}% higher than GCP`
          : `Peer Spot $/vCPU-hr is ${Math.abs(pct).toFixed(1)}% lower than GCP public list Spot`
      }
    >
      {gcpCheaper ? `+${pct.toFixed(0)}%` : `${pct.toFixed(0)}%`}
    </span>
  );
}

function ObtainabilityBar({ score, label, maxVms }) {
  if (maxVms === 0) {
    return (
      <div className="flex items-center gap-2">
        <div className="w-20 h-2 rounded-full bg-zinc-200 dark:bg-zinc-800 overflow-hidden">
          <div className="h-full bg-rose-500" style={{ width: '8%' }} />
        </div>
        <span className="font-mono text-xs text-rose-600 dark:text-rose-400 font-medium">
          Stockout
        </span>
      </div>
    );
  }
  const pct = Math.max(5, Math.min(100, Math.round((score || 0) * 100)));
  const barColor =
    score > 0.7
      ? 'bg-emerald-500'
      : score >= 0.5
      ? 'bg-orange-400'
      : 'bg-rose-500';
  const textColor =
    score > 0.7
      ? 'text-emerald-700 dark:text-emerald-400'
      : score >= 0.5
      ? 'text-amber-700 dark:text-amber-400'
      : 'text-rose-600 dark:text-rose-400';

  return (
    <div className="flex items-center gap-2.5">
      <div className="w-20 h-2 rounded-full bg-zinc-200 dark:bg-zinc-800 overflow-hidden shrink-0">
        <div
          className={`h-full rounded-full transition-all duration-300 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`font-mono text-xs font-semibold ${textColor}`}>
        {pct}% ({label})
      </span>
    </div>
  );
}

export default function App() {
  const {
    ladder,
    syncCatalogFamilies,
    familyColors,
    targetTotalVcpus,
    setTargetTotalVcpus,
    spotSharePct,
    setSpotSharePct,
  } = useLadder();

  // Theme state ('light' | 'dark' | 'system') persisted in localStorage
  const [themeMode, setThemeMode] = useState(() => {
    try {
      return localStorage.getItem('spot-advisor-theme') || 'dark';
    } catch {
      return 'dark';
    }
  });
  const [systemPrefersDark, setSystemPrefersDark] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
      : true
  );

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e) => setSystemPrefersDark(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const isDark = themeMode === 'dark' || (themeMode === 'system' && systemPrefersDark);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
    document.documentElement.style.colorScheme = isDark ? 'dark' : 'light';
    try {
      localStorage.setItem('spot-advisor-theme', themeMode);
    } catch {
      // Ignore storage errors in restricted environments
    }
  }, [isDark, themeMode]);

  // Catalog & Scan State
  const [catalog, setCatalog] = useState(null);
  const [project, setProject] = useState('');
  const [selectedRegions, setSelectedRegions] = useState([]);
  const [selectedFamilies, setSelectedFamilies] = useState([
    'N4',
    'C4D',
    'C4',
    'N2D',
    'C3D',
    'N2',
  ]);
  const [shapeProfile, setShapeProfile] = useState('standard');
  const [perZoneUnlock, setPerZoneUnlock] = useState(true);
  const [minScore, setMinScore] = useState(0.5);

  const [scanData, setScanData] = useState(null);
  const [scanning, setScanning] = useState(true);
  const [scanError, setScanError] = useState('');

  // Active Navigation Tab
  const [activeTab, setActiveTab] = useState('scanner');

  // Scanner Filters & Table State
  const [geoFilter, setGeoFilter] = useState('ALL');
  const [lifecycleFilter, setLifecycleFilter] = useState('HIDE_SUNSET');
  const [onlyAvailable, setOnlyAvailable] = useState(false);
  const [showPeerPricing, setShowPeerPricing] = useState(true);
  const [gcpDiscountPct, setGcpDiscountPct] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedPool, setSelectedPool] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const gcpDiscountFactor = Math.max(0.1, 1 - Math.min(70, Math.max(0, gcpDiscountPct)) / 100);

  // Region & Family Dropdown Popovers
  const [regionMenuOpen, setRegionMenuOpen] = useState(false);
  const [regionSearch, setRegionSearch] = useState('');
  const regionMenuRef = useRef(null);

  const [familyMenuOpen, setFamilyMenuOpen] = useState(false);
  const [familySearch, setFamilySearch] = useState('');
  const familyMenuRef = useRef(null);

  // Copy CLI state
  const [copiedCli, setCopiedCli] = useState(false);

  useEffect(() => {
    const handleOutside = (e) => {
      if (regionMenuRef.current && !regionMenuRef.current.contains(e.target)) {
        setRegionMenuOpen(false);
      }
      if (familyMenuRef.current && !familyMenuRef.current.contains(e.target)) {
        setFamilyMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, []);

  // Initial Catalog + Live Fleet Scan
  useEffect(() => {
    let mounted = true;
    async function init() {
      try {
        setScanning(true);
        const catRes = await axios.get('/api/catalog');
        if (!mounted) return;
        const cat = catRes.data;
        setCatalog(cat);
        syncCatalogFamilies(cat.families || []);
        const initProj = cat.default_project || '';
        setProject(initProj);
        const defRegs = (cat.regions || [])
          .filter((r) => r.default_selected)
          .map((r) => r.id);
        setSelectedRegions(defRegs);
        const defFams =
          cat.default_families || ['N4', 'C4D', 'C4', 'N2D', 'C3D', 'N2'];
        setSelectedFamilies(defFams);

        if (!initProj) {
          setScanError(
            'Enter your GCP Project ID in the header above (or export GOOGLE_CLOUD_PROJECT) and click Refresh Live Scan.'
          );
          return;
        }

        const scanRes = await axios.post('/api/scan', {
          project: initProj,
          regions: defRegs,
          families: defFams,
          per_zone_unlock: true,
          min_score: 0.5,
          shape_profile: 'standard',
          force_refresh: false,
        });
        if (!mounted) return;
        setScanData(scanRes.data);
      } catch (err) {
        if (!mounted) return;
        setScanError(
          err.response?.data?.detail ||
            err.message ||
            'Failed to query Spot Advisor API.'
        );
      } finally {
        if (mounted) setScanning(false);
      }
    }
    init();
    return () => {
      mounted = false;
    };
  }, [syncCatalogFamilies]);

  const triggerScan = async (
    forceRefresh = false,
    overrideScore = minScore,
    overrideZonal = perZoneUnlock,
    overrideRegions = selectedRegions,
    overrideFamilies = selectedFamilies,
    overrideProfile = shapeProfile
  ) => {
    const trimmedProj = project.trim();
    if (!trimmedProj) {
      setScanError('Please enter your GCP Project ID in the top header before scanning.');
      return;
    }
    if (!overrideRegions.length) {
      setScanError('Please select at least one GCP region to scan.');
      return;
    }
    if (!overrideFamilies.length) {
      setScanError('Please select at least one VM family to scan.');
      return;
    }
    setScanning(true);
    setScanError('');
    try {
      const res = await axios.post('/api/scan', {
        project: trimmedProj,
        regions: overrideRegions,
        families: overrideFamilies,
        per_zone_unlock: overrideZonal,
        min_score: overrideScore,
        shape_profile: overrideProfile,
        force_refresh: forceRefresh,
      });
      setScanData(res.data);
      if (selectedPool) {
        const updated = (res.data.pools || []).find(
          (p) => p.id === selectedPool.id
        );
        setSelectedPool(updated || null);
      }
    } catch (err) {
      setScanError(
        err.response?.data?.detail ||
          err.message ||
          'Failed to scan Spot capacity.'
      );
    } finally {
      setScanning(false);
    }
  };

  const familyCatalogMap = useMemo(() => {
    const map = {};
    (catalog?.families || []).forEach((f) => {
      map[f.id] = f;
    });
    return map;
  }, [catalog]);

  const enabledFamilySet = useMemo(() => {
    return new Set(ladder.filter((i) => i.enabled).map((i) => i.id));
  }, [ladder]);

  const pools = scanData?.pools || [];

  // Family totals across scanned regions
  const familyTotals = useMemo(() => {
    const totals = {};
    pools.forEach((p) => {
      if (p.supported && p.max_vcpus > 0) {
        totals[p.family] = (totals[p.family] || 0) + p.max_vcpus;
      }
    });
    return totals;
  }, [pools]);

  // Portfolio Planner: Allocate targetSpotVcpus in strict SortableLadder priority order
  const targetSpotVcpus = Math.round((targetTotalVcpus * spotSharePct) / 100);
  const targetCudVcpus = targetTotalVcpus - targetSpotVcpus;

  const portfolioPlan = useMemo(() => {
    let remaining = targetSpotVcpus;
    const allocations = [];
    let totalSpotCostHr = 0;
    let pricedVcpus = 0;

    ladder.forEach((rung, rankIdx) => {
      if (!rung.enabled) return;
      const candidates = pools
        .filter((p) => p.family === rung.id && p.supported && p.max_vcpus > 0)
        .sort((a, b) => {
          if (b.obtainability !== a.obtainability) {
            return b.obtainability - a.obtainability;
          }
          const pa = a.preemption_rate_30d ?? 50;
          const pb = b.preemption_rate_30d ?? 50;
          if (pa !== pb) return pa - pb;
          return b.max_vcpus - a.max_vcpus;
        });

      candidates.forEach((pool) => {
        if (remaining <= 0) return;
        const takeVcpus = Math.min(pool.max_vcpus, remaining);
        const vmsNeeded = Math.ceil(takeVcpus / pool.vcpus_per_vm);
        const actualVcpus = Math.min(pool.max_vcpus, vmsNeeded * pool.vcpus_per_vm);
        const estHrUsd =
          pool.spot_price_vcpu_hr !== null
            ? actualVcpus * pool.spot_price_vcpu_hr * gcpDiscountFactor
            : null;
        if (estHrUsd !== null) {
          totalSpotCostHr += estHrUsd;
          pricedVcpus += actualVcpus;
        }
        allocations.push({
          ...pool,
          ladderRank: rankIdx + 1,
          allocatedVms: vmsNeeded,
          allocatedVcpus: actualVcpus,
          estHourlyUsd: estHrUsd,
        });
        remaining -= actualVcpus;
      });
    });

    const allocatedTotal = allocations.reduce(
      (acc, a) => acc + a.allocatedVcpus,
      0
    );
    const weightedSpotVcpuHr =
      pricedVcpus > 0 ? totalSpotCostHr / pricedVcpus : null;

    return {
      allocations,
      allocatedTotal,
      shortfallVcpus: Math.max(0, targetSpotVcpus - allocatedTotal),
      coveragePct:
        targetSpotVcpus > 0
          ? Math.min(100, Math.round((allocatedTotal / targetSpotVcpus) * 100))
          : 100,
      totalSpotCostHr,
      weightedSpotVcpuHr,
    };
  }, [ladder, pools, targetSpotVcpus, gcpDiscountFactor]);

  // KPI Metrics
  const kpis = useMemo(() => {
    let enabledSafeVcpus = 0;
    let allFamiliesSafeVcpus = 0;
    const regionMap = {};

    pools.forEach((p) => {
      if (!p.supported || p.max_vcpus <= 0) return;
      allFamiliesSafeVcpus += p.max_vcpus;
      if (enabledFamilySet.has(p.family)) {
        enabledSafeVcpus += p.max_vcpus;
        if (!regionMap[p.region]) {
          regionMap[p.region] = {
            region: p.region,
            label: p.region_label,
            vcpus: 0,
            preemptionSum: 0,
            preemptionCount: 0,
          };
        }
        regionMap[p.region].vcpus += p.max_vcpus;
        if (p.preemption_rate_30d !== null && p.preemption_rate_30d !== undefined) {
          regionMap[p.region].preemptionSum += p.preemption_rate_30d;
          regionMap[p.region].preemptionCount += 1;
        }
      }
    });

    const topRegion = Object.values(regionMap).sort(
      (a, b) => b.vcpus - a.vcpus
    )[0];

    return {
      enabledSafeVcpus,
      allFamiliesSafeVcpus,
      topRegion,
    };
  }, [pools, enabledFamilySet]);

  // Filtered Scanner Rows
  const filteredPools = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return pools.filter((p) => {
      if (geoFilter !== 'ALL' && p.geo !== geoFilter && p.subgeo !== geoFilter) {
        return false;
      }
      if (onlyAvailable && (!p.supported || p.max_vcpus <= 0)) {
        return false;
      }
      if (lifecycleFilter === 'RECOMMENDED_ONLY' && p.lifecycle !== 'RECOMMENDED') {
        return false;
      }
      if (lifecycleFilter === 'HIDE_SUNSET' && p.lifecycle === 'LEGACY') {
        return false;
      }
      if (q) {
        const hay = `${p.region} ${p.region_label} ${p.family} ${p.category || ''} ${p.arch || ''} ${p.machine_type} ${p.aws_mapping} ${p.aws_equiv?.sku || ''} ${p.aws_equiv?.region || ''} ${p.azure_equiv?.sku || ''} ${p.azure_equiv?.region || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [pools, geoFilter, lifecycleFilter, onlyAvailable, searchQuery]);

  useEffect(() => {
    setPage(1);
  }, [geoFilter, lifecycleFilter, onlyAvailable, searchQuery, selectedRegions, selectedFamilies, shapeProfile, minScore, pageSize]);

  const totalPages = Math.max(1, Math.ceil(filteredPools.length / pageSize));
  const paginatedPools = filteredPools.slice(
    (page - 1) * pageSize,
    page * pageSize
  );

  // ECharts Option 1: Regional Stacked Capacity by Machine Family
  const regionalStackedChartOption = useMemo(() => {
    const activeRegions = Array.from(new Set(pools.map((p) => p.region)));
    const regionTotals = {};
    activeRegions.forEach((r) => {
      regionTotals[r] = pools
        .filter((p) => p.region === r && p.supported)
        .reduce((s, p) => s + p.max_vcpus, 0);
    });
    activeRegions.sort((a, b) => (regionTotals[b] || 0) - (regionTotals[a] || 0));

    const scannedFams = Array.from(
      new Set(pools.filter((p) => p.supported && p.max_vcpus > 0).map((p) => p.family))
    );
    const familiesOrder = ladder
      .map((l) => l.id)
      .filter((id) => scannedFams.includes(id));

    const series = familiesOrder.map((famId) => ({
      name: famId,
      type: 'bar',
      stack: 'total',
      emphasis: { focus: 'series' },
      itemStyle: { color: familyColors[famId] || '#3b82f6' },
      data: activeRegions.map((reg) => {
        const match = pools.find((p) => p.region === reg && p.family === famId);
        return match && match.supported ? match.max_vcpus : 0;
      }),
    }));

    const useSlider = activeRegions.length > 14;
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: isDark ? '#18181b' : '#ffffff',
        borderColor: isDark ? '#27272a' : '#e4e4e7',
        textStyle: { color: isDark ? '#f4f4f5' : '#18181b', fontSize: 12 },
      },
      legend: {
        type: 'scroll',
        top: 0,
        textStyle: { color: isDark ? '#d4d4d8' : '#3f3f46', fontSize: 12 },
      },
      grid: { top: 44, left: 68, right: 24, bottom: useSlider ? 78 : 54 },
      dataZoom: useSlider
        ? [
            {
              type: 'slider',
              bottom: 6,
              height: 16,
              startValue: 0,
              endValue: 13,
            },
          ]
        : [],
      xAxis: {
        type: 'category',
        data: activeRegions,
        axisLabel: {
          color: isDark ? '#a1a1aa' : '#52525b',
          fontSize: 11,
          rotate: 22,
        },
        axisLine: { lineStyle: { color: isDark ? '#27272a' : '#e4e4e7' } },
      },
      yAxis: {
        type: 'value',
        name: 'Safe Spot vCPUs',
        nameTextStyle: { color: isDark ? '#a1a1aa' : '#71717a', fontSize: 11 },
        axisLabel: {
          color: isDark ? '#a1a1aa' : '#71717a',
          fontSize: 11,
          formatter: (v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : v),
        },
        splitLine: {
          lineStyle: { color: isDark ? '#27272a' : '#f4f4f5', type: 'dashed' },
        },
      },
      series,
    };
  }, [pools, ladder, familyColors, isDark]);

  // ECharts Option 2: Spot $/vCPU-hr vs 30d Preemption Rate across Top Active Pools
  const economicsChartOption = useMemo(() => {
    const active = pools
      .filter(
        (p) =>
          p.supported &&
          p.max_vcpus > 0 &&
          p.spot_price_vcpu_hr !== null &&
          p.lifecycle !== 'LEGACY'
      )
      .slice(0, 14);

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: isDark ? '#18181b' : '#ffffff',
        borderColor: isDark ? '#27272a' : '#e4e4e7',
        textStyle: { color: isDark ? '#f4f4f5' : '#18181b', fontSize: 12 },
      },
      legend: {
        type: 'scroll',
        top: 0,
        textStyle: { color: isDark ? '#d4d4d8' : '#3f3f46', fontSize: 12 },
      },
      grid: { top: 40, left: 68, right: 64, bottom: 70 },
      xAxis: {
        type: 'category',
        data: active.map((p) => `${p.region}\n(${p.family})`),
        axisLabel: {
          color: isDark ? '#a1a1aa' : '#52525b',
          fontSize: 10,
          interval: 0,
          rotate: 22,
        },
        axisLine: { lineStyle: { color: isDark ? '#27272a' : '#e4e4e7' } },
      },
      yAxis: [
        {
          type: 'value',
          name: 'Spot $/vCPU-hr',
          nameTextStyle: { color: isDark ? '#a1a1aa' : '#71717a', fontSize: 11 },
          axisLabel: {
            color: isDark ? '#a1a1aa' : '#71717a',
            fontSize: 11,
            formatter: (v) => `$${Number(v).toFixed(3)}`,
          },
          splitLine: {
            lineStyle: { color: isDark ? '#27272a' : '#f4f4f5', type: 'dashed' },
          },
        },
        {
          type: 'value',
          name: '30d Preemption %',
          nameTextStyle: { color: isDark ? '#a1a1aa' : '#71717a', fontSize: 11 },
          axisLabel: {
            color: isDark ? '#a1a1aa' : '#71717a',
            fontSize: 11,
            formatter: (v) => `${v}%`,
          },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name:
            gcpDiscountPct > 0
              ? `GCP Net Spot (-${gcpDiscountPct}%) $/vCPU-hr`
              : 'GCP Spot $/vCPU-hr',
          type: 'bar',
          barMaxWidth: showPeerPricing ? 20 : 28,
          itemStyle: { color: '#3b82f6', borderRadius: [4, 4, 0, 0] },
          data: active.map((p) =>
            p.spot_price_vcpu_hr !== null
              ? Number((p.spot_price_vcpu_hr * gcpDiscountFactor).toFixed(5))
              : null
          ),
        },
        ...(showPeerPricing
          ? [
              {
                name: 'AWS Equiv. Spot $/vCPU-hr',
                type: 'bar',
                barMaxWidth: 20,
                itemStyle: { color: '#f97316', borderRadius: [4, 4, 0, 0] },
                data: active.map((p) => p.aws_equiv?.spot_vcpu_hr ?? null),
              },
              {
                name: 'Azure Equiv. Spot $/vCPU-hr',
                type: 'bar',
                barMaxWidth: 20,
                itemStyle: { color: '#06b6d4', borderRadius: [4, 4, 0, 0] },
                data: active.map((p) => p.azure_equiv?.spot_vcpu_hr ?? null),
              },
            ]
          : []),
        {
          name: 'GCP 30d Preemption (%)',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          symbolSize: 7,
          itemStyle: { color: '#f59e0b' },
          lineStyle: { width: 2.5, color: '#f59e0b' },
          data: active.map((p) => p.preemption_rate_30d ?? 0),
        },
      ],
    };
  }, [pools, isDark, gcpDiscountFactor, gcpDiscountPct, showPeerPricing]);

  // ECharts Option 3: Portfolio Allocation by Region & Family
  const portfolioChartOption = useMemo(() => {
    const allocs = portfolioPlan.allocations;
    const regionsInPlan = Array.from(new Set(allocs.map((a) => a.region)));
    const enabledFams = ladder.filter((l) => l.enabled).map((l) => l.id);

    const series = enabledFams.map((famId) => ({
      name: famId,
      type: 'bar',
      stack: 'allocated',
      barMaxWidth: 36,
      itemStyle: { color: familyColors[famId] || '#10b981' },
      data: regionsInPlan.map((reg) => {
        const hit = allocs.find((a) => a.region === reg && a.family === famId);
        return hit ? hit.allocatedVcpus : 0;
      }),
    }));

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: isDark ? '#18181b' : '#ffffff',
        borderColor: isDark ? '#27272a' : '#e4e4e7',
        textStyle: { color: isDark ? '#f4f4f5' : '#18181b', fontSize: 12 },
      },
      legend: {
        type: 'scroll',
        top: 0,
        textStyle: { color: isDark ? '#d4d4d8' : '#3f3f46', fontSize: 12 },
      },
      grid: { top: 38, left: 68, right: 24, bottom: 36 },
      xAxis: {
        type: 'category',
        data: regionsInPlan,
        axisLabel: { color: isDark ? '#a1a1aa' : '#52525b', fontSize: 11 },
        axisLine: { lineStyle: { color: isDark ? '#27272a' : '#e4e4e7' } },
      },
      yAxis: {
        type: 'value',
        name: 'Allocated Spot vCPUs',
        nameTextStyle: { color: isDark ? '#a1a1aa' : '#71717a', fontSize: 11 },
        axisLabel: {
          color: isDark ? '#a1a1aa' : '#71717a',
          fontSize: 11,
          formatter: (v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : v),
        },
        splitLine: {
          lineStyle: { color: isDark ? '#27272a' : '#f4f4f5', type: 'dashed' },
        },
      },
      series,
    };
  }, [portfolioPlan, ladder, familyColors, isDark]);

  const handleToggleRegion = (regionId) => {
    setSelectedRegions((prev) =>
      prev.includes(regionId)
        ? prev.filter((r) => r !== regionId)
        : [...prev, regionId]
    );
  };

  const handleToggleFamily = (familyId) => {
    setSelectedFamilies((prev) =>
      prev.includes(familyId)
        ? prev.filter((f) => f !== familyId)
        : [...prev, familyId]
    );
  };

  const filteredMenuRegions = useMemo(() => {
    const q = regionSearch.trim().toLowerCase();
    return (catalog?.regions || []).filter((r) => {
      if (!q) return true;
      return `${r.id} ${r.label} ${r.geo} ${r.subgeo || ''}`
        .toLowerCase()
        .includes(q);
    });
  }, [catalog?.regions, regionSearch]);

  const filteredMenuFamilies = useMemo(() => {
    const q = familySearch.trim().toLowerCase();
    return (catalog?.families || []).filter((f) => {
      if (!q) return true;
      return `${f.id} ${f.name} ${f.category || ''} ${f.arch || ''} ${f.aws_mapping || ''}`
        .toLowerCase()
        .includes(q);
    });
  }, [catalog?.families, familySearch]);

  const handleCopyCli = async () => {
    if (!catalog?.cli_script) return;
    await navigator.clipboard.writeText(catalog.cli_script);
    setCopiedCli(true);
    setTimeout(() => setCopiedCli(false), 2000);
  };

  const handleDownloadCli = () => {
    if (!catalog?.cli_script) return;
    const blob = new Blob([catalog.cli_script], {
      type: 'text/x-python;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'spot_advisor_scanner.py';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-[#09090b] text-zinc-900 dark:text-zinc-100 transition-colors">
      <div className="max-w-[1800px] mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Top Header */}
        <header className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 shadow-sm p-5">
          <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2.5 flex-wrap">
                <div className="p-2 rounded-xl bg-blue-600 text-white shadow-sm">
                  <Cpu className="w-5 h-5" />
                </div>
                <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-zinc-950 dark:text-zinc-50">
                  GCP Spot Capacity & Quant Grid Advisor
                </h1>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300 border border-blue-200/70 dark:border-blue-800/70">
                  Live Compute Advice Beta API
                </span>
                {catalog?.stats && (
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-medium bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300 border border-emerald-200/70 dark:border-emerald-800/70">
                    {catalog.stats.total_regions} Regions • {catalog.stats.total_families} Families • {catalog.stats.total_shapes} VM Shapes
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 flex-wrap mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                <span>
                  Last scanned:{' '}
                  <strong className="font-mono text-zinc-700 dark:text-zinc-200">
                    {formatScanTimestamp(scanData?.scanned_at)}
                  </strong>
                  {scanData?.elapsed_ms !== undefined && (
                    <span className="ml-1.5 font-mono text-zinc-400">
                      ({scanData.cached ? 'cached' : `${scanData.elapsed_ms} ms`})
                    </span>
                  )}
                </span>
                <span className="hidden sm:inline text-zinc-300 dark:text-zinc-700">•</span>
                <div className="flex items-center gap-2 flex-wrap">
                  <a
                    href="https://cloud.google.com/compute/docs/instances/view-vm-availability"
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800/80 hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-medium transition-colors"
                  >
                    Spot Advisor Docs <ExternalLink className="w-3 h-3" />
                  </a>
                  <a
                    href="https://cloud.google.com/compute/docs/instances/create-vms-in-bulk"
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800/80 hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-medium transition-colors"
                  >
                    Bulk Insert API <ExternalLink className="w-3 h-3" />
                  </a>
                  <a
                    href="https://cloud.google.com/storage/docs/anywhere-cache"
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800/80 hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-medium transition-colors"
                  >
                    GCS Anywhere Cache <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              </div>
            </div>

            {/* Interactive Controls */}
            <div className="flex items-center gap-2.5 flex-wrap">
              {/* Editable GCP Project ID Input */}
              <div className="flex items-center bg-zinc-100/80 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl px-3 py-1.5">
                <span className="text-xs text-zinc-500 dark:text-zinc-400 mr-2">
                  Project:
                </span>
                <input
                  id="gcp-project-input"
                  type="text"
                  placeholder="your-gcp-project-id"
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                  disabled={scanning}
                  className="bg-transparent font-mono text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none w-40 disabled:opacity-50"
                />
              </div>

              {/* Region Multi-Selector Dropdown (All 43 Live Regions) */}
              <div className="relative z-40" ref={regionMenuRef}>
                <button
                  id="region-selector-btn"
                  type="button"
                  onClick={() => {
                    setFamilyMenuOpen(false);
                    setRegionMenuOpen((o) => !o);
                  }}
                  disabled={scanning}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold bg-zinc-100/80 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-200/70 dark:hover:bg-zinc-800 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Globe className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                  Regions ({selectedRegions.length}/{catalog?.regions?.length || 43})
                  <ChevronDown className="w-3.5 h-3.5 text-zinc-500" />
                </button>

                {regionMenuOpen && (
                  <div className="absolute right-0 mt-2 w-96 max-h-[28rem] flex flex-col rounded-2xl bg-white dark:bg-[#121216] border border-zinc-200 dark:border-zinc-800 shadow-2xl p-3 space-y-2.5 z-50">
                    <div className="flex items-center justify-between gap-2 pb-2 border-b border-zinc-200 dark:border-zinc-800">
                      <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-200">
                        All GCP Regions ({catalog?.regions?.length || 43})
                      </span>
                      <div className="flex items-center gap-1.5 flex-wrap justify-end">
                        <button
                          type="button"
                          onClick={() =>
                            setSelectedRegions(
                              (catalog?.regions || []).map((r) => r.id)
                            )
                          }
                          className="px-2 py-0.5 rounded bg-blue-50 dark:bg-blue-950/60 text-[11px] font-semibold text-blue-600 dark:text-blue-400 hover:underline cursor-pointer"
                        >
                          All ({catalog?.regions?.length || 43})
                        </button>
                        {['APAC', 'EMEA', 'AMER'].map((geo) => (
                          <button
                            key={geo}
                            type="button"
                            onClick={() =>
                              setSelectedRegions(
                                (catalog?.regions || [])
                                  .filter((r) => r.geo === geo)
                                  .map((r) => r.id)
                              )
                            }
                            className="px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-[11px] font-medium text-emerald-700 dark:text-emerald-400 hover:underline cursor-pointer"
                          >
                            {geo}
                          </button>
                        ))}
                        <button
                          type="button"
                          onClick={() =>
                            setSelectedRegions(
                              (catalog?.regions || [])
                                .filter((r) => r.default_selected)
                                .map((r) => r.id)
                            )
                          }
                          className="text-[11px] text-zinc-500 dark:text-zinc-400 hover:underline cursor-pointer"
                        >
                          Core (8)
                        </button>
                      </div>
                    </div>
                    <input
                      type="text"
                      placeholder="Search 43 regions (Tokyo, Frankfurt, Iowa, Bangkok...)"
                      value={regionSearch}
                      onChange={(e) => setRegionSearch(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded-lg text-xs bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-blue-500"
                    />
                    <div className="overflow-y-auto space-y-1 pr-1 flex-1">
                      {filteredMenuRegions.map((reg) => {
                        const checked = selectedRegions.includes(reg.id);
                        return (
                          <label
                            key={reg.id}
                            className="flex items-start gap-2.5 p-1.5 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800/60 cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => handleToggleRegion(reg.id)}
                              className="mt-0.5 accent-blue-600 rounded cursor-pointer"
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center justify-between gap-2 text-xs font-medium text-zinc-900 dark:text-zinc-100">
                                <span className="truncate">{reg.label}</span>
                                <span className="shrink-0 font-mono text-[10px] px-1.5 py-0.2 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500">
                                  {reg.subgeo || reg.geo}
                                </span>
                              </div>
                              <div className="text-[11px] text-zinc-500 dark:text-zinc-400 truncate">
                                {reg.note}
                              </div>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                    <div className="pt-2 border-t border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
                      <span className="text-[11px] text-zinc-500">
                        {selectedRegions.length} selected
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          setRegionMenuOpen(false);
                          triggerScan(
                            false,
                            minScore,
                            perZoneUnlock,
                            selectedRegions,
                            selectedFamilies,
                            shapeProfile
                          );
                        }}
                        className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white transition-colors cursor-pointer"
                      >
                        Apply & Scan
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* VM Families Multi-Selector Dropdown (All 34 Spot-Supported Series) */}
              <div className="relative z-40" ref={familyMenuRef}>
                <button
                  id="family-selector-btn"
                  type="button"
                  onClick={() => {
                    setRegionMenuOpen(false);
                    setFamilyMenuOpen((o) => !o);
                  }}
                  disabled={scanning}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold bg-zinc-100/80 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-200/70 dark:hover:bg-zinc-800 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Server className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                  VM Families ({selectedFamilies.length}/{catalog?.families?.length || 34})
                  <ChevronDown className="w-3.5 h-3.5 text-zinc-500" />
                </button>

                {familyMenuOpen && (
                  <div className="absolute right-0 mt-2 w-[26rem] max-h-[30rem] flex flex-col rounded-2xl bg-white dark:bg-[#121216] border border-zinc-200 dark:border-zinc-800 shadow-2xl p-3 space-y-2.5 z-50">
                    <div className="flex items-center justify-between gap-2 pb-2 border-b border-zinc-200 dark:border-zinc-800">
                      <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-200">
                        Spot-Capable VM Families ({catalog?.families?.length || 34})
                      </span>
                      <div className="flex items-center gap-1.5 flex-wrap justify-end">
                        <button
                          type="button"
                          onClick={() =>
                            setSelectedFamilies(
                              (catalog?.families || []).map((f) => f.id)
                            )
                          }
                          className="px-2 py-0.5 rounded bg-blue-50 dark:bg-blue-950/60 text-[11px] font-semibold text-blue-600 dark:text-blue-400 hover:underline cursor-pointer"
                        >
                          All ({catalog?.families?.length || 34})
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setSelectedFamilies(
                              catalog?.default_families || [
                                'N4',
                                'C4D',
                                'C4',
                                'N2D',
                                'C3D',
                                'N2',
                              ]
                            )
                          }
                          className="px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-[11px] font-medium text-emerald-700 dark:text-emerald-400 hover:underline cursor-pointer"
                        >
                          Quant Core
                        </button>
                        {[
                          { label: 'GP', cat: 'General Purpose' },
                          { label: 'Compute', cat: 'Compute-Optimized' },
                          { label: 'HPC', cat: 'HPC & Scale-Out' },
                          { label: 'Mem', cat: 'Memory-Optimized' },
                          { label: 'Stor', cat: 'Storage-Optimized' },
                          { label: 'GPU', cat: 'GPU / AI' },
                        ].map((preset) => (
                          <button
                            key={preset.label}
                            type="button"
                            onClick={() =>
                              setSelectedFamilies(
                                (catalog?.families || [])
                                  .filter((f) => f.category === preset.cat)
                                  .map((f) => f.id)
                              )
                            }
                            className="px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-[11px] text-zinc-700 dark:text-zinc-300 hover:underline cursor-pointer"
                          >
                            {preset.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    <input
                      type="text"
                      placeholder="Search families (N4, C4D, C4A, H4D, G4, A3, Z4D, M4...)"
                      value={familySearch}
                      onChange={(e) => setFamilySearch(e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded-lg text-xs bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-blue-500"
                    />

                    <div className="overflow-y-auto space-y-1 pr-1 flex-1">
                      {filteredMenuFamilies.map((fam) => {
                        const checked = selectedFamilies.includes(fam.id);
                        return (
                          <label
                            key={fam.id}
                            className="flex items-start gap-2.5 p-1.5 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800/60 cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => handleToggleFamily(fam.id)}
                              className="mt-0.5 accent-emerald-600 rounded cursor-pointer"
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center justify-between gap-2 text-xs font-medium text-zinc-900 dark:text-zinc-100">
                                <span className="truncate">{fam.name}</span>
                                <span className="shrink-0 font-mono text-[10px] px-1.5 py-0.2 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500">
                                  {fam.shape_count || fam.shapes?.length || 0} shapes •{' '}
                                  {fam.region_count || 43} reg
                                </span>
                              </div>
                              <div className="text-[11px] text-zinc-500 dark:text-zinc-400 truncate">
                                {fam.category} • {fam.arch}
                              </div>
                            </div>
                          </label>
                        );
                      })}
                    </div>

                    <div className="pt-2 border-t border-zinc-200 dark:border-zinc-800 space-y-2">
                      <p className="text-[10px] text-zinc-500 dark:text-zinc-400 leading-snug">
                        Note: Bare-metal-only (<code>X4</code>, <code>X5</code>,{' '}
                        <code>*-metal</code>, <code>A4X</code>) and Cloud TPUs are excluded
                        by GCE Spot Advice APIs.
                      </p>
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] text-zinc-500">
                          {selectedFamilies.length} families selected
                        </span>
                        <button
                          type="button"
                          onClick={() => {
                            setFamilyMenuOpen(false);
                            triggerScan(
                              false,
                              minScore,
                              perZoneUnlock,
                              selectedRegions,
                              selectedFamilies,
                              shapeProfile
                            );
                          }}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white transition-colors cursor-pointer"
                        >
                          Apply & Scan
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Refresh Button */}
              <button
                id="refresh-scan-btn"
                type="button"
                onClick={() => triggerScan(true)}
                disabled={scanning}
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white shadow-sm transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <RefreshCw
                  className={`w-3.5 h-3.5 ${scanning ? 'animate-spin' : ''}`}
                />
                {scanning ? 'Probing Live API...' : 'Refresh Live Scan'}
              </button>

              {/* Segmented Light / Dark / System Theme Switcher */}
              <div
                id="theme-switcher"
                role="group"
                aria-label="Theme mode"
                className="inline-flex items-center p-1 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-100/90 dark:bg-zinc-900"
              >
                {[
                  { id: 'light', label: 'Light', icon: Sun },
                  { id: 'dark', label: 'Dark', icon: Moon },
                  { id: 'system', label: 'Auto', icon: Monitor },
                ].map((opt) => {
                  const Icon = opt.icon;
                  const active = themeMode === opt.id;
                  return (
                    <button
                      key={opt.id}
                      id={`theme-${opt.id}-btn`}
                      type="button"
                      onClick={() => setThemeMode(opt.id)}
                      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                        active
                          ? 'bg-white dark:bg-zinc-800 text-zinc-950 dark:text-zinc-50 shadow-sm'
                          : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-950 dark:hover:text-zinc-200'
                      }`}
                      title={`Switch to ${opt.label} theme`}
                    >
                      <Icon
                        className={`w-3.5 h-3.5 ${
                          active && opt.id === 'light'
                            ? 'text-amber-500'
                            : active && opt.id === 'dark'
                            ? 'text-blue-400'
                            : ''
                        }`}
                      />
                      <span>{opt.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {scanError && (
            <div className="mt-4 p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-xs text-rose-700 dark:text-rose-300 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {scanError}
            </div>
          )}
        </header>

        {/* 4 Primary KPI Cards */}
        <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {/* KPI 1 */}
          <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              <span>Safe Obtainable Spot Pool</span>
              <Zap className="w-4 h-4 text-blue-500" />
            </div>
            {scanning && !scanData ? (
              <div className="h-9 mt-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
            ) : (
              <>
                <div className="font-mono text-2xl sm:text-3xl font-bold text-zinc-950 dark:text-zinc-50 mt-2">
                  {kpis.enabledSafeVcpus.toLocaleString()}{' '}
                  <span className="text-sm font-medium text-zinc-500">vCPUs</span>
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1.5">
                  Across {enabledFamilySet.size} ladder-enabled families (
                  <span className="font-mono">
                    {kpis.allFamiliesSafeVcpus.toLocaleString()}
                  </span>{' '}
                  total across {selectedFamilies.length} scanned)
                </p>
              </>
            )}
          </div>

          {/* KPI 2 */}
          <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              <span>{spotSharePct}/{100 - spotSharePct} Quant Grid Coverage</span>
              <Layers className="w-4 h-4 text-emerald-500" />
            </div>
            {scanning && !scanData ? (
              <div className="h-9 mt-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
            ) : (
              <>
                <div className="flex items-baseline gap-2.5 mt-2">
                  <span className="font-mono text-2xl sm:text-3xl font-bold text-zinc-950 dark:text-zinc-50">
                    {portfolioPlan.coveragePct}%
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded-md text-xs font-semibold ${
                      portfolioPlan.coveragePct >= 100
                        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                        : 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300'
                    }`}
                  >
                    {portfolioPlan.coveragePct >= 100
                      ? 'Full Spot Target Met'
                      : `${portfolioPlan.shortfallVcpus.toLocaleString()} vCPU gap`}
                  </span>
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1.5">
                  Target:{' '}
                  <b className="font-mono">{targetSpotVcpus.toLocaleString()}</b> Spot +{' '}
                  <b className="font-mono">{targetCudVcpus.toLocaleString()}</b> CUD/OD
                </p>
              </>
            )}
          </div>

          {/* KPI 3 */}
          <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              <span>Primary Storage Anchor Region</span>
              <Server className="w-4 h-4 text-indigo-500" />
            </div>
            {scanning && !scanData ? (
              <div className="h-9 mt-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
            ) : (
              <>
                <div className="font-mono text-xl sm:text-2xl font-bold text-zinc-950 dark:text-zinc-50 mt-2 truncate">
                  {kpis.topRegion ? kpis.topRegion.region : '—'}
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1.5 truncate">
                  {kpis.topRegion
                    ? `${kpis.topRegion.vcpus.toLocaleString()} safe Spot vCPUs • Deepest anchor for GCS Anywhere Cache`
                    : 'Select regions to identify deepest anchor'}
                </p>
              </>
            )}
          </div>

          {/* KPI 4 */}
          <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              <span>
                {gcpDiscountPct > 0
                  ? `Weighted Net Spot Rate (-${gcpDiscountPct}%)`
                  : 'Weighted Portfolio Spot Rate'}
              </span>
              <DollarSign className="w-4 h-4 text-amber-500" />
            </div>
            {scanning && !scanData ? (
              <div className="h-9 mt-2 rounded-lg bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
            ) : (
              <>
                <div className="font-mono text-2xl sm:text-3xl font-bold text-zinc-950 dark:text-zinc-50 mt-2">
                  {portfolioPlan.weightedSpotVcpuHr !== null
                    ? `$${portfolioPlan.weightedSpotVcpuHr.toFixed(4)}`
                    : '—'}
                  <span className="text-xs font-normal text-zinc-500"> /vCPU-hr</span>
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1.5">
                  Est. Spot burn:{' '}
                  <b className="font-mono text-zinc-800 dark:text-zinc-200">
                    ${Math.round(portfolioPlan.totalSpotCostHr).toLocaleString()}/hr
                  </b>{' '}
                  {gcpDiscountPct > 0 ? `(incl. ${gcpDiscountPct}% GCP disc.)` : 'at allocated burst'}
                </p>
              </>
            )}
          </div>
        </section>

        {/* Underline Navigation Tabs */}
        <nav className="border-b border-zinc-200 dark:border-zinc-800 flex items-center gap-6 overflow-x-auto">
          {[
            {
              id: 'scanner',
              label: 'Live Regional Spot Scanner',
              icon: Activity,
            },
            {
              id: 'portfolio',
              label: '1M-vCPU Portfolio & Fallback Ladder',
              icon: Sliders,
            },
            {
              id: 'analytics',
              label: 'Capacity & Pricing Analytics',
              icon: BarChart3,
            },
            {
              id: 'playbook',
              label: 'Architecture Guide & Standalone CLI',
              icon: BookOpen,
            },
          ].map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                id={`tab-${tab.id}`}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 pb-3 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap cursor-pointer ${
                  active
                    ? 'border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400'
                    : 'border-transparent text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200'
                }`}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
              </button>
            );
          })}
        </nav>

        {/* TAB 1: LIVE REGIONAL SPOT SCANNER */}
        {activeTab === 'scanner' && (
          <section className="space-y-4">
            {/* Filter Controls Bar (relative z-30 above sticky table header) */}
            <div className="relative z-30 bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-4 shadow-sm flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-3">
                {/* Search */}
                <div className="relative">
                  <Search className="w-4 h-4 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    id="scanner-search-input"
                    type="text"
                    placeholder="Filter region, GCP, AWS (m7i/c7a), Azure (D96s_v6)..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9 pr-3 py-1.5 rounded-xl text-xs bg-zinc-100/80 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-blue-500 w-72"
                  />
                </div>

                {/* Geo Filter */}
                <select
                  id="geo-filter-select"
                  value={geoFilter}
                  onChange={(e) => setGeoFilter(e.target.value)}
                  className="px-3 py-1.5 rounded-xl text-xs font-medium bg-zinc-100/80 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-800 dark:text-zinc-200 cursor-pointer"
                >
                  <option value="ALL">All Geographies</option>
                  <option value="APAC">APAC Regions Only</option>
                  <option value="EMEA">EMEA (Europe + ME + Africa)</option>
                  <option value="Europe">Europe Only</option>
                  <option value="Middle East">Middle East Only</option>
                  <option value="Africa">Africa Only</option>
                  <option value="AMER">Americas (US + CA + LATAM)</option>
                  <option value="North America">North America Only</option>
                  <option value="South America">South America Only</option>
                </select>

                {/* Shape Profile Selector */}
                <select
                  id="shape-profile-select"
                  value={shapeProfile}
                  disabled={scanning}
                  onChange={(e) => {
                    const nextProf = e.target.value;
                    setShapeProfile(nextProf);
                    triggerScan(
                      false,
                      minScore,
                      perZoneUnlock,
                      selectedRegions,
                      selectedFamilies,
                      nextProf
                    );
                  }}
                  className="px-3 py-1.5 rounded-xl text-xs font-medium bg-zinc-100/80 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-800 dark:text-zinc-200 cursor-pointer disabled:opacity-50"
                  title="Choose which VM shape class to probe per family"
                >
                  <option value="standard">Shape Tier: Standard (Default)</option>
                  <option value="highmem">Shape Tier: High-Mem / Ultramem</option>
                  <option value="highcpu">Shape Tier: High-CPU</option>
                  <option value="lssd">Shape Tier: Local SSD (-lssd)</option>
                  <option value="largest">Shape Tier: Max Core Size</option>
                </select>

                {/* Lifecycle Filter */}
                <select
                  id="lifecycle-filter-select"
                  value={lifecycleFilter}
                  onChange={(e) => setLifecycleFilter(e.target.value)}
                  className="px-3 py-1.5 rounded-xl text-xs font-medium bg-zinc-100/80 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-800 dark:text-zinc-200 cursor-pointer"
                >
                  <option value="HIDE_SUNSET">Current-Gen & High-Yield Pools</option>
                  <option value="RECOMMENDED_ONLY">Recommended Latest-Gen Only</option>
                  <option value="ALL">Show All {selectedFamilies.length} Selected Families</option>
                </select>

                {/* Min Obtainability Filter */}
                <select
                  id="min-score-select"
                  value={minScore}
                  disabled={scanning}
                  onChange={(e) => {
                    const nextScore = parseFloat(e.target.value);
                    setMinScore(nextScore);
                    triggerScan(
                      false,
                      nextScore,
                      perZoneUnlock,
                      selectedRegions,
                      selectedFamilies,
                      shapeProfile
                    );
                  }}
                  className="px-3 py-1.5 rounded-xl text-xs font-medium bg-zinc-100/80 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-800 dark:text-zinc-200 cursor-pointer disabled:opacity-50"
                >
                  <option value={0.5}>Min Obtainability ≥ 50% (Medium+)</option>
                  <option value={0.7}>Min Obtainability ≥ 70% (High Only)</option>
                </select>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                {/* Enterprise GCP Discount % Modeling Control */}
                <div
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl border text-xs transition-colors ${
                    gcpDiscountPct > 0
                      ? 'bg-emerald-50/90 dark:bg-emerald-950/40 border-emerald-300 dark:border-emerald-700 text-emerald-800 dark:text-emerald-300'
                      : 'bg-zinc-100/80 dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300'
                  }`}
                  title="Model an enterprise percentage discount off GCP public list Spot pricing across all tables, charts & peer deltas"
                >
                  <span className="font-semibold whitespace-nowrap">GCP Discount:</span>
                  <input
                    id="gcp-discount-input"
                    type="number"
                    min={0}
                    max={60}
                    step={1}
                    value={gcpDiscountPct}
                    onChange={(e) => {
                      const raw = Number(e.target.value);
                      if (Number.isNaN(raw)) {
                        setGcpDiscountPct(0);
                      } else {
                        setGcpDiscountPct(Math.min(60, Math.max(0, raw)));
                      }
                    }}
                    className="w-11 px-1.5 py-0.5 rounded-md bg-white dark:bg-zinc-950 border border-zinc-300 dark:border-zinc-700 font-mono text-xs font-bold text-right text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-emerald-500"
                  />
                  <span className="font-mono font-semibold">%</span>
                  <div className="hidden sm:inline-flex items-center gap-1 ml-1 pl-1.5 border-l border-zinc-300/70 dark:border-zinc-700">
                    {[0, 20, 25, 30].map((preset) => (
                      <button
                        key={preset}
                        type="button"
                        onClick={() => setGcpDiscountPct(preset)}
                        className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold transition-colors cursor-pointer ${
                          gcpDiscountPct === preset
                            ? 'bg-emerald-600 text-white'
                            : 'bg-white/80 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700'
                        }`}
                      >
                        {preset}%
                      </button>
                    ))}
                  </div>
                </div>

                {/* Hide / Show AWS & Azure Peer Pricing Columns Toggle */}
                <button
                  id="toggle-peer-pricing-btn"
                  type="button"
                  onClick={() => setShowPeerPricing((v) => !v)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border transition-colors cursor-pointer ${
                    showPeerPricing
                      ? 'bg-blue-50 dark:bg-blue-950/50 border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300'
                      : 'bg-zinc-100/80 dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                  title="Show or hide the 4 AWS & Azure equivalent VM and live Spot pricing columns"
                >
                  {showPeerPricing ? (
                    <>
                      <Eye className="w-3.5 h-3.5" />
                      <span>AWS / Azure Peers</span>
                    </>
                  ) : (
                    <>
                      <EyeOff className="w-3.5 h-3.5" />
                      <span>AWS / Azure Hidden</span>
                    </>
                  )}
                </button>

                <label className="inline-flex items-center gap-2 text-xs font-medium text-zinc-700 dark:text-zinc-300 cursor-pointer select-none">
                  <input
                    id="only-available-checkbox"
                    type="checkbox"
                    checked={onlyAvailable}
                    onChange={(e) => setOnlyAvailable(e.target.checked)}
                    className="w-4 h-4 accent-emerald-600 rounded cursor-pointer"
                  />
                  Available Pools Only (&gt;0 vCPUs)
                </label>

                {/* Per-Zone Deep Unlock Toggle */}
                <label className="inline-flex items-center gap-2 text-xs font-medium text-zinc-700 dark:text-zinc-300 cursor-pointer select-none">
                  <input
                    id="per-zone-unlock-checkbox"
                    type="checkbox"
                    checked={perZoneUnlock}
                    disabled={scanning}
                    onChange={(e) => {
                      const nextVal = e.target.checked;
                      setPerZoneUnlock(nextVal);
                      triggerScan(
                        false,
                        minScore,
                        nextVal,
                        selectedRegions,
                        selectedFamilies,
                        shapeProfile
                      );
                    }}
                    className="w-4 h-4 accent-blue-600 rounded cursor-pointer"
                  />
                  Per-Zone Unlock (Bypass 1,000-VM API Cap)
                </label>
              </div>
            </div>

            {/* Split View: Table (w-full or w-2/3) + Slide-In Investigation Drawer (w-1/3) */}
            <div className="flex flex-col lg:flex-row gap-4 items-start">
              <div
                className={`w-full ${
                  selectedPool ? 'lg:w-2/3' : 'lg:w-full'
                } bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 shadow-sm overflow-hidden transition-all duration-300`}
              >
                <div className="overflow-x-auto max-h-[680px]">
                  <table className="w-full text-left border-collapse">
                    <thead className="sticky top-0 z-10 bg-zinc-100/95 dark:bg-zinc-900/95 backdrop-blur border-b border-zinc-200 dark:border-zinc-800 text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                      <tr>
                        <th className="py-3 px-3 whitespace-nowrap">Region</th>
                        <th className="py-3 px-3 whitespace-nowrap">GCP Family & Shape</th>
                        <th className="py-3 px-3 whitespace-nowrap">Lifecycle</th>
                        <th className="py-3 px-3 text-right whitespace-nowrap">Safe Pool</th>
                        <th className="py-3 px-3 whitespace-nowrap">Obtainability</th>
                        <th className="py-3 px-3 text-right whitespace-nowrap">30d Preempt</th>
                        <th className="py-3 px-3 text-right whitespace-nowrap text-blue-600 dark:text-blue-400">
                          {gcpDiscountPct > 0
                            ? `GCP Net $/vCPU (-${gcpDiscountPct}%)`
                            : 'GCP Spot $/vCPU'}
                        </th>
                        {showPeerPricing && (
                          <>
                            <th className="py-3 px-3 whitespace-nowrap border-l border-zinc-200/80 dark:border-zinc-800 text-orange-600 dark:text-orange-400">
                              AWS Equiv. VM
                            </th>
                            <th className="py-3 px-3 text-right whitespace-nowrap text-orange-600 dark:text-orange-400">
                              AWS Spot $/vCPU
                            </th>
                            <th className="py-3 px-3 whitespace-nowrap border-l border-zinc-200/80 dark:border-zinc-800 text-sky-600 dark:text-sky-400">
                              Azure Equiv. VM
                            </th>
                            <th className="py-3 px-3 text-right whitespace-nowrap text-sky-600 dark:text-sky-400">
                              Azure Spot $/vCPU
                            </th>
                          </>
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-200/70 dark:divide-zinc-800/70 text-xs">
                      {scanning && !scanData ? (
                        Array.from({ length: 8 }).map((_, idx) => (
                          <tr key={idx}>
                            <td colSpan={showPeerPricing ? 11 : 7} className="p-3">
                              <div className="h-8 rounded-lg bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
                            </td>
                          </tr>
                        ))
                      ) : paginatedPools.length === 0 ? (
                        <tr>
                          <td
                            colSpan={showPeerPricing ? 11 : 7}
                            className="py-12 text-center text-zinc-500 dark:text-zinc-400"
                          >
                            No Spot pools match your current filter criteria.
                          </td>
                        </tr>
                      ) : (
                        paginatedPools.map((pool) => {
                          const isSelected = selectedPool?.id === pool.id;
                          const aws = pool.aws_equiv;
                          const az = pool.azure_equiv;
                          const effGcpVcpuHr =
                            pool.spot_price_vcpu_hr !== null &&
                            pool.spot_price_vcpu_hr !== undefined
                              ? pool.spot_price_vcpu_hr * gcpDiscountFactor
                              : null;
                          const effGcpVmHr =
                            pool.spot_price_vm_hr !== null &&
                            pool.spot_price_vm_hr !== undefined
                              ? pool.spot_price_vm_hr * gcpDiscountFactor
                              : null;
                          const awsDelta = computeDeltaPct(
                            aws?.spot_vcpu_hr,
                            effGcpVcpuHr
                          );
                          const azDelta = computeDeltaPct(
                            az?.spot_vcpu_hr,
                            effGcpVcpuHr
                          );
                          return (
                            <tr
                              key={pool.id}
                              onClick={() =>
                                setSelectedPool(isSelected ? null : pool)
                              }
                              className={`cursor-pointer transition-colors ${
                                isSelected
                                  ? 'bg-blue-50/90 dark:bg-blue-950/35'
                                  : 'hover:bg-zinc-50 dark:hover:bg-zinc-900/60'
                              }`}
                            >
                              <td className="py-2.5 px-3 whitespace-nowrap">
                                <div className="font-semibold text-zinc-950 dark:text-zinc-50">
                                  {pool.region}
                                </div>
                                <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
                                  {pool.region_label.split(' (')[0]} • {pool.geo}
                                </div>
                              </td>
                              <td className="py-2.5 px-3 whitespace-nowrap">
                                <div className="flex items-center gap-1.5">
                                  <span
                                    className="w-2.5 h-2.5 rounded-full shrink-0"
                                    style={{
                                      backgroundColor:
                                        familyColors[pool.family] || '#3b82f6',
                                    }}
                                  />
                                  <span className="font-bold text-zinc-900 dark:text-zinc-100">
                                    {pool.family}
                                  </span>
                                  <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
                                    {pool.machine_type}
                                  </span>
                                </div>
                                <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                                  {pool.vcpus_per_vm} vCPUs • {pool.memory_gb_per_vm} GB
                                </div>
                              </td>
                              <td className="py-2.5 px-3 whitespace-nowrap">
                                <LifecyclePill
                                  lifecycle={pool.lifecycle}
                                  label={pool.lifecycle_label}
                                />
                              </td>
                              <td className="py-2.5 px-3 text-right whitespace-nowrap">
                                {pool.supported ? (
                                  <>
                                    <div className="font-mono text-sm font-bold text-zinc-950 dark:text-zinc-50">
                                      {pool.max_vcpus.toLocaleString()} vCPUs
                                    </div>
                                    <div className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400 flex items-center justify-end gap-1">
                                      <span>{pool.max_vms.toLocaleString()} VMs</span>
                                      {pool.max_vms > 1000 && (
                                        <span className="px-1 py-0.2 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 text-[10px] font-semibold">
                                          Zonal+
                                        </span>
                                      )}
                                    </div>
                                  </>
                                ) : (
                                  <span className="text-zinc-400">Unsupported</span>
                                )}
                              </td>
                              <td className="py-2.5 px-3 whitespace-nowrap">
                                {pool.supported ? (
                                  <ObtainabilityBar
                                    score={pool.obtainability}
                                    label={pool.obtainability_label}
                                    maxVms={pool.max_vms}
                                  />
                                ) : (
                                  <span className="text-zinc-400">—</span>
                                )}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono whitespace-nowrap">
                                {pool.preemption_rate_30d !== null &&
                                pool.preemption_rate_30d !== undefined ? (
                                  <span
                                    className={
                                      pool.preemption_rate_30d <= 5
                                        ? 'text-emerald-600 dark:text-emerald-400 font-semibold'
                                        : pool.preemption_rate_30d <= 15
                                        ? 'text-amber-600 dark:text-amber-400 font-semibold'
                                        : 'text-rose-600 dark:text-rose-400 font-semibold'
                                    }
                                  >
                                    {pool.preemption_rate_30d.toFixed(1)}%
                                  </span>
                                ) : (
                                  <span className="text-zinc-400">—</span>
                                )}
                              </td>
                              <td className="py-2.5 px-3 text-right font-mono whitespace-nowrap">
                                {effGcpVcpuHr !== null ? (
                                  <div>
                                    <div className="font-bold text-blue-700 dark:text-blue-300">
                                      ${effGcpVcpuHr.toFixed(4)}
                                    </div>
                                    <div className="text-[11px] text-zinc-500">
                                      {gcpDiscountPct > 0 ? (
                                        <span title={`Public list Spot: $${pool.spot_price_vcpu_hr.toFixed(4)}/vCPU-hr`}>
                                          <span className="line-through text-zinc-400 mr-1">
                                            ${pool.spot_price_vcpu_hr.toFixed(4)}
                                          </span>
                                          ${effGcpVmHr?.toFixed(2)}/VM
                                        </span>
                                      ) : (
                                        <span>${effGcpVmHr?.toFixed(2)}/VM</span>
                                      )}
                                    </div>
                                  </div>
                                ) : (
                                  <span className="text-zinc-400">—</span>
                                )}
                              </td>

                              {showPeerPricing && (
                                <>
                                  {/* Column 8: AWS Equivalent VM */}
                                  <td className="py-2.5 px-3 border-l border-zinc-200/70 dark:border-zinc-800/70 whitespace-nowrap">
                                    {aws ? (
                                      <div>
                                        <div className="font-mono text-[11px] font-semibold text-zinc-800 dark:text-zinc-200">
                                          {aws.sku}
                                        </div>
                                        <div
                                          className="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5"
                                          title={
                                            aws.region_exact
                                              ? `Exact AWS region match (${aws.region})`
                                              : `Nearest AWS region peer (${aws.region})`
                                          }
                                        >
                                          {aws.vcpus ? `${aws.vcpus}v` : '—'}
                                          {aws.ram_gb ? ` • ${Math.round(aws.ram_gb)} GB` : ''} •{' '}
                                          <span className="font-mono">
                                            {aws.region_exact ? aws.region : `~${aws.region}`}
                                          </span>
                                        </div>
                                      </div>
                                    ) : (
                                      <span className="text-zinc-400">—</span>
                                    )}
                                  </td>

                                  {/* Column 9: AWS Spot Pricing */}
                                  <td className="py-2.5 px-3 text-right font-mono whitespace-nowrap">
                                    {aws &&
                                    aws.spot_vcpu_hr !== null &&
                                    aws.spot_vcpu_hr !== undefined ? (
                                      <div>
                                        <div className="flex items-center justify-end gap-1.5">
                                          <span className="font-semibold text-zinc-900 dark:text-zinc-100">
                                            ${aws.spot_vcpu_hr.toFixed(4)}
                                          </span>
                                          <PriceDeltaBadge pct={awsDelta} />
                                        </div>
                                        <div className="text-[11px] text-zinc-500 flex items-center justify-end gap-1.5">
                                          <span>${aws.spot_vm_hr?.toFixed(2)}/VM</span>
                                          {aws.interruption_band && (
                                            <span
                                              className="text-[10px] text-zinc-400"
                                              title={`AWS Spot Advisor interruption rate: ${aws.interruption_band}`}
                                            >
                                              ({aws.interruption_band})
                                            </span>
                                          )}
                                        </div>
                                      </div>
                                    ) : (
                                      <span className="text-[11px] text-zinc-400">N/A</span>
                                    )}
                                  </td>

                                  {/* Column 10: Azure Equivalent VM */}
                                  <td className="py-2.5 px-3 border-l border-zinc-200/70 dark:border-zinc-800/70 whitespace-nowrap">
                                    {az ? (
                                      <div>
                                        <div className="font-mono text-[11px] font-semibold text-zinc-800 dark:text-zinc-200">
                                          {az.sku}
                                        </div>
                                        <div
                                          className="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5"
                                          title={
                                            az.region_exact
                                              ? `Exact Azure region match (${az.region})`
                                              : `Nearest Azure region peer (${az.region})`
                                          }
                                        >
                                          {az.vcpus ? `${az.vcpus}v` : '—'}
                                          {az.ram_gb ? ` • ${Math.round(az.ram_gb)} GB` : ''} •{' '}
                                          <span className="font-mono">
                                            {az.region_exact ? az.region : `~${az.region}`}
                                          </span>
                                        </div>
                                      </div>
                                    ) : (
                                      <span className="text-zinc-400">—</span>
                                    )}
                                  </td>

                                  {/* Column 11: Azure Spot Pricing */}
                                  <td className="py-2.5 px-3 text-right font-mono whitespace-nowrap">
                                    {az &&
                                    az.spot_vcpu_hr !== null &&
                                    az.spot_vcpu_hr !== undefined ? (
                                      <div>
                                        <div className="flex items-center justify-end gap-1.5">
                                          <span className="font-semibold text-zinc-900 dark:text-zinc-100">
                                            ${az.spot_vcpu_hr.toFixed(4)}
                                          </span>
                                          <PriceDeltaBadge pct={azDelta} />
                                        </div>
                                        <div className="text-[11px] text-zinc-500">
                                          ${az.spot_vm_hr?.toFixed(2)}/VM
                                        </div>
                                      </div>
                                    ) : (
                                      <span className="text-[11px] text-zinc-400">N/A</span>
                                    )}
                                  </td>
                                </>
                              )}
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Footer & Icon-Only Pagination */}
                <div className="px-4 py-3 border-t border-zinc-200 dark:border-zinc-800 space-y-2 text-xs text-zinc-500 dark:text-zinc-400">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      Showing{' '}
                      <span className="font-mono font-semibold text-zinc-800 dark:text-zinc-200">
                        {filteredPools.length === 0
                          ? 0
                          : (page - 1) * pageSize + 1}
                      </span>
                      –
                      <span className="font-mono font-semibold text-zinc-800 dark:text-zinc-200">
                        {Math.min(page * pageSize, filteredPools.length)}
                      </span>{' '}
                      of{' '}
                      <span className="font-mono font-semibold text-zinc-800 dark:text-zinc-200">
                        {filteredPools.length}
                      </span>{' '}
                      pools •{' '}
                      Click any row to inspect top-down shape ladder & zonal shards
                    </div>
                    <div className="flex items-center gap-2">
                    <select
                      value={pageSize}
                      onChange={(e) => setPageSize(Number(e.target.value))}
                      className="px-2 py-1 rounded-lg text-xs bg-zinc-100 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-200 cursor-pointer"
                      title="Rows per page"
                    >
                      <option value={12}>12 / page</option>
                      <option value={20}>20 / page</option>
                      <option value={50}>50 / page</option>
                      <option value={100}>100 / page</option>
                    </select>
                    <button
                      type="button"
                      onClick={() => setPage(1)}
                      disabled={page === 1}
                      className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                      title="First page"
                    >
                      <ChevronsLeft className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                      title="Previous page"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    <span className="px-2.5 font-mono text-xs">
                      {page} / {totalPages}
                    </span>
                    <button
                      type="button"
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={page === totalPages}
                      className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                      title="Next page"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setPage(totalPages)}
                      disabled={page === totalPages}
                      className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                      title="Last page"
                    >
                      <ChevronsRight className="w-4 h-4" />
                    </button>
                  </div>
                  </div>
                  {/* Transparent Multi-Cloud Live Spot Feed Attribution */}
                  {showPeerPricing && (
                    <div className="pt-2 border-t border-zinc-200/60 dark:border-zinc-800/60 flex flex-wrap items-center justify-between gap-2 text-[11px] text-zinc-500 dark:text-zinc-400">
                      <div className="flex flex-wrap items-center gap-3">
                        <span className="font-medium text-zinc-600 dark:text-zinc-300">
                          Live Public Linux Spot Pricing (RAM/vCPU-matched):
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <span className="w-2 h-2 rounded-full bg-blue-500" />
                          GCP Capacity History API
                          {gcpDiscountPct > 0 && (
                            <span className="font-mono text-emerald-600 dark:text-emerald-400 font-semibold">
                              (-{gcpDiscountPct}%)
                            </span>
                          )}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <span
                            className={`w-2 h-2 rounded-full ${
                              scanData?.pricing_meta?.aws_live
                                ? 'bg-orange-500'
                                : 'bg-zinc-400'
                            }`}
                          />
                          AWS EC2 Live Spot JSON
                          {scanData?.pricing_meta?.aws_last_modified && (
                            <span className="font-mono text-[10px] text-zinc-400">
                              ({scanData.pricing_meta.aws_last_modified.slice(5, 22)} UTC)
                            </span>
                          )}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <span
                            className={`w-2 h-2 rounded-full ${
                              scanData?.pricing_meta?.azure_live
                                ? 'bg-sky-500'
                                : 'bg-zinc-400'
                            }`}
                          />
                          Azure Retail Prices API
                        </span>
                      </div>
                      <span>
                        Delta pills show peer $/vCPU-hr vs {gcpDiscountPct > 0 ? `GCP Net (-${gcpDiscountPct}%)` : 'GCP'} (<span className="text-emerald-600 dark:text-emerald-400 font-semibold">+%</span> = GCP lower; <span className="font-mono">~region</span> = nearest cloud geo peer)
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Slide-in Investigation Drawer */}
              {selectedPool && (
                <InvestigationDrawer
                  selectedPool={selectedPool}
                  project={project}
                  minScore={minScore}
                  shapeProfile={shapeProfile}
                  isDark={isDark}
                  gcpDiscountPct={gcpDiscountPct}
                  showPeerPricing={showPeerPricing}
                  onClose={() => setSelectedPool(null)}
                />
              )}
            </div>
          </section>
        )}

        {/* TAB 2: 1M-vCPU PORTFOLIO & FALLBACK LADDER */}
        {activeTab === 'portfolio' && (
          <section className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Left Column: Sliders + Sortable Fallback Ladder */}
              <div className="lg:col-span-5 bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm space-y-5">
                <div>
                  <h2 className="text-base font-bold text-zinc-950 dark:text-zinc-50">
                    Quant Grid Sizing & Fallback Pecking Order
                  </h2>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
                    Drag machine families to reorder your fallback priority. Common large-scale grid pattern pairs ~20% CUD / On-Demand baseline with ~80% multi-region Spot.
                  </p>
                </div>

                {/* Target Grid vCPUs Slider */}
                <div className="p-4 rounded-xl bg-zinc-50 dark:bg-zinc-900/60 border border-zinc-200/70 dark:border-zinc-800 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      Total Peak Grid Target
                    </span>
                    <span className="font-mono text-sm font-bold text-blue-600 dark:text-blue-400">
                      {targetTotalVcpus.toLocaleString()} vCPUs
                    </span>
                  </div>
                  <input
                    id="target-vcpus-slider"
                    type="range"
                    min={100000}
                    max={2000000}
                    step={50000}
                    value={targetTotalVcpus}
                    onChange={(e) => setTargetTotalVcpus(Number(e.target.value))}
                    className="w-full accent-blue-600 cursor-pointer"
                  />

                  <div className="flex items-center justify-between pt-2">
                    <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      Spot Burst vs. CUD/On-Demand Baseline
                    </span>
                    <span className="font-mono text-xs font-bold text-emerald-600 dark:text-emerald-400">
                      {spotSharePct}% Spot / {100 - spotSharePct}% CUD
                    </span>
                  </div>
                  <input
                    id="spot-share-slider"
                    type="range"
                    min={50}
                    max={95}
                    step={5}
                    value={spotSharePct}
                    onChange={(e) => setSpotSharePct(Number(e.target.value))}
                    className="w-full accent-emerald-600 cursor-pointer"
                  />

                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-zinc-200 dark:border-zinc-800 text-xs">
                    <div>
                      <span className="text-zinc-500">Spot Target:</span>{' '}
                      <b className="font-mono">{targetSpotVcpus.toLocaleString()}</b>
                    </div>
                    <div>
                      <span className="text-zinc-500">CUD/OD Anchor:</span>{' '}
                      <b className="font-mono">{targetCudVcpus.toLocaleString()}</b>
                    </div>
                  </div>
                </div>

                {/* Drag-and-Drop Sortable Ladder */}
                <SortableLadder
                  familyCatalogMap={familyCatalogMap}
                  familyTotals={familyTotals}
                />
              </div>

              {/* Right Column: Computed Allocation Plan Table */}
              <div className="lg:col-span-7 bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm flex flex-col">
                <div className="flex items-center justify-between gap-2 pb-4 border-b border-zinc-200 dark:border-zinc-800">
                  <div>
                    <h2 className="text-base font-bold text-zinc-950 dark:text-zinc-50">
                      Recommended Multi-Region Spot Burst Allocation
                    </h2>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                      Allocated{' '}
                      <b className="font-mono text-zinc-900 dark:text-zinc-100">
                        {portfolioPlan.allocatedTotal.toLocaleString()}
                      </b>{' '}
                      of{' '}
                      <b className="font-mono">
                        {targetSpotVcpus.toLocaleString()}
                      </b>{' '}
                      target Spot vCPUs ({portfolioPlan.coveragePct}%)
                    </p>
                  </div>
                  {portfolioPlan.shortfallVcpus > 0 && (
                    <span className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                      Add regions or enable fallback family (+
                      {portfolioPlan.shortfallVcpus.toLocaleString()} vCPUs needed)
                    </span>
                  )}
                </div>

                <div className="overflow-x-auto max-h-[520px] mt-3">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead className="sticky top-0 z-10 bg-zinc-100 dark:bg-zinc-900 text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                      <tr>
                        <th className="py-2.5 px-3">Priority</th>
                        <th className="py-2.5 px-3">Region</th>
                        <th className="py-2.5 px-3">Machine Shape</th>
                        <th className="py-2.5 px-3 text-right">Allocated VMs</th>
                        <th className="py-2.5 px-3 text-right">Allocated vCPUs</th>
                        <th className="py-2.5 px-3 text-right">Est. $/hr</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-200/70 dark:divide-zinc-800/70">
                      {portfolioPlan.allocations.map((row) => (
                        <tr
                          key={row.id}
                          className="hover:bg-zinc-50 dark:hover:bg-zinc-900/60"
                        >
                          <td className="py-2.5 px-3 font-mono font-semibold text-zinc-600 dark:text-zinc-300">
                            #{row.ladderRank} ({row.family})
                          </td>
                          <td className="py-2.5 px-3 font-medium text-zinc-900 dark:text-zinc-100">
                            {row.region}
                          </td>
                          <td className="py-2.5 px-3 font-mono text-zinc-700 dark:text-zinc-300">
                            {row.machine_type}
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono">
                            {row.allocatedVms.toLocaleString()}
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono font-bold text-zinc-950 dark:text-zinc-50">
                            {row.allocatedVcpus.toLocaleString()}
                          </td>
                          <td className="py-2.5 px-3 text-right font-mono text-zinc-700 dark:text-zinc-300">
                            {row.estHourlyUsd !== null
                              ? `$${row.estHourlyUsd.toFixed(2)}`
                              : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {/* Full-Width 1-Per-Row Portfolio Chart */}
            <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm">
              <h3 className="text-sm font-bold text-zinc-950 dark:text-zinc-50 mb-1">
                Allocated Spot Burst vCPUs by Region & Machine Family
              </h3>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-4">
                Visualizes how the {targetSpotVcpus.toLocaleString()} Spot vCPU target
                distributes across regions without double-counting intra-family host pools.
              </p>
              <div className="h-80 w-full">
                <ReactECharts
                  option={portfolioChartOption}
                  style={{ height: '100%', width: '100%' }}
                  notMerge={true}
                />
              </div>
            </div>
          </section>
        )}

        {/* TAB 3: CAPACITY & PRICING ANALYTICS (STRICT 1-CHART-PER-ROW) */}
        {activeTab === 'analytics' && (
          <section className="grid grid-cols-1 gap-6">
            <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm">
              <h2 className="text-base font-bold text-zinc-950 dark:text-zinc-50">
                Regional Safe Obtainable Spot Capacity by Machine Family (vCPUs)
              </h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 mb-4">
                Each stacked segment represents the safe non-overlapping family ceiling in
                that region via per-zone binary search.
              </p>
              <div className="h-96 w-full">
                <ReactECharts
                  option={regionalStackedChartOption}
                  style={{ height: '100%', width: '100%' }}
                  notMerge={true}
                />
              </div>
            </div>

            <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm">
              <h2 className="text-base font-bold text-zinc-950 dark:text-zinc-50">
                Spot Unit Economics ($/vCPU-hr) vs. 30-Day Preemption Rate (%)
              </h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 mb-4">
                Pulled live from Compute Engine <code className="font-mono">advice/capacityHistory</code>.
                Target pools with low Spot $/vCPU-hr and low 30-day preemption.
              </p>
              <div className="h-96 w-full">
                <ReactECharts
                  option={economicsChartOption}
                  style={{ height: '100%', width: '100%' }}
                  notMerge={true}
                />
              </div>
            </div>
          </section>
        )}

        {/* TAB 4: ARCHITECTURE GUIDE & STANDALONE CLI */}
        {activeTab === 'playbook' && (
          <section className="space-y-6">
            {/* Guardrails Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm">
                <div className="flex items-center gap-2 text-sm font-bold text-zinc-950 dark:text-zinc-50">
                  <ShieldCheck className="w-4 h-4 text-emerald-500" />
                  1. Bypassing the 1,000-VM API Cap
                </div>
                <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-2 leading-relaxed">
                  Spot Advisor enforces <code className="font-mono">size ≤ 1000</code>.
                  Probe maximum shapes first (<code className="font-mono">c4d-standard-384</code>,{' '}
                  <code className="font-mono">c4-standard-288</code>,{' '}
                  <code className="font-mono">n2d-standard-224</code>,{' '}
                  <code className="font-mono">n4-standard-80</code>) and query each zone
                  independently to unlock 3,000+ VMs/region without spinning trial VMs.
                </p>
              </div>

              <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm">
                <div className="flex items-center gap-2 text-sm font-bold text-zinc-950 dark:text-zinc-50">
                  <AlertTriangle className="w-4 h-4 text-amber-500" />
                  2. Multi-Family Instance Flexibility
                </div>
                <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-2 leading-relaxed">
                  Standardize primary commitments on latest-gen{' '}
                  <b>N4, C4D, and C4</b> for strong price-performance, while
                  adding <b>N2D</b> and <b>C3D</b> into{' '}
                  <code className="font-mono">instanceFlexibilityPolicy</code> for
                  burst diversification across regions.
                </p>
              </div>

              <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm">
                <div className="flex items-center gap-2 text-sm font-bold text-zinc-950 dark:text-zinc-50">
                  <Layers className="w-4 h-4 text-blue-500" />
                  3. 80/20 Commercial & Storage Architecture
                </div>
                <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-2 leading-relaxed">
                  Pair a <b>20% CUD / DWS Flex-Start baseline</b> with an{' '}
                  <b>80% multi-region Spot burst</b>. Co-locate Multi-Region{' '}
                  <b>Google Cloud Storage</b> with <b>GCS Anywhere Cache</b> (zonal
                  SSD cache) to accelerate repeated read-heavy batch sweeps and
                  reduce cross-zone data transfer.
                </p>
              </div>
            </div>

            {/* Standalone CLI Script Export */}
            <div className="bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 p-5 shadow-sm space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <h3 className="text-base font-bold text-zinc-950 dark:text-zinc-50 flex items-center gap-2">
                    <Terminal className="w-4 h-4 text-blue-500" />
                    Standalone CLI: <code className="font-mono">spot_advisor_scanner.py</code>
                  </h3>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                    Standalone Python script calling public Compute Engine Beta Capacity Advice REST APIs with standard Application Default Credentials (ADC).
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    id="copy-cli-btn"
                    type="button"
                    onClick={handleCopyCli}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-800 dark:text-zinc-100 transition-colors cursor-pointer"
                  >
                    {copiedCli ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-emerald-500" />
                        Copied!
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5" />
                        Copy Script
                      </>
                    )}
                  </button>
                  <button
                    id="download-cli-btn"
                    type="button"
                    onClick={handleDownloadCli}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white transition-colors cursor-pointer"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Download .py
                  </button>
                </div>
              </div>

              <pre className="p-4 rounded-xl bg-zinc-100 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 text-xs font-mono overflow-x-auto max-h-96 leading-relaxed border border-zinc-200 dark:border-zinc-800 transition-colors">
                <code>{catalog?.cli_script || '# Loading script...'}</code>
              </pre>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
