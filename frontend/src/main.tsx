import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ToastProvider } from './components/ToastNotification'
import './index.css'

const container = document.getElementById('root')
if (!container) throw new Error('Root container is missing from index.html')

createRoot(container).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>,
)
