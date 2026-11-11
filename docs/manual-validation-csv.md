# Validations manuelles depuis le CSV

Les commandes se renseignent dans la colonne `action` (au singulier).
Les espaces et la casse de la commande sont ignorés.

## `ok` : validation du cut

- `status = cut_validated`
- `pipeline_target = TO_ENHANCE`
- La description est vidée et les associations de mots-clés du segment sont supprimées,
  même si ces colonnes sont remplies dans le CSV.
- La catégorie du CSV est conservée. Si elle est renseignée, la confidence passe à
  `0.99`, comme dans le comportement existant.

Les métadonnées IA pourront ainsi être régénérées sur le parcours suivant.

## `val` : validation finale manuelle

La catégorie, la description et au moins un mot-clé doivent être présents dans le CSV.
Les valeurs vides ou les marqueurs comme `None` et `NULL` ne comptent pas.
Si une donnée manque, la ligne est signalée en erreur dans le journal CSV sans
mise à jour du segment ; les autres lignes continuent à être traitées.

Si les données sont complètes :

- `status = validated`
- `pipeline_target = TO_CHECK`
- La catégorie, la description et les mots-clés corrigés du CSV sont enregistrés.
- La confidence déjà enregistrée en base est conservée, quelle que soit la valeur
  de la colonne CSV ; le seuil automatique ne bloque pas cette approbation humaine.
- Une entrée « Validation finale manuelle via CSV » est ajoutée à l'historique
  de traitement, ainsi qu'au journal d'import CSV.

Le segment passe ensuite au check habituel. Cette commande ne déplace pas le
segment vers une autre vidéo.
