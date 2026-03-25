import client from './client';

export const mapsApi = {
  list: () => client.get('/maps').then((r) => r.data),
  create: (name) => client.post('/maps', { name }).then((r) => r.data),
  update: (id, patch) => client.patch(`/maps/${id}`, patch).then((r) => r.data),
  delete: (id) => client.delete(`/maps/${id}`),
  assignEntity: (mapId, entityType, entityId) =>
    client
      .post(`/maps/${mapId}/entities`, { entity_type: entityType, entity_id: entityId })
      .then((r) => r.data),
  removeEntity: (mapId, entityType, entityId) =>
    client.delete(`/maps/${mapId}/entities/${entityType}/${entityId}`),
  pinEntity: (entityType, entityId) =>
    client.post('/maps/pin', { entity_type: entityType, entity_id: entityId }).then((r) => r.data),
  unpinEntity: (entityType, entityId) => client.delete(`/maps/pin/${entityType}/${entityId}`),
};
