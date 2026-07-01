# Security Scan Report - Tue Jun 30 09:11:23 PM EDT 2026

## 1. Bandit (Python SAST)
```
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: B101
[main]	INFO	running on Python 3.14.6
[tester]	WARNING	nosec encountered (B608), but no failed test on file apps/backend/src/app/db/duckdb_client.py:83
[tester]	WARNING	nosec encountered (B608), but no failed test on file apps/backend/src/app/db/duckdb_client.py:91
[manager]	WARNING	Test in comment: read is not a test name or id, ignoring
[manager]	WARNING	Test in comment: only is not a test name or id, ignoring
[manager]	WARNING	Test in comment: path is not a test name or id, ignoring
[manager]	WARNING	Test in comment: probe is not a test name or id, ignoring
[manager]	WARNING	Test in comment: not is not a test name or id, ignoring
[manager]	WARNING	Test in comment: creating is not a test name or id, ignoring
[manager]	WARNING	Test in comment: temp is not a test name or id, ignoring
[manager]	WARNING	Test in comment: files is not a test name or id, ignoring
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_dhcp.py:57
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_dhcp.py:58
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_dhcp.py:60
[manager]	WARNING	Test in comment: mDNS is not a test name or id, ignoring
[manager]	WARNING	Test in comment: multicast is not a test name or id, ignoring
[manager]	WARNING	Test in comment: requires is not a test name or id, ignoring
[manager]	WARNING	Test in comment: binding is not a test name or id, ignoring
[manager]	WARNING	Test in comment: to is not a test name or id, ignoring
[manager]	WARNING	Test in comment: all is not a test name or id, ignoring
[manager]	WARNING	Test in comment: interfaces is not a test name or id, ignoring
[tester]	WARNING	nosec encountered (B104), but no failed test on file apps/backend/src/app/services/discovery_fingerprint.py:269
[manager]	WARNING	Test in comment: read is not a test name or id, ignoring
[manager]	WARNING	Test in comment: only is not a test name or id, ignoring
[manager]	WARNING	Test in comment: path is not a test name or id, ignoring
[manager]	WARNING	Test in comment: probe is not a test name or id, ignoring
[manager]	WARNING	Test in comment: not is not a test name or id, ignoring
[manager]	WARNING	Test in comment: creating is not a test name or id, ignoring
[manager]	WARNING	Test in comment: temp is not a test name or id, ignoring
[manager]	WARNING	Test in comment: files is not a test name or id, ignoring
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_service.py:94
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_service.py:96
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_service.py:97
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_service.py:98
[manager]	WARNING	Test in comment: numeric is not a test name or id, ignoring
[manager]	WARNING	Test in comment: sort is not a test name or id, ignoring
[manager]	WARNING	Test in comment: fallback is not a test name or id, ignoring
[manager]	WARNING	Test in comment: not is not a test name or id, ignoring
[manager]	WARNING	Test in comment: a is not a test name or id, ignoring
[manager]	WARNING	Test in comment: bind is not a test name or id, ignoring
[manager]	WARNING	Test in comment: address is not a test name or id, ignoring
[tester]	WARNING	nosec encountered (B104), but no failed test on file apps/backend/src/app/services/layout_service.py:66
[tester]	WARNING	nosec encountered (B104), but no failed test on file apps/backend/src/app/services/layout_service.py:66
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:03
Run started:2026-07-01 01:11:27.661229+00:00

Test results:
	No issues identified.

Code scanned:
	Total lines of code: 45298
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 6

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 122
		Medium: 0
		High: 0
	Total issues (by confidence):
		Undefined: 0
		Low: 0
		Medium: 8
		High: 114
Files skipped (0):
```
## 2. Semgrep (SAST)
```
               
               
┌─────────────┐
│ Scan Status │
└─────────────┘
  Scanning 548 files tracked by git with 1074 Code rules:
                                                                                                                        
  Language      Rules   Files          Origin      Rules                                                                
 ─────────────────────────────        ───────────────────                                                               
  <multilang>      58     366          Community    1074                                                                
  js              153     278                                                                                           
  python          243     241                                                                                           
  bash              4       6                                                                                           
  json              4       3                                                                                           
  yaml             35       2                                                                                           
  dockerfile        6       2                                                                                           
  ts              163       1                                                                                           
                                                                                                                        
                
                
┌──────────────┐
│ Scan Summary │
└──────────────┘
✅ Scan completed successfully.
 • Findings: 16 (16 blocking)
 • Rules run: 508
 • Targets scanned: 548
 • Parsed lines: ~99.9%
 • Scan was limited to files tracked by git
 • For a detailed list of skipped files and lines, run semgrep with the --verbose flag
Ran 508 rules on 548 files: 16 findings.
                    
                    
┌──────────────────┐
│ 16 Code Findings │
└──────────────────┘
                                         
    apps/backend/src/app/core/security.py
   ❯❯❱ python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
          ❰❰ Blocking ❱❱
          Detected JWT token decoded with 'verify=False'. This bypasses any integrity checks for the token
          which means the token could be tampered with by malicious actors. Ensure that the JWT token is  
          verified.                                                                                       
          Details: https://sg.run/6nyB                                                                    
                                                                                                          
           ▶▶┆ Autofix ▶ True
          273┆ "verify_signature": False
                                      
    apps/backend/src/app/core/users.py
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          ❰❰ Blocking ❱❱
          Detected a python logger call with a potential hardcoded secret "Could not read jwt_secret from   
          database; falling back to %s env" being logged. This may lead to secret credentials being exposed.
          Make sure that the logger is not logging  sensitive information.                                  
          Details: https://sg.run/ydNx                                                                      
                                                                                                            
          197┆ _logger.warning(
          198┆     "Could not read jwt_secret from database; falling back to %s env",
          199┆     CB_JWT_SECRET_ENV,
          200┆     exc_info=True,
          201┆ )
                                              
    apps/backend/src/app/services/db_backup.py
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          ❰❰ Blocking ❱❱
          Detected a python logger call with a potential hardcoded secret "Could not decrypt S3 secret key:
          %s" being logged. This may lead to secret credentials being exposed. Make sure that the logger is
          not logging  sensitive information.                                                              
          Details: https://sg.run/ydNx                                                                     
                                                                                                           
          173┆ _logger.warning(
          174┆     "Could not decrypt S3 secret key: %s", exc
          175┆ )  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-
               credential-disclosure  # noqa: E501                                                     
                                                   
    apps/backend/src/app/services/discovery_dhcp.py
    ❯❱ python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
          ❰❰ Blocking ❱❱
          Detected a python logger call with a potential hardcoded secret "DHCP SSH: credential decryption
          failed: %s" being logged. This may lead to secret credentials being exposed. Make sure that the 
          logger is not logging  sensitive information.                                                   
          Details: https://sg.run/ydNx                                                                    
                                                                                                          
          181┆ logger.warning(
          182┆     "DHCP SSH: credential decryption failed: %s", exc
          183┆ )  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-
               credential-disclosure  # noqa: E501                                                     
                                                          
    apps/backend/src/app/services/discovery_fingerprint.py
     ❱ python.lang.security.audit.network.bind.avoid-bind-to-all-interfaces
          ❰❰ Blocking ❱❱
          Running `socket.bind` to 0.0.0.0, or empty string could unexpectedly expose the server publicly as
          it binds to all available interfaces. Consider instead getting correct address from an environment
          variable or configuration file.                                                                   
          Details: https://sg.run/rdln                                                                      
                                                                                                            
          263┆ sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
          264┆ sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
          265┆ try:
          266┆     sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)
          267┆ except AttributeError:
          268┆     pass  # Not available on all platforms
          269┆ sock.bind(("", _MDNS_PORT))  # nosec B104 — mDNS multicast requires binding to all
               interfaces                                                                        
                     
    docker/nginx.conf
    ❯❱ generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling
          ❰❰ Blocking ❱❱
          Conditions for Nginx H2C smuggling identified. H2C smuggling allows upgrading HTTP/1.1 connections 
          to lesser-known HTTP/2 over cleartext (h2c) connections which can allow a bypass of reverse proxy  
          access controls, and lead to long-lived, unrestricted HTTP traffic directly to back-end servers. To
          mitigate: WebSocket support required: Allow only the value websocket for HTTP/1.1 upgrade headers  
          (e.g., Upgrade: websocket). WebSocket support not required: Do not forward Upgrade headers.        
          Details: https://sg.run/ploZ                                                                       
                                                                                                             
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

```
## 3. Gitleaks (Secret Scanning)
```
Finding:     1   [1;3;m-----BEGIN PRIVATE KEY-----[0m                                             
[1;3;m   2 ┌ **************************************************************...[0m
Secret:      [1;3;m-----BEGIN PRIVATE KEY-----[0m                                             
[1;3;m   2 ┌ **************************************************************...[0m
RuleID:      private-key
Entropy:     1.135028
File:        security_scan_report.md
Line:        482
Commit:      14b81dc846a2cee2af26e454e68242d0f8ab04d9
Author:      BlkLeg Shawnji
Email:       blacklegshawnji@gamil.com
Date:        2026-03-26T00:47:28Z
Fingerprint: 14b81dc846a2cee2af26e454e68242d0f8ab04d9:security_scan_report.md:private-key:482
Link:        https://github.com/BlkLeg/CircuitBreaker/blob/14b81dc846a2cee2af26e454e68242d0f8ab04d9/security_scan_report.md?plain=1#L482-L509

Finding:     1   [1;3;m-----BEGIN PRIVATE KEY-----[0m                                             
[1;3;m   2 ┌ **************************************************************...[0m
Secret:      [1;3;m-----BEGIN PRIVATE KEY-----[0m                                             
[1;3;m   2 ┌ **************************************************************...[0m
RuleID:      private-key
Entropy:     1.135028
File:        security_scan_report.md
Line:        524
Commit:      14b81dc846a2cee2af26e454e68242d0f8ab04d9
Author:      BlkLeg Shawnji
Email:       blacklegshawnji@gamil.com
Date:        2026-03-26T00:47:28Z
Fingerprint: 14b81dc846a2cee2af26e454e68242d0f8ab04d9:security_scan_report.md:private-key:524
Link:        https://github.com/BlkLeg/CircuitBreaker/blob/14b81dc846a2cee2af26e454e68242d0f8ab04d9/security_scan_report.md?plain=1#L524-L551

```
## 4. ESLint + security (Frontend)
```

> circuit-breaker-ui@0.3.0 lint
> eslint .


/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/components/ipam/IPAddressesTab.jsx
   18:5  warning  Generic Object Injection Sink                                                                                   security/detect-object-injection
  163:5  warning  React Hook useMemo has an unnecessary dependency: 'onUpdate'. Either exclude it or remove the dependency array  react-hooks/exhaustive-deps

/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/context/TenantContext.jsx
  45:6  warning  React Hook useEffect has a missing dependency: 'fetchTenants'. Either include it or remove the dependency array  react-hooks/exhaustive-deps

/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/pages/NotificationsPage.jsx
   96:14  warning  Generic Object Injection Sink                                                                                      security/detect-object-injection
  119:5   warning  React Hook useMemo has a missing dependency: 'handleToggleSink'. Either include it or remove the dependency array  react-hooks/exhaustive-deps
  240:68  warning  Generic Object Injection Sink                                                                                      security/detect-object-injection

/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/pages/settings/DeviceRolesSection.jsx
  77:26  warning  Generic Object Injection Sink  security/detect-object-injection
  78:12  warning  Generic Object Injection Sink  security/detect-object-injection

✖ 8 problems (0 errors, 8 warnings)

```
## 5. Hadolint (Dockerfile lint)
```
Dockerfile:20 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
Dockerfile:52 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
```
## 6. Checkov (IaC)
```
dockerfile scan results:

Passed checks: 198, Failed checks: 0, Skipped checks: 1


2026-06-30 21:12:39,124 [MainThread  ] [ERROR]  YAML error parsing ./site/search/search_index.json: while parsing a quoted scalar
  in "<unicode string>", line 1, column 104579
found invalid Unicode character escape code
  in "<unicode string>", line 1, column 107748
cloudformation scan results:

Passed checks: 0, Failed checks: 0, Skipped checks: 0, Parsing errors: 1

dockerfile scan results:

Passed checks: 784, Failed checks: 1, Skipped checks: 3

Check: CKV_DOCKER_3: "Ensure that a user for the container has been created"
	FAILED for resource: /Dockerfile.mono.
	File: /Dockerfile.mono:1-170
	Guide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/docker-policies/docker-policy-index/ensure-that-a-user-for-the-container-has-been-created

		Code lines for this resource are too many. Please use IDE of your choice to review the file.
github_actions scan results:

Passed checks: 594, Failed checks: 6, Skipped checks: 0

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
	FAILED for resource: on(Build Packages)
	File: /.github/workflows/build.yml:0-1
Check: CKV2_GHA_1: "Ensure top-level permissions are not set to write-all"
	FAILED for resource: on(CI)
	File: /.github/workflows/ci.yml:0-1
Check: CKV2_GHA_1: "Ensure top-level permissions are not set to write-all"
	FAILED for resource: on(CodeQL)
	File: /.github/workflows/codeql.yml:16-17
Check: CKV2_GHA_1: "Ensure top-level permissions are not set to write-all"
	FAILED for resource: on(Dev CI)
	File: /.github/workflows/dev-ci.yml:0-1

```
## 7. Trivy (Filesystem)
```
2026-07-01T01:12:42Z	INFO	[vulndb] Need to update DB
2026-07-01T01:12:42Z	INFO	[vulndb] Downloading vulnerability DB...
2026-07-01T01:12:42Z	INFO	[vulndb] Downloading artifact...	repo="mirror.gcr.io/aquasec/trivy-db:2"
12.40 MiB / 98.23 MiB [------->_____________________________________________________] 12.62% ? p/s ?26.25 MiB / 98.23 MiB [---------------->____________________________________________] 26.72% ? p/s ?40.20 MiB / 98.23 MiB [------------------------>____________________________________] 40.93% ? p/s ?55.22 MiB / 98.23 MiB [-------------------------->_____________________] 56.21% 71.42 MiB p/s ETA 0s69.30 MiB / 98.23 MiB [--------------------------------->______________] 70.55% 71.42 MiB p/s ETA 0s83.79 MiB / 98.23 MiB [---------------------------------------->_______] 85.30% 71.42 MiB p/s ETA 0s97.92 MiB / 98.23 MiB [----------------------------------------------->] 99.69% 71.40 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 71.40 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 71.40 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 66.83 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 66.83 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 66.83 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 62.52 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 62.52 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 62.52 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 58.48 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 58.48 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 58.48 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [---------------------------------------------->] 100.00% 54.71 MiB p/s ETA 0s98.23 MiB / 98.23 MiB [-------------------------------------------------] 100.00% 25.94 MiB p/s 4.0s2026-07-01T01:12:48Z	INFO	[vulndb] Artifact successfully downloaded	repo="mirror.gcr.io/aquasec/trivy-db:2"
2026-07-01T01:12:48Z	INFO	[vuln] Vulnerability scanning is enabled
2026-07-01T01:12:48Z	INFO	[secret] Secret scanning is enabled
2026-07-01T01:12:48Z	INFO	[secret] If your scanning is slow, please try '--scanners vuln' to disable secret scanning
2026-07-01T01:12:48Z	INFO	[secret] Please see https://trivy.dev/docs/v0.72/guide/scanner/secret#recommendation for faster secret detection
2026-07-01T01:13:04Z	WARN	[secret] Invalid UTF-8 sequences detected in file content, replacing with empty string
2026-07-01T01:13:19Z	WARN	[secret] The size of the scanned file is too large. It is recommended to use `--skip-files` for this file to avoid high memory consumption.	file_path=".venv/lib/python3.14/site-packages/policy_sentry/shared/data/iam-definition.json" size (MB)=10
2026-07-01T01:13:34Z	WARN	[pip] Unable to find python `site-packages` directory. License detection is skipped.	err="unable to find path to Python executable"
2026-07-01T01:13:34Z	INFO	[npm] Run "npm install" to collect the license information of packages	dir="node_modules"
2026-07-01T01:13:34Z	INFO	Suppressing dependencies for development and testing. To display them, try the '--include-dev-deps' flag.
2026-07-01T01:13:34Z	INFO	Number of language-specific files	num=4
2026-07-01T01:13:34Z	INFO	[npm] Detecting vulnerabilities...
2026-07-01T01:13:34Z	INFO	[pip] Detecting vulnerabilities...
2026-07-01T01:13:34Z	INFO	[poetry] Detecting vulnerabilities...

Report Summary

┌──────────────────────────────────────────────────────────────────────────────────┬────────┬─────────────────┬─────────┐
│                                      Target                                      │  Type  │ Vulnerabilities │ Secrets │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ apps/backend/poetry.lock                                                         │ poetry │        8        │    -    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ apps/backend/requirements.txt                                                    │  pip   │        0        │    -    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ apps/frontend/package-lock.json                                                  │  npm   │        0        │    -    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.14/site-packages/fastapi_users/authentication/transport/__pyc- │  text  │        -        │    1    │
│ ache__/bearer.cpython-314.pyc                                                    │        │                 │         │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.14/site-packages/moto/ec2/models/elastic_network_interfaces.py │  text  │        -        │    1    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.14/site-packages/moto/moto_proxy/ca.key                        │  text  │        -        │    1    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.14/site-packages/moto/moto_proxy/cert.key                      │  text  │        -        │    1    │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.14/site-packages/uptime_kuma_api/__pycache__/api.cpython-314.- │  text  │        -        │    2    │
│ pyc                                                                              │        │                 │         │
├──────────────────────────────────────────────────────────────────────────────────┼────────┼─────────────────┼─────────┤
│ .venv/lib/python3.14/site-packages/uptime_kuma_api/api.py                        │  text  │        -        │    2    │
└──────────────────────────────────────────────────────────────────────────────────┴────────┴─────────────────┴─────────┘
Legend:
- '-': Not scanned
- '0': Clean (no security findings detected)


apps/backend/poetry.lock (poetry)
=================================
Total: 8 (UNKNOWN: 0, LOW: 1, MEDIUM: 5, HIGH: 2, CRITICAL: 0)

┌────────────────────┬─────────────────────┬──────────┬──────────┬───────────────────┬───────────────┬──────────────────────────────────────────────────────────────┐
│      Library       │    Vulnerability    │ Severity │  Status  │ Installed Version │ Fixed Version │                            Title                             │
├────────────────────┼─────────────────────┼──────────┼──────────┼───────────────────┼───────────────┼──────────────────────────────────────────────────────────────┤
│ asyncssh           │ CVE-2026-45309      │ MEDIUM   │ fixed    │ 2.22.0            │ 2.23.0        │ AsyncSSH `AuthorizedKeysFile %u` path traversal allows       │
│                    │                     │          │          │                   │               │ attacker-selected authorized keys to authenticate a...       │
│                    │                     │          │          │                   │               │ https://avd.aquasec.com/nvd/cve-2026-45309                   │
├────────────────────┼─────────────────────┼──────────┤          ├───────────────────┼───────────────┼──────────────────────────────────────────────────────────────┤
│ msgpack            │ GHSA-6v7p-g79w-8964 │ HIGH     │          │ 1.1.2             │ 1.2.1         │ MessagePack for Python: Out-of-bounds read / crash on        │
│                    │                     │          │          │                   │               │ Unpacker reuse after a...                                    │
│                    │                     │          │          │                   │               │ https://github.com/advisories/GHSA-6v7p-g79w-8964            │
├────────────────────┼─────────────────────┤          ├──────────┼───────────────────┼───────────────┼──────────────────────────────────────────────────────────────┤
│ nltk               │ CVE-2026-54293      │          │ affected │ 3.9.4             │               │ nltk: NLTK: Information Disclosure via Path Traversal in     │
│                    │                     │          │          │                   │               │ `nltk.data.load()`                                           │
│                    │                     │          │          │                   │               │ https://avd.aquasec.com/nvd/cve-2026-54293                   │
├────────────────────┼─────────────────────┼──────────┼──────────┼───────────────────┼───────────────┼──────────────────────────────────────────────────────────────┤
│ pip                │ CVE-2026-3219       │ MEDIUM   │ fixed    │ 26.0.1            │ 26.1          │ pip: pip: Incorrect file installation due to improper        │
│                    │                     │          │          │                   │               │ archive handling                                             │
│                    │                     │          │          │                   │               │ https://avd.aquasec.com/nvd/cve-2026-3219                    │
│                    ├─────────────────────┤          │          │                   │               ├──────────────────────────────────────────────────────────────┤
│                    │ CVE-2026-6357       │          │          │                   │               │ pip: pip: Arbitrary code execution or information disclosure │
│                    │                     │          │          │                   │               │ via malicious wheel package...                               │
│                    │                     │          │          │                   │               │ https://avd.aquasec.com/nvd/cve-2026-6357                    │
├────────────────────┼─────────────────────┼──────────┤          ├───────────────────┼───────────────┼──────────────────────────────────────────────────────────────┤
│ pygments           │ CVE-2026-4539       │ LOW      │          │ 2.19.2            │ 2.20.0        │ pygments: Pygments: Denial of Service via inefficient        │
│                    │                     │          │          │                   │               │ regular expression processing in AdlLexer...                 │
│                    │                     │          │          │                   │               │ https://avd.aquasec.com/nvd/cve-2026-4539                    │
├────────────────────┼─────────────────────┼──────────┤          ├───────────────────┼───────────────┼──────────────────────────────────────────────────────────────┤
│ pymdown-extensions │ CVE-2026-46338      │ MEDIUM   │          │ 10.21             │ 10.21.3       │ Regression in pymdownx.snippets reintroduces sibling-prefix  │
│                    │                     │          │          │                   │               │ path traversal bypass despite restrict_base_path             │
│                    │                     │          │          │                   │               │ https://avd.aquasec.com/nvd/cve-2026-46338                   │
├────────────────────┼─────────────────────┤          │          ├───────────────────┼───────────────┼──────────────────────────────────────────────────────────────┤
│ pytest             │ CVE-2025-71176      │          │          │ 9.0.2             │ 9.0.3         │ pytest: pytest: Denial of Service or Privilege Escalation    │
│                    │                     │          │          │                   │               │ via insecure temporary directory...                          │
│                    │                     │          │          │                   │               │ https://avd.aquasec.com/nvd/cve-2025-71176                   │
└────────────────────┴─────────────────────┴──────────┴──────────┴───────────────────┴───────────────┴──────────────────────────────────────────────────────────────┘

.venv/lib/python3.14/site-packages/fastapi_users/authentication/transport/__pycache__/bearer.cpython-314.pyc (secrets)
======================================================================================================================
Total: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 1, HIGH: 0, CRITICAL: 0)

MEDIUM: JWT (jwt-token)
════════════════════════════════════════
JWT token
────────────────────────────────────────



.venv/lib/python3.14/site-packages/moto/ec2/models/elastic_network_interfaces.py (secrets)
==========================================================================================
Total: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 1)

CRITICAL: AWS (aws-access-key-id)
════════════════════════════════════════
AWS Access Key ID
────────────────────────────────────────
 .venv/lib/python3.14/site-packages/moto/ec2/models/elastic_network_interfaces.py:81 (offset: 2766 bytes)
────────────────────────────────────────
  79           self.add_tags(tags or {})
  80           self.requester_managed = False
  81 [         self.requester_id = "********************"
  82           self.status = "available"
────────────────────────────────────────



.venv/lib/python3.14/site-packages/moto/moto_proxy/ca.key (secrets)
===================================================================
Total: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 0, HIGH: 1, CRITICAL: 0)

HIGH: AsymmetricPrivateKey (private-key)
════════════════════════════════════════
Asymmetric Private Key
────────────────────────────────────────
 .venv/lib/python3.14/site-packages/moto/moto_proxy/ca.key:2-27 (offset: 28 bytes)
────────────────────────────────────────
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
────────────────────────────────────────



.venv/lib/python3.14/site-packages/moto/moto_proxy/cert.key (secrets)
=====================================================================
Total: 1 (UNKNOWN: 0, LOW: 0, MEDIUM: 0, HIGH: 1, CRITICAL: 0)

HIGH: AsymmetricPrivateKey (private-key)
════════════════════════════════════════
Asymmetric Private Key
────────────────────────────────────────
 .venv/lib/python3.14/site-packages/moto/moto_proxy/cert.key:2-27 (offset: 28 bytes)
────────────────────────────────────────
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
────────────────────────────────────────



.venv/lib/python3.14/site-packages/uptime_kuma_api/__pycache__/api.cpython-314.pyc (secrets)
============================================================================================
Total: 2 (UNKNOWN: 0, LOW: 0, MEDIUM: 2, HIGH: 0, CRITICAL: 0)

MEDIUM: JWT (jwt-token)
════════════════════════════════════════
JWT token
────────────────────────────────────────


MEDIUM: JWT (jwt-token)
════════════════════════════════════════
JWT token
────────────────────────────────────────



.venv/lib/python3.14/site-packages/uptime_kuma_api/api.py (secrets)
===================================================================
Total: 2 (UNKNOWN: 0, LOW: 0, MEDIUM: 2, HIGH: 0, CRITICAL: 0)

MEDIUM: JWT (jwt-token)
════════════════════════════════════════
JWT token
────────────────────────────────────────
 .venv/lib/python3.14/site-packages/uptime_kuma_api/api.py:414 (offset: 12249 bytes)
────────────────────────────────────────
 412           >>> api.login('INSERT_USERNAME', 'INSERT_PASSWORD')
 413           {
 414 [             'token': '***********************************************************************************************************************************'
 415           }
────────────────────────────────────────


MEDIUM: JWT (jwt-token)
════════════════════════════════════════
JWT token
────────────────────────────────────────
 .venv/lib/python3.14/site-packages/uptime_kuma_api/api.py:3032 (offset: 130301 bytes)
────────────────────────────────────────
3030               >>> api.login(username, password)
3031               {
3032 [                 'token': '***********************************************************************************************************************************'
3033               }
────────────────────────────────────────


```
## 8. Trivy (Config / IaC)
```
2026-07-01T01:13:35Z	INFO	[misconfig] Misconfiguration scanning is enabled
2026-07-01T01:13:35Z	INFO	[checks-client] Need to update the checks bundle
2026-07-01T01:13:35Z	INFO	[checks-client] Downloading the checks bundle...
234.65 KiB / 234.65 KiB [------------------------------------------------------] 100.00% ? p/s 100ms2026-07-01T01:13:53Z	INFO	Detected config files	num=20

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
│ Dockerfile                                                                       │   dockerfile   │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ Dockerfile.mono                                                                  │   dockerfile   │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ docker/backend.Dockerfile                                                        │   dockerfile   │         0         │
├──────────────────────────────────────────────────────────────────────────────────┼────────────────┼───────────────────┤
│ docker/frontend.Dockerfile                                                       │   dockerfile   │         0         │
└──────────────────────────────────────────────────────────────────────────────────┴────────────────┴───────────────────┘
Legend:
- '-': Not scanned
- '0': Clean (no security findings detected)

```
## 9. npm audit (Frontend)
```
found 0 vulnerabilities
```

