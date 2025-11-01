import time

import requests
from requests.exceptions import RequestException

from shared.utils.config import COMFYUI_URL
from shared.utils.logger import get_logger

logger = get_logger(__name__)

TIMEOUT = 120  # ⏱️ délai max d'attente en secondes
RETRY_INTERVAL = 5  # 🕔 pause entre chaque tentative


def wait_for_comfyui() -> None:
    print(f"⏳ Attente du démarrage de ComfyUI sur {COMFYUI_URL}…")
    start_time = time.time()

    while True:
        try:
            response = requests.get(COMFYUI_URL, timeout=3)
            if response.status_code == 200:
                print("✅ ComfyUI est prêt !")
                return
        except RequestException:
            pass  # ignore et réessaie

        if time.time() - start_time > TIMEOUT:
            print(f"❌ Temps dépassé ({TIMEOUT}s) — ComfyUI n'est pas joignable.")
            exit(1)

        time.sleep(RETRY_INTERVAL)
