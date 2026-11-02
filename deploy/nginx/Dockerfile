FROM nginx:1.27-alpine

RUN apk add --no-cache openssl

COPY entrypoint.sh /usr/local/bin/nexaslot-nginx-entrypoint
RUN chmod +x /usr/local/bin/nexaslot-nginx-entrypoint

ENTRYPOINT ["/usr/local/bin/nexaslot-nginx-entrypoint"]
STOPSIGNAL SIGQUIT
