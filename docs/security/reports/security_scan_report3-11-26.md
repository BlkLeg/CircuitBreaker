# Security Scan Report - Wed Mar 11 06:08:45 PM MST 2026
## 1. Bandit (Python SAST)
```
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.14.3
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:01
Run started:2026-03-12 01:08:47.199611+00:00

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
   Location: apps/backend/src/app/api/auth_oauth.py:28:24
27	_OAUTH_STATE_TTL = timedelta(minutes=10)
28	_STAGE_TOKEN_EXCHANGE = "token exchange"
29	_STAGE_USER_LOOKUP = "user lookup"

--------------------------------------------------
>> Issue: [B101:assert_used] Use of assert detected. The enclosed code will be removed when compiling to optimised byte code.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b101_assert_used.html
   Location: apps/backend/src/app/api/auth_oauth.py:248:8
247	    else:
248	        assert user is not None
249	        user.provider = provider

--------------------------------------------------
>> Issue: [B101:assert_used] Use of assert detected. The enclosed code will be removed when compiling to optimised byte code.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b101_assert_used.html
   Location: apps/backend/src/app/api/auth_oauth.py:267:4
266	    db.refresh(user)
267	    assert user is not None
268	    return user, is_new

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/branding.py:182:4
181	        data = buf.getvalue()
182	    except Exception:
183	        # If Pillow fails, save the raw upload — it's already validated by extension
184	        pass
185	

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
   Location: apps/backend/src/app/api/ws_discovery.py:129:8
128	            await pubsub.aclose()
129	        except Exception:
130	            pass
131	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:144:8
143	            await websocket.close(code=1008)
144	        except Exception:
145	            pass
146	        return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:162:16
161	                    await websocket.close(code=1008)
162	                except Exception:
163	                    pass
164	                return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:200:12
199	                await websocket.close(code=1008)
200	            except Exception:
201	                pass
202	            return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:210:12
209	                await websocket.close(code=1008)
210	            except Exception:
211	                pass
212	            return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:228:16
227	                        await websocket.send_text(json.dumps({"type": "pong", "ts": utcnow_iso()}))
228	                except Exception:
229	                    pass
230	        except WebSocketDisconnect:

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_discovery.py:243:8
242	            await websocket.close(code=1011)
243	        except Exception:
244	            pass
245	

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
   Location: apps/backend/src/app/api/ws_status.py:158:8
157	            await websocket.close(code=1011)
158	        except Exception:
159	            pass
160	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_telemetry.py:118:8
117	            await pubsub.aclose()
118	        except Exception:
119	            pass
120	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_telemetry.py:131:4
130	        pass
131	    except Exception:
132	        pass
133	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_telemetry.py:143:8
142	            await websocket.close(code=1008)
143	        except Exception:
144	            pass
145	        return

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/api/ws_telemetry.py:282:8
281	            await websocket.close(code=1011)
282	        except Exception:
283	            pass

--------------------------------------------------
>> Issue: [B105:hardcoded_password_string] Possible hardcoded password: 'NATS_AUTH_TOKEN'
   Severity: Low   Confidence: Medium
   CWE: CWE-259 (https://cwe.mitre.org/data/definitions/259.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b105_hardcoded_password_string.html
   Location: apps/backend/src/app/core/config_toml.py:30:4
29	    "nats.url": "CB_NATS_URL",
30	    "nats.auth_token": "NATS_AUTH_TOKEN",
31	    "security.vault_key": "CB_VAULT_KEY",
32	    "security.cors_origins": "CORS_ORIGINS",
33	    "discovery.docker_host": "CB_DOCKER_HOST",
34	    "discovery.proxmox_url": "CB_PROXMOX_URL",
35	    "paths.data_dir": "CB_DATA_DIR",
36	    "paths.log_dir": "CB_LOG_DIR",
37	    "paths.static_dir": "STATIC_DIR",
38	    "paths.alembic_ini": "CB_ALEMBIC_INI",
39	    "updates.check_on_startup": "CB_UPDATE_CHECK",
40	}
41	
42	
43	def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
44	    """Flatten nested dict to dotted keys with string values."""
45	    result: dict[str, str] = {}
46	    for key, value in data.items():
47	        full_key = f"{prefix}.{key}" if prefix else key
48	        if isinstance(value, dict):
49	            result.update(_flatten(value, full_key))

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/core/redis.py:87:12
86	                await _redis.aclose()
87	            except Exception:
88	                pass
89	            _redis = None

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
   Location: apps/backend/src/app/core/users.py:130:8
129	                raw_token = json.loads(response.body).get("access_token")
130	        except Exception:
131	            pass
132	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/core/users.py:236:4
235	            db.close()
236	    except Exception:
237	        pass
238	

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
   Location: apps/backend/src/app/main.py:857:4
856	        asyncio.create_task(log_update_notice(settings.app_version))
857	    except Exception:
858	        pass  # Never let update check affect startup
859	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/middleware/tenant_middleware.py:38:12
37	                tenant_id = payload.get("tenant_id")
38	            except Exception:  # noqa: BLE001
39	                pass
40	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/schemas/settings.py:234:12
233	                self.theme_colors = json.loads(raw)
234	            except Exception:
235	                pass
236	        return self

--------------------------------------------------
>> Issue: [B105:hardcoded_password_string] Possible hardcoded password: 'OAuth token is invalid or expired'
   Severity: Low   Confidence: Medium
   CWE: CWE-259 (https://cwe.mitre.org/data/definitions/259.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b105_hardcoded_password_string.html
   Location: apps/backend/src/app/services/auth_service.py:33:27
32	_MSG_BOOTSTRAP_DONE = "Bootstrap already completed. Please refresh and log in."
33	_MSG_OAUTH_TOKEN_INVALID = "OAuth token is invalid or expired"
34	

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/auth_service.py:766:4
765	            )
766	    except Exception:  # noqa: BLE001
767	        pass
768	    return OnboardingStepResponse(current_step="start", previous_step="start")

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: apps/backend/src/app/services/certificate_service.py:10:0
9	import logging
10	import subprocess
11	from datetime import datetime, timedelta, timezone

--------------------------------------------------
>> Issue: [B607:start_process_with_partial_path] Starting a process with a partial executable path
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b607_start_process_with_partial_path.html
   Location: apps/backend/src/app/services/certificate_service.py:150:21
149	        try:
150	            result = subprocess.run(
151	                [
152	                    "certbot", "certonly",
153	                    "--standalone",
154	                    "--non-interactive",
155	                    "--agree-tos",
156	                    "--email", "admin@localhost",
157	                    "-d", cert.domain,
158	                    "--cert-path", "/tmp/cb_cert.pem",
159	                    "--key-path", "/tmp/cb_key.pem",
160	                ],
161	                capture_output=True,
162	                text=True,
163	                timeout=120,
164	            )
165	            if result.returncode != 0:

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: apps/backend/src/app/services/certificate_service.py:150:21
149	        try:
150	            result = subprocess.run(
151	                [
152	                    "certbot", "certonly",
153	                    "--standalone",
154	                    "--non-interactive",
155	                    "--agree-tos",
156	                    "--email", "admin@localhost",
157	                    "-d", cert.domain,
158	                    "--cert-path", "/tmp/cb_cert.pem",
159	                    "--key-path", "/tmp/cb_key.pem",
160	                ],
161	                capture_output=True,
162	                text=True,
163	                timeout=120,
164	            )
165	            if result.returncode != 0:

--------------------------------------------------
>> Issue: [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
   Severity: Medium   Confidence: Medium
   CWE: CWE-377 (https://cwe.mitre.org/data/definitions/377.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b108_hardcoded_tmp_directory.html
   Location: apps/backend/src/app/services/certificate_service.py:158:35
157	                    "-d", cert.domain,
158	                    "--cert-path", "/tmp/cb_cert.pem",
159	                    "--key-path", "/tmp/cb_key.pem",
160	                ],
161	                capture_output=True,
162	                text=True,
163	                timeout=120,
164	            )
165	            if result.returncode != 0:
166	                _logger.error("certbot renewal failed for %s: %s", cert.domain, result.stderr)
167	                return cert
168	

--------------------------------------------------
>> Issue: [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
   Severity: Medium   Confidence: Medium
   CWE: CWE-377 (https://cwe.mitre.org/data/definitions/377.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b108_hardcoded_tmp_directory.html
   Location: apps/backend/src/app/services/certificate_service.py:159:34
158	                    "--cert-path", "/tmp/cb_cert.pem",
159	                    "--key-path", "/tmp/cb_key.pem",
160	                ],
161	                capture_output=True,
162	                text=True,
163	                timeout=120,
164	            )
165	            if result.returncode != 0:
166	                _logger.error("certbot renewal failed for %s: %s", cert.domain, result.stderr)
167	                return cert
168	
169	            with open("/tmp/cb_cert.pem") as f:

--------------------------------------------------
>> Issue: [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
   Severity: Medium   Confidence: Medium
   CWE: CWE-377 (https://cwe.mitre.org/data/definitions/377.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b108_hardcoded_tmp_directory.html
   Location: apps/backend/src/app/services/certificate_service.py:169:22
168	
169	            with open("/tmp/cb_cert.pem") as f:
170	                new_cert_pem = f.read()

--------------------------------------------------
>> Issue: [B108:hardcoded_tmp_directory] Probable insecure usage of temp file/directory.
   Severity: Medium   Confidence: Medium
   CWE: CWE-377 (https://cwe.mitre.org/data/definitions/377.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b108_hardcoded_tmp_directory.html
   Location: apps/backend/src/app/services/certificate_service.py:171:22
170	                new_cert_pem = f.read()
171	            with open("/tmp/cb_key.pem") as f:
172	                new_key_pem = f.read()

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
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/log_service.py:245:4
244	            pass
245	    except Exception:
246	        pass

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
>> Issue: [B311:blacklist] Standard pseudo-random generators are not suitable for security/cryptographic purposes.
   Severity: Low   Confidence: High
   CWE: CWE-330 (https://cwe.mitre.org/data/definitions/330.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_calls.html#b311-random
   Location: apps/backend/src/app/services/proxmox_service.py:539:33
538	                        * (2**attempt)
539	                        * (0.5 + random.random() * 0.5)
540	                    )

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/services/proxmox_service.py:1461:8
1460	                uptime_str = f"{d}d {h}h {m}m"
1461	        except Exception:
1462	            pass
1463	

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
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: apps/backend/src/app/start.py:224:4
223	            print(f"[start] Loaded {toml_count} setting(s) from config.toml")
224	    except Exception:
225	        pass  # config.toml support is optional
226	

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
	Total lines of code: 30387
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 0

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 82
		Medium: 11
		High: 1
	Total issues (by confidence):
		Undefined: 0
		Low: 3
		Medium: 14
		High: 77
Files skipped (0):
```
## 2. Semgrep (SAST)
```
               
               
┌─────────────┐
│ Scan Status │
└─────────────┘
  Scanning 408 files tracked by git with 1063 Code rules:
                                                                                                                        
  Language      Rules   Files          Origin      Rules                                                                
 ─────────────────────────────        ───────────────────                                                               
  <multilang>      58     273          Community    1063                                                                
  js              156     190                                                                                           
  python          243     181                                                                                           
  bash              4       6                                                                                           
  yaml             31       3                                                                                           
  dockerfile        6       2                                                                                           
  json              4       2                                                                                           
  ts              166       1                                                                                           
                                                                                                                        
                
                
┌──────────────┐
│ Scan Summary │
└──────────────┘
✅ Scan completed successfully.
 • Findings: 43 (43 blocking)
 • Rules run: 507
 • Targets scanned: 408
 • Parsed lines: ~99.9%
 • Scan was limited to files tracked by git
 • For a detailed list of skipped files and lines, run semgrep with the --verbose flag
Ran 507 rules on 408 files: 43 findings.

A new version of Semgrep is available. See https://semgrep.dev/docs/upgrading

📢 Too many findings? Try Semgrep Pro for more powerful queries and less noise.
   See https://sg.run/false-positives.
                    
                    
┌──────────────────┐
│ 43 Code Findings │
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
                                                                                                           
          191┆ _logger.info("Password reset email sent to %s", user.email)
            ⋮┆----------------------------------------
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          Detected a python logger call with a potential hardcoded secret "Password reset token generated for
          %s (SMTP not configured); deliver token via alternate channel." being logged. This may lead to     
          secret credentials being exposed. Make sure that the logger is not logging  sensitive information. 
          Details: https://sg.run/ydNx                                                                       
                                                                                                             
          193┆ _logger.info(
          194┆     "Password reset token generated for %s (SMTP not configured); deliver token via
               alternate channel.",                                                               
          195┆     user.email,
          196┆ )
            ⋮┆----------------------------------------
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          Detected a python logger call with a potential hardcoded secret "Failed to send password reset email
          to %s (reason: %s)" being logged. This may lead to secret credentials being exposed. Make sure that 
          the logger is not logging  sensitive information.                                                   
          Details: https://sg.run/ydNx                                                                        
                                                                                                              
          198┆ _logger.warning(
          199┆     "Failed to send password reset email to %s (reason: %s)",
          200┆     user.email,
          201┆     type(exc).__name__,
          202┆ )
                                            
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
                                
    apps/backend/src/app/main.py
   ❯❯❱ python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
          sqlalchemy.text passes the constructed SQL statement to the database mostly unchanged. This means  
          that the usual SQL injection protections are not applied and this function is vulnerable to SQL    
          injection if user input can reach here. Use normal SQLAlchemy operators (such as `or_()`, `and_()`,
          etc.) to construct SQL.                                                                            
          Details: https://sg.run/yP1O                                                                       
                                                                                                             
          481┆ sa.text(
          482┆     f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF audit_log "
          483┆     f"FOR VALUES FROM ('{start}') TO ('{end}')"
          484┆ )
                                                     
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
                                                    
    apps/backend/src/app/services/proxmox_service.py
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          Detected a python logger call with a potential hardcoded secret "Proxmox discovery failed (invalid
          config/token) for integration %d: %s" being logged. This may lead to secret credentials being     
          exposed. Make sure that the logger is not logging  sensitive information.                         
          Details: https://sg.run/ydNx                                                                      
                                                                                                            
          528┆ _logger.warning(
          529┆     "Proxmox discovery failed (invalid config/token) for integration %d: %s",
          530┆     config.id,
          531┆     e,
          532┆ )
                                                  
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
           78┆ ENTRYPOINT ["/entrypoint.sh"]
   
   ❯❯❱ dockerfile.security.missing-user.missing-user
          By not specifying a USER, a program in the container may run as 'root'. This is a security hazard.
          If an attacker can control a process running as root, they may have control over the container.   
          Ensure that the last USER in a Dockerfile is a USER other than 'root'.                            
          Details: https://sg.run/Gbvn                                                                      
                                                                                                            
           ▶▶┆ Autofix ▶ USER non-root CMD ["python", "src/app/start.py"]
           79┆ CMD ["python", "src/app/start.py"]
                     
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
                                                                                                              
           29┆ add_header   Retry-After 5 always;
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
           41┆ proxy_pass $backend;
            ⋮┆----------------------------------------
           89┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           90┆ proxy_http_version 1.1;
           91┆ proxy_set_header   Upgrade    $http_upgrade;
           92┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
          100┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
          101┆ proxy_http_version 1.1;
          102┆ proxy_set_header   Upgrade    $http_upgrade;
          103┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
          112┆ proxy_pass         $backend;
   
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
          113┆ proxy_http_version 1.1;
          114┆ proxy_set_header   Upgrade    $http_upgrade;
          115┆ proxy_set_header   Connection "upgrade";
   
    ❯❱ generic.nginx.security.missing-internal.missing-internal
          This location block contains a 'proxy_pass' directive but does not contain the 'internal' directive.
          The 'internal' directive restricts access to this location to internal requests. Without 'internal',
          an attacker could use your server for server-side request forgeries (SSRF). Include the 'internal'  
          directive in this block to limit exposure.                                                          
          Details: https://sg.run/Q5px                                                                        
                                                                                                              
          124┆ proxy_pass         $backend;
            ⋮┆----------------------------------------
          142┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          157┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          169┆ proxy_pass $backend;
            ⋮┆----------------------------------------
          181┆ proxy_pass $backend;

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

> circuit-breaker-ui@0.2.2 lint
> eslint .


/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/__tests__/discovery-page.test.jsx
  73:39  warning  'jobCounts' is defined but never used  @typescript-eslint/no-unused-vars

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/__tests__/map-page.test.jsx
  185:13  warning  'props' is defined but never used  @typescript-eslint/no-unused-vars

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/__tests__/settings-import.test.jsx
  63:39  warning  'activeTab' is defined but never used  @typescript-eslint/no-unused-vars

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/__tests__/toast.test.jsx
  3:37  warning  'waitFor' is defined but never used  @typescript-eslint/no-unused-vars

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/TagsCell.jsx
  84:11  warning  Unsafe Regular Expression  security/detect-unsafe-regex

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/discovery/ScanProfileForm.jsx
  12:17  warning  Unsafe Regular Expression  security/detect-unsafe-regex

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/hooks/useMapDataLoad.js
  138:5  warning  React Hook useCallback has a missing dependency: 'fitView'. Either include it or remove the dependency array. If 'fitView' changes too often, find the parent component that defines it and wrap that definition in useCallback  react-hooks/exhaustive-deps

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/InviteAcceptPage.jsx
  29:5  warning  Potential timing attack, left side: true  security/detect-possible-timing-attacks

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/ResetPasswordPage.jsx
  88:5  warning  Potential timing attack, left side: true  security/detect-possible-timing-attacks

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/vite.config.ts
  12:21  warning  Found readFileSync from package "node:fs" with non literal argument at index 0  security/detect-non-literal-fs-filename

✖ 10 problems (0 errors, 10 warnings)

```
## 5. Hadolint (Dockerfile lint)
```
Dockerfile:20 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
Dockerfile:52 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
docker/backend.Dockerfile:12 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
docker/backend.Dockerfile:33 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
docker/frontend.Dockerfile:24 DL3018 [1m[93mwarning[0m: Pin versions in apk add. Instead of `apk add <package>` use `apk add <package>=<version>`
```
## 6. Checkov (IaC)
```
dockerfile scan results:

Passed checks: 197, Failed checks: 0, Skipped checks: 1


2026-03-11 18:09:40,509 [MainThread  ] [ERROR]  YAML error parsing ./site/search/search_index.json: while parsing a quoted scalar
  in "<unicode string>", line 1, column 104579
found invalid Unicode character escape code
  in "<unicode string>", line 1, column 107748
cloudformation scan results:

Passed checks: 0, Failed checks: 0, Skipped checks: 0, Parsing errors: 1

dockerfile scan results:

Passed checks: 747, Failed checks: 1, Skipped checks: 3

Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.mono.
	File: /Dockerfile.mono:1-126
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
github_actions scan results:

Passed checks: 647, Failed checks: 4, Skipped checks: 0

Check: CKV_GHA_7: "The build output cannot be affected by user parameters other than the build entry point and the top-level source location. GitHub Actions workflow_dispatch inputs MUST be empty. "
	FAILED for resource: on(Native Binaries)
	File: /.github/workflows/native.yml:9-14

		9  |       version:
		10 |         description: "Version override (e.g. 0.2.2)"
		11 |         required: false
		12 | 
		13 | permissions:
		14 |   contents: write

Check: CKV2_GHA_1: "Ensure top-level permissions are not set to write-all"
	FAILED for resource: on(Ollama Issue Triage)
	File: /.github/workflows/issue-triage.yml:0-1
Check: CKV2_GHA_1: "Ensure top-level permissions are not set to write-all"
	FAILED for resource: on(Ollama GPU Runner)
	File: /.github/workflows/ollama-runner.yml:0-1
Check: CKV2_GHA_1: "Ensure top-level permissions are not set to write-all"
	FAILED for resource: on(Ollama PR Review)
	File: /.github/workflows/pr-preview.yml:20-21

```
## 7. Trivy (Filesystem)
```
2026-03-12T01:09:44Z	INFO	[vulndb] Need to update DB
2026-03-12T01:09:44Z	INFO	[vulndb] Downloading vulnerability DB...
2026-03-12T01:09:44Z	INFO	[vulndb] Downloading artifact...	repo="mirror.gcr.io/aquasec/trivy-db:2"
3.39 MiB / 87.31 MiB [-->____________________________________________________________] 3.88% ? p/s ?9.92 MiB / 87.31 MiB [------->______________________________________________________] 11.36% ? p/s ?16.73 MiB / 87.31 MiB [----------->_________________________________________________] 19.16% ? p/s ?24.32 MiB / 87.31 MiB [------------->__________________________________] 27.86% 34.88 MiB p/s ETA 1s32.32 MiB / 87.31 MiB [----------------->______________________________] 37.02% 34.88 MiB p/s ETA 1s41.54 MiB / 87.31 MiB [---------------------->_________________________] 47.58% 34.88 MiB p/s ETA 1s50.56 MiB / 87.31 MiB [--------------------------->____________________] 57.90% 35.45 MiB p/s ETA 1s59.93 MiB / 87.31 MiB [-------------------------------->_______________] 68.64% 35.45 MiB p/s ETA 0s69.46 MiB / 87.31 MiB [-------------------------------------->_________] 79.56% 35.45 MiB p/s ETA 0s78.51 MiB / 87.31 MiB [------------------------------------------->____] 89.92% 36.17 MiB p/s ETA 0s87.31 MiB / 87.31 MiB [---------------------------------------------->] 100.00% 36.17 MiB p/s ETA 0s87.31 MiB / 87.31 MiB [---------------------------------------------->] 100.00% 36.17 MiB p/s ETA 0s87.31 MiB / 87.31 MiB [---------------------------------------------->] 100.00% 34.78 MiB p/s ETA 0s87.31 MiB / 87.31 MiB [---------------------------------------------->] 100.00% 34.78 MiB p/s ETA 0s87.31 MiB / 87.31 MiB [---------------------------------------------->] 100.00% 34.78 MiB p/s ETA 0s87.31 MiB / 87.31 MiB [---------------------------------------------->] 100.00% 32.54 MiB p/s ETA 0s87.31 MiB / 87.31 MiB [---------------------------------------------->] 100.00% 32.54 MiB p/s ETA 0s87.31 MiB / 87.31 MiB [---------------------------------------------->] 100.00% 32.54 MiB p/s ETA 0s87.31 MiB / 87.31 MiB [---------------------------------------------->] 100.00% 30.44 MiB p/s ETA 0s87.31 MiB / 87.31 MiB [-------------------------------------------------] 100.00% 24.02 MiB p/s 3.8s2026-03-12T01:09:50Z	INFO	[vulndb] Artifact successfully downloaded	repo="mirror.gcr.io/aquasec/trivy-db:2"
2026-03-12T01:09:50Z	INFO	[vuln] Vulnerability scanning is enabled
2026-03-12T01:09:50Z	INFO	[secret] Secret scanning is enabled
2026-03-12T01:09:50Z	INFO	[secret] If your scanning is slow, please try '--scanners vuln' to disable secret scanning
2026-03-12T01:09:50Z	INFO	[secret] Please see https://trivy.dev/docs/v0.69/guide/scanner/secret#recommendation for faster secret detection
2026-03-12T01:09:58Z	WARN	[secret] Invalid UTF-8 sequences detected in file content, replacing with empty string
2026-03-12T01:10:03Z	WARN	[secret] The size of the scanned file is too large. It is recommended to use `--skip-files` for this file to avoid high memory consumption.	file_path=".venv/lib/python3.14/site-packages/policy_sentry/shared/data/iam-definition.json" size (MB)=10
2026-03-12T01:10:18Z	WARN	[pip] Unable to find python `site-packages` directory. License detection is skipped.	err="unable to find path to Python executable"
2026-03-12T01:10:18Z	INFO	Suppressing dependencies for development and testing. To display them, try the '--include-dev-deps' flag.
2026-03-12T01:10:18Z	INFO	Number of language-specific files	num=4
2026-03-12T01:10:18Z	INFO	[npm] Detecting vulnerabilities...
2026-03-12T01:10:18Z	INFO	[pip] Detecting vulnerabilities...
2026-03-12T01:10:18Z	INFO	[poetry] Detecting vulnerabilities...

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
│ .github/workflows/.env                                                           │  text  │        -        │    1    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.14/site-packages/fastapi_users/authentication/transport/__pyc- │  text  │        -        │    1    │
│ ache__/bearer.cpython-314.pyc                                                    │        │                 │         │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ docker/circuitbreaker-data/tls/privkey.pem                                       │  text  │        -        │    1    │
└──────────────────────────────────────────────────────────────────────────────────┴────────┴─────────────────┴─────────┘
Legend:
- '-': Not scanned
- '0': Clean (no security findings detected)


.github/workflows/.env (secrets)
================================
Total: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 1)

CRITICAL: GitHub (github-fine-grained-pat)
════════════════════════════════════════
GitHub Fine-grained personal access tokens
────────────────────────────────────────
 .github/workflows/.env:1 (offset: 9 bytes)
────────────────────────────────────────
   1 [ GH_TOKEN=*********************************************************************************************
   2   OLLAMA_API_URL=http://10.10.10.110:11434
────────────────────────────────────────



.venv/lib/python3.14/site-packages/fastapi_users/authentication/transport/__pycache__/bearer.cpython-314.pyc (secrets)
======================================================================================================================
Total: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 1, HIGH: 0, CRITICAL: 0)

MEDIUM: JWT (jwt-token)
════════════════════════════════════════
JWT token
────────────────────────────────────────



docker/circuitbreaker-data/tls/privkey.pem (secrets)
====================================================
Total: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 0, HIGH: 1, CRITICAL: 0)

HIGH: AsymmetricPrivateKey (private-key)
════════════════════════════════════════
Asymmetric Private Key
────────────────────────────────────────
 docker/circuitbreaker-data/tls/privkey.pem:2-4 (offset: 28 bytes)
────────────────────────────────────────
   1   -----BEGIN PRIVATE KEY-----
   2 ┌ ****************************************************************
   3 │ ****************************************************************
   4 └ ********************************************************
   5   -----END PRIVATE KEY-----
────────────────────────────────────────


```
## 8. Trivy (Config / IaC)
```
2026-03-12T01:10:19Z	INFO	[misconfig] Misconfiguration scanning is enabled
2026-03-12T01:10:19Z	INFO	[checks-client] Need to update the checks bundle
2026-03-12T01:10:19Z	INFO	[checks-client] Downloading the checks bundle...
235.65 KiB / 235.65 KiB [------------------------------------------------------] 100.00% ? p/s 100ms2026-03-12T01:10:42Z	INFO	Detected config files	num=20

Report Summary

┌──────────────────────────────────────────────────────────────────────────────────┬────────────────┬───────────────────┐
│                                      Target                                      │      Type      │ Misconfigurations │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/cloudformation/2010-05-15/resourc- │ cloudformation │         0         │
│ es-1.json                                                                        │                │                   │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/cloudwatch/2010-08-01/resources-1- │ cloudformation │         0         │
│ .json                                                                            │                │                   │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/dynamodb/2012-08-10/resources-1.j- │ cloudformation │         0         │
│ son                                                                              │                │                   │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/ec2/2014-10-01/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/ec2/2015-03-01/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/ec2/2015-04-15/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/ec2/2015-10-01/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/ec2/2016-04-01/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/ec2/2016-09-15/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/ec2/2016-11-15/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/glacier/2012-06-01/resources-1.js- │ cloudformation │         0         │
│ on                                                                               │                │                   │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/iam/2010-05-08/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/opsworks/2013-02-18/resources-1.j- │ cloudformation │         0         │
│ son                                                                              │                │                   │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/s3/2006-03-01/resources-1.json     │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/sns/2010-03-31/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.14/site-packages/boto3/data/sqs/2012-11-05/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ Dockerfile                                                                       │   dockerfile   │         1         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ Dockerfile.mono                                                                  │   dockerfile   │         1         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ docker/backend.Dockerfile                                                        │   dockerfile   │         1         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ docker/frontend.Dockerfile                                                       │   dockerfile   │         0         │
└──────────────────────────────────────────────────────────────────────────────────┴────────────────┴───────────────────┘
Legend:
- '-': Not scanned
- '0': Clean (no security findings detected)


Dockerfile (dockerfile)
=======================
Tests: 27 (SUCCESSES: 26, FAILURES: 1)
Failures: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 0, HIGH: 1, CRITICAL: 0)

DS-0002 (HIGH): Specify at least 1 USER command in Dockerfile with non-root user as argument
════════════════════════════════════════
Running containers with 'root' user can lead to a container escape situation. It is a best practice to run containers as non-root users, which can be done by adding a 'USER' statement to the Dockerfile.

See https://avd.aquasec.com/misconfig/ds-0002
────────────────────────────────────────



Dockerfile.mono (dockerfile)
============================
Tests: 27 (SUCCESSES: 26, FAILURES: 1)
Failures: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 0, HIGH: 1, CRITICAL: 0)

DS-0002 (HIGH): Specify at least 1 USER command in Dockerfile with non-root user as argument
════════════════════════════════════════
Running containers with 'root' user can lead to a container escape situation. It is a best practice to run containers as non-root users, which can be done by adding a 'USER' statement to the Dockerfile.

See https://avd.aquasec.com/misconfig/ds-0002
────────────────────────────────────────



docker/backend.Dockerfile (dockerfile)
======================================
Tests: 27 (SUCCESSES: 26, FAILURES: 1)
Failures: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 0, HIGH: 1, CRITICAL: 0)

DS-0002 (HIGH): Specify at least 1 USER command in Dockerfile with non-root user as argument
════════════════════════════════════════
Running containers with 'root' user can lead to a container escape situation. It is a best practice to run containers as non-root users, which can be done by adding a 'USER' statement to the Dockerfile.

See https://avd.aquasec.com/misconfig/ds-0002
────────────────────────────────────────


```
## 9. npm audit (Frontend)
```
found 0 vulnerabilities
```
