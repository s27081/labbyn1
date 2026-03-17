import { useState } from 'react'
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { SortableItem } from './sortable-item'
import type { ApiRackDetailMachineItem } from '@/integrations/racks/racks.types'
import type { DragEndEvent } from '@dnd-kit/core'

interface DndTableProps {
  dbItems: Array<Array<ApiRackDetailMachineItem>>
  onReorder: (newItems: Array<Array<ApiRackDetailMachineItem>>) => void
}

export function DndTable({ dbItems, onReorder }: DndTableProps) {
  const [shelves, setShelves] = useState(() =>
    dbItems.map((machines, index) => ({
      id: `shelf-${index}`,
      machines,
    })),
  )
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  )
  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext
        items={shelves.map((shelf) => shelf.id)}
        strategy={verticalListSortingStrategy}
      >
        {shelves.map((shelf) => (
          <SortableItem items={shelf.machines} id={shelf.id} key={shelf.id} />
        ))}
      </SortableContext>
    </DndContext>
  )

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    // we have a 2D array of machines representing shelfs
    if (!over || active.id === over.id) {
      return
    }
    const oldIndex = shelves.findIndex((shelf) => shelf.id === active.id)
    const newIndex = shelves.findIndex((shelf) => shelf.id === over.id)

    const result = arrayMove(shelves, oldIndex, newIndex)
    setShelves(result)
    onReorder(result.map((shelf) => shelf.machines))

    return result
  }
}
