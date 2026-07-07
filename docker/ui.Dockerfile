# Build the React SPA, then serve the static bundle with nginx (which also proxies
# /api → api:8080 so the browser needs no CORS in prod — 08 #25). Build context is repo root.
FROM node:22-alpine AS build
WORKDIR /app
COPY ui/package.json ./
RUN npm install
COPY ui/ ./
RUN npm run build

FROM nginx:alpine
COPY ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
