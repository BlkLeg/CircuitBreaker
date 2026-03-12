#!/bin/bash
set -e

# Stop and disable service
if systemctl is-active --quiet circuit-breaker.service 2>/dev/null; then
  systemctl stop circuit-breaker.service
fi
if systemctl is-enabled --quiet circuit-breaker.service 2>/dev/null; then
  systemctl disable circuit-breaker.service
fi
systemctl daemon-reload 2>/dev/null || true
