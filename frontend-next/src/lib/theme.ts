export type Theme = 'light' | 'dark'
const KEY = 'wf-theme'

export function applyTheme(t: Theme) {
  document.documentElement.classList.toggle('dark', t === 'dark')
}

/** Read the saved theme (else the OS preference) and apply it. Call once at boot. */
export function initTheme(): Theme {
  const saved = localStorage.getItem(KEY) as Theme | null
  const t: Theme = saved ?? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  applyTheme(t)
  return t
}

export function saveTheme(t: Theme) {
  localStorage.setItem(KEY, t)
  applyTheme(t)
}
