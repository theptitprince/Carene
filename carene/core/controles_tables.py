# -*- coding: utf-8 -*-
"""Les contrôles de cohérence des tables d'un navire (3.2.0, D-82) — sans Qt.

Le bord (24/09/2026), sur la revue : « pour le contrôle de cohérence des
tables à l'import d'un navire, je te laisse gérer ».

Une table hydrostatique mal importée ne lève pas d'erreur : elle donne un
navire faux qui calcule. La revue l'a montré — une colonne « Volume » prise
pour le déplacement, une assiette recopiée sous une autre étiquette, une
jauge donnée en fraction 0–1 : chaque fois, le calcul « converge », reste
« dans le domaine », et rien ne le dit. Ce module relit les tables avec ce que
la physique impose, et dit ce qui ne tient pas :

- **hydrostatiques** : déplacement strictement croissant avec le tirant
  d'eau ; Δ/V constant (c'est la densité des tables) ; TPC ≈ dΔ/dT ;
  KB + BM = KM ; TE AR − TE AV = assiette ; pas de doublon ; LCB entre les
  perpendiculaires ;
- **pantocarènes** : mêmes angles à toutes les assiettes ; pas de doublon ;
  KN aux petits angles ≈ KM · sin φ (sinon, des KN donnés pour un KG supposé,
  ou des GZ) ;
- **jaugeages** : remplissage de 0 à 100 % (et pas en fraction 0–1) ;
  volume, poids et sonde croissants ; poids/volume ≈ densité ; volume à
  100 % ≈ volume net ; FSM maximal ≥ plus grand FSM de la table.

Chaque constat a un niveau : « erreur » (le navire calculerait faux),
« avertissement » (à vérifier contre le dossier), « info » (écart de données
sans conséquence sur le calcul). Les seuils sont des tolérances de lecture,
pas des règlements : le navire de référence, dont les tables sont celles
du dossier approuvé, les passe toutes — les deux seuls constats qu'il produit sont deux
écarts d'une fraction de t·m sur un FSM maximal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

ERREUR, AVERTISSEMENT, INFO = "erreur", "avertissement", "info"

# tolérances de lecture (tables imprimées au millième, arrondies)
TOL_DENSITE_REL = 0.003       # Δ/V : 0,3 % d'une ligne à l'autre
TOL_TPC_T_CM = 0.10           # TPC contre dΔ/dT
TOL_KM_M = 0.02               # KB + BM contre KM
TOL_ASSIETTE_M = 0.01         # TE AR − TE AV contre l'assiette
TOL_KN_KM_M = 0.10            # KN(φ)/sin φ contre KM, aux petits angles
TOL_JAUGE_DENSITE_REL = 0.02  # poids/volume contre la densité déclarée
TOL_VOLUME_NET_REL = 0.03     # V(100 %) contre Volume_net_m3


@dataclass
class Constat:
    niveau: str
    table: str
    message: str

    def ligne(self):
        return f"[{self.table}] {self.message}"


def _f(v):
    try:
        x = float(str(v).replace(",", ".")) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if x is None or x != x or math.isinf(x):
        return None
    return x


def _par_assiette(rows, cle_axe):
    groupes = {}
    for r in rows:
        t, x = _f(r.get("Assiette_m")), _f(r.get(cle_axe))
        if t is None or x is None:
            continue
        groupes.setdefault(round(t, 4), []).append((x, r))
    for t in groupes:
        groupes[t].sort(key=lambda p: p[0])
    return groupes


# ------------------------------------------------------------ hydrostatiques
def controler_hydro(rows, perpendiculaires=None, densite_declaree=None):
    out = []
    if not rows:
        return out
    groupes = _par_assiette(rows, "TE_milieu_m")
    densites = []
    for t, lignes in sorted(groupes.items()):
        etiquette = f"assiette {t:+.3f} m"
        tirants = [x for x, _r in lignes]
        doublons = sorted({x for x in tirants if tirants.count(x) > 1})
        if doublons:
            out.append(Constat(ERREUR, "Hydrostatiques",
                               f"{etiquette} : tirant(s) d'eau en double "
                               f"({', '.join(f'{d:.3f}' for d in doublons[:4])}) — "
                               "une table recopiée deux fois ?"))
        prec = None
        for x, r in lignes:
            d = _f(r.get("Deplacement_t"))
            if d is None:
                continue
            if prec is not None and d <= prec[1] and x > prec[0]:
                out.append(Constat(ERREUR, "Hydrostatiques",
                                   f"{etiquette} : le déplacement ne croît pas avec le "
                                   f"tirant d'eau ({prec[0]:.3f} m → {prec[1]:.1f} t, "
                                   f"{x:.3f} m → {d:.1f} t)."))
                break
            prec = (x, d)
        for x, r in lignes:
            d, v = _f(r.get("Deplacement_t")), _f(r.get("Volume_m3"))
            if d and v:
                densites.append(d / v)
            ar, av = _f(r.get("TE_AR_m")), _f(r.get("TE_AV_m"))
            if ar is not None and av is not None and abs((ar - av) - t) > TOL_ASSIETTE_M:
                out.append(Constat(ERREUR, "Hydrostatiques",
                                   f"{etiquette}, T = {x:.3f} m : TE AR − TE AV = "
                                   f"{ar - av:+.3f} m au lieu de {t:+.3f} m — colonnes AR "
                                   "et AV inversées, ou assiette de signe contraire ?"))
                break
            kb, bm, km = _f(r.get("VCB_m")), _f(r.get("BMT_m")), _f(r.get("KMt_m"))
            if kb is not None and bm is not None and km is not None \
                    and abs(kb + bm - km) > TOL_KM_M:
                out.append(Constat(AVERTISSEMENT, "Hydrostatiques",
                                   f"{etiquette}, T = {x:.3f} m : KB + BM = {kb + bm:.3f} m "
                                   f"≠ KM = {km:.3f} m."))
                break
            lcb = _f(r.get("LCB_m"))
            if perpendiculaires and lcb is not None:
                x_ar, x_av = perpendiculaires
                if not (x_ar - 1.0 <= lcb <= x_av + 1.0):
                    out.append(Constat(ERREUR, "Hydrostatiques",
                                       f"{etiquette}, T = {x:.3f} m : LCB = {lcb:.2f} m, hors "
                                       f"des perpendiculaires ({x_ar:.2f} à {x_av:.2f} m) — "
                                       "origine longitudinale différente ?"))
                    break
        # TPC ≈ dΔ/dT / 100
        for (x0, r0), (x1, r1) in zip(lignes, lignes[1:]):
            d0, d1 = _f(r0.get("Deplacement_t")), _f(r1.get("Deplacement_t"))
            p0, p1 = _f(r0.get("TPC_t_cm")), _f(r1.get("TPC_t_cm"))
            if None in (d0, d1, p0, p1) or x1 - x0 <= 0:
                continue
            pente = (d1 - d0) / (x1 - x0) / 100.0
            if abs(pente - (p0 + p1) / 2.0) > max(TOL_TPC_T_CM, 0.02 * pente):
                out.append(Constat(AVERTISSEMENT, "Hydrostatiques",
                                   f"{etiquette}, entre {x0:.3f} et {x1:.3f} m : dΔ/dT = "
                                   f"{pente:.2f} t/cm, TPC tabulé {(p0 + p1) / 2:.2f} t/cm — "
                                   "déplacement et TPC ne se suivent pas (colonne volume "
                                   "prise pour le déplacement ?)."))
                break
    if densites:
        moy = sum(densites) / len(densites)
        ecart = max(abs(d - moy) for d in densites) / moy
        if ecart > TOL_DENSITE_REL:
            out.append(Constat(ERREUR, "Hydrostatiques",
                               f"Δ/V n'est pas constant (de {min(densites):.4f} à "
                               f"{max(densites):.4f}) : déplacement et volume ne sont pas "
                               "de la même table, ou une colonne est mal reconnue."))
        elif densite_declaree and abs(moy - float(densite_declaree)) > 0.002:
            out.append(Constat(AVERTISSEMENT, "Hydrostatiques",
                               f"Les tables sont à la densité {moy:.4f} (Δ/V), le dossier "
                               f"déclare {float(densite_declaree):.4f}."))
        else:
            out.append(Constat(INFO, "Hydrostatiques",
                               f"Densité des tables (Δ/V) : {moy:.4f} t/m³."))
    return out


# ------------------------------------------------------------ pantocarènes
def controler_kn(rows, angles, hydro_rows=None):
    out = []
    if not rows:
        return out
    groupes = _par_assiette(rows, "Deplacement_t")
    colonnes = [f"KN_{a:g}" for a in angles]
    for t, lignes in sorted(groupes.items()):
        etiquette = f"assiette {t:+.3f} m"
        depl = [x for x, _r in lignes]
        doublons = sorted({x for x in depl if depl.count(x) > 1})
        if doublons:
            out.append(Constat(ERREUR, "Pantocarènes",
                               f"{etiquette} : déplacement(s) en double "
                               f"({', '.join(f'{d:.1f}' for d in doublons[:4])})."))
        manquants = sorted({c for _x, r in lignes for c in colonnes if _f(r.get(c)) is None})
        if manquants:
            out.append(Constat(ERREUR, "Pantocarènes",
                               f"{etiquette} : angle(s) sans valeur "
                               f"({', '.join(m.replace('KN_', '') + '°' for m in manquants[:6])}) — "
                               "toutes les assiettes doivent porter les mêmes angles, sinon "
                               "la courbe GZ ne peut pas être tracée."))
    # KN aux petits angles contre KM : un KN donné pour un KG supposé (ou un GZ)
    # s'écarte de KM · sin φ d'autant
    petits = [a for a in angles if 0 < a <= 10]
    if petits and hydro_rows:
        a = min(petits)
        hyd = _par_assiette(hydro_rows, "Deplacement_t")
        for t, lignes in sorted(groupes.items()):
            if t not in hyd:
                continue
            xs = [x for x, _r in hyd[t]]
            kms = [_f(r.get("KMt_m")) for _x, r in hyd[t]]
            if len(xs) < 2 or None in kms:
                continue
            ecarts = []
            for x, r in lignes:
                kn = _f(r.get(f"KN_{a:g}"))
                if kn is None or not (xs[0] <= x <= xs[-1]):
                    continue
                import bisect
                i = min(max(bisect.bisect_right(xs, x) - 1, 0), len(xs) - 2)
                u = (x - xs[i]) / (xs[i + 1] - xs[i]) if xs[i + 1] > xs[i] else 0.0
                km = kms[i] + u * (kms[i + 1] - kms[i])
                ecarts.append(kn / math.sin(math.radians(a)) - km)
            if ecarts and max(abs(e) for e in ecarts) > TOL_KN_KM_M:
                pire = max(ecarts, key=abs)
                out.append(Constat(AVERTISSEMENT, "Pantocarènes",
                                   f"assiette {t:+.3f} m : KN({a:g}°)/sin {a:g}° s'écarte "
                                   f"de KM de {pire:+.2f} m — KN donnés pour un KG supposé, "
                                   "ou colonne de GZ importée comme KN ?"))
                break
    return out


# ------------------------------------------------------------ jaugeages
def controler_jauge(nom, rows, meta=None):
    out = []
    meta = meta or {}
    if not rows:
        return out
    lignes = sorted(((_f(r.get("Remplissage_pc")), r) for r in rows
                     if _f(r.get("Remplissage_pc")) is not None), key=lambda p: p[0])
    if not lignes:
        return [Constat(ERREUR, "Jaugeages", f"{nom} : aucune colonne de remplissage lisible.")]
    rmin, rmax = lignes[0][0], lignes[-1][0]
    if rmax <= 1.0 + 1e-9:
        out.append(Constat(ERREUR, "Jaugeages",
                           f"{nom} : remplissage de {rmin:g} à {rmax:g} — table donnée en "
                           "FRACTION 0–1 au lieu de pourcentage : toute saisie en % la "
                           "donnerait pleine."))
    else:
        if rmin > 1.0:
            out.append(Constat(AVERTISSEMENT, "Jaugeages",
                               f"{nom} : la table commence à {rmin:g} % — une caisse vide "
                               "serait pesée à la première ligne."))
        if rmax < 99.0:
            out.append(Constat(AVERTISSEMENT, "Jaugeages",
                               f"{nom} : la table s'arrête à {rmax:g} % — au-delà, le "
                               "remplissage est ramené à la dernière ligne."))
    for col in ("Volume_m3", "Poids_t", "Sondage_m"):
        vals = [_f(r.get(col)) for _p, r in lignes]
        vals = [v for v in vals if v is not None]
        # tolérance d'arrondi : une ligne à 100 % répétée au dix-millième près
        # n'est pas une table qui décroît
        if len(vals) >= 2 and any(b < a - max(1e-3, 1e-4 * abs(a))
                                  for a, b in zip(vals, vals[1:])):
            out.append(Constat(ERREUR, "Jaugeages",
                               f"{nom} : la colonne {col} décroît quand le remplissage "
                               "croît."))
    dens = _f(meta.get("Densite"))
    ratios = [(_f(r.get("Poids_t")) / _f(r.get("Volume_m3")))
              for _p, r in lignes if (_f(r.get("Volume_m3")) or 0) > 1e-6
              and _f(r.get("Poids_t")) is not None]
    if dens and ratios:
        moy = sum(ratios) / len(ratios)
        if abs(moy - dens) / dens > TOL_JAUGE_DENSITE_REL:
            out.append(Constat(AVERTISSEMENT, "Jaugeages",
                               f"{nom} : poids/volume = {moy:.3f} dans la table, densité "
                               f"déclarée {dens:.3f} — un relevé de densité remettrait le "
                               "poids à l'échelle d'une base fausse."))
    vnet = _f(meta.get("Volume_net_m3"))
    v100 = _f(lignes[-1][1].get("Volume_m3")) if rmax >= 99.0 else None
    if vnet and v100 and abs(v100 - vnet) / vnet > TOL_VOLUME_NET_REL:
        out.append(Constat(AVERTISSEMENT, "Jaugeages",
                           f"{nom} : volume à {rmax:g} % = {v100:.2f} m³, volume net "
                           f"déclaré {vnet:.2f} m³."))
    fsm_max = _f(meta.get("FSM_max_tm"))
    fsms = [_f(r.get("FSM_tm")) for _p, r in lignes]
    fsms = [v for v in fsms if v is not None]
    if fsm_max is not None and fsms and max(fsms) > fsm_max + 0.01:
        out.append(Constat(INFO, "Jaugeages",
                           f"{nom} : FSM maximal déclaré {fsm_max:.2f} t·m, la table va "
                           f"jusqu'à {max(fsms):.2f} t·m (écart de données, sans effet en "
                           "convention « réel »)."))
    return out


# ------------------------------------------------------------ tout le navire
def controler_brouillon(draft):
    """Tous les contrôles, sur le brouillon de la fenêtre « Création du
    navire » (`NavireDraft`) : [Constat], les erreurs d'abord."""
    dims = getattr(draft, "dimensions", {}) or {}
    pp = None
    if dims.get("x_perpendiculaire_ar_m") is not None and dims.get("x_perpendiculaire_av_m") is not None:
        pp = (float(dims["x_perpendiculaire_ar_m"]), float(dims["x_perpendiculaire_av_m"]))
    elif isinstance(dims.get("perpendiculaires"), dict):
        p = dims["perpendiculaires"]
        if p.get("arriere_m") is not None and p.get("avant_m") is not None:
            pp = (float(p["arriere_m"]), float(p["avant_m"]))
    out = controler_hydro(draft.hydro_rows, pp, dims.get("densite_eau_tables"))
    out += controler_kn(draft.kn_rows, draft.kn_angles, draft.hydro_rows)
    metas = {c.get("Nom"): c for c in draft.capacites}
    for nom, rows in sorted(draft.jauges.items()):
        out += controler_jauge(nom, rows, metas.get(nom))
    rang = {ERREUR: 0, AVERTISSEMENT: 1, INFO: 2}
    out.sort(key=lambda c: rang.get(c.niveau, 3))
    return out
