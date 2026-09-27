# -*- coding: utf-8 -*-
"""Démonstration en ligne de commande du moteur de calcul, sans dépendance
graphique. Calcule l'équilibre, la courbe GZ et les critères réglementaires
pour un poids total / centre de gravité donnés, à partir d'un navire virtuel.

Usage :
    python3 -m carene.core.cli navires/<NOM> --poids 2616.33 --lcg 33.0827 \
        --tcg 0.0002 --vcg 4.8447 --fsm 36.5447
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from carene.core.navire import Navire
from carene.core import hydrostatics, stability, criteria


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("navire", help="Dossier du navire virtuel (ex: navires/<NOM>)")
    p.add_argument("--poids", type=float, required=True, help="Poids total (t)")
    p.add_argument("--lcg", type=float, required=True, help="LCG (m, repère navire)")
    p.add_argument("--tcg", type=float, default=0.0, help="TCG (m, + = bâbord)")
    p.add_argument("--vcg", type=float, required=True,
                    help="VCG solide, non corrigé de carène liquide (m)")
    p.add_argument("--fsm", type=float, default=0.0, help="Moment de carène liquide total (t.m)")
    args = p.parse_args()

    nav = Navire.load(args.navire)
    # les réserves du chargement du dossier (colonne facultative incomplète,
    # convention de carène liquide non déclarée…) valent d'être lues : elles
    # disent sur quoi le calcul qui suit repose vraiment
    for m in nav.messages:
        print(f"  ! {m}")

    eq = hydrostatics.solve_equilibrium(nav, args.poids, args.lcg)
    print(f"Équilibre : assiette {eq.trim_m:+.3f} m, tirant d'eau moyen {eq.draft_m:.3f} m "
          f"({eq.iterations} itérations, {'convergé' if eq.converged else 'NON convergé'}"
          f", {'dans le domaine' if eq.dans_domaine else 'HORS du domaine des tables'})")

    gz = stability.gz_curve(nav, eq, args.vcg, args.tcg, args.fsm)
    print(f"GM0 solide {gz.gm_solide_m:.3f} m, GM0 corrigé (carène liquide) {gz.gm_corrige_m:.3f} m")
    print(f"GZmax {gz.gz_max_m:.3f} m à {gz.angle_gz_max_deg:.1f}°"
          + (f", annulation à {gz.angle_annulation_deg:.1f}°" if gz.angle_annulation_deg else ""))
    if not gz.dans_domaine_kn:
        print("  ! Assiette ou déplacement hors du domaine des pantocarènes : "
              "les KN sont lus en bord de table.")

    rep = criteria.evaluate_general(nav, gz)
    print("\nCritères :")
    for chk in rep.checks:
        print(f"  [{'OK' if chk.ok else 'NON CONFORME'}] {chk.libelle} : "
              f"{chk.valeur:.4f} {chk.comparaison} {chk.seuil} {chk.unite}")
    for m in rep.messages:
        print(f"  ! {m}")

    # Un verdict ne vaut que dans le domaine des tables : hors domaine, les
    # critères portent sur des valeurs extrapolées, et imprimer « CONFORME »
    # y donnait une caution que le dossier ne couvre pas (D-23).
    if not (eq.dans_domaine and gz.dans_domaine_kn):
        print("\nRésultat global : HORS DOMAINE — sans valeur")
    else:
        print("\nRésultat global :", "CONFORME" if rep.ok else "NON CONFORME")


if __name__ == "__main__":
    main()
