# Security Scan Report - Mon Mar  9 10:36:16 PM MST 2026
## 1. Bandit (Python Static Analysis)
```
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.14.3
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:01
Run started:2026-03-10 05:36:18.447886+00:00

Test results:
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/admin_db.py:41:4
40	                alembic_version = row[0]
41	    except Exception:
42	        pass
43	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/admin_db.py:58:8
57	                    db_size_mb = round(row[0] / 1_048_576, 2)
58	        except Exception:
59	            pass
60	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/admin_db.py:75:8
74	                    connections_max = int(row2[0])
75	        except Exception:
76	            pass
77	

--------------------------------------------------
>> Issue: [B105:hardcoded_password_string] Possible hardcoded password: 'token exchange'
   Severity: Low   Confidence: Medium
   CWE: CWE-259 (https://cwe.mitre.org/data/definitions/259.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b105_hardcoded_password_string.html
   Location: apps/backend/src/app/api/auth_oauth.py:26:24
25	_OAUTH_STATE_TTL = timedelta(minutes=10)
26	_STAGE_TOKEN_EXCHANGE = "token exchange"
27	_STAGE_USER_LOOKUP = "user lookup"

--------------------------------------------------
>> Issue: [B101:assert_used] Use of assert detected. The enclosed code will be removed when compiling to optimised byte code.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b101_assert_used.html
   Location: apps/backend/src/app/api/auth_oauth.py:242:8
241	    else:
242	        assert user is not None
243	        user.provider = provider

--------------------------------------------------
>> Issue: [B101:assert_used] Use of assert detected. The enclosed code will be removed when compiling to optimised byte code.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b101_assert_used.html
   Location: apps/backend/src/app/api/auth_oauth.py:255:4
254	    db.refresh(user)
255	    assert user is not None
256	    return user, is_new

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/branding.py:157:4
156	        data = buf.getvalue()
157	    except Exception:
158	        # If Pillow fails, save the raw upload — it's already validated by extension
159	        pass
160	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/discovery.py:88:4
87	            )
88	    except Exception:
89	        pass
90	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/discovery.py:105:8
104	            docker_container_count = get_docker_status(socket_path).get("container_count", 0)
105	        except Exception:
106	            pass
107	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/discovery.py:137:8
136	                return DiscoveryStatusOut.model_validate(payload)
137	        except Exception:
138	            pass
139	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/discovery.py:145:8
144	            await nats_client.kv_put("dashboard_cache", cache_key, json.dumps(out.model_dump()))
145	        except Exception:
146	            pass
147	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/discovery.py:216:8
215	            vlan_ids = json.loads(profile.vlan_ids)
216	        except Exception:
217	            pass
218	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/events.py:87:8
86	                    last_log_id = max_id
87	        except Exception:
88	            pass
89	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/events.py:189:20
188	                        await sub.unsubscribe()
189	                    except Exception:
190	                        pass
191	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/proxmox.py:221:8
220	                return ProxmoxClusterOverviewResponse(**payload)
221	        except Exception:
222	            pass
223	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/proxmox.py:233:8
232	            await nats_client.kv_put("dashboard_cache", cache_key, json.dumps(payload))
233	        except Exception:
234	            pass
235	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/settings.py:114:12
113	                existing[provider_name].pop("client_secret", None)
114	            except Exception:
115	                pass  # Vault not available, keep plain for now
116	    settings.oauth_providers = json.dumps(existing)

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/settings.py:144:16
143	                    entry.pop("client_secret", None)
144	                except Exception:
145	                    pass  # Keep plaintext if vault unavailable
146	            elif not entry.get("client_secret"):

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/status.py:216:8
215	                return DashboardV2Response(groups=groups_models, global_=global_model)
216	        except Exception:
217	            pass  # Fallback to DB on cache miss/error
218	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/status.py:236:8
235	            await nats_client.kv_put("dashboard_cache", cache_key, json.dumps(cache_payload))
236	        except Exception:
237	            pass
238	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:113:16
112	                    await websocket.close(code=1008)
113	                except Exception:
114	                    pass
115	                return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:155:12
154	                await websocket.close(code=1008)
155	            except Exception:
156	                pass
157	            return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:165:12
164	                await websocket.close(code=1008)
165	            except Exception:
166	                pass
167	            return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:182:16
181	                        await websocket.send_text(json.dumps({"type": "pong", "ts": utcnow_iso()}))
182	                except Exception:
183	                    pass  # Unknown / malformed client frames are silently ignored.
184	        except WebSocketDisconnect:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:195:8
194	            await websocket.close(code=1011)
195	        except Exception:
196	            pass
197	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_status.py:52:4
51	            await ws.send_text(json.dumps({"type": "ping", "ts": utcnow_iso()}))
52	    except Exception:
53	        pass
54	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_status.py:151:8
150	            await websocket.close(code=1011)
151	        except Exception:
152	            pass
153	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:227:16
226	                    await websocket.close(code=1008)
227	                except Exception:
228	                    pass
229	                return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:265:12
264	                await websocket.close(code=1008)
265	            except Exception:
266	                pass
267	            return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:277:12
276	                await websocket.close(code=1008)
277	            except Exception:
278	                pass
279	            return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:293:16
292	                        await websocket.send_text(json.dumps({"type": "pong", "ts": utcnow_iso()}))
293	                except Exception:
294	                    pass
295	        except WebSocketDisconnect:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:306:8
305	            await websocket.close(code=1011)
306	        except Exception:
307	            pass
308	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/core/audit.py:67:12
66	                    actor_name = u.display_name or u.email
67	            except Exception:
68	                pass
69	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/core/audit.py:77:8
76	            redact_ip = getattr(cfg, "audit_log_hide_ip", False)
77	        except Exception:
78	            pass
79	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/core/audit.py:98:4
97	        db.commit()
98	    except Exception:
99	        # Audit logging must never crash the request it decorates.
100	        pass

--------------------------------------------------
>> Issue: [B324:hashlib] Use of weak MD5 hash for security. Consider usedforsecurity=False
   Severity: High   Confidence: High
   CWE: CWE-327 (https://cwe.mitre.org/data/definitions/327.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b324_hashlib.html
   Location: apps/backend/src/app/core/security.py:115:11
114	def gravatar_hash(email: str) -> str:
115	    return hashlib.md5(email.strip().lower().encode()).hexdigest()  # noqa: S324
116	

--------------------------------------------------
>> Issue: [B105:hardcoded_password_string] Possible hardcoded password: 'CB_JWT_SECRET'
   Severity: Low   Confidence: Medium
   CWE: CWE-259 (https://cwe.mitre.org/data/definitions/259.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b105_hardcoded_password_string.html
   Location: apps/backend/src/app/core/users.py:24:20
23	# JWT secret: DB (from OOBE/settings) or CB_JWT_SECRET env only. No vault/API-token or runtime random.
24	CB_JWT_SECRET_ENV = "CB_JWT_SECRET"
25	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/core/users.py:97:8
96	                raw_token = json.loads(response.body).get("access_token")
97	        except Exception:
98	            pass
99	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/core/users.py:200:4
199	            db.close()
200	    except Exception:
201	        pass
202	

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:59:18
58	            text(
59	                f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM read_csv_auto(:path) LIMIT 0"
60	            )

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:63:19
62	        conn.execute(
63	            text(f"INSERT INTO {table} SELECT * FROM read_csv_auto(:path)"), {"path": path}
64	        )

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:65:40
64	        )
65	        row_count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0
66	        conn.commit()

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: apps/backend/src/app/integrations/apc_ups.py:1:0
1	import subprocess
2	
3	from app.core.validation import validate_snmp_community

--------------------------------------------------
>> Issue: [B607:start_process_with_partial_path] Starting a process with a partial executable path
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b607_start_process_with_partial_path.html
   Location: apps/backend/src/app/integrations/apc_ups.py:22:12
21	        safe_community = validate_snmp_community(community)
22	        r = subprocess.run(
23	            ["snmpget", "-v2c", "-c", safe_community, "-Oqv", host, oid],
24	            capture_output=True,
25	            text=True,
26	            timeout=3,
27	        )
28	        return r.stdout.strip() if r.returncode == 0 else None

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: apps/backend/src/app/integrations/apc_ups.py:22:12
21	        safe_community = validate_snmp_community(community)
22	        r = subprocess.run(
23	            ["snmpget", "-v2c", "-c", safe_community, "-Oqv", host, oid],
24	            capture_output=True,
25	            text=True,
26	            timeout=3,
27	        )
28	        return r.stdout.strip() if r.returncode == 0 else None

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: apps/backend/src/app/integrations/idrac.py:1:0
1	import subprocess
2	
3	from app.core.validation import validate_snmp_community

--------------------------------------------------
>> Issue: [B607:start_process_with_partial_path] Starting a process with a partial executable path
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b607_start_process_with_partial_path.html
   Location: apps/backend/src/app/integrations/idrac.py:18:12
17	        safe_community = validate_snmp_community(community)
18	        r = subprocess.run(
19	            ["snmpget", "-v2c", "-c", safe_community, "-Oqv", host, oid],
20	            capture_output=True,
21	            text=True,
22	            timeout=3,
23	        )
24	        return r.stdout.strip() if r.returncode == 0 else None

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: apps/backend/src/app/integrations/idrac.py:18:12
17	        safe_community = validate_snmp_community(community)
18	        r = subprocess.run(
19	            ["snmpget", "-v2c", "-c", safe_community, "-Oqv", host, oid],
20	            capture_output=True,
21	            text=True,
22	            timeout=3,
23	        )
24	        return r.stdout.strip() if r.returncode == 0 else None

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: apps/backend/src/app/integrations/snmp_generic.py:1:0
1	import subprocess
2	
3	from app.core.validation import validate_snmp_community

--------------------------------------------------
>> Issue: [B607:start_process_with_partial_path] Starting a process with a partial executable path
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b607_start_process_with_partial_path.html
   Location: apps/backend/src/app/integrations/snmp_generic.py:9:12
8	        safe_community = validate_snmp_community(community)
9	        r = subprocess.run(
10	            ["snmpget", "-v2c", "-c", safe_community, "-Oqv", host, oid],
11	            capture_output=True,
12	            text=True,
13	            timeout=3,
14	        )
15	        return r.stdout.strip() if r.returncode == 0 else None

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: apps/backend/src/app/integrations/snmp_generic.py:9:12
8	        safe_community = validate_snmp_community(community)
9	        r = subprocess.run(
10	            ["snmpget", "-v2c", "-c", safe_community, "-Oqv", host, oid],
11	            capture_output=True,
12	            text=True,
13	            timeout=3,
14	        )
15	        return r.stdout.strip() if r.returncode == 0 else None

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/main.py:233:4
232	            command.stamp(alembic_cfg, "a3b4c5d6e7fc")  # 0015_proxmox_storage
233	    except Exception:
234	        pass
235	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/main.py:278:8
277	            _vault_db.close()
278	        except Exception:
279	            pass
280	        raise SystemExit(1) from _ve

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/middleware/logging_middleware.py:313:12
312	                old_value_str = _fetch_entity_json(entity_type, entity_id)
313	            except Exception:
314	                pass
315	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/middleware/logging_middleware.py:335:12
334	                    new_value_str = resp_body.decode("utf-8")
335	            except Exception:
336	                pass
337	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/middleware/logging_middleware.py:347:12
346	                entity_id = parsed.get("id")
347	            except Exception:
348	                pass
349	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/middleware/logging_middleware.py:356:12
355	                entity_name = _parsed.get("name") or _parsed.get("title") or ""
356	            except Exception:
357	                pass
358	        # Fall back to request body name if response had none

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/middleware/logging_middleware.py:363:12
362	                entity_name = _parsed.get("name") or _parsed.get("title") or ""
363	            except Exception:
364	                pass
365	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/middleware/logging_middleware.py:373:8
372	                diff = {"before": before, "after": after}
373	        except Exception:
374	            pass
375	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/schemas/settings.py:233:12
232	                self.theme_colors = json.loads(raw)
233	            except Exception:
234	                pass
235	        return self

--------------------------------------------------
>> Issue: [B105:hardcoded_password_string] Possible hardcoded password: 'OAuth token is invalid or expired'
   Severity: Low   Confidence: Medium
   CWE: CWE-259 (https://cwe.mitre.org/data/definitions/259.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b105_hardcoded_password_string.html
   Location: apps/backend/src/app/services/auth_service.py:32:27
31	_MSG_BOOTSTRAP_DONE = "Bootstrap already completed. Please refresh and log in."
32	_MSG_OAUTH_TOKEN_INVALID = "OAuth token is invalid or expired"
33	

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: apps/backend/src/app/services/db_backup.py:15:0
14	import shutil
15	import subprocess
16	from datetime import UTC, datetime, timedelta

--------------------------------------------------
>> Issue: [B607:start_process_with_partial_path] Starting a process with a partial executable path
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b607_start_process_with_partial_path.html
   Location: apps/backend/src/app/services/db_backup.py:60:15
59	    try:
60	        proc = subprocess.run(  # noqa: S603
61	            ["pg_dump", "--no-password"],
62	            env=_pg_env_from_url(db_url),
63	            capture_output=True,
64	            check=True,
65	        )
66	        with gzip.open(out_path, "wb") as f:

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: apps/backend/src/app/services/db_backup.py:60:15
59	    try:
60	        proc = subprocess.run(  # noqa: S603
61	            ["pg_dump", "--no-password"],
62	            env=_pg_env_from_url(db_url),
63	            capture_output=True,
64	            check=True,
65	        )
66	        with gzip.open(out_path, "wb") as f:

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: apps/backend/src/app/services/discovery_safe.py:7:0
6	import socket
7	import subprocess
8	from concurrent.futures import ThreadPoolExecutor

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_safe.py:41:4
40	            return True
41	    except Exception:
42	        pass
43	

--------------------------------------------------
>> Issue: [B607:start_process_with_partial_path] Starting a process with a partial executable path
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b607_start_process_with_partial_path.html
   Location: apps/backend/src/app/services/discovery_safe.py:46:12
45	    try:
46	        r = subprocess.run(
47	            ["ping", "-c", "1", "-W", "1", ip],
48	            stdout=subprocess.DEVNULL,
49	            stderr=subprocess.DEVNULL,
50	            timeout=3,
51	        )
52	        return r.returncode == 0

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: apps/backend/src/app/services/discovery_safe.py:46:12
45	    try:
46	        r = subprocess.run(
47	            ["ping", "-c", "1", "-W", "1", ip],
48	            stdout=subprocess.DEVNULL,
49	            stderr=subprocess.DEVNULL,
50	            timeout=3,
51	        )
52	        return r.returncode == 0

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:257:12
256	                    payload["eta_seconds"] = int(max(0, total_est - elapsed))
257	            except Exception:
258	                pass
259	    if processed is not None:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:547:16
546	                    await writer.wait_closed()
547	                except Exception:
548	                    pass
549	                text = data.decode(errors="replace").strip()[:256]

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:552:12
551	                    banners[port] = text
552	            except Exception:
553	                pass
554	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:568:4
567	                return r.text.strip()[:100]
568	    except Exception:
569	        pass
570	    return None

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1007:20
1006	                            await client.get(f"http://{ip}")
1007	                    except Exception:
1008	                        pass
1009	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1351:12
1350	                db.commit()
1351	            except Exception:
1352	                pass
1353	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1406:12
1405	                vlan_ids = json.loads(profile.vlan_ids)
1406	            except Exception:
1407	                pass
1408	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1571:8
1570	                asyncio.run(_emit_result_processed_event(db, result.id, "reject"))
1571	        except Exception:
1572	            pass  # Don't fail the operation if WebSocket emission fails
1573	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1633:16
1632	                        asyncio.run(_emit_result_processed_event(db, result.id, "accept"))
1633	                except Exception:
1634	                    pass  # Don't fail the operation if WebSocket emission fails
1635	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1704:16
1703	                        asyncio.run(_emit_result_processed_event(db, result.id, "accept"))
1704	                except Exception:
1705	                    pass  # Don't fail the operation if WebSocket emission fails
1706	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/listener_service.py:159:16
158	                    ip = socket.inet_ntoa(info.addresses[0])
159	                except Exception:
160	                    pass
161	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/listener_service.py:171:12
170	                }
171	            except Exception:
172	                pass
173	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/listener_service.py:210:12
209	                send_sock.close()
210	            except Exception:
211	                pass
212	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/listener_service.py:306:8
305	            )
306	        except Exception:
307	            pass
308	

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: apps/backend/src/app/services/monitor_service.py:13:0
12	import socket
13	import subprocess
14	import time

--------------------------------------------------
>> Issue: [B607:start_process_with_partial_path] Starting a process with a partial executable path
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b607_start_process_with_partial_path.html
   Location: apps/backend/src/app/services/monitor_service.py:47:12
46	        t0 = time.monotonic()
47	        r = subprocess.run(
48	            ["ping", "-c", "1", "-W", "1", ip],
49	            stdout=subprocess.DEVNULL,
50	            stderr=subprocess.DEVNULL,
51	            timeout=3,
52	        )
53	        latency = (time.monotonic() - t0) * 1000

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: apps/backend/src/app/services/monitor_service.py:47:12
46	        t0 = time.monotonic()
47	        r = subprocess.run(
48	            ["ping", "-c", "1", "-W", "1", ip],
49	            stdout=subprocess.DEVNULL,
50	            stderr=subprocess.DEVNULL,
51	            timeout=3,
52	        )
53	        latency = (time.monotonic() - t0) * 1000

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to httpx with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b501_request_with_no_cert_validation.html
   Location: apps/backend/src/app/services/monitor_service.py:96:17
95	            # Intentionally skip TLS verification for self-signed certs common in homelabs.
96	            with httpx.Client(verify=False, timeout=timeout) as client:  # noqa: S501
97	                resp = client.head(url)

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/monitor_service.py:101:8
100	                return True, round(latency, 2)
101	        except Exception:
102	            pass
103	    return False, None

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/monitor_service.py:138:4
137	            return True, round(latency, 2)
138	    except Exception:
139	        pass
140	    return False, None

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/monitor_service.py:206:8
205	            return [int(p) for p in ports]
206	        except Exception:
207	            pass
208	    return _TCP_FALLBACK_PORTS

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/monitor_service.py:226:4
225	        snmp_community = settings.discovery_snmp_community or None
226	    except Exception:
227	        pass
228	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/proxmox_service.py:98:4
97	        await nats_client.publish(subject, payload)
98	    except Exception:
99	        pass
100	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/proxmox_service.py:1286:8
1285	                uptime_str = f"{d}d {h}h {m}m"
1286	        except Exception:
1287	            pass
1288	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/self_discovery.py:32:8
31	            labels = json.loads(service.docker_labels)
32	        except Exception:
33	            pass
34	

--------------------------------------------------
>> Issue: [B107:hardcoded_password_default] Possible hardcoded password: ''
   Severity: Low   Confidence: Medium
   CWE: CWE-259 (https://cwe.mitre.org/data/definitions/259.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b107_hardcoded_password_default.html
   Location: apps/backend/src/app/services/smtp_service.py:358:0
357	
358	def _reset_html(
359	    app_name: str, primary_color: str, has_logo: bool, reset_url: str, reset_token: str = ""
360	) -> str:
361	    header = _header_block(app_name, primary_color, has_logo)
362	    btn = _s_btn(primary_color)
363	    token_block = (
364	        f'    <p style="{_S_P}">Enter this token in the reset form: <code style="background:#3c3836;padding:4px 8px;border-radius:4px;word-break:break-all">{reset_token}</code></p>'
365	        if reset_token
366	        else ""
367	    )
368	    return (
369	        f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"></head>'
370	        f'<body style="margin:0;padding:0;background:#1d2021">'
371	        f'<div style="{_S_WRAP}">'
372	        f"  {header}"
373	        f'  <div style="{_S_BODY}">'
374	        f'    <p style="{_S_P}">Hi there,</p>'
375	        f'    <p style="{_S_P}">A password reset was requested for your'
376	        f"    <strong>{app_name}</strong> account.</p>"
377	        f'    <p style="{_S_P}">Click the button below to open the reset page, then enter the token from this email and your new password. This token expires in 1 hour.</p>'
378	        f'    <a href="{reset_url}" style="{btn}">Reset Password &rarr;</a>'
379	        f"{token_block}"
380	        f'    <hr style="{_S_HR}">'
381	        f'    <p style="{_S_SMALL}">If you didn&rsquo;t request this, you can safely'
382	        f"    ignore this email &mdash; your password has not been changed.</p>"
383	        f"  </div>"
384	        f'  <div style="{_S_FOOT}">{app_name} &mdash; automated security notification</div>'
385	        f"</div>"
386	        f"</body></html>"
387	    )
388	

--------------------------------------------------
>> Issue: [B105:hardcoded_password_string] Possible hardcoded password: 'circuitbreaker:invite'
   Severity: Low   Confidence: Medium
   CWE: CWE-259 (https://cwe.mitre.org/data/definitions/259.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b105_hardcoded_password_string.html
   Location: apps/backend/src/app/services/user_service.py:19:19
18	
19	INVITE_TOKEN_AUD = "circuitbreaker:invite"
20	VALID_ROLES = frozenset({"admin", "editor", "viewer"})

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:260:4
259	        )
260	    except Exception:  # noqa: BLE001
261	        pass
262	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:309:4
308	        )
309	    except Exception:  # noqa: BLE001
310	        pass
311	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:326:4
325	            count += 1
326	    except Exception:  # noqa: BLE001
327	        pass
328	    try:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:334:4
333	        )
334	    except Exception:  # noqa: BLE001
335	        pass
336	    try:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:338:4
337	        count += db.query(Credential).count()
338	    except Exception:  # noqa: BLE001
339	        pass
340	    return count

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:354:4
353	            return "healthy" if _sha256(current_key) == cfg.vault_key_hash else "degraded"
354	    except Exception:  # noqa: BLE001
355	        pass
356	    return "healthy"

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:368:4
367	            last_rotated = cfg.vault_key_rotated_at.isoformat()
368	    except Exception:  # noqa: BLE001
369	        pass
370	

--------------------------------------------------
>> Issue: [B104:hardcoded_bind_all_interfaces] Possible binding to all interfaces.
   Severity: Medium   Confidence: Medium
   CWE: CWE-605 (https://cwe.mitre.org/data/definitions/605.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b104_hardcoded_bind_all_interfaces.html
   Location: apps/backend/src/app/start.py:163:62
162	
163	    host = str(_get_option(args.host, "HOST", config, "host", "0.0.0.0"))
164	    port = int(str(_get_option(args.port, "PORT", config, "port", 8080)))

--------------------------------------------------
>> Issue: [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
   Severity: Medium   Confidence: Medium
   CWE: CWE-377 (https://cwe.mitre.org/data/definitions/377.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b108_hardcoded_tmp_directory.html
   Location: apps/backend/src/app/workers/discovery.py:12:21
11	
12	_HEALTHY_FILE = Path("/tmp/worker.healthy")  # noqa: S108
13	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/workers/discovery.py:91:12
90	                await msg.nak()
91	            except Exception:
92	                pass
93	        except Exception as e:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/workers/discovery.py:97:12
96	                await msg.nak()
97	            except Exception:
98	                pass
99	

--------------------------------------------------
>> Issue: [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
   Severity: Medium   Confidence: Medium
   CWE: CWE-377 (https://cwe.mitre.org/data/definitions/377.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b108_hardcoded_tmp_directory.html
   Location: apps/backend/src/app/workers/notification_worker.py:17:21
16	
17	_HEALTHY_FILE = Path("/tmp/worker.healthy")  # noqa: S108
18	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/workers/status_worker.py:51:16
50	                        metrics.append({"type": "hardware", "id": hid, "data": data})
51	                except Exception:
52	                    pass
53	            # Daily uptime for this hardware

--------------------------------------------------
>> Issue: [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
   Severity: Medium   Confidence: Medium
   CWE: CWE-377 (https://cwe.mitre.org/data/definitions/377.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b108_hardcoded_tmp_directory.html
   Location: apps/backend/src/app/workers/webhook_worker.py:19:21
18	
19	_HEALTHY_FILE = Path("/tmp/worker.healthy")  # noqa: S108
20	

--------------------------------------------------

Code scanned:
	Total lines of code: 27251
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 0

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 100
		Medium: 7
		High: 2
	Total issues (by confidence):
		Undefined: 0
		Low: 3
		Medium: 9
		High: 97
Files skipped (0):
```
## 2. Semgrep (Static Analysis)
```
               
               
┌─────────────┐
│ Scan Status │
└─────────────┘
  Scanning 373 files tracked by git with 1063 Code rules:
                                                                                                                        
  Language      Rules   Files          Origin      Rules                                                                
 ─────────────────────────────        ───────────────────                                                               
  <multilang>      58     249          Community    1063                                                                
  js              156     180                                                                                           
  python          243     161                                                                                           
  yaml             31       4                                                                                           
  dockerfile        6       2                                                                                           
  json              4       2                                                                                           
  ts              166       1                                                                                           
  bash              4       1                                                                                           
                                                                                                                        
                
                
┌──────────────┐
│ Scan Summary │
└──────────────┘
✅ Scan completed successfully.
 • Findings: 28 (28 blocking)
 • Rules run: 507
 • Targets scanned: 373
 • Parsed lines: ~99.9%
 • Scan was limited to files tracked by git
 • For a detailed list of skipped files and lines, run semgrep with the --verbose flag
Ran 507 rules on 373 files: 28 findings.

A new version of Semgrep is available. See https://semgrep.dev/docs/upgrading

📢 Too many findings? Try Semgrep Pro for more powerful queries and less noise.
   See https://sg.run/false-positives.
                    
                    
┌──────────────────┐
│ 28 Code Findings │
└──────────────────┘
                                            
    apps/backend/src/app/api/ws_discovery.py
   ❯❯❱ javascript.lang.security.detect-insecure-websocket.detect-insecure-websocket
          Insecure WebSocket Detected. WebSocket Secure (wss) should be used for all WebSocket connections.
          Details: https://sg.run/GWyz                                                                     
                                                                                                           
           33┆ - Plain ws:// connections are warned about in production (use WSS).
            ⋮┆----------------------------------------
           69┆ """Log a warning when the connection arrives over plain ws:// in production."""
                                      
    apps/backend/src/app/core/users.py
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          Detected a python logger call with a potential hardcoded secret "Password reset email sent to %s"
          being logged. This may lead to secret credentials being exposed. Make sure that the logger is not
          logging  sensitive information.                                                                  
          Details: https://sg.run/ydNx                                                                     
                                                                                                           
          158┆ _logger.info("Password reset email sent to %s", user.email)
            ⋮┆----------------------------------------
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          Detected a python logger call with a potential hardcoded secret "Password reset token for %s (SMTP  
          not configured): %s" being logged. This may lead to secret credentials being exposed. Make sure that
          the logger is not logging  sensitive information.                                                   
          Details: https://sg.run/ydNx                                                                        
                                                                                                              
          160┆ _logger.info(
          161┆     "Password reset token for %s (SMTP not configured): %s",
          162┆     user.email,
          163┆     token,
          164┆ )
            ⋮┆----------------------------------------
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          Detected a python logger call with a potential hardcoded secret "Failed to send password reset email
          to %s: %s" being logged. This may lead to secret credentials being exposed. Make sure that the      
          logger is not logging  sensitive information.                                                       
          Details: https://sg.run/ydNx                                                                        
                                                                                                              
          166┆ _logger.warning("Failed to send password reset email to %s: %s", user.email, exc)
                                            
    apps/backend/src/app/db/duckdb_client.py
   ❯❯❱ python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
          sqlalchemy.text passes the constructed SQL statement to the database mostly unchanged. This means  
          that the usual SQL injection protections are not applied and this function is vulnerable to SQL    
          injection if user input can reach here. Use normal SQLAlchemy operators (such as `or_()`, `and_()`,
          etc.) to construct SQL.                                                                            
          Details: https://sg.run/yP1O                                                                       
                                                                                                             
           58┆ text(
           59┆     f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM read_csv_auto(:path) LIMIT 0"
           60┆ )
            ⋮┆----------------------------------------
           63┆ text(f"INSERT INTO {table} SELECT * FROM read_csv_auto(:path)"), {"path": path}
            ⋮┆----------------------------------------
           65┆ row_count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0
                                         
    apps/backend/src/app/db/migrations.py
   ❯❯❱ python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
          sqlalchemy.text passes the constructed SQL statement to the database mostly unchanged. This means  
          that the usual SQL injection protections are not applied and this function is vulnerable to SQL    
          injection if user input can reach here. Use normal SQLAlchemy operators (such as `or_()`, `and_()`,
          etc.) to construct SQL.                                                                            
          Details: https://sg.run/yP1O                                                                       
                                                                                                             
           57┆ text(f"PRAGMA table_info({table_name})")
                                                     
    apps/backend/src/app/services/hardware_service.py
    ❯❱ python.sqlalchemy.performance.performance-improvements.len-all-count
          Using QUERY.count() instead of len(QUERY.all()) sends less data to the client since the SQLAlchemy
          method is performed server-side.                                                                  
          Details: https://sg.run/4y8g                                                                      
                                                                                                            
          440┆ cu_count = len(
          441┆     db.execute(select(ComputeUnit).where(ComputeUnit.hardware_id == hardware_id))
          442┆     .scalars()
          443┆     .all()
          444┆ )
            ⋮┆----------------------------------------
          447┆ st_count = len(
          448┆     db.execute(select(Storage).where(Storage.hardware_id == hardware_id)).scalars().all()
          449┆ )
            ⋮┆----------------------------------------
          452┆ svc_count = len(
          453┆     db.execute(select(Service).where(Service.hardware_id == hardware_id)).scalars().all()
          454┆ )
                                                     
    apps/backend/src/app/services/listener_service.py
     ❱ python.lang.security.audit.network.bind.avoid-bind-to-all-interfaces
          Running `socket.bind` to 0.0.0.0, or empty string could unexpectedly expose the server publicly as
          it binds to all available interfaces. Consider instead getting correct address from an environment
          variable or configuration file.                                                                   
          Details: https://sg.run/rdln                                                                      
                                                                                                            
          190┆ sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
          191┆ sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
          192┆ try:
          193┆     sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
          194┆ except AttributeError:
          195┆     pass  # not available on all platforms
          196┆ sock.bind(("", _SSDP_PORT))
                                                  
    apps/backend/src/app/services/vault_service.py
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          Detected a python logger call with a potential hardcoded secret "Could not re-encrypt SMTP password 
          during rotation: %s" being logged. This may lead to secret credentials being exposed. Make sure that
          the logger is not logging  sensitive information.                                                   
          Details: https://sg.run/ydNx                                                                        
                                                                                                              
          206┆ _logger.warning("Could not re-encrypt SMTP password during rotation: %s", exc)
            ⋮┆----------------------------------------
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          Detected a python logger call with a potential hardcoded secret "Could not re-encrypt credential %d 
          during rotation: %s" being logged. This may lead to secret credentials being exposed. Make sure that
          the logger is not logging  sensitive information.                                                   
          Details: https://sg.run/ydNx                                                                        
                                                                                                              
          228┆ _logger.warning("Could not re-encrypt credential %d during rotation: %s", cred.id, exc)
                             
    docker/backend.Dockerfile
   ❯❯❱ dockerfile.security.missing-user-entrypoint.missing-user-entrypoint
          By not specifying a USER, a program in the container may run as 'root'. This is a security hazard.
          If an attacker can control a process running as root, they may have control over the container.   
          Ensure that the last USER in a Dockerfile is a USER other than 'root'.                            
          Details: https://sg.run/k281                                                                      
                                                                                                            
           ▶▶┆ Autofix ▶ USER non-root ENTRYPOINT ["/entrypoint.sh"]
           72┆ ENTRYPOINT ["/entrypoint.sh"]
   
   ❯❯❱ dockerfile.security.missing-user.missing-user
          By not specifying a USER, a program in the container may run as 'root'. This is a security hazard.
          If an attacker can control a process running as root, they may have control over the container.   
          Ensure that the last USER in a Dockerfile is a USER other than 'root'.                            
          Details: https://sg.run/Gbvn                                                                      
                                                                                                            
           ▶▶┆ Autofix ▶ USER non-root CMD ["python", "src/app/start.py"]
           73┆ CMD ["python", "src/app/start.py"]
                     
    docker/nginx.conf
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           45┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           46┆ proxy_http_version 1.1;
           47┆ proxy_set_header   Upgrade    $http_upgrade;
           48┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           57┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           58┆ proxy_http_version 1.1;
           59┆ proxy_set_header   Upgrade    $http_upgrade;
           60┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           70┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           71┆ proxy_http_version 1.1;
           72┆ proxy_set_header   Upgrade    $http_upgrade;
           73┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           83┆ proxy_pass         $backend;
            ⋮┆----------------------------------------
           96┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          108┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          116┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          124┆ proxy_pass $backend;

```
## 3. npm audit (Frontend)
```
found 0 vulnerabilities
```
## 4. Trivy (Filesystem Scan)
```
2026-03-10T05:36:38Z	INFO	[vulndb] Need to update DB
2026-03-10T05:36:38Z	INFO	[vulndb] Downloading vulnerability DB...
2026-03-10T05:36:38Z	INFO	[vulndb] Downloading artifact...	repo="mirror.gcr.io/aquasec/trivy-db:2"
2026-03-10T05:36:45Z	INFO	[vulndb] Artifact successfully downloaded	repo="mirror.gcr.io/aquasec/trivy-db:2"
2026-03-10T05:36:45Z	INFO	[vuln] Vulnerability scanning is enabled
2026-03-10T05:36:45Z	INFO	[secret] Secret scanning is enabled
2026-03-10T05:36:45Z	INFO	[secret] If your scanning is slow, please try '--scanners vuln' to disable secret scanning
2026-03-10T05:36:45Z	INFO	[secret] Please see https://trivy.dev/docs/v0.69/guide/scanner/secret#recommendation for faster secret detection
2026-03-10T05:36:49Z	WARN	[secret] Invalid UTF-8 sequences detected in file content, replacing with empty string
2026-03-10T05:37:06Z	WARN	[secret] The size of the scanned file is too large. It is recommended to use `--skip-files` for this file to avoid high memory consumption.	file_path="apps/frontend/dist/assets/StatusPage-CS9qZ0nK.js.map" size (MB)=19
2026-03-10T05:37:08Z	WARN	[pip] Unable to find python `site-packages` directory. License detection is skipped.	err="unable to find path to Python executable"
2026-03-10T05:37:08Z	INFO	[npm] To collect the license information of packages, "npm install" needs to be performed beforehand	dir="proxmox-cluster-dashboard/node_modules"
2026-03-10T05:37:08Z	INFO	Suppressing dependencies for development and testing. To display them, try the '--include-dev-deps' flag.
2026-03-10T05:37:08Z	INFO	Number of language-specific files	num=5
2026-03-10T05:37:08Z	INFO	[npm] Detecting vulnerabilities...
2026-03-10T05:37:08Z	INFO	[pip] Detecting vulnerabilities...
2026-03-10T05:37:08Z	INFO	[poetry] Detecting vulnerabilities...

Report Summary

┌──────────────────────────────────────────────────────────────────────────────────┬────────┬─────────────────┬─────────┐
│                                      Target                                      │  Type  │ Vulnerabilities │ Secrets │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ apps/backend/poetry.lock                                                         │ poetry │        0        │    -    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ apps/backend/requirements.txt                                                    │  pip   │        0        │    -    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ apps/frontend/package-lock.json                                                  │  npm   │        0        │    -    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ proxmox-cluster-dashboard/package-lock.json                                      │  npm   │        0        │    -    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.14/site-packages/fastapi_users/authentication/transport/__pyc- │  text  │        -        │    1    │
│ ache__/bearer.cpython-314.pyc                                                    │        │                 │         │
└──────────────────────────────────────────────────────────────────────────────────┴────────┴─────────────────┴─────────┘
Legend:
- '-': Not scanned
- '0': Clean (no security findings detected)


.venv/lib/python3.14/site-packages/fastapi_users/authentication/transport/__pycache__/bearer.cpython-314.pyc (secrets)
======================================================================================================================
Total: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 1, HIGH: 0, CRITICAL: 0)

MEDIUM: JWT (jwt-token)
════════════════════════════════════════
JWT token
────────────────────────────────────────


```
