"""
analyse_actdce2.py
------------------
Analyse le HTML de debug_actdce2_v2.html pour comprendre ce qu'il contient.
Lance : python analyse_actdce2.py
"""
import io
import sys
import re

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

content = open("debug_actdce2_v2.html", encoding="utf-8").read()
print(f"Taille totale fichier : {len(content)} chars")
print()

print("=" * 60)
print("DERNIERS 1500 chars du HTML")
print("=" * 60)
print(content[-1500:])
print()

print("=" * 60)
print("RECHERCHE DE PATTERNS")
print("=" * 60)

# Patterns AJAX / fetch / XHR
ajax = re.findall(r'\.(ajax|get|post|fetch|load|getJSON)\(', content, re.IGNORECASE)
print(f"Appels jQuery/AJAX détectés : {len(ajax)} : {set(ajax)}")

# URLs cfm relatives qui pourraient être appelées en XHR
urls_cfm = re.findall(r'["\']([^"\'<>]*\.cfm[^"\'<>]*)["\']', content)
urls_cfm_uniques = list(set(urls_cfm))
print(f"URLs .cfm uniques trouvées : {len(urls_cfm_uniques)}")
for u in urls_cfm_uniques[:15]:
    print(f"  {u[:150]}")
print()

# Scripts JS inline avec fuseaction= ou XHR
print("Scripts JS inline contenant 'fuseaction', 'XHR', ou 'fetch' :")
scripts = re.findall(r"<script[^>]*>([\s\S]*?)</script>", content, re.IGNORECASE)
for i, s in enumerate(scripts):
    if "fuseaction" in s.lower() or "xhr" in s.lower() or "fetch" in s.lower() or "ajax" in s.lower():
        print(f"--- Script {i+1} ({len(s)} chars) ---")
        print(s[:800])
        print()

# Tous les attributs data-* (souvent utilisés pour configurer du JS)
print("Attributs data-* :")
data_attrs = re.findall(r'(data-[a-z\-]+)=["\']([^"\']{1,200})["\']', content, re.IGNORECASE)
for name, val in data_attrs[:20]:
    print(f"  {name} = {val[:100]}")
print()

# Présence d'iframes
iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', content)
print(f"iframes : {len(iframes)}")
for f in iframes:
    print(f"  {f}")
print()

# IDs et classes des divs principaux
print("Divs/sections principaux (id ou class) :")
divs = re.findall(r'<(div|section|article|form)[^>]*(?:id|class)=["\']([^"\']{1,60})["\']', content)
for tag, ident in divs[:20]:
    print(f"  <{tag} ...{ident}>")
print()

# Boutons / formulaires de téléchargement
print("Boutons / forms / inputs avec action :")
formes = re.findall(r'<(button|form|input)[^>]+(?:action|onclick|type)=["\']([^"\']+)["\']', content)
for tag, action in formes[:10]:
    print(f"  <{tag} ...{action[:100]}>")
