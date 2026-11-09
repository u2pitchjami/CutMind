# Choisir le moteur d’analyse vidéo

Transformers reste le moteur par défaut. Les prompts, l’extraction des frames,
la fusion des résultats et la normalisation des mots-clés sont conservés.
Le choix s’applique aussi aux notes de qualité et d’intérêt.

Dans le `.env` chargé par CutMind (`/app/config/.env` dans le conteneur) :

```dotenv
KEYWORDS_BACKEND=transformers
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=
OLLAMA_TIMEOUT=180
OLLAMA_THINK=false
OLLAMA_NUM_CTX=16384
OLLAMA_BATCH_SIZE=6
OLLAMA_KEEP_ALIVE=1m
```

Pour tester Ollama, renseigner le nom exact d’un modèle **vision** déjà installé
sur le serveur, puis définir `KEYWORDS_BACKEND=ollama` et redémarrer CutMind.
Utiliser une URL accessible **depuis CutMind** : dans un conteneur, `localhost`
désigne ce conteneur, pas le serveur hôte ni un autre conteneur.
Aucun modèle n’est téléchargé automatiquement.

Les mêmes options peuvent être définies dans la section `generate_keywords` de
`smartcut.yaml` : `backend`, `ollama_base_url`, `ollama_model`, `ollama_timeout`,
`ollama_think`, `ollama_num_ctx`, `ollama_batch_size`, `ollama_keep_alive`. Les variables d’environnement ont priorité.
Les YAML existants restent compatibles sans ajout de clés.

Avec Ollama, CutMind ne charge pas le modèle Qwen Hugging Face et n’attend pas
le GPU local pour ce chargement. Ollama gère le placement et la mémoire de son
modèle. Le nombre maximal de frames par appel est `OLLAMA_BATCH_SIZE` ; commencer
petit puis ajuster selon la mémoire et le contexte du modèle. Les images sont
redimensionnées aux dimensions `sizeh`/`sizel` existantes et envoyées en base64.
Les options Qwen de budget de pixels et de quantification restent propres à
Transformers. Les autres composants locaux, dont le normaliseur de mots-clés,
restent inchangés et peuvent encore utiliser leurs propres modèles.

L’appel utilise `/api/chat` sans streaming avec un schéma JSON propre au prompt.
Le délai configuré est le délai de lecture HTTP (connexion : 10 secondes), pas
une limite absolue de durée du traitement. `max_new_tokens`, `temperature`,
`top_p` et `repetition_penalty` sont transmis aux options Ollama correspondantes ;
`do_sample=false` impose une température de zéro.
Les durées et nombres de tokens sont journalisés. Une erreur serveur, une
réponse vide, invalide ou tronquée remonte dans la gestion des erreurs IA
existante, sans bascule automatique vers Transformers.

Pour comparer, utiliser les mêmes segments et prompts, idéalement le même
modèle et une quantification comparable. Comparer mots-clés, description,
catégorie, notes, durée et mémoire ; les deux moteurs ne garantissent pas des
résultats identiques. Le champ `ai_model` conserve le nom du modèle utilisé.
Revenir à `KEYWORDS_BACKEND=transformers` puis redémarrer pour rétablir le moteur
initial.

API de référence : https://docs.ollama.com/api/chat

## Contexte insuffisant

Si Ollama indique `request (...) exceeds the available context size (4096 tokens)`,
la somme des prompts et des images dépasse le contexte alloué. CutMind transmet
`OLLAMA_NUM_CTX` (16384 par défaut) dans `options.num_ctx` à chaque appel.
Ce budget doit couvrir les entrées et laisser de la place pour la sortie, y
compris le raisonnement éventuel du modèle. Il est distinct de `max_new_tokens`,
qui limite seulement la génération. Augmenter le contexte consomme davantage de
mémoire sur le serveur Ollama ; on peut aussi réduire `OLLAMA_BATCH_SIZE`.
Le réglage YAML correspondant est `generate_keywords.ollama_num_ctx`.

## Réponse tronquée et raisonnement

CutMind envoie `think=false` par défaut pour obtenir directement le JSON final.
Certains modèles, dont Qwen3.5-RANA, activent sinon le raisonnement par défaut et
peuvent épuiser la limite `generate_keywords.max_new_tokens` avant de produire
leur réponse. `OLLAMA_THINK=true` (ou `generate_keywords.ollama_think: true` dans
le YAML) permet de le réactiver pour un modèle compatible, en adaptant alors le
budget de génération et le contexte. La capacité à désactiver le raisonnement
dépend du modèle utilisé.

Une réponse tronquée reste rejetée ; le message d’erreur précise la raison
d’arrêt, le nombre de tokens générés, les limites et la présence éventuelle de
raisonnement sans en journaliser le contenu. Si la limite est encore atteinte
avec `OLLAMA_THINK=false`, augmenter `generate_keywords.max_new_tokens` dans
`smartcut.yaml`, en laissant assez de contexte pour les entrées et la sortie.
