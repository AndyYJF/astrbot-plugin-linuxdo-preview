FROM ghcr.io/thephaseless/byparr:3.0.4@sha256:874f719518f617d03a60e03411fc5d090647e1a877041e81f8dc965927c7deb6 AS sidecar-base

USER root
COPY --chown=1000:1000 sidecar /opt/linuxdo-sidecar/sidecar
RUN chmod 0755 \
      /opt/linuxdo-sidecar/sidecar/entrypoint.sh \
      /opt/linuxdo-sidecar/sidecar/session-entrypoint.sh \
      /opt/linuxdo-sidecar/sidecar/wait-for-x-display.sh

USER 1000
WORKDIR /app
ENV PYTHONPATH=/opt/linuxdo-sidecar:/app

FROM sidecar-base AS session-bootstrap

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      novnc \
      websockify \
      x11vnc \
      xdotool \
      xvfb \
    && rm -rf /var/lib/apt/lists/*

USER 1000
EXPOSE 6080
HEALTHCHECK NONE
ENTRYPOINT ["tini", "--", "/opt/linuxdo-sidecar/sidecar/session-entrypoint.sh"]

FROM sidecar-base AS runtime

EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=3).read()"]
ENTRYPOINT ["tini", "--", "/opt/linuxdo-sidecar/sidecar/entrypoint.sh"]
