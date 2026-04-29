FROM mcr.microsoft.com/devcontainers/python:3.14

# System dependencies for OpenCV, Quarto, and general tooling
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget ca-certificates git \
    ffmpeg libglib2.0-0 libsm6 libxext6 libxrender1 libgl1 \
    gdebi-core make graphviz \
    bash bash-completion \
    pdf2svg fontconfig xz-utils tar perl \
    && rm -rf /var/lib/apt/lists/*

# Install Quarto
RUN curl -fsSL -o /tmp/quarto.deb \
    https://quarto.org/download/latest/quarto-linux-amd64.deb \
    && gdebi --non-interactive /tmp/quarto.deb \
    && rm -f /tmp/quarto.deb \
    && quarto --version
