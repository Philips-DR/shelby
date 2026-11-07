# syntax=docker/dockerfile:1.7
#
# The web app: its own program, its own image. It calls the backend from the browser, so it needs
# nothing from the backend image and the backend needs nothing from it.
#
# Built from Shelby's root:  docker build -f docker/web.Dockerfile .   (or compose)

ARG NODE=24-slim

FROM node:${NODE} AS build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM node:${NODE}
WORKDIR /app/web
# `vite preview` serves dist/ and, through vite.config.ts, hands each page its token at serve
# time. Vite itself is a dev dependency, so node_modules comes along.
# Owned by the user it runs as: Vite writes a temporary copy of its config into node_modules.
COPY --chown=node:node --from=build /app/web/node_modules ./node_modules
COPY --chown=node:node --from=build /app/web/dist ./dist
COPY --chown=node:node web/package.json web/tsconfig.json web/index.html web/vite.config.ts ./
USER node
EXPOSE 8751
CMD ["npx", "vite", "preview", "--logLevel", "warn"]
