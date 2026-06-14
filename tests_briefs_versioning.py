"""
tests_briefs_versioning.py
--------------------------
Tests HORS-LIGNE du versioning des prompts (Chantier 1E).
Lancement : python tests_briefs_versioning.py
"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import preset
import briefs_versioning as BV

preset.recharger()

ok = 0
ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}")


print("=== hash_preset / hashes_presets_installes ===")
h = preset.hash_preset("btp")
check("hash_preset('btp') = 16 hex", bool(h) and bool(re.fullmatch(r"[0-9a-f]{16}", h)))
check("hash_preset('inexistant') = None", preset.hash_preset("inexistant_xyz") is None)
allh = preset.hashes_presets_installes()
check("hashes_presets_installes couvre les 6 presets", len(allh) >= 6)
check("format sha256:<hex>", all(v.startswith("sha256:") for v in allh.values()))
check("hash stable entre 2 appels", preset.hash_preset("btp") == h)

print("\n=== prompts_versions_pour_presets ===")
pv = preset.prompts_versions_pour_presets(["btp", "ingenierie"])
check("clé = '<code>/_preset.json'", "btp/_preset.json" in pv and "ingenierie/_preset.json" in pv)
check("hors-périmètre ([]) → {}", preset.prompts_versions_pour_presets([]) == {})

print("\n=== lister_briefs_obsoletes (données synthétiques) ===")
COUR = {"btp": "sha256:aaaa", "it": "sha256:bbbb"}
briefs = {
    "M_ok":      {"_meta": {"type": "complet", "prompts_versions": {"btp/_preset.json": "sha256:aaaa"}}},
    "M_perime":  {"_meta": {"type": "complet", "prompts_versions": {"btp/_preset.json": "sha256:OLD0"}}},
    "M_sans_pv": {"_meta": {"type": "complet"}},
    "M_light":   {"_meta": {"type": "light", "date_generation": "x"}},
    "M_preset_disparu": {"_meta": {"type": "complet", "prompts_versions": {"zzz/_preset.json": "sha256:cccc"}}},
}
obs = BV.lister_briefs_obsoletes(briefs=briefs, hashes_courants=COUR)
check("brief à jour NON obsolète", "M_ok" not in obs)
check("brief avec hash périmé obsolète", "M_perime" in obs)
check("brief sans prompts_versions obsolète", "M_sans_pv" in obs)
check("brief light ignoré", "M_light" not in obs)
check("brief référençant un preset disparu obsolète", "M_preset_disparu" in obs)
check("résultat trié", obs == sorted(obs))


print(f"\n{'='*56}")
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
