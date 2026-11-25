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

import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import ReactECharts from 'echarts-for-react';
import { format, parseISO } from 'date-fns';
import {
  X,
  Layers,
  ShieldAlert,
  TrendingDown,
  MapPin,
  Cpu,
} from 'lucide-react';

function safeFormatDate(isoStr, pattern = 'MMM dd, yyyy') {
  if (!isoStr) return '—';
  try {
    return format(parseISO(isoStr), pattern);
  } catch {
    return isoStr.slice(0, 10);
  }
}

export default function InvestigationDrawer({
  selectedPool,
  project,
  minScore,
  shapeProfile = 'standard',
  isDark,
  gcpDiscountPct = 0,
  showPeerPricing = true,
  onClose,
}) {
  const gcpDiscountFactor = Math.max(
    0.1,
    1 - Math.min(70, Math.max(0, gcpDiscountPct)) / 100
  );
  const [drilldown, setDrilldown] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedRungIdx, setSelectedRungIdx] = useState(0);
  const [customMachineType, setCustomMachineType] = useState('');
  const [shapeClassFilter, setShapeClassFilter] = useState('all');

  useEffect(() => {
    setCustomMachineType('');
    setShapeClassFilter('all');
  }, [selectedPool?.id]);

  useEffect(() => {
    if (!selectedPool) {
      setDrilldown(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError('');
    setSelectedRungIdx(0);

    const params = {
      region: selectedPool.region,
      family: selectedPool.family,
      project,
      min_score: minScore,
      shape_profile: shapeProfile,
    };
    if (customMachineType) {
      params.machine_type = customMachineType;
    }

    axios
      .get('/api/pecking-order', { params })
      .then((res) => {
        if (!cancelled) {
          setDrilldown(res.data);
          const firstActiveIdx = (res.data.rungs || []).findIndex(
            (r) => r.supported && r.effective_vcpus > 0
          );
          if (firstActiveIdx >= 0) {
            setSelectedRungIdx(firstActiveIdx);
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err.response?.data?.detail ||
              err.message ||
              'Failed to run pecking-order drilldown.'
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedPool?.id, project, minScore, shapeProfile, customMachineType]);

  const filteredShapes = useMemo(() => {
    const all = drilldown?.available_shapes || [];
    if (shapeClassFilter === 'all') return all;
    return all.filter((sh) => sh.shape_class === shapeClassFilter);
  }, [drilldown?.available_shapes, shapeClassFilter]);

  if (!selectedPool) return null;

  const activeRung =
    drilldown?.rungs?.[selectedRungIdx] || drilldown?.rungs?.[0] || null;

  const priceSeries = activeRung?.price_history || selectedPool.price_history || [];

  const priceChartOption = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: isDark ? '#18181b' : '#ffffff',
      borderColor: isDark ? '#27272a' : '#e4e4e7',
      textStyle: {
        color: isDark ? '#f4f4f5' : '#18181b',
        fontSize: 12,
      },
      formatter: (params) => {
        if (!params || !params.length) return '';
        const p = params[0];
        const vcpuCount = activeRung?.vcpus || selectedPool.vcpus_per_vm || 1;
        const perVcpu = (p.value / vcpuCount).toFixed(4);
        return `<div style="font-weight:600;margin-bottom:4px">${p.axisValue}</div>
          <div>VM Spot Rate: <b>$${Number(p.value).toFixed(4)}/hr</b></div>
          <div>Per-vCPU Spot: <b>$${perVcpu}/vCPU-hr</b></div>`;
      },
    },
    grid: {
      top: 24,
      right: 16,
      bottom: 32,
      left: 56,
    },
    xAxis: {
      type: 'category',
      data: priceSeries.map((pt) => safeFormatDate(pt.start, 'MMM dd, yyyy')),
      axisLabel: {
        color: isDark ? '#a1a1aa' : '#71717a',
        fontSize: 10,
        hideOverlap: true,
      },
      axisLine: {
        lineStyle: { color: isDark ? '#27272a' : '#e4e4e7' },
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        color: isDark ? '#a1a1aa' : '#71717a',
        fontSize: 10,
        formatter: (v) => `$${Number(v).toFixed(2)}`,
      },
      splitLine: {
        lineStyle: {
          color: isDark ? '#27272a' : '#f4f4f5',
          type: 'dashed',
        },
      },
    },
    series: [
      {
        name: 'Spot VM $/hr',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        data: priceSeries.map((pt) => pt.usd_per_hr),
        lineStyle: {
          width: 2.5,
          color: '#3b82f6',
        },
        itemStyle: {
          color: '#3b82f6',
        },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(59, 130, 246, 0.28)' },
              { offset: 1, color: 'rgba(59, 130, 246, 0.02)' },
            ],
          },
        },
      },
    ],
  };

  return (
    <aside
      id="investigation-drawer"
      className="w-full lg:w-1/3 bg-white dark:bg-[#0c0c0f] rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 shadow-lg p-5 flex flex-col gap-4 transition-all duration-300 self-start lg:sticky lg:top-4"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 pb-3 border-b border-zinc-200 dark:border-zinc-800">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="px-2 py-0.5 rounded-md text-xs font-mono font-semibold bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
              {selectedPool.family}
            </span>
            <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
              {selectedPool.geo} • {selectedPool.category || 'Compute'}
            </span>
          </div>
          <h3 className="text-base font-bold text-zinc-950 dark:text-zinc-50 mt-1">
            {selectedPool.region_label}
          </h3>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Top-Down Pecking-Order & Full Shape Inspector
          </p>
        </div>
        <button
          id="close-drawer-btn"
          type="button"
          onClick={onClose}
          className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
          title="Close drilldown panel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Live Shape Selector Across ALL Possible VMs in This Family */}
      {drilldown?.available_shapes?.length > 0 && (
        <div className="p-3 rounded-xl bg-zinc-50 dark:bg-zinc-900/70 border border-zinc-200/80 dark:border-zinc-800 space-y-2">
          <div className="flex items-center justify-between text-xs font-semibold text-zinc-700 dark:text-zinc-200">
            <span className="flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-blue-500" />
              Inspect Specific VM Shape ({drilldown.available_shapes.length} in region)
            </span>
            {customMachineType && (
              <button
                type="button"
                onClick={() => setCustomMachineType('')}
                className="text-[11px] text-blue-600 dark:text-blue-400 hover:underline cursor-pointer"
              >
                Reset Ladder
              </button>
            )}
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            {['all', 'standard', 'highmem', 'highcpu', 'lssd', 'gpu'].map((cls) => {
              const count =
                cls === 'all'
                  ? drilldown.available_shapes.length
                  : drilldown.available_shapes.filter((s) => s.shape_class === cls).length;
              if (cls !== 'all' && count === 0) return null;
              return (
                <button
                  key={cls}
                  type="button"
                  onClick={() => setShapeClassFilter(cls)}
                  className={`px-2 py-0.5 rounded-md text-[11px] font-medium border cursor-pointer transition-colors ${
                    shapeClassFilter === cls
                      ? 'bg-blue-600 text-white border-blue-600'
                      : 'bg-white dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 border-zinc-200 dark:border-zinc-700'
                  }`}
                >
                  {cls.toUpperCase()} ({count})
                </button>
              );
            })}
          </div>
          <select
            id="drawer-shape-select"
            value={customMachineType}
            onChange={(e) => setCustomMachineType(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded-lg text-xs font-mono bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 cursor-pointer"
          >
            <option value="">
              Top-Down Family Ladder ({drilldown.rungs?.length || 0} key rungs)
            </option>
            {filteredShapes.map((sh) => (
              <option key={sh.type} value={sh.type}>
                {sh.type} ({sh.vcpus} vCPUs • {sh.memory_gb} GB RAM)
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Loading Skeleton */}
      {loading && (
        <div className="space-y-3 py-2" data-testid="drawer-loading">
          <div className="text-xs text-blue-600 dark:text-blue-400 font-medium flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-ping" />
            Probing {customMachineType || selectedPool.family} across zones...
          </div>
          <div className="h-20 rounded-xl bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
          <div className="h-36 rounded-xl bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
          <div className="h-44 rounded-xl bg-zinc-100 dark:bg-zinc-900 animate-pulse" />
        </div>
      )}

      {error && !loading && (
        <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-xs text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      {!loading && drilldown && (
        <>
          {/* Host-Pool Overlap Guardrail Banner */}
          <div className="p-3.5 rounded-xl bg-amber-50/90 dark:bg-amber-950/30 border border-amber-200/80 dark:border-amber-800/60">
            <div className="flex items-center gap-2 text-xs font-semibold text-amber-900 dark:text-amber-300">
              <ShieldAlert className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400" />
              Host-Pool Overlap Guardrail
            </div>
            <p className="text-xs text-amber-800/90 dark:text-amber-200/80 mt-1 leading-relaxed">
              Shapes inside <span className="font-mono font-semibold">{drilldown.family}</span> carve
              from the same physical hosts. Do <b>not</b> sum ladder rungs together.
            </p>
            <div className="grid grid-cols-2 gap-2 mt-2.5 pt-2.5 border-t border-amber-200/70 dark:border-amber-800/50">
              <div>
                <div className="text-[11px] uppercase tracking-wider text-emerald-700 dark:text-emerald-400 font-semibold">
                  Safe Family Ceiling
                </div>
                <div className="font-mono text-sm font-bold text-zinc-950 dark:text-zinc-50">
                  {drilldown.safe_non_overlapping_vcpus.toLocaleString()} vCPUs
                </div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wider text-rose-600 dark:text-rose-400 font-semibold">
                  Naive Sum (Overlapped)
                </div>
                <div className="font-mono text-sm font-semibold line-through text-zinc-500 dark:text-zinc-400">
                  {drilldown.naive_overlapping_sum_vcpus.toLocaleString()} vCPUs
                </div>
              </div>
            </div>
          </div>

          {/* Pecking-Order Shape Ladder */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5" />
                {customMachineType ? 'Selected Shape Probe' : 'Top-Down Shape Pecking Order'}
              </span>
              <span className="text-[11px] text-zinc-400">Click rung to inspect zones</span>
            </div>
            <div className="space-y-1.5">
              {drilldown.rungs.map((rung, idx) => {
                const isSelected = idx === selectedRungIdx;
                const isBest =
                  rung.effective_vcpus > 0 &&
                  rung.effective_vcpus === drilldown.safe_non_overlapping_vcpus;
                return (
                  <button
                    key={rung.machine_type}
                    type="button"
                    onClick={() => setSelectedRungIdx(idx)}
                    className={`w-full text-left p-2.5 rounded-xl border transition-colors cursor-pointer ${
                      isSelected
                        ? 'bg-blue-50/80 dark:bg-blue-950/30 border-blue-400 dark:border-blue-600'
                        : 'bg-zinc-50/70 dark:bg-zinc-900/50 border-zinc-200/70 dark:border-zinc-800 hover:bg-zinc-100/80 dark:hover:bg-zinc-800/70'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-mono text-xs font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                          {rung.machine_type}
                        </span>
                        {isBest && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                            MAX POOL
                          </span>
                        )}
                      </div>
                      <span className="font-mono text-xs font-bold text-zinc-950 dark:text-zinc-50">
                        {rung.supported
                          ? `${rung.effective_vcpus.toLocaleString()} vCPUs`
                          : 'Unsupported'}
                      </span>
                    </div>
                    {rung.supported && (
                      <div className="flex items-center justify-between text-[11px] text-zinc-500 dark:text-zinc-400 mt-1">
                        <span>
                          Region API: <b className="font-mono">{rung.regional_api_vms}</b> VMs →
                          Zonal Unlock:{' '}
                          <b className="font-mono text-blue-600 dark:text-blue-400">
                            {rung.per_zone_unlocked_vms}
                          </b>{' '}
                          VMs
                        </span>
                        <span className="font-mono">
                          Score: {(rung.obtainability * 100).toFixed(0)}%
                        </span>
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Per-Zone Breakdown for Active Rung */}
          {activeRung && activeRung.zone_breakdown?.length > 0 && (
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5 mb-2">
                <MapPin className="w-3.5 h-3.5" />
                Per-Zone Shards ({activeRung.machine_type})
              </div>
              <div className="grid grid-cols-3 gap-2">
                {activeRung.zone_breakdown.map((zb) => (
                  <div
                    key={zb.zone}
                    className="p-2.5 rounded-xl bg-zinc-50 dark:bg-zinc-900/70 border border-zinc-200/70 dark:border-zinc-800"
                  >
                    <div className="font-mono text-[11px] font-semibold text-zinc-600 dark:text-zinc-300 truncate">
                      {zb.zone}
                    </div>
                    <div className="font-mono text-sm font-bold text-zinc-950 dark:text-zinc-50 mt-0.5">
                      {zb.max_vms.toLocaleString()}{' '}
                      <span className="text-[11px] font-normal text-zinc-500">VMs</span>
                    </div>
                    <div className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
                      {zb.max_vcpus.toLocaleString()} vCPUs
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Live Multi-Cloud Head-to-Head Spot Benchmark */}
          {showPeerPricing &&
            (() => {
              const aws = activeRung?.aws_equiv || selectedPool.aws_equiv;
              const az = activeRung?.azure_equiv || selectedPool.azure_equiv;
              const rawGcpVcpuHr =
                activeRung?.spot_price_vcpu_hr ?? selectedPool.spot_price_vcpu_hr;
              const rawGcpVmHr =
                activeRung?.spot_price_vm_hr ?? selectedPool.spot_price_vm_hr;
              const gcpVcpuHr =
                rawGcpVcpuHr != null ? rawGcpVcpuHr * gcpDiscountFactor : null;
              const gcpVmHr =
                rawGcpVmHr != null ? rawGcpVmHr * gcpDiscountFactor : null;
              const awsDelta =
                aws?.spot_vcpu_hr != null && gcpVcpuHr != null && gcpVcpuHr > 0
                  ? ((aws.spot_vcpu_hr - gcpVcpuHr) / gcpVcpuHr) * 100
                  : null;
              const azDelta =
                az?.spot_vcpu_hr != null && gcpVcpuHr != null && gcpVcpuHr > 0
                  ? ((az.spot_vcpu_hr - gcpVcpuHr) / gcpVcpuHr) * 100
                  : null;
              const gcpShape = activeRung?.machine_type || selectedPool.machine_type;
              const gcpVcpus = activeRung?.vcpus || selectedPool.vcpus_per_vm;
              const gcpRam = activeRung?.memory_gb || selectedPool.memory_gb_per_vm;
              return (
                <div className="p-3 rounded-xl bg-zinc-50/90 dark:bg-zinc-900/70 border border-zinc-200/80 dark:border-zinc-800 space-y-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                    Multi-Cloud Spot Comparison ({gcpShape})
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[11px]">
                    <div className="p-2 rounded-lg bg-blue-50/70 dark:bg-blue-950/30 border border-blue-200/70 dark:border-blue-800/60">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-blue-700 dark:text-blue-300">GCP</span>
                        {gcpDiscountPct > 0 && (
                          <span className="font-mono text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                            -{gcpDiscountPct}%
                          </span>
                        )}
                      </div>
                      <div className="font-mono text-[10px] text-zinc-700 dark:text-zinc-300 truncate mt-0.5" title={gcpShape}>
                        {gcpShape}
                      </div>
                      <div className="font-mono text-xs font-bold text-zinc-950 dark:text-zinc-50 mt-1">
                        {gcpVcpuHr != null ? `$${gcpVcpuHr.toFixed(4)}/v` : '—'}
                      </div>
                      <div className="text-[10px] text-zinc-500 dark:text-zinc-400">
                        {gcpVmHr != null ? `$${gcpVmHr.toFixed(2)}/VM` : ''} • {gcpVcpus}v/{Math.round(gcpRam)}G
                      </div>
                    </div>
                    <div className="p-2 rounded-lg bg-orange-50/60 dark:bg-orange-950/20 border border-orange-200/70 dark:border-orange-800/50">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-orange-700 dark:text-orange-300">AWS</span>
                        {awsDelta != null && (
                          <span
                            className={`font-mono text-[10px] font-semibold ${
                              awsDelta > 0
                                ? 'text-emerald-600 dark:text-emerald-400'
                                : 'text-amber-600 dark:text-amber-400'
                            }`}
                          >
                            {awsDelta > 0 ? `+${awsDelta.toFixed(0)}%` : `${awsDelta.toFixed(0)}%`}
                          </span>
                        )}
                      </div>
                      <div className="font-mono text-[10px] text-zinc-700 dark:text-zinc-300 truncate mt-0.5" title={aws?.sku || ''}>
                        {aws?.sku || 'N/A'}
                      </div>
                      <div className="font-mono text-xs font-bold text-zinc-950 dark:text-zinc-50 mt-1">
                        {aws?.spot_vcpu_hr != null ? `$${aws.spot_vcpu_hr.toFixed(4)}/v` : 'N/A'}
                      </div>
                      <div className="text-[10px] text-zinc-500 dark:text-zinc-400 truncate">
                        {aws?.spot_vm_hr != null ? `$${aws.spot_vm_hr.toFixed(2)}/VM` : ''} {aws?.region ? `• ${aws.region}` : ''}
                      </div>
                    </div>
                    <div className="p-2 rounded-lg bg-sky-50/60 dark:bg-sky-950/20 border border-sky-200/70 dark:border-sky-800/50">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-sky-700 dark:text-sky-300">Azure</span>
                        {azDelta != null && (
                          <span
                            className={`font-mono text-[10px] font-semibold ${
                              azDelta > 0
                                ? 'text-emerald-600 dark:text-emerald-400'
                                : 'text-amber-600 dark:text-amber-400'
                            }`}
                          >
                            {azDelta > 0 ? `+${azDelta.toFixed(0)}%` : `${azDelta.toFixed(0)}%`}
                          </span>
                        )}
                      </div>
                      <div className="font-mono text-[10px] text-zinc-700 dark:text-zinc-300 truncate mt-0.5" title={az?.sku || ''}>
                        {az?.sku || 'N/A'}
                      </div>
                      <div className="font-mono text-xs font-bold text-zinc-950 dark:text-zinc-50 mt-1">
                        {az?.spot_vcpu_hr != null ? `$${az.spot_vcpu_hr.toFixed(4)}/v` : 'N/A'}
                      </div>
                      <div className="text-[10px] text-zinc-500 dark:text-zinc-400 truncate">
                        {az?.spot_vm_hr != null ? `$${az.spot_vm_hr.toFixed(2)}/VM` : ''} {az?.region ? `• ${az.region}` : ''}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}

          {/* 6-Month Floating Spot Price Chart */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5">
                <TrendingDown className="w-3.5 h-3.5" />
                Floating Spot Price History ({activeRung?.machine_type})
              </span>
              {activeRung?.preemption_rate_30d !== null &&
                activeRung?.preemption_rate_30d !== undefined && (
                  <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
                    30d Preemption: {activeRung.preemption_rate_30d.toFixed(1)}%
                  </span>
                )}
            </div>
            {priceSeries.length > 0 ? (
              <div className="h-48 w-full rounded-xl border border-zinc-200/70 dark:border-zinc-800 p-2 bg-zinc-50/40 dark:bg-zinc-900/30">
                <ReactECharts
                  option={priceChartOption}
                  style={{ height: '100%', width: '100%' }}
                  notMerge={true}
                />
              </div>
            ) : (
              <div className="p-4 rounded-xl border border-zinc-200/70 dark:border-zinc-800 text-xs text-zinc-500 text-center">
                No historical price series returned for this machine shape.
              </div>
            )}
          </div>

          {/* Architecture Guidance Note */}
          <div className="p-3 rounded-xl bg-zinc-50 dark:bg-zinc-900/70 border border-zinc-200/80 dark:border-zinc-800 text-xs text-zinc-600 dark:text-zinc-300 leading-relaxed">
            <span className="font-semibold text-zinc-900 dark:text-zinc-100">
              Architecture & AWS Reference ({drilldown.aws_mapping}):
            </span>{' '}
            {drilldown.lifecycle_note}
          </div>
        </>
      )}
    </aside>
  );
}
