# Security Analysis: CircuitBreaker

## Executive Summary
This document provides a high-level overview of the security features implemented in the CircuitBreaker application. Designed with home lab enthusiasts in mind, the application incorporates a defense-in-depth approach to secure personal infrastructure, services, and data. The security model balances robust protection mechanisms with usability, ensuring that self-hosted environments are safeguarded against common vulnerabilities and unauthorized access without introducing excessive administrative overhead.

## Security Features

* **Multi-Factor Authentication (MFA):** Supports Time-based One-Time Password (TOTP) secondary authentication, along with backup recovery codes, to provide an additional layer of security beyond traditional passwords.
* **Role-Based Access Control (RBAC):** Utilizes a tiered permission model (Admin, Editor, Viewer, Demo) to ensure users have the appropriate level of access required for their role, adhering to the principle of least privilege.
* **Granular API Scopes:** Implements fine-grained access control over specific actions (read, write, delete) across various modules such as hardware, networks, and services.
* **Hardened Authentication:** Secures user credentials using industry-standard Bcrypt for password hashing and JSON Web Tokens (JWT) with audience validation for robust session management.
* **Salted API Tokens:** Employs salted HMAC hashes for API tokens to secure machine-to-machine communications, ensuring tokens are not exposed in plaintext within the database.
* **Configurable Rate Limiting:** Protects the application against brute-force attacks and denial-of-service (DoS) attempts with adjustable profiles (relaxed, normal, strict) that throttle requests to sensitive endpoints.
* **Audit Logging:** Maintains a comprehensive audit trail that records significant system events, configuration modifications, and access attempts to provide transparency and accountability.
* **Web Security Middleware:** Automatically enforces essential web security headers (such as HSTS and CSP) and provides Cross-Site Request Forgery (CSRF) protection to safeguard the web interface.
* **Sensitive Data Protection:** Incorporates log redaction utilities to prevent secrets, credentials, or Personally Identifiable Information (PII) from being inadvertently leaked into system logs.
* **Account Lockout Policy:** Mitigates automated password guessing and credential stuffing attacks by automatically locking user accounts following a predefined number of consecutive failed login attempts.

## Bottom Line
CircuitBreaker incorporates a comprehensive suite of modern security practices tailored for the self-hosted environment. By integrating features such as MFA, RBAC, API rate limiting, and extensive audit logging, the application provides home lab enthusiasts with a secure, resilient, and transparent platform to manage their infrastructure safely.