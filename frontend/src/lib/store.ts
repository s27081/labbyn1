import { create } from 'zustand'
import type { Equipment, Wall } from '@/types/types'

interface LabState {
  equipment: Record<string, Equipment>
  walls: Record<string, Wall>
  hasUnsavedChanges: boolean
  initEquipment: (eqArray: Array<Equipment>) => void
  addEquipment: (eq: Equipment) => void
  updateMultipleEquipment: (
    updates: Array<{ id: string; updates: Partial<Equipment> }>,
  ) => void
  deleteMultipleEquipment: (ids: Array<string>) => void
  getEquipmentArray: () => Array<Equipment>
  initWalls: (wallArray: Array<Wall>) => void
  addWall: (wall: Wall) => void
  updateMultipleWalls: (
    updates: Array<{ id: string; updates: Partial<Wall> }>,
  ) => void
  deleteMultipleWalls: (ids: Array<string>) => void
  getWallsArray: () => Array<Wall>
  markSaved: () => void
}

export const useLabStore = create<LabState>((set, get) => ({
  equipment: {},
  walls: {},
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

  initWalls: (wallArray) =>
    set({
      walls: Object.fromEntries(wallArray.map((w) => [w.id, w])),
      hasUnsavedChanges: false,
    }),

  addWall: (wall) =>
    set((state) => ({
      walls: { ...state.walls, [wall.id]: wall },
      hasUnsavedChanges: true,
    })),

  updateMultipleWalls: (updatesList) =>
    set((state) => {
      const newWalls = { ...state.walls }
      updatesList.forEach(({ id, updates }) => {
        if (newWalls[id]) newWalls[id] = { ...newWalls[id], ...updates }
      })
      return { walls: newWalls, hasUnsavedChanges: true }
    }),

  deleteMultipleWalls: (ids) =>
    set((state) => {
      const newWalls = { ...state.walls }
      ids.forEach((id) => delete newWalls[id])
      return { walls: newWalls, hasUnsavedChanges: true }
    }),

  getWallsArray: () => Object.values(get().walls),

  markSaved: () => set({ hasUnsavedChanges: false }),
}))
