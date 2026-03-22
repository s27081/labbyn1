import {
  Brackets,
  ClipboardList,
  DoorOpen,
  FileText,
  Loader2,
  Search,
  Server,
  User,
  Users,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { SidebarMenuButton, SidebarMenuItem } from './ui/sidebar'
import { Button } from './ui/button'
import { Kbd, KbdGroup } from './ui/kbd'
import type { LucideIcon } from 'lucide-react'
import type { ApiSearchItem } from '@/integrations/search/search.types'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { searchListQueryOptions } from '@/integrations/search/search.query'

const categoryIcons: Record<string, LucideIcon> = {
  users: User,
  machines: Server,
  racks: Brackets,
  teams: Users,
  rooms: DoorOpen,
  inventory: ClipboardList,
  documentation: FileText,
}

export function CommandMenu() {
  const [open, setOpen] = useState(false)
  const [activeFilter, setActiveFilter] = useState<string | null>(null)
  const navigate = useNavigate()

  const { data, isLoading } = useQuery(searchListQueryOptions)

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        e.stopPropagation()
        setOpen((prev) => !prev)
      }
    }

    window.addEventListener('keydown', down)
    return () => window.removeEventListener('keydown', down)
  }, [])

  const runCommand = useCallback((command: () => unknown) => {
    setOpen(false)
    command()
  }, [])

  const availableCategories = useMemo(() => {
    if (!data) return []
    return Object.entries(data)
      .filter(([_, items]) => items.length > 0)
      .map(([key]) => key)
  }, [data])

  return (
    <>
      <SidebarMenuItem key={'search'}>
        <SidebarMenuButton asChild onClick={() => setOpen(true)}>
          <Button
            variant="outline"
            className="h-8 w-full justify-start pl-3 font-normal text-muted-foreground shadow-none hover:bg-accent hover:text-accent-foreground"
          >
            <Search />
            <span>Search resources...</span>
            <KbdGroup>
              <Kbd>Ctrl</Kbd>
              <span>+</span>
              <Kbd>k</Kbd>
            </KbdGroup>
          </Button>
        </SidebarMenuButton>
      </SidebarMenuItem>

      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput placeholder="Search users, docs, or devices (e.g. '10.1.1' or 'GPU')..." />

        {availableCategories.length > 0 && (
          <div className="flex items-center gap-2 overflow-x-auto border-b px-3 py-2 scrollbar-hide">
            <Button
              variant={activeFilter === null ? 'default' : 'secondary'}
              size="sm"
              className="h-7 rounded-full px-3 text-xs"
              onClick={() => setActiveFilter(null)}
            >
              All
            </Button>
            {availableCategories.map((cat) => {
              const Icon = categoryIcons[cat]
              return (
                <Button
                  key={cat}
                  variant={activeFilter === cat ? 'default' : 'secondary'}
                  size="sm"
                  className="h-7 rounded-full px-3 text-xs capitalize"
                  onClick={() =>
                    setActiveFilter(activeFilter === cat ? null : cat)
                  }
                >
                  <Icon className="mr-1.5 h-3 w-3" />
                  {cat}
                </Button>
              )
            })}
          </div>
        )}

        <CommandList>
          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading index...
            </div>
          ) : (
            <>
              <CommandEmpty className="py-8 text-center text-sm">
                No results found.
              </CommandEmpty>

              {data &&
                Object.entries(data).map(([categoryName, items]) => {
                  if (items.length === 0) return null
                  if (activeFilter && activeFilter !== categoryName) return null

                  const heading =
                    categoryName.charAt(0).toUpperCase() + categoryName.slice(1)
                  const IconComponent = categoryIcons[categoryName]

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
                          className="group my-0.5"
                        >
                          <div className="flex w-full items-center gap-3">
                            <IconComponent className="h-4 w-4 shrink-0 text-muted-foreground group-aria-selected:text-primary" />

                            <div className="flex flex-1 flex-col overflow-hidden">
                              <span className="truncate text-sm font-medium">
                                {item.label}
                              </span>
                              <span className="truncate text-xs text-muted-foreground group-aria-selected:text-foreground">
                                {item.sublabel}
                              </span>
                            </div>

                            <span className="shrink-0 rounded bg-muted/50 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
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
