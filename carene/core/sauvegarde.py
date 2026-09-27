# -*- coding: utf-8 -*-
"""La sauvegarde du navire : un zip qu'on emporte, qu'on rend, qu'on relit.

Le bord (17/09/2026), après avoir passé sa version pour une migration à la
main : « pour faciliter les mises à jour, on pourrait imaginer un
export/import type sauvegarde, en gardant dans les versions futures la
possibilité d'importer des sauvegardes de versions passées (au moins pour les
numéros de version majeure) ».

Ce que c'est — et ce que ce n'est pas :

- **une sauvegarde est le dossier du navire, tel quel**, fichier pour
  fichier : tables du dossier approuvé, géométrie décalquée, plans et
  calages, journal des points, conditions, brouillons, validation. Plus les
  réglages de l'application (`carene.config.json`), à part, parce qu'ils ne
  sont pas le navire. Rien n'est converti, résumé ni « nettoyé » à l'export :
  ce qu'on relit, c'est exactement ce qu'on avait ;
- **un manifeste dit ce qu'il y a dedans** : quelle version de Carène l'a
  écrite, quand, quel navire, quels fichiers, avec l'empreinte de chacun. À
  l'import on vérifie tout avant d'écrire quoi que ce soit — une archive
  tronquée par un mail ou une clé USB fatiguée se refuse, elle ne s'installe
  pas à moitié ;
- **importer ne détruit jamais** : le navire déjà en place est mis de côté
  (`<NOM>.avant_import-<horodatage>`), pas écrasé. Jeter, c'est le geste de
  l'utilisateur, jamais celui du logiciel ;
- **l'engagement de compatibilité tient au format des fichiers, pas au zip.**
  Le zip est trivial et le restera (des fichiers, un manifeste JSON). Ce qui
  compte, c'est que `navire.json`, `geometrie.json` (version 3), les points
  du journal (`carene-point`), les conditions (`carene-condition`) portent
  chacun leur `format` et leur `version`, et que leurs LECTEURS gardent la
  lecture des versions passées : un point sans `modifie_le`, une condition
  sans `brouillons`, un réglage `orientation` d'avant `disposition` se
  relisent aujourd'hui, et se reliront. La règle, consignée en D-54 : **une
  sauvegarde écrite par une version 2.x s'importe dans toute 2.x ultérieure
  et dans la 3.x** ; une 3.x saura encore lire une 2.x. Ce que la version
  suivante ne saurait plus relire serait converti à l'import, en le disant,
  jamais perdu en silence.

Rien ici ne dépend de Qt : `main.py --sauvegarde` l'appelle depuis la ligne
de commande, ce qui permet une sauvegarde automatique (tâche planifiée du
poste) sans ouvrir la fenêtre.
"""
from ..ecriture import ecriture_atomique
import hashlib
import json
import os
import shutil
import time
import zipfile
from dataclasses import dataclass, field

FORMAT = "carene-sauvegarde"
VERSION_FORMAT = 1          # ne s'incrémente que si le ZIP lui-même change de forme
MANIFESTE = "sauvegarde.json"
PREFIXE_NAVIRE = "navire/"          # tout le dossier du navire, tel quel
PREFIXE_CONFIG = "config/"          # carene.config.json, à part
NOM_CONFIG = "carene.config.json"
# ce qu'on ne met pas dans une sauvegarde : jamais des données du bord, que
# des résidus de machine
EXCLUS_DOSSIERS = {"__pycache__", ".git"}
# ... ni le verrou « ouvert par » du navire (voir core.verrou_navire) : il
# dit qui a le navire ouvert MAINTENANT, il n'a rien à faire dans une archive
EXCLUS_FICHIERS = {".DS_Store", "Thumbs.db", "desktop.ini", "carene.ouvert.json"}
# les clés de la configuration qui désignent CE poste : elles ne se
# transportent pas (voir `importer`)
CLES_CONFIG_LOCALES = {"ship_folder", "navire_supprime"}


class SauvegardeInvalide(Exception):
    """L'archive n'est pas une sauvegarde de Carène, ou elle est abîmée. Le
    message dit lequel, en français, pour la boîte de dialogue."""


@dataclass
class Fichier:
    chemin: str          # relatif au dossier du navire, séparateur « / »
    octets: int
    sha256: str


@dataclass
class Manifeste:
    """Ce que l'archive dit d'elle-même."""
    version_format: int
    version_carene: str
    date: str                       # ISO, seconde près, heure locale
    navire: str                     # le nom du navire (navire.json)
    dossier: str                    # le nom du dossier : « <NOM> »
    fichiers: list = field(default_factory=list)      # [Fichier] du navire
    config: bool = False            # carene.config.json est-il dedans ?
    contenu: dict = field(default_factory=dict)       # comptes, pour l'écran
    formats: dict = field(default_factory=dict)       # format/version par fichier clé

    @property
    def octets(self):
        return sum(f.octets for f in self.fichiers)

    def to_dict(self):
        return {
            "format": FORMAT, "version_format": self.version_format,
            "version_carene": self.version_carene, "date": self.date,
            "navire": self.navire, "dossier": self.dossier, "config": self.config,
            "contenu": self.contenu, "formats": self.formats,
            "fichiers": [{"chemin": f.chemin, "octets": f.octets, "sha256": f.sha256}
                         for f in self.fichiers],
        }

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            raise SauvegardeInvalide(
                "Ce fichier n'est pas une sauvegarde de Carène (son manifeste "
                "ne dit pas « %s »)." % FORMAT)
        try:
            vf = int(d.get("version_format", 0))
        except (TypeError, ValueError):
            raise SauvegardeInvalide("Le manifeste de la sauvegarde est illisible "
                                     "(version de format absente).")
        if vf > VERSION_FORMAT:
            raise SauvegardeInvalide(
                "Cette sauvegarde a été écrite par une version plus récente de "
                "Carène (%s, format %d) : mettez Carène à jour pour la relire."
                % (d.get("version_carene", "?"), vf))
        fichiers = []
        for f in d.get("fichiers", []) or []:
            try:
                fichiers.append(Fichier(str(f["chemin"]), int(f["octets"]), str(f["sha256"])))
            except (KeyError, TypeError, ValueError):
                raise SauvegardeInvalide("Le manifeste de la sauvegarde liste un "
                                         "fichier sans chemin ou sans empreinte.")
        return cls(version_format=vf,
                   version_carene=str(d.get("version_carene", "")),
                   date=str(d.get("date", "")),
                   navire=str(d.get("navire", "")),
                   dossier=str(d.get("dossier", "")),
                   fichiers=fichiers,
                   config=bool(d.get("config", False)),
                   contenu=dict(d.get("contenu", {}) or {}),
                   formats=dict(d.get("formats", {}) or {}))

    def resume(self):
        """Deux ou trois lignes pour la boîte de dialogue."""
        c = self.contenu
        lignes = ["Navire : %s (dossier %s)" % (self.navire or "?", self.dossier or "?"),
                  "Écrite par Carène %s le %s" % (self.version_carene or "?",
                                                   _date_lisible(self.date))]
        detail = []
        if "points" in c:
            detail.append("%d point(s) du journal" % c["points"])
        if c.get("brouillons"):
            detail.append("%d brouillon(s)" % c["brouillons"])
        if "conditions" in c:
            detail.append("%d condition(s)" % c["conditions"])
        if "plans" in c:
            detail.append("%d plan(s)" % c["plans"])
        detail.append("%d fichier(s), %s" % (len(self.fichiers), _taille(self.octets)))
        lignes.append(" · ".join(detail))
        if self.config:
            lignes.append("Avec les réglages de l'application (carene.config.json).")
        return "\n".join(lignes)


# ---------------------------------------------------------------- écriture
def nom_de_fichier(navire, quand=None):
    """« sauvegarde_<NOM>_2026-09-17_183005.zip » : le navire et l'instant,
    lisibles dans l'explorateur sans ouvrir l'archive. À la SECONDE (D-77) :
    à la minute, deux sauvegardes faites coup sur coup portaient le même nom,
    et la seconde écrasait la première."""
    quand = quand or time.localtime()
    propre = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (navire or "navire"))
    return "sauvegarde_%s_%s.zip" % (propre, time.strftime("%Y-%m-%d_%H%M%S", quand))


def _fichiers_du_dossier(dossier):
    """Tous les fichiers du dossier, chemins relatifs en « / », triés — le
    même ordre à chaque export, pour qu'on puisse comparer deux archives."""
    out = []
    for racine, dirs, fichiers in os.walk(dossier):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUS_DOSSIERS)
        for nom in sorted(fichiers):
            if nom in EXCLUS_FICHIERS:
                continue
            # les filets de l'écriture protégée (D-77) : la copie de la
            # version précédente et le provisoire d'une écriture en cours
            if nom.endswith(".bak") or nom.endswith(".tmp"):
                continue
            complet = os.path.join(racine, nom)
            rel = os.path.relpath(complet, dossier).replace(os.sep, "/")
            out.append((rel, complet))
    return out


def _sha256(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 16), b""):
            h.update(bloc)
    return h.hexdigest()


def _lire_json(chemin):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def nom_du_navire(dossier):
    """Le nom lu dans `navire.json`, sinon dans `geometrie.json`, sinon "".
    (La même lecture que `app_paths.ship_name`, sans dépendre de Qt.)"""
    d = _lire_json(os.path.join(dossier, "navire.json"))
    if isinstance(d, dict):
        nom = (d.get("identification") or {}).get("nom", "")
        if nom:
            return str(nom)
    d = _lire_json(os.path.join(dossier, "geometrie.json"))
    if isinstance(d, dict):
        return str(d.get("ship_name", "") or "")
    return ""


def _inventaire(dossier, fichiers):
    """Les comptes et les formats que le manifeste annonce : ce que l'écran
    montre AVANT d'importer, pour qu'on sache ce qu'on va reprendre."""
    contenu = {
        "points": sum(1 for rel, _c in fichiers
                      if rel.startswith("journal/") and rel.endswith(".json")),
        "conditions": sum(1 for rel, _c in fichiers
                          if rel.startswith("conditions/") and rel.endswith(".json")),
        "plans": sum(1 for rel, _c in fichiers
                     if rel.startswith("plans/") and not rel.endswith(".json")
                     and not rel.endswith(".npz")),
    }
    brouillons = 0
    for rel, complet in fichiers:
        if rel.startswith("journal/") and rel.endswith(".json"):
            d = _lire_json(complet)
            cond = (d or {}).get("condition") or {}
            brouillons += len(cond.get("brouillons") or [])
    if brouillons:
        contenu["brouillons"] = brouillons
    formats = {}
    for nom in ("navire.json", "geometrie.json"):
        d = _lire_json(os.path.join(dossier, nom))
        if isinstance(d, dict):
            formats[nom] = {"format": d.get("format", ""), "version": d.get("version", "")}
    premier = next((c for rel, c in fichiers
                    if rel.startswith("journal/") and rel.endswith(".json")), None)
    if premier:
        d = _lire_json(premier)
        if isinstance(d, dict):
            formats["journal"] = {"format": d.get("format", ""), "version": d.get("version", "")}
    return contenu, formats


def exporter(dossier_navire, chemin_zip, config=None, version_carene=""):
    """Écrit la sauvegarde. Renvoie le manifeste.

    `config` : le carene.config.json à joindre (None : aucun). L'archive est
    écrite dans un fichier temporaire à côté, puis renommée : une sauvegarde
    interrompue ne laisse pas un zip à moitié écrit sous son vrai nom."""
    if not os.path.isdir(dossier_navire):
        raise SauvegardeInvalide("Le dossier du navire n'existe pas : %s" % dossier_navire)
    fichiers = _fichiers_du_dossier(dossier_navire)
    if not fichiers:
        raise SauvegardeInvalide("Le dossier du navire est vide : rien à sauvegarder.")
    contenu, formats = _inventaire(dossier_navire, fichiers)
    m = Manifeste(version_format=VERSION_FORMAT, version_carene=version_carene,
                  date=time.strftime("%Y-%m-%dT%H:%M:%S"),
                  navire=nom_du_navire(dossier_navire),
                  dossier=os.path.basename(os.path.normpath(dossier_navire)),
                  contenu=contenu, formats=formats)
    os.makedirs(os.path.dirname(os.path.abspath(chemin_zip)) or ".", exist_ok=True)
    provisoire = chemin_zip + ".partiel"
    try:
        with zipfile.ZipFile(provisoire, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, complet in fichiers:
                # UNE SEULE LECTURE par fichier : les octets archivés sont ceux
                # dont on calcule l'empreinte et la taille. Lire deux fois
                # (`z.write` puis `_sha256`) donnait, si un point
                # s'enregistrait entre les deux, une archive dont l'empreinte
                # ne correspondait pas au contenu — et que l'import refusait
                # EN ENTIER, le jour où l'on en avait besoin (P-9).
                with open(complet, "rb") as f:
                    octets = f.read()
                info = zipfile.ZipInfo.from_file(complet, PREFIXE_NAVIRE + rel)
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, octets)
                m.fichiers.append(Fichier(rel, len(octets),
                                          hashlib.sha256(octets).hexdigest()))
            if config and os.path.isfile(config):
                z.write(config, PREFIXE_CONFIG + NOM_CONFIG)
                m.config = True
            z.writestr(MANIFESTE, json.dumps(m.to_dict(), ensure_ascii=False, indent=1))
        os.replace(provisoire, chemin_zip)
    except BaseException:
        try:
            os.remove(provisoire)
        except OSError:
            pass
        raise
    return m


# ----------------------------------------------------------------- lecture
def lire(chemin_zip):
    """Le manifeste d'une sauvegarde, après les vérifications qui ne coûtent
    rien : c'est un zip, il a un manifeste, le manifeste est le nôtre, chaque
    fichier annoncé est bien dans l'archive. Les empreintes, c'est `verifier`."""
    if not zipfile.is_zipfile(chemin_zip):
        raise SauvegardeInvalide("Ce fichier n'est pas une archive zip lisible : %s"
                                 % os.path.basename(chemin_zip))
    with zipfile.ZipFile(chemin_zip) as z:
        noms = set(z.namelist())
        if MANIFESTE not in noms:
            raise SauvegardeInvalide(
                "Ce zip n'est pas une sauvegarde de Carène : il n'a pas de "
                "manifeste %s. (Une livraison de Carène ou un dossier zippé à la "
                "main n'est pas une sauvegarde — passez par « Navire › Exporter "
                "une sauvegarde du navire… ».)" % MANIFESTE)
        try:
            d = json.loads(z.read(MANIFESTE).decode("utf-8"))
        except ValueError:
            raise SauvegardeInvalide("Le manifeste de la sauvegarde est illisible.")
        m = Manifeste.from_dict(d)
        manquants = [f.chemin for f in m.fichiers if PREFIXE_NAVIRE + f.chemin not in noms]
        if manquants:
            raise SauvegardeInvalide(
                "La sauvegarde est incomplète : %d fichier(s) annoncé(s) par le "
                "manifeste manquent dans l'archive (%s%s)."
                % (len(manquants), ", ".join(manquants[:3]), "…" if len(manquants) > 3 else ""))
        if m.config and PREFIXE_CONFIG + NOM_CONFIG not in noms:
            m.config = False
        for f in m.fichiers:
            _chemin_sur(f.chemin)
    return m


def verifier(chemin_zip):
    """Les fichiers dont l'empreinte ne correspond pas : [] si tout est sain."""
    m = lire(chemin_zip)
    abimes = []
    with zipfile.ZipFile(chemin_zip) as z:
        for f in m.fichiers:
            h = hashlib.sha256()
            with z.open(PREFIXE_NAVIRE + f.chemin) as src:
                for bloc in iter(lambda: src.read(1 << 16), b""):
                    h.update(bloc)
            if h.hexdigest() != f.sha256:
                abimes.append(f.chemin)
    return abimes


def _chemin_sur(rel):
    """Un chemin relatif qui reste DANS le dossier : pas d'absolu, pas de
    « .. » — une archive forgée ne doit pas pouvoir écrire ailleurs."""
    parts = rel.split("/")
    if not rel or rel.startswith("/") or (len(rel) > 1 and rel[1] == ":") \
            or any(p in ("", ".", "..") for p in parts):
        raise SauvegardeInvalide("La sauvegarde contient un chemin de fichier "
                                 "inacceptable : %r" % rel)
    return parts


# ------------------------------------------------------------------ import
@dataclass
class Resultat:
    dossier: str              # où le navire a été écrit
    mis_de_cote: str = ""     # l'ancien dossier, renommé — "" s'il n'y en avait pas
    fichiers: int = 0
    config_reprise: bool = False
    manifeste: Manifeste = None


def importer(chemin_zip, dossier_navires, nom_dossier=None,
             config_cible=None, reprendre_config=False):
    """Restaure la sauvegarde dans `dossier_navires/<nom>/`. Renvoie `Resultat`.

    Ordre des opérations, et il compte : on VÉRIFIE l'archive entière (les
    empreintes comprises) avant de toucher au disque ; on extrait dans un
    dossier provisoire à côté ; on met de côté l'ancien navire s'il y en a
    un ; on renomme le provisoire à sa place. À aucun moment le navire en
    place n'est à moitié remplacé, et l'ancien reste sur le disque.

    `reprendre_config` : les réglages de l'application contenus dans la
    sauvegarde (répartiteur, préférences) sont fusionnés dans `config_cible`
    — sauf ce qui désigne un poste précis (`ship_folder`), qui n'a aucun
    sens transporté d'une machine à l'autre."""
    m = lire(chemin_zip)
    abimes = verifier(chemin_zip)
    if abimes:
        raise SauvegardeInvalide(
            "La sauvegarde est abîmée : %d fichier(s) n'ont plus l'empreinte "
            "annoncée par le manifeste (%s%s). Rien n'a été importé — reprenez "
            "une autre copie de l'archive."
            % (len(abimes), ", ".join(abimes[:3]), "…" if len(abimes) > 3 else ""))
    nom = nom_dossier or m.dossier or m.navire or "navire"
    _chemin_sur(nom)
    os.makedirs(dossier_navires, exist_ok=True)
    dest = os.path.join(dossier_navires, nom)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    provisoire = os.path.join(dossier_navires, ".import-%s-%s" % (nom, stamp))
    if os.path.exists(provisoire):
        shutil.rmtree(provisoire)
    n = 0
    try:
        with zipfile.ZipFile(chemin_zip) as z:
            for f in m.fichiers:
                cible = os.path.join(provisoire, *_chemin_sur(f.chemin))
                os.makedirs(os.path.dirname(cible), exist_ok=True)
                with z.open(PREFIXE_NAVIRE + f.chemin) as src, open(cible, "wb") as out:
                    shutil.copyfileobj(src, out)
                n += 1
            # la configuration est LUE ici, mais ne se fusionne qu'une fois
            # le navire en place : un import qui échoue ne doit rien changer
            # aux réglages du poste (P-12)
            config_lue = None
            if reprendre_config and m.config and config_cible:
                config_lue = json.loads(z.read(PREFIXE_CONFIG + NOM_CONFIG).decode("utf-8"))
    except BaseException:
        shutil.rmtree(provisoire, ignore_errors=True)
        raise
    mis_de_cote = ""
    if os.path.exists(dest):
        mis_de_cote = _nom_libre("%s.avant_import-%s" % (dest, stamp))
        os.rename(dest, mis_de_cote)
    try:
        os.rename(provisoire, dest)
    except OSError:
        # LE SECOND GESTE A ÉCHOUÉ (fichiers fraîchement écrits tenus par un
        # antivirus, droits du partage) : le navire en place a déjà été mis de
        # côté. On le REMET, et on ne laisse pas traîner le provisoire — sans
        # quoi le message « le navire en place n'a pas été touché » était
        # faux, et le poste n'avait plus de navire (P-12).
        if mis_de_cote:
            try:
                os.rename(mis_de_cote, dest)
            except OSError:
                pass
        shutil.rmtree(provisoire, ignore_errors=True)
        raise
    config_reprise = (_fusionner_config(config_lue, config_cible)
                      if config_lue is not None else False)
    return Resultat(dossier=dest, mis_de_cote=mis_de_cote, fichiers=n,
                    config_reprise=config_reprise, manifeste=m)


def _nom_libre(chemin):
    """`chemin`, ou `chemin-2`, `-3`… : deux imports dans la même seconde ne
    doivent pas se disputer le même nom de mise de côté."""
    if not os.path.exists(chemin):
        return chemin
    n = 2
    while os.path.exists("%s-%d" % (chemin, n)):
        n += 1
    return "%s-%d" % (chemin, n)


def _fusionner_config(source, config_cible):
    """Les réglages de la sauvegarde par-dessus ceux du poste — sauf les clés
    locales. Renvoie True si quelque chose a été écrit."""
    if not isinstance(source, dict):
        return False
    try:
        with open(config_cible, encoding="utf-8") as f:
            cible = json.load(f)
        if not isinstance(cible, dict):
            cible = {}
    except (OSError, ValueError):
        cible = {}
    repris = {k: v for k, v in source.items() if k not in CLES_CONFIG_LOCALES}
    if not repris:
        return False
    cible.update(repris)
    os.makedirs(os.path.dirname(os.path.abspath(config_cible)) or ".", exist_ok=True)
    with ecriture_atomique(config_cible) as f:
        json.dump(cible, f, ensure_ascii=False, indent=1)
    return True


# ------------------------------------------------------------------ divers
def _taille(octets):
    if octets < 1024:
        return "%d o" % octets
    if octets < 1024 * 1024:
        return "%.0f Ko" % (octets / 1024)
    return "%.1f Mo" % (octets / (1024 * 1024))


def _date_lisible(iso):
    try:
        t = time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
        return time.strftime("%d/%m/%Y %H:%M", t)
    except (ValueError, TypeError):
        return iso or "?"
