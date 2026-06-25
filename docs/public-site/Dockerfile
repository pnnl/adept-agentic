FROM python:3.11-slim AS builder

WORKDIR /docs

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdocs build --strict

FROM nginx:alpine AS serve
COPY --from=builder /docs/site /usr/share/nginx/html
EXPOSE 80

FROM builder AS dev
EXPOSE 8000
ENTRYPOINT ["mkdocs"]
CMD ["serve", "--dev-addr=0.0.0.0:8000"]
