import client from './client';

export const authApi = {
  bootstrapStatus: () => client.get('/bootstrap/status'),
  bootstrapInitialize: (payload) => client.post('/bootstrap/initialize', payload),
  register: (email, password, displayName) => {
    const body = { email, password };
    if (displayName) body.display_name = displayName;
    return client.post('/auth/register', body);
  },
  login: (email, password) => client.post('/auth/login', { email, password }),
  me: () => client.get('/auth/me'),
  updateProfile: (formData, tokenOverride) => {
    const headers = { 'Content-Type': 'multipart/form-data' };
    if (tokenOverride) headers.Authorization = `Bearer ${tokenOverride}`;
    return client.put('/auth/me', formData, { headers });
  },
  logout: () => client.post('/auth/logout'),
};
