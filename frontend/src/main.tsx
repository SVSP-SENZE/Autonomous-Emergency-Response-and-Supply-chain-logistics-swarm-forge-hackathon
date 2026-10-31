import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { ScenarioProvider } from './hooks/useScenario';
import { ToastProvider } from './components/common/Toast';
import './styles/index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <ScenarioProvider>
          <App />
        </ScenarioProvider>
      </ToastProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
