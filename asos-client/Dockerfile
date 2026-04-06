FROM node:20-alpine AS builder

ARG VITE_BRAIN_HOST=localhost
ARG VITE_BRAIN_PORT=9090
ENV VITE_BRAIN_HOST=$VITE_BRAIN_HOST
ENV VITE_BRAIN_PORT=$VITE_BRAIN_PORT

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
