# Reuse the environment already downloaded for the Armbian image build.
FROM ghcr.io/armbian/docker-armbian-build:armbian-debian-trixie-latest
RUN apt-get update && apt-get install -y --no-install-recommends rauc squashfs-tools \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/bin/bash"]
