import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
const Comparison = lazy(() => import('./astryx/Comparison.tsx'))
const Gauge = lazy(() => import('./gauge/GaugeApp.tsx'))

const screen = (h: string) => (h.startsWith('#gauge') ? 'gauge' : h === '#astryx' ? 'astryx' : 'app')
const current = screen(location.hash)
// 画面ごとにCSSが違うので、別の画面へ移るときは読み込み直して混ざらないようにする
addEventListener('hashchange', () => { if (screen(location.hash) !== current) location.reload() })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense fallback={null}>
      {current === 'gauge' ? <Gauge /> : current === 'astryx' ? <Comparison /> : <App />}
    </Suspense>
  </StrictMode>,
)
