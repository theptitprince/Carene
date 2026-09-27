# -*- coding: utf-8 -*-
"""La bibliothèque des réglementations de stabilité (3.0.0, D-79) — sans Qt.

Le bord (24/09/2026) : « Tous les critères doivent être dispo dans le
logiciel. Juste on choisit nous-mêmes lesquels nous intéressent (en
définissant le type de bateau et/ou propulsion…) » ; « les différentes
réglementations de stab ne doivent pas être codées en dur, pour permettre
leur mise à jour facilement » ; « on est sur une aide, pas un programme
certifié. On se limite à l'état intact. »

Trois idées, et rien de plus :

1. **Une réglementation est un FICHIER de données** (`carene/reglements/
   *.json`, format « carene-reglement ») : son texte de référence, sa
   version, son statut (`verifie` : rejouée sur un dossier approuvé ;
   `relu` : relue ligne à ligne sur le texte officiel, pas encore rejouée sur
   un dossier approuvé ; `a_relire` : à relire sur le texte officiel avant
   usage — Carène le dit à chaque calcul), le profil de navire auquel elle s'applique, la situation
   où elle s'applique (toujours, sans voile, sous voile), et ses critères —
   chacun avec son paragraphe, son seuil et sa **brique** de calcul. Mettre
   une règle à jour, c'est remplacer son fichier.

2. **Le code ne porte que des briques de calcul génériques** (`BRIQUES`) :
   aire sous GZ entre deux angles (plafonnée à θf), GZ maximal au-delà d'un
   angle, angle du GZmax, GM, angle d'équilibre sous un bras de gîte (vent,
   giration, passagers), critère météo (dont les tables de l'OMI viennent du
   fichier), critère NR500 sous voile, ligne de charge. Toute la stabilité à
   l'état intact s'écrit avec elles.

3. **Le profil du navire propose, l'officier dispose** (`proposer`) : à
   partir du type de navire, de la propulsion, de la longueur et des
   cargaisons particulières, Carène propose les réglementations applicables ;
   le navire retient celles qu'on coche (`navire.json › reglements`), avec
   leur version — et les dossiers d'avant, qui n'ont que `criteres`, sont
   relus tels quels (`reglements_du_navire`).
"""
from __future__ import annotations

import copy
import glob
import json
import math
import os
from dataclasses import dataclass, field

FORMAT = "carene-reglement"
VERSION_FORMAT = 1
DOSSIER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "reglements")

# ------------------------------------------------------------------ profil
TYPES = [
    ("cargo", "Navire de charge"),
    ("passagers", "Navire à passagers"),
    ("peche", "Navire de pêche"),
    ("servitude", "Navire de servitude, remorqueur, travaux"),
    ("formation", "Navire-école, formation à la voile"),
    ("voilier_traditionnel", "Voilier traditionnel"),
    ("autre", "Autre"),
]
PROPULSIONS = [("moteur", "Moteur"), ("voile", "Voile seule"), ("mixte", "Voile et moteur")]
CARGAISONS = [("bois_en_pontee", "Bois en pontée")]
SITUATIONS = ("toujours", "sans_voile", "sous_voile")
STATUTS = {"verifie": "vérifiée",
           "relu": "relue sur le texte officiel, pas encore rejouée sur un dossier approuvé",
           "a_relire": "à relire sur le texte officiel"}

# Les anciens jeux de critères de navire.json (`criteres`) et la
# réglementation de la bibliothèque qui les remplace ; pour chacun, de quelle
# clé du dossier vient le seuil de quel critère.
CORRESPONDANCE_ANCIENNE = {
    "is2008_general": ("IMO_IS2008_A_2_2", {
        "aire_0_30_m_rad_min": "IS2008_A1", "aire_0_40_m_rad_min": "IS2008_A2",
        "aire_30_40_m_rad_min": "IS2008_A3", "gz_max_m_min": "IS2008_GZ",
        "angle_gz_max_deg_min": "IS2008_ANG", "gm0_corrige_m_min": "IS2008_GM"}),
    "critere_meteo": ("IMO_IS2008_A_2_3", {}),
    "nr500_voile": ("BV_NR500_GM", {"gm0_corrige_m_min": "NR500_GM"}),
    "nr500_voile_sous_voile": ("BV_NR500_SOUS_VOILE", {}),
}


@dataclass
class Critere:
    code: str
    libelle: str
    brique: str
    parametres: dict = field(default_factory=dict)
    seuil: float = None
    comparaison: str = ">="
    unite: str = ""
    reference: str = ""


@dataclass
class Reglement:
    id: str
    titre: str
    texte: str = ""
    version: str = ""
    statut: str = "a_relire"
    verification: str = ""
    applicabilite: dict = field(default_factory=dict)
    situation: str = "toujours"
    criteres: list = field(default_factory=list)
    tables: dict = field(default_factory=dict)
    chemin: str = ""

    @property
    def a_relire(self):
        return self.statut not in ("verifie", "relu")

    @property
    def rejouee(self):
        """Rejouée sur un dossier approuvé : elle rejoint le tableau général."""
        return self.statut == "verifie"

    def titre_court(self):
        return self.titre + (" — à relire" if self.a_relire else "")


class ReglementInvalide(ValueError):
    pass


def lire_fichier(chemin) -> Reglement:
    """Un fichier de réglementation, vérifié : format, identifiant, briques
    connues, situation connue. Lève ReglementInvalide en le disant."""
    try:
        with open(chemin, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        raise ReglementInvalide(f"{os.path.basename(chemin)} : illisible ({e})") from e
    if d.get("format") != FORMAT:
        raise ReglementInvalide(f"{os.path.basename(chemin)} : ce n'est pas une réglementation Carène")
    if int(d.get("version_format", 0)) > VERSION_FORMAT:
        raise ReglementInvalide(f"{os.path.basename(chemin)} : format plus récent que ce Carène")
    rid = str(d.get("id") or "").strip()
    if not rid:
        raise ReglementInvalide(f"{os.path.basename(chemin)} : pas d'identifiant")
    situation = d.get("situation", "toujours")
    if situation not in SITUATIONS:
        raise ReglementInvalide(f"{rid} : situation inconnue « {situation} »")
    criteres = []
    for c in d.get("criteres") or []:
        brique = c.get("brique")
        if brique not in BRIQUES:
            raise ReglementInvalide(f"{rid} : brique de calcul inconnue « {brique} »")
        seuil = c.get("seuil")
        criteres.append(Critere(
            code=str(c["code"]), libelle=str(c.get("libelle") or c["code"]),
            brique=brique, parametres=dict(c.get("parametres") or {}),
            seuil=None if seuil is None else float(seuil),
            comparaison=str(c.get("comparaison") or ">="),
            unite=str(c.get("unite") or ""), reference=str(c.get("reference") or "")))
    return Reglement(
        id=rid, titre=str(d.get("titre") or rid), texte=str(d.get("texte") or ""),
        version=str(d.get("version") or ""), statut=str(d.get("statut") or "a_relire"),
        verification=str(d.get("verification") or ""),
        applicabilite=dict(d.get("applicabilite") or {}), situation=situation,
        criteres=criteres, tables=dict(d.get("tables") or {}), chemin=chemin)


_CACHE = {}


def bibliotheque(dossier=None):
    """{id: Reglement} de la bibliothèque, et la liste des fichiers refusés.

    Un fichier illisible n'empêche pas les autres de se charger : il est
    nommé dans `messages`, et le reste de la bibliothèque sert."""
    dossier = dossier or DOSSIER
    cle = (dossier, tuple(sorted((os.path.basename(p), os.path.getmtime(p))
                                 for p in glob.glob(os.path.join(dossier, "*.json")))))
    if cle in _CACHE:
        return _CACHE[cle]
    regs, messages = {}, []
    for chemin in sorted(glob.glob(os.path.join(dossier, "*.json"))):
        try:
            r = lire_fichier(chemin)
        except ReglementInvalide as e:
            messages.append(str(e))
            continue
        if r.id in regs:
            messages.append(f"{r.id} : deux fichiers portent cet identifiant — "
                            f"{os.path.basename(chemin)} est ignoré")
            continue
        regs[r.id] = r
    _CACHE.clear()
    _CACHE[cle] = (regs, messages)
    return regs, messages


# --------------------------------------------------------------- proposer
def profil_du_navire(navire_ou_manifeste):
    """Le profil déclaré (`navire.json › profil`), complété de ce qu'on sait
    déjà : la longueur de franc-bord ; un navire qui décrit des voilures est
    au moins « mixte »."""
    man = getattr(navire_ou_manifeste, "manifest", navire_ou_manifeste) or {}
    p = dict(man.get("profil") or {})
    dims = man.get("dimensions") or {}
    if not p.get("longueur_m"):
        p["longueur_m"] = (dims.get("longueur_de_franc_bord_m")
                           or dims.get("longueur_entre_pp_hydro_m"))
    if not p.get("propulsion"):
        voilures = man.get("profils_vent") or {}
        p["propulsion"] = "mixte" if voilures else ""
    p.setdefault("type", "")
    p.setdefault("cargaisons", [])
    return p


def s_applique(reglement, profil):
    """(vrai/faux, raison) : la réglementation convient-elle à ce profil ?"""
    a = reglement.applicabilite or {}
    t, prop = profil.get("type"), profil.get("propulsion")
    if t and a.get("types") and t not in a["types"]:
        return False, "type de navire non visé"
    if prop and a.get("propulsion") and prop not in a["propulsion"]:
        return False, "propulsion non visée"
    lmin = a.get("longueur_min_m")
    try:
        longueur = float(profil.get("longueur_m") or 0.0)
    except (TypeError, ValueError):
        longueur = 0.0
    if lmin and longueur and longueur < float(lmin):
        return False, f"navire de moins de {float(lmin):g} m"
    lmax = a.get("longueur_max_m")
    if lmax and longueur and longueur >= float(lmax):
        return False, f"navire de {float(lmax):g} m ou plus"
    besoin = a.get("cargaisons") or []
    if besoin and not set(besoin) & set(profil.get("cargaisons") or []):
        return False, "cargaison particulière non déclarée"
    if not t and not prop:
        return True, "profil non renseigné — proposée par défaut"
    return True, "convient au profil déclaré"


def proposer(profil, biblio=None):
    """[(Reglement, raison)] des réglementations que le profil appelle."""
    regs = (biblio or bibliotheque()[0])
    out = []
    for r in sorted(regs.values(), key=lambda r: r.id):
        ok, raison = s_applique(r, profil)
        if ok:
            out.append((r, raison))
    return out


# --------------------------------------------------- ce que le navire retient
@dataclass
class Retenue:
    """Une réglementation retenue par le navire, avec ses surcharges : les
    seuils propres au dossier (par code de critère) et les paramètres propres
    au dossier (conventions de calcul qu'il imprime)."""
    reglement: Reglement
    seuils: dict = field(default_factory=dict)
    parametres: dict = field(default_factory=dict)


def reglements_du_navire(navire, biblio=None):
    """[Retenue] des réglementations du navire, et [message].

    `navire.json › reglements` (3.0) : [{"id", "version", "seuils",
    "parametres"}]. Un dossier d'avant la 3.0 n'a que `criteres` : il est
    relu par `CORRESPONDANCE_ANCIENNE`, seuils et conventions compris — un
    navire ne change pas de verdict parce qu'on a changé de version (D-54) —,
    et la ligne de charge s'y ajoute (elle ne contrôle rien sans marque d'été,
    et le dit)."""
    regs, messages = (biblio, []) if biblio is not None else bibliotheque()
    messages = list(messages)
    man = getattr(navire, "manifest", None) or {}
    out = []
    if isinstance(man.get("reglements"), list):
        for d in man["reglements"]:
            rid = str(d.get("id") or "")
            r = regs.get(rid)
            if r is None:
                messages.append(f"Réglementation « {rid} » retenue par le navire mais "
                                "absente de la bibliothèque de ce Carène : non évaluée.")
                continue
            if d.get("version") and r.version and d["version"] != r.version:
                messages.append(f"{r.titre} : le navire l'a retenue en version "
                                f"{d['version']}, la bibliothèque porte la version "
                                f"{r.version} — c'est elle qui est appliquée.")
            out.append(Retenue(r, dict(d.get("seuils") or {}),
                               dict(d.get("parametres") or {})))
        return out, messages
    anciens = getattr(navire, "criteres", None) or man.get("criteres") or {}
    for cle, bloc in anciens.items():
        if cle not in CORRESPONDANCE_ANCIENNE or not isinstance(bloc, dict):
            continue
        rid, cles = CORRESPONDANCE_ANCIENNE[cle]
        r = regs.get(rid)
        if r is None:
            continue
        seuils = {code: float(bloc[k]) for k, code in cles.items()
                  if isinstance(bloc.get(k), (int, float))}
        parametres = {k: v for k, v in bloc.items()
                      if k not in cles and k != "reference" and not str(k).startswith("note")}
        out.append(Retenue(r, seuils, parametres))
    ll = regs.get("LL1966_LIGNE_DE_CHARGE")
    if ll is not None and not any(x.reglement.id == ll.id for x in out):
        out.append(Retenue(ll))
    return out, messages


def pour_navire_json(retenues):
    """La liste à écrire dans `navire.json › reglements`."""
    out = []
    for x in retenues:
        d = {"id": x.reglement.id, "version": x.reglement.version}
        if x.seuils:
            d["seuils"] = dict(x.seuils)
        if x.parametres:
            d["parametres"] = dict(x.parametres)
        out.append(d)
    return out


# ------------------------------------------------------------------ évaluer
@dataclass
class Contexte:
    """Tout ce qu'une brique peut demander, pour UN point de chargement."""
    navire: object
    eq: object
    gz: object
    theta_f_deg: float = None
    vent: dict = None               # surface au vent de la voilure portée
    meteo: object = None            # fonction (critere, tables) -> WeatherResult
    profil: dict = field(default_factory=dict)
    groupe: str = ""


def _seuil(critere, retenue):
    s = retenue.seuils.get(critere.code, critere.seuil)
    return None if s is None else float(s)


def _depuis(gz):
    return ("" if gz.origine_deg is None or abs(gz.origine_deg) < 0.05
            else f" depuis la gîte d'équilibre {gz.origine_deg:+.1f}°")


def _x_f(ctx):
    if ctx.theta_f_deg is None or ctx.gz.origine_deg is None:
        return None
    return float(ctx.theta_f_deg) - abs(ctx.gz.origine_deg)


def _b_aire(ctx, c, r, rep, groupe):
    from .stability import aire_residuelle
    gz = ctx.gz
    de, a = float(c.parametres.get("de_deg", 0.0)), float(c.parametres.get("a_deg", 30.0))
    x_f = _x_f(ctx) if c.parametres.get("plafond_theta_f") else None
    borne = a if x_f is None else min(a, x_f)
    texte = f"{borne:.0f}°" + (" (θf)" if x_f is not None and borne < a else "")
    valeur = aire_residuelle(gz, de, borne) if borne > de else float("nan")
    if gz.residuel_max_deg < borne - 1e-9:
        rep.messages.append(
            f"La courbe résiduelle s'arrête à {gz.residuel_max_deg:.1f}° : l'aire "
            f"jusqu'à {texte} ne peut pas être mesurée sans prolonger la table.")
    libelle = c.libelle
    if "(ou θf)" in libelle or c.parametres.get("plafond_theta_f"):
        libelle = f"Aire {de:g}°-{texte}"
        if "bois" in c.libelle:
            libelle += ", bois en pontée"
    rep.add(c.code, libelle + _depuis(gz), valeur, _seuil(c, r), c.comparaison,
            c.unite, groupe=groupe)


def _b_gz_au_dela(ctx, c, r, rep, groupe):
    from .criteria import _max_au_dela
    rep.add(c.code, c.libelle, _max_au_dela(ctx.gz, float(c.parametres.get("angle_deg", 0.0))),
            _seuil(c, r), c.comparaison, c.unite, groupe=groupe)


def _b_angle_gz_max(ctx, c, r, rep, groupe):
    rep.add(c.code, c.libelle + _depuis(ctx.gz), ctx.gz.angle_gz_max_deg,
            _seuil(c, r), c.comparaison, c.unite, groupe=groupe)


def _b_gm(ctx, c, r, rep, groupe):
    rep.add(c.code, c.libelle, ctx.gz.gm_corrige_m, _seuil(c, r), c.comparaison,
            c.unite, groupe=groupe)


def _b_ligne_de_charge(ctx, c, r, rep, groupe):
    from .criteria import evaluate_ligne_de_charge
    rep.fusionner(evaluate_ligne_de_charge(ctx.navire, ctx.eq, groupe=groupe or "Ligne de charge"))


def _b_meteo(ctx, c, r, rep, groupe):
    from .criteria import rapport_critere_meteo
    critere = dict(c.parametres)
    critere.update(r.parametres)
    if ctx.meteo is None:
        rep.add("METEO_ABSENT", "Critère météo — surface au vent non décrite au dossier",
                float("nan"), float("nan"), ">=", groupe=groupe)
        rep.messages.append("Le critère météo est retenu, mais la surface au vent n'est pas "
                            "connue pour ce point : il n'est pas évalué (INCOMPLET).")
        return
    wres, motif = ctx.meteo(critere, r.reglement.tables)
    if wres is None:
        rep.add("VENT_ABSENT", "Critère de vent — non évaluable : " + motif,
                float("nan"), float("nan"), ">=", groupe=groupe)
        return
    rep.fusionner(rapport_critere_meteo(ctx.navire, wres, groupe=groupe, critere=critere))


def _b_nr500(ctx, c, r, rep, groupe):
    from .criteria import evaluate_nr500_voilier
    if ctx.vent is None:
        rep.add("VENT_ABSENT", "Critère sous voile — surface au vent inconnue",
                float("nan"), float("nan"), ">=", groupe=groupe)
        return
    seuils = dict(c.parametres)
    seuils.update(r.parametres)
    rep.fusionner(evaluate_nr500_voilier(
        ctx.navire, ctx.gz, ctx.eq, ctx.eq.displacement_t, ctx.vent,
        theta_f_deg=ctx.theta_f_deg, groupe=groupe, seuils=seuils))


def _b_bras_gite(ctx, c, r, rep, groupe):
    """Angle d'équilibre sous un bras de gîte l(φ) = l0·cos φ (ou constant) :
    giration (M = coef · v0²/L · Δ · (KG − d/2)) ou moment donné au profil."""
    from .weather import G, _CourbeCote
    p = dict(c.parametres)
    p.update(r.parametres)
    gz, eq = ctx.gz, ctx.eq
    moment = p.get("moment")
    delta = float(eq.displacement_t)
    if moment == "giration":
        v_kn = ctx.profil.get("vitesse_service_kn")
        # L_WL, la longueur à la flottaison (§ 3.1.2) : celle de la table
        # hydrostatique à ce point si elle la porte, sinon celle du profil,
        # sinon la longueur de franc-bord — et on le dit
        hydro = getattr(eq, "hydro", None) or {}
        longueur = next((hydro[k] for k in ("LWL_m", "Lwl_m", "L_flottaison_m")
                         if hydro.get(k)), None)
        if not longueur:
            longueur = ctx.profil.get("longueur_flottaison_m")
        if not longueur:
            longueur = ctx.profil.get("longueur_m")
            if longueur:
                rep.messages.append(
                    f"{c.libelle} : la longueur à la flottaison n'est pas tabulée — la "
                    f"longueur de franc-bord ({float(longueur):.2f} m) la remplace (approché).")
        if not v_kn or not longueur:
            rep.add(c.code, c.libelle + " — vitesse de service ou longueur inconnue",
                    float("nan"), _seuil(c, r), c.comparaison, c.unite, groupe=groupe)
            return
        v = float(v_kn) * 0.514444
        kg = gz.kg_effectif_m
        m_knm = float(p.get("coefficient", 0.200)) * v * v / float(longueur) * delta \
            * (kg - eq.draft_m / 2.0)
        l0 = m_knm / (G * delta)
    elif isinstance(moment, str) and moment.startswith("profil:"):
        brut = ctx.profil.get(moment.split(":", 1)[1])
        if not brut:
            rep.add(c.code, c.libelle + " — moment d'inclinaison non renseigné au profil",
                    float("nan"), _seuil(c, r), c.comparaison, c.unite, groupe=groupe)
            return
        l0 = float(brut) / delta
    else:
        l0 = float(p.get("bras_m") or 0.0)
    loi = p.get("loi", "cos")
    courbe = _CourbeCote(gz)
    angle = float("nan")
    phi, pas = 0.0, 0.05
    prec = courbe.gz(0.0) - l0
    while phi < min(60.0, courbe.sous_le_vent_max):
        phi2 = phi + pas
        lever = l0 * (math.cos(math.radians(phi2)) if loi == "cos" else 1.0)
        cur = courbe.gz(phi2) - lever
        if prec < 0 <= cur or prec == 0:
            angle = phi + pas * (-prec) / (cur - prec) if cur != prec else phi
            break
        phi, prec = phi2, cur
    rep.add(c.code, c.libelle, angle, _seuil(c, r), c.comparaison, c.unite, groupe=groupe)
    if angle != angle:
        rep.messages.append(f"{c.libelle} : le bras de gîte ({l0:.3f} m) n'est jamais "
                            "rattrapé par GZ dans le domaine calculé.")


BRIQUES = {
    "aire": _b_aire,
    "gz_au_dela": _b_gz_au_dela,
    "angle_gz_max": _b_angle_gz_max,
    "gm": _b_gm,
    "ligne_de_charge": _b_ligne_de_charge,
    "meteo": _b_meteo,
    "nr500_voilier": _b_nr500,
    "bras_gite": _b_bras_gite,
}
BRIQUES_COURBE = {"aire", "gz_au_dela", "angle_gz_max", "bras_gite"}


def evaluer(retenue, ctx, groupe=None):
    """Le rapport de critères d'UNE réglementation retenue, sur UN point."""
    from .criteria import CriteriaReport
    r = retenue.reglement
    rep = CriteriaReport()
    groupe = r.titre_court() if groupe is None else groupe
    sans_equilibre = ctx.gz.origine_deg is None or not ctx.gz.heel_residuel_deg
    x_f = _x_f(ctx)
    for c in r.criteres:
        if c.brique in BRIQUES_COURBE:
            if sans_equilibre:
                continue                 # la ligne EQUILIBRE le dit, une fois
            if x_f is not None and x_f <= 0:
                continue                 # θf déjà atteint : dit par le préambule
        BRIQUES[c.brique](ctx, c, retenue, rep, groupe)
    if r.a_relire and rep.checks:
        rep.messages.append(
            f"« {r.titre} » : réglementation dont les seuils sont À RELIRE sur le "
            f"texte officiel ({r.texte}) — ses lignes ne sont pas vérifiées.")
    elif not r.rejouee and rep.checks:
        rep.messages.append(
            f"« {r.titre} » : relue sur le texte officiel ({r.texte}), mais pas "
            "encore rejouée sur un dossier de stabilité approuvé.")
    return rep


def preambule(ctx):
    """Ce qui vaut pour toutes les réglementations d'un point : pas
    d'équilibre stable, θf déjà atteint, θf approché, pantocarènes hors
    domaine. Dit une fois, pas une par réglementation."""
    from .criteria import CriteriaReport
    from .stability import source_tirants_eau
    rep = CriteriaReport()
    gz = ctx.gz
    if gz.origine_deg is None or not gz.heel_residuel_deg:
        rep.add("EQUILIBRE", "Équilibre stable (le navire se redresse)", 0.0, 1.0, ">=", "")
        rep.messages.append(
            "Aucune gîte d'équilibre stable dans le domaine des pantocarènes : le "
            "navire ne se redresse pas. Les aires et le GZ ne se mesurent pas — le "
            "point est NON CONFORME.")
        return rep
    if ctx.theta_f_deg is not None:
        if source_tirants_eau(ctx.navire) != "perpendiculaires":
            rep.messages.append("Angle d'envahissement calculé sur les repères peints, "
                                "pas sur les perpendiculaires : approché.")
        rep.messages.append(
            f"Angle d'envahissement θf = {float(ctx.theta_f_deg):.1f}° approché "
            "géométriquement (franc-bord local / demi-largeur, muraille verticale) : "
            "il plafonne les aires qui le demandent.")
        x_f = _x_f(ctx)
        if x_f is not None and x_f <= 0:
            rep.add("IS2008_THETAF", "Gîte permanente en deçà de l'angle d'envahissement",
                    float(ctx.theta_f_deg), abs(gz.origine_deg), ">=", "deg")
    else:
        rep.messages.append("Angle d'envahissement non fourni : les aires sont "
                            "plafonnées à leur borne nominale. Si θf est plus petit, "
                            "elles sont surestimées.")
    if not gz.dans_domaine_kn:
        rep.messages.append(
            "Assiette ou déplacement hors du domaine de la table des pantocarènes : "
            "les KN sont lus en bord de table, la courbe GZ et tout ce qui en découle "
            "sont sans valeur réglementaire.")
    return rep


def evaluer_navire(retenues, ctx, situation="toujours"):
    """Le rapport de toutes les réglementations retenues pour une SITUATION :
    « toujours » pour le tableau général ; « sans_voile » ou « sous_voile »
    pour le critère de vent de la voilure portée."""
    from .criteria import CriteriaReport
    rep = CriteriaReport()
    if situation == "toujours":
        rep.fusionner(preambule(ctx))
        # le préambule a dit l'essentiel quand il n'y a pas d'équilibre : on
        # garde les critères qui ne demandent pas la courbe (GM, ligne de charge)
    for x in retenues:
        if x.reglement.situation != situation:
            continue
        # les réglementations VÉRIFIÉES qui valent toujours forment le tableau
        # général, comme avant la 3.0 (la ligne de charge a son propre titre) ;
        # une réglementation À RELIRE porte le sien, qui le dit
        if situation == "toujours":
            groupe = "" if x.reglement.rejouee else x.reglement.titre_court()
        else:
            groupe = ctx.groupe or x.reglement.titre_court()
        rep.fusionner(evaluer(x, ctx, groupe=groupe))
    return rep
