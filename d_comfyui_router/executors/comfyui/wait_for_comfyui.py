import time

import requests
from requests.exceptions import RequestException

from shared.utils.config import COMFYUI_URL
from shared.utils.logger import LoggerProtocol, ensure_logger

TIMEOUT = 180  # ⏱️ délai max d'attente en secondes
RETRY_INTERVAL = 5  # 🕔 pause entre chaque tentative


def wait_for_comfyui(
    logger: LoggerProtocol | None = None,
) -> bool:
    logger = ensure_logger(logger, __name__)
    logger.info(f"⏳ Attente du démarrage de ComfyUI sur {COMFYUI_URL}…")
    start_time = time.time()

    while True:
        try:
            response = requests.get(COMFYUI_URL, timeout=3)
            if response.status_code == 200:
                logger.info("✅ ComfyUI est prêt !")
                return True
        except RequestException:
            pass  # ignore et réessaie

        if time.time() - start_time > TIMEOUT:
            logger.warning(f"❌ Temps dépassé ({TIMEOUT}s) — ComfyUI n'est pas joignable.")
            exit(1)
            return False

        time.sleep(RETRY_INTERVAL)
