# ── Build stage ──────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./
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
