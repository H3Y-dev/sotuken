import { StrictMode, lazy, Suspense, useSyncExternalStore } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
const Comparison = lazy(() => import('./astryx/Comparison.tsx'))
const Gauge = lazy(() => import('./gauge/GaugeApp.tsx'))

const screen = (h: string) => (h.startsWith('#gauge') ? 'gauge' : h === '#astryx' ? 'astryx' : 'app')
const onHash = (f: () => void) => {
  addEventListener('hashchange', f)
  return () => removeEventListener('hashchange', f)
}

// 画面の切り替えは React の状態で行う（読み込み直さない）。
// CSS が混ざらないよう、計器盤の CSS は .gauge の中だけ、Astryx の CSS は表示中だけ差し込む。
function Root() {
  const current = screen(useSyncExternalStore(onHash, () => location.hash))
  return (
    <Suspense fallback={null}>
      {current === 'gauge' ? <Gauge /> : current === 'astryx' ? <Comparison /> : <App />}
    </Suspense>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
