import useWebSocket, { ReadyState } from 'react-use-websocket'
import { useEffect } from 'react'
import { Activity, Cpu, MemoryStick, Server } from 'lucide-react'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

interface PlatformWebsocketProps {
  instance?: string
}

interface MetricsPayload {
  instance: string
  online: boolean
  cpu: number | null
  memory: number | null
  disks: Array<{ value: number; timestamp: number }>
}

export function PlatformWebsocket({ instance }: PlatformWebsocketProps) {
  // TO DO: Move token retrieval from LocalStorage
  const token = localStorage.getItem('access_token')

  const WS_URL = `${import.meta.env.VITE_WS_URL}/metrics?token=${token}&instance=${instance}:9100`

  const { sendJsonMessage, lastJsonMessage, readyState } = useWebSocket(
    WS_URL.toString(),
    {
      share: false,
      shouldReconnect: () => true,
    },
  )

  useEffect(() => {
    if (readyState === ReadyState.OPEN) {
      sendJsonMessage({
        event: 'subscribe',
        data: {
          channel: 'general',
        },
      })
    }
  }, [readyState, sendJsonMessage])

  if (!lastJsonMessage) {
    return (
      <Card className="w-full">
        <CardContent className="flex items-center justify-center py-12">
          <div className="flex items-center gap-3 text-muted-foreground">
            <div className="h-4 w-4 rounded-full bg-primary/60 animate-pulse" />
            <span className="font-medium">
              Waiting for live metrics stream...
            </span>
          </div>
        </CardContent>
      </Card>
    )
  }

  const { online, cpu, memory } = lastJsonMessage as MetricsPayload
  return (
    <Card className="w-full">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-6">
        <div className="flex flex-col gap-1.5">
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-primary" />
            Live Telemetry
          </CardTitle>
          <CardDescription>Real-time resource utilization</CardDescription>
        </div>

        {/* Status Indicator */}
        <div
          className={`flex items-center gap-2 px-3 py-1 rounded-md text-sm font-bold border ${
            online
              ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20'
              : 'bg-destructive/10 text-destructive border-destructive/20'
          }`}
        >
          <div
            className={`h-2 w-2 rounded-full ${
              online ? 'bg-emerald-500 animate-pulse' : 'bg-destructive'
            }`}
          />
          {online ? 'ONLINE' : 'OFFLINE'}
        </div>
      </CardHeader>

      <CardContent>
        {/* Information Grid */}
        <div className="grid flex-1 gap-6 sm:grid-cols-3 bg-muted/30 p-6 rounded-lg border border-border/50">
          {[
            {
              label: 'Target Instance',
              value: instance,
              icon: Server,
            },
            {
              label: 'CPU Utilization',
              value: cpu !== null ? `${cpu.toFixed(2)} %` : 'N/A',
              icon: Cpu,
            },
            {
              label: 'Memory Allocation',
              value: memory !== null ? `${memory.toFixed(2)} %` : 'N/A',
              icon: MemoryStick,
            },
          ].map((field) => (
            <div key={field.label} className="grid gap-2">
              <span className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <field.icon className="h-4 w-4" /> {field.label}
              </span>
              <span className="text-2xl font-semibold md:break-all">
                {field.value}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
