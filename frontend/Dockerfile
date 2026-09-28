# CivicPulse frontend — multi-stage: node builds, nginx serves.
#
# The Node toolchain never reaches the final image (§3.1). That is not tidiness: node_modules
# for this project is ~200 MB of build-time dependency and every megabyte of it would be attack
# surface sitting in production for no reason. The runtime stage contains static files and nginx.

# ---------- stage 1: build ----------
# Pinned to a digest, not just a tag: a tag is a moving pointer, and "works on my laptop,
# fails in CI" usually means the tag moved between the two builds (§5.2 Q1).
FROM node:22.12.0-alpine@sha256:51eff88af6dff26f59316b6e356188ffa2c422bd3c3b76f2556a2e7e89d080bd AS build

WORKDIR /app

# Dependencies before source, so a source edit does not invalidate the npm install layer.
# This ordering is the difference between a 4-second rebuild and a 90-second one.
COPY package.json package-lock.json ./
RUN npm ci

# Source last. Anything that changes often belongs in the latest possible layer.
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src

# Typecheck runs as part of the build: an image that compiles but does not typecheck is an
# image that lies about being buildable.
RUN npm run build

# ---------- stage 2: serve ----------
FROM nginx:1.27.3-alpine-slim@sha256:5a56ae385906c5b43ccc99379bce883aa93dc0556d7f705ba501d819925e8fa1 AS runtime

# No package installs at all: alpine-slim already ships envsubst and the entrypoint hooks in
# /docker-entrypoint.d/ that render /etc/nginx/templates/*.template at container start. Using
# the base image's own mechanism rather than replacing it keeps this stage to 21 MB.

# Only the built artefact crosses the stage boundary — no source, no node_modules, no Node.
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.sh /docker-entrypoint.d/40-civicpulse-config.sh

# nginx:alpine ships an unprivileged 'nginx' user. Running as root would mean a container
# escape starts with uid 0; binding 8080 instead of 80 is what makes non-root possible at all,
# since ports below 1024 need privileges.
RUN chmod +x /docker-entrypoint.d/40-civicpulse-config.sh \
    && sed -i 's/listen       80;/listen 8080;/' /etc/nginx/conf.d/default.conf 2>/dev/null || true \
    && chown -R nginx:nginx /usr/share/nginx/html /etc/nginx/conf.d \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid \
    && chown -R nginx:nginx /var/cache/nginx

USER nginx

EXPOSE 8080

# Checks this image's own nginx, not the backend: a frontend container is healthy when it can
# serve its own files, regardless of whether the API is having a bad day.
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/healthz || exit 1

# The base image's own entrypoint is kept, so it runs every script in /docker-entrypoint.d/ in
# numeric order: 20-envsubst-on-templates.sh renders our nginx template, then our 40- script
# writes config.js. Overriding ENTRYPOINT would silently disable the template rendering.
#
# Restricted to the variables we mean to substitute, so nginx's own $host, $remote_addr and
# $upstream survive envsubst untouched. NGINX_LOCAL_RESOLVERS is exported by the base image's
# 15-local-resolvers.envsh and feeds the resolver directive the /api/ proxy needs.
ENV NGINX_ENVSUBST_FILTER="BACKEND_URL|NGINX_LOCAL_RESOLVERS"

# Opts in to the base image's 15-local-resolvers.envsh, which reads the nameservers out of
# /etc/resolv.conf and exports NGINX_LOCAL_RESOLVERS for the template above. Without this the
# script returns early and the resolver directive renders unsubstituted. Deriving it at runtime
# is what makes one image work with Docker's 127.0.0.11 and with a cluster's DNS service.
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1

# Exec form: nginx becomes PID 1 and receives SIGTERM directly, so `docker stop` and a
# Kubernetes rolling update both shut it down gracefully instead of waiting for the 10s kill.
CMD ["nginx", "-g", "daemon off;"]
