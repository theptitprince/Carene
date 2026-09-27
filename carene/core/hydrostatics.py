# -*- coding: utf-8 -*-
"""Équilibre longitudinal (assiette + tirant d'eau moyen) par résolution sur la
table hydrostatique du navire virtuel. Aucune donnée navire codée en dur : tout
vient de l'objet Navire (carene.core.navire) passé en paramètre.
"""
from dataclasses import dataclass, field


@dataclass
class Equilibre:
    trim_m: float          # assiette (>0 = enfoncement arrière, convention du dossier de référence)
    draft_m: float          # tirant d'eau moyen /OH
    displacement_t: float
    lcb_m: float
    hydro: dict = field(default_factory=dict)   # toutes les colonnes hydro interpolées
    iterations: int = 0
    converged: bool = True
    # La solution tombe-t-elle DANS le domaine tabulé ? Une solution
    # extrapolée peut parfaitement « converger » tout en n'ayant aucune
    # valeur : le résultat doit alors être présenté comme non exploitable.
    dans_domaine: bool = True


def solve_equilibrium(navire, weight_t, lcg_m, trim_guess=0.0, draft_guess=None,
                       tol_weight=1e-3, tol_lcg=1e-4, max_iter=40, method="linear"):
    """Résout (assiette, tirant d'eau moyen) tels que :
        Déplacement(assiette, tirant) = weight_t
        LCB(assiette, tirant)         = lcg_m
    par Newton-Raphson 2D avec jacobien aux différences finies sur la table
    hydrostatique. C'est l'équilibre "droit" (sans gîte) ; la gîte éventuelle
    (due à un TCG non nul) se calcule ensuite via la courbe de GZ (voir
    carene.core.stability), la table hydrostatique du dossier de référence n'étant
    fournie qu'à droite.
    """
    hydro = navire.hydro
    if draft_guess is None:
        # estimation grossière : moyenne du domaine de tirant d'eau de la table
        all_d = [d for row in hydro.rows_axis2 for d in row]
        draft_guess = sum(all_d) / len(all_d)

    # table à une seule assiette : le problème dégénère en 1D — on résout le
    # tirant d'eau sur le déplacement, l'assiette est celle de la table (elle
    # n'est pas interpolable, et le dire vaut mieux que de ne pas converger)
    if len(set(float(a) for a in hydro.axis1)) == 1:
        return _solve_1d(navire, weight_t, float(hydro.axis1[0]), draft_guess,
                         tol_weight, max_iter, method)

    t, d = trim_guess, draft_guess
    h_t = 1e-3   # pas de différences finies (m d'assiette)
    h_d = 1e-3   # pas de différences finies (m de tirant d'eau)
    converged = False
    it = 0
    for it in range(1, max_iter + 1):
        disp = hydro.value(t, d, "Deplacement_t", method)
        lcb = hydro.value(t, d, "LCB_m", method)
        f1 = disp - weight_t
        f2 = lcb - lcg_m
        if abs(f1) < tol_weight and abs(f2) < tol_lcg:
            converged = True
            break
        disp_t2 = hydro.value(t + h_t, d, "Deplacement_t", method)
        lcb_t2 = hydro.value(t + h_t, d, "LCB_m", method)
        disp_d2 = hydro.value(t, d + h_d, "Deplacement_t", method)
        lcb_d2 = hydro.value(t, d + h_d, "LCB_m", method)
        j11 = (disp_t2 - disp) / h_t
        j21 = (lcb_t2 - lcb) / h_t
        j12 = (disp_d2 - disp) / h_d
        j22 = (lcb_d2 - lcb) / h_d
        det = j11 * j22 - j12 * j21
        if abs(det) < 1e-9:
            break
        dt = (f1 * j22 - f2 * j12) / det * -1
        dd = (j11 * f2 - j21 * f1) / det * -1
        # bornage du pas pour éviter les divergences loin de la solution
        dt = max(-0.5, min(0.5, dt))
        dd = max(-0.5, min(0.5, dd))
        t += dt
        d += dd

    # `row_at` a déjà interpolé TOUTES les colonnes de la table, déplacement
    # compris et par le même chemin : le recalculer n'y changeait rien.
    row = hydro.row_at(t, d, method)
    return Equilibre(trim_m=t, draft_m=d, displacement_t=row["Deplacement_t"],
                      lcb_m=row["LCB_m"], hydro=row, iterations=it,
                      converged=converged, dans_domaine=hydro.contains(t, d))


def _solve_1d(navire, weight_t, trim_fixe, draft_guess, tol_weight, max_iter,
              method):
    """Équilibre sur une table mono-assiette : Newton 1D sur le tirant d'eau.

    L'assiette rendue est celle de la table ; l'écart LCG-LCB n'est pas
    résorbable (aucune autre assiette pour interpoler) et reste visible dans
    le résultat — l'appelant sait qu'il travaille en assiette figée."""
    hydro = navire.hydro
    d = draft_guess
    h_d = 1e-3
    converged = False
    it = 0
    for it in range(1, max_iter + 1):
        f = hydro.value(trim_fixe, d, "Deplacement_t", method) - weight_t
        if abs(f) < tol_weight:
            converged = True
            break
        deriv = (hydro.value(trim_fixe, d + h_d, "Deplacement_t", method)
                 - (f + weight_t)) / h_d
        if abs(deriv) < 1e-9:
            break
        d -= max(-0.5, min(0.5, f / deriv))
    # même remarque qu'en 2D : `row_at` porte déjà le déplacement interpolé
    row = hydro.row_at(trim_fixe, d, method)
    return Equilibre(trim_m=trim_fixe, draft_m=d,
                      displacement_t=row["Deplacement_t"],
                      lcb_m=row["LCB_m"], hydro=row, iterations=it,
                      converged=converged,
                      dans_domaine=hydro.contains(trim_fixe, d))


def block_coefficient(volume_m3, lwl_m, beam_m, draft_m):
    """Cb = V / (Lwl . B . d) — dépend de l'assiette/tirant d'eau courants,
    donc calculé à la demande plutôt que stocké comme une constante navire."""
    denom = lwl_m * beam_m * draft_m
    return volume_m3 / denom if denom else 0.0
