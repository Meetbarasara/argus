# Placeholder until M10 builds the real React app.
FROM nginx:alpine
RUN printf '%s' '<!doctype html><title>Argus</title><h1>Argus UI placeholder (arrives at M10)</h1>' \
    > /usr/share/nginx/html/index.html
