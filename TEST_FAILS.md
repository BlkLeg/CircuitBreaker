E       KeyError: 'id'

../../tests/integration/test_categories.py:69: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_________________________________________________________ test_delete_category_unused __________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486f1a3570>

    def test_delete_category_unused(client):
        cat = _create_category(client).json()
>       resp = client.delete(f"/api/v1/categories/{cat['id']}")
                                                   ^^^^^^^^^
E       KeyError: 'id'

../../tests/integration/test_categories.py:79: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_________________________________________________________ test_delete_category_in_use __________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486f1a3ac0>

    def test_delete_category_in_use(client):
        cat = _create_category(client).json()
>       _create_service(client, name="Plex", category_id=cat["id"])
                                                         ^^^^^^^^^
E       KeyError: 'id'

../../tests/integration/test_categories.py:85: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_____________________________________________________ test_service_create_with_category_id _____________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486d26ce20>

    def test_service_create_with_category_id(client):
        cat = _create_category(client, name="infra").json()
>       resp = _create_service(client, name="Prometheus", category_id=cat["id"])
                                                                      ^^^^^^^^^
E       KeyError: 'id'

../../tests/integration/test_categories.py:113: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_______________________________________________ test_service_create_category_id_wins_over_string _______________________________________________

client = <starlette.testclient.TestClient object at 0x7f486d26d480>

    def test_service_create_category_id_wins_over_string(client):
        cat = _create_category(client, name="infra").json()
>       resp = _create_service(client, name="Grafana", category_id=cat["id"], category="other")
                                                                   ^^^^^^^^^
E       KeyError: 'id'

../../tests/integration/test_categories.py:120: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
______________________________________________________ test_category_log_entry_on_create _______________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486d26c270>

    def test_category_log_entry_on_create(client):
        _create_category(client, name="media")
>       logs = client.get("/api/v1/logs").json()["logs"]
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'logs'

../../tests/integration/test_categories.py:129: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
______________________________________________________ test_category_log_entry_on_rename _______________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486d26dae0>

    def test_category_log_entry_on_rename(client):
        cat = _create_category(client, name="media").json()
>       client.patch(f"/api/v1/categories/{cat['id']}", json={"name": "streaming"})
                                           ^^^^^^^^^
E       KeyError: 'id'

../../tests/integration/test_categories.py:140: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
______________________________________________________ test_category_log_entry_on_delete _______________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486d26d8c0>

    def test_category_log_entry_on_delete(client):
        cat = _create_category(client, name="media").json()
>       client.delete(f"/api/v1/categories/{cat['id']}")
                                            ^^^^^^^^^
E       KeyError: 'id'

../../tests/integration/test_categories.py:158: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
________________________________________________________ test_environment_log_on_create ________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487c50e140>

    def test_environment_log_on_create(client):
        _create_env(client, name="prod")
>       logs = client.get("/api/v1/logs").json()["logs"]
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'logs'

../../tests/integration/test_environments.py:162: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
________________________________________________________ test_environment_log_on_rename ________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487c50fdf0>

    def test_environment_log_on_rename(client):
        env = _create_env(client, name="prod").json()
        client.patch(f"/api/v1/environments/{env['id']}", json={"name": "production"})
    
>       logs = client.get("/api/v1/logs").json()["logs"]
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'logs'

../../tests/integration/test_environments.py:175: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
________________________________________________________ test_environment_log_on_delete ________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487c50fbd0>

    def test_environment_log_on_delete(client):
        env = _create_env(client, name="prod").json()
        client.delete(f"/api/v1/environments/{env['id']}")
    
>       logs = client.get("/api/v1/logs").json()["logs"]
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'logs'

../../tests/integration/test_environments.py:187: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
___________________________________________________________ test_conflict_log_entry ____________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487c50d480>

    def test_conflict_log_entry(client):
        _hw(client, name="pve-01", ip=HW_IP_A)
        _hw(client, name="pve-02", ip=HW_IP_A)  # triggers 409
    
>       logs = client.get("/api/v1/logs").json()["logs"]
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'logs'

../../tests/integration/test_ip_reservation.py:186: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
-------------------------------------------------------------- Captured log call ---------------------------------------------------------------
WARNING  app.services.hardware_service:hardware_service.py:203 IP conflict blocked save for hardware 'pve-02': 10.0.0.1 already used by pve-01
______________________________________________ TestAuthDisabledCRUD.test_settings_update_no_auth _______________________________________________

self = <integration.test_oobe_smoke.TestAuthDisabledCRUD object at 0x7f487c88f230>
client = <starlette.testclient.TestClient object at 0x7f48777dfdf0>

    def test_settings_update_no_auth(self, client):
        """PUT /settings works without auth when auth is disabled."""
        resp = client.put(f"{API}/settings", json={"theme": "dark"})
>       assert resp.status_code == 200
E       assert 401 == 200
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_oobe_smoke.py:189: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
________________________________________________ TestAuthDisabledCRUD.test_admin_export_no_auth ________________________________________________

self = <integration.test_oobe_smoke.TestAuthDisabledCRUD object at 0x7f487c704cb0>
client = <starlette.testclient.TestClient object at 0x7f486f1a3570>

    def test_admin_export_no_auth(self, client):
        """Admin export is accessible when auth is disabled."""
        resp = client.get(f"{API}/admin/export")
>       assert resp.status_code == 200
E       assert 401 == 200
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_oobe_smoke.py:194: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_____________________________________________ TestAppSettingsFields.test_update_rate_limit_profile _____________________________________________

self = <integration.test_phase1_auth.TestAppSettingsFields object at 0x7f487c7a4550>
client = <starlette.testclient.TestClient object at 0x7f486eead040>

    def test_update_rate_limit_profile(self, client):
        resp = client.put("/api/v1/settings", json={"rate_limit_profile": "strict"})
>       assert resp.status_code == 200
E       assert 401 == 200
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase1_auth.py:139: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
____________________________________________________________ test_audit_log_filters ____________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486eeacd10>, db = <sqlalchemy.orm.session.Session object at 0x7f48775caf90>

    def test_audit_log_filters(client, db):
        """Verify that log API filtering works with multiple filter params."""
        now = utcnow()
        db.add(
            Log(
                timestamp=now,
                category="crud",
                action="created",
                actor="alice",
                entity_type="hardware",
                severity="info",
            )
        )
        db.add(
            Log(
                timestamp=now,
                category="settings",
                action="updated",
                actor="bob",
                entity_type="settings",
                severity="warn",
            )
        )
        db.commit()
    
        r = client.get("/api/v1/logs", params={"action": "created"})
>       assert r.status_code == 200
E       assert 401 == 200
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase2_audit.py:129: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_______________________________________________________ test_settings_update_cve_fields ________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486eeae690>, db = <sqlalchemy.orm.session.Session object at 0x7f48775cb770>

    def test_settings_update_cve_fields(client, db):
        """PUT /api/v1/settings should accept CVE fields."""
        db.add(AppSettings(id=1))
        db.commit()
    
        r = client.put(
            "/api/v1/settings",
            json={
                "cve_sync_enabled": True,
                "cve_sync_interval_hours": 6,
            },
        )
>       assert r.status_code == 200
E       assert 401 == 200
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase2_cve.py:156: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_______________________________________________________ test_topology_ws_status_endpoint _______________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486eeac5a0>

    def test_topology_ws_status_endpoint(client: TestClient):
        """GET /api/v1/topology/ws/status returns connection metrics."""
        r = client.get("/api/v1/topology/ws/status")
>       assert r.status_code == 200
E       assert 401 == 200
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase3_realtime.py:156: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
____________________________________________________ test_settings_realtime_fields_writable ____________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486eeaf020>

    def test_settings_realtime_fields_writable(client: TestClient):
        """PUT /api/v1/settings can update realtime fields."""
        r = client.put(
            "/api/v1/settings",
            json={"realtime_notifications_enabled": False, "realtime_transport": "sse"},
        )
>       assert r.status_code == 200
E       assert 401 == 200
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase3_realtime.py:181: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_____________________________________ TestCapabilitiesReflectsSettings.test_auth_enabled_reflects_setting ______________________________________

self = <integration.test_phase6_capabilities.TestCapabilitiesReflectsSettings object at 0x7f487c7a4f50>
client = <starlette.testclient.TestClient object at 0x7f486da32e00>

    def test_auth_enabled_reflects_setting(self, client):
>       _create_settings(client, auth_enabled=True)

../../tests/integration/test_phase6_capabilities.py:83: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

client = <starlette.testclient.TestClient object at 0x7f486da32e00>, kwargs = {'auth_enabled': True}, r = <Response [401 Unauthorized]>
@py_assert1 = 401, @py_assert4 = (200, 201), @py_assert3 = False
@py_format6 = '401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'
@py_format8 = '{"detail":"Authentication required"}\n>assert 401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'

    def _create_settings(client, **kwargs):
        """Seed an AppSettings row via the settings PATCH endpoint."""
        r = client.put("/api/v1/settings", json=kwargs)
>       assert r.status_code in (200, 201), r.text
E       AssertionError: {"detail":"Authentication required"}
E       assert 401 in (200, 201)
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase6_capabilities.py:77: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_____________________________________ TestCapabilitiesReflectsSettings.test_auth_disabled_reflects_setting _____________________________________

self = <integration.test_phase6_capabilities.TestCapabilitiesReflectsSettings object at 0x7f487c7a5090>
client = <starlette.testclient.TestClient object at 0x7f486da31bf0>

    def test_auth_disabled_reflects_setting(self, client):
>       _create_settings(client, auth_enabled=False)

../../tests/integration/test_phase6_capabilities.py:88: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

client = <starlette.testclient.TestClient object at 0x7f486da31bf0>, kwargs = {'auth_enabled': False}, r = <Response [401 Unauthorized]>
@py_assert1 = 401, @py_assert4 = (200, 201), @py_assert3 = False
@py_format6 = '401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'
@py_format8 = '{"detail":"Authentication required"}\n>assert 401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'

    def _create_settings(client, **kwargs):
        """Seed an AppSettings row via the settings PATCH endpoint."""
        r = client.put("/api/v1/settings", json=kwargs)
>       assert r.status_code in (200, 201), r.text
E       AssertionError: {"detail":"Authentication required"}
E       assert 401 in (200, 201)
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase6_capabilities.py:77: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
______________________________________ TestCapabilitiesReflectsSettings.test_cve_enabled_reflects_setting ______________________________________

self = <integration.test_phase6_capabilities.TestCapabilitiesReflectsSettings object at 0x7f487c7bc180>
client = <starlette.testclient.TestClient object at 0x7f486eeacf30>

    def test_cve_enabled_reflects_setting(self, client):
>       _create_settings(client, cve_sync_enabled=True)

../../tests/integration/test_phase6_capabilities.py:93: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

client = <starlette.testclient.TestClient object at 0x7f486eeacf30>, kwargs = {'cve_sync_enabled': True}, r = <Response [401 Unauthorized]>
@py_assert1 = 401, @py_assert4 = (200, 201), @py_assert3 = False
@py_format6 = '401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'
@py_format8 = '{"detail":"Authentication required"}\n>assert 401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'

    def _create_settings(client, **kwargs):
        """Seed an AppSettings row via the settings PATCH endpoint."""
        r = client.put("/api/v1/settings", json=kwargs)
>       assert r.status_code in (200, 201), r.text
E       AssertionError: {"detail":"Authentication required"}
E       assert 401 in (200, 201)
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase6_capabilities.py:77: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
__________________________________ TestCapabilitiesReflectsSettings.test_realtime_transport_reflects_setting ___________________________________

self = <integration.test_phase6_capabilities.TestCapabilitiesReflectsSettings object at 0x7f487c7bc770>
client = <starlette.testclient.TestClient object at 0x7f48777debe0>

    def test_realtime_transport_reflects_setting(self, client):
>       _create_settings(client, realtime_transport="sse")

../../tests/integration/test_phase6_capabilities.py:98: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

client = <starlette.testclient.TestClient object at 0x7f48777debe0>, kwargs = {'realtime_transport': 'sse'}, r = <Response [401 Unauthorized]>
@py_assert1 = 401, @py_assert4 = (200, 201), @py_assert3 = False
@py_format6 = '401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'
@py_format8 = '{"detail":"Authentication required"}\n>assert 401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'

    def _create_settings(client, **kwargs):
        """Seed an AppSettings row via the settings PATCH endpoint."""
        r = client.put("/api/v1/settings", json=kwargs)
>       assert r.status_code in (200, 201), r.text
E       AssertionError: {"detail":"Authentication required"}
E       assert 401 in (200, 201)
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase6_capabilities.py:77: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
__________________________________ TestCapabilitiesReflectsSettings.test_listener_mdns_ssdp_reflects_setting ___________________________________

self = <integration.test_phase6_capabilities.TestCapabilitiesReflectsSettings object at 0x7f487c705d90>
client = <starlette.testclient.TestClient object at 0x7f48777df790>

    def test_listener_mdns_ssdp_reflects_setting(self, client):
>       _create_settings(client, listener_enabled=True, mdns_enabled=True, ssdp_enabled=False)

../../tests/integration/test_phase6_capabilities.py:103: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

client = <starlette.testclient.TestClient object at 0x7f48777df790>
kwargs = {'listener_enabled': True, 'mdns_enabled': True, 'ssdp_enabled': False}, r = <Response [401 Unauthorized]>, @py_assert1 = 401
@py_assert4 = (200, 201), @py_assert3 = False, @py_format6 = '401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'
@py_format8 = '{"detail":"Authentication required"}\n>assert 401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'

    def _create_settings(client, **kwargs):
        """Seed an AppSettings row via the settings PATCH endpoint."""
        r = client.put("/api/v1/settings", json=kwargs)
>       assert r.status_code in (200, 201), r.text
E       AssertionError: {"detail":"Authentication required"}
E       assert 401 in (200, 201)
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase6_capabilities.py:77: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_______________________________ TestCapabilitiesReflectsSettings.test_docker_discovery_enabled_reflects_setting ________________________________

self = <integration.test_phase6_capabilities.TestCapabilitiesReflectsSettings object at 0x7f487c8c6ad0>
client = <starlette.testclient.TestClient object at 0x7f48777df130>

    def test_docker_discovery_enabled_reflects_setting(self, client):
>       _create_settings(client, docker_discovery_enabled=True)

../../tests/integration/test_phase6_capabilities.py:110: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

client = <starlette.testclient.TestClient object at 0x7f48777df130>, kwargs = {'docker_discovery_enabled': True}
r = <Response [401 Unauthorized]>, @py_assert1 = 401, @py_assert4 = (200, 201), @py_assert3 = False
@py_format6 = '401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'
@py_format8 = '{"detail":"Authentication required"}\n>assert 401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'

    def _create_settings(client, **kwargs):
        """Seed an AppSettings row via the settings PATCH endpoint."""
        r = client.put("/api/v1/settings", json=kwargs)
>       assert r.status_code in (200, 201), r.text
E       AssertionError: {"detail":"Authentication required"}
E       assert 401 in (200, 201)
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase6_capabilities.py:77: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
___________________________________ TestCapabilitiesReflectsSettings.test_nats_available_true_when_connected ___________________________________

self = <integration.test_phase6_capabilities.TestCapabilitiesReflectsSettings object at 0x7f487c7db450>
client = <starlette.testclient.TestClient object at 0x7f48777de9c0>

    def test_nats_available_true_when_connected(self, client):
        """Mock is_connected as a property to simulate NATS connected state."""
>       _create_settings(client)  # ensure s is not None so the live branch is hit
        ^^^^^^^^^^^^^^^^^^^^^^^^

../../tests/integration/test_phase6_capabilities.py:121: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

client = <starlette.testclient.TestClient object at 0x7f48777de9c0>, kwargs = {}, r = <Response [401 Unauthorized]>, @py_assert1 = 401
@py_assert4 = (200, 201), @py_assert3 = False, @py_format6 = '401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'
@py_format8 = '{"detail":"Authentication required"}\n>assert 401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'

    def _create_settings(client, **kwargs):
        """Seed an AppSettings row via the settings PATCH endpoint."""
        r = client.put("/api/v1/settings", json=kwargs)
>       assert r.status_code in (200, 201), r.text
E       AssertionError: {"detail":"Authentication required"}
E       assert 401 in (200, 201)
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase6_capabilities.py:77: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_______________________________ TestCapabilitiesReflectsSettings.test_docker_socket_available_false_when_missing _______________________________

self = <integration.test_phase6_capabilities.TestCapabilitiesReflectsSettings object at 0x7f487c7db650>
client = <starlette.testclient.TestClient object at 0x7f48777de250>

    def test_docker_socket_available_false_when_missing(self, client):
        """Docker socket at a non-existent path reports available=False."""
>       _create_settings(client, docker_socket_path="/tmp/no-such-docker.sock")

../../tests/integration/test_phase6_capabilities.py:129: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

client = <starlette.testclient.TestClient object at 0x7f48777de250>, kwargs = {'docker_socket_path': '/tmp/no-such-docker.sock'}
r = <Response [401 Unauthorized]>, @py_assert1 = 401, @py_assert4 = (200, 201), @py_assert3 = False
@py_format6 = '401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'
@py_format8 = '{"detail":"Authentication required"}\n>assert 401\n{401 = <Response [401 Unauthorized]>.status_code\n} in (200, 201)'

    def _create_settings(client, **kwargs):
        """Seed an AppSettings row via the settings PATCH endpoint."""
        r = client.put("/api/v1/settings", json=kwargs)
>       assert r.status_code in (200, 201), r.text
E       AssertionError: {"detail":"Authentication required"}
E       assert 401 in (200, 201)
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_phase6_capabilities.py:77: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
____________________________________________________ test_vault_survives_simulated_restart _____________________________________________________

client = <starlette.testclient.TestClient object at 0x7f48777ddbf0>, db = <sqlalchemy.orm.session.Session object at 0x7f48775c9d30>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f486cc1c360>

    def test_vault_survives_simulated_restart(client, db, monkeypatch):
        """Core restart-persistence test.
    
        1. Bootstrap → vault key is persisted to DB (and env).
        2. Simulate restart: clear in-memory singleton and env var.
        3. Reload key from DB via load_vault_key().
        4. Re-initialize singleton with loaded key.
        5. Previously encrypted ciphertext must decrypt correctly.
        """
        from app.services import vault_service
        from app.services.credential_vault import CredentialVault, get_vault
    
        # Bootstrap to generate vault key
        resp = client.post("/api/v1/bootstrap/initialize", json=_BOOTSTRAP_PAYLOAD)
        assert resp.status_code == 200
    
        # Encrypt something using the current (bootstrapped) vault
        vault = get_vault()
        assert vault.is_initialized, "Vault should be initialized after bootstrap"
        secret = "my-snmp-community-string"
        ciphertext = vault.encrypt(secret)
    
        # Simulate restart: clear the singleton and remove env var
        fresh_vault = CredentialVault()
        monkeypatch.setattr("app.services.credential_vault._vault_instance", fresh_vault)
        saved_env_key = os.environ.pop("CB_VAULT_KEY", None)
    
        # Also disable file-based loading so we test the DB fallback
        import app.services.vault_service as vs
        original_path = vs._DATA_ENV_PATH
        monkeypatch.setattr(vs, "_DATA_ENV_PATH", Path("/nonexistent/.env"))
    
        try:
            # Load key from DB fallback
            loaded_key = vault_service.load_vault_key(db)
>           assert loaded_key is not None, "load_vault_key() should find key in DB after bootstrap"
E           AssertionError: load_vault_key() should find key in DB after bootstrap
E           assert None is not None

../../tests/integration/test_phase7_vault.py:179: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
-------------------------------------------------------------- Captured log call ---------------------------------------------------------------
WARNING  app.services.vault_service:vault_service.py:142 Could not write vault key to /data/.env: [Errno 13] Permission denied: '/data' — storing in DB only.
______________________________________________________ test_vault_rotation_updates_db_key ______________________________________________________

client = <starlette.testclient.TestClient object at 0x7f48777dde10>, db = <sqlalchemy.orm.session.Session object at 0x7f48775ca660>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f486cafd4e0>

    def test_vault_rotation_updates_db_key(client, db, monkeypatch):
        """rotate_vault_key() must update AppSettings.vault_key with the new key."""
        import app.services.vault_service as vs
    
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr(vs, "_DATA_ENV_PATH", Path(tmpdir) / ".env")
    
            from app.db.models import AppSettings
            from app.services import vault_service
    
            client.post("/api/v1/bootstrap/initialize", json=_BOOTSTRAP_PAYLOAD)
            cfg = db.get(AppSettings, 1)
>           old_key = cfg.vault_key
                      ^^^^^^^^^^^^^
E           AttributeError: 'AppSettings' object has no attribute 'vault_key'

../../tests/integration/test_phase7_vault.py:243: AttributeError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_________________________________________________________ test_load_vault_key_from_db __________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f48668fbf00>, db = <sqlalchemy.orm.session.Session object at 0x7f48775cbe00>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f4876913070>

    def test_load_vault_key_from_db(client, db, monkeypatch):
        """load_vault_key() falls back to AppSettings.vault_key when env and file are absent."""
        import app.services.vault_service as vs
        from app.services.vault_service import load_vault_key
    
        client.post("/api/v1/bootstrap/initialize", json=_BOOTSTRAP_PAYLOAD)
    
        monkeypatch.delenv("CB_VAULT_KEY", raising=False)
        monkeypatch.setattr(vs, "_DATA_ENV_PATH", Path("/nonexistent/.env"))
    
        result = load_vault_key(db)
>       assert result is not None
E       assert None is not None

../../tests/integration/test_phase7_vault.py:309: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
-------------------------------------------------------------- Captured log call ---------------------------------------------------------------
WARNING  app.services.vault_service:vault_service.py:142 Could not write vault key to /data/.env: [Errno 13] Permission denied: '/data' — storing in DB only.
_______________________________________________________ test_list_proxmox_configs_empty ________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487c50d370>

    def test_list_proxmox_configs_empty(client):
        r = client.get("/api/v1/integrations/proxmox")
>       assert r.status_code == 200
E       assert 401 == 200
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_proxmox.py:90: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
__________________________________________________________ test_create_proxmox_config __________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487c50d150>, monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f487c6403d0>

    def test_create_proxmox_config(client, monkeypatch):
        _mock_vault(monkeypatch)
        r = client.post("/api/v1/integrations/proxmox", json={
            "name": "Test PVE",
            "config_url": "https://pve.local:8006",
            "api_token": "root@pam!cbtoken=secret123",
            "auto_sync": True,
            "sync_interval_s": 300,
            "verify_ssl": False,
        })
>       assert r.status_code == 200
E       assert 401 == 200
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_proxmox.py:104: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
___________________________________________________________ test_get_proxmox_config ____________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f48777dcaf0>, monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f486fc5a890>

    def test_get_proxmox_config(client, monkeypatch):
        _mock_vault(monkeypatch)
        create = client.post("/api/v1/integrations/proxmox", json={
            "name": "My Cluster",
            "config_url": "https://pve.local:8006",
            "api_token": "user@pam!tok=val",
        })
>       cid = create.json()["id"]
              ^^^^^^^^^^^^^^^^^^^
E       KeyError: 'id'

../../tests/integration/test_proxmox.py:119: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
__________________________________________________________ test_update_proxmox_config __________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486d26c8d0>, monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f4866e47e00>

    def test_update_proxmox_config(client, monkeypatch):
        _mock_vault(monkeypatch)
        create = client.post("/api/v1/integrations/proxmox", json={
            "name": "Old Name",
            "config_url": "https://pve.local:8006",
            "api_token": "user@pam!tok=val",
        })
>       cid = create.json()["id"]
              ^^^^^^^^^^^^^^^^^^^
E       KeyError: 'id'

../../tests/integration/test_proxmox.py:133: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
__________________________________________________________ test_delete_proxmox_config __________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f486d26e250>, monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f486fc5b1c0>

    def test_delete_proxmox_config(client, monkeypatch):
        _mock_vault(monkeypatch)
        create = client.post("/api/v1/integrations/proxmox", json={
            "name": "ToDelete",
            "config_url": "https://pve.local:8006",
            "api_token": "user@pam!tok=val",
        })
>       cid = create.json()["id"]
              ^^^^^^^^^^^^^^^^^^^
E       KeyError: 'id'

../../tests/integration/test_proxmox.py:147: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
___________________________________________________________ test_get_proxmox_status ____________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487c50ead0>, monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f4875f571c0>

    def test_get_proxmox_status(client, monkeypatch):
        _mock_vault(monkeypatch)
        create = client.post("/api/v1/integrations/proxmox", json={
            "name": "Status Test",
            "config_url": "https://pve.local:8006",
            "api_token": "user@pam!tok=val",
        })
>       cid = create.json()["id"]
              ^^^^^^^^^^^^^^^^^^^
E       KeyError: 'id'

../../tests/integration/test_proxmox.py:163: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
____________________________________________________________ test_proxmox_not_found ____________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f48748447c0>

    def test_proxmox_not_found(client):
        r = client.get("/api/v1/integrations/proxmox/9999")
>       assert r.status_code == 404
E       assert 401 == 404
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_proxmox.py:175: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_______________________________________________________ test_log_entry_has_utc_timestamp _______________________________________________________

client = <starlette.testclient.TestClient object at 0x7f4874847680>

    def test_log_entry_has_utc_timestamp(client):
        client.post("/api/v1/hardware", json={"name": "test-hw"})
>       logs = client.get("/api/v1/logs").json()["logs"]
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'logs'

../../tests/integration/test_timestamps.py:43: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
____________________________________________________ test_log_entry_never_contains_just_now ____________________________________________________

client = <starlette.testclient.TestClient object at 0x7f4874248f30>

    def test_log_entry_never_contains_just_now(client):
        for i in range(5):
            client.post("/api/v1/hardware", json={"name": f"hw-{i}"})
    
>       logs = client.get("/api/v1/logs").json()["logs"]
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'logs'

../../tests/integration/test_timestamps.py:56: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
__________________________________________________ test_log_response_includes_elapsed_seconds __________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487424ae00>

    def test_log_response_includes_elapsed_seconds(client):
        client.post("/api/v1/hardware", json={"name": "test-hw"})
>       logs = client.get("/api/v1/logs").json()["logs"]
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'logs'

../../tests/integration/test_timestamps.py:64: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_____________________________________________________ test_settings_update_valid_timezone ______________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487424bac0>

    def test_settings_update_valid_timezone(client):
        resp = client.put("/api/v1/settings", json={"timezone": "America/Denver"})
>       assert resp.status_code == 200
E       assert 401 == 200
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_timezone.py:34: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
____________________________________________________ test_settings_update_invalid_timezone _____________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487424bdf0>

    def test_settings_update_invalid_timezone(client):
        resp = client.put("/api/v1/settings", json={"timezone": "Mars/Olympus"})
>       assert resp.status_code == 422
E       assert 401 == 422
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_timezone.py:42: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_____________________________________________________ test_settings_update_empty_timezone ______________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487424b460>

    def test_settings_update_empty_timezone(client):
        resp = client.put("/api/v1/settings", json={"timezone": ""})
>       assert resp.status_code == 422
E       assert 401 == 422
E        +  where 401 = <Response [401 Unauthorized]>.status_code

../../tests/integration/test_timezone.py:49: AssertionError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
_________________________________________________________ test_timezone_log_on_change __________________________________________________________

client = <starlette.testclient.TestClient object at 0x7f487424a140>

    def test_timezone_log_on_change(client):
        client.put("/api/v1/settings", json={"timezone": "America/Denver"})
    
>       logs = client.get("/api/v1/logs").json()["logs"]
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'logs'

../../tests/integration/test_timezone.py:57: KeyError
-------------------------------------------------------------- Captured log setup --------------------------------------------------------------
WARNING  app.workers.webhook_worker:webhook_worker.py:168 Waiting for NATS... retrying in 1s
WARNING  app.workers.notification_worker:notification_worker.py:127 Waiting for NATS... retrying in 1s
ERROR    app.workers.discovery:discovery.py:110 Failed to connect to NATS, retrying in 2s…
=============================================================== warnings summary ===============================================================
src/app/api/notifications.py:35
  /home/shawnji/Documents/projects/CircuitBreaker/apps/backend/src/app/api/notifications.py:35: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.12/migration/
    class SinkOut(BaseModel):

src/app/api/notifications.py:52
  /home/shawnji/Documents/projects/CircuitBreaker/apps/backend/src/app/api/notifications.py:52: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.12/migration/
    class RouteOut(BaseModel):

tests/integration/test_audit_log.py: 18 warnings
tests/integration/test_auth.py: 26 warnings
tests/integration/test_categories.py: 14 warnings
tests/integration/test_cortex.py: 14 warnings
tests/integration/test_crud_all_entities.py: 37 warnings
tests/integration/test_discovery.py: 26 warnings
tests/integration/test_environments.py: 13 warnings
tests/integration/test_graph_edge_types.py: 3 warnings
tests/integration/test_hardware.py: 6 warnings
tests/integration/test_ip_reservation.py: 13 warnings
tests/integration/test_oobe_smoke.py: 40 warnings
tests/integration/test_phase1_auth.py: 8 warnings
tests/integration/test_phase2_audit.py: 4 warnings
tests/integration/test_phase2_cve.py: 11 warnings
tests/integration/test_phase3_realtime.py: 6 warnings
tests/integration/test_phase6_5_users.py: 10 warnings
tests/integration/test_phase6_capabilities.py: 17 warnings
tests/integration/test_phase7_vault.py: 14 warnings
tests/integration/test_proxmox.py: 11 warnings
tests/integration/test_services.py: 7 warnings
tests/integration/test_timestamps.py: 5 warnings
tests/integration/test_timezone.py: 6 warnings
  /home/shawnji/Documents/projects/CircuitBreaker/tests/integration/conftest.py:34: SAWarning: Can't sort tables for DROP; an unresolvable foreign key dependency exists between tables: hardware, networks, scan_results; and backend does not support ALTER.  To restore at least a partial sort, apply use_alter=True to ForeignKey and ForeignKeyConstraint objects involved in the cycle to mark these as known cycles that will be ignored.
    Base.metadata.drop_all(engine)

tests/integration/test_phase6_5_users.py::test_admin_invite_email_uses_external_app_url
  /home/shawnji/Documents/projects/CircuitBreaker/apps/backend/src/app/api/admin_users.py:462: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    invite.email_sent_at = datetime.utcnow().isoformat()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================================================== short test summary info ============================================================
FAILED ../../tests/integration/test_audit_log.py::test_hardware_create_produces_log - KeyError: 'logs'
FAILED ../../tests/integration/test_audit_log.py::test_hardware_update_produces_log_with_diff - KeyError: 'logs'
FAILED ../../tests/integration/test_audit_log.py::test_hardware_delete_produces_log - KeyError: 'logs'
FAILED ../../tests/integration/test_audit_log.py::test_service_create_update_delete_logs - KeyError: 'logs'
FAILED ../../tests/integration/test_audit_log.py::test_network_create_update_delete_logs - KeyError: 'logs'
FAILED ../../tests/integration/test_audit_log.py::test_login_failure_produces_warn_log - KeyError: 'logs'
FAILED ../../tests/integration/test_audit_log.py::test_settings_update_log_never_contains_credentials - KeyError: 'logs'
FAILED ../../tests/integration/test_audit_log.py::test_logs_filter_by_entity_type - assert 401 == 200
FAILED ../../tests/integration/test_audit_log.py::test_logs_filter_by_action - assert 401 == 200
FAILED ../../tests/integration/test_audit_log.py::test_logs_filter_by_severity - assert 401 == 200
FAILED ../../tests/integration/test_audit_log.py::test_logs_search_by_entity_name - assert 401 == 200
FAILED ../../tests/integration/test_audit_log.py::test_logs_pagination - assert 401 == 200
FAILED ../../tests/integration/test_audit_log.py::test_oobe_complete_produces_log - KeyError: 'logs'
FAILED ../../tests/integration/test_categories.py::test_create_category_success - assert 401 == 201
FAILED ../../tests/integration/test_categories.py::test_create_category_case_insensitive_duplicate - assert 401 == 409
FAILED ../../tests/integration/test_categories.py::test_create_category_no_color - assert 401 == 201
FAILED ../../tests/integration/test_categories.py::test_list_categories_includes_service_count - KeyError: 'id'
FAILED ../../tests/integration/test_categories.py::test_rename_category - KeyError: 'id'
FAILED ../../tests/integration/test_categories.py::test_delete_category_unused - KeyError: 'id'
FAILED ../../tests/integration/test_categories.py::test_delete_category_in_use - KeyError: 'id'
FAILED ../../tests/integration/test_categories.py::test_service_create_with_category_id - KeyError: 'id'
FAILED ../../tests/integration/test_categories.py::test_service_create_category_id_wins_over_string - KeyError: 'id'
FAILED ../../tests/integration/test_categories.py::test_category_log_entry_on_create - KeyError: 'logs'
FAILED ../../tests/integration/test_categories.py::test_category_log_entry_on_rename - KeyError: 'id'
FAILED ../../tests/integration/test_categories.py::test_category_log_entry_on_delete - KeyError: 'id'
FAILED ../../tests/integration/test_environments.py::test_environment_log_on_create - KeyError: 'logs'
FAILED ../../tests/integration/test_environments.py::test_environment_log_on_rename - KeyError: 'logs'
FAILED ../../tests/integration/test_environments.py::test_environment_log_on_delete - KeyError: 'logs'
FAILED ../../tests/integration/test_ip_reservation.py::test_conflict_log_entry - KeyError: 'logs'
FAILED ../../tests/integration/test_oobe_smoke.py::TestAuthDisabledCRUD::test_settings_update_no_auth - assert 401 == 200
FAILED ../../tests/integration/test_oobe_smoke.py::TestAuthDisabledCRUD::test_admin_export_no_auth - assert 401 == 200
FAILED ../../tests/integration/test_phase1_auth.py::TestAppSettingsFields::test_update_rate_limit_profile - assert 401 == 200
FAILED ../../tests/integration/test_phase2_audit.py::test_audit_log_filters - assert 401 == 200
FAILED ../../tests/integration/test_phase2_cve.py::test_settings_update_cve_fields - assert 401 == 200
FAILED ../../tests/integration/test_phase3_realtime.py::test_topology_ws_status_endpoint - assert 401 == 200
FAILED ../../tests/integration/test_phase3_realtime.py::test_settings_realtime_fields_writable - assert 401 == 200
FAILED ../../tests/integration/test_phase6_capabilities.py::TestCapabilitiesReflectsSettings::test_auth_enabled_reflects_setting - AssertionError: {"detail":"Authentication required"}
FAILED ../../tests/integration/test_phase6_capabilities.py::TestCapabilitiesReflectsSettings::test_auth_disabled_reflects_setting - AssertionError: {"detail":"Authentication required"}
FAILED ../../tests/integration/test_phase6_capabilities.py::TestCapabilitiesReflectsSettings::test_cve_enabled_reflects_setting - AssertionError: {"detail":"Authentication required"}
FAILED ../../tests/integration/test_phase6_capabilities.py::TestCapabilitiesReflectsSettings::test_realtime_transport_reflects_setting - AssertionError: {"detail":"Authentication required"}
FAILED ../../tests/integration/test_phase6_capabilities.py::TestCapabilitiesReflectsSettings::test_listener_mdns_ssdp_reflects_setting - AssertionError: {"detail":"Authentication required"}
FAILED ../../tests/integration/test_phase6_capabilities.py::TestCapabilitiesReflectsSettings::test_docker_discovery_enabled_reflects_setting - AssertionError: {"detail":"Authentication required"}
FAILED ../../tests/integration/test_phase6_capabilities.py::TestCapabilitiesReflectsSettings::test_nats_available_true_when_connected - AssertionError: {"detail":"Authentication required"}
FAILED ../../tests/integration/test_phase6_capabilities.py::TestCapabilitiesReflectsSettings::test_docker_socket_available_false_when_missing - AssertionError: {"detail":"Authentication required"}
FAILED ../../tests/integration/test_phase7_vault.py::test_vault_survives_simulated_restart - AssertionError: load_vault_key() should find key in DB after bootstrap
FAILED ../../tests/integration/test_phase7_vault.py::test_vault_rotation_updates_db_key - AttributeError: 'AppSettings' object has no attribute 'vault_key'
FAILED ../../tests/integration/test_phase7_vault.py::test_load_vault_key_from_db - assert None is not None
FAILED ../../tests/integration/test_proxmox.py::test_list_proxmox_configs_empty - assert 401 == 200
FAILED ../../tests/integration/test_proxmox.py::test_create_proxmox_config - assert 401 == 200
FAILED ../../tests/integration/test_proxmox.py::test_get_proxmox_config - KeyError: 'id'
FAILED ../../tests/integration/test_proxmox.py::test_update_proxmox_config - KeyError: 'id'
FAILED ../../tests/integration/test_proxmox.py::test_delete_proxmox_config - KeyError: 'id'
FAILED ../../tests/integration/test_proxmox.py::test_get_proxmox_status - KeyError: 'id'
FAILED ../../tests/integration/test_proxmox.py::test_proxmox_not_found - assert 401 == 404
FAILED ../../tests/integration/test_timestamps.py::test_log_entry_has_utc_timestamp - KeyError: 'logs'
FAILED ../../tests/integration/test_timestamps.py::test_log_entry_never_contains_just_now - KeyError: 'logs'
FAILED ../../tests/integration/test_timestamps.py::test_log_response_includes_elapsed_seconds - KeyError: 'logs'
FAILED ../../tests/integration/test_timezone.py::test_settings_update_valid_timezone - assert 401 == 200
FAILED ../../tests/integration/test_timezone.py::test_settings_update_invalid_timezone - assert 401 == 422
FAILED ../../tests/integration/test_timezone.py::test_settings_update_empty_timezone - assert 401 == 422
FAILED ../../tests/integration/test_timezone.py::test_timezone_log_on_change - KeyError: 'logs'
61 failed, 276 passed, 8 skipped, 312 warnings in 51.28s
make: *** [Makefile:82: test] Error 1
(.venv) shawnji@fedora-laptop:~/Documents/projects/CircuitBreaker$ 