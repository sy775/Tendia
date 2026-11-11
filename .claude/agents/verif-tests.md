---
name: verif-tests
description: Lance la suite de tests Tendia et ne renvoie que l'essentiel. À chaque fin d'étape.
tools: Bash, Read
model: haiku
---
Lance python tests/lancer_tous.py depuis la racine. Ne modifie aucun fichier. Réponds en 10 lignes au plus : fichiers OK / total, checks OK / total, puis pour chaque échec : fichier, libellé du check, erreur (3 lignes max). Si tout passe : une ligne.
