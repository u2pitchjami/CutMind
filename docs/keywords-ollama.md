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
Transformers. Le normaliseur de mots-clés et confidence disposent de choix de backend
indépendants, décrits ci-dessous.

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

## Confidence via Ollama

Les trois passes (catégorie, mots-clés et ratings) suivent `KEYWORDS_BACKEND`.
Le calcul de confidence dispose d'un choix indépendant :

```dotenv
CONFIDENCE_BACKEND=ollama
CONFIDENCE_OLLAMA_MODEL=nom-exact-du-modele-embeddings-installe
# Facultatif : reprend OLLAMA_BASE_URL si absent
CONFIDENCE_OLLAMA_BASE_URL=http://localhost:11434
CONFIDENCE_OLLAMA_TIMEOUT=180
CONFIDENCE_OLLAMA_KEEP_ALIVE=1m
```

Redémarrer CutMind après modification. Le modèle doit accepter les embeddings
textuels ; le modèle vision de `OLLAMA_MODEL` n'est pas repris automatiquement.
Aucun téléchargement automatique n'est effectué.

Les mêmes champs (`backend`, `ollama_model`, `ollama_base_url`, `ollama_timeout`,
`ollama_keep_alive`) sont disponibles dans `analyse_confidence` du YAML.
Les variables d'environnement ont priorité. Sans configuration supplémentaire,
`transformers` conserve le modèle `model_confidence` existant.

CutMind envoie la description et les mots-clés joints par des virgules dans un
seul appel `/api/embed`, puis calcule leur similarité cosinus, arrondie à trois
décimales et bornée entre 0 et 1 comme auparavant. Les entrées trop longues
sont rejetées (`truncate=false`). Les erreurs remontent sans repli automatique.
Le modèle SentenceTransformer de confidence n'est pas chargé avec ce backend.
La fusion des mots-clés et les segments déjà validés à 0.99 restent inchangés.

Un changement de modèle d'embeddings peut modifier la distribution des scores :
comparer sur les mêmes segments et vérifier les seuils de validation existants.
Les scores déjà enregistrés ne sont pas recalculés automatiquement.
Pour revenir au calcul local : `CONFIDENCE_BACKEND=transformers`.

API de référence : https://docs.ollama.com/api/embed


## Harmonisation des mots-clés via Ollama

```dotenv
KEYWORD_NORMALIZER_BACKEND=ollama
KEYWORD_NORMALIZER_OLLAMA_MODEL=nom-exact-du-modele-embeddings-installe
# Facultatif : reprend OLLAMA_BASE_URL si absent
KEYWORD_NORMALIZER_OLLAMA_BASE_URL=http://localhost:11434
KEYWORD_NORMALIZER_OLLAMA_TIMEOUT=180
KEYWORD_NORMALIZER_OLLAMA_KEEP_ALIVE=1m
```

Redémarrer CutMind après modification. Le modèle doit produire des embeddings
textuels et être déjà installé. Il peut être le même que celui de confidence.
Le choix reste indépendant de `CONFIDENCE_BACKEND` et `KEYWORDS_BACKEND`.
Par défaut, `KEYWORD_NORMALIZER_BACKEND=transformers` conserve le modèle local
`model_name_key`. Aucun modèle SentenceTransformer du normaliseur n'est chargé
avec le backend Ollama.

Les mêmes champs (`backend`, `ollama_model`, `ollama_base_url`, `ollama_timeout`,
`ollama_keep_alive`) sont disponibles dans `keyword_normalizer` du YAML.
Les variables d'environnement ont priorité.

Le mapping manuel, les mots interdits, les modes `full`, `strict`, `mixed` et
`similarity_threshold` sont conservés. Pour les mots sans correspondance manuelle,
CutMind demande les embeddings du mot et des candidats dans un appel `/api/embed`,
puis choisit le candidat de similarité cosinus maximale s'il atteint le seuil.
Sans candidat, le mot reste inchangé. Une erreur Ollama remonte sans repli local.
Le seuil peut nécessiter un ajustement après comparaison des modèles.

Le cache Ollama est limité à l'instance du normaliseur en mémoire : le cache
Transformers sur disque n'est ni réutilisé ni écrasé. Cela évite de reprendre
les rapprochements sémantiques d'un autre modèle et permet de revenir au backend
local sans altérer son cache.


## Catégorie non attribuée

Une catégorie JSON `null`, vide ou égale à `"None"` / `"null"` (sans distinction
majuscule/minuscule) est traitée comme une absence de catégorie. Si aucun batch
ne fournit de catégorie exploitable, les passes mots-clés et ratings du segment
sont arrêtées. L'historique indique cette absence, puis le segment suivant est
traité sans exception pour ce résultat métier.

La règle de reprise reste identique : premier échec, tag `IA_error` et cible
`TO_IA` ; deuxième échec, cible `IA_error`. Un nom de catégorie valide fourni
manuellement continue de sélectionner directement son prompt. Les erreurs
techniques (connexion, JSON invalide, prompt inconnu, etc.) conservent leur
gestion existante.

## Diagnostic des réponses tronquées

Si la réponse est incomplète (`done` différent de `true`) ou si `done_reason`
vaut `length`, CutMind sauvegarde un fichier JSON unique dans
`/app/logs/cutmind/`. Le chemin est indiqué dans le message
d'erreur et les logs. Avec le montage Docker du projet, le dossier est :

- conteneur : `/app/logs/cutmind/` ;
- hôte : `/home/pipo/data/logs/cutmind/logs/cutmind/`.

Le fichier contient la sortie `message.content` complète telle que reçue (dans
le champ `content`), l'identifiant du segment/batch, le modèle, les noms des
prompts, les options de génération, le nombre d'images et les compteurs et
raisons d'arrêt Ollama. Les images base64, le texte des prompts et le contenu
`thinking` ne sont pas sauvegardés ; seule sa présence est indiquée.

Examiner `content` pour distinguer une réponse longue de répétitions ou de
marqueurs de conversation inattendus avant d'augmenter `max_new_tokens`.
La réponse tronquée reste rejetée. Si le fichier ne peut pas être écrit,
l'erreur initiale reste signalée avec un avertissement dans les logs.
Les réponses réussies ne créent pas de fichier de diagnostic. Ces fichiers
ne sont pas purgés automatiquement par ce mécanisme.
