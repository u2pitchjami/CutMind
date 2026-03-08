# ============================================================
# 🐳 ComfyUI Router Dockerfile — version stable CUDA + FFmpeg
# ============================================================

# ---- 1️⃣ Base : Ubuntu + CUDA 12.4 runtime ----
FROM nvidia/cuda:13.1.1-cudnn-runtime-ubuntu24.04


# --- 1️⃣ Configuration de base ---
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# --- 2️⃣ Installation dépendances système ---
RUN apt-get update && apt-get install -y \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    libgl1 \
    python3 python3-pip python3-dev \
    tzdata \
 && ln -snf /usr/share/zoneinfo/Europe/Paris /etc/localtime \
 && echo "Europe/Paris" > /etc/timezone \
 && add-apt-repository -y ppa:ubuntuhandbook1/ffmpeg8 \
 && apt-get update \
 && apt-get install -y ffmpeg \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PIP_BREAK_SYSTEM_PACKAGES=1
# ---- 4️⃣ Vérification de ffmpeg ---
#RUN python3 -m pip install --upgrade pip setuptools wheel

# ---- 5️⃣ Installation des dépendances Python ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- 6️⃣ Copie du code source ----
COPY . .

# ---- 7️⃣ Préparation des répertoires ----
RUN mkdir -p /basedir/input /basedir/output

# ---- 8️⃣ Variables d’environnement ----
ENV PYTHONUNBUFFERED=1

# ---- 9️⃣ Commande par défaut ----
CMD ["python3", "-m", "comfyui_router.z_smartcut.smartcut"]
