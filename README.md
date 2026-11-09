![Projet Logo](Comfyui-Video-Router.svg)

# 🎥 ComfyUI Video Router

## 🚀 Description
ComfyUI Video Router est un outil Python automatisé permettant d'envoyer des vidéos à **ComfyUI** pour traitement, avec sélection dynamique du workflow selon la résolution et support complet du GPU (NVENC).

## 🧩 Fonctionnalités principales
- Détection automatique de la résolution vidéo (`ffprobe`)
- Routage vers le bon workflow ComfyUI
- Envoi automatique via l’API HTTP
- Conversion H.265 CPU ou GPU (NVENC)
- Synchronisation intelligente de la sortie ComfyUI (`wait_for_output_v2`)
- Nettoyage automatique des fichiers temporaires
- Logs détaillés et persistants

## ⚙️ Images Docker disponibles
| Version | Description | Image |
|----------|--------------|-------|
| 🧠 CPU | Version de développement sans GPU | `u2pitchjami/comfyui_video_router:cpu` |
| ⚡ GPU | Version production avec accélération NVENC | `u2pitchjami/comfyui_video_router:nvidia` |

## 🧠 Exemple d'utilisation
```bash
docker run --rm   -v /mnt/user/Zin-progress/comfyui-nvidia/basedir:/basedir   -v /home/pipo/data/logs/comfyui_router:/app/logs   u2pitchjami/comfyui_video_router:cpu
```

## 🧰 Technologies
- Python 3.11
- FFmpeg + NVENC
- Docker / Docker Compose
- API ComfyUI
- Unraid

## 🧱 Structure du projet
```
comfyui_router/
├── main.py
├── comfyui/
│   ├── comfyui_command.py
│   ├── comfyui_workflow.py
│   ├── ffmpeg/ffmpeg_command.py
│   ├── output/output.py
│   └── utils/
│       ├── logger.py
│       ├── config.py
│       └── safe_runner.py
```

## 🧩 Auteurs
Projet développé par **u2pitchjami**  
Optimisation & assistance technique : DevOps Assistant 🧠

## 📄 Licence
MIT

## Analyse IA : Transformers ou Ollama

Le moteur de génération est configurable ; Transformers reste utilisé par défaut.
Voir [la configuration Ollama et les consignes de comparaison](docs/keywords-ollama.md).
