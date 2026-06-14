"""
briefs_versioning.py
--------------------
Versioning des prompts d'extraction (Chantier 1E).

Un brief complet porte dans son `_meta.prompts_versions` le hash SHA-256 des
`_preset.json` utilisés à sa génération (cf tendia_extraire). Quand un preset
évolue, les briefs générés avec l'ancienne version deviennent « obsolètes » et
gagneraient à être re-extraits.

`lister_briefs_obsoletes()` retourne ces marche_ids. NON appelée par le sprint —
utilitaire pour des re-extractions ciblées futures.
"""
from typing import Optional


def lister_briefs_obsoletes(briefs: Optional[dict] = None,
                            hashes_courants: Optional[dict] = None) -> list:
    """
    Retourne les marche_ids dont le brief a été généré avec une version de prompt
    différente des `_preset.json` actuels.

    Est considéré obsolète un brief :
    - sans `_meta.prompts_versions` (ancien, pré-versioning) ; OU
    - dont au moins un preset versionné a un hash != hash courant ; OU
    - dont un preset versionné n'existe plus.

    Args (tous optionnels, pour testabilité) :
        briefs : {id: brief}. Défaut : collection `briefs_extraits`.
        hashes_courants : {code: 'sha256:...'}. Défaut : presets installés.

    Returns: liste triée de marche_ids.
    """
    if briefs is None:
        import stockage
        briefs = stockage.charger("briefs_extraits") or {}
    if hashes_courants is None:
        import preset
        hashes_courants = preset.hashes_presets_installes()

    obsoletes = []
    for mid, b in briefs.items():
        meta = (b or {}).get("_meta") or {}
        # Les briefs light ne sont pas concernés par le versioning des prompts complet.
        if meta.get("type") == "light":
            continue
        pv = meta.get("prompts_versions")
        if not pv:
            obsoletes.append(mid)   # ancien brief sans versioning
            continue
        perime = False
        for cle, h in pv.items():
            code = cle.split("/")[0]
            if hashes_courants.get(code) != h:
                perime = True
                break
        if perime:
            obsoletes.append(mid)
    return sorted(obsoletes)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    obs = lister_briefs_obsoletes()
    print(f"Briefs obsolètes (prompts modifiés depuis génération) : {len(obs)}")
    for mid in obs[:50]:
        print(f"  - {mid}")
    if len(obs) > 50:
        print(f"  … {len(obs) - 50} autres")
