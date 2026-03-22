import axios from 'axios';

const BASE = import.meta.env.VITE_API_URL || '';

export const publicApi = {
  fetchStatusPage: (slug, signal) =>
    axios.get(`${BASE}/api/v1/public/status/${slug}`, { signal, timeout: 8000 }),
};
