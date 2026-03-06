import client from './client';

export const authApi = {
  bootstrapStatus: () => client.get('/bootstrap/status'),
  bootstrapInitialize: (payload) => client.post('/bootstrap/initialize', payload),
  register: (email, password, displayName) => {
    const body = { email, password };
    if (displayName) body.display_name = displayName;
    return client.post('/auth/register', body);
  },
  login: (email, password) => {
    const params = new URLSearchParams();
    params.append('username', email);
    params.append('password', password);
    return client.post('/auth/jwt/login', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
  },
  me: () => client.get('/auth/me'),
  updateProfile: (formData, tokenOverride) => {
    const headers = tokenOverride ? { Authorization: `Bearer ${tokenOverride}` } : {};
    return client.put('/auth/me/avatar', formData, { headers });
  },
  logout: () => client.post('/auth/jwt/logout'),
  forgotPassword: (email) => client.post('/auth/forgot-password', { email }),
};
