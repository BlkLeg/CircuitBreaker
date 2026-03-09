# ── Build stage ──────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY apps/frontend/package.json apps/frontend/package-lock.json* ./
# BuildKit cache mount keeps node_modules cache between builds (avoids re-downloading ~986 packages).
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# VERSION must land at /VERSION (one level above WORKDIR /app) so the
# syncversion script's readFileSync('../VERSION') resolves correctly.
COPY VERSION /VERSION
COPY apps/frontend/ ./

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
