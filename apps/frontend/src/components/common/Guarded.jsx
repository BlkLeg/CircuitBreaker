import React from 'react';
import PropTypes from 'prop-types';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext.jsx';
import { canEdit, isAdmin } from '../../utils/rbac';
import { guardFor } from '../../data/routeGuards';

/**
 * The only route guard in the app. The required role comes from data/routeGuards.js and
 * never from the call site — App.jsx and the navigation layer keeping separate lists is
 * what let /certificates and /notifications render for viewers while the menu hid them.
 *
 * Defense in depth: the API is the boundary. This stops a viewer loading a page that
 * would 403 in every panel, and stops the menu's `require` from being a claim nothing
 * enforces.
 */
export default function Guarded({ path, children }) {
  const { user } = useAuth();
  const guard = guardFor(path);
  if (guard === 'admin' && !isAdmin(user)) return <Navigate to="/map" replace />;
  if (guard === 'editor' && !canEdit(user)) return <Navigate to="/map" replace />;
  return children;
}

Guarded.propTypes = {
  path: PropTypes.string.isRequired,
  children: PropTypes.node.isRequired,
};
