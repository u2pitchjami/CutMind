from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

import requests

from shared.models.exceptions import CutMindError, ErrCode, get_step_ctx
from shared.utils.config import COMFYUI_URL

# ---------------------------------------------------------------------------
# Typage des callbacks
# ---------------------------------------------------------------------------
OnStartCallback = Callable[[str], None]
OnProgressCallback = Callable[[str, str], None]
OnCompleteCallback = Callable[[str, list[str]], None]
OnErrorCallback = Callable[[str | None, str], None]


class ComfyClientREST:
    """
    Client REST pour ComfyUI.

    Version NON BLOQUANTE :
    - POST /prompt  → lance un workflow et renvoie prompt_id
    - GET /history  → utilisé seulement pour un log d'activité (optionnel)
    - La détection de fin réelle est déléguée au OutputManager (fichiers générés)

    Pourquoi ?
    → Certaines versions de ComfyUI renvoient 'success' trop tôt,
      donc /history/<id> ne peut pas être utilisé pour savoir la fin réelle.
    """

    def __init__(self, host: str = COMFYUI_URL) -> None:
        self.base_url = host

        self.on_start: OnStartCallback | None = None
        self.on_progress: OnProgressCallback | None = None
        self.on_complete: OnCompleteCallback | None = None
        self.on_error: OnErrorCallback | None = None

    # ------------------------------------------------------------------
    # Callbacks registration
    # ------------------------------------------------------------------
    def set_on_start(self, cb: OnStartCallback) -> None:
        self.on_start = cb

    def set_on_progress(self, cb: OnProgressCallback) -> None:
        self.on_progress = cb

    def set_on_complete(self, cb: OnCompleteCallback) -> None:
        self.on_complete = cb

    def set_on_error(self, cb: OnErrorCallback) -> None:
        self.on_error = cb

    # ------------------------------------------------------------------
    # Submit workflow
    # ------------------------------------------------------------------
    def submit_prompt(self, workflow: dict[str, Any]) -> str:
        """
        Envoie un workflow à ComfyUI et récupère le prompt_id.
        """
        url = f"{self.base_url}/prompt"

        try:
            resp = requests.post(url, json={"prompt": workflow}, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            prompt_id = data.get("prompt_id")
            if not isinstance(prompt_id, str):
                raise CutMindError(
                    "Réponse ComfyUI invalide : prompt_id manquant.",
                    code=ErrCode.NETWORK,
                    ctx=get_step_ctx({"response": data}),
                )

            if self.on_start:
                self.on_start(prompt_id)

            return prompt_id

        except requests.RequestException as exc:
            msg = f"Erreur réseau lors de l'envoi du workflow : {exc}"
            if self.on_error:
                self.on_error(None, msg)
            raise CutMindError(
                msg,
                code=ErrCode.NETWORK,
                ctx=get_step_ctx({"url": url}),
            ) from exc

    # ------------------------------------------------------------------
    # (OPTIONNEL) léger polling pour logs de statut
    # ------------------------------------------------------------------
    def poll_history_once(self, prompt_id: str) -> None:
        """
        Lecture NON BLOQUANTE de /history/<id> :
        utilisée uniquement pour générer un log de type "progress".
        Ne sert pas à déterminer la fin réelle du workflow.
        """
        url = f"{self.base_url}/history/{prompt_id}"

        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                return

            hist = resp.json()
            entry = hist.get(prompt_id)
            if not isinstance(entry, dict):
                return

            status = entry.get("status", "unknown")

            if self.on_progress:
                self.on_progress(prompt_id, status)

        except Exception:
            # On ignore totalement, ComfyUI étant très variable
            pass

    # ------------------------------------------------------------------
    # Faux wait_for_completion : NE BLOQUE PLUS
    # ------------------------------------------------------------------
    def wait_for_completion(
        self,
        prompt_id: str,
        timeout: int = 10,
        poll_interval: float = 1.0,
    ) -> None:
        """
        EXPLICATION :
        ----------------
        Cette fonction NE DOIT PAS bloquer l'exécution :
        → ComfyUI renvoie parfois "success" avant même la fin du workflow.
        → Seul OutputManager peut déterminer la fin réelle via les fichiers générés.

        Donc :
        - on poll l'history quelques fois uniquement pour log
        - puis on rend la main au Processor
        - OutputManager fera la vraie synchronisation
        """
        start = time.time()

        while time.time() - start < timeout:
            self.poll_history_once(prompt_id)
            time.sleep(poll_interval)

        # Pas de retour de fichiers ici → OutputManager s’en charge
        return None
