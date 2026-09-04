FROM ubuntu:24.04

ARG TARGETARCH
ARG RUNNER_VERSION=2.337.0
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git jq libicu74 libkrb5-3 liblttng-ust1 \
    libssl3t64 libunwind8 zlib1g python3 python3-venv \
    libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libdrm2 libdbus-1-3 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libasound2t64 libcups2t64 libpango-1.0-0 libcairo2 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1001 runner \
    && mkdir -p /opt/hostedtoolcache \
    && chown runner:runner /opt/hostedtoolcache
WORKDIR /home/runner
RUN case "$TARGETARCH" in \
      arm64) arch=arm64; checksum=9b1dc70626422526e3c94767cf024896beb15da5342a3f4819bf2feac13e0393 ;; \
      amd64) arch=x64; checksum=70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613 ;; \
      *) exit 1 ;; \
    esac \
    && curl --fail --location --retry 3 --output /tmp/runner.tar.gz \
      "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${arch}-${RUNNER_VERSION}.tar.gz" \
    && echo "$checksum  /tmp/runner.tar.gz" | sha256sum --check \
    && tar xzf /tmp/runner.tar.gz \
    && rm /tmp/runner.tar.gz \
    && chown -R runner:runner /home/runner
COPY --chown=runner:runner entrypoint.sh /home/runner/entrypoint.sh
ENV RUNNER_TOOL_CACHE=/opt/hostedtoolcache
USER runner
ENTRYPOINT ["bash", "/home/runner/entrypoint.sh"]
