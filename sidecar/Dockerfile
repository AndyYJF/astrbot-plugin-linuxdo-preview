FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

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
RUN pip install --no-cache-dir -r /app/sidecar/requirements.txt
COPY sidecar /app/sidecar
RUN chmod 0755 /app/sidecar/entrypoint.sh \
    && mkdir -p /var/lib/linuxdo-browser \
    && chown -R pwuser:pwuser /app /var/lib/linuxdo-browser

USER pwuser
ENV DISPLAY=:99
ENTRYPOINT ["/app/sidecar/entrypoint.sh"]
