FROM ghcr.io/thephaseless/byparr:3.0.4@sha256:874f719518f617d03a60e03411fc5d090647e1a877041e81f8dc965927c7deb6

USER root
COPY --chown=1000:1000 sidecar /opt/linuxdo-sidecar/sidecar
RUN chmod 0755 /opt/linuxdo-sidecar/sidecar/entrypoint.sh

USER 1000
WORKDIR /app
ENV PYTHONPATH=/opt/linuxdo-sidecar:/app
ENTRYPOINT ["tini", "--", "/opt/linuxdo-sidecar/sidecar/entrypoint.sh"]
