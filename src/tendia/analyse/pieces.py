"""
tendia/analyse/pieces.py
------------------------
Inventaire COMPLET des pièces d'un DCE pour le mode d'analyse « document »
(promu de l'expérimentation exp_gemini, commit 3ba9a4b) :

- parcours récursif (sous-dossiers + zips imbriqués, décompressés dans
  data/pieces/<id>/ ; data/dce/ est en LECTURE SEULE, rien n'y est jamais écrit) ;
- plans, photos, CAO, polices, données cartographiques… ignorés (statut plan_ignore) ;
- .doc/.docx/.odt/.rtf → PDF, .xls/.xlsm/.ods/.slk → .xlsx : via Word/Excel (COM, piloté
  par PowerShell) sous Windows quand Office est installé, sinon via LibreOffice headless
  (`soffice --convert-to`) ; choix automatique, forçable par TENDIA_CONVERSION=office|
  libreoffice ; repli sur l'autre moteur si une conversion échoue. La pagination reste
  citable ; une conversion impossible donne le statut echec_conversion ;
- plans (PDF dont le nom évoque un plan, une coupe, une façade…) ignorés ;
- archives .rar et .7z, formats inconnus : statut format_non_gere (jamais ignorés en silence) ;
- texte page par page (« [[Page N]] ») ; PDF sans texte (scans) marqués pour
  une LECTURE VISUELLE (PDF natif, découpé en parties ≤ 100 pages / 20 Mo pour respecter
  les limites Claude et Gemini) ;
- dédoublonnage par empreinte (même pièce en clair et dans un zip), doublons listés ;
- typage : RC, CCAP, CCTP, BPU/DPGF/DQE, AE, annexe (nom de fichier, puis
  premières lignes du contenu).

Le dossier de travail data/pieces/<id>/ (hors git) est reconstruit quand l'inventaire est
absent, que le dossier source a changé (signature : chemins, tailles, dates) ou que
`force=True`. Rien n'est supprimé : l'ancien contenu est déplacé dans
archive/data/pieces/<id>_<horodatage>/ ; la trace des analyses déjà payées (_trace.json)
reste en place.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import unicodedata
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

from tendia.core.chemins import ARCHIVE, DATA

DIR_PIECES = DATA / "pieces"

# pypdf signale chaque police qu'il ne sait pas décoder : sans intérêt ici, des centaines de lignes par DCE.
logging.getLogger("pypdf").setLevel(logging.ERROR)

# Statuts d'un fichier écarté (voir sources_lecture.tableau_lecture).
STATUTS_ECARTES = ("plan_ignore", "format_non_gere", "echec_conversion")
# Destination des anciens dossiers de travail. None : archive/data/pieces en prod, ou
# DIR_PIECES / "_archive" quand DIR_PIECES est redirigé (tests) pour ne jamais écrire
# dans la vraie archive depuis un test.
DIR_ARCHIVE_PIECES = None
FICHIERS_CONSERVES = ("_trace.json",)       # analyses déjà payées : jamais déplacées

GRAPHIQUES = {".dwg", ".dxf", ".dgn", ".shx", ".plt", ".pc3", ".ifc", ".rvt", ".jpg", ".jpeg", ".png",
              ".tif", ".tiff", ".bmp", ".gif", ".svg", ".webp", ".heic", ".ttf", ".otf", ".db",
              ".ds_store", ".bak", ".dwf", ".dwfx", ".skp", ".3dm", ".stp", ".step", ".mp4", ".mov",
              ".avi", ".lnk", ".ini", ".exe", ".dll", ".js", ".css", ".sig",
              ".p7s", ".jws", ".xades", ".tmp",
              # données cartographiques (SIG) accompagnant les plans
              ".shp", ".dbf", ".prj", ".cpg", ".qpj", ".sbn", ".sbx", ".gml", ".kml", ".kmz", ".gpkg"}
WORD = {".doc", ".docx", ".odt", ".rtf", ".docm", ".dot", ".dotx"}
EXCEL = {".xls", ".xlsm", ".ods", ".xlsb", ".slk"}
ARCHIVES = {".zip"}
HTML = {".html", ".htm"}
TEXTE = {".txt", ".csv"}
# PDF de plans / pièces graphiques (ignorés comme les fichiers CAO).
RE_PLAN = re.compile(r"(^|[^a-z])(plans?|pln|coupes?|facades?|elevations?|implantation|plan de masse|"
                     r"plan de situation|nivellement|carroyage|photos?|reportage photo)([^a-z]|$)")
SEUIL_TEXTE_PLAN = 1500      # caractères par page en moyenne au-delà desquels un « plan » est lu
PAGES_MAX_PARTIE = 100
OCTETS_MAX_PARTIE = 20 * 1024 * 1024
ARCHIVES_NON_GEREES = {".rar", ".7z"}

TYPES = ("RC", "CCAP", "CCTP", "BPU_DPGF_DQE", "AE", "annexe")
_REGLES_NOM = [
    ("RC", r"(^|[^a-z])(rc|r c|reglement (de )?(la )?consultation|reglement de consult)([^a-z]|$)"),
    ("CCAP", r"(^|[^a-z])(ccap|cahier des clauses administratives particulieres)([^a-z]|$)"),
    ("CCTP", r"(^|[^a-z])(cctp|cctc|cahier des clauses techniques particulieres|clauses techniques communes|"
             r"cahier des charges techniques|cdc technique|ccp|cahier des charges)([^a-z]|$)"),
    ("BPU_DPGF_DQE", r"(^|[^a-z])(bpu|dpgf|dqe|bordereau|decomposition du prix|detail quantitatif|"
                     r"devis quantitatif|cadre de reponse financier|bpu dqe)([^a-z]|$)"),
    ("AE", r"(^|[^a-z])(ae|acte d engagement|attri ?1|actes? d engagement)([^a-z]|$)"),
]
_REGLES_CONTENU = [
    ("RC", r"reglement (particulier )?de (la )?consultation"),
    ("CCAP", r"cahier des clauses administratives particulieres"),
    ("CCTP", r"cahier des clauses techniques particulieres"),
    ("BPU_DPGF_DQE", r"bordereau des prix unitaires|decomposition du prix global|detail quantitatif estimatif"),
    ("AE", r"acte d.engagement"),
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def typer_piece(nom: str, debut_texte: str = "") -> str:
    n = _norm(Path(nom).stem)
    for t, rx in _REGLES_NOM:
        if re.search(rx, n):
            return t
    c = _norm(debut_texte[:3000])
    for t, rx in _REGLES_CONTENU:
        if re.search(rx, c):
            return t
    return "annexe"


def _sha(chemin: Path) -> str:
    h = hashlib.sha1()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


LONGUEUR_MAX_CHEMIN = 200      # Windows : 260 caractères au plus, marge pour les fichiers dérivés


def _nom_zip(info_nom: str, utf8: bool) -> str:
    """Nom d'une entrée de zip. Noms encodés CP437 par les outils Windows : tentative de réparation."""
    if utf8:
        return info_nom
    try:
        return info_nom.encode("cp437").decode("utf-8")
    except Exception:
        try:
            return info_nom.encode("cp437").decode("cp850")
        except Exception:
            return info_nom


def _chemin_cible(dest: Path, nom: str, racine_longs: Path = None):
    """Chemin d'extraction d'une entrée de zip sous `dest`, ou None si l'entrée sortirait
    du dossier (« ../ »). Les dossiers intermédiaires sont raccourcis ; si le chemin reste
    trop long pour Windows, le fichier est rangé dans `<racine_longs>/<empreinte>/` (nom
    conservé ; racine_longs : dossier court du marché, à défaut `dest/_long`)."""
    parties = [x for x in nom.replace("\\", "/").split("/") if x not in ("", ".")]
    if not parties or ".." in parties or ":" in parties[0]:
        return None
    # un dossier raccourci garde une empreinte de son nom complet : deux dossiers qui ne
    # diffèrent qu'après le 30e caractère (« … - Lot 1 », « … - Lot 2 ») restent distincts
    dossiers = [d if len(d) <= 30 else d[:30].rstrip(" .") + "~" + hashlib.sha1(d.encode("utf-8", "replace")).hexdigest()[:6]
                for d in (x.rstrip(" .") or "_" for x in parties[:-1])]
    cible = dest.joinpath(*dossiers, parties[-1])
    if len(str(cible)) > LONGUEUR_MAX_CHEMIN:
        fichier = Path(parties[-1].rstrip(" ."))
        court = (fichier.stem[:80].rstrip(" .") or "_") + fichier.suffix
        empreinte = hashlib.sha1(f"{dest}|{nom}".encode("utf-8", "replace")).hexdigest()[:10]
        cible = (racine_longs or dest / "_long") / empreinte / court
        return cible
    if dest.resolve() not in cible.resolve().parents:
        return None
    return cible


def _entrees_zip_tronque(zp: Path):
    """Entrées lisibles d'un zip sans répertoire central (téléchargement interrompu) : lecture
    séquentielle des en-têtes locaux. Rend (nom, contenu) jusqu'à la première entrée incomplète."""
    donnees = zp.read_bytes()
    pos = 0
    while True:
        i = donnees.find(b"PK\x03\x04", pos)
        if i < 0:
            return
        if i + 30 > len(donnees):
            return
        (_ver, drapeaux, methode, _h, _d, _crc, taille_c, _taille, n_nom, n_extra) = struct.unpack(
            "<HHHHHIIIHH", donnees[i + 4:i + 30])
        nom = _nom_zip(bytes(donnees[i + 30:i + 30 + n_nom]).decode("utf-8" if drapeaux & 0x800 else "cp437",
                                                                     "replace"), bool(drapeaux & 0x800))
        debut = i + 30 + n_nom + n_extra
        if nom.endswith("/"):
            pos = debut
            continue
        if methode == 8:
            d = zlib.decompressobj(-15)
            morceaux, lu = [], debut
            while not d.eof and lu < len(donnees):
                bloc = donnees[lu:lu + (1 << 20)]
                morceaux.append(d.decompress(bloc))
                lu += len(bloc)
            if not d.eof:
                return                      # entrée coupée par la troncature
            fin = lu - len(d.unused_data)
            contenu = b"".join(morceaux)
        elif methode == 0 and not (drapeaux & 8 and not taille_c):
            fin = debut + taille_c
            if fin > len(donnees):
                return
            contenu = donnees[debut:fin]
        else:
            return                          # méthode non gérée : on s'arrête là
        yield nom, contenu
        pos = fin


def _extraire_entree(dest: Path, nom: str, ecrire, zp: Path, profondeur: int, racine_longs: Path = None) -> list:
    """Écrit une entrée (ecrire(fichier_ouvert)) et décompresse un zip imbriqué. Rend les erreurs."""
    cible = _chemin_cible(dest, nom, racine_longs)
    if cible is None:
        return [f"{zp.name}: entrée ignorée (chemin hors archive) : {nom}"]
    if cible.exists():
        # deux entrées vers le même fichier (noms raccourcis, casse) : aucune n'écrase l'autre
        cible = ((racine_longs or dest / "_long")
                 / hashlib.sha1(f"{dest}|{nom}|2".encode("utf-8", "replace")).hexdigest()[:10] / cible.name)
        if cible.exists():
            return [f"{zp.name}: entrée en double ignorée : {nom}"]
    cible.parent.mkdir(parents=True, exist_ok=True)
    with open(cible, "wb") as d:
        ecrire(d)
    if cible.suffix.lower() in ARCHIVES:
        empreinte = hashlib.sha1(nom.encode("utf-8", "replace")).hexdigest()[:6]
        sous = cible.with_name(f"{cible.stem[:30].rstrip(' .')}~{empreinte}_zip")
        if racine_longs is not None and len(str(sous)) > LONGUEUR_MAX_CHEMIN - 60:
            # zip imbriqué déjà profond : son contenu repart d'un dossier court
            sous = racine_longs / f"{hashlib.sha1(str(cible).encode('utf-8', 'replace')).hexdigest()[:10]}_zip"
        sous.mkdir(parents=True, exist_ok=True)
        return _dezipper(cible, sous, profondeur + 1, racine_longs)
    return []


def _dezipper(zp: Path, dest: Path, profondeur=0, racine_longs: Path = None) -> list:
    """Décompresse récursivement sous `dest` ; renvoie les erreurs éventuelles, chacune
    préfixée par « <nom du zip>: ». Un zip tronqué (sans répertoire central) est lu
    séquentiellement : ses premières pièces sont récupérées, la troncature est signalée."""
    erreurs = []
    if profondeur > 5:
        return [f"{zp.name}: imbrication trop profonde"]
    try:
        with zipfile.ZipFile(zp) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                nom = _nom_zip(info.filename, bool(info.flag_bits & 0x800))
                try:
                    with z.open(info) as s:
                        erreurs += _extraire_entree(dest, nom, lambda d: shutil.copyfileobj(s, d), zp,
                                                    profondeur, racine_longs)
                except Exception as e:
                    erreurs.append(f"{zp.name}: {type(e).__name__} sur « {nom[-80:]} » : {str(e)[:120]}")
    except zipfile.BadZipFile as e:
        recuperes = 0
        try:
            for nom, contenu in _entrees_zip_tronque(zp):
                erreurs += _extraire_entree(dest, nom, lambda d: d.write(contenu), zp, profondeur, racine_longs)
                recuperes += 1
        except Exception as e2:
            erreurs.append(f"{zp.name}: {type(e2).__name__}: {str(e2)[:120]}")
        erreurs.append(f"{zp.name}: archive tronquée ou illisible ({e}) ; {recuperes} fichier(s) récupéré(s), "
                       f"le reste de l'archive n'a pas pu être lu")
    except Exception as e:
        erreurs.append(f"{zp.name}: {type(e).__name__}: {e}")
    return erreurs


# AutomationSecurity = 3 : macros désactivées (les DCE viennent d'internet). Le mot de passe
# factice fait échouer l'ouverture d'un document protégé au lieu d'afficher une invite bloquante.
_PS_CONVERSION = r"""
$ErrorActionPreference = 'Continue'
$jobs = Get-Content -Raw -Encoding UTF8 '{fichier}' | ConvertFrom-Json
$word = $null; $excel = $null
foreach ($j in $jobs) {{
  try {{
    if ($j.app -eq 'word') {{
      if (-not $word) {{ $word = New-Object -ComObject Word.Application; $word.Visible = $false; $word.DisplayAlerts = 0; $word.AutomationSecurity = 3 }}
      $d = $word.Documents.Open($j.src, $false, $true, $false, 'tendia'); $d.SaveAs([ref]$j.dst, [ref]17); $d.Close($false)
    }} else {{
      if (-not $excel) {{ $excel = New-Object -ComObject Excel.Application; $excel.Visible = $false; $excel.DisplayAlerts = $false; $excel.AutomationSecurity = 3 }}
      $b = $excel.Workbooks.Open($j.src, 0, $true, [Type]::Missing, 'tendia'); $b.SaveAs($j.dst, 51); $b.Close($false)
    }}
    Write-Output ("OK " + $j.dst)
  }} catch {{ Write-Output ("KO " + $j.src + " :: " + $_.Exception.Message) }}
}}
if ($word) {{ $word.Quit() }}; if ($excel) {{ $excel.Quit() }}
"""


def _office_disponible() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application"))
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application"))
        return True
    except OSError:
        return False


def _soffice() -> str:
    for nom in ("soffice", "libreoffice"):
        chemin = shutil.which(nom)
        if chemin:
            return chemin
    for chemin in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                   r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                   "/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
                   "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if os.path.isfile(chemin):
            return chemin
    return None


def moteurs_conversion() -> list:
    """Moteurs disponibles, dans l'ordre de préférence (Office local d'abord s'il existe)."""
    force = (os.environ.get("TENDIA_CONVERSION") or "").lower()
    dispo = []
    if _office_disponible():
        dispo.append("office")
    if _soffice():
        dispo.append("libreoffice")
    if force in dispo:
        dispo.remove(force)
        dispo.insert(0, force)
    return dispo


def _convertir_libreoffice(jobs: list, travail: Path) -> dict:
    """soffice --headless --convert-to pdf|xlsx ; un profil isolé évite les conflits d'instance."""
    soffice = _soffice()
    profil = (travail / "_lo_profil").resolve().as_uri()
    res = {}
    for k, j in enumerate(jobs):
        sortie = travail / f"_lo_{k:03d}"
        sortie.mkdir(exist_ok=True)
        fmt = "pdf" if j["app"] == "word" else "xlsx"
        try:
            subprocess.run([soffice, f"-env:UserInstallation={profil}", "--headless", "--norestore",
                            "--convert-to", fmt, "--outdir", str(sortie), j["src"]],
                           capture_output=True, timeout=300)
            produit = next(sortie.glob(f"*.{fmt}"), None)
            if produit:
                shutil.move(str(produit), j["dst"])
        except Exception as e:
            res[j["src"]] = f"libreoffice : {type(e).__name__}: {e}"
            continue
        ok = Path(j["dst"]).exists() and Path(j["dst"]).stat().st_size > 0
        res[j["src"]] = None if ok else "libreoffice : échec conversion"
    return res


def _convertir(jobs: list, travail: Path) -> dict:
    """jobs = [{app, src, dst}] → {src: erreur|None}. Essaie les moteurs disponibles dans
    l'ordre ; les fichiers en échec sont retentés avec le moteur suivant."""
    if not jobs:
        return {}
    erreurs = {j["src"]: [] for j in jobs}
    reussis = set()
    restants = list(jobs)
    for moteur in moteurs_conversion():
        if not restants:
            break
        r = (_convertir_office if moteur == "office" else _convertir_libreoffice)(restants, travail)
        for src, err in r.items():
            if err is None:
                reussis.add(src)
            else:
                erreurs[src].append(f"{moteur} : {err}")
        restants = [j for j in restants if j["src"] not in reussis]
    return {src: None if src in reussis else (" | ".join(e) or "aucun moteur de conversion "
                                               "(ni Word/Excel, ni LibreOffice)")
            for src, e in erreurs.items()}


def _convertir_office(jobs: list, travail: Path) -> dict:
    """Word/Excel via COM (Windows). Une seule instance Word/Excel."""
    fj = travail / "_conversion.json"
    fj.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    fps = travail / "_conversion.ps1"
    fps.write_text(_PS_CONVERSION.format(fichier=str(fj)), encoding="utf-8-sig")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(fps)],
                             capture_output=True, text=True, encoding="cp850", errors="replace",
                             timeout=120 + 60 * len(jobs)).stdout or ""
    except subprocess.TimeoutExpired:
        out = ""
    res = {}
    for j in jobs:
        ok = Path(j["dst"]).exists() and Path(j["dst"]).stat().st_size > 0
        res[j["src"]] = None if ok else (next((l for l in out.splitlines() if j["src"] in l), "échec conversion"))
    return res


def _texte_pdf_pages(chemin: Path) -> list:
    from pypdf import PdfReader
    try:
        r = PdfReader(str(chemin))
    except Exception:
        return []
    pages = []
    for p in r.pages:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def _texte_moyen_par_page(chemin: Path) -> float:
    """Caractères de texte par page en moyenne d'un PDF (0 si illisible ou sans page)."""
    pages = _texte_pdf_pages(chemin)
    return sum(len(p.strip()) for p in pages) / len(pages) if pages else 0.0


def _parties_pdf(chemin: Path, dest: Path) -> list:
    """Découpe un PDF en parties ≤ PAGES_MAX_PARTIE pages et ≤ OCTETS_MAX_PARTIE (limites
    Claude : 600 pages / 32 Mo par requête ; Gemini : 1000 pages / 50 Mo par fichier)."""
    from pypdf import PdfReader, PdfWriter
    if chemin.stat().st_size <= OCTETS_MAX_PARTIE:
        try:
            if len(PdfReader(str(chemin)).pages) <= PAGES_MAX_PARTIE:
                return [str(chemin)]
        except Exception:
            return [str(chemin)]
    r = PdfReader(str(chemin))
    n = len(r.pages)
    pas = PAGES_MAX_PARTIE
    while True:
        parties = []
        for k, debut in enumerate(range(0, n, pas)):
            w = PdfWriter()
            for i in range(debut, min(n, debut + pas)):
                w.add_page(r.pages[i])
            cible = dest / f"{chemin.stem[:50]}_p{debut + 1}-{min(n, debut + pas)}.pdf"
            with open(cible, "wb") as f:
                w.write(f)
            parties.append(str(cible))
        if pas == 1 or all(os.path.getsize(p) <= OCTETS_MAX_PARTIE for p in parties):
            return parties
        pas = max(1, pas // 2)


def _texte_xlsx_feuilles(chemin: Path) -> list:
    """[(nom_feuille, texte)] — lignes non vides, cellules séparées par ' | '."""
    from openpyxl import load_workbook
    out = []
    try:
        wb = load_workbook(str(chemin), read_only=True, data_only=True)
    except Exception:
        return out
    for ws in wb.worksheets:
        lignes = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                lignes.append(" | ".join(cells))
        out.append((ws.title, "\n".join(lignes)))
    return out


def dossier_travail(mid: str) -> Path:
    """DIR_PIECES / mid, après contrôle : l'identifiant doit désigner un sous-dossier direct
    de DIR_PIECES (pas de « ../ », pas de chemin absolu, pas de séparateur)."""
    if not isinstance(mid, str) or not mid.strip() or mid.startswith("_"):
        raise ValueError(f"identifiant de marché invalide : {mid!r}")
    racine = Path(DIR_PIECES).resolve()
    travail = (racine / mid).resolve()
    if travail.parent != racine or travail.name != mid:
        raise ValueError(f"identifiant de marché invalide (hors de {racine}) : {mid!r}")
    return travail


def signature_source(dossier_dce) -> str:
    """Empreinte du dossier source : chemins relatifs, tailles et dates de tous ses fichiers."""
    racine = Path(dossier_dce)
    if not racine.is_dir():
        return ""
    lignes = sorted(f"{f.relative_to(racine).as_posix()}|{f.stat().st_size}|{f.stat().st_mtime_ns}"
                    for f in racine.rglob("*") if f.is_file())
    return hashlib.sha1("\n".join(lignes).encode("utf-8")).hexdigest() if lignes else ""


def _dir_archive() -> Path:
    if DIR_ARCHIVE_PIECES is not None:
        return Path(DIR_ARCHIVE_PIECES)
    if Path(DIR_PIECES).resolve() == (DATA / "pieces").resolve():
        return ARCHIVE / "data" / "pieces"
    return Path(DIR_PIECES) / "_archive"


def _archiver_travail(travail: Path) -> None:
    """Déplace l'ancien contenu du dossier de travail dans l'archive (rien n'est supprimé).
    Les fichiers de FICHIERS_CONSERVES restent en place."""
    anciens = [f for f in travail.iterdir() if f.name not in FICHIERS_CONSERVES]
    if not anciens:
        return
    base = _dir_archive() / f"{travail.name}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    cible, n = base, 1
    while cible.exists():
        n += 1
        cible = base.with_name(f"{base.name}_{n}")
    cible.mkdir(parents=True)
    for f in anciens:
        shutil.move(str(f), str(cible / f.name))


def _noms_uniques(pieces: list, racines: list) -> None:
    """Deux pièces de même nom (lot1/CCTP.pdf, lot2/CCTP.pdf) : le nom affiché, qui sert de
    clé à l'analyse, reçoit le dossier parent qui les distingue."""
    par_nom = {}
    for p in pieces:
        par_nom.setdefault(p["nom"], []).append(p)
    for nom, groupe in par_nom.items():
        if len(groupe) < 2:
            continue
        chemins = []
        for p in groupe:
            chemin = Path(p["chemin_original"])
            for racine in racines:
                try:
                    chemin = chemin.relative_to(racine)
                    break
                except ValueError:
                    continue
            chemins.append(chemin.parts)
        for profondeur in range(2, max(len(c) for c in chemins) + 1):
            candidats = ["/".join(c[-profondeur:]) for c in chemins]
            if len(set(candidats)) == len(candidats):
                break
        else:
            candidats = [f"{nom} ({k})" for k in range(1, len(groupe) + 1)]
        for p, candidat in zip(groupe, candidats):
            p["nom"] = candidat


def _texte_html(chemin: Path) -> str:
    brut = chemin.read_bytes()
    try:
        from bs4 import BeautifulSoup
        soupe = BeautifulSoup(brut, "html.parser")
        for balise in soupe(["script", "style", "noscript"]):
            balise.decompose()
        texte = soupe.get_text("\n")
    except Exception:
        texte = re.sub(r"<[^>]+>", " ", brut.decode("utf-8", "replace"))
    return re.sub(r"\n\s*\n+", "\n", texte).strip()


def inventorier(mid: str, dossier_dce: str, verbose: bool = True, force: bool = False) -> dict:
    """Construit (ou relit) l'inventaire des pièces du DCE `mid`.

    Le dossier `dossier_dce` n'est que lu. Tout ce qui est produit (zips décompressés,
    conversions, parties de PDF, textes) va sous DIR_PIECES / mid. L'inventaire déjà
    écrit est relu tel quel tant que le dossier source n'a pas changé (signature_source),
    sauf `force=True`.

    Résultat : "pieces" (pièces retenues, texte extrait, noms uniques, "empreinte" du
    fichier d'origine), "ecartes" (fichiers non lus : {"nom", "statut", "detail"}, statut
    dans STATUTS_ECARTES), "doublons" ({"nom", "doublon_de"}), "erreurs", "chars_total",
    "nb_pages_total", "signature_source".
    """
    travail = dossier_travail(mid)
    source = Path(dossier_dce).resolve()
    if travail == source or travail in source.parents or source in travail.parents:
        raise ValueError(f"le dossier du DCE et le dossier de travail se recouvrent : {source}")
    signature = signature_source(source)
    fichier = travail / "_inventaire.json"
    if fichier.exists() and not force:
        try:
            inv = json.loads(fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            inv = None
        if inv is not None and inv.get("signature_source") == signature:
            return inv
    if travail.exists():
        _archiver_travail(travail)      # jamais data/dce ; rien n'est supprimé
    (travail / "_extrait").mkdir(parents=True, exist_ok=True)
    (travail / "_converti").mkdir(exist_ok=True)
    (travail / "_parties").mkdir(exist_ok=True)
    erreurs = []

    # 1. Tous les fichiers, zips décompressés récursivement
    ecartes, doublons = [], []
    # Les zips rangés dans _zip_archives/ par l'ancien dézippage à plat (extraire._dezipper_dossier)
    # sont relus eux aussi : ce dézippage ne gardait qu'un fichier par nom, deux pièces homonymes
    # de dossiers différents y perdaient l'une des deux. Les copies à plat sont dédoublonnées
    # par empreinte (le tri ci-dessous garde le fichier de la source le plus proche de la racine).
    fichiers = [f for f in source.rglob("*") if f.is_file()] if source.is_dir() else []
    for i, f in enumerate([f for f in fichiers if f.suffix.lower() in ARCHIVES]):
        dest = travail / "_extrait" / f"{i:02d}_{f.stem[:40].rstrip(' .')}"
        dest.mkdir()
        erreurs_zip = _dezipper(f, dest, racine_longs=travail / "_extrait" / "_l")
        erreurs += erreurs_zip
        # Archive (ou archive imbriquée) non lue en entier : son contenu manque, on le dit.
        for e in erreurs_zip:
            nom_zip, _, detail = e.partition(": ")
            if "entrée ignorée" in e or "entrée en double" in e or any(x["nom"] == nom_zip for x in ecartes):
                continue
            ecartes.append({"nom": nom_zip, "statut": "format_non_gere",
                            "detail": f"archive non lue en entier : {detail[:160]}"})
    extraits = travail / "_extrait"
    fichiers += [f for f in extraits.rglob("*") if f.is_file()]

    def _ordre(p: Path) -> tuple:
        """Fichiers de la source d'abord, puis par profondeur relative, puis par chemin :
        le même ordre quel que soit l'emplacement du dépôt ou du dossier de travail."""
        for rang, racine in enumerate((source, extraits)):
            try:
                rel = p.relative_to(racine)
                return (rang, len(rel.parts), rel.as_posix())
            except ValueError:
                continue
        return (2, len(p.parts), str(p))

    # 2. Tri + dédoublonnage
    vus, retenus, ignores, non_geres = {}, [], [], []
    for f in sorted(fichiers, key=_ordre):
        ext = f.suffix.lower()
        if ext in ARCHIVES:
            continue
        if ext in GRAPHIQUES or f.name.startswith("~$") or f.name.startswith("."):
            ignores.append(f.name)
            ecartes.append({"nom": f.name, "statut": "plan_ignore",
                            "detail": f"fichier graphique ou technique ({ext or 'sans extension'})"})
            continue
        if ext == ".pdf" and RE_PLAN.search(_norm(f.stem)):
            # Un nom de plan ne suffit plus (PGC, plan de retrait amiante, rapport photos
            # commenté…) : un « plan » qui porte du texte (moyenne > SEUIL_TEXTE_PLAN
            # caractères par page) est lu comme une pièce.
            moyenne = _texte_moyen_par_page(f)
            if moyenne <= SEUIL_TEXTE_PLAN:
                ignores.append(f"{f.name} (plan / pièce graphique)")
                ecartes.append({"nom": f.name, "statut": "plan_ignore",
                                "detail": f"plan / pièce graphique ({int(moyenne)} caractères par page en moyenne)"})
                continue
        if ext in ARCHIVES_NON_GEREES:
            non_geres.append(f"{f.name} (archive {ext} non décompressée)")
            ecartes.append({"nom": f.name, "statut": "format_non_gere",
                            "detail": f"archive {ext} non décompressée"})
            continue
        if ext not in {".pdf", ".xlsx"} | WORD | EXCEL | TEXTE | HTML:
            non_geres.append(f"{f.name} (format {ext or '?'} non géré)")
            ecartes.append({"nom": f.name, "statut": "format_non_gere",
                            "detail": f"format {ext or '?'} non géré"})
            continue
        h = _sha(f)
        if h in vus:
            doublons.append({"nom": f.name, "doublon_de": vus[h].name})
            continue
        vus[h] = f
        retenus.append((f, h))

    # 3. Conversions bureautiques (pagination conservée)
    jobs = []
    for i, (f, _h) in enumerate(retenus):
        ext = f.suffix.lower()
        if ext in WORD:
            jobs.append({"app": "word", "src": str(f), "dst": str(travail / "_converti" / f"{i:03d}_{f.stem[:60]}.pdf")})
        elif ext in EXCEL:
            jobs.append({"app": "excel", "src": str(f), "dst": str(travail / "_converti" / f"{i:03d}_{f.stem[:60]}.xlsx")})
    conv = _convertir(jobs, travail)
    dst_par_src = {j["src"]: Path(j["dst"]) for j in jobs}

    # 4. Texte par page + typage
    pieces = []
    for f, empreinte in retenus:
        ext = f.suffix.lower()
        lu = f
        if ext in WORD | EXCEL:
            if conv.get(str(f)):
                non_geres.append(f"{f.name} (conversion impossible : {str(conv[str(f)])[:120]})")
                ecartes.append({"nom": f.name, "statut": "echec_conversion",
                                "detail": str(conv[str(f)])[:200]})
                continue
            lu = dst_par_src[str(f)]
        pages, unite = [], "page"
        if lu.suffix.lower() == ".pdf":
            pages = _texte_pdf_pages(lu)
        elif lu.suffix.lower() == ".xlsx":
            feuilles = _texte_xlsx_feuilles(lu)
            pages = [t for _, t in feuilles]
            unite = "feuille"
            noms_feuilles = [n for n, _ in feuilles]
        elif lu.suffix.lower() in HTML:
            pages = [_texte_html(lu)]
        else:
            pages = [lu.read_text(encoding="utf-8", errors="replace")]
        chars = sum(len(p) for p in pages)
        est_pdf = lu.suffix.lower() == ".pdf"
        # Pièce dont on ne tire rien (PDF corrompu à 0 page, tableur illisible, fichier vide) :
        # elle n'est pas « lue », et aucun appel LLM ne part sur du vide.
        if not pages or (chars == 0 and not est_pdf):
            raison = ("PDF illisible (aucune page)" if est_pdf else "aucun texte extrait du fichier")
            non_geres.append(f"{f.name} ({raison})")
            ecartes.append({"nom": f.name, "statut": "echec_conversion", "detail": raison})
            continue
        # Lecture visuelle si le PDF est (majoritairement) scanné : ≥ 30 % de pages sans texte
        # exploitable, ou presque aucun texte. Les pages vides isolées sont seulement signalées.
        pages_vides = [i + 1 for i, p in enumerate(pages) if len(p.strip()) < 50] if est_pdf else []
        scan = (est_pdf and len(pages) > 0
                and (len(pages_vides) >= 0.3 * len(pages) or chars < 200 * len(pages)))
        texte = "".join(
            f"\n[[{'Feuille ' + noms_feuilles[i] if unite == 'feuille' else 'Page ' + str(i + 1)}]]\n{p}"
            for i, p in enumerate(pages))
        pieces.append({
            "nom": f.name,
            "chemin_original": str(f),
            "chemin_lu": str(lu),
            "empreinte": empreinte,
            "type": typer_piece(f.name, texte),
            "unite": unite,
            "nb_pages": len(pages),
            "chars": chars,
            "scan_sans_texte": scan,
            "lecture_visuelle": scan,
            "pages_sans_texte": pages_vides[:200],
            "parties_pdf": _parties_pdf(Path(lu), travail / "_parties") if scan else [],
            "texte_fichier": None,
        })
        # Le texte est stocké sur disque (peut faire plusieurs Mo).
        ft = travail / f"_texte_{len(pieces):03d}.txt"
        ft.write_text(texte, encoding="utf-8")
        pieces[-1]["texte_fichier"] = str(ft)

    _noms_uniques(pieces, [source, extraits])
    ordre = {t: i for i, t in enumerate(TYPES)}
    pieces.sort(key=lambda p: (ordre[p["type"]], p["nom"]))
    inv = {
        "marche_id": mid,
        "signature_source": signature,
        "pieces": pieces,
        "ecartes": ecartes,
        "doublons": doublons,
        "ignores_graphiques": ignores,
        "non_lus": non_geres,
        "erreurs": erreurs,
        "chars_total": sum(p["chars"] for p in pieces),
        "nb_pages_total": sum(p["nb_pages"] for p in pieces if p["unite"] == "page"),
    }
    fichier.write_text(json.dumps(inv, ensure_ascii=False, indent=1), encoding="utf-8")
    if verbose:
        from collections import Counter
        ct = Counter(p["type"] for p in pieces)
        print(f"      inventaire : {len(pieces)} pièces ({dict(ct)}), {inv['chars_total']:,} car., "
              f"{len(ignores)} graphiques ignorés, {len(non_geres)} non lus, {len(doublons)} doublons, "
              f"{sum(p['scan_sans_texte'] for p in pieces)} scans")
    return inv


def texte_piece(piece: dict) -> str:
    return Path(piece["texte_fichier"]).read_text(encoding="utf-8")


_RE_MARQUEUR = re.compile(r"\n\[\[(Page \d+|Feuille [^\]\n]+)\]\]\n")


def pages_de(piece: dict) -> list:
    """[(clé, texte)] de toutes les pages de la pièce : numéro (int) ou nom de feuille."""
    if not piece or not piece.get("texte_fichier"):
        return []
    try:
        morceaux = _RE_MARQUEUR.split(texte_piece(piece))
    except OSError:
        return []
    resultat = []
    for marqueur, contenu in zip(morceaux[1::2], morceaux[2::2]):
        cle = int(marqueur[5:]) if marqueur.startswith("Page ") else marqueur[8:]
        resultat.append((cle, contenu))
    return resultat


def texte_page(piece: dict, page) -> str:
    """Texte d'une page (numéro, int ou chaîne) ou d'une feuille (nom) de la pièce,
    d'après les marqueurs [[Page N]] / [[Feuille X]]. "" si la page n'existe pas."""
    if page is None or not piece or not piece.get("texte_fichier"):
        return ""
    cle = str(page).strip()
    if not cle:
        return ""
    try:
        texte = texte_piece(piece)
    except OSError:
        return ""
    morceaux = _RE_MARQUEUR.split(texte)      # [avant, marqueur 1, texte 1, marqueur 2, texte 2, ...]
    voulus = {f"Page {int(cle)}"} if cle.isdigit() else {cle, f"Feuille {cle}"}
    for marqueur, contenu in zip(morceaux[1::2], morceaux[2::2]):
        if marqueur in voulus:
            return contenu
    return ""
