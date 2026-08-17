# --- build ---------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

# --- serve ---------------------------------------------------------------
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template

# BACKEND_URL is substituted into the nginx template at container start, so
# the same image works locally and in Cloud Run.
ENV BACKEND_URL=http://backend:8080 \
    PORT=8080

EXPOSE 8080
