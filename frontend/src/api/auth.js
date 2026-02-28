import client from './client';

export const authApi = {
  register: (email, password, displayName) => {
    const body = { email, password };
    if (displayName) body.display_name = displayName;
    return client.post('/auth/register', body);
  },
  login: (email, password) => client.post('/auth/login', { email, password }),
  me: () => client.get('/auth/me'),
  updateProfile: (formData) =>
    client.put('/auth/me', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  logout: () => client.post('/auth/logout'),
};
