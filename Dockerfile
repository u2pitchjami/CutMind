# ============================================================
# 🐳 ComfyUI Router Dockerfile
# Basé sur CUDA + Python + FFmpeg NVIDIA
# ============================================================

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# --- 1️⃣ Configuration de base ---
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# --- 2️⃣ Installation dépendances système ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 python3-pip ffmpeg git curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# --- 3️⃣ Installation des dépendances Python ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- 4️⃣ Copie du code source ---
COPY . .

# --- 5️⃣ Création des dossiers utilisés ---
RUN mkdir -p /basedir/input /basedir/output

# --- 6️⃣ Variables d’environnement par défaut ---
ENV PYTHONUNBUFFERED=1

# --- 7️⃣ Commande par défaut ---
CMD ["python3", "-m", "comfyui_router.main"]
