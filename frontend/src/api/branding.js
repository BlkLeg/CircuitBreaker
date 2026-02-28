import client from './client';

export const brandingApi = {
  uploadFavicon: (file) => {
    const form = new FormData();
    form.append('file', file);
    return client.post('/branding/upload-favicon', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  uploadLoginLogo: (file) => {
    const form = new FormData();
    form.append('file', file);
    return client.post('/branding/upload-login-logo', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  exportTheme: () => client.get('/branding/export'),

  importTheme: (data) => client.post('/branding/import', data),
};
