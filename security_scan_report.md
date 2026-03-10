# Security Scan Report - Tue Mar 10 12:00:14 AM MST 2026
## 1. Bandit (Python SAST)
```
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.14.3
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:01
Run started:2026-03-10 07:00:16.101676+00:00

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
   Location: apps/backend/src/app/api/branding.py:168:4
167	        data = buf.getvalue()
168	    except Exception:
169	        # If Pillow fails, save the raw upload — it's already validated by extension
170	        pass
171	

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
   Location: apps/backend/src/app/api/settings.py:118:12
117	                existing[provider_name].pop("client_secret", None)
118	            except Exception:
119	                pass  # Vault not available, keep plain for now
120	    settings.oauth_providers = json.dumps(existing)

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/settings.py:148:16
147	                    entry.pop("client_secret", None)
148	                except Exception:
149	                    pass  # Keep plaintext if vault unavailable
150	            elif not entry.get("client_secret"):

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
   Location: apps/backend/src/app/api/ws_discovery.py:103:8
102	            await websocket.close(code=1008)
103	        except Exception:
104	            pass
105	        return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:121:16
120	                    await websocket.close(code=1008)
121	                except Exception:
122	                    pass
123	                return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:163:12
162	                await websocket.close(code=1008)
163	            except Exception:
164	                pass
165	            return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:173:12
172	                await websocket.close(code=1008)
173	            except Exception:
174	                pass
175	            return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:190:16
189	                        await websocket.send_text(json.dumps({"type": "pong", "ts": utcnow_iso()}))
190	                except Exception:
191	                    pass  # Unknown / malformed client frames are silently ignored.
192	        except WebSocketDisconnect:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:203:8
202	            await websocket.close(code=1011)
203	        except Exception:
204	            pass
205	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_status.py:54:4
53	            await ws.send_text(json.dumps({"type": "ping", "ts": utcnow_iso()}))
54	    except Exception:
55	        pass
56	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_status.py:75:8
74	            await websocket.close(code=1008)
75	        except Exception:
76	            pass
77	        return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_status.py:162:8
161	            await websocket.close(code=1011)
162	        except Exception:
163	            pass
164	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:218:8
217	            await websocket.close(code=1008)
218	        except Exception:
219	            pass
220	        return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:235:16
234	                    await websocket.close(code=1008)
235	                except Exception:
236	                    pass
237	                return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:273:12
272	                await websocket.close(code=1008)
273	            except Exception:
274	                pass
275	            return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:285:12
284	                await websocket.close(code=1008)
285	            except Exception:
286	                pass
287	            return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:301:16
300	                        await websocket.send_text(json.dumps({"type": "pong", "ts": utcnow_iso()}))
301	                except Exception:
302	                    pass
303	        except WebSocketDisconnect:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_topology.py:314:8
313	            await websocket.close(code=1011)
314	        except Exception:
315	            pass
316	

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
   Location: apps/backend/src/app/main.py:235:4
234	            command.stamp(alembic_cfg, "a3b4c5d6e7fc")  # 0015_proxmox_storage
235	    except Exception:
236	        pass
237	

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
   Location: apps/backend/src/app/services/discovery_service.py:72:8
71	            return None, None
72	        except Exception:
73	            pass  # Fall back to Python loop on invalid cidr or other error
74	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:277:12
276	                    payload["eta_seconds"] = int(max(0, total_est - elapsed))
277	            except Exception:
278	                pass
279	    if processed is not None:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:567:16
566	                    await writer.wait_closed()
567	                except Exception:
568	                    pass
569	                text = data.decode(errors="replace").strip()[:256]

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:572:12
571	                    banners[port] = text
572	            except Exception:
573	                pass
574	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:588:4
587	                return r.text.strip()[:100]
588	    except Exception:
589	        pass
590	    return None

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1027:20
1026	                            await client.get(f"http://{ip}")
1027	                    except Exception:
1028	                        pass
1029	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1371:12
1370	                db.commit()
1371	            except Exception:
1372	                pass
1373	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1426:12
1425	                vlan_ids = json.loads(profile.vlan_ids)
1426	            except Exception:
1427	                pass
1428	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1591:8
1590	                asyncio.run(_emit_result_processed_event(db, result.id, "reject"))
1591	        except Exception:
1592	            pass  # Don't fail the operation if WebSocket emission fails
1593	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1653:16
1652	                        asyncio.run(_emit_result_processed_event(db, result.id, "accept"))
1653	                except Exception:
1654	                    pass  # Don't fail the operation if WebSocket emission fails
1655	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/discovery_service.py:1724:16
1723	                        asyncio.run(_emit_result_processed_event(db, result.id, "accept"))
1724	                except Exception:
1725	                    pass  # Don't fail the operation if WebSocket emission fails
1726	

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
	Total lines of code: 27450
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 0

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 103
		Medium: 7
		High: 2
	Total issues (by confidence):
		Undefined: 0
		Low: 3
		Medium: 9
		High: 100
Files skipped (0):
```
## 2. Semgrep (SAST)
```
               
               
┌─────────────┐
│ Scan Status │
└─────────────┘
  Scanning 377 files tracked by git with 1063 Code rules:
                                                                                                                        
  Language      Rules   Files          Origin      Rules                                                                
 ─────────────────────────────        ───────────────────                                                               
  <multilang>      58     251          Community    1063                                                                
  js              156     180                                                                                           
  python          243     164                                                                                           
  yaml             31       5                                                                                           
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
 • Targets scanned: 377
 • Parsed lines: ~99.9%
 • Scan was limited to files tracked by git
 • For a detailed list of skipped files and lines, run semgrep with the --verbose flag
Ran 507 rules on 377 files: 28 findings.

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
## 3. Gitleaks (Secret Scanning)
```
Finding:     Revises: 0016_webhook_deliveries_oauth_states, [1;3;mb4a9c1d2e8f0[0m
Secret:      [1;3;mb4a9c1d2e8f0[0m
RuleID:      generic-api-key
Entropy:     3.584963
File:        apps/backend/migrations/versions/0020_merge_heads.py
Line:        4
Commit:      2ecbb38e8c6d5faa82501b23e748d1cd5a3190c9
Author:      BlkLeg Shawnji
Email:       blacklegshawnji@gamil.com
Date:        2026-03-08T17:08:27Z
Fingerprint: 2ecbb38e8c6d5faa82501b23e748d1cd5a3190c9:apps/backend/migrations/versions/0020_merge_heads.py:generic-api-key:4
Link:        https://github.com/BlkLeg/CircuitBreaker/blob/2ecbb38e8c6d5faa82501b23e748d1cd5a3190c9/apps/backend/migrations/versions/0020_merge_heads.py#L4

```
## 4. ESLint + security (Frontend)
```

> circuit-breaker-ui@0.2.0 lint
> eslint .


Oops! Something went wrong! :(

ESLint: 9.39.3

Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'eslint-plugin-security' imported from /home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/eslint.config.mjs
    at packageResolve (node:internal/modules/esm/resolve:873:9)
    at moduleResolve (node:internal/modules/esm/resolve:946:18)
    at defaultResolve (node:internal/modules/esm/resolve:1188:11)
    at ModuleLoader.defaultResolve (node:internal/modules/esm/loader:708:12)
    at #cachedDefaultResolve (node:internal/modules/esm/loader:657:25)
    at ModuleLoader.resolve (node:internal/modules/esm/loader:640:38)
    at ModuleLoader.getModuleJobForImport (node:internal/modules/esm/loader:264:38)
    at ModuleJob._link (node:internal/modules/esm/module_job:168:49)
```
## 5. Hadolint (Dockerfile lint)
```
Hadolint skipped (binary/docker not found).
```
## 6. Checkov (IaC)
```
dockerfile scan results:

Passed checks: 330, Failed checks: 7, Skipped checks: 0

Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /backend.Dockerfile.
	File: /backend.Dockerfile:1-73
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /backend.Dockerfile.
	File: /backend.Dockerfile:1-73
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /frontend.Dockerfile.
	File: /frontend.Dockerfile:1-34
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | # ── Build stage ──────────────────────────────────────────────────────────────
		2  | FROM node:20-alpine AS builder
		3  | 
		4  | WORKDIR /app
		5  | 
		6  | COPY apps/frontend/package.json apps/frontend/package-lock.json* ./
		7  | # BuildKit cache mount keeps node_modules cache between builds (avoids re-downloading ~986 packages).
		8  | RUN --mount=type=cache,target=/root/.npm \
		9  |     npm ci
		10 | 
		11 | # VERSION must land at /VERSION (one level above WORKDIR /app) so the
		12 | # syncversion script's readFileSync('../VERSION') resolves correctly.
		13 | COPY VERSION /VERSION
		14 | COPY apps/frontend/ ./
		15 | 
		16 | RUN npm run build
		17 | 
		18 | # ── Serve stage ──────────────────────────────────────────────────────────────
		19 | # Use the official unprivileged nginx image — binds on 8080, no root required
		20 | FROM nginxinc/nginx-unprivileged:1.27-alpine
		21 | 
		22 | # Create the breaker26 user that matches the rest of the stack
		23 | USER root
		24 | RUN addgroup -S breaker26 && adduser -S -G breaker26 -H -s /sbin/nologin breaker26
		25 | 
		26 | COPY --from=builder /app/dist /usr/share/nginx/html
		27 | COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
		28 | RUN chown -R breaker26:breaker26 /usr/share/nginx/html
		29 | 
		30 | USER breaker26
		31 | 
		32 | EXPOSE 8080
		33 | 
		34 | CMD ["nginx", "-g", "daemon off;"]
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /Dockerfile.prod.
	File: /Dockerfile.prod:1-17
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | FROM python:3.12-alpine AS backend
		2  | WORKDIR /app
		3  | COPY apps/backend/src ./src
		4  | COPY apps/backend/requirements.txt ./
		5  | RUN pip install -r requirements.txt
		6  | 
		7  | FROM node:20-alpine AS frontend
		8  | WORKDIR /app
		9  | COPY apps/frontend ./
		10 | RUN npm ci --prod && npm run build
		11 | 
		12 | FROM python:3.12-alpine
		13 | WORKDIR /app
		14 | COPY --from=backend /app /app
		15 | COPY --from=frontend /app/dist /app/static
		16 | EXPOSE 8080
		17 | CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.prod.
	File: /Dockerfile.prod:1-17
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		1  | FROM python:3.12-alpine AS backend
		2  | WORKDIR /app
		3  | COPY apps/backend/src ./src
		4  | COPY apps/backend/requirements.txt ./
		5  | RUN pip install -r requirements.txt
		6  | 
		7  | FROM node:20-alpine AS frontend
		8  | WORKDIR /app
		9  | COPY apps/frontend ./
		10 | RUN npm ci --prod && npm run build
		11 | 
		12 | FROM python:3.12-alpine
		13 | WORKDIR /app
		14 | COPY --from=backend /app /app
		15 | COPY --from=frontend /app/dist /app/static
		16 | EXPOSE 8080
		17 | CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /Dockerfile.native.
	File: /Dockerfile.native:1-48
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | FROM ubuntu:22.04
		6  | 
		7  | ENV DEBIAN_FRONTEND=noninteractive
		8  | 
		9  | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		10 | RUN apt-get update && apt-get install -y --no-install-recommends \
		11 |     ca-certificates \
		12 |     curl \
		13 |     gnupg \
		14 |     software-properties-common \
		15 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		16 |     && mkdir -p /etc/apt/keyrings \
		17 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		18 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		19 |     && apt-get update \
		20 |     && apt-get install -y --no-install-recommends \
		21 |     python3.12 \
		22 |     python3.12-venv \
		23 |     libpython3.12 \
		24 |     nodejs \
		25 |     binutils \
		26 |     && rm -rf /var/lib/apt/lists/*
		27 | 
		28 | # Ensure python3.12 is the default; install pip for it
		29 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		30 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		31 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		32 | 
		33 | WORKDIR /build
		34 | 
		35 | # Copy repo (context is repo root)
		36 | COPY . .
		37 | 
		38 | # Install backend deps + PyInstaller
		39 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		40 | 
		41 | # Build frontend
		42 | RUN cd apps/frontend && npm ci && npm run build
		43 | 
		44 | # Build native package
		45 | RUN python3 scripts/build_native_release.py --clean
		46 | 
		47 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		48 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.native.
	File: /Dockerfile.native:1-48
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | FROM ubuntu:22.04
		6  | 
		7  | ENV DEBIAN_FRONTEND=noninteractive
		8  | 
		9  | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		10 | RUN apt-get update && apt-get install -y --no-install-recommends \
		11 |     ca-certificates \
		12 |     curl \
		13 |     gnupg \
		14 |     software-properties-common \
		15 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		16 |     && mkdir -p /etc/apt/keyrings \
		17 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		18 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		19 |     && apt-get update \
		20 |     && apt-get install -y --no-install-recommends \
		21 |     python3.12 \
		22 |     python3.12-venv \
		23 |     libpython3.12 \
		24 |     nodejs \
		25 |     binutils \
		26 |     && rm -rf /var/lib/apt/lists/*
		27 | 
		28 | # Ensure python3.12 is the default; install pip for it
		29 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		30 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		31 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		32 | 
		33 | WORKDIR /build
		34 | 
		35 | # Copy repo (context is repo root)
		36 | COPY . .
		37 | 
		38 | # Install backend deps + PyInstaller
		39 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		40 | 
		41 | # Build frontend
		42 | RUN cd apps/frontend && npm ci && npm run build
		43 | 
		44 | # Build native package
		45 | RUN python3 scripts/build_native_release.py --clean
		46 | 
		47 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		48 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]

2026-03-10 00:00:49,615 [MainThread  ] [ERROR]  YAML error parsing ./site/search/search_index.json: while parsing a quoted scalar
  in "<unicode string>", line 1, column 104579
found invalid Unicode character escape code
  in "<unicode string>", line 1, column 107748
cloudformation scan results:

Passed checks: 0, Failed checks: 0, Skipped checks: 0, Parsing errors: 1

dockerfile scan results:

Passed checks: 843, Failed checks: 15, Skipped checks: 0

Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /backend.Dockerfile.
	File: /backend.Dockerfile:1-73
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /backend.Dockerfile.
	File: /backend.Dockerfile:1-73
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /frontend.Dockerfile.
	File: /frontend.Dockerfile:1-34
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | # ── Build stage ──────────────────────────────────────────────────────────────
		2  | FROM node:20-alpine AS builder
		3  | 
		4  | WORKDIR /app
		5  | 
		6  | COPY apps/frontend/package.json apps/frontend/package-lock.json* ./
		7  | # BuildKit cache mount keeps node_modules cache between builds (avoids re-downloading ~986 packages).
		8  | RUN --mount=type=cache,target=/root/.npm \
		9  |     npm ci
		10 | 
		11 | # VERSION must land at /VERSION (one level above WORKDIR /app) so the
		12 | # syncversion script's readFileSync('../VERSION') resolves correctly.
		13 | COPY VERSION /VERSION
		14 | COPY apps/frontend/ ./
		15 | 
		16 | RUN npm run build
		17 | 
		18 | # ── Serve stage ──────────────────────────────────────────────────────────────
		19 | # Use the official unprivileged nginx image — binds on 8080, no root required
		20 | FROM nginxinc/nginx-unprivileged:1.27-alpine
		21 | 
		22 | # Create the breaker26 user that matches the rest of the stack
		23 | USER root
		24 | RUN addgroup -S breaker26 && adduser -S -G breaker26 -H -s /sbin/nologin breaker26
		25 | 
		26 | COPY --from=builder /app/dist /usr/share/nginx/html
		27 | COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
		28 | RUN chown -R breaker26:breaker26 /usr/share/nginx/html
		29 | 
		30 | USER breaker26
		31 | 
		32 | EXPOSE 8080
		33 | 
		34 | CMD ["nginx", "-g", "daemon off;"]
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /Dockerfile.prod.
	File: /Dockerfile.prod:1-17
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | FROM python:3.12-alpine AS backend
		2  | WORKDIR /app
		3  | COPY apps/backend/src ./src
		4  | COPY apps/backend/requirements.txt ./
		5  | RUN pip install -r requirements.txt
		6  | 
		7  | FROM node:20-alpine AS frontend
		8  | WORKDIR /app
		9  | COPY apps/frontend ./
		10 | RUN npm ci --prod && npm run build
		11 | 
		12 | FROM python:3.12-alpine
		13 | WORKDIR /app
		14 | COPY --from=backend /app /app
		15 | COPY --from=frontend /app/dist /app/static
		16 | EXPOSE 8080
		17 | CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.prod.
	File: /Dockerfile.prod:1-17
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		1  | FROM python:3.12-alpine AS backend
		2  | WORKDIR /app
		3  | COPY apps/backend/src ./src
		4  | COPY apps/backend/requirements.txt ./
		5  | RUN pip install -r requirements.txt
		6  | 
		7  | FROM node:20-alpine AS frontend
		8  | WORKDIR /app
		9  | COPY apps/frontend ./
		10 | RUN npm ci --prod && npm run build
		11 | 
		12 | FROM python:3.12-alpine
		13 | WORKDIR /app
		14 | COPY --from=backend /app /app
		15 | COPY --from=frontend /app/dist /app/static
		16 | EXPOSE 8080
		17 | CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /Dockerfile.native.
	File: /Dockerfile.native:1-48
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | FROM ubuntu:22.04
		6  | 
		7  | ENV DEBIAN_FRONTEND=noninteractive
		8  | 
		9  | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		10 | RUN apt-get update && apt-get install -y --no-install-recommends \
		11 |     ca-certificates \
		12 |     curl \
		13 |     gnupg \
		14 |     software-properties-common \
		15 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		16 |     && mkdir -p /etc/apt/keyrings \
		17 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		18 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		19 |     && apt-get update \
		20 |     && apt-get install -y --no-install-recommends \
		21 |     python3.12 \
		22 |     python3.12-venv \
		23 |     libpython3.12 \
		24 |     nodejs \
		25 |     binutils \
		26 |     && rm -rf /var/lib/apt/lists/*
		27 | 
		28 | # Ensure python3.12 is the default; install pip for it
		29 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		30 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		31 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		32 | 
		33 | WORKDIR /build
		34 | 
		35 | # Copy repo (context is repo root)
		36 | COPY . .
		37 | 
		38 | # Install backend deps + PyInstaller
		39 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		40 | 
		41 | # Build frontend
		42 | RUN cd apps/frontend && npm ci && npm run build
		43 | 
		44 | # Build native package
		45 | RUN python3 scripts/build_native_release.py --clean
		46 | 
		47 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		48 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.native.
	File: /Dockerfile.native:1-48
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | FROM ubuntu:22.04
		6  | 
		7  | ENV DEBIAN_FRONTEND=noninteractive
		8  | 
		9  | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		10 | RUN apt-get update && apt-get install -y --no-install-recommends \
		11 |     ca-certificates \
		12 |     curl \
		13 |     gnupg \
		14 |     software-properties-common \
		15 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		16 |     && mkdir -p /etc/apt/keyrings \
		17 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		18 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		19 |     && apt-get update \
		20 |     && apt-get install -y --no-install-recommends \
		21 |     python3.12 \
		22 |     python3.12-venv \
		23 |     libpython3.12 \
		24 |     nodejs \
		25 |     binutils \
		26 |     && rm -rf /var/lib/apt/lists/*
		27 | 
		28 | # Ensure python3.12 is the default; install pip for it
		29 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		30 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		31 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		32 | 
		33 | WORKDIR /build
		34 | 
		35 | # Copy repo (context is repo root)
		36 | COPY . .
		37 | 
		38 | # Install backend deps + PyInstaller
		39 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		40 | 
		41 | # Build frontend
		42 | RUN cd apps/frontend && npm ci && npm run build
		43 | 
		44 | # Build native package
		45 | RUN python3 scripts/build_native_release.py --clean
		46 | 
		47 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		48 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /docker/Dockerfile.native.
	File: /docker/Dockerfile.native:1-48
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | FROM ubuntu:22.04
		6  | 
		7  | ENV DEBIAN_FRONTEND=noninteractive
		8  | 
		9  | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		10 | RUN apt-get update && apt-get install -y --no-install-recommends \
		11 |     ca-certificates \
		12 |     curl \
		13 |     gnupg \
		14 |     software-properties-common \
		15 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		16 |     && mkdir -p /etc/apt/keyrings \
		17 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		18 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		19 |     && apt-get update \
		20 |     && apt-get install -y --no-install-recommends \
		21 |     python3.12 \
		22 |     python3.12-venv \
		23 |     libpython3.12 \
		24 |     nodejs \
		25 |     binutils \
		26 |     && rm -rf /var/lib/apt/lists/*
		27 | 
		28 | # Ensure python3.12 is the default; install pip for it
		29 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		30 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		31 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		32 | 
		33 | WORKDIR /build
		34 | 
		35 | # Copy repo (context is repo root)
		36 | COPY . .
		37 | 
		38 | # Install backend deps + PyInstaller
		39 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		40 | 
		41 | # Build frontend
		42 | RUN cd apps/frontend && npm ci && npm run build
		43 | 
		44 | # Build native package
		45 | RUN python3 scripts/build_native_release.py --clean
		46 | 
		47 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		48 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /docker/Dockerfile.native.
	File: /docker/Dockerfile.native:1-48
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | FROM ubuntu:22.04
		6  | 
		7  | ENV DEBIAN_FRONTEND=noninteractive
		8  | 
		9  | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		10 | RUN apt-get update && apt-get install -y --no-install-recommends \
		11 |     ca-certificates \
		12 |     curl \
		13 |     gnupg \
		14 |     software-properties-common \
		15 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		16 |     && mkdir -p /etc/apt/keyrings \
		17 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		18 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		19 |     && apt-get update \
		20 |     && apt-get install -y --no-install-recommends \
		21 |     python3.12 \
		22 |     python3.12-venv \
		23 |     libpython3.12 \
		24 |     nodejs \
		25 |     binutils \
		26 |     && rm -rf /var/lib/apt/lists/*
		27 | 
		28 | # Ensure python3.12 is the default; install pip for it
		29 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		30 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		31 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		32 | 
		33 | WORKDIR /build
		34 | 
		35 | # Copy repo (context is repo root)
		36 | COPY . .
		37 | 
		38 | # Install backend deps + PyInstaller
		39 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		40 | 
		41 | # Build frontend
		42 | RUN cd apps/frontend && npm ci && npm run build
		43 | 
		44 | # Build native package
		45 | RUN python3 scripts/build_native_release.py --clean
		46 | 
		47 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		48 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /docker/frontend.Dockerfile.
	File: /docker/frontend.Dockerfile:1-34
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | # ── Build stage ──────────────────────────────────────────────────────────────
		2  | FROM node:20-alpine AS builder
		3  | 
		4  | WORKDIR /app
		5  | 
		6  | COPY apps/frontend/package.json apps/frontend/package-lock.json* ./
		7  | # BuildKit cache mount keeps node_modules cache between builds (avoids re-downloading ~986 packages).
		8  | RUN --mount=type=cache,target=/root/.npm \
		9  |     npm ci
		10 | 
		11 | # VERSION must land at /VERSION (one level above WORKDIR /app) so the
		12 | # syncversion script's readFileSync('../VERSION') resolves correctly.
		13 | COPY VERSION /VERSION
		14 | COPY apps/frontend/ ./
		15 | 
		16 | RUN npm run build
		17 | 
		18 | # ── Serve stage ──────────────────────────────────────────────────────────────
		19 | # Use the official unprivileged nginx image — binds on 8080, no root required
		20 | FROM nginxinc/nginx-unprivileged:1.27-alpine
		21 | 
		22 | # Create the breaker26 user that matches the rest of the stack
		23 | USER root
		24 | RUN addgroup -S breaker26 && adduser -S -G breaker26 -H -s /sbin/nologin breaker26
		25 | 
		26 | COPY --from=builder /app/dist /usr/share/nginx/html
		27 | COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
		28 | RUN chown -R breaker26:breaker26 /usr/share/nginx/html
		29 | 
		30 | USER breaker26
		31 | 
		32 | EXPOSE 8080
		33 | 
		34 | CMD ["nginx", "-g", "daemon off;"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.
	File: /Dockerfile:1-111
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /docker/backend.Dockerfile.
	File: /docker/backend.Dockerfile:1-73
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /docker/backend.Dockerfile.
	File: /docker/backend.Dockerfile:1-73
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /docker/Dockerfile.prod.
	File: /docker/Dockerfile.prod:1-17
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | FROM python:3.12-alpine AS backend
		2  | WORKDIR /app
		3  | COPY apps/backend/src ./src
		4  | COPY apps/backend/requirements.txt ./
		5  | RUN pip install -r requirements.txt
		6  | 
		7  | FROM node:20-alpine AS frontend
		8  | WORKDIR /app
		9  | COPY apps/frontend ./
		10 | RUN npm ci --prod && npm run build
		11 | 
		12 | FROM python:3.12-alpine
		13 | WORKDIR /app
		14 | COPY --from=backend /app /app
		15 | COPY --from=frontend /app/dist /app/static
		16 | EXPOSE 8080
		17 | CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /docker/Dockerfile.prod.
	File: /docker/Dockerfile.prod:1-17
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		1  | FROM python:3.12-alpine AS backend
		2  | WORKDIR /app
		3  | COPY apps/backend/src ./src
		4  | COPY apps/backend/requirements.txt ./
		5  | RUN pip install -r requirements.txt
		6  | 
		7  | FROM node:20-alpine AS frontend
		8  | WORKDIR /app
		9  | COPY apps/frontend ./
		10 | RUN npm ci --prod && npm run build
		11 | 
		12 | FROM python:3.12-alpine
		13 | WORKDIR /app
		14 | COPY --from=backend /app /app
		15 | COPY --from=frontend /app/dist /app/static
		16 | EXPOSE 8080
		17 | CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
github_actions scan results:

Passed checks: 433, Failed checks: 2, Skipped checks: 0

Check: CKV_GHA_7: "The build output cannot be affected by user parameters other than the build entry point and the top-level source location. GitHub Actions workflow_dispatch inputs MUST be empty. "
	FAILED for resource: on(Docker Build & Publish)
	File: /.github/workflows/docker-build.yml:9-15

		9  |       tag:
		10 |         description: 'Image tag to push (e.g. v0.1.5)'
		11 |         required: false
		12 |         default: 'dev'
		13 | 
		14 | permissions:
		15 |   contents: read

Check: CKV2_GHA_1: "Ensure top-level permissions are not set to write-all"
	FAILED for resource: on(Block Tests in Prod Paths)
	File: /.github/workflows/block-tests.yml:0-1

```
## 7. Trivy (Filesystem)
```
2026-03-10T07:00:53Z	INFO	[vulndb] Need to update DB
2026-03-10T07:00:53Z	INFO	[vulndb] Downloading vulnerability DB...
2026-03-10T07:00:53Z	INFO	[vulndb] Downloading artifact...	repo="mirror.gcr.io/aquasec/trivy-db:2"
2026-03-10T07:01:00Z	INFO	[vulndb] Artifact successfully downloaded	repo="mirror.gcr.io/aquasec/trivy-db:2"
2026-03-10T07:01:00Z	INFO	[vuln] Vulnerability scanning is enabled
2026-03-10T07:01:00Z	INFO	[secret] Secret scanning is enabled
2026-03-10T07:01:00Z	INFO	[secret] If your scanning is slow, please try '--scanners vuln' to disable secret scanning
2026-03-10T07:01:00Z	INFO	[secret] Please see https://trivy.dev/docs/v0.69/guide/scanner/secret#recommendation for faster secret detection
2026-03-10T07:01:01Z	INFO	Received signal, attempting graceful shutdown...
2026-03-10T07:01:01Z	INFO	Press Ctrl+C again to force exit
```
## 8. Trivy (Config / IaC)
```
Scan config files for misconfigurations


2026-03-10T07:01:03Z	FATAL	Fatal error	unknown flag: --no-progress
Usage:
  trivy config [flags] DIR

Aliases:
  config, conf

Cache Flags
      --cache-backend string   [EXPERIMENTAL] cache backend (e.g. redis://localhost:6379) (default "memory")
      --cache-ttl duration     cache TTL when using redis as cache backend
      --redis-ca string        redis ca file location, if using redis as cache backend
      --redis-cert string      redis certificate file location, if using redis as cache backend
      --redis-key string       redis key file location, if using redis as cache backend
      --redis-tls              enable redis TLS with public certificates, if using redis as cache backend

Misconfiguration Flags
      --ansible-extra-vars strings        set additional variables as key=value or @file (YAML/JSON)
      --ansible-inventory strings         specify inventory host path or comma separated host list
      --ansible-playbook strings          specify playbook file path(s) to scan
      --cf-params strings                 specify paths to override the CloudFormation parameters files
      --checks-bundle-repository string   OCI registry URL to retrieve checks bundle from (default "mirror.gcr.io/aquasec/trivy-checks:2")
      --config-file-schemas strings       specify paths to JSON configuration file schemas to determine that a file matches some configuration and pass the schema to Rego checks for type checking
      --helm-api-versions strings         Available API versions used for Capabilities.APIVersions. This flag is the same as the api-versions flag of the helm template command. (can specify multiple or separate values with commas: policy/v1/PodDisruptionBudget,apps/v1/Deployment)
      --helm-kube-version string          Kubernetes version used for Capabilities.KubeVersion. This flag is the same as the kube-version flag of the helm template command.
      --helm-set strings                  specify Helm values on the command line (can specify multiple or separate values with commas: key1=val1,key2=val2)
      --helm-set-file strings             specify Helm values from respective files specified via the command line (can specify multiple or separate values with commas: key1=path1,key2=path2)
      --helm-set-string strings           specify Helm string values on the command line (can specify multiple or separate values with commas: key1=val1,key2=val2)
      --helm-values strings               specify paths to override the Helm values.yaml files
      --include-non-failures              include successes, available with '--scanners misconfig'
      --misconfig-scanners strings        comma-separated list of misconfig scanners to use for misconfiguration scanning (default [azure-arm,cloudformation,dockerfile,helm,kubernetes,terraform,terraformplan-json,terraformplan-snapshot,ansible])
      --raw-config-scanners strings       specify the types of scanners that will also scan raw configurations. For example, scanners will scan a non-adapted configuration into a shared state (allowed values: terraform)
      --render-cause strings              specify configuration types for which the rendered causes will be shown in the table report (allowed values: terraform,ansible)
      --tf-exclude-downloaded-modules     exclude misconfigurations for downloaded terraform modules
      --tf-vars strings                   specify paths to override the Terraform tfvars files

Module Flags
      --enable-modules strings   [EXPERIMENTAL] module names to enable
      --module-dir string        specify directory to the wasm modules that will be loaded (default "/root/.trivy/modules")

Registry Flags
      --password strings        password. Comma-separated passwords allowed. TRIVY_PASSWORD should be used for security reasons.
      --password-stdin          password from stdin. Comma-separated passwords are not supported.
      --registry-token string   registry token
      --username strings        username. Comma-separated usernames allowed.

Rego Flags
      --check-namespaces strings    Rego namespaces
      --config-check strings        specify the paths to the Rego check files or to the directories containing them, applying config files
      --config-data strings         specify paths from which data for the Rego checks will be recursively loaded
      --include-deprecated-checks   include deprecated checks
      --rego-error-limit int        maximum number of compile errors allowed during Rego policy evaluation (default 10)
      --skip-check-update           skip fetching rego check updates
      --trace-rego                  enable more verbose trace output for custom queries

Kubernetes Flags
      --k8s-version string   specify k8s version to validate outdated api by it (example: 1.21.0)

Report Flags
      --compliance string          compliance report to generate
      --exit-code int              specify exit code when any security issues are found
  -f, --format string              format
                                   Allowed values:
                                     - table
                                     - json
                                     - template
                                     - sarif
                                     - cyclonedx
                                     - spdx
                                     - spdx-json
                                     - github
                                     - cosign-vuln
                                    (default "table")
      --ignore-policy string       specify the Rego file path to evaluate each vulnerability
      --ignorefile string          specify .trivyignore file (default ".trivyignore")
  -o, --output string              output file name
      --output-plugin-arg string   [EXPERIMENTAL] output plugin arguments
      --report string              specify a compliance report format for the output (allowed values: all,summary) (default "all")
  -s, --severity strings           severities of security issues to be displayed
                                   Allowed values:
                                     - UNKNOWN
                                     - LOW
                                     - MEDIUM
                                     - HIGH
                                     - CRITICAL
                                    (default [UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL])
      --table-mode strings         [EXPERIMENTAL] tables that will be displayed in 'table' format (allowed values: summary,detailed) (default [summary,detailed])
  -t, --template string            output template

Scan Flags
      --disable-telemetry       disable sending anonymous usage data to Aqua
      --file-patterns strings   specify config file patterns
      --skip-dirs strings       specify the directories or glob patterns to skip
      --skip-files strings      specify the files or glob patterns to skip
      --skip-version-check      suppress notices about version updates and Trivy announcements

Global Flags:
      --cacert string             Path to PEM-encoded CA certificate file
      --cache-dir string          cache directory (default "/root/.cache/trivy")
  -c, --config string             config path (default "trivy.yaml")
  -d, --debug                     debug mode
      --generate-default-config   write the default config to trivy-default.yaml
      --insecure                  allow insecure server connections
  -q, --quiet                     suppress progress bar and log output
      --timeout duration          timeout (default 5m0s)
  -v, --version                   show version
```
## 9. npm audit (Frontend)
```
found 0 vulnerabilities
```
