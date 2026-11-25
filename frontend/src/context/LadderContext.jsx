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

import React, { createContext, useCallback, useContext, useState } from 'react';

const CHART_PALETTE = [
  '#3b82f6', // blue
  '#10b981', // emerald
  '#06b6d4', // cyan
  '#f59e0b', // amber
  '#f97316', // orange
  '#ef4444', // rose
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#14b8a6', // teal
  '#84cc16', // lime
  '#6366f1', // indigo
  '#0ea5e9', // sky
  '#d946ef', // fuchsia
  '#eab308', // yellow
  '#22c55e', // green
  '#fb7185', // light rose
  '#a855f7', // purple
];

const DEFAULT_PORTFOLIO_ENABLED = new Set(['N4', 'C4D', 'C4', 'N2D']);

const DEFAULT_LADDER = [
  { id: 'N4', enabled: true, color: CHART_PALETTE[0] },
  { id: 'C4D', enabled: true, color: CHART_PALETTE[1] },
  { id: 'C4', enabled: true, color: CHART_PALETTE[2] },
  { id: 'N2D', enabled: true, color: CHART_PALETTE[3] },
  { id: 'C3D', enabled: false, color: CHART_PALETTE[4] },
  { id: 'N2', enabled: false, color: CHART_PALETTE[5] },
];

const LadderContext = createContext(null);

export function LadderProvider({ children }) {
  const [ladder, setLadder] = useState(DEFAULT_LADDER);
  const [targetTotalVcpus, setTargetTotalVcpus] = useState(1000000);
  const [spotSharePct, setSpotSharePct] = useState(80);

  const syncCatalogFamilies = useCallback((catalogFamilies = []) => {
    if (!catalogFamilies.length) return;
    setLadder((prev) => {
      const existingMap = new Map(prev.map((item) => [item.id, item]));
      const next = [...prev];
      catalogFamilies.forEach((fam, idx) => {
        if (!existingMap.has(fam.id)) {
          next.push({
            id: fam.id,
            enabled: DEFAULT_PORTFOLIO_ENABLED.has(fam.id),
            color: CHART_PALETTE[idx % CHART_PALETTE.length],
          });
        }
      });
      return next;
    });
  }, []);

  const toggleFamilyInLadder = (familyId) => {
    setLadder((prev) =>
      prev.map((item) =>
        item.id === familyId ? { ...item, enabled: !item.enabled } : item
      )
    );
  };

  const familyColors = ladder.reduce((acc, item) => {
    acc[item.id] = item.color;
    return acc;
  }, {});

  return (
    <LadderContext.Provider
      value={{
        ladder,
        setLadder,
        syncCatalogFamilies,
        toggleFamilyInLadder,
        familyColors,
        chartPalette: CHART_PALETTE,
        targetTotalVcpus,
        setTargetTotalVcpus,
        spotSharePct,
        setSpotSharePct,
      }}
    >
      {children}
    </LadderContext.Provider>
  );
}

export function useLadder() {
  const ctx = useContext(LadderContext);
  if (!ctx) {
    throw new Error('useLadder must be used within a LadderProvider');
  }
  return ctx;
}
