# ── Build stage ──────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./

# Bake Sentry DSN into the JS bundle at build time (VITE_* vars are inlined
# by Vite and not available at runtime in the browser).
ARG VITE_SENTRY_DSN
ARG VITE_SENTRY_ENVIRONMENT=production
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN
ENV VITE_SENTRY_ENVIRONMENT=$VITE_SENTRY_ENVIRONMENT

RUN npm run build

# ── Serve stage ──────────────────────────────────────────────────────────────
# Use the official unprivileged nginx image — binds on 8080, no root required
FROM nginxinc/nginx-unprivileged:1.27-alpine

# Create the breaker26 user that matches the rest of the stack
USER root
RUN addgroup -S breaker26 && adduser -S -G breaker26 -H -s /sbin/nologin breaker26

COPY --from=builder /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
RUN chown -R breaker26:breaker26 /usr/share/nginx/html

USER breaker26

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
