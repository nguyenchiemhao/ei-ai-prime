# widget image. Build context: the repository root (see compose.yaml).
# Build stage compiles the tokens and the app; the serve stage is a non-root nginx with static files.
FROM node:22.23.3-bookworm-slim AS build
WORKDIR /repo
COPY package.json package-lock.json tsconfig.base.json ./
COPY apps/admin/package.json apps/admin/package.json
COPY apps/widget/package.json apps/widget/package.json
COPY packages/api-types/package.json packages/api-types/package.json
COPY packages/design-tokens/package.json packages/design-tokens/package.json
COPY packages/i18n/package.json packages/i18n/package.json
RUN npm ci --ignore-scripts --workspace @ei-ai/widget
COPY packages packages
COPY apps/widget apps/widget
RUN npm run build --workspace @ei-ai/design-tokens && npm run build --workspace @ei-ai/widget

FROM nginxinc/nginx-unprivileged:1.30.5-alpine3.24
COPY apps/widget/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/widget/dist /usr/share/nginx/html
EXPOSE 8080
