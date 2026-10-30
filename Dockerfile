
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/shop.db \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /home/team

COPY requirements.txt .
# syntax=docker/dockerfile:1

# RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl dnsutils iproute2 iputils-ping net-tools nmap micro nano\
    procps sudo tmux traceroute wget \
    && useradd -m -s /bin/bash team \
    && mkdir -p /data \
    && echo 'team ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/team \
    && chmod 0440 /etc/sudoers.d/team \
    && chown -R team:team /home/team /data \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL --retry 5 \
    https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 \
    -o /usr/local/bin/ttyd \
    && chmod +x /usr/local/bin/ttyd

RUN --mount=type=cache,target=/root/.cache/pip \
pip install -r requirements.txt

COPY --chown=team:team app ./app
COPY entrypoint.sh /entrypoint.sh

RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

USER team

WORKDIR /home/team

EXPOSE 8000 7681

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
