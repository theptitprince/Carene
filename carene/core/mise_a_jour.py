# -*- coding: utf-8 -*-
"""Les mises à jour de Carène — depuis le serveur du bord (D-85), ou un
dépôt GitHub (D-70) — sans Qt.

**Le serveur du bord (3.5.0, D-85)** : une adresse (`carene.SERVEUR_MAJ`, ou
celle du poste), où sont publiés `derniere.json` — version, nom du zip,
taille, empreinte SHA-256, notes — et le zip du PROGRAMME SEUL
(`tools/livraison.py --serveur`). Le dossier peut être protégé par
`.htaccess` : Carène envoie alors l'identifiant et le mot de passe du poste
(authentification de base, `carene/identifiants.py`), et à ce serveur
seulement. L'empreinte est **obligatoire** : sans elle, rien ne s'installe.
Une adresse en `http://` fait circuler identifiant et mot de passe en clair :
Carène l'accepte et le dit.

Le bord (22/09/2026) : « si je mets le projet sur GitHub, cela te semble-t-il
possible que Carène fasse des vérifications de mise à jour et les télécharge
et les installe à la demande (sans que cela ne change les navires en
place) ? » Puis : « on garde la vérification automatique au lancement (et un
test internet ; si pas internet tant pis, message disant que la vérification
n'a pas pu avoir lieu). »

Trois temps, trois fonctions, aucune ne connaît la fenêtre :

1. **`verifier(depot)`** interroge l'API des *Releases* de GitHub
   (`/repos/<dépôt>/releases/latest`) et rend une `Verification` : la
   version proposée, ses notes, le zip à télécharger — ou la raison pour
   laquelle on ne sait pas (pas de réseau, dépôt introuvable). Elle ne lève
   jamais : à bord, le réseau manque plus souvent qu'il ne marche, et « la
   vérification n'a pas pu avoir lieu » est un résultat normal.
2. **`telecharger(verification, dossier)`** rapporte le zip dans un dossier
   temporaire et le vérifie — sa taille contre celle annoncée par l'API, son
   empreinte SHA-256 contre celle que les notes de la release publient
   (`tools/livraison.py` l'y écrit). Un zip qui ne correspond pas n'est pas
   installé.
3. **`preparer_installation(zip, dossier_programme, relancer)`** écrit le
   script qui fera le travail UNE FOIS CARÈNE FERMÉE — un programme ne peut
   pas se remplacer pendant qu'il tourne. Le script attend la fin du
   processus, met de côté l'ancien programme (`_ancienne_<version>/`),
   déplie le zip par-dessus l'installation, et relance Carène.

**Ce qui n'est jamais touché** : le dossier du navire, `carene.config.json`,
`journaux/`, `sauvegardes/`. Le zip de livraison ne contient le navire que
sous `navires/<NOM>.exemple/` (voir `tools/livraison.py`, D-54) ; se
déplier par-dessus l'installation est déjà la façon documentée de mettre
Carène à jour à la main, ce script ne fait que l'automatiser.

L'adresse du dépôt est une constante du programme (`carene.DEPOT_GITHUB`),
surchargeable par la clé `depot_github` de la configuration du poste : la
source des mises à jour appartient au logiciel, pas au navire.

Le réseau passe par `urllib` avec un délai court, et la fonction d'accès est
injectable (`ouvrir=`) : les tests parlent à un faux GitHub, jamais au vrai.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import base64
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

API = "https://api.github.com/repos/{depot}/releases/latest"
DELAI_S = 4                  # une vérification qui traîne n'est pas une vérification
DELAI_TELECHARGEMENT_S = 60
AGENT = "Carene-mise-a-jour"
MOTIF_SHA = re.compile(r"\b([0-9a-fA-F]{64})\b")
DESCRIPTION = "derniere.json"            # ce que le serveur du bord publie (D-85)


def est_serveur(source: str) -> bool:
    """Une adresse de serveur (http, https), pas un dépôt GitHub."""
    return str(source or "").strip().lower().startswith(("http://", "https://"))


# ================================================================ versions
def tuple_version(v: str) -> tuple:
    """« 2.18.0 » → (2, 18, 0) ; « v2.18.0-rc1 » → (2, 18, 0, 'rc1').

    Comparaison maison plutôt que `packaging`, qui n'est pas au
    `requirements.txt` : trois entiers séparés par des points suffisent à
    Carène, et une étiquette derrière un tiret se compare après."""
    v = str(v or "").strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    corps, _, etiquette = v.partition("-")
    nombres = []
    for morceau in corps.split("."):
        try:
            nombres.append(int(morceau))
        except ValueError:
            nombres.append(0)
    while len(nombres) < 3:
        nombres.append(0)
    return tuple(nombres) + ((etiquette,) if etiquette else ())


def plus_recente(candidate: str, courante: str) -> bool:
    """`candidate` est-elle strictement plus récente que `courante` ?"""
    a, b = tuple_version(candidate), tuple_version(courante)
    # une version « 2.18.0 » est plus récente que sa « 2.18.0-rc1 »
    if a[:3] == b[:3]:
        return len(a) == 3 and len(b) > 3
    return a[:3] > b[:3]


# ============================================================ vérification
@dataclass
class Verification:
    """Ce que la vérification a trouvé — ou pourquoi elle n'a rien trouvé."""

    courante: str
    version: str = ""               # la dernière release, telle que taguée
    disponible: bool = False        # True : plus récente que `courante`
    notes: str = ""                 # les notes de la release (Markdown)
    url_zip: str = ""               # la pièce jointe à télécharger
    nom_zip: str = ""
    taille: int = 0                 # annoncée par l'API
    sha256: str = ""                # lue dans les notes, si publiée
    page: str = ""                  # la page de la release, pour un humain
    hors_ligne: bool = False        # pas de réseau : « n'a pas pu avoir lieu »
    erreur: str = ""                # autre chose (dépôt introuvable, JSON…)
    source: str = "github"          # « serveur » (D-85) ou « github » (D-70)
    adresse: str = ""               # le serveur ou le dépôt interrogé
    # l'identifiant et le mot de passe du serveur : jamais imprimés
    identifiants: tuple = field(default=None, repr=False, compare=False)

    @property
    def http_clair(self) -> bool:
        """Serveur en http:// : identifiant et mot de passe passent en clair."""
        return self.source == "serveur" and self.adresse.lower().startswith("http://")

    @property
    def a_pu_avoir_lieu(self) -> bool:
        return not self.hors_ligne and not self.erreur

    def phrase(self) -> str:
        """Une ligne pour la barre d'état."""
        if self.hors_ligne:
            return ("La vérification de mise à jour n'a pas pu avoir lieu : "
                    "pas de connexion à Internet.")
        if self.erreur:
            return f"La vérification de mise à jour n'a pas pu avoir lieu : {self.erreur}"
        if self.disponible:
            return f"Une mise à jour est disponible : Carène {self.version}."
        return f"Carène {self.courante} est à jour."


class _RedirectionSansIdentifiants(urllib.request.HTTPRedirectHandler):
    """Une redirection vers un AUTRE hôte perd l'identifiant et le mot de
    passe : `urllib` les recopierait sinon dans la nouvelle requête."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        nouvelle = super().redirect_request(req, fp, code, msg, headers, newurl)
        if nouvelle is not None and (urllib.parse.urlparse(newurl).netloc.lower()
                                     != urllib.parse.urlparse(req.full_url).netloc.lower()):
            nouvelle.remove_header("Authorization")
        return nouvelle


def _requete(url, entetes=None):
    h = {"User-Agent": AGENT}
    h.update(entetes or {})
    return urllib.request.Request(url, headers=h)


def _ouvreur():
    return urllib.request.build_opener(_RedirectionSansIdentifiants())


def _ouvrir_http(url, delai, entetes=None):
    """L'accès réseau par défaut : rend (octets, en_tetes)."""
    h = dict(entetes or {})
    if urllib.parse.urlparse(url).netloc.lower() == "api.github.com":
        h.setdefault("Accept", "application/vnd.github+json")
    with _ouvreur().open(_requete(url, h), timeout=delai) as rep:
        return rep.read(), dict(rep.headers)


def _appel(ouvrir, url, delai, entetes):
    """`ouvrir(url, delai)` — ou `ouvrir(url, delai, entetes)` quand il y a des
    en-têtes à passer : les accès injectés des tests d'avant n'en prennent
    pas."""
    return ouvrir(url, delai, entetes) if entetes else ouvrir(url, delai)


def entetes_identification(identifiants) -> dict:
    """L'en-tête de l'authentification de base (.htaccess), ou {}."""
    if not identifiants or not identifiants[0]:
        return {}
    brut = f"{identifiants[0]}:{identifiants[1] or ''}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(brut).decode("ascii")}


def _meme_hote(a, b) -> bool:
    return (urllib.parse.urlparse(a).netloc.lower()
            == urllib.parse.urlparse(b).netloc.lower())


def verifier(depot: str, courante: str, ouvrir=None, delai=DELAI_S,
             identifiants=None) -> Verification:
    """Interroge le serveur du bord (adresse http/https) ou GitHub (dépôt
    « propriétaire/dépôt ») et rend une `Verification`. Ne lève jamais.

    `ouvrir(url, delai[, entetes]) -> (octets, en_tetes)` : injectable pour
    les tests. `identifiants` : (identifiant, mot de passe) du serveur."""
    ouvrir = ouvrir or _ouvrir_http
    if est_serveur(depot):
        return _verifier_serveur(depot.strip(), courante, ouvrir, delai, identifiants)
    v = Verification(courante=courante)
    depot = (depot or "").strip().strip("/")
    v.adresse = depot
    if not depot or "/" not in depot:
        v.erreur = "aucune adresse de mises à jour n'est configurée"
        return v
    try:
        brut, _entetes = ouvrir(API.format(depot=depot), delai)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            v.erreur = f"le dépôt « {depot} » n'a pas de release (404)"
        else:
            v.erreur = f"GitHub a répondu {e.code}"
        return v
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        # pas de DNS, pas de route, délai dépassé : c'est « pas d'Internet »
        v.hors_ligne = True
        v.erreur = ""
        return v
    except Exception as e:                  # noqa: BLE001 - jamais bloquant
        v.erreur = f"{type(e).__name__}: {e}"
        return v
    try:
        d = json.loads(brut.decode("utf-8") if isinstance(brut, bytes) else brut)
    except (ValueError, UnicodeDecodeError) as e:
        v.erreur = f"réponse illisible ({e})"
        return v
    v.version = str(d.get("tag_name") or d.get("name") or "").strip()
    v.notes = str(d.get("body") or "")
    v.page = str(d.get("html_url") or "")
    for a in d.get("assets") or []:
        nom = str(a.get("name") or "")
        if nom.lower().endswith(".zip"):
            v.url_zip = str(a.get("browser_download_url") or "")
            v.nom_zip = nom
            try:
                v.taille = int(a.get("size") or 0)
            except (TypeError, ValueError):
                v.taille = 0
            break
    m = MOTIF_SHA.search(v.notes)
    v.sha256 = m.group(1).lower() if m else ""
    v.disponible = bool(v.version) and plus_recente(v.version, courante) and bool(v.url_zip)
    if v.version and plus_recente(v.version, courante) and not v.url_zip:
        v.erreur = f"la release {v.version} n'a pas de zip en pièce jointe"
    return v


def _verifier_serveur(adresse, courante, ouvrir, delai, identifiants):
    """Le serveur du bord : `<adresse>/derniere.json` (D-85)."""
    base = adresse.rstrip("/")
    v = Verification(courante=courante, source="serveur", adresse=base,
                     identifiants=identifiants)
    try:
        brut, _entetes = _appel(ouvrir, base + "/" + DESCRIPTION, delai,
                                entetes_identification(identifiants))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            v.erreur = ("le serveur a refusé l'identifiant ou le mot de passe (401)"
                        if identifiants and identifiants[0] else
                        "le serveur demande un identifiant et un mot de passe (401) — "
                        "Aide › Serveur des mises à jour…")
        elif e.code == 403:
            v.erreur = "le serveur refuse l'accès (403)"
        elif e.code == 404:
            v.erreur = "aucune version n'est publiée sur le serveur (404)"
        else:
            v.erreur = f"le serveur a répondu {e.code}"
        return v
    except (urllib.error.URLError, OSError, TimeoutError):
        v.hors_ligne = True
        return v
    except Exception as e:                  # noqa: BLE001 - jamais bloquant
        v.erreur = f"{type(e).__name__}: {e}"
        return v
    try:
        d = json.loads(brut.decode("utf-8") if isinstance(brut, bytes) else brut)
        if not isinstance(d, dict):
            raise ValueError("ce n'est pas un objet JSON")
    except (ValueError, UnicodeDecodeError) as e:
        v.erreur = f"{DESCRIPTION} illisible ({e})"
        return v
    v.version = str(d.get("version") or "").strip()
    v.notes = str(d.get("notes") or "")
    v.page = str(d.get("page") or "")
    nom = str(d.get("zip") or "").strip()
    if nom:
        v.url_zip = urllib.parse.urljoin(base + "/", nom)
        v.nom_zip = os.path.basename(urllib.parse.urlparse(v.url_zip).path) or nom
    try:
        v.taille = int(d.get("taille") or 0)
    except (TypeError, ValueError):
        v.taille = 0
    sha = str(d.get("sha256") or "").strip().lower()
    v.sha256 = sha if re.fullmatch(r"[0-9a-f]{64}", sha) else ""
    nouvelle = bool(v.version) and plus_recente(v.version, courante)
    if nouvelle and not v.url_zip:
        v.erreur = f"{DESCRIPTION} annonce la version {v.version} sans nommer son zip"
    elif nouvelle and not v.sha256:
        v.erreur = (f"{DESCRIPTION} annonce la version {v.version} sans empreinte "
                    "SHA-256 : elle ne sera pas installée")
    v.disponible = nouvelle and bool(v.url_zip) and bool(v.sha256)
    return v


# ============================================================ téléchargement
def sha256_de(chemin: str) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def telecharger(v: Verification, dossier: str, ouvrir=None,
                progression=None, delai=DELAI_TELECHARGEMENT_S) -> str:
    """Rapporte le zip de `v` dans `dossier` et le vérifie ; rend son chemin.

    Lève `ValueError` si le zip ne correspond pas à ce qu'annonce la release
    (taille, empreinte) : on n'installe pas ce qu'on ne reconnaît pas.
    `progression(octets_recus, total)` est appelée en cours de route."""
    if not v.url_zip:
        raise ValueError("aucun zip à télécharger")
    if v.source == "serveur" and not v.sha256:
        # D-85 : l'empreinte est obligatoire — un zip qu'on ne sait pas
        # reconnaître ne s'installe pas
        raise ValueError("aucune empreinte SHA-256 publiée : le zip n'est pas installé")
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(dossier, v.nom_zip or "carene_mise_a_jour.zip")
    # l'identifiant ne part qu'au serveur qui l'a demandé, jamais ailleurs
    entetes = (entetes_identification(v.identifiants)
               if v.source == "serveur" and _meme_hote(v.url_zip, v.adresse) else {})
    if ouvrir is not None:
        brut, _e = _appel(ouvrir, v.url_zip, delai, entetes)
        with open(chemin, "wb") as f:
            f.write(brut)
        if progression:
            progression(len(brut), v.taille or len(brut))
    else:
        req = _requete(v.url_zip, entetes)
        with _ouvreur().open(req, timeout=delai) as rep, open(chemin, "wb") as f:
            recu = 0
            total = v.taille or int(rep.headers.get("Content-Length") or 0)
            for bloc in iter(lambda: rep.read(1 << 16), b""):
                f.write(bloc)
                recu += len(bloc)
                if progression:
                    progression(recu, total)
    taille = os.path.getsize(chemin)
    if v.taille and taille != v.taille:
        raise ValueError(f"taille inattendue : {taille} octets reçus pour "
                         f"{v.taille} annoncés")
    if v.sha256:
        empreinte = sha256_de(chemin)
        if empreinte != v.sha256:
            raise ValueError("l'empreinte SHA-256 du zip ne correspond pas à "
                             "celle publiée avec la version")
    import zipfile
    if not zipfile.is_zipfile(chemin):
        raise ValueError("le fichier reçu n'est pas un zip")
    return chemin


# ============================================================ installation
# ce que l'ancienne version garde de côté : le programme, pas les données
DOSSIERS_PROGRAMME = ("carene", "tests", "tools", "docs", "examples")
FICHIERS_PROGRAMME = ("main.py", "carene.spec", "requirements.txt", "LISEZMOI.txt",
                      "installer_dependances.bat")


@dataclass
class Installation:
    script: str                      # le script à lancer
    ancienne: str                    # où l'ancienne version est mise de côté
    journal: str                     # ce que le script écrit
    commande: list = field(default_factory=list)   # pour le lancer


def _commande_de_relance() -> list:
    """Comment relancer Carène après la mise à jour : l'exécutable gelé, ou
    `python main.py` avec l'interpréteur qui tourne."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "main.py"]


def preparer_installation(zip_chemin: str, dossier_programme: str,
                          version_courante: str, pid: int | None = None,
                          relancer: list | None = None,
                          windows: bool | None = None) -> Installation:
    """Écrit le script d'installation et rend de quoi le lancer.

    Le script (un `.bat` sous Windows, un `.sh` ailleurs) :
    1. attend que le processus `pid` (Carène) soit fini ;
    2. copie le programme actuel dans `_ancienne_<version>/` — le dossier du
       navire, la configuration et les journaux n'en font pas partie ;
    3. déplie le zip PAR-DESSUS `dossier_programme` ;
    4. relance Carène (`relancer`), et note tout dans `journaux/mise_a_jour.log`.
    """
    windows = os.name == "nt" if windows is None else windows
    relancer = relancer or _commande_de_relance()
    pid = os.getpid() if pid is None else int(pid)
    ancienne = os.path.join(dossier_programme, f"_ancienne_{version_courante}")
    dossier_journal = os.path.join(dossier_programme, "journaux")
    os.makedirs(dossier_journal, exist_ok=True)
    journal = os.path.join(dossier_journal, "mise_a_jour.log")
    dossier_script = os.path.dirname(zip_chemin)
    if windows:
        script = os.path.join(dossier_script, "mise_a_jour_carene.bat")
        copies = "\n".join(
            [f'if exist "%PROG%\\{d}" xcopy /E /I /Q /Y "%PROG%\\{d}" "%ANC%\\{d}" >nul'
             for d in DOSSIERS_PROGRAMME]
            + [f'if exist "%PROG%\\{f}" copy /Y "%PROG%\\{f}" "%ANC%\\" >nul'
               for f in FICHIERS_PROGRAMME])
        relance = " ".join(f'"{m}"' for m in relancer)
        contenu = f"""@echo off
rem Mise a jour de Carene (D-70) : ecrit par Carene, lance apres sa fermeture.
set "PROG={dossier_programme}"
set "ANC={ancienne}"
set "ZIP={zip_chemin}"
set "LOG={journal}"
set "PID={pid}"
echo [%date% %time%] mise a jour : attente de la fermeture de Carene (PID %PID%) >> "%LOG%"
:attente
rem chemins complets : un PATH ou Git passe avant System32 donnerait le `find` de Git
"%SystemRoot%\\System32\\tasklist.exe" /FI "PID eq %PID%" 2>nul | "%SystemRoot%\\System32\\find.exe" "%PID%" >nul
if not errorlevel 1 (
  rem une seconde d'attente : `timeout` refuse une console redirigee, `ping` marche partout
  ping -n 2 127.0.0.1 >nul
  goto attente
)
echo [%date% %time%] Carene fermee ; ancienne version gardee dans "%ANC%" >> "%LOG%"
if not exist "%ANC%" mkdir "%ANC%"
{copies}
echo [%date% %time%] extraction de "%ZIP%" par-dessus "%PROG%" >> "%LOG%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%PROG%' -Force" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] ECHEC de l'extraction : l'ancienne version est intacte dans "%ANC%" >> "%LOG%"
  echo La mise a jour a echoue. Voir "%LOG%".
  pause
  exit /b 1
)
echo [%date% %time%] mise a jour installee ; relance de Carene >> "%LOG%"
cd /d "%PROG%"
start "" {relance}
exit /b 0
"""
        with open(script, "w", encoding="cp1252", errors="replace", newline="\r\n") as f:
            f.write(contenu)
        commande = ["cmd", "/c", "start", "", "/min", script]
    else:
        script = os.path.join(dossier_script, "mise_a_jour_carene.sh")
        copies = "\n".join(
            [f'[ -e "$PROG/{d}" ] && cp -R "$PROG/{d}" "$ANC/"' for d in DOSSIERS_PROGRAMME]
            + [f'[ -e "$PROG/{f}" ] && cp "$PROG/{f}" "$ANC/"' for f in FICHIERS_PROGRAMME])
        import shlex
        relance = " ".join(shlex.quote(m) for m in relancer)
        contenu = f"""#!/bin/sh
# Mise à jour de Carène (D-70) : écrit par Carène, lancé après sa fermeture.
PROG={shlex.quote(dossier_programme)}
ANC={shlex.quote(ancienne)}
ZIP={shlex.quote(zip_chemin)}
LOG={shlex.quote(journal)}
PID={pid}
echo "[$(date)] mise à jour : attente de la fermeture de Carène (PID $PID)" >> "$LOG"
while kill -0 "$PID" 2>/dev/null; do sleep 1; done
echo "[$(date)] Carène fermée ; ancienne version gardée dans $ANC" >> "$LOG"
mkdir -p "$ANC"
{copies}
echo "[$(date)] extraction de $ZIP par-dessus $PROG" >> "$LOG"
if ! python3 -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$ZIP" "$PROG" >> "$LOG" 2>&1; then
  echo "[$(date)] ÉCHEC de l'extraction : l'ancienne version est intacte dans $ANC" >> "$LOG"
  exit 1
fi
echo "[$(date)] mise à jour installée ; relance de Carène" >> "$LOG"
cd "$PROG" && {relance} &
exit 0
"""
        with open(script, "w", encoding="utf-8", newline="\n") as f:
            f.write(contenu)
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        commande = ["/bin/sh", script]
    return Installation(script=script, ancienne=ancienne, journal=journal,
                        commande=commande)


def lancer_script(inst: Installation) -> None:
    """Démarre le script en arrière-plan, détaché : il survit à Carène."""
    import subprocess
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(inst.commande, creationflags=flags, close_fds=True)
    else:
        subprocess.Popen(inst.commande, start_new_session=True, close_fds=True)
