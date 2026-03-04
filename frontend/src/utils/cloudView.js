/**
 * Cloud View Grouping Logic
 * Ported from v1.5 MapPage/TopologyMap logic
 */

export const groupNodesIntoCloud = (nodes) => {
  const newNodes = nodes.map(n => ({ ...n })); // Deep copy

  // Find nodes that should be grouped
  const nodesToGroup = newNodes.filter(n => n.data?.linkedNetworkId);

  nodesToGroup.forEach(child => {
    const parentId = `net-${child.data.linkedNetworkId}`; 
    // In CB v2, linkedNetworkId refers to the DB ID of the network, so we prefix it with 'net-'
    // to match the React Flow node ID format.
    const parent = newNodes.find(n => n.id === parentId);

    if (parent) {
      // Transform parent to cloud
      parent.data = { ...parent.data, isCloud: true, memberCount: (parent.data.memberCount || 0) + 1 };
      
      // Transform child
      child.parentId = parentId;
      child.extent = 'parent';
      
      // Calculate relative position (center them randomly within the parent cloud area)
      // Parent center is 200, 200 (since width/height in CustomNode is 400x400)
      child.position = {
        x: 140 + (Math.random() * 120 - 60),
        y: 140 + (Math.random() * 120 - 60)
      };
    }
  });

  return newNodes;
};

export const restoreFromCloudView = (nodes) => {
  const newNodes = nodes.map(n => ({ ...n }));

  // Find children
  const children = newNodes.filter(n => n.parentId);

  children.forEach(child => {
    const parent = newNodes.find(n => n.id === child.parentId);
    if (parent) {
      // Calculate new absolute position based on parent
      child.position = {
        x: (parent.position.x || 0) + (child.position.x || 0),
        y: (parent.position.y || 0) + (child.position.y || 0)
      };
      delete child.parentId;
      delete child.extent;
    }
  });

  // Reset parents
  newNodes.forEach(n => {
    if (n.data?.isCloud) {
      n.data = { ...n.data, isCloud: false, memberCount: 0 };
    }
  });

  return newNodes;
};
