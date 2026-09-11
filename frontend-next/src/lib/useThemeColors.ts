import { useEffect, useState } from 'react'

const TOKENS = ['--ink', '--ink-2', '--ink-3', '--line', '--surface', '--accent', '--warn'] as const
type Token = (typeof TOKENS)[number]
export type ThemeColors = Record<Token, string>

function read(): ThemeColors {
  const cs = getComputedStyle(document.documentElement)
  return Object.fromEntries(TOKENS.map((t) => [t, cs.getPropertyValue(t).trim()])) as ThemeColors
}

/**
 * Resolved token values for SVG chart props (Recharts sets fill/stroke as attributes, which
 * do not resolve `var()`), re-read whenever the theme class flips so charts follow the toggle.
 */
export function useThemeColors(): ThemeColors {
  const [colors, setColors] = useState<ThemeColors>(read)
  useEffect(() => {
    const obs = new MutationObserver(() => setColors(read()))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => obs.disconnect()
  }, [])
  return colors
}
