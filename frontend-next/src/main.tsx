import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
// Inter, self-hosted through the Vite asset pipeline (same origin, no CDN, no data-URI bloat)
import '@fontsource-variable/inter'
import './index.css'
import App from './App.tsx'
import { initTheme } from './lib/theme.ts'
import { AppDataProvider } from './context/AppData.tsx'

initTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AppDataProvider>
        <App />
      </AppDataProvider>
    </BrowserRouter>
  </StrictMode>,
)
