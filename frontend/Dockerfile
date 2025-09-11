# syntax=docker/dockerfile:1

# Build #
FROM node:20.5.0-alpine AS build
WORKDIR /app

# Install deps using lockfile (faster & reproducible). Vite needs dev deps at build time.
COPY package*.json ./
RUN npm ci --include=dev --no-audit --fund=false

# Copy source and build
COPY . .
RUN npm run build

# Runtime #
FROM nginx:alpine

# Static assets
COPY --from=build /app/dist /usr/share/nginx/html

# Lightweight static health file (also served via /healthz route below)
RUN printf "OK\n" > /usr/share/nginx/html/healthz

# Hardened, cache-friendly nginx config for a Vite SPA
# - Cache immutable hashed assets aggressively
# - No-cache index.html so clients pick up new builds
# - SPA fallback for client-side routing
RUN cat > /etc/nginx/conf.d/default.conf <<'EOF'
server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  index index.html;

  # Long cache for hashed assets (Vite outputs content-hashed filenames)
  location ~* \.(?:js|css|mjs|json|png|jpg|jpeg|gif|svg|ico|webp|avif|woff2?)$ {
    try_files $uri =404;
    access_log off;
    add_header Cache-Control "public, max-age=31536000, immutable";
  }

  # HTML must not be cached so new builds propagate quickly
  location = /index.html {
    try_files $uri =404;
    add_header Cache-Control "no-store";
  }

  # Single-page app fallback for all other routes
  location / {
    try_files $uri $uri/ /index.html;
  }

  # Simple health endpoint for probes
  location = /healthz {
    access_log off;
    add_header Content-Type text/plain;
    return 200 "OK\n";
  }
}
EOF

EXPOSE 80

# Optional container healthcheck (works because alpine has busybox 'wget')
# DigitalOcean uses its own probes; this is helpful for local runs / docker compose.
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -qO- http://localhost/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
