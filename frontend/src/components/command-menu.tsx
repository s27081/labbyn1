import {
  Activity,
  Brackets,
  ClipboardList,
  Database,
  DoorOpen,
  FileText,
  Loader2,
  Search,
  Server,
  User,
  Users,
} from 'lucide-react'
import React, { useMemo } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { SidebarMenuButton, SidebarMenuItem } from './ui/sidebar'
import { Button } from './ui/button'
import { Kbd, KbdGroup } from './ui/kbd'
import type { Device } from '@/types/types'
import type { ApiSearchItem } from '@/integrations/search/search.types'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { searchListQueryOptions } from '@/integrations/search/search.query'

const categoryIcons: Record<string, React.ElementType> = {
  users: User,
  machines: Server,
  racks: Brackets,
  teams: Users,
  rooms: DoorOpen,
  inventory: ClipboardList,
  documentation: FileText,
}

export function CommandMenu() {
  const [open, setOpen] = React.useState(false)
  const navigate = useNavigate()

  const { data, isLoading } = useQuery(searchListQueryOptions)

  React.useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        e.stopPropagation()
        setOpen((open) => !open)
      }
    }

    window.addEventListener('keydown', down)
    return () => window.removeEventListener('keydown', down)
  }, [])

  const runCommand = React.useCallback((command: () => unknown) => {
    setOpen(false)
    command()
  }, [])

  return (
    <>
      <SidebarMenuItem key={'search'}>
        <SidebarMenuButton asChild onClick={() => setOpen(true)}>
          <Button
            variant={'outline'}
            className="text-foreground dark:bg-card hover:bg-accent hover:border-primary relative h-8 w-full justify-start pl-3 font-normal shadow-none"
          >
            <Search />
            <span>Search resources...</span>
            <KbdGroup>
              <Kbd>Ctrl</Kbd>
              <span>+</span>
              <Kbd>K</Kbd>
            </KbdGroup>
          </Button>
        </SidebarMenuButton>
      </SidebarMenuItem>

      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput placeholder="Search users, docs, or devices (e.g. '10.1.1' or 'GPU')..." />
        <CommandList>
          {isLoading ? (
            <div className="py-6 text-center text-sm text-muted-foreground flex items-center justify-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading index...
            </div>
          ) : (
            <>
              <CommandEmpty>No results found.</CommandEmpty>

              {data &&
                Object.entries(data).map(([categoryName, items]) => {
                  // Skip rendering the group entirely if there are no items
                  if (!items || items.length === 0) return null

                  // Capitalize the category name for the heading ("machines" -> "Machines")
                  const heading =
                    categoryName.charAt(0).toUpperCase() + categoryName.slice(1)
                  const IconComponent = categoryIcons[categoryName] || FileText

                  return (
                    <CommandGroup key={categoryName} heading={heading}>
                      {items.map((item: ApiSearchItem) => (
                        <CommandItem
                          key={item.id}
                          value={`${item.id} ${item.label} ${item.sublabel}`}
                          onSelect={() =>
                            runCommand(() =>
                              navigate({ to: `${item.target_url}` }),
                            )
                          }
                        >
                          <div className="flex w-full items-center gap-3">
                            <IconComponent />

                            <div className="flex flex-1 flex-col">
                              <span className="text-sm font-medium leading-none mb-1">
                                {item.label}
                              </span>
                              <span className="text-xs text-muted-foreground line-clamp-1">
                                {item.sublabel}
                              </span>
                            </div>

                            <span className="text-[10px] font-mono text-muted-foreground bg-muted/50 px-1.5 py-0.5 rounded-sm shrink-0">
                              ID: {item.id}
                            </span>
                          </div>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  )
                })}
            </>
          )}
        </CommandList>
      </CommandDialog>
    </>
  )
}
