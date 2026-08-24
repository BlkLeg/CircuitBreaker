import client from './client.jsx';

// INC-14: API token administration. All routes are require_role("admin").

export const listTokens = (scope = 'mine') => client.get('/auth/api-tokens', { params: { scope } });

export const createToken = (body) => client.post('/auth/api-token', body);

export const createServiceAccount = (body) => client.post('/auth/service-account', body);

export const rotateToken = (id) => client.post(`/auth/api-tokens/${id}/rotate`);

export const revokeToken = (id) => client.delete(`/auth/api-tokens/${id}`);

export const getScopeCatalog = () => client.get('/auth/scopes');
