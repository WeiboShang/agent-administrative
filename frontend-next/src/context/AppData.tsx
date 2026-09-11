import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, type Actor, type Options } from '@/lib/api'

type AppData = {
  options: Options | null
  actor: Actor | null
  setActor: (id: string) => void
  loading: boolean
  error: string | null
}

const Ctx = createContext<AppData | null>(null)

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<Options | null>(null)
  const [actor, setActorState] = useState<Actor | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .options()
      .then((o) => {
        setOptions(o)
        setActorState(o.actors[0] ?? null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  function setActor(id: string) {
    setActorState(options?.actors.find((a) => a.id === id) ?? null)
  }

  return <Ctx.Provider value={{ options, actor, setActor, loading, error }}>{children}</Ctx.Provider>
}

export function useAppData(): AppData {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAppData must be used within AppDataProvider')
  return v
}
