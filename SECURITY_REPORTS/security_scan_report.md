# Security Scan Report - Tue Mar 10 01:27:32 AM MST 2026
## 1. Bandit (Python SAST)
```
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.14.3
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:01
Run started:2026-03-10 08:27:34.489785+00:00

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
   Location: apps/backend/src/app/api/branding.py:172:4
171	        data = buf.getvalue()
172	    except Exception:
173	        # If Pillow fails, save the raw upload — it's already validated by extension
174	        pass
175	

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
   Location: apps/backend/src/app/api/ws_status.py:53:4
52	            await ws.send_text(json.dumps({"type": "ping", "ts": utcnow_iso()}))
53	    except Exception:
54	        pass
55	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_status.py:74:8
73	            await websocket.close(code=1008)
74	        except Exception:
75	            pass
76	        return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_status.py:161:8
160	            await websocket.close(code=1011)
161	        except Exception:
162	            pass
163	

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
   Location: apps/backend/src/app/core/users.py:199:4
198	            db.close()
199	    except Exception:
200	        pass
201	

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:71:18
70	            text(
71	                f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM read_csv_auto(:path) LIMIT 0"
72	            )

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:75:19
74	        conn.execute(
75	            text(f"INSERT INTO {table} SELECT * FROM read_csv_auto(:path)"), {"path": path}
76	        )

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:77:40
76	        )
77	        row_count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0
78	        conn.commit()

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
   Location: apps/backend/src/app/services/monitor_service.py:14:0
13	import socket
14	import subprocess
15	import time

--------------------------------------------------
>> Issue: [B607:start_process_with_partial_path] Starting a process with a partial executable path
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b607_start_process_with_partial_path.html
   Location: apps/backend/src/app/services/monitor_service.py:52:12
51	        t0 = time.monotonic()
52	        r = subprocess.run(
53	            ["ping", "-c", "1", "-W", "1", ip],
54	            stdout=subprocess.DEVNULL,
55	            stderr=subprocess.DEVNULL,
56	            timeout=3,
57	        )
58	        latency = (time.monotonic() - t0) * 1000

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: apps/backend/src/app/services/monitor_service.py:52:12
51	        t0 = time.monotonic()
52	        r = subprocess.run(
53	            ["ping", "-c", "1", "-W", "1", ip],
54	            stdout=subprocess.DEVNULL,
55	            stderr=subprocess.DEVNULL,
56	            timeout=3,
57	        )
58	        latency = (time.monotonic() - t0) * 1000

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/monitor_service.py:113:8
112	                return True, round(latency, 2)
113	        except Exception:
114	            pass
115	    return False, None

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/monitor_service.py:150:4
149	            return True, round(latency, 2)
150	    except Exception:
151	        pass
152	    return False, None

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/monitor_service.py:218:8
217	            return [int(p) for p in ports]
218	        except Exception:
219	            pass
220	    return _TCP_FALLBACK_PORTS

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/monitor_service.py:238:4
237	        snmp_community = settings.discovery_snmp_community or None
238	    except Exception:
239	        pass
240	

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
	Total lines of code: 27503
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 0

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 80
		Medium: 7
		High: 1
	Total issues (by confidence):
		Undefined: 0
		Low: 3
		Medium: 9
		High: 76
Files skipped (0):
```
## 2. Semgrep (SAST)
```
               
               
┌─────────────┐
│ Scan Status │
└─────────────┘
  Scanning 376 files tracked by git with 1063 Code rules:
                                                                                                                        
  Language      Rules   Files          Origin      Rules                                                                
 ─────────────────────────────        ───────────────────                                                               
  <multilang>      58     251          Community    1063                                                                
  js              156     179                                                                                           
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
 • Targets scanned: 376
 • Parsed lines: ~99.9%
 • Scan was limited to files tracked by git
 • For a detailed list of skipped files and lines, run semgrep with the --verbose flag
Ran 507 rules on 376 files: 28 findings.

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
          Detected a python logger call with a potential hardcoded secret "Password reset token generated for
          %s (SMTP not configured); deliver token via alternate channel." being logged. This may lead to     
          secret credentials being exposed. Make sure that the logger is not logging  sensitive information. 
          Details: https://sg.run/ydNx                                                                       
                                                                                                             
          160┆ _logger.info(
          161┆     "Password reset token generated for %s (SMTP not configured); deliver token via
               alternate channel.",                                                               
          162┆     user.email,
          163┆ )
            ⋮┆----------------------------------------
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          Detected a python logger call with a potential hardcoded secret "Failed to send password reset email
          to %s: %s" being logged. This may lead to secret credentials being exposed. Make sure that the      
          logger is not logging  sensitive information.                                                       
          Details: https://sg.run/ydNx                                                                        
                                                                                                              
          165┆ _logger.warning("Failed to send password reset email to %s: %s", user.email, exc)
                                            
    apps/backend/src/app/db/duckdb_client.py
   ❯❯❱ python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
          sqlalchemy.text passes the constructed SQL statement to the database mostly unchanged. This means  
          that the usual SQL injection protections are not applied and this function is vulnerable to SQL    
          injection if user input can reach here. Use normal SQLAlchemy operators (such as `or_()`, `and_()`,
          etc.) to construct SQL.                                                                            
          Details: https://sg.run/yP1O                                                                       
                                                                                                             
           70┆ text(
           71┆     f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM read_csv_auto(:path) LIMIT 0"
           72┆ )
            ⋮┆----------------------------------------
           75┆ text(f"INSERT INTO {table} SELECT * FROM read_csv_auto(:path)"), {"path": path}
            ⋮┆----------------------------------------
           77┆ row_count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0
                                         
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
           76┆ ENTRYPOINT ["/entrypoint.sh"]
   
   ❯❯❱ dockerfile.security.missing-user.missing-user
          By not specifying a USER, a program in the container may run as 'root'. This is a security hazard.
          If an attacker can control a process running as root, they may have control over the container.   
          Ensure that the last USER in a Dockerfile is a USER other than 'root'.                            
          Details: https://sg.run/Gbvn                                                                      
                                                                                                            
           ▶▶┆ Autofix ▶ USER non-root CMD ["python", "src/app/start.py"]
           77┆ CMD ["python", "src/app/start.py"]
                     
    docker/nginx.conf
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           46┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           47┆ proxy_http_version 1.1;
           48┆ proxy_set_header   Upgrade    $http_upgrade;
           49┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           58┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           59┆ proxy_http_version 1.1;
           60┆ proxy_set_header   Upgrade    $http_upgrade;
           61┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           71┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           72┆ proxy_http_version 1.1;
           73┆ proxy_set_header   Upgrade    $http_upgrade;
           74┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           84┆ proxy_pass         $backend;
            ⋮┆----------------------------------------
           97┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          109┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          117┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          125┆ proxy_pass $backend;

```
## 3. Gitleaks (Secret Scanning)
```
```
## 4. ESLint + security (Frontend)
```

> circuit-breaker-ui@0.2.0 lint
> eslint .


/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/api/client.jsx
  106:11  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/CatalogSearch.jsx
  90:20  warning  Function Call Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/CommandPalette.jsx
  196:20  warning  Function Call Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/DocEditor.jsx
  393:16  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/Dock.jsx
   89:41  warning  Generic Object Injection Sink               security/detect-object-injection
   90:44  warning  Generic Object Injection Sink               security/detect-object-injection
  101:12  warning  Generic Object Injection Sink               security/detect-object-injection
  107:20  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
  212:13  warning  Generic Object Injection Sink               security/detect-object-injection
  222:36  warning  Generic Object Injection Sink               security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/EntityForm.jsx
  112:65  warning  Generic Object Injection Sink               security/detect-object-injection
  158:26  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
  196:22  warning  Generic Object Injection Sink               security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/Layout/Topbar.jsx
  17:17  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/TagsCell.jsx
  84:11  warning  Unsafe Regular Expression  security/detect-unsafe-regex

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/ThemePalette.jsx
  17:24  warning  Generic Object Injection Sink        security/detect-object-injection
  17:24  warning  Generic Object Injection Sink        security/detect-object-injection
  32:16  warning  Function Call Object Injection Sink  security/detect-object-injection
  46:15  warning  Generic Object Injection Sink        security/detect-object-injection
  51:16  warning  Generic Object Injection Sink        security/detect-object-injection
  52:21  warning  Generic Object Injection Sink        security/detect-object-injection
  64:31  warning  Generic Object Injection Sink        security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/common/IconPickerModal.jsx
  976:26  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/common/Toast.jsx
  16:9   warning  Generic Object Injection Sink        security/detect-object-injection
  17:20  warning  Function Call Object Injection Sink  security/detect-object-injection
  18:14  warning  Generic Object Injection Sink        security/detect-object-injection
  27:7   warning  Generic Object Injection Sink        security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/details/NetworkDetail.jsx
  124:10  warning  Generic Object Injection Sink               security/detect-object-injection
  124:29  warning  Generic Object Injection Sink               security/detect-object-injection
  125:5   warning  Generic Object Injection Sink               security/detect-object-injection
  195:26  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/details/PortEditor.jsx
  203:7   warning  Generic Object Injection Sink  security/detect-object-injection
  203:45  warning  Generic Object Injection Sink  security/detect-object-injection
  204:8   warning  Generic Object Injection Sink  security/detect-object-injection
  205:8   warning  Generic Object Injection Sink  security/detect-object-injection
  249:35  warning  Generic Object Injection Sink  security/detect-object-injection
  252:53  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/details/VulnerabilityPanel.jsx
  13:17  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/discovery/BulkActionsDrawer.jsx
  208:13  warning  Generic Object Injection Sink  security/detect-object-injection
  257:24  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/discovery/ConflictResolver.jsx
  26:11  warning  Generic Object Injection Sink  security/detect-object-injection
  27:9   warning  Generic Object Injection Sink  security/detect-object-injection
  69:30  warning  Generic Object Injection Sink  security/detect-object-injection
  75:25  warning  Generic Object Injection Sink  security/detect-object-injection
  90:30  warning  Generic Object Injection Sink  security/detect-object-injection
  96:25  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/discovery/DiscoverySidebar.jsx
  31:25  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/discovery/JobStatusBadge.jsx
  65:15  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/discovery/LiveListenersPanel.jsx
  10:17  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/discovery/ReviewQueuePanel.jsx
  236:21  warning  Generic Object Injection Sink  security/detect-object-injection
  237:19  warning  Generic Object Injection Sink  security/detect-object-injection
  286:52  warning  Generic Object Injection Sink  security/detect-object-injection
  396:14  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/discovery/ScanDetailPanel.jsx
  33:17  warning  Generic Object Injection Sink  security/detect-object-injection
  55:17  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/discovery/ScanProfileForm.jsx
  12:17  warning  Unsafe Regular Expression  security/detect-unsafe-regex

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/discovery/ScanProfilesPanel.jsx
  23:15  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/map/ConnectionTypePicker.jsx
  46:22  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/map/CustomEdge.jsx
  75:33  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/map/CustomNode.jsx
  151:33  warning  Generic Object Injection Sink  security/detect-object-injection
  247:52  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/map/DrawToolsDropdown.jsx
  194:30  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/map/VisualLineContextMenu.jsx
  61:26  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/map/connectionTypes.js
  25:22  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/map/linkMutations.js
  507:12  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/map/mapConstants.js
   57:10  warning  Generic Object Injection Sink        security/detect-object-injection
  150:30  warning  Generic Object Injection Sink        security/detect-object-injection
  151:25  warning  Function Call Object Injection Sink  security/detect-object-injection
  158:15  warning  Generic Object Injection Sink        security/detect-object-injection
  159:25  warning  Function Call Object Injection Sink  security/detect-object-injection
  337:17  warning  Generic Object Injection Sink        security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/proxmox/ProxmoxIntegrationSection.jsx
  12:13  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/settings/BrandingSettings.jsx
  381:20  warning  Generic Object Injection Sink  security/detect-object-injection
  384:15  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/settings/DockSettings.jsx
  48:41  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/settings/IconLibraryManager.jsx
  258:5   warning  Generic Object Injection Sink               security/detect-object-injection
  263:9   warning  Generic Object Injection Sink               security/detect-object-injection
  264:7   warning  Generic Object Injection Sink               security/detect-object-injection
  264:33  warning  Generic Object Injection Sink               security/detect-object-injection
  271:10  warning  Generic Object Injection Sink               security/detect-object-injection
  271:27  warning  Generic Object Injection Sink               security/detect-object-injection
  272:5   warning  Generic Object Injection Sink               security/detect-object-injection
  324:27  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/settings/NotificationsManager.jsx
   17:10  warning  Generic Object Injection Sink  security/detect-object-injection
   42:23  warning  Generic Object Injection Sink  security/detect-object-injection
  377:20  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/settings/ThemeSettings.jsx
  218:52  warning  Function Call Object Injection Sink  security/detect-object-injection
  233:11  warning  Generic Object Injection Sink        security/detect-object-injection
  243:16  warning  Function Call Object Injection Sink  security/detect-object-injection
  280:44  warning  Generic Object Injection Sink        security/detect-object-injection
  310:16  warning  Function Call Object Injection Sink  security/detect-object-injection
  334:49  warning  Generic Object Injection Sink        security/detect-object-injection
  348:32  warning  Generic Object Injection Sink        security/detect-object-injection
  350:31  warning  Generic Object Injection Sink        security/detect-object-injection
  351:31  warning  Generic Object Injection Sink        security/detect-object-injection
  352:31  warning  Generic Object Injection Sink        security/detect-object-injection
  353:31  warning  Generic Object Injection Sink        security/detect-object-injection
  400:20  warning  Generic Object Injection Sink        security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/settings/WebhooksManager.jsx
  211:78  warning  Generic Object Injection Sink  security/detect-object-injection
  321:28  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/context/SettingsContext.jsx
  14:52  warning  Generic Object Injection Sink        security/detect-object-injection
  15:14  warning  Function Call Object Injection Sink  security/detect-object-injection
  82:42  warning  Generic Object Injection Sink        security/detect-object-injection
  83:16  warning  Generic Object Injection Sink        security/detect-object-injection
  98:16  warning  Generic Object Injection Sink        security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/hooks/useMapDataLoad.js
  85:23  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/icons/vendorIcons.js
  42:10  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/AdminUsersPage.jsx
  37:24  warning  Generic Object Injection Sink  security/detect-object-injection
  38:16  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/ComputeUnitsPage.jsx
   54:21  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
  217:9   warning  Generic Object Injection Sink               security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/DiscoveryHistoryPage.jsx
   37:17  warning  Generic Object Injection Sink               security/detect-object-injection
  142:12  warning  Generic Object Injection Sink               security/detect-object-injection
  153:24  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/DiscoveryPage.jsx
  163:9   warning  Generic Object Injection Sink               security/detect-object-injection
  250:23  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
  333:38  warning  Generic Object Injection Sink               security/detect-object-injection
  334:37  warning  Generic Object Injection Sink               security/detect-object-injection
  335:37  warning  Generic Object Injection Sink               security/detect-object-injection
  336:39  warning  Generic Object Injection Sink               security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/DocsPage.jsx
  155:10  warning  Generic Object Injection Sink  security/detect-object-injection
  513:12  warning  Generic Object Injection Sink  security/detect-object-injection
  513:25  warning  Generic Object Injection Sink  security/detect-object-injection
  514:7   warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/HardwarePage.jsx
   23:48  warning  Generic Object Injection Sink               security/detect-object-injection
   73:21  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
  415:9   warning  Generic Object Injection Sink               security/detect-object-injection
  417:9   warning  Generic Object Injection Sink               security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/InviteAcceptPage.jsx
  29:5  warning  Potential timing attack, left side: true  security/detect-possible-timing-attacks

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/LogsPage.jsx
   113:7   warning  Generic Object Injection Sink               security/detect-object-injection
   113:36  warning  Generic Object Injection Sink               security/detect-object-injection
   115:10  warning  Generic Object Injection Sink               security/detect-object-injection
   242:46  warning  Generic Object Injection Sink               security/detect-object-injection
   242:78  warning  Generic Object Injection Sink               security/detect-object-injection
   329:65  warning  Generic Object Injection Sink               security/detect-object-injection
   330:65  warning  Generic Object Injection Sink               security/detect-object-injection
  1235:27  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/MapPage.jsx
   581:23  warning  Generic Object Injection Sink               security/detect-object-injection
   894:23  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
   895:23  warning  Generic Object Injection Sink               security/detect-object-injection
  1074:12  warning  Generic Object Injection Sink               security/detect-object-injection
  1089:12  warning  Generic Object Injection Sink               security/detect-object-injection
  1091:14  warning  Generic Object Injection Sink               security/detect-object-injection
  2055:24  warning  Generic Object Injection Sink               security/detect-object-injection
  2075:31  warning  Generic Object Injection Sink               security/detect-object-injection
  2076:16  warning  Generic Object Injection Sink               security/detect-object-injection
  2085:26  warning  Generic Object Injection Sink               security/detect-object-injection
  2123:24  warning  Generic Object Injection Sink               security/detect-object-injection
  2135:29  warning  Generic Object Injection Sink               security/detect-object-injection
  2444:31  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
  2448:83  warning  Generic Object Injection Sink               security/detect-object-injection
  2453:35  warning  Generic Object Injection Sink               security/detect-object-injection
  2454:30  warning  Generic Object Injection Sink               security/detect-object-injection
  2460:22  warning  Generic Object Injection Sink               security/detect-object-injection
  3233:42  warning  Generic Object Injection Sink               security/detect-object-injection
  3246:28  warning  Generic Object Injection Sink               security/detect-object-injection
  3464:35  warning  Generic Object Injection Sink               security/detect-object-injection
  3486:38  warning  Generic Object Injection Sink               security/detect-object-injection
  3764:34  warning  Generic Object Injection Sink               security/detect-object-injection
  3926:43  warning  Generic Object Injection Sink               security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/NetworksPage.jsx
  133:36  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/OOBEWizardPage.jsx
   188:16  warning  Function Call Object Injection Sink  security/detect-object-injection
   529:11  warning  Generic Object Injection Sink        security/detect-object-injection
   530:20  warning  Function Call Object Injection Sink  security/detect-object-injection
   595:16  warning  Function Call Object Injection Sink  security/detect-object-injection
   601:16  warning  Function Call Object Injection Sink  security/detect-object-injection
  1045:32  warning  Generic Object Injection Sink        security/detect-object-injection
  1163:48  warning  Generic Object Injection Sink        security/detect-object-injection
  1360:23  warning  Generic Object Injection Sink        security/detect-object-injection
  1360:23  warning  Generic Object Injection Sink        security/detect-object-injection
  1360:66  warning  Generic Object Injection Sink        security/detect-object-injection
  1368:60  warning  Generic Object Injection Sink        security/detect-object-injection
  1882:48  warning  Generic Object Injection Sink        security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/ResetPasswordPage.jsx
  88:5  warning  Potential timing attack, left side: true  security/detect-possible-timing-attacks

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/SettingsPage.jsx
  459:21  warning  Generic Object Injection Sink  security/detect-object-injection
  460:36  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/StoragePage.jsx
  108:9  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/utils/layouts.js
   96:21  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
  206:10  warning  Generic Object Injection Sink               security/detect-object-injection
  206:28  warning  Generic Object Injection Sink               security/detect-object-injection
  207:5   warning  Generic Object Injection Sink               security/detect-object-injection
  212:19  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
  218:56  warning  Generic Object Injection Sink               security/detect-object-injection
  259:16  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
  343:7   warning  Generic Object Injection Sink               security/detect-object-injection
  375:10  warning  Generic Object Injection Sink               security/detect-object-injection
  375:22  warning  Generic Object Injection Sink               security/detect-object-injection
  376:5   warning  Generic Object Injection Sink               security/detect-object-injection
  382:5   warning  Generic Object Injection Sink               security/detect-object-injection
  429:10  warning  Generic Object Injection Sink               security/detect-object-injection
  429:23  warning  Generic Object Injection Sink               security/detect-object-injection
  430:5   warning  Generic Object Injection Sink               security/detect-object-injection
  435:19  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection
  438:20  warning  Generic Object Injection Sink               security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/utils/mapDataUtils.js
  71:18  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/utils/mapGeometryUtils.js
  141:19  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/utils/md5.js
   49:24  warning  Generic Object Injection Sink        security/detect-object-injection
   77:27  warning  Function Call Object Injection Sink  security/detect-object-injection
   96:27  warning  Function Call Object Injection Sink  security/detect-object-injection
  118:27  warning  Function Call Object Injection Sink  security/detect-object-injection
  125:27  warning  Function Call Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/vite.config.ts
  12:21  warning  Found readFileSync from package "node:fs" with non literal argument at index 0  security/detect-non-literal-fs-filename

✖ 202 problems (0 errors, 202 warnings)

```
## 5. Hadolint (Dockerfile lint)
```
Hadolint skipped (binary/docker not found).
```
## 6. Checkov (IaC)
```
dockerfile scan results:

Passed checks: 352, Failed checks: 3, Skipped checks: 0

Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /backend.Dockerfile.
	File: /backend.Dockerfile:1-77
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /Dockerfile.native.
	File: /Dockerfile.native:1-49
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | # Build-only image: no USER or HEALTHCHECK (not a long-running service).
		6  | FROM ubuntu:22.04
		7  | 
		8  | ENV DEBIAN_FRONTEND=noninteractive
		9  | 
		10 | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		11 | RUN apt-get update && apt-get install -y --no-install-recommends \
		12 |     ca-certificates \
		13 |     curl \
		14 |     gnupg \
		15 |     software-properties-common \
		16 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		17 |     && mkdir -p /etc/apt/keyrings \
		18 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		19 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		20 |     && apt-get update \
		21 |     && apt-get install -y --no-install-recommends \
		22 |     python3.12 \
		23 |     python3.12-venv \
		24 |     libpython3.12 \
		25 |     nodejs \
		26 |     binutils \
		27 |     && rm -rf /var/lib/apt/lists/*
		28 | 
		29 | # Ensure python3.12 is the default; install pip for it
		30 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		31 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		32 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		33 | 
		34 | WORKDIR /build
		35 | 
		36 | # Copy repo (context is repo root)
		37 | COPY . .
		38 | 
		39 | # Install backend deps + PyInstaller
		40 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		41 | 
		42 | # Build frontend
		43 | RUN cd apps/frontend && npm ci && npm run build
		44 | 
		45 | # Build native package
		46 | RUN python3 scripts/build_native_release.py --clean
		47 | 
		48 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		49 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.native.
	File: /Dockerfile.native:1-49
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | # Build-only image: no USER or HEALTHCHECK (not a long-running service).
		6  | FROM ubuntu:22.04
		7  | 
		8  | ENV DEBIAN_FRONTEND=noninteractive
		9  | 
		10 | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		11 | RUN apt-get update && apt-get install -y --no-install-recommends \
		12 |     ca-certificates \
		13 |     curl \
		14 |     gnupg \
		15 |     software-properties-common \
		16 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		17 |     && mkdir -p /etc/apt/keyrings \
		18 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		19 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		20 |     && apt-get update \
		21 |     && apt-get install -y --no-install-recommends \
		22 |     python3.12 \
		23 |     python3.12-venv \
		24 |     libpython3.12 \
		25 |     nodejs \
		26 |     binutils \
		27 |     && rm -rf /var/lib/apt/lists/*
		28 | 
		29 | # Ensure python3.12 is the default; install pip for it
		30 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		31 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		32 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		33 | 
		34 | WORKDIR /build
		35 | 
		36 | # Copy repo (context is repo root)
		37 | COPY . .
		38 | 
		39 | # Install backend deps + PyInstaller
		40 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		41 | 
		42 | # Build frontend
		43 | RUN cd apps/frontend && npm ci && npm run build
		44 | 
		45 | # Build native package
		46 | RUN python3 scripts/build_native_release.py --clean
		47 | 
		48 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		49 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]

2026-03-10 01:28:02,848 [MainThread  ] [ERROR]  YAML error parsing ./site/search/search_index.json: while parsing a quoted scalar
  in "<unicode string>", line 1, column 104579
found invalid Unicode character escape code
  in "<unicode string>", line 1, column 107748
cloudformation scan results:

Passed checks: 0, Failed checks: 0, Skipped checks: 0, Parsing errors: 1

dockerfile scan results:

Passed checks: 887, Failed checks: 7, Skipped checks: 0

Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /backend.Dockerfile.
	File: /backend.Dockerfile:1-77
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /Dockerfile.native.
	File: /Dockerfile.native:1-49
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | # Build-only image: no USER or HEALTHCHECK (not a long-running service).
		6  | FROM ubuntu:22.04
		7  | 
		8  | ENV DEBIAN_FRONTEND=noninteractive
		9  | 
		10 | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		11 | RUN apt-get update && apt-get install -y --no-install-recommends \
		12 |     ca-certificates \
		13 |     curl \
		14 |     gnupg \
		15 |     software-properties-common \
		16 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		17 |     && mkdir -p /etc/apt/keyrings \
		18 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		19 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		20 |     && apt-get update \
		21 |     && apt-get install -y --no-install-recommends \
		22 |     python3.12 \
		23 |     python3.12-venv \
		24 |     libpython3.12 \
		25 |     nodejs \
		26 |     binutils \
		27 |     && rm -rf /var/lib/apt/lists/*
		28 | 
		29 | # Ensure python3.12 is the default; install pip for it
		30 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		31 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		32 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		33 | 
		34 | WORKDIR /build
		35 | 
		36 | # Copy repo (context is repo root)
		37 | COPY . .
		38 | 
		39 | # Install backend deps + PyInstaller
		40 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		41 | 
		42 | # Build frontend
		43 | RUN cd apps/frontend && npm ci && npm run build
		44 | 
		45 | # Build native package
		46 | RUN python3 scripts/build_native_release.py --clean
		47 | 
		48 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		49 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.native.
	File: /Dockerfile.native:1-49
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | # Build-only image: no USER or HEALTHCHECK (not a long-running service).
		6  | FROM ubuntu:22.04
		7  | 
		8  | ENV DEBIAN_FRONTEND=noninteractive
		9  | 
		10 | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		11 | RUN apt-get update && apt-get install -y --no-install-recommends \
		12 |     ca-certificates \
		13 |     curl \
		14 |     gnupg \
		15 |     software-properties-common \
		16 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		17 |     && mkdir -p /etc/apt/keyrings \
		18 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		19 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		20 |     && apt-get update \
		21 |     && apt-get install -y --no-install-recommends \
		22 |     python3.12 \
		23 |     python3.12-venv \
		24 |     libpython3.12 \
		25 |     nodejs \
		26 |     binutils \
		27 |     && rm -rf /var/lib/apt/lists/*
		28 | 
		29 | # Ensure python3.12 is the default; install pip for it
		30 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		31 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		32 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		33 | 
		34 | WORKDIR /build
		35 | 
		36 | # Copy repo (context is repo root)
		37 | COPY . .
		38 | 
		39 | # Install backend deps + PyInstaller
		40 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		41 | 
		42 | # Build frontend
		43 | RUN cd apps/frontend && npm ci && npm run build
		44 | 
		45 | # Build native package
		46 | RUN python3 scripts/build_native_release.py --clean
		47 | 
		48 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		49 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /docker/backend.Dockerfile.
	File: /docker/backend.Dockerfile:1-77
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.
	File: /Dockerfile:1-111
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
Check: CKV_DOCKER_2: "Ensure that HEALTHCHECK instructions have been added to container images"
	FAILED for resource: /docker/Dockerfile.native.
	File: /docker/Dockerfile.native:1-49
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-healthcheck-instructions-have-been-added-to-container-images

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | # Build-only image: no USER or HEALTHCHECK (not a long-running service).
		6  | FROM ubuntu:22.04
		7  | 
		8  | ENV DEBIAN_FRONTEND=noninteractive
		9  | 
		10 | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		11 | RUN apt-get update && apt-get install -y --no-install-recommends \
		12 |     ca-certificates \
		13 |     curl \
		14 |     gnupg \
		15 |     software-properties-common \
		16 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		17 |     && mkdir -p /etc/apt/keyrings \
		18 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		19 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		20 |     && apt-get update \
		21 |     && apt-get install -y --no-install-recommends \
		22 |     python3.12 \
		23 |     python3.12-venv \
		24 |     libpython3.12 \
		25 |     nodejs \
		26 |     binutils \
		27 |     && rm -rf /var/lib/apt/lists/*
		28 | 
		29 | # Ensure python3.12 is the default; install pip for it
		30 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		31 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		32 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		33 | 
		34 | WORKDIR /build
		35 | 
		36 | # Copy repo (context is repo root)
		37 | COPY . .
		38 | 
		39 | # Install backend deps + PyInstaller
		40 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		41 | 
		42 | # Build frontend
		43 | RUN cd apps/frontend && npm ci && npm run build
		44 | 
		45 | # Build native package
		46 | RUN python3 scripts/build_native_release.py --clean
		47 | 
		48 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		49 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]
Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /docker/Dockerfile.native.
	File: /docker/Dockerfile.native:1-49
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		1  | # Native binary build with older glibc for compatibility with older Linux distros.
		2  | # Built on Fedora 43 / Ubuntu 24.04 links against GLIBC_ABI_GNU2_TLS (glibc 2.42+),
		3  | # which older systems (Debian 11, Ubuntu 20.04) lack. This image uses Ubuntu 22.04
		4  | # (glibc 2.35) so the resulting binary runs on Ubuntu 22.04+ and most older systems.
		5  | # Build-only image: no USER or HEALTHCHECK (not a long-running service).
		6  | FROM ubuntu:22.04
		7  | 
		8  | ENV DEBIAN_FRONTEND=noninteractive
		9  | 
		10 | # Add deadsnakes PPA for Python 3.12; NodeSource for Node 20 (Vite needs Node 18+)
		11 | RUN apt-get update && apt-get install -y --no-install-recommends \
		12 |     ca-certificates \
		13 |     curl \
		14 |     gnupg \
		15 |     software-properties-common \
		16 |     && add-apt-repository ppa:deadsnakes/ppa -y \
		17 |     && mkdir -p /etc/apt/keyrings \
		18 |     && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
		19 |     && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
		20 |     && apt-get update \
		21 |     && apt-get install -y --no-install-recommends \
		22 |     python3.12 \
		23 |     python3.12-venv \
		24 |     libpython3.12 \
		25 |     nodejs \
		26 |     binutils \
		27 |     && rm -rf /var/lib/apt/lists/*
		28 | 
		29 | # Ensure python3.12 is the default; install pip for it
		30 | RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 - \
		31 |     && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
		32 |     && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1
		33 | 
		34 | WORKDIR /build
		35 | 
		36 | # Copy repo (context is repo root)
		37 | COPY . .
		38 | 
		39 | # Install backend deps + PyInstaller
		40 | RUN pip install --no-cache-dir -e "./apps/backend[dev]" pyinstaller
		41 | 
		42 | # Build frontend
		43 | RUN cd apps/frontend && npm ci && npm run build
		44 | 
		45 | # Build native package
		46 | RUN python3 scripts/build_native_release.py --clean
		47 | 
		48 | # When run with -v $(pwd)/dist/native:/out, copy built artifacts to host
		49 | CMD ["sh", "-c", "cp -av dist/native/. /out/ && ls -la /out"]
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
2026-03-10T08:28:06Z	INFO	[vulndb] Need to update DB
2026-03-10T08:28:06Z	INFO	[vulndb] Downloading vulnerability DB...
2026-03-10T08:28:06Z	INFO	[vulndb] Downloading artifact...	repo="mirror.gcr.io/aquasec/trivy-db:2"
2026-03-10T08:28:13Z	INFO	[vulndb] Artifact successfully downloaded	repo="mirror.gcr.io/aquasec/trivy-db:2"
2026-03-10T08:28:13Z	INFO	[vuln] Vulnerability scanning is enabled
2026-03-10T08:28:13Z	INFO	[secret] Secret scanning is enabled
2026-03-10T08:28:13Z	INFO	[secret] If your scanning is slow, please try '--scanners vuln' to disable secret scanning
2026-03-10T08:28:13Z	INFO	[secret] Please see https://trivy.dev/docs/v0.69/guide/scanner/secret#recommendation for faster secret detection
2026-03-10T08:28:20Z	WARN	[secret] Invalid UTF-8 sequences detected in file content, replacing with empty string
2026-03-10T08:28:25Z	WARN	[secret] The size of the scanned file is too large. It is recommended to use `--skip-files` for this file to avoid high memory consumption.	file_path=".venv/lib/python3.14/site-packages/policy_sentry/shared/data/iam-definition.json" size (MB)=10
2026-03-10T08:28:40Z	WARN	[secret] The size of the scanned file is too large. It is recommended to use `--skip-files` for this file to avoid high memory consumption.	file_path="apps/frontend/dist/assets/StatusPage-CS9qZ0nK.js.map" size (MB)=19
2026-03-10T08:28:43Z	INFO	[npm] To collect the license information of packages, "npm install" needs to be performed beforehand	dir="proxmox-cluster-dashboard/node_modules"
2026-03-10T08:28:43Z	WARN	[pip] Unable to find python `site-packages` directory. License detection is skipped.	err="unable to find path to Python executable"
2026-03-10T08:28:43Z	INFO	Suppressing dependencies for development and testing. To display them, try the '--include-dev-deps' flag.
2026-03-10T08:28:43Z	INFO	Number of language-specific files	num=5
2026-03-10T08:28:43Z	INFO	[npm] Detecting vulnerabilities...
2026-03-10T08:28:43Z	INFO	[pip] Detecting vulnerabilities...
2026-03-10T08:28:43Z	INFO	[poetry] Detecting vulnerabilities...

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
## 8. Trivy (Config / IaC)
```
Scan config files for misconfigurations


2026-03-10T08:28:44Z	FATAL	Fatal error	unknown flag: --no-progress
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
