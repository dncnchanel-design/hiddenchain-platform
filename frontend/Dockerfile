FROM node:22-alpine AS builder

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build:production

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
RUN sed -i -E 's|^pid[[:space:]]+[^;]+;|pid /tmp/nginx.pid;|' /etc/nginx/nginx.conf \
    && sed -i -E 's|^error_log[[:space:]]+[^;]+;|error_log /dev/stderr notice;|' /etc/nginx/nginx.conf \
    && sed -i -E 's|^[[:space:]]*access_log[[:space:]]+[^;]+;|    access_log /dev/stdout main;|' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /etc/nginx/conf.d
EXPOSE 8080
USER nginx
