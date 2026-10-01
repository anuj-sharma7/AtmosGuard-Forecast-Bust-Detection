import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, HashRouter } from 'react-router-dom';

import App from './App';
import { isSnapshotMode } from './api/client';
import { AppStateProvider } from './state/AppState';
import './index.css';

// A static snapshot build has no server to rewrite unknown paths back to the
// SPA shell, and may not be served from a domain root at all - so it routes on
// the hash. Served by the FastAPI app, normal history routing applies.
const Router = isSnapshotMode() ? HashRouter : BrowserRouter;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Router>
      <AppStateProvider>
        <App />
      </AppStateProvider>
    </Router>
  </StrictMode>,
);
