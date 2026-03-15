import React from 'react';
import ReactDOM from 'react-dom/client';
import { datadogRum } from '@datadog/browser-rum';
import { datadogLogs } from '@datadog/browser-logs';
import './styles/main.css';
import './styles/tailwind.css';
import App from './App';

const APP_VERSION = import.meta.env.VITE_APP_VERSION || '0.2.2';

if (import.meta.env.VITE_DD_RUM_APPLICATION_ID && import.meta.env.VITE_DD_RUM_CLIENT_TOKEN) {
  datadogRum.init({
    applicationId: import.meta.env.VITE_DD_RUM_APPLICATION_ID,
    clientToken: import.meta.env.VITE_DD_RUM_CLIENT_TOKEN,
    site: 'datadoghq.com',
    service: 'circuit-breaker-frontend',
    env: 'production',
    version: APP_VERSION,
    sessionSampleRate: 100,
    sessionReplaySampleRate: 20,
    trackUserInteractions: true,
    trackResources: true,
    trackLongTasks: true,
    defaultPrivacyLevel: 'mask-user-input',
  });

  datadogLogs.init({
    clientToken: import.meta.env.VITE_DD_RUM_CLIENT_TOKEN,
    site: 'datadoghq.com',
    service: 'circuit-breaker-frontend',
    env: 'production',
    forwardErrorsToLogs: true,
    forwardConsoleLogs: ['error', 'warn'],
    sessionSampleRate: 100,
  });
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
