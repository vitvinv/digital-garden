FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV CONDA_DIR=/opt/conda
ENV CONDA_ENV=pgl
ENV PATH=${CONDA_DIR}/envs/${CONDA_ENV}/bin:${CONDA_DIR}/bin:${PATH}

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    git \
    ca-certificates \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh \
    && bash /tmp/miniconda.sh -b -p ${CONDA_DIR} \
    && rm /tmp/miniconda.sh \
    && conda clean -afy

RUN conda create -n ${CONDA_ENV} --override-channels \
      -c openalea3 -c conda-forge \
      python=3.10 openalea.plantgl -y \
    && conda run -n ${CONDA_ENV} pip install --no-cache-dir trimesh numpy pytest \
    && conda clean -afy

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g --no-fund --no-audit @gltf-transform/cli \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

RUN python -c "from openalea.plantgl.all import *; print('PlantGL OK')" \
    && python -c "import trimesh; print('trimesh OK')" \
    && gltf-transform --version \
    && echo "Docker image ready"
