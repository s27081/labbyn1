import { create } from 'zustand'
import type { Equipment, WallNode, WallSegment } from '@/types/types'

interface LabState {
  equipment: Record<string, Equipment>
  wallNodes: Record<string, WallNode>
  wallSegments: Record<string, WallSegment>
  hasUnsavedChanges: boolean

  initEquipment: (eqArray: Array<Equipment>) => void
  addEquipment: (eq: Equipment) => void
  updateMultipleEquipment: (
    updates: Array<{ id: string; updates: Partial<Equipment> }>,
  ) => void
  deleteMultipleEquipment: (ids: Array<string>) => void
  getEquipmentArray: () => Array<Equipment>

  initWallNodes: (nodesArray: Array<WallNode>) => void
  addWallNode: (node: WallNode) => void
  updateMultipleWallNodes: (
    updates: Array<{ id: string; updates: Partial<WallNode> }>,
  ) => void
  deleteMultipleWallNodes: (ids: Array<string>) => void
  getWallNodesArray: () => Array<WallNode>

  initWallSegments: (segmentsArray: Array<WallSegment>) => void
  addWallSegment: (segment: WallSegment) => void
  deleteMultipleWallSegments: (ids: Array<string>) => void
  getWallSegmentsArray: () => Array<WallSegment>

  markSaved: () => void
}

export const useLabStore = create<LabState>((set, get) => ({
  equipment: {},
  wallNodes: {},
  wallSegments: {},
  hasUnsavedChanges: false,

  initEquipment: (eqArray) =>
    set({
      equipment: Object.fromEntries(eqArray.map((e) => [e.id, e])),
      hasUnsavedChanges: false,
    }),

  addEquipment: (eq) =>
    set((state) => ({
      equipment: { ...state.equipment, [eq.id]: eq },
      hasUnsavedChanges: true,
    })),

  updateMultipleEquipment: (updatesList) =>
    set((state) => {
      const newEq = { ...state.equipment }
      updatesList.forEach(({ id, updates }) => {
        if (newEq[id]) newEq[id] = { ...newEq[id], ...updates }
      })
      return { equipment: newEq, hasUnsavedChanges: true }
    }),

  deleteMultipleEquipment: (ids) =>
    set((state) => {
      const newEq = { ...state.equipment }
      ids.forEach((id) => delete newEq[id])
      return { equipment: newEq, hasUnsavedChanges: true }
    }),

  getEquipmentArray: () => Object.values(get().equipment),

  initWallNodes: (nodesArray) =>
    set({
      wallNodes: Object.fromEntries(nodesArray.map((n) => [n.id, n])),
      hasUnsavedChanges: false,
    }),

  addWallNode: (node) =>
    set((state) => ({
      wallNodes: { ...state.wallNodes, [node.id]: node },
      hasUnsavedChanges: true,
    })),

  updateMultipleWallNodes: (updatesList) =>
    set((state) => {
      const newNodes = { ...state.wallNodes }
      updatesList.forEach(({ id, updates }) => {
        if (newNodes[id]) newNodes[id] = { ...newNodes[id], ...updates }
      })
      return { wallNodes: newNodes, hasUnsavedChanges: true }
    }),

  deleteMultipleWallNodes: (ids) =>
    set((state) => {
      const newNodes = { ...state.wallNodes }
      ids.forEach((id) => delete newNodes[id])
      return { wallNodes: newNodes, hasUnsavedChanges: true }
    }),

  getWallNodesArray: () => Object.values(get().wallNodes),

  initWallSegments: (segmentsArray) =>
    set({
      wallSegments: Object.fromEntries(segmentsArray.map((s) => [s.id, s])),
      hasUnsavedChanges: false,
    }),

  addWallSegment: (segment) =>
    set((state) => ({
      wallSegments: { ...state.wallSegments, [segment.id]: segment },
      hasUnsavedChanges: true,
    })),

  deleteMultipleWallSegments: (ids) =>
    set((state) => {
      const newSegments = { ...state.wallSegments }
      ids.forEach((id) => delete newSegments[id])
      return { wallSegments: newSegments, hasUnsavedChanges: true }
    }),

  getWallSegmentsArray: () => Object.values(get().wallSegments),

  markSaved: () => set({ hasUnsavedChanges: false }),
}))
