# Discovery Phase Analysis: Bottlenecks & Inefficiencies

This document outlines several components within the scanning workflows that introduce performance bottlenecks or implementation gaps. 

## 1. mDNS Unicast Probe Serialization (`discovery_fingerprint.py`)
**Location:** `_run_mdns_probe`
**Inefficiency:** 
The probe attempts to query 17 different `_MDNS_SERVICE_TYPES` to identify mobile and IoT devices. It runs these `aiozc.async_get_service_info` queries in a `for` loop, awaiting each one sequentially with a 0.5-second timeout. 
If an IP is inactive or simply doesn't respond to mDNS queries, it will hit the 0.5-second timeout 17 times. This results in **up to 8.5 seconds of blocking delay per host**.
* **Impact:** High. Limits overall scan throughput during the fingerprinting phase, even with an 8-slot semaphore.
* **Fix:** Box all 17 queries into tasks and use `asyncio.gather` for concurrent resolution.

## 2. LLDP and Router ARP SNMP Walks Sequential MIB Queries (`discovery_probes.py`)
**Locations:** `_run_router_arp_table`, `_run_lldp_probe`
**Inefficiency:** 
Both of these functions use `pysnmp`'s `next_cmd` to walk tables, but they call `_walk(oid)` iteratively for each column.
* In `_run_router_arp_table`, it walks the `ipNetToMediaTable` 3 separate times (MAC, IP, Type).
* In `_run_lldp_probe`, it walks the `lldpRemTable` 6 separate times.
* **Impact:** Medium. SNMP tables on enterprise switches can have hundreds or thousands of rows. Walking the same table 3 to 6 times sequentially multiplies the round-trip latency drastically.
* **Fix:** Combine the columns into a single `next_cmd()` execution by passing multiple `ObjectType(ObjectIdentity(oid))` arguments, letting the agent fetch the entire row per PDU constraint.

## 3. DHCP SSH Subprocess Wrap Failure (`discovery_dhcp.py`)
**Location:** `_run_router_ssh_dhcp`
**Inefficiency / Gap:**
For Tier 3 DHCP discovery, if `asyncssh` fails, a subprocess fallback is triggered. The subprocess executes the `ssh` binary directly and passes the password via `env={"SSHPASS": password}`. However, native OpenSSH does not read the `SSHPASS` environment variable directly. The `sshpass -e ssh` wrapper wrapper is required.
* **Impact:** Medium robustness gap. If the network drops Python's native `asyncssh`, the fallback will hang or immediately fail interactively instead of feeding the password.
* **Fix:** The command vector should be `["sshpass", "-e", "ssh", ...]` rather than directly executing `ssh`. 

## 4. Enhanced Bulk Merge N+1 Query & Transaction Overhead (`discovery_merge.py`)
**Location:** `enhanced_bulk_merge`
**Inefficiency:**
When accepting a large batch of scanned devices, the method iterates sequentially over `payload.result_ids`. For each result, it invokes `merge_scan_result` which triggers isolated `commit()`, `flush()`, and nested `savepoint` operations, as well as initiating `_emit_result_processed_event` sequentially via async loop calls.
* **Impact:** High (at scale). Doing O(N) database scalar reads and writes individually for a 200+ node scan will lock the UI for multiple seconds or exhaust database connections briefly.
* **Fix:** Load all target `ScanResult` and matching `Hardware` rows in a single batch query, update them in memory, and commit the session exactly once.

## 5. Nmap Parser Bottleneck (`discovery_probes.py`)
**Location:** `_run_nmap_scan`
**Inefficiency:**
The execution leverages `python-nmap` initialized in an executor block. `python-nmap` waits for the scan to finish, ingests the massive XML output entirely into Python objects, and then iterates. While acceptable for `/24` subnets, large `/16` sweeps can have 10-20MB XML sizes that take tens of seconds to ingest, blocking an executor worker lock strictly parsing XML.
* **Impact:** Moderate. Python's GIL blocks other CPU-bound tasks during the large XML `xml.etree` parse within `python-nmap`.
* **Fix:** Consider streaming the XML output asynchronously (using `xml.etree.ElementTree.iterparse` via a direct subprocess pipe) if large subnets are meant to be scaled up.

## 6. Massive Subnet Scapy Sweeps Memory Exhaustion (`discovery_probes.py`)
**Location:** `_run_arp_scan`
**Inefficiency:**
If the fallback `scapy` ARP scan is engaged on a massive subnet (e.g., a `/8` or `/12`), Scapy attempts to build the entire payload array into memory before streaming `srp(Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=cidr))`. For a `/8`, this constructs over 16.7 million packets in memory synchronously.
* **Impact:** Critical for massive subnets. Will instantly result in `OOM` (Out of Memory) crashes or total CPU lockups for several minutes.
* **Fix:** `scapy` should not be utilized for sweeps larger than `/16`. For massive scale, raw socket iteration or batching (sweeping in chunks of `/24`) is fundamentally required.

## 7. Granular Loop Commits during Ingestion (`discovery_service.py`)
**Location:** `_scan_import`
**Inefficiency:** 
During Phase 3 scan ingestion, the orchestrator iterates over `raw_results` (`for raw in raw_results:`). Inside this loop, it constructs the `ScanResult`, calculates conflicts, and then issues `db.commit()`—all *inside* the loop.
* **Impact:** Severe DB Concurrency bottleneck on large subnets. If an Nmap `/8` or `/16` sweep returns 5,000 active devices, this logic forces 5,000 completely separate database transactions to initialize, commit, and sync continuously. 
* **Fix:** The `db.commit()` must be deferred to outside the `for` loop, moving entirely to a bulk insertion philosophy where the session maintains the objects in memory and flushes them efficiently.
