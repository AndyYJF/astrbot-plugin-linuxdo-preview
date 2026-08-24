FROM python:3.12.11-slim-bookworm

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fluxbox \
        novnc \
        websockify \
        x11vnc \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY sidecar/requirements.txt /app/sidecar/requirements.txt
RUN pip install --no-cache-dir -r /app/sidecar/requirements.txt \
    && python -m playwright install --with-deps chromium \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin pwuser
COPY sidecar /app/sidecar
RUN chmod 0755 /app/sidecar/entrypoint.sh \
    && mkdir -p /var/lib/linuxdo-browser \
    && chmod -R a+rX /ms-playwright \
    && chown -R pwuser:pwuser /app /var/lib/linuxdo-browser

USER pwuser
ENV DISPLAY=:99
ENTRYPOINT ["/app/sidecar/entrypoint.sh"]
