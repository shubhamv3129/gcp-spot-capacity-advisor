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

import React, { useMemo, useState } from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import { useLadder } from '../context/LadderContext';

function LifecycleBadge({ lifecycle, label }) {
  if (lifecycle === 'RECOMMENDED') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
        <CheckCircle2 className="w-3 h-3" />
        {label}
      </span>
    );
  }
  if (lifecycle === 'DIVERSIFICATION') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400">
        <AlertTriangle className="w-3 h-3" />
        {label}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400">
      <XCircle className="w-3 h-3" />
      {label}
    </span>
  );
}

function SortableLadderItem({ item, index, meta, vcpuTotal, onToggle }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      id={`ladder-item-${item.id}`}
      className={`flex items-center justify-between gap-3 p-3 rounded-xl border transition-colors ${
        isDragging
          ? 'bg-blue-50 dark:bg-blue-900/30 border-blue-400 shadow-lg z-20'
          : item.enabled
          ? 'bg-white dark:bg-[#0c0c0f] border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-900/80'
          : 'bg-zinc-100/60 dark:bg-zinc-900/40 border-zinc-200/60 dark:border-zinc-800/60 opacity-65'
      }`}
    >
      <div className="flex items-center gap-3 min-w-0">
        <button
          type="button"
          id={`drag-handle-${item.id}`}
          {...attributes}
          {...listeners}
          className="cursor-grab active:cursor-grabbing text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 p-1"
          title="Drag to reorder fallback priority"
        >
          <GripVertical className="w-4 h-4" />
        </button>
        <span
          className="w-2.5 h-2.5 rounded-full shrink-0"
          style={{ backgroundColor: item.color }}
        />
        <span className="font-mono text-xs font-semibold px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
          #{index + 1}
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-sm text-zinc-950 dark:text-zinc-50">
              {item.id}
            </span>
            {meta && (
              <LifecycleBadge
                lifecycle={meta.lifecycle}
                label={meta.lifecycle_label}
              />
            )}
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 truncate">
            {meta ? `${meta.category || ''} • ${meta.aws_mapping}` : ''}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3 shrink-0">
        <div className="text-right">
          <div className="font-mono text-xs font-semibold text-zinc-900 dark:text-zinc-100">
            {(vcpuTotal || 0).toLocaleString()} vCPUs
          </div>
          <div className="text-xs text-zinc-500 dark:text-zinc-400">
            scanned pool
          </div>
        </div>
        <input
          id={`toggle-family-${item.id}`}
          type="checkbox"
          checked={item.enabled}
          onChange={() => onToggle(item.id)}
          className="w-4 h-4 accent-blue-500 rounded cursor-pointer"
          title={`Include ${item.id} in grid portfolio`}
        />
      </div>
    </div>
  );
}

export default function SortableLadder({ familyCatalogMap, familyTotals }) {
  const { ladder, setLadder, toggleFamilyInLadder } = useLadder();
  const [showAll, setShowAll] = useState(false);

  const visibleLadder = useMemo(() => {
    if (showAll) return ladder;
    return ladder.filter((item) => item.enabled || (familyTotals[item.id] || 0) > 0);
  }, [ladder, showAll, familyTotals]);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = (event) => {
    const { active, over } = event;
    if (over && active.id !== over.id) {
      setLadder((items) => {
        const oldIndex = items.findIndex((i) => i.id === active.id);
        const newIndex = items.findIndex((i) => i.id === over.id);
        return arrayMove(items, oldIndex, newIndex);
      });
    }
  };

  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-zinc-500 dark:text-zinc-400">
          Showing {visibleLadder.length} of {ladder.length} families
        </span>
        <button
          type="button"
          onClick={() => setShowAll((s) => !s)}
          className="text-blue-600 dark:text-blue-400 font-semibold hover:underline cursor-pointer"
        >
          {showAll ? 'Show Active / Scanned Only' : `Show All ${ladder.length} Families`}
        </button>
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={visibleLadder.map((i) => i.id)}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
            {visibleLadder.map((item, idx) => (
              <SortableLadderItem
                key={item.id}
                item={item}
                index={idx}
                meta={familyCatalogMap[item.id]}
                vcpuTotal={familyTotals[item.id] || 0}
                onToggle={toggleFamilyInLadder}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
}
