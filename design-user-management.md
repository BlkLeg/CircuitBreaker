# Design Document: User Management Enhancements

## Objective
Enhance the User Management interface to expose powerful administrative capabilities. While the backend supports several advanced features (like masquerading and role updates), the frontend currently lacks the UI to utilize them. We also need to implement missing backend functionality like admin-initiated password resets and granular session revocation to provide a complete administrative toolkit.

## 1. Role & Permissions Management (Grant/Revoke)
**Context:** Currently, users are assigned a role during creation or invitation, but there is no UI to change it later.
*   **Backend:** The `PATCH /admin/users/{id}` endpoint already supports updating the `role` (viewer, editor, admin).
*   **Frontend UI:**
    *   Introduce an "Edit User" modal accessible from the actions column in the `AdminUsersPage`.
    *   Allow the admin to change the user's role via a dropdown and update their `display_name`.
    *   Show an immediate confirmation toast when the permissions are updated.

## 2. Admin-Initiated Password Reset
**Context:** When a user forgets their password or an account is compromised, admins need a fast way to secure it without relying on SMTP email recovery.
*   **Backend Implementation:** 
    *   Create a new endpoint `POST /admin/users/{id}/reset-password`.
    *   This endpoint will generate a secure temporary password (reusing the existing `_generate_temp_password()` helper).
    *   It will hash the temporary password, update the user's record, and critically, set `force_password_change = True`.
    *   It will automatically call the existing `revoke_all_sessions()` to log the user out of all active devices immediately.
    *   Return the temporary password in the API response.
*   **Frontend UI:**
    *   Add a "Reset Password" action button (key icon) in the user row.
    *   Display a secure overlay modal with the generated temporary password (similar to the local user creation success screen) featuring a copy-to-clipboard button and a warning that all active sessions have been terminated.

## 3. Masquerading (Login-As)
**Context:** Admins often need to see exactly what a specific user sees to troubleshoot permission issues or verify dashboard configurations.
*   **Backend:** The `POST /admin/users/{id}/masquerade` endpoint already exists. It returns a short-lived (15 min) JWT with specific `is_masquerade` claims.
*   **Frontend UI:**
    *   Add a "Masquerade" action button (mask or user-switch icon) to the user row.
    *   When clicked, call the API, swap the current authentication token in memory/storage with the returned masquerade token, and force a hard reload or React state reset.
    *   **Crucial UX:** Implement a persistent banner component at the top of the screen (e.g., "You are masquerading as user@example.com") with a "Return to Admin" button that restores the original admin session.

## 4. Session Revocation
**Context:** The UI currently displays the number of active sessions a user has, but provides no mechanism to act on that information.
*   **Backend:** Add an endpoint `DELETE /admin/users/{id}/sessions` to revoke all sessions for a specific user (wrapping the existing `revoke_all_sessions` service function).
*   **Frontend UI:**
    *   Add a "Revoke Sessions" action to the user row, rendered only if `session_count > 0`.
    *   Include a confirmation dialog: "Are you sure you want to log out [User] from all active devices?"

## Implementation Phases
1.  **Phase 1 (Backend Parity):** Implement the `reset-password` and `sessions` DELETE endpoints in `apps/backend/src/app/api/admin_users.py`.
2.  **Phase 2 (Frontend CRUD):** Update the `adminUsersApi` client and build the "Edit User", "Reset Password", and "Revoke Sessions" modals in `AdminUsersPage.jsx`.
3.  **Phase 3 (Masquerade):** Implement the masquerade token swapping logic in the `AuthContext` and build the global warning banner.
