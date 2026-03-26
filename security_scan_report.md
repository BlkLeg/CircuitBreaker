# Security Scan Report - Wed Mar 25 04:52:54 PM MST 2026

## 1. Bandit (Python SAST)
```
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: B101
[main]	INFO	running on Python 3.12.13
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:02
Run started:2026-03-25 23:52:57.016685+00:00

Test results:
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:83:18
82	                # The :path parameter is properly parameterized. Not user-controlled.
83	                f"CREATE TABLE IF NOT EXISTS {table_identifier} AS "
84	                "SELECT * FROM read_csv_auto(:path) LIMIT 0"
85	            ),

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:91:18
90	                # Safe: table_identifier validated above; :path is parameterized.
91	                f"INSERT INTO {table_identifier} SELECT * FROM read_csv_auto(:path)"
92	            ),

--------------------------------------------------
>> Issue: [B608:hardcoded_sql_expressions] Possible SQL injection vector through string-based query construction.
   Severity: Medium   Confidence: Low
   CWE: CWE-89 (https://cwe.mitre.org/data/definitions/89.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b608_hardcoded_sql_expressions.html
   Location: apps/backend/src/app/db/duckdb_client.py:98:22
97	                text(
98	                    f"SELECT count(*) FROM {table_identifier}"
99	                )  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text  # nosec B608  # noqa: E501

--------------------------------------------------
>> Issue: [B104:hardcoded_bind_all_interfaces] Possible binding to all interfaces.
   Severity: Medium   Confidence: Medium
   CWE: CWE-605 (https://cwe.mitre.org/data/definitions/605.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b104_hardcoded_bind_all_interfaces.html
   Location: apps/backend/src/app/services/layout_service.py:65:66
64	            others_sorted = sorted(
65	                others, key=lambda n: int((n.get("ip_address") or "0.0.0.0").split(".")[-1])
66	            )

--------------------------------------------------
>> Issue: [B324:hashlib] Use of weak MD5 hash for security. Consider usedforsecurity=False
   Severity: High   Confidence: High
   CWE: CWE-327 (https://cwe.mitre.org/data/definitions/327.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b324_hashlib.html
   Location: apps/backend/src/app/workers/notification_worker.py:155:28
154	    raw = f"{subject}:{severity}:{title}"
155	    key = f"cb:alert:dedup:{hashlib.md5(raw.encode()).hexdigest()}"  # noqa: S324
156	    result = await r.set(key, 1, ex=_DEDUP_WINDOW_S, nx=True)

--------------------------------------------------

Code scanned:
	Total lines of code: 39590
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 0

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 103
		Medium: 4
		High: 1
	Total issues (by confidence):
		Undefined: 0
		Low: 3
		Medium: 9
		High: 96
Files skipped (0):
```
## 2. Semgrep (SAST)
```
               
               
┌─────────────┐
│ Scan Status │
└─────────────┘
  Scanning 544 files tracked by git with 1063 Code rules:
                                                                                                                        
  Language      Rules   Files          Origin      Rules                                                                
 ─────────────────────────────        ───────────────────                                                               
  <multilang>      58     363          Community    1063                                                                
  js              156     272                                                                                           
  python          243     231                                                                                           
  bash              4       6                                                                                           
  yaml             31       2                                                                                           
  dockerfile        6       2                                                                                           
  json              4       2                                                                                           
  ts              166       1                                                                                           
                                                                                                                        
                    
                    
┌──────────────────┐
│ 22 Code Findings │
└──────────────────┘
                                         
    apps/backend/src/app/core/security.py
   ❯❯❱ python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
          ❰❰ Blocking ❱❱
          Detected JWT token decoded with 'verify=False'. This bypasses any integrity checks for the token
          which means the token could be tampered with by malicious actors. Ensure that the JWT token is  
          verified.                                                                                       
          Details: https://sg.run/6nyB                                                                    
                                                                                                          
           ▶▶┆ Autofix ▶ True
          251┆ token, options={"verify_signature": False}, algorithms=["HS256"]
                                            
    apps/backend/src/app/db/duckdb_client.py
   ❯❯❱ python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
          ❰❰ Blocking ❱❱
          sqlalchemy.text passes the constructed SQL statement to the database mostly unchanged. This means  
          that the usual SQL injection protections are not applied and this function is vulnerable to SQL    
          injection if user input can reach here. Use normal SQLAlchemy operators (such as `or_()`, `and_()`,
          etc.) to construct SQL.                                                                            
          Details: https://sg.run/yP1O                                                                       
                                                                                                             
           97┆ text(
           98┆     f"SELECT count(*) FROM {table_identifier}"
           99┆ )  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-
               text  # nosec B608  # noqa: E501                                                        
                                              
    apps/backend/src/app/services/db_backup.py
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          ❰❰ Blocking ❱❱
          Detected a python logger call with a potential hardcoded secret "Could not decrypt S3 secret key:
          %s" being logged. This may lead to secret credentials being exposed. Make sure that the logger is
          not logging  sensitive information.                                                              
          Details: https://sg.run/ydNx                                                                     
                                                                                                           
          173┆ _logger.warning("Could not decrypt S3 secret key: %s", exc)
                     
    docker/nginx.conf
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          ❰❰ Blocking ❱❱
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           49┆ proxy_http_version 1.1;
           50┆ proxy_set_header   Upgrade    $http_upgrade;
           51┆ proxy_set_header   Connection "upgrade";
            ⋮┆----------------------------------------
           61┆ proxy_http_version 1.1;
           62┆ proxy_set_header   Upgrade    $http_upgrade;
           63┆ proxy_set_header   Connection "upgrade";
            ⋮┆----------------------------------------
           74┆ proxy_http_version 1.1;
           75┆ proxy_set_header   Upgrade    $http_upgrade;
           76┆ proxy_set_header   Connection "upgrade";
            ⋮┆----------------------------------------
           87┆ proxy_http_version 1.1;
           88┆ proxy_set_header   Upgrade    $http_upgrade;
           89┆ proxy_set_header   Connection "upgrade";
            ⋮┆----------------------------------------
          100┆ proxy_http_version 1.1;
          101┆ proxy_set_header   Host              $host;
          102┆ proxy_set_header   X-Real-IP         $remote_addr;
          103┆ proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
          104┆ proxy_set_header   Authorization     $http_authorization;
          105┆ proxy_set_header   Upgrade           "";
          106┆ proxy_set_header   Connection        "";
            ⋮┆----------------------------------------
          115┆ proxy_http_version 1.1;
          116┆ proxy_set_header Host              $host;
          117┆ proxy_set_header X-Real-IP         $remote_addr;
          118┆ proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
          119┆ proxy_set_header Authorization     $http_authorization;
          120┆ proxy_set_header Upgrade           "";
          121┆ proxy_set_header Connection        "";
            ⋮┆----------------------------------------
          130┆ proxy_http_version 1.1;
          131┆ proxy_set_header Host            $host;
          132┆ proxy_set_header X-Real-IP       $remote_addr;
          133┆ proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          134┆ proxy_set_header Upgrade         "";
          135┆ proxy_set_header Connection      "";
            ⋮┆----------------------------------------
          141┆ proxy_http_version 1.1;
          142┆ proxy_set_header Host            $host;
          143┆ proxy_set_header X-Real-IP       $remote_addr;
          144┆ proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          145┆ proxy_set_header Upgrade         "";
          146┆ proxy_set_header Connection      "";
            ⋮┆----------------------------------------
          152┆ proxy_http_version 1.1;
          153┆ proxy_set_header Host            $host;
          154┆ proxy_set_header X-Real-IP       $remote_addr;
          155┆ proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          156┆ proxy_set_header Upgrade         "";
          157┆ proxy_set_header Connection      "";
                          
    docker/nginx.mono.conf
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          ❰❰ Blocking ❱❱
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
           53┆ proxy_http_version 1.1;
           54┆ proxy_set_header Host              $host;
           55┆ proxy_set_header X-Real-IP         $remote_addr;
           56┆ proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
           57┆ proxy_set_header Upgrade           "";
           58┆ proxy_set_header Connection        "";
            ⋮┆----------------------------------------
          106┆ proxy_http_version 1.1;
          107┆ proxy_set_header   Upgrade    $http_upgrade;
          108┆ proxy_set_header   Connection "upgrade";
            ⋮┆----------------------------------------
          117┆ proxy_http_version 1.1;
          118┆ proxy_set_header   Upgrade    $http_upgrade;
          119┆ proxy_set_header   Connection "upgrade";
            ⋮┆----------------------------------------
          129┆ proxy_http_version 1.1;
          130┆ proxy_set_header   Upgrade    $http_upgrade;
          131┆ proxy_set_header   Connection "upgrade";
            ⋮┆----------------------------------------
          141┆ proxy_http_version 1.1;
          142┆ proxy_set_header   Upgrade    $http_upgrade;
          143┆ proxy_set_header   Connection "upgrade";
            ⋮┆----------------------------------------
          153┆ proxy_http_version 1.1;
          154┆ proxy_set_header   Host              $host;
          155┆ proxy_set_header   X-Real-IP         $remote_addr;
          156┆ proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
          157┆ proxy_set_header   Authorization     $http_authorization;
          158┆ proxy_set_header   Upgrade           "";
          159┆ proxy_set_header   Connection        "";
            ⋮┆----------------------------------------
          173┆ proxy_http_version 1.1;
          174┆ proxy_set_header Host              $host;
          175┆ proxy_set_header X-Real-IP         $remote_addr;
          176┆ proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
          177┆ proxy_set_header Authorization     $http_authorization;
          178┆ proxy_set_header Upgrade           "";
          179┆ proxy_set_header Connection        "";
            ⋮┆----------------------------------------
          191┆ proxy_http_version 1.1;
          192┆ proxy_set_header Host            $host;
          193┆ proxy_set_header X-Real-IP       $remote_addr;
          194┆ proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          195┆ proxy_set_header Upgrade         "";
          196┆ proxy_set_header Connection      "";
            ⋮┆----------------------------------------
          206┆ proxy_http_version 1.1;
          207┆ proxy_set_header Host            $host;
          208┆ proxy_set_header X-Real-IP       $remote_addr;
          209┆ proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          210┆ proxy_set_header Upgrade         "";
          211┆ proxy_set_header Connection      "";
            ⋮┆----------------------------------------
          221┆ proxy_http_version 1.1;
          222┆ proxy_set_header Host            $host;
          223┆ proxy_set_header X-Real-IP       $remote_addr;
          224┆ proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          225┆ proxy_set_header Upgrade         "";
          226┆ proxy_set_header Connection      "";
                
                
┌──────────────┐
│ Scan Summary │
└──────────────┘
✅ Scan completed successfully.
 • Findings: 22 (22 blocking)
 • Rules run: 507
 • Targets scanned: 544
 • Parsed lines: ~99.9%
 • Scan was limited to files tracked by git
 • For a detailed list of skipped files and lines, run semgrep with the --verbose flag
Ran 507 rules on 544 files: 22 findings.

```
## 3. Gitleaks (Secret Scanning)
```
```
## 4. ESLint + security (Frontend)
```

> circuit-breaker-ui@0.2.6 lint
> eslint .


/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/ipam/IPAddressesTab.jsx
   17:5  warning  Generic Object Injection Sink                                                                                   security/detect-object-injection
  162:5  warning  React Hook useMemo has an unnecessary dependency: 'onUpdate'. Either exclude it or remove the dependency array  react-hooks/exhaustive-deps

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/components/map/ContextMenu.jsx
  234:24  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/context/TenantContext.jsx
  45:6  warning  React Hook useEffect has a missing dependency: 'fetchTenants'. Either include it or remove the dependency array  react-hooks/exhaustive-deps

/home/shawnji/Documents/projects/CircuitBreaker/apps/frontend/src/pages/NotificationsPage.jsx
   96:14  warning  Generic Object Injection Sink                                                                                      security/detect-object-injection
  119:5   warning  React Hook useMemo has a missing dependency: 'handleToggleSink'. Either include it or remove the dependency array  react-hooks/exhaustive-deps
  240:68  warning  Generic Object Injection Sink                                                                                      security/detect-object-injection

✖ 7 problems (0 errors, 7 warnings)

```
## 5. Hadolint (Dockerfile lint)
```
Dockerfile.mono:39 DL3042 [1m[93mwarning[0m: Avoid use of cache directory with pip. Use `pip install --no-cache-dir <package>`
Dockerfile.mono:101 DL4006 [1m[93mwarning[0m: Set the SHELL option -o pipefail before RUN with a pipe in it. If you are using /bin/sh in an alpine image or if your shell is symlinked to busybox then consider explicitly setting your SHELL to /bin/ash, or disable this check
Dockerfile:20 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
Dockerfile:35 DL3042 [1m[93mwarning[0m: Avoid use of cache directory with pip. Use `pip install --no-cache-dir <package>`
Dockerfile:52 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
```
## 6. Checkov (IaC)
```
dockerfile scan results:

Passed checks: 198, Failed checks: 0, Skipped checks: 1


2026-03-25 16:54:00,307 [MainThread  ] [ERROR]  YAML error parsing ./site/search/search_index.json: while parsing a quoted scalar
  in "<unicode string>", line 1, column 104579
found invalid Unicode character escape code
  in "<unicode string>", line 1, column 107748
cloudformation scan results:

Passed checks: 0, Failed checks: 0, Skipped checks: 0, Parsing errors: 1

dockerfile scan results:

Passed checks: 784, Failed checks: 1, Skipped checks: 3

Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.mono.
	File: /Dockerfile.mono:1-158
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
github_actions scan results:

Passed checks: 443, Failed checks: 5, Skipped checks: 0

Check: CKV_GHA_7: "The build output cannot be affected by user parameters other than the build entry point and the top-level source location. GitHub Actions workflow_dispatch inputs MUST be empty. "
	FAILED for resource: on(Build Packages)
	File: /.github/workflows/build.yml:11-17

		11 |       version:
		12 |         description: "Version string (e.g. 0.1.3). Defaults to dev-<sha>."
		13 |         required: false
		14 |         default: ""
		15 | 
		16 | jobs:
		17 |   build:

Check: CKV_GHA_7: "The build output cannot be affected by user parameters other than the build entry point and the top-level source location. GitHub Actions workflow_dispatch inputs MUST be empty. "
	FAILED for resource: on(Release)
	File: /.github/workflows/release.yml:9-14

		9  |       version:
		10 |         description: "Version to release (e.g. 0.1.3, without the v prefix)"
		11 |         required: true
		12 | 
		13 | permissions:
		14 |   contents: write    # create GitHub Release, upload assets

Check: CKV2_GHA_1: "Ensure top-level permissions are not set to write-all"
	FAILED for resource: on(CodeQL)
	File: /.github/workflows/codeql.yml:16-17
Check: CKV2_GHA_1: "Ensure top-level permissions are not set to write-all"
	FAILED for resource: on(Build Packages)
	File: /.github/workflows/build.yml:0-1
Check: CKV2_GHA_1: "Ensure top-level permissions are not set to write-all"
	FAILED for resource: on(CI)
	File: /.github/workflows/ci.yml:0-1

```
## 7. Trivy (Filesystem)
```
2026-03-25T16:54:07-07:00	INFO	[vulndb] Need to update DB
2026-03-25T16:54:07-07:00	INFO	[vulndb] Downloading vulnerability DB...
2026-03-25T16:54:07-07:00	INFO	[vulndb] Downloading artifact...	repo="mirror.gcr.io/aquasec/trivy-db:2"
2.33 MiB / 88.14 MiB [--->_________________________________________________________________________________________________________________] 2.64% ? p/s ?7.72 MiB / 88.14 MiB [---------->__________________________________________________________________________________________________________] 8.76% ? p/s ?14.44 MiB / 88.14 MiB [------------------>________________________________________________________________________________________________] 16.38% ? p/s ?21.75 MiB / 88.14 MiB [------------------------->____________________________________________________________________________] 24.68% 32.33 MiB p/s ETA 2s29.28 MiB / 88.14 MiB [--------------------------------->____________________________________________________________________] 33.22% 32.33 MiB p/s ETA 1s36.69 MiB / 88.14 MiB [------------------------------------------>___________________________________________________________] 41.62% 32.33 MiB p/s ETA 1s42.95 MiB / 88.14 MiB [------------------------------------------------->____________________________________________________] 48.73% 32.53 MiB p/s ETA 1s48.89 MiB / 88.14 MiB [-------------------------------------------------------->_____________________________________________] 55.47% 32.53 MiB p/s ETA 1s56.83 MiB / 88.14 MiB [----------------------------------------------------------------->____________________________________] 64.47% 32.53 MiB p/s ETA 0s64.53 MiB / 88.14 MiB [-------------------------------------------------------------------------->___________________________] 73.21% 32.75 MiB p/s ETA 0s72.39 MiB / 88.14 MiB [----------------------------------------------------------------------------------->__________________] 82.13% 32.75 MiB p/s ETA 0s78.78 MiB / 88.14 MiB [------------------------------------------------------------------------------------------->__________] 89.38% 32.75 MiB p/s ETA 0s86.00 MiB / 88.14 MiB [--------------------------------------------------------------------------------------------------->__] 97.57% 32.94 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [---------------------------------------------------------------------------------------------------->] 100.00% 32.94 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [---------------------------------------------------------------------------------------------------->] 100.00% 32.94 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [---------------------------------------------------------------------------------------------------->] 100.00% 31.05 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [---------------------------------------------------------------------------------------------------->] 100.00% 31.05 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [---------------------------------------------------------------------------------------------------->] 100.00% 31.05 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [---------------------------------------------------------------------------------------------------->] 100.00% 29.05 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [---------------------------------------------------------------------------------------------------->] 100.00% 29.05 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [---------------------------------------------------------------------------------------------------->] 100.00% 29.05 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [---------------------------------------------------------------------------------------------------->] 100.00% 27.17 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [---------------------------------------------------------------------------------------------------->] 100.00% 27.17 MiB p/s ETA 0s88.14 MiB / 88.14 MiB [-------------------------------------------------------------------------------------------------------] 100.00% 19.89 MiB p/s 4.6s2026-03-25T16:54:14-07:00	INFO	[vulndb] Artifact successfully downloaded	repo="mirror.gcr.io/aquasec/trivy-db:2"
2026-03-25T16:54:14-07:00	INFO	[vuln] Vulnerability scanning is enabled
2026-03-25T16:54:14-07:00	INFO	[secret] Secret scanning is enabled
2026-03-25T16:54:14-07:00	INFO	[secret] If your scanning is slow, please try '--scanners vuln' to disable secret scanning
2026-03-25T16:54:14-07:00	INFO	[secret] Please see https://trivy.dev/docs/v0.69/guide/scanner/secret#recommendation for faster secret detection
2026-03-25T16:54:31-07:00	WARN	[secret] Invalid UTF-8 sequences detected in file content, replacing with empty string
2026-03-25T16:54:39-07:00	WARN	[secret] The size of the scanned file is too large. It is recommended to use `--skip-files` for this file to avoid high memory consumption.	file_path=".venv/lib/python3.12/site-packages/policy_sentry/shared/data/iam-definition.json" size (MB)=10
2026-03-25T16:55:05-07:00	INFO	[python] Licenses acquired from one or more METADATA files may be subject to additional terms. Use `--debug` flag to see all affected packages.
2026-03-25T16:55:05-07:00	INFO	Suppressing dependencies for development and testing. To display them, try the '--include-dev-deps' flag.
2026-03-25T16:55:05-07:00	INFO	Number of language-specific files	num=4
2026-03-25T16:55:05-07:00	INFO	[npm] Detecting vulnerabilities...
2026-03-25T16:55:05-07:00	INFO	[pip] Detecting vulnerabilities...
2026-03-25T16:55:05-07:00	INFO	[poetry] Detecting vulnerabilities...

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
│ .venv/lib/python3.12/site-packages/fastapi_users/authentication/transport/__pyc- │  text  │        -        │    1    │
│ ache__/bearer.cpython-312.pyc                                                    │        │                 │         │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.12/site-packages/moto/ec2/models/elastic_network_interfaces.py │  text  │        -        │    1    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.12/site-packages/moto/moto_proxy/ca.key                        │  text  │        -        │    1    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.12/site-packages/moto/moto_proxy/cert.key                      │  text  │        -        │    1    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.12/site-packages/uptime_kuma_api/__pycache__/api.cpython-312.- │  text  │        -        │    2    │
│ pyc                                                                              │        │                 │         │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.12/site-packages/uptime_kuma_api/api.py                        │  text  │        -        │    2    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.14/site-packages/fastapi_users/authentication/transport/__pyc- │  text  │        -        │    1    │
│ ache__/bearer.cpython-314.pyc                                                    │        │                 │         │
└──────────────────────────────────────────────────────────────────────────────────┴────────┴─────────────────┴─────────┘
Legend:
- '-': Not scanned
- '0': Clean (no security findings detected)


.venv/lib/python3.12/site-packages/fastapi_users/authentication/transport/__pycache__/bearer.cpython-312.pyc (secrets)
======================================================================================================================
Total: 1 (MEDIUM: 1, HIGH: 0, CRITICAL: 0)

MEDIUM: JWT (jwt-token)
══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
JWT token
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────



.venv/lib/python3.12/site-packages/moto/ec2/models/elastic_network_interfaces.py (secrets)
==========================================================================================
Total: 1 (MEDIUM: 0, HIGH: 0, CRITICAL: 1)

CRITICAL: AWS (aws-access-key-id)
══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
AWS Access Key ID
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 .venv/lib/python3.12/site-packages/moto/ec2/models/elastic_network_interfaces.py:81 (offset: 2822 bytes)
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  79           self.add_tags(tags or {})
  80           self.requester_managed = False
  81 [         self.requester_id = "********************"
  82           self.status = "available"
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────



.venv/lib/python3.12/site-packages/moto/moto_proxy/ca.key (secrets)
===================================================================
Total: 1 (MEDIUM: 0, HIGH: 1, CRITICAL: 0)

HIGH: AsymmetricPrivateKey (private-key)
══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
Asymmetric Private Key
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 .venv/lib/python3.12/site-packages/moto/moto_proxy/ca.key:2-27 (offset: 28 bytes)
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
   1   -----BEGIN PRIVATE KEY-----
   2 ┌ ****************************************************************
   3 │ ****************************************************************
   4 │ ****************************************************************
   5 │ ****************************************************************
   6 │ ****************************************************************
   7 │ ****************************************************************
   8 │ ****************************************************************
   9 │ ****************************************************************
  10 │ ****************************************************************
  11 │ ****************************************************************
  12 │ ****************************************************************
  13 │ ****************************************************************
  14 │ ****************************************************************
  15 │ ****************************************************************
  16 │ ****************************************************************
  17 │ ****************************************************************
  18 │ ****************************************************************
  19 │ ****************************************************************
  20 │ ****************************************************************
  21 │ ****************************************************************
  22 │ ****************************************************************
  23 │ ****************************************************************
  24 │ ****************************************************************
  25 │ ****************************************************************
  26 │ ****************************************************************
  27 └ ************************
  28   -----END PRIVATE KEY-----
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────



.venv/lib/python3.12/site-packages/moto/moto_proxy/cert.key (secrets)
=====================================================================
Total: 1 (MEDIUM: 0, HIGH: 1, CRITICAL: 0)

HIGH: AsymmetricPrivateKey (private-key)
══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
Asymmetric Private Key
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 .venv/lib/python3.12/site-packages/moto/moto_proxy/cert.key:2-27 (offset: 28 bytes)
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
   1   -----BEGIN PRIVATE KEY-----
   2 ┌ ****************************************************************
   3 │ ****************************************************************
   4 │ ****************************************************************
   5 │ ****************************************************************
   6 │ ****************************************************************
   7 │ ****************************************************************
   8 │ ****************************************************************
   9 │ ****************************************************************
  10 │ ****************************************************************
  11 │ ****************************************************************
  12 │ ****************************************************************
  13 │ ****************************************************************
  14 │ ****************************************************************
  15 │ ****************************************************************
  16 │ ****************************************************************
  17 │ ****************************************************************
  18 │ ****************************************************************
  19 │ ****************************************************************
  20 │ ****************************************************************
  21 │ ****************************************************************
  22 │ ****************************************************************
  23 │ ****************************************************************
  24 │ ****************************************************************
  25 │ ****************************************************************
  26 │ ****************************************************************
  27 └ ************************
  28   -----END PRIVATE KEY-----
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────



.venv/lib/python3.12/site-packages/uptime_kuma_api/__pycache__/api.cpython-312.pyc (secrets)
============================================================================================
Total: 2 (MEDIUM: 2, HIGH: 0, CRITICAL: 0)

MEDIUM: JWT (jwt-token)
══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
JWT token
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


MEDIUM: JWT (jwt-token)
══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
JWT token
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────



.venv/lib/python3.12/site-packages/uptime_kuma_api/api.py (secrets)
===================================================================
Total: 2 (MEDIUM: 2, HIGH: 0, CRITICAL: 0)

MEDIUM: JWT (jwt-token)
══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
JWT token
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 .venv/lib/python3.12/site-packages/uptime_kuma_api/api.py:414 (offset: 12249 bytes)
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 412           >>> api.login('INSERT_USERNAME', 'INSERT_PASSWORD')
 413           {
 414 [             'token': '***********************************************************************************************************************************'
 415           }
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


MEDIUM: JWT (jwt-token)
══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
JWT token
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 .venv/lib/python3.12/site-packages/uptime_kuma_api/api.py:3014 (offset: 129102 bytes)
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
3012               >>> api.login(username, password)
3013               {
3014 [                 'token': '***********************************************************************************************************************************'
3015               }
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────



.venv/lib/python3.14/site-packages/fastapi_users/authentication/transport/__pycache__/bearer.cpython-314.pyc (secrets)
======================================================================================================================
Total: 1 (MEDIUM: 1, HIGH: 0, CRITICAL: 0)

MEDIUM: JWT (jwt-token)
══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
JWT token
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


```
## 8. Trivy (Config / IaC)
```
2026-03-25T16:55:05-07:00	INFO	[misconfig] Misconfiguration scanning is enabled
2026-03-25T16:55:05-07:00	INFO	[checks-client] Need to update the checks bundle
2026-03-25T16:55:05-07:00	INFO	[checks-client] Downloading the checks bundle...
234.65 KiB / 234.65 KiB [------------------------------------------------------------------------------------------------------------] 100.00% ? p/s 100ms2026-03-25T16:55:51-07:00	INFO	Detected config files	num=19

Report Summary

┌──────────────────────────────────────────────────────────────────────────────────┬────────────────┬───────────────────┐
│                                      Target                                      │      Type      │ Misconfigurations │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/cloudformation/2010-05-15/resourc- │ cloudformation │         0         │
│ es-1.json                                                                        │                │                   │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/cloudwatch/2010-08-01/resources-1- │ cloudformation │         0         │
│ .json                                                                            │                │                   │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/dynamodb/2012-08-10/resources-1.j- │ cloudformation │         0         │
│ son                                                                              │                │                   │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/ec2/2014-10-01/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/ec2/2015-03-01/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/ec2/2015-04-15/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/ec2/2015-10-01/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/ec2/2016-04-01/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/ec2/2016-09-15/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/ec2/2016-11-15/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/glacier/2012-06-01/resources-1.js- │ cloudformation │         0         │
│ on                                                                               │                │                   │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/iam/2010-05-08/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/s3/2006-03-01/resources-1.json     │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/sns/2010-03-31/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ .venv/lib/python3.12/site-packages/boto3/data/sqs/2012-11-05/resources-1.json    │ cloudformation │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ Dockerfile                                                                       │   dockerfile   │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ Dockerfile.mono                                                                  │   dockerfile   │         1         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ docker/backend.Dockerfile                                                        │   dockerfile   │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ docker/frontend.Dockerfile                                                       │   dockerfile   │         0         │
└──────────────────────────────────────────────────────────────────────────────────┴────────────────┴───────────────────┘
Legend:
- '-': Not scanned
- '0': Clean (no security findings detected)


Dockerfile.mono (dockerfile)
============================
Tests: 27 (SUCCESSES: 26, FAILURES: 1)
Failures: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 0, HIGH: 1, CRITICAL: 0)

DS-0002 (HIGH): Specify at least 1 USER command in Dockerfile with non-root user as argument
══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
Running containers with 'root' user can lead to a container escape situation. It is a best practice to run containers as non-root users, which can be done by adding a 'USER' statement to the Dockerfile.

See https://avd.aquasec.com/misconfig/ds-0002
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────


```
## 9. npm audit (Frontend)
```
# npm audit report

picomatch  <=2.3.1 || 4.0.0 - 4.0.3
Severity: high
Picomatch has a ReDoS vulnerability via extglob quantifiers - https://github.com/advisories/GHSA-c2c7-rcm5-vvqj
Picomatch has a ReDoS vulnerability via extglob quantifiers - https://github.com/advisories/GHSA-c2c7-rcm5-vvqj
Picomatch: Method Injection in POSIX Character Classes causes incorrect Glob Matching - https://github.com/advisories/GHSA-3v7f-55p6-f55p
Picomatch: Method Injection in POSIX Character Classes causes incorrect Glob Matching - https://github.com/advisories/GHSA-3v7f-55p6-f55p
fix available via `npm audit fix`
node_modules/picomatch
node_modules/rollup-plugin-visualizer/node_modules/picomatch
node_modules/tinyglobby/node_modules/picomatch
node_modules/vite/node_modules/picomatch
node_modules/vitest/node_modules/picomatch

yaml  1.0.0 - 1.10.2 || 2.0.0 - 2.8.2
Severity: moderate
yaml is vulnerable to Stack Overflow via deeply nested YAML collections - https://github.com/advisories/GHSA-48c2-rrv3-qjmp
yaml is vulnerable to Stack Overflow via deeply nested YAML collections - https://github.com/advisories/GHSA-48c2-rrv3-qjmp
fix available via `npm audit fix`
node_modules/cosmiconfig/node_modules/yaml
node_modules/yaml

2 vulnerabilities (1 moderate, 1 high)

To address all issues, run:
  npm audit fix
```

