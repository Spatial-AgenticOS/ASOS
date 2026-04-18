ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

ARG FERAL_VERSION=2026.4.9

RUN apk add --no-cache python3 py3-pip py3-wheel

WORKDIR /app
COPY feral-core/ ./feral-core/
COPY run.sh /

RUN pip3 install --no-cache-dir --break-system-packages "./feral-core[llm]"

RUN chmod a+x /run.sh
CMD ["/run.sh"]
