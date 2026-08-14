# Security Scan Report - Fri Aug 14 11:40:17 AM EDT 2026

_Gate mode active — HIGH/CRIT findings will cause non-zero exit._
## 0. Suppression metadata
```
security suppression metadata valid: /home/shawnji/Documents/Projects/CircuitBreaker/specs/1.0.0/release-control/security-suppressions.json
```
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
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_service.py:106
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_service.py:108
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_service.py:109
[tester]	WARNING	nosec encountered (B108), but no failed test on file apps/backend/src/app/services/discovery_service.py:110
[manager]	WARNING	Test in comment: numeric is not a test name or id, ignoring
[manager]	WARNING	Test in comment: sort is not a test name or id, ignoring
[manager]	WARNING	Test in comment: fallback is not a test name or id, ignoring
[manager]	WARNING	Test in comment: not is not a test name or id, ignoring
[manager]	WARNING	Test in comment: a is not a test name or id, ignoring
[manager]	WARNING	Test in comment: bind is not a test name or id, ignoring
[manager]	WARNING	Test in comment: address is not a test name or id, ignoring
[tester]	WARNING	nosec encountered (B104), but no failed test on file apps/backend/src/app/services/layout_service.py:66
[tester]	WARNING	nosec encountered (B104), but no failed test on file apps/backend/src/app/services/layout_service.py:66
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:04
Run started:2026-08-14 15:40:21.857016+00:00

Test results:
	No issues identified.

Code scanned:
	Total lines of code: 58866
	Total lines skipped (#nosec): 0
	Total potential issues skipped due to specifically being disabled (e.g., #nosec BXXX): 6

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 132
		Medium: 2
		High: 0
	Total issues (by confidence):
		Undefined: 0
		Low: 0
		Medium: 14
		High: 120
Files skipped (0):
```
## 2. Semgrep (SAST)
```
               
               
┌─────────────┐
│ Scan Status │
└─────────────┘
  Scanning 669 files tracked by git with 310 Code rules:
                                                                                                                        
  Language      Rules   Files          Origin      Rules                                                                
 ─────────────────────────────        ───────────────────                                                               
  <multilang>      45     669          Community     310                                                                
  js               32     354                                                                                           
  python           84     283                                                                                           
  json              1       5                                                                                           
  yaml              9       2                                                                                           
  dockerfile        4       2                                                                                           
  ts               34       1                                                                                           
                                                                                                                        
                
                
┌──────────────┐
│ Scan Summary │
└──────────────┘
✅ Scan completed successfully.
 • Findings: 0 (0 blocking)
 • Rules run: 176
 • Targets scanned: 669
 • Parsed lines: ~99.9%
 • Scan was limited to files tracked by git
 • For a detailed list of skipped files and lines, run semgrep with the --verbose flag
Ran 176 rules on 669 files: 0 findings.
(need more rules? `semgrep login` for additional free Semgrep Registry rules)


A new version of Semgrep is available. See https://semgrep.dev/docs/upgrading
If Semgrep missed a finding, please send us feedback to let us know!
See https://semgrep.dev/docs/reporting-false-negatives/
```
## 3. Gitleaks (Secret Scanning)
```

    ○
    │╲
    │ ○
    ○ ░
    ░    gitleaks

[90m3:40PM[0m [32mINF[0m [1mscanned ~70544958 bytes (70.54 MB) in 9.97s[0m
[90m3:40PM[0m [32mINF[0m [1mno leaks found[0m
```
## 4. ESLint + security (Frontend)
```

> circuit-breaker-ui@0.3.5 lint
> eslint .


/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/components/agents/AgentApprovalModal.jsx
  246:30  warning  Generic Object Injection Sink  security/detect-object-injection
  250:37  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/components/discovery/ScanProgressAnimation.jsx
  68:26  warning  Variable Assigned to Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/components/ipam/IPAddressesTab.jsx
   18:5  warning  Generic Object Injection Sink                                                                                   security/detect-object-injection
  163:5  warning  React Hook useMemo has an unnecessary dependency: 'onUpdate'. Either exclude it or remove the dependency array  react-hooks/exhaustive-deps

/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/data/remediationGuides.js
  86:10  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/pages/AgentDetailPage.jsx
   77:54  warning  Generic Object Injection Sink  security/detect-object-injection
   99:44  warning  Generic Object Injection Sink  security/detect-object-injection
  120:19  warning  Generic Object Injection Sink  security/detect-object-injection
  361:34  warning  Generic Object Injection Sink  security/detect-object-injection
  543:44  warning  Generic Object Injection Sink  security/detect-object-injection
  576:25  warning  Generic Object Injection Sink  security/detect-object-injection
  577:25  warning  Generic Object Injection Sink  security/detect-object-injection
  670:46  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/pages/AgentsPage.jsx
   41:21  warning  Generic Object Injection Sink  security/detect-object-injection
  197:28  warning  Generic Object Injection Sink  security/detect-object-injection

/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/pages/NotificationsPage.jsx
   96:14  warning  Generic Object Injection Sink                                                                                      security/detect-object-injection
  119:5   warning  React Hook useMemo has a missing dependency: 'handleToggleSink'. Either include it or remove the dependency array  react-hooks/exhaustive-deps
  240:68  warning  Generic Object Injection Sink                                                                                      security/detect-object-injection

/home/shawnji/Documents/Projects/CircuitBreaker/apps/frontend/src/pages/settings/DeviceRolesSection.jsx
  77:26  warning  Generic Object Injection Sink  security/detect-object-injection
  78:12  warning  Generic Object Injection Sink  security/detect-object-injection

✖ 21 problems (0 errors, 21 warnings)

```
## 5. Hadolint (Dockerfile lint)
```
Dockerfile.mono:60 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
Dockerfile.mono:194 DL3025 [1m[93mwarning[0m: Use arguments JSON notation for CMD and ENTRYPOINT arguments
Dockerfile:20 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
Dockerfile:52 DL3008 [1m[93mwarning[0m: Pin versions in apt get install. Instead of `apt-get install <package>` use `apt-get install <package>=<version>`
Dockerfile:105 DL3066 [92minfo[0m: Non-numeric user-id may not be resolvable by host system
Dockerfile:110 DL3025 [1m[93mwarning[0m: Use arguments JSON notation for CMD and ENTRYPOINT arguments
```
## 6. Checkov (IaC)
```
dockerfile scan results:

Passed checks: 198, Failed checks: 0, Skipped checks: 1


dockerfile scan results:

Passed checks: 198, Failed checks: 0, Skipped checks: 1

github_actions scan results:

Passed checks: 742, Failed checks: 0, Skipped checks: 2


```
## 7. Trivy (Filesystem)
```
2026-08-14T15:41:01Z	INFO	[vulndb] Need to update DB
2026-08-14T15:41:01Z	INFO	[vulndb] Downloading vulnerability DB...
2026-08-14T15:41:01Z	INFO	[vulndb] Downloading artifact...	repo="mirror.gcr.io/aquasec/trivy-db:2"
11.83 MiB / 106.87 MiB [------>_____________________________________________________] 11.07% ? p/s ?26.41 MiB / 106.87 MiB [-------------->_____________________________________________] 24.71% ? p/s ?39.63 MiB / 106.87 MiB [---------------------->_____________________________________] 37.08% ? p/s ?52.84 MiB / 106.87 MiB [----------------------->_______________________] 49.44% 68.37 MiB p/s ETA 0s66.06 MiB / 106.87 MiB [----------------------------->_________________] 61.81% 68.37 MiB p/s ETA 0s81.85 MiB / 106.87 MiB [----------------------------------->___________] 76.59% 68.37 MiB p/s ETA 0s96.66 MiB / 106.87 MiB [------------------------------------------>____] 90.44% 68.67 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 68.67 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 68.67 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 65.34 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 65.34 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 65.34 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 61.12 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 61.12 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 61.12 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 57.18 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 57.18 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 57.18 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 53.49 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 53.49 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-------------------------------------------->] 100.00% 53.49 MiB p/s ETA 0s106.87 MiB / 106.87 MiB [-----------------------------------------------] 100.00% 25.56 MiB p/s 4.4s2026-08-14T15:41:08Z	INFO	[vulndb] Artifact successfully downloaded	repo="mirror.gcr.io/aquasec/trivy-db:2"
2026-08-14T15:41:08Z	INFO	[vuln] Vulnerability scanning is enabled
2026-08-14T15:41:08Z	INFO	[secret] Secret scanning is enabled
2026-08-14T15:41:08Z	INFO	[secret] If your scanning is slow, please try '--scanners vuln' to disable secret scanning
2026-08-14T15:41:08Z	INFO	[secret] Please see https://trivy.dev/docs/v0.74/guide/scanner/secret#recommendation for faster secret detection
2026-08-14T15:41:16Z	INFO	[npm] Run "npm install" to collect the license information of packages	dir="node_modules"
2026-08-14T15:41:16Z	WARN	[pip] Unable to find python `site-packages` directory. License detection is skipped.	err="unable to find path to Python executable"
2026-08-14T15:41:16Z	INFO	Suppressing dependencies for development and testing. To display them, try the '--include-dev-deps' flag.
2026-08-14T15:41:16Z	INFO	Number of language-specific files	num=5
2026-08-14T15:41:16Z	INFO	[gomod] Detecting vulnerabilities...
2026-08-14T15:41:16Z	INFO	[npm] Detecting vulnerabilities...
2026-08-14T15:41:16Z	INFO	[pip] Detecting vulnerabilities...
2026-08-14T15:41:16Z	INFO	[poetry] Detecting vulnerabilities...
2026-08-14T15:41:16Z	WARN	Using severities from other vendors for some vulnerabilities. Read https://trivy.dev/docs/v0.74/guide/scanner/vulnerability#severity-selection for details.

Report Summary

┌─────────────────────────────────┬────────┬─────────────────┬─────────┐
│             Target              │  Type  │ Vulnerabilities │ Secrets │
├─────────────────────────────────┼────────┼─────────────────┼─────────┤
│ apps/agent/go.mod               │ gomod  │        0        │    -    │
├─────────────────────────────────┼────────┼─────────────────┼─────────┤
│ apps/backend/poetry.lock        │ poetry │        0        │    -    │
├─────────────────────────────────┼────────┼─────────────────┼─────────┤
│ apps/backend/requirements.txt   │  pip   │        0        │    -    │
├─────────────────────────────────┼────────┼─────────────────┼─────────┤
│ apps/frontend/package-lock.json │  npm   │        0        │    -    │
├─────────────────────────────────┼────────┼─────────────────┼─────────┤
│ package-lock.json               │  npm   │        0        │    -    │
└─────────────────────────────────┴────────┴─────────────────┴─────────┘
Legend:
- '-': Not scanned
- '0': Clean (no security findings detected)

```
## 8. Trivy (Config / IaC)
```
2026-08-14T15:41:19Z	INFO	[misconfig] Misconfiguration scanning is enabled
2026-08-14T15:41:19Z	INFO	[checks-client] Need to update the checks bundle
2026-08-14T15:41:19Z	INFO	[checks-client] Downloading the checks bundle...
234.65 KiB / 234.65 KiB [------------------------------------------------------] 100.00% ? p/s 100ms2026-08-14T15:41:36Z	INFO	Detected config files	num=5

Report Summary

┌────────────────────────────┬────────────┬───────────────────┐
│           Target           │    Type    │ Misconfigurations │
├────────────────────────────┼────────────┼───────────────────┤
│ Dockerfile                 │ dockerfile │         0         │
├────────────────────────────┼────────────┼───────────────────┤
│ Dockerfile.mono            │ dockerfile │         0         │
├────────────────────────────┼────────────┼───────────────────┤
│ apps/agent/e2e/Dockerfile  │ dockerfile │         0         │
├────────────────────────────┼────────────┼───────────────────┤
│ docker/backend.Dockerfile  │ dockerfile │         0         │
├────────────────────────────┼────────────┼───────────────────┤
│ docker/frontend.Dockerfile │ dockerfile │         0         │
└────────────────────────────┴────────────┴───────────────────┘
Legend:
- '-': Not scanned
- '0': Clean (no security findings detected)

```
## 9. npm audit (Frontend)
```
found 0 vulnerabilities
```
## 9b. pip-audit (Python dependencies)
```
No known vulnerabilities found
```
## 10. Go vulnerability scan (Agent)
```
=== Symbol Results ===

No vulnerabilities found.

Your code is affected by 0 vulnerabilities.
This scan also found 0 vulnerabilities in packages you import and 1
vulnerability in modules you require, but your code doesn't appear to call these
vulnerabilities.
Use '-show verbose' for more details.
```

## ✅ Gate Result: All scans passed (zero HIGH/CRIT)
