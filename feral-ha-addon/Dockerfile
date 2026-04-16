ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip py3-wheel

WORKDIR /app
COPY feral-core/ ./feral-core/
COPY run.sh /

RUN pip3 install --no-cache-dir ./feral-core[llm]

RUN chmod a+x /run.sh
CMD ["/run.sh"]
