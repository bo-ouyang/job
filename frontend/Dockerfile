FROM node:20.19-alpine AS build

WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_AGENT_ENABLED=true
ARG VITE_AGENT_DATA_SOURCE=api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_AGENT_ENABLED=$VITE_AGENT_ENABLED \
    VITE_AGENT_DATA_SOURCE=$VITE_AGENT_DATA_SOURCE
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/nginx/container.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
