FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install xray-core binary — auto-detect architecture
RUN ARCH=$(uname -m) && \
    case "$ARCH" in \
      x86_64)  XRAY_ARCH="64" ;; \
      aarch64) XRAY_ARCH="arm64-v8a" ;; \
      armv7l)  XRAY_ARCH="arm32-v7a" ;; \
      *)        echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac && \
    curl -Lo /tmp/xray.zip \
      "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-${XRAY_ARCH}.zip" && \
    unzip /tmp/xray.zip -d /usr/local/bin/ && \
    chmod +x /usr/local/bin/xray && \
    rm /tmp/xray.zip

COPY requirements-node.txt .
RUN pip install --no-cache-dir -r requirements-node.txt

COPY node_agent.py .

# Xray config directory — mounted from host at runtime
VOLUME ["/etc/xray"]

ENV XRAY_CONFIG_PATH=/etc/xray/config.json
ENV XRAY_BIN=/usr/local/bin/xray
ENV AGENT_PORT=8080

EXPOSE 8080

CMD ["python", "node_agent.py"]
