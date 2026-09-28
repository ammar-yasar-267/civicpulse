#!/bin/sh
# Writes /config.js at container start, from environment variables.
#
# This is the mechanism that keeps one image deployable to every environment (§2.1). A
# `vite build` inlines import.meta.env values into the static bundle, so an API URL chosen at
# build time would make the image environment-specific and destroy build-once-deploy-many for
# the frontend. Choosing it here, at start, is what avoids that.
#
# Runs as /docker-entrypoint.d/40-civicpulse-config.sh under the nginx base image's own
# entrypoint, after 20-envsubst-on-templates.sh has rendered nginx.conf from its template.
# Hence no envsubst call here: the base image already did that job.
set -eu

: "${API_BASE_URL:=}"           # empty => same origin, i.e. use the nginx /api proxy
: "${APP_ENVIRONMENT:=production}"

CONFIG_FILE=/usr/share/nginx/html/config.js

# Strip characters that would let a malformed env var break out of the JS string literal. The
# values are operator-supplied rather than user-supplied, so this is belt-and-braces, but a
# config file that can produce a syntax error takes the whole page down.
sanitise() {
    printf '%s' "$1" | tr -d '"\\\n\r'
}

cat > "$CONFIG_FILE" <<EOF
// Generated at container start by 40-civicpulse-config.sh. Do not edit; do not cache.
window.__CIVICPULSE_CONFIG__ = {
  apiBaseUrl: "$(sanitise "${API_BASE_URL}")",
  environment: "$(sanitise "${APP_ENVIRONMENT}")"
};
EOF

echo "civicpulse-frontend: environment=${APP_ENVIRONMENT} api_base=\"${API_BASE_URL:-same-origin}\" backend=${BACKEND_URL:-http://backend:8000}"
