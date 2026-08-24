import React from 'react';
import AccessTokensManager from '../components/settings/AccessTokensManager';

/**
 * Page shell for the token administration UI built under INC-14.
 *
 * AccessTokensManager renders a bare <div> with no page chrome, so unlike
 * AdminUsersPage and KnowledgeBasePage it needs no `embedded` prop — the
 * heading lives here and the component is mounted as-is. The shell follows
 * IntelPage: `.page` carries the fixed-header offset, and `.page-header` is a
 * flex row that would put the subtitle beside the heading rather than under it.
 */
export default function AccessTokensPage() {
  return (
    <div className="page">
      <h2>Access Tokens</h2>
      <p style={{ opacity: 0.7, fontSize: 12 }}>
        API tokens and service accounts across every administrator, with the scopes each one
        carries.
      </p>
      <AccessTokensManager />
    </div>
  );
}
