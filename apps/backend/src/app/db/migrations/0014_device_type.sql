-- Migration 0014: Add device_type and device_confidence to scan_results
-- Safe to run multiple times (IF NOT EXISTS guards).

ALTER TABLE scan_results
    ADD COLUMN IF NOT EXISTS device_type VARCHAR(64),
    ADD COLUMN IF NOT EXISTS device_confidence SMALLINT;

COMMENT ON COLUMN scan_results.device_type IS
    'Fingerprinted device category: ios_device, android_device, fire_tv, router, printer, nas, smart_tv, ip_camera, windows_pc, chromecast, apple_tv, hypervisor, voip_phone, iot_device, linux_server, access_point, switch, firewall';

COMMENT ON COLUMN scan_results.device_confidence IS
    '0-100 classification confidence score from the fingerprinting engine';
