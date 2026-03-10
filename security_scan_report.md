# Security Scan Report - Tue Mar 10 07:51:28 AM MST 2026
## 1. Bandit (Python SAST)
```
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.14.3
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:01
Run started:2026-03-10 14:51:30.352324+00:00

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
>> Issue: [B311:blacklist] Standard pseudo-random generators are not suitable for security/cryptographic purposes.
   Severity: Low   Confidence: High
   CWE: CWE-330 (https://cwe.mitre.org/data/definitions/330.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_calls.html#b311-random
   Location: apps/backend/src/app/core/retry.py:36:44
35	                base_delay = base_delay_s * (2**attempt)
36	                delay = base_delay * (0.5 + random.random() * 0.5)
37	                _logger.debug(

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
   Location: apps/backend/src/app/core/users.py:203:4
202	            db.close()
203	    except Exception:
204	        pass
205	

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:72:18
71	            text(
72	                f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM read_csv_auto(:path) LIMIT 0"
73	            )

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:76:19
75	        conn.execute(
76	            text(f"INSERT INTO {table} SELECT * FROM read_csv_auto(:path)"), {"path": path}
77	        )

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:78:40
77	        )
78	        row_count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0
79	        conn.commit()

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
   Location: apps/backend/src/app/services/vault_service.py:281:4
280	        )
281	    except Exception:  # noqa: BLE001
282	        pass
283	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:330:4
329	        )
330	    except Exception:  # noqa: BLE001
331	        pass
332	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:347:4
346	            count += 1
347	    except Exception:  # noqa: BLE001
348	        pass
349	    try:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:355:4
354	        )
355	    except Exception:  # noqa: BLE001
356	        pass
357	    try:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:359:4
358	        count += db.query(Credential).count()
359	    except Exception:  # noqa: BLE001
360	        pass
361	    return count

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:375:4
374	            return "healthy" if _sha256(current_key) == cfg.vault_key_hash else "degraded"
375	    except Exception:  # noqa: BLE001
376	        pass
377	    return "healthy"

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/vault_service.py:389:4
388	            last_rotated = cfg.vault_key_rotated_at.isoformat()
389	    except Exception:  # noqa: BLE001
390	        pass
391	

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
	Total lines of code: 27635
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
  Scanning 386 files tracked by git with 1063 Code rules:
                                                                                                                        
  Language      Rules   Files          Origin      Rules                                                                
 ─────────────────────────────        ───────────────────                                                               
  <multilang>      58     258          Community    1063                                                                
  js              156     179                                                                                           
  python          243     165                                                                                           
  yaml             31       6                                                                                           
  bash              4       6                                                                                           
  dockerfile        6       2                                                                                           
  json              4       2                                                                                           
  ts              166       1                                                                                           
                                                                                                                        
                
                
┌──────────────┐
│ Scan Summary │
└──────────────┘
✅ Scan completed successfully.
 • Findings: 42 (42 blocking)
 • Rules run: 507
 • Targets scanned: 386
 • Parsed lines: ~99.9%
 • Scan was limited to files tracked by git
 • For a detailed list of skipped files and lines, run semgrep with the --verbose flag
Ran 507 rules on 386 files: 42 findings.

A new version of Semgrep is available. See https://semgrep.dev/docs/upgrading

📢 Too many findings? Try Semgrep Pro for more powerful queries and less noise.
   See https://sg.run/false-positives.
                    
                    
┌──────────────────┐
│ 42 Code Findings │
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
          to %s (reason: %s)" being logged. This may lead to secret credentials being exposed. Make sure that 
          the logger is not logging  sensitive information.                                                   
          Details: https://sg.run/ydNx                                                                        
                                                                                                              
          165┆ _logger.warning(
          166┆     "Failed to send password reset email to %s (reason: %s)",
          167┆     user.email,
          168┆     type(exc).__name__,
          169┆ )
                                            
    apps/backend/src/app/db/duckdb_client.py
   ❯❯❱ python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
          sqlalchemy.text passes the constructed SQL statement to the database mostly unchanged. This means  
          that the usual SQL injection protections are not applied and this function is vulnerable to SQL    
          injection if user input can reach here. Use normal SQLAlchemy operators (such as `or_()`, `and_()`,
          etc.) to construct SQL.                                                                            
          Details: https://sg.run/yP1O                                                                       
                                                                                                             
           71┆ text(
           72┆     f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM read_csv_auto(:path) LIMIT 0"
           73┆ )
            ⋮┆----------------------------------------
           76┆ text(f"INSERT INTO {table} SELECT * FROM read_csv_auto(:path)"), {"path": path}
            ⋮┆----------------------------------------
           78┆ row_count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0
                                         
    apps/backend/src/app/db/migrations.py
   ❯❯❱ python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
          sqlalchemy.text passes the constructed SQL statement to the database mostly unchanged. This means  
          that the usual SQL injection protections are not applied and this function is vulnerable to SQL    
          injection if user input can reach here. Use normal SQLAlchemy operators (such as `or_()`, `and_()`,
          etc.) to construct SQL.                                                                            
          Details: https://sg.run/yP1O                                                                       
                                                                                                             
           72┆ text(f"PRAGMA table_info({table_name})")
                                                     
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
          during rotation (reason: %s)" being logged. This may lead to secret credentials being exposed. Make
          sure that the logger is not logging  sensitive information.                                        
          Details: https://sg.run/ydNx                                                                       
                                                                                                             
          218┆ _logger.warning(
          219┆     "Could not re-encrypt SMTP password during rotation (reason: %s)",
          220┆     type(exc).__name__,
          221┆ )
            ⋮┆----------------------------------------
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          Detected a python logger call with a potential hardcoded secret "Could not re-encrypt credential %d
          during rotation (reason: %s)" being logged. This may lead to secret credentials being exposed. Make
          sure that the logger is not logging  sensitive information.                                        
          Details: https://sg.run/ydNx                                                                       
                                                                                                             
          245┆ _logger.warning(
          246┆     "Could not re-encrypt credential %d during rotation (reason: %s)",
          247┆     cred.id,
          248┆     type(exc).__name__,
          249┆ )
                             
    docker/backend.Dockerfile
   ❯❯❱ dockerfile.security.missing-user-entrypoint.missing-user-entrypoint
          By not specifying a USER, a program in the container may run as 'root'. This is a security hazard.
          If an attacker can control a process running as root, they may have control over the container.   
          Ensure that the last USER in a Dockerfile is a USER other than 'root'.                            
          Details: https://sg.run/k281                                                                      
                                                                                                            
           ▶▶┆ Autofix ▶ USER non-root ENTRYPOINT ["/entrypoint.sh"]
           77┆ ENTRYPOINT ["/entrypoint.sh"]
   
   ❯❯❱ dockerfile.security.missing-user.missing-user
          By not specifying a USER, a program in the container may run as 'root'. This is a security hazard.
          If an attacker can control a process running as root, they may have control over the container.   
          Ensure that the last USER in a Dockerfile is a USER other than 'root'.                            
          Details: https://sg.run/Gbvn                                                                      
                                                                                                            
           ▶▶┆ Autofix ▶ USER non-root CMD ["python", "src/app/start.py"]
           78┆ CMD ["python", "src/app/start.py"]
                     
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
                          
    docker/nginx.mono.conf
    ❯❱ generic.nginx.security.header-redefinition.header-redefinition
          The 'add_header' directive is called in a 'location' block after headers have been set at the server
          block. Calling 'add_header' in the location block will actually overwrite the headers defined in the
          server block, no matter which headers are set. To fix this, explicitly set all headers or set all   
          headers in the server block.                                                                        
          Details: https://sg.run/Lwl7                                                                        
                                                                                                              
           21┆ add_header   Retry-After 5 always;
            ⋮┆----------------------------------------
           47┆ add_header Cache-Control "public, immutable";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           56┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           57┆ proxy_http_version 1.1;
           58┆ proxy_set_header   Upgrade    $http_upgrade;
           59┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           67┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           68┆ proxy_http_version 1.1;
           69┆ proxy_set_header   Upgrade    $http_upgrade;
           70┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           79┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           80┆ proxy_http_version 1.1;
           81┆ proxy_set_header   Upgrade    $http_upgrade;
           82┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           91┆ proxy_pass         $backend;
            ⋮┆----------------------------------------
          109┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          124┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          136┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          148┆ proxy_pass $backend;
   
    ❯❱ generic.nginx.security.header-redefinition.header-redefinition
          The 'add_header' directive is called in a 'location' block after headers have been set at the server
          block. Calling 'add_header' in the location block will actually overwrite the headers defined in the
          server block, no matter which headers are set. To fix this, explicitly set all headers or set all   
          headers in the server block.                                                                        
          Details: https://sg.run/Lwl7                                                                        
                                                                                                              
          156┆ add_header Cache-Control "no-cache, no-store, must-revalidate";

```
## 3. Gitleaks (Secret Scanning)
```
Finding:     Revises: 0016_webhook_deliveries_oauth_states, [1;3;mb4a9c1d2e8f0[0m
Secret:      [1;3;mb4a9c1d2e8f0[0m
RuleID:      generic-api-key
Entropy:     3.584963
File:        apps/backend/migrations/versions/0020_merge_heads.py
Line:        4
Commit:      54e37bd54a71a4ffcbe4a05bf20fa4cb83de22fc
Author:      Shawnji
Email:       blacklegshawnji@gmail.com
Date:        2026-03-10T02:43:05Z
Fingerprint: 54e37bd54a71a4ffcbe4a05bf20fa4cb83de22fc:apps/backend/migrations/versions/0020_merge_heads.py:generic-api-key:4
Link:        https://github.com/BlkLeg/CircuitBreaker/blob/54e37bd54a71a4ffcbe4a05bf20fa4cb83de22fc/apps/backend/migrations/versions/0020_merge_heads.py#L4

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

Finding:     ...rofile': 'normal', 'jwt_secret': '[1;3;m5954cbda0f1bd6e782cd2d0604b35dad4e0592031369944a049ce5fdaf155437[0m', 'session_timeout_h...
Secret:      [1;3;m5954cbda0f1bd6e782cd2d0604b35dad4e0592031369944a049ce5fdaf155437[0m
RuleID:      generic-api-key
Entropy:     3.853780
File:        docker/circuitbreaker-data/backend_api_err.log
Line:        412136
Commit:      0f36b6b0fc9a8c4c945f547b31ae0143fe1a9db2
Author:      BlkLeg Shawnji
Email:       blacklegshawnji@gamil.com
Date:        2026-03-10T14:14:02Z
Fingerprint: 0f36b6b0fc9a8c4c945f547b31ae0143fe1a9db2:docker/circuitbreaker-data/backend_api_err.log:generic-api-key:412136
Link:        https://github.com/BlkLeg/CircuitBreaker/blob/0f36b6b0fc9a8c4c945f547b31ae0143fe1a9db2/docker/circuitbreaker-data/backend_api_err.log#L412136

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
Dockerfile:20 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
Dockerfile:52 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
docker/backend.Dockerfile:12 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
docker/backend.Dockerfile:33 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
docker/frontend.Dockerfile:24 DL3018 [1m[93mwarning[0m: Pin versions in apk add. Instead of `apk add <package>` use `apk add <package>=<version>`
docker/Dockerfile.prod:5 DL3042 [1m[93mwarning[0m: Avoid use of cache directory with pip. Use `pip install --no-cache-dir <package>`
docker/Dockerfile.prod:17 DL3018 [1m[93mwarning[0m: Pin versions in apk add. Instead of `apk add <package>` use `apk add <package>=<version>`
docker/Dockerfile.native:13 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
docker/Dockerfile.native:13 DL4006 [1m[93mwarning[0m: Set the SHELL option -o pipefail before RUN with a pipe in it. If you are using /bin/sh in an alpine image or if your shell is symlinked to busybox then consider explicitly setting your SHELL to /bin/ash, or disable this check
docker/Dockerfile.native:32 DL4006 [1m[93mwarning[0m: Set the SHELL option -o pipefail before RUN with a pipe in it. If you are using /bin/sh in an alpine image or if your shell is symlinked to busybox then consider explicitly setting your SHELL to /bin/ash, or disable this check
docker/Dockerfile.native:42 DL3013 [1m[93mwarning[0m: Pin versions in pip. Instead of `pip install <package>` use `pip install <package>==<version>` or `pip install --requirement <requirements file>`
docker/Dockerfile.native:45 DL3003 [1m[93mwarning[0m: Use WORKDIR to switch to a directory
```
## 6. Checkov (IaC)
```
