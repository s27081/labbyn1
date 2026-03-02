import React, {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import {
  Billboard,
  ContactShadows,
  Environment,
  GizmoHelper,
  GizmoViewport,
  Grid,
  Instance,
  Instances,
  KeyboardControls,
  Loader,
  MapControls,
  OrthographicCamera,
  PerspectiveCamera,
  RoundedBox,
  Text,
  TransformControls,
  useKeyboardControls,
} from '@react-three/drei'
import * as THREE from 'three'
import { formatHex } from 'culori'
import { useNavigate } from '@tanstack/react-router'
import { useShallow } from 'zustand/react/shallow'
import { Save, Trash2, X } from 'lucide-react'

import { RackInfoPanel } from './rack-info-panel'
import { ControlsOverlay } from './controls-overlay'
import { MapToolbar } from './map-toolbar'
import { ViewSettings } from './view-settings'
import type { ThreeEvent } from '@react-three/fiber'
import type {
  MapControls as MapControlsImpl,
  TransformControls as TransformControlsImpl,
} from 'three-stdlib'
import type { Equipment, Wall } from '@/types/types'
import { Button } from '@/components/ui/button'
import { useLabStore } from '@/lib/store'

// --- Constants & Base Geometries ---
const RACK_SIZE = { w: 8, h: 20, d: 8 }
const WALL_H = 22
const WALL_T = 1.5

const wallGeometryBase = new THREE.BoxGeometry(1, WALL_H, WALL_T)
const glassGeometryBase = new THREE.PlaneGeometry(
  RACK_SIZE.w - 1,
  RACK_SIZE.h - 1,
)
const glassMaterialBase = new THREE.MeshStandardMaterial({
  color: '#FFF',
  metalness: 0.7,
  roughness: 0.7,
  transparent: true,
  opacity: 0.6,
  depthWrite: false,
})
const glowGeometryBase = new THREE.BoxGeometry(
  RACK_SIZE.w,
  RACK_SIZE.h,
  RACK_SIZE.d,
)
const rackGeometryBase = new THREE.BoxGeometry(
  RACK_SIZE.w,
  RACK_SIZE.h,
  RACK_SIZE.d,
)

export type EditMode =
  | 'view'
  | 'select'
  | 'add-rack'
  | 'add-wall'
  | 'add-label'
  | 'move'
  | 'rotate'
  | 'delete'

export interface LabLabel {
  id: string
  text: string
  x: number
  y: number
}

const snapToData = (v3d: number, enabled: boolean) =>
  enabled ? Math.round(v3d) * 10 : v3d * 10

// --- Custom Hooks ---

function useThemeColors() {
  const [colors, setColors] = useState({
    background: '#000000',
    primary: '#3b82f6',
    border: '#333333',
    card: '#222222',
    wall: '#555555',
    rackBody: '#1e293b',
    grid: '#333333',
    text: '#ffffff',
  })

  useEffect(() => {
    let timeout: NodeJS.Timeout
    const update = () => {
      clearTimeout(timeout)
      timeout = setTimeout(() => {
        const style = getComputedStyle(document.documentElement)
        const getHex = (varName: string, fallback: string) => {
          const color = style.getPropertyValue(varName).trim()
          return color ? formatHex(color) || fallback : fallback
        }
        setColors({
          background: getHex('--background', '#000000'),
          primary: getHex('--primary', '#3b82f6'),
          border: getHex('--border', '#333333'),
          card: getHex('--card', '#1a1a1a'),
          wall: getHex('--muted-foreground', '#666666'),
          rackBody: '#1e293b',
          grid: getHex('--border', '#333333'),
          text: getHex('--foreground', '#ffffff'),
        })
      }, 100)
    }

    update()
    const observer = new MutationObserver(update)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    })
    return () => {
      observer.disconnect()
      clearTimeout(timeout)
    }
  }, [])

  return colors
}

function useLabHistory(
  initEquipment: (eq: Array<Equipment>) => void,
  getEquipmentArray: () => Array<Equipment>,
  setWalls: React.Dispatch<React.SetStateAction<Array<Wall>>>,
  setLabels: React.Dispatch<React.SetStateAction<Array<LabLabel>>>,
) {
  interface HistoryState {
    equipment: Array<Equipment>
    walls: Array<Wall>
    labels: Array<LabLabel>
  }

  const [history, setHistory] = useState<Array<HistoryState>>([])
  const [historyIndex, setHistoryIndex] = useState(-1)

  const saveToHistory = useCallback(
    (currentWalls: Array<Wall>, currentLabels: Array<LabLabel>) => {
      setHistory((prev) => {
        const newHistory = prev.slice(0, Math.max(0, historyIndex + 1))
        newHistory.push({
          equipment: [...getEquipmentArray()],
          walls: [...currentWalls],
          labels: [...currentLabels],
        })
        return newHistory.slice(-25)
      })
      setHistoryIndex((prev) => Math.min(prev + 1, 24))
    },
    [getEquipmentArray, historyIndex],
  )

  const undo = useCallback(
    (currentWalls: Array<Wall>, currentLabels: Array<LabLabel>) => {
      if (historyIndex >= 0) {
        let currentHistory = history
        if (historyIndex === history.length - 1 && history.length < 25) {
          currentHistory = [
            ...history,
            {
              equipment: getEquipmentArray(),
              walls: currentWalls,
              labels: currentLabels,
            },
          ]
          setHistory(currentHistory)
        }
        const prev = currentHistory[historyIndex]
        initEquipment(prev.equipment)
        setWalls(prev.walls)
        setLabels(prev.labels)
        setHistoryIndex(historyIndex - 1)
      }
    },
    [
      history,
      historyIndex,
      getEquipmentArray,
      initEquipment,
      setWalls,
      setLabels,
    ],
  )

  const redo = useCallback(() => {
    const nextIdx = historyIndex + 1
    if (nextIdx < history.length - 1) {
      const next = history[nextIdx + 1]
      initEquipment(next.equipment)
      setWalls(next.walls)
      setLabels(next.labels)
      setHistoryIndex(nextIdx)
    }
  }, [history, historyIndex, initEquipment, setWalls, setLabels])

  return { history, historyIndex, saveToHistory, undo, redo }
}

function useBoxSelection(
  mode: EditMode,
  walls: Array<Wall>,
  setSelectedIds: React.Dispatch<React.SetStateAction<Array<string>>>,
) {
  const [selectStart, setSelectStart] = useState<THREE.Vector3 | null>(null)
  const [selectEnd, setSelectEnd] = useState<THREE.Vector3 | null>(null)

  const handlePointerDown = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      if (mode === 'select') {
        e.stopPropagation()
        setSelectStart(e.point.clone())
        setSelectEnd(e.point.clone())
      }
    },
    [mode],
  )

  const handlePointerMove = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      if (mode === 'select' && selectStart) {
        e.stopPropagation()
        setSelectEnd(e.point.clone())
      }
    },
    [mode, selectStart],
  )

  const handlePointerUp = useCallback(
    (e: ThreeEvent<PointerEvent>) => {
      if (mode === 'select' && selectStart && selectEnd) {
        e.stopPropagation()
        const minX = Math.min(selectStart.x, selectEnd.x)
        const maxX = Math.max(selectStart.x, selectEnd.x)
        const minZ = Math.min(selectStart.z, selectEnd.z)
        const maxZ = Math.max(selectStart.z, selectEnd.z)

        const eqArray = useLabStore.getState().getEquipmentArray()
        const selectedRacks = eqArray
          .filter((eq) => {
            const ex = eq.x / 10
            const ez = eq.y / 10
            return ex >= minX && ex <= maxX && ez >= minZ && ez <= maxZ
          })
          .map((eq) => eq.id)

        const selectedWalls = walls
          .filter((w) => {
            const cx = (w.x1 + w.x2) / 20
            const cz = (w.y1 + w.y2) / 20
            return cx >= minX && cx <= maxX && cz >= minZ && cz <= maxZ
          })
          .map((w) => w.id)

        setSelectedIds((prev) => {
          if (e.shiftKey)
            return Array.from(
              new Set([...prev, ...selectedRacks, ...selectedWalls]),
            )
          return [...selectedRacks, ...selectedWalls]
        })
        setSelectStart(null)
        setSelectEnd(null)
      }
    },
    [mode, selectStart, selectEnd, walls, setSelectedIds],
  )

  return {
    selectStart,
    selectEnd,
    setSelectStart,
    setSelectEnd,
    handlePointerDown,
    handlePointerMove,
    handlePointerUp,
  }
}

// --- Sub-components ---

function GhostPreview({
  mode,
  wallStart,
}: {
  mode: EditMode
  wallStart: THREE.Vector3 | null
}) {
  const meshRef = useRef<THREE.Group>(null)
  const wallMeshRef = useRef<THREE.Mesh>(null)
  const { mouse, camera } = useThree()
  const plane = useMemo(
    () => new THREE.Plane(new THREE.Vector3(0, 1, 0), 0),
    [],
  )
  const raycaster = useMemo(() => new THREE.Raycaster(), [])
  const point = useMemo(() => new THREE.Vector3(), [])

  useFrame(() => {
    if (!meshRef.current || (mode !== 'add-rack' && mode !== 'add-wall')) return
    raycaster.setFromCamera(mouse, camera)
    raycaster.ray.intersectPlane(plane, point)
    const snappedX = Math.round(point.x)
    const snappedZ = Math.round(point.z)
    meshRef.current.position.set(snappedX, 0, snappedZ)

    if (mode === 'add-wall' && wallStart && wallMeshRef.current) {
      const dist = wallStart.distanceTo(
        new THREE.Vector3(snappedX, 0, snappedZ),
      )
      const angle = Math.atan2(snappedZ - wallStart.z, snappedX - wallStart.x)
      wallMeshRef.current.scale.set(dist || 0.1, 1, 1)
      wallMeshRef.current.position.set(
        (wallStart.x + snappedX) / 2,
        WALL_H / 2,
        (wallStart.z + snappedZ) / 2,
      )
      meshRef.current.rotation.y = -angle
    } else {
      meshRef.current.rotation.y = 0
    }
  })

  return (
    <group ref={meshRef}>
      {mode === 'add-rack' && (
        <mesh position={[0, RACK_SIZE.h / 2, 0]}>
          <boxGeometry args={[RACK_SIZE.w, RACK_SIZE.h, RACK_SIZE.d]} />
          <meshStandardMaterial color="#3b82f6" transparent opacity={0.3} />
        </mesh>
      )}
      {mode === 'add-wall' && wallStart && (
        <mesh ref={wallMeshRef} geometry={wallGeometryBase}>
          <meshStandardMaterial color="#3b82f6" transparent opacity={0.3} />
        </mesh>
      )}
    </group>
  )
}

function SceneController({
  is2D,
  activeCamera,
  center,
  enabled,
  controlsRef,
}: {
  is2D: boolean
  activeCamera: string
  center?: THREE.Vector3
  enabled: boolean
  controlsRef: React.RefObject<MapControlsImpl | null>
}) {
  const { camera, invalidate } = useThree()
  const [, getKeys] = useKeyboardControls()
  const initialized = useRef(false)
  const prevIs2D = useRef(is2D)

  useEffect(() => {
    if (!controlsRef.current || !center) return

    if (!initialized.current) {
      if (is2D) camera.position.set(center.x, 600, center.z)
      else camera.position.set(center.x + 150, 200, center.z + 150)
      controlsRef.current.target.copy(center)
      camera.lookAt(center)
      controlsRef.current.update()
      initialized.current = true
      return
    }

    if (prevIs2D.current !== is2D) {
      const target = controlsRef.current.target
      if (is2D) camera.position.set(target.x, 600, target.z)
      else camera.position.set(target.x + 150, 200, target.z + 150)
      controlsRef.current.update()
      prevIs2D.current = is2D
      invalidate()
    }
  }, [is2D, camera, invalidate, center, controlsRef])

  const direction = useMemo(() => new THREE.Vector3(), [])
  const rightVec = useMemo(() => new THREE.Vector3(), [])

  useFrame((_, delta) => {
    if (!enabled || !controlsRef.current) return
    const { forward, back, left, right, rotateLeft, rotateRight } = getKeys()

    if ((rotateLeft || rotateRight) && !is2D) {
      const angle = (rotateLeft ? 1 : -1) * 2 * delta
      const offset = new THREE.Vector3()
        .copy(camera.position)
        .sub(controlsRef.current.target)
      offset.applyAxisAngle(new THREE.Vector3(0, 1, 0), angle)
      camera.position.copy(controlsRef.current.target).add(offset)
      controlsRef.current.update()
      invalidate()
    }

    if (forward || back || left || right) {
      const speed = 400 * delta
      const move = new THREE.Vector3()

      camera.getWorldDirection(direction)
      direction.y = 0
      direction.normalize()
      rightVec.crossVectors(direction, camera.up).normalize()

      if (forward) move.addScaledVector(direction, speed)
      if (back) move.addScaledVector(direction, -speed)
      if (left) move.addScaledVector(rightVec, -speed)
      if (right) move.addScaledVector(rightVec, speed)

      if (move.lengthSq() > 0) {
        camera.position.add(move)
        controlsRef.current.target.add(move)
        controlsRef.current.update()
        invalidate()
      }
    }
  })

  return (
    <MapControls
      ref={controlsRef}
      makeDefault
      enabled={enabled}
      screenSpacePanning={activeCamera === 'orthographic'}
      enableRotate={!is2D}
      maxPolarAngle={is2D ? 0 : Math.PI / 2.1}
      minPolarAngle={0}
    />
  )
}

function Rack({
  id,
  colors,
  mode,
  onSelect,
  viewOverlay,
  isSelected,
  dragDeltaRef,
  dragDeltaRotRef,
  groupCenter,
  saveToHistory,
}: {
  id: string
  colors: any
  mode: EditMode
  onSelect: (id: string, shift: boolean) => void
  viewOverlay: string
  isSelected: boolean
  dragDeltaRef: React.MutableRefObject<THREE.Vector3>
  dragDeltaRotRef: React.MutableRefObject<number>
  groupCenter: THREE.Vector3 | null
  saveToHistory: () => void
}) {
  const data = useLabStore((state) => state.equipment[id])
  const deleteMultipleEquipment = useLabStore(
    (state) => state.deleteMultipleEquipment,
  )

  const groupRef = useRef<THREE.Group>(null)
  const textGroupRef = useRef<THREE.Group>(null)
  const isDel = mode === 'delete'

  const rackRotation = (data as any)?.rotation || 0
  const vOffset = useMemo(() => new THREE.Vector3(), [])
  const yAxis = useMemo(() => new THREE.Vector3(0, 1, 0), [])

  useFrame((state) => {
    if (groupRef.current && data) {
      if (
        isSelected &&
        groupCenter &&
        (dragDeltaRef.current.lengthSq() > 0 || dragDeltaRotRef.current !== 0)
      ) {
        vOffset.set(data.x / 10 - groupCenter.x, 0, data.y / 10 - groupCenter.z)
        vOffset.applyAxisAngle(yAxis, dragDeltaRotRef.current)

        groupRef.current.position.set(
          groupCenter.x + vOffset.x + dragDeltaRef.current.x,
          RACK_SIZE.h / 2,
          groupCenter.z + vOffset.z + dragDeltaRef.current.z,
        )
        groupRef.current.rotation.set(
          0,
          rackRotation + dragDeltaRotRef.current,
          0,
        )
      } else {
        groupRef.current.position.set(data.x / 10, RACK_SIZE.h / 2, data.y / 10)
        groupRef.current.rotation.set(0, rackRotation, 0)
      }
    }

    if (textGroupRef.current && groupRef.current) {
      if (state.camera.type === 'OrthographicCamera')
        textGroupRef.current.visible = state.camera.zoom > 1
      else
        textGroupRef.current.visible =
          state.camera.position.distanceTo(groupRef.current.position) < 2500
    }
  })

  const rackColor = useMemo(() => {
    if (!data) return colors.rackBody
    const match = data.id.match(/R(\d+)-C(\d+)/)
    const r = match ? parseInt(match[1], 10) : 0
    const c = match ? parseInt(match[2], 10) : 0
    if (viewOverlay === 'heatmap')
      return `hsl(10, 100%, ${r % 2 === 0 ? 40 : 70}%)`
    if (viewOverlay === 'network')
      return `hsl(210, 100%, ${c % 2 === 0 ? 40 : 70}%)`
    return colors.rackBody
  }, [viewOverlay, data?.id, colors.rackBody])

  const handleClick = useCallback(
    (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation()
      if (mode === 'select') return

      if (mode === 'move' || mode === 'rotate') {
        if (!isSelected) onSelect(id, e.shiftKey)
      } else if (isDel) {
        saveToHistory()
        deleteMultipleEquipment([id])
      } else if (mode === 'view') {
        onSelect(id, e.shiftKey)
      }
    },
    [
      mode,
      isDel,
      id,
      deleteMultipleEquipment,
      onSelect,
      saveToHistory,
      isSelected,
    ],
  )

  if (!data) return null
  const renderAsRealMesh = isSelected

  return (
    <group
      ref={groupRef}
      userData={{ id: data.id }}
      position={[data.x / 10, RACK_SIZE.h / 2, data.y / 10]}
      rotation={[0, rackRotation, 0]}
    >
      {isSelected && (
        <mesh scale={[1.05, 1.01, 1.05]} geometry={glowGeometryBase}>
          <meshBasicMaterial color={colors.primary} transparent opacity={0.3} />
        </mesh>
      )}

      {renderAsRealMesh ? (
        <RoundedBox
          args={[RACK_SIZE.w, RACK_SIZE.h, RACK_SIZE.d]}
          radius={0.2}
          castShadow
          onClick={handleClick}
        >
          <meshStandardMaterial
            color={isDel ? '#ef4444' : rackColor}
            metalness={0.9}
            roughness={0.5}
            emissive={viewOverlay !== 'none' ? rackColor : '#000'}
            emissiveIntensity={viewOverlay !== 'none' ? 0.6 : 0}
          />
        </RoundedBox>
      ) : (
        <Instance color={isDel ? '#ef4444' : rackColor} onClick={handleClick} />
      )}

      <mesh
        position={[0, 0, RACK_SIZE.d / 2 + 0.1]}
        geometry={glassGeometryBase}
        material={glassMaterialBase}
      />

      <group ref={textGroupRef}>
        <Billboard position={[0, RACK_SIZE.h / 2 + 4, 0]}>
          <mesh>
            <planeGeometry args={[data.id.length * 1.2 + 2, 4]} />
            <meshBasicMaterial
              color="#000000"
              transparent
              opacity={0.6}
              depthTest={false}
            />
          </mesh>
          <Text
            fontSize={2}
            color={colors.text}
            fontWeight="bold"
            anchorX="center"
            anchorY="middle"
            renderOrder={100}
          >
            {data.id}
          </Text>
        </Billboard>
      </group>
    </group>
  )
}

function WallInstance({
  data,
  colors,
  mode,
  isSelected,
  dragDeltaRef,
  dragDeltaRotRef,
  groupCenter,
  onSelect,
  onDelete,
}: {
  data: Wall
  colors: any
  mode: EditMode
  isSelected: boolean
  dragDeltaRef: React.MutableRefObject<THREE.Vector3>
  dragDeltaRotRef: React.MutableRefObject<number>
  groupCenter: THREE.Vector3 | null
  onSelect: (id: string, shift: boolean) => void
  onDelete: () => void
}) {
  const groupRef = useRef<THREE.Group>(null)
  const p1 = useMemo(() => new THREE.Vector3(), [])
  const p2 = useMemo(() => new THREE.Vector3(), [])
  const yAxis = useMemo(() => new THREE.Vector3(0, 1, 0), [])

  useFrame(() => {
    if (
      groupRef.current &&
      isSelected &&
      groupCenter &&
      (dragDeltaRef.current.lengthSq() > 0 || dragDeltaRotRef.current !== 0)
    ) {
      p1.set(
        data.x1 / 10 - groupCenter.x,
        0,
        data.y1 / 10 - groupCenter.z,
      ).applyAxisAngle(yAxis, dragDeltaRotRef.current)
      const nx1 = groupCenter.x + p1.x + dragDeltaRef.current.x
      const nz1 = groupCenter.z + p1.z + dragDeltaRef.current.z

      p2.set(
        data.x2 / 10 - groupCenter.x,
        0,
        data.y2 / 10 - groupCenter.z,
      ).applyAxisAngle(yAxis, dragDeltaRotRef.current)
      const nx2 = groupCenter.x + p2.x + dragDeltaRef.current.x
      const nz2 = groupCenter.z + p2.z + dragDeltaRef.current.z

      const len = Math.sqrt((nx2 - nx1) ** 2 + (nz2 - nz1) ** 2)
      const ang = Math.atan2(nz2 - nz1, nx2 - nx1)

      groupRef.current.position.set(
        (nx1 + nx2) / 2,
        WALL_H / 2,
        (nz1 + nz2) / 2,
      )
      groupRef.current.rotation.set(0, -ang, 0)
      groupRef.current.scale.set(len, 1, 1)
    } else if (groupRef.current) {
      const x1 = data.x1 / 10,
        z1 = data.y1 / 10
      const x2 = data.x2 / 10,
        z2 = data.y2 / 10
      const len = Math.sqrt((x2 - x1) ** 2 + (z2 - z1) ** 2)
      const ang = Math.atan2(z2 - z1, x2 - x1)

      groupRef.current.position.set((x1 + x2) / 2, WALL_H / 2, (z1 + z2) / 2)
      groupRef.current.rotation.set(0, -ang, 0)
      groupRef.current.scale.set(len, 1, 1)
    }
  })

  return (
    <group
      ref={groupRef}
      onClick={(e) => {
        e.stopPropagation()
        if (mode === 'select') return
        if (mode === 'delete') onDelete()
        else if (mode === 'move' || mode === 'rotate' || mode === 'view') {
          if (!isSelected || mode === 'view') onSelect(data.id, e.shiftKey)
        }
      }}
    >
      <mesh castShadow geometry={wallGeometryBase}>
        <meshStandardMaterial
          color={
            mode === 'delete'
              ? '#ef4444'
              : isSelected
                ? colors.primary
                : colors.wall
          }
          transparent
          opacity={isSelected ? 0.9 : 0.7}
        />
      </mesh>
    </group>
  )
}

// --- Main Application Component ---

export function CanvasComponent3D({
  equipment: initialEquipment,
  walls: initialWalls,
  initialSelectedId,
}: any) {
  const initEquipment = useLabStore((state) => state.initEquipment)
  const getEquipmentArray = useLabStore((state) => state.getEquipmentArray)
  const addEquipment = useLabStore((state) => state.addEquipment)
  const updateMultipleEquipment = useLabStore(
    (state) => state.updateMultipleEquipment,
  )
  const deleteMultipleEquipment = useLabStore(
    (state) => state.deleteMultipleEquipment,
  )
  const addWall = useLabStore((state) => state.addWall)
  const updateMultipleWalls = useLabStore((state) => state.updateMultipleWalls)
  const deleteMultipleWalls = useLabStore((state) => state.deleteMultipleWalls)
  const hasUnsavedChanges = useLabStore((state) => state.hasUnsavedChanges)
  const markSaved = useLabStore((state) => state.markSaved)
  const equipmentIds = useLabStore(
    useShallow((state) => Object.keys(state.equipment)),
  )

  const initStore = useRef(false)
  useEffect(() => {
    if (!initStore.current) {
      initEquipment(initialEquipment)
      initStore.current = true
    }
  }, [initialEquipment, initEquipment])

  const [selectedIds, setSelectedIds] = useState<Array<string>>(
    initialSelectedId ? [initialSelectedId] : [],
  )
  const [is2D, setIs2D] = useState(false)
  const [projection, setProjection] = useState<'perspective' | 'orthographic'>(
    'perspective',
  )
  const [walls, setWalls] = useState<Array<Wall>>(initialWalls)
  const [labels, setLabels] = useState<Array<LabLabel>>([])
  const [mode, setMode] = useState<EditMode>('view')
  const [useSnap, setUseSnap] = useState(true)
  const [viewOverlay, setViewOverlay] = useState<
    'none' | 'heatmap' | 'network'
  >('none')
  const [wallStart, setWallStart] = useState<THREE.Vector3 | null>(null)

  const colors = useThemeColors()
  const navigate = useNavigate()
  const activeCamera = is2D ? 'orthographic' : projection

  const { historyIndex, history, saveToHistory, undo, redo } = useLabHistory(
    initEquipment,
    getEquipmentArray,
    setWalls,
    setLabels,
  )
  const {
    selectStart,
    selectEnd,
    setSelectStart,
    setSelectEnd,
    handlePointerDown,
    handlePointerMove,
    handlePointerUp,
  } = useBoxSelection(mode, walls, setSelectedIds)

  const mapControlsRef = useRef<MapControlsImpl>(null)
  const transformRef = useRef<TransformControlsImpl>(null)
  const [dummyObj, setDummyObj] = useState<THREE.Group | null>(null)

  const dragStartPos = useRef<THREE.Vector3 | null>(null)
  const dragDeltaRef = useRef(new THREE.Vector3())
  const dragStartRot = useRef(0)
  const dragDeltaRotRef = useRef(0)
  const [dragDropCount, setDragDropCount] = useState(0)

  useEffect(() => {
    if (selectedIds.length === 0 || (mode !== 'move' && mode !== 'rotate')) {
      dragStartPos.current = null
      dragDeltaRef.current.set(0, 0, 0)
      dragDeltaRotRef.current = 0
    }
  }, [selectedIds, mode])

  const selectedEquipmentData = useLabStore(
    useShallow((state) =>
      selectedIds
        .filter((id) => !id.startsWith('WALL'))
        .map((id) => state.equipment[id])
        .filter(Boolean),
    ),
  )

  const groupCenter = useMemo(() => {
    if (selectedIds.length === 0) return null
    let x = 0,
      y = 0,
      count = 0

    selectedEquipmentData.forEach((e) => {
      x += e.x
      y += e.y
      count++
    })
    walls
      .filter((w) => selectedIds.includes(w.id))
      .forEach((w) => {
        x += (w.x1 + w.x2) / 2
        y += (w.y1 + w.y2) / 2
        count++
      })

    if (count === 0) return null
    return new THREE.Vector3(x / count / 10, RACK_SIZE.h / 2, y / count / 10)
  }, [selectedIds, dragDropCount, walls, selectedEquipmentData])

  const handleDragEnd = useCallback(() => {
    if (!dragStartPos.current) return
    saveToHistory(walls, labels)

    const dx = dragDeltaRef.current.x
    const dz = dragDeltaRef.current.z
    const angle = dragDeltaRotRef.current
    const cx = groupCenter?.x || 0
    const cz = groupCenter?.z || 0

    const yAxis = new THREE.Vector3(0, 1, 0)
    const tempOffset = new THREE.Vector3()

    const eqUpdates = selectedEquipmentData.map((obj) => {
      tempOffset.set(obj.x / 10 - cx, 0, obj.y / 10 - cz)
      tempOffset.applyAxisAngle(yAxis, angle)

      return {
        id: obj.id,
        updates: {
          x: snapToData(cx + tempOffset.x + dx, useSnap),
          y: snapToData(cz + tempOffset.z + dz, useSnap),
          rotation: (((obj as any).rotation || 0) + angle) % (Math.PI * 2),
        },
      }
    })
    if (eqUpdates.length > 0) updateMultipleEquipment(eqUpdates)

    const wallIdsToUpdate = selectedIds.filter((id) => id.startsWith('WALL'))
    if (wallIdsToUpdate.length > 0) {
      const storeUpdates: Array<{ id: string; updates: Partial<Wall> }> = []
      setWalls((prev) =>
        prev.map((w) => {
          if (!wallIdsToUpdate.includes(w.id)) return w
          const p1 = new THREE.Vector3(
            w.x1 / 10 - cx,
            0,
            w.y1 / 10 - cz,
          ).applyAxisAngle(yAxis, angle)
          const p2 = new THREE.Vector3(
            w.x2 / 10 - cx,
            0,
            w.y2 / 10 - cz,
          ).applyAxisAngle(yAxis, angle)

          const updates = {
            x1: snapToData(cx + p1.x + dx + 100, useSnap),
            y1: snapToData(cz + p1.z + dz + 100, useSnap),
            x2: snapToData(cx + p2.x + dx, useSnap),
            y2: snapToData(cz + p2.z + dz, useSnap),
          }
          storeUpdates.push({ id: w.id, updates })
          return { ...w, ...updates }
        }),
      )
      updateMultipleWalls(storeUpdates)
    }

    dragStartPos.current = null
    dragDeltaRef.current.set(0, 0, 0)
    dragDeltaRotRef.current = 0
    setDragDropCount((c) => c + 1)
  }, [
    groupCenter,
    selectedEquipmentData,
    selectedIds,
    useSnap,
    saveToHistory,
    updateMultipleEquipment,
    updateMultipleWalls,
    walls,
    labels,
  ])

  useEffect(() => {
    const controls = transformRef.current
    if (controls && dummyObj) {
      const onDragChange = (e: any) => {
        if (mapControlsRef.current) mapControlsRef.current.enabled = !e.value
        if (e.value) {
          dragStartPos.current = dummyObj.position.clone()
          dragStartRot.current = dummyObj.rotation.y
        } else {
          handleDragEnd()
        }
      }
      const eventDispatcher = controls as any
      eventDispatcher.addEventListener('dragging-changed', onDragChange)
      return () =>
        eventDispatcher.removeEventListener('dragging-changed', onDragChange)
    }
  }, [dummyObj, handleDragEnd])

  useEffect(() => {
    if (mode === 'add-rack' || mode === 'add-wall' || mode === 'add-label')
      setSelectedIds([])
    setSelectStart(null)
    setSelectEnd(null)
  }, [mode, setSelectStart, setSelectEnd])

  const handleSelect = useCallback(
    (id: string | null, shiftKey: boolean = false) => {
      if (!id) {
        setSelectedIds([])
        return
      }
      setSelectedIds((prev) =>
        shiftKey
          ? prev.includes(id)
            ? prev.filter((i) => i !== id)
            : [...prev, id]
          : [id],
      )

      if (!shiftKey && mode === 'view' && !id.startsWith('WALL')) {
        navigate({
          to: '/map',
          search: (prev: any) => ({
            ...prev,
            redirectId: id ?? undefined,
            redirectType: 'rack',
          }),
          replace: true,
        })
      }
    },
    [navigate, mode],
  )

  const handleGridClick = (e: ThreeEvent<MouseEvent>) => {
    if (mode === 'select' || mode === 'move' || mode === 'rotate') return
    if (mode === 'view') {
      setSelectedIds([])
      navigate({
        to: '/map',
        search: (prev: any) => ({
          ...prev,
          redirectId: undefined,
          redirectType: undefined,
        }),
        replace: true,
      })
      return
    }

    e.stopPropagation()
    const pt = new THREE.Vector3(
      Math.round(e.point.x),
      0,
      Math.round(e.point.z),
    )
    saveToHistory(walls, labels)

    if (mode === 'add-rack') {
      addEquipment({
        id: `RACK-${Date.now()}`,
        x: pt.x * 10,
        y: pt.z * 10,
        rotation: 0,
        type: 'rack',
        label: 'New',
      } as any)
      setMode('view')
    } else if (mode === 'add-wall') {
      if (!wallStart) setWallStart(pt)
      else {
        const newWall = {
          id: `WALL-${Date.now()}`,
          x1: wallStart.x * 10,
          y1: wallStart.z * 10,
          x2: pt.x * 10,
          y2: pt.z * 10,
        }
        setWalls([...walls, newWall])
        addWall(newWall)
        setWallStart(null)
        setMode('view')
      }
    } else if (mode === 'add-label') {
      const text = prompt('Label Text:', 'Zone A')
      if (text)
        setLabels([
          ...labels,
          { id: `L-${Date.now()}`, text, x: pt.x, y: pt.z },
        ])
      setMode('view')
    }
  }

  const sceneCenter = useMemo(() => {
    const eqArray = getEquipmentArray()
    if (!eqArray.length) return new THREE.Vector3(0, 0, 0)
    const avgX = eqArray.reduce((acc, e) => acc + e.x, 0) / eqArray.length
    const avgY = eqArray.reduce((acc, e) => acc + e.y, 0) / eqArray.length
    return new THREE.Vector3(avgX / 10, 0, avgY / 10)
  }, [equipmentIds.length, getEquipmentArray])

  const handleSaveToBackend = () => setTimeout(() => markSaved(), 500)

  const deleteSelection = () => {
    saveToHistory(walls, labels)
    const wallIds = selectedIds.filter((id) => id.startsWith('WALL'))
    const eqIds = selectedIds.filter((id) => !id.startsWith('WALL'))
    deleteMultipleEquipment(eqIds)
    deleteMultipleWalls(wallIds)
    setWalls((prev) => prev.filter((w) => !selectedIds.includes(w.id)))
    setSelectedIds([])
  }

  return (
    <div
      className="relative w-full h-full bg-background flex min-w-0 overflow-hidden outline-none"
      tabIndex={0}
      onMouseDown={(e) => e.currentTarget.focus()}
    >
      <div className="absolute top-4 left-4 z-20 flex flex-col gap-4">
        <ViewSettings
          canUndo={historyIndex >= 0}
          canRedo={historyIndex < history.length - 1}
          onUndo={() => undo(walls, labels)}
          onRedo={redo}
          viewOverlay={viewOverlay}
          setViewOverlay={setViewOverlay}
          useSnap={useSnap}
          setUseSnap={setUseSnap}
          is2D={is2D}
          setIs2D={setIs2D}
          projection={projection}
          setProjection={setProjection}
        />
        <MapToolbar mode={mode} setMode={(v) => setMode(v as EditMode)} />
      </div>

      <div className="absolute top-4 right-4 z-20 flex gap-2">
        {hasUnsavedChanges && (
          <Button
            onClick={handleSaveToBackend}
            className="bg-emerald-600 hover:bg-emerald-700 text-white animate-in fade-in slide-in-from-top-4 shadow-lg"
          >
            <Save className="w-4 h-4 mr-2" /> Save Changes
          </Button>
        )}
      </div>

      {selectedIds.length > 0 && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 backdrop-blur-xl bg-card/90 p-2 rounded-xl border border-border/50 shadow-2xl animate-in slide-in-from-bottom-6">
          <div className="px-3 py-1 text-sm font-bold tracking-tight flex items-center border-r border-border/50 text-foreground">
            {selectedIds.length} Selected
          </div>
          <Button
            size="sm"
            variant="ghost"
            className="h-8"
            onClick={() => setSelectedIds([])}
          >
            <X className="w-4 h-4 mr-1" /> Clear
          </Button>
          <Button
            size="sm"
            variant="destructive"
            className="h-8"
            onClick={deleteSelection}
          >
            <Trash2 className="w-4 h-4 mr-1" /> Delete
          </Button>
        </div>
      )}

      <div className="flex-1 relative h-full min-w-0">
        <KeyboardControls
          map={[
            { name: 'forward', keys: ['ArrowUp', 'KeyW'] },
            { name: 'back', keys: ['ArrowDown', 'KeyS'] },
            { name: 'left', keys: ['ArrowLeft', 'KeyA'] },
            { name: 'right', keys: ['ArrowRight', 'KeyD'] },
            { name: 'rotateLeft', keys: ['KeyQ'] },
            { name: 'rotateRight', keys: ['KeyE'] },
          ]}
        >
          <Canvas
            shadows
            dpr={[1, 2]}
            gl={{ antialias: true, logarithmicDepthBuffer: true }}
          >
            <Suspense fallback={null}>
              <GizmoHelper alignment="bottom-right" margin={[80, 80]}>
                <GizmoViewport />
              </GizmoHelper>

              <PerspectiveCamera
                makeDefault={activeCamera === 'perspective'}
                position={[150, 200, 150]}
                fov={45}
                far={2000}
              />
              <OrthographicCamera
                makeDefault={activeCamera === 'orthographic'}
                position={[0, 600, 0]}
                zoom={is2D ? 15 : 6}
                near={-500}
                far={2000}
              />

              <SceneController
                is2D={is2D}
                activeCamera={activeCamera}
                center={mode === 'view' ? sceneCenter : undefined}
                enabled={mode !== 'select'}
                controlsRef={mapControlsRef}
              />

              <ambientLight intensity={1.8} />
              <pointLight
                position={[100, 200, 100]}
                castShadow
                intensity={3}
                shadow-bias={-0.0005}
                shadow-mapSize={1024}
              />
              <Environment preset="warehouse" />

              <mesh
                rotation={[-Math.PI / 2, 0, 0]}
                position={[0, -0.05, 0]}
                onClick={handleGridClick}
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
              >
                <planeGeometry args={[10000, 10000]} />
                <meshBasicMaterial transparent opacity={0} depthWrite={false} />
              </mesh>

              {mode === 'select' && selectStart && selectEnd && (
                <mesh
                  position={[
                    (selectStart.x + selectEnd.x) / 2,
                    0.5,
                    (selectStart.z + selectEnd.z) / 2,
                  ]}
                  rotation={[-Math.PI / 2, 0, 0]}
                >
                  <planeGeometry
                    args={[
                      Math.abs(selectStart.x - selectEnd.x) || 0.1,
                      Math.abs(selectStart.z - selectEnd.z) || 0.1,
                    ]}
                  />
                  <meshBasicMaterial
                    color={colors.primary}
                    transparent
                    opacity={0.3}
                    side={THREE.DoubleSide}
                  />
                </mesh>
              )}

              <Grid
                infiniteGrid
                cellSize={10}
                sectionSize={50}
                cellColor={colors.grid}
                sectionColor={colors.primary}
                fadeDistance={1500}
                fadeStrength={1}
                cellThickness={1}
                sectionThickness={2}
                position={[0, -0.01, 0]}
              />

              {selectedIds.length > 0 &&
                (mode === 'move' || mode === 'rotate') &&
                groupCenter && (
                  <group key={selectedIds.join('-') + dragDropCount}>
                    <group
                      ref={(node) =>
                        node && dummyObj !== node && setDummyObj(node)
                      }
                      position={groupCenter}
                    />
                    {dummyObj && dummyObj.parent && (
                      <TransformControls
                        ref={transformRef}
                        object={dummyObj}
                        mode={mode === 'rotate' ? 'rotate' : 'translate'}
                        showX={mode !== 'rotate'}
                        showZ={mode !== 'rotate'}
                        showY={mode === 'rotate'}
                        translationSnap={useSnap ? 1 : null}
                        rotationSnap={useSnap ? Math.PI / 4 : null}
                        onChange={() => {
                          if (dragStartPos.current) {
                            dragDeltaRef.current
                              .copy(dummyObj.position)
                              .sub(dragStartPos.current)
                            dragDeltaRotRef.current =
                              dummyObj.rotation.y - dragStartRot.current
                          }
                        }}
                      />
                    )}
                  </group>
                )}

              <Instances
                limit={5000}
                geometry={rackGeometryBase}
                castShadow
                receiveShadow
              >
                {viewOverlay === 'none' ? (
                  <meshStandardMaterial
                    metalness={0.9}
                    roughness={0.5}
                    color="#ffffff"
                  />
                ) : (
                  <meshBasicMaterial color="#ffffff" />
                )}
                {equipmentIds.map((id) => (
                  <Rack
                    key={id}
                    id={id}
                    colors={colors}
                    mode={mode}
                    viewOverlay={viewOverlay}
                    isSelected={selectedIds.includes(id)}
                    groupCenter={groupCenter}
                    dragDeltaRef={dragDeltaRef}
                    dragDeltaRotRef={dragDeltaRotRef}
                    onSelect={handleSelect}
                    saveToHistory={() => saveToHistory(walls, labels)}
                  />
                ))}
              </Instances>

              {walls.map((w: Wall) => (
                <WallInstance
                  key={w.id}
                  data={w}
                  colors={colors}
                  mode={mode}
                  isSelected={selectedIds.includes(w.id)}
                  groupCenter={groupCenter}
                  dragDeltaRef={dragDeltaRef}
                  dragDeltaRotRef={dragDeltaRotRef}
                  onSelect={handleSelect}
                  onDelete={() => {
                    saveToHistory(walls, labels)
                    setWalls((prev) => prev.filter((item) => item.id !== w.id))
                    deleteMultipleWalls([w.id])
                  }}
                />
              ))}

              {labels.map((l) => (
                <Billboard key={l.id} position={[l.x, 8, l.y]}>
                  <Text
                    fontSize={5}
                    color={colors.text}
                    fontWeight="bold"
                    fillOpacity={0.7}
                  >
                    {l.text}
                  </Text>
                </Billboard>
              ))}
              <GhostPreview mode={mode} wallStart={wallStart} />
              <ContactShadows
                opacity={0.4}
                scale={1000}
                blur={2.5}
                far={15}
                resolution={256}
                color="#000000"
              />
            </Suspense>
          </Canvas>
        </KeyboardControls>
        <ControlsOverlay is2D={is2D} />
        <Loader
          containerStyles={{ background: 'var(--background)' }}
          innerStyles={{ backgroundColor: 'var(--card)' }}
          barStyles={{ backgroundColor: 'var(--primary)' }}
        />
      </div>

      {selectedIds.length === 1 &&
        getEquipmentArray().find((e) => e.id === selectedIds[0]) &&
        mode === 'view' && (
          <RackInfoPanel
            rack={getEquipmentArray().find((e) => e.id === selectedIds[0])!}
            onClose={() => setSelectedIds([])}
          />
        )}
    </div>
  )
}
