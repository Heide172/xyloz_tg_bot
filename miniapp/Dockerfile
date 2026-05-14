# Multi-stage: build SvelteKit static → serve через nginx.
FROM node:22-alpine AS build
WORKDIR /app

COPY miniapp/package.json miniapp/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY miniapp ./

# VITE_API_BASE_URL подставляется в build-time, по умолчанию относительный путь.
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

FROM nginx:alpine
COPY miniapp/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
