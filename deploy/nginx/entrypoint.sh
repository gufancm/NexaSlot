#!/bin/sh
set -eu

DOMAIN="${DOMAIN:?DOMAIN is required}"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
BOOTSTRAP_DIR="/etc/nginx/bootstrap"
TEMPLATE_DIR="/etc/nginx/nexaslot-templates"
RELOAD_SECONDS="${CERT_RELOAD_SECONDS:-3600}"

mkdir -p "$BOOTSTRAP_DIR" /etc/nginx/conf.d

if [ ! -s "$CERT_DIR/fullchain.pem" ] || [ ! -s "$CERT_DIR/privkey.pem" ]; then
  echo "No Let's Encrypt certificate for $DOMAIN; using a temporary self-signed certificate"
  openssl req -x509 -nodes -newkey rsa:2048 -days 30 \
    -keyout "$BOOTSTRAP_DIR/privkey.pem" \
    -out "$BOOTSTRAP_DIR/fullchain.pem" \
    -subj "/CN=$DOMAIN" \
    -addext "subjectAltName=DNS:$DOMAIN" >/dev/null 2>&1
fi

render_config() {
  if [ -s "$CERT_DIR/fullchain.pem" ] && [ -s "$CERT_DIR/privkey.pem" ]; then
    template="$TEMPLATE_DIR/https.conf.template"
  else
    template="$TEMPLATE_DIR/bootstrap.conf.template"
  fi
  DOMAIN="$DOMAIN" envsubst '${DOMAIN}' < "$template" \
    > /etc/nginx/conf.d/default.conf
}

render_config
nginx -t
nginx -g 'daemon off;' &
NGINX_PID=$!

reload_config() {
  while sleep "$RELOAD_SECONDS"; do
    render_config
    if nginx -t; then
      nginx -s reload || true
    fi
  done
}
reload_config &
RELOAD_PID=$!

stop() {
  kill -TERM "$RELOAD_PID" 2>/dev/null || true
  kill -QUIT "$NGINX_PID" 2>/dev/null || true
  wait "$NGINX_PID" 2>/dev/null || true
  exit 0
}
trap stop TERM INT QUIT

while kill -0 "$NGINX_PID" 2>/dev/null; do
  wait "$NGINX_PID" || true
done
