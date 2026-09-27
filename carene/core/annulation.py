# -*- coding: utf-8 -*-
"""Annuler / refaire le chargement du point : une pile d'ÉTATS (D-61).

Le bord (22/09/2026) : « on devrait prévoir un Ctrl+Z… » L'éditeur de plans en
avait un depuis longtemps ; le poste de travail, là où l'on pose les colis, où
l'on relève les sondes et où l'on ajoute les poids, n'en avait pas.

**Une pile d'états, pas une pile de gestes.** Un « geste inverse » par action —
retirer ce qu'on vient de poser, remettre la sonde d'avant, redéplacer un
colis — c'est autant de code que l'action elle-même, et deux fois plus
d'occasions de se tromper : le jour où un geste oublie son inverse, Ctrl+Z
fabrique un chargement qui n'a jamais existé. On garde donc, avant chaque
changement, **l'état complet du chargement**, tel qu'il s'écrit sur le disque
(`LoadingCondition.to_dict()`). Annuler, c'est relire un état ; il ne peut
donc pas en sortir un chargement impossible. Sur un point lourd (90 lots,
600 colis posés), un état pèse 7 Ko compressé et se capture en 3 ms : le prix
est nul devant le calcul d'équilibre qui suit.

Ce module ne connaît ni Qt, ni la fenêtre : il prend des dicts et rend des
dicts. Il sait aussi **dire ce qu'il annule** (`decrire`) — « Annuler la pose
de 3 charges » vaut mieux qu'« Annuler ».
"""
from __future__ import annotations

import json
import zlib

# Profondeur de la pile. Quarante gestes couvrent largement une escale ; au-delà
# c'est le journal des points qui fait mémoire, pas Ctrl+Z.
PROFONDEUR = 40


def _gel(etat):
    """L'état, compressé : une pile de quarante chargements ne doit pas peser
    dans la mémoire d'un poste de passerelle."""
    return zlib.compress(json.dumps(etat, separators=(",", ":")).encode("utf-8"), 1)


def _degel(paquet):
    return json.loads(zlib.decompress(paquet).decode("utf-8"))


class PileAnnulation:
    """Les états d'avant (annuler) et ceux d'après (refaire).

    L'appelant garde l'état courant chez lui ; cette pile ne connaît que ce
    qui l'entoure. `pousser` enregistre l'état PRÉCÉDENT avec le libellé du
    changement qui vient d'avoir lieu.
    """

    def __init__(self, profondeur=PROFONDEUR):
        self.profondeur = int(profondeur)
        self._avant = []            # [(paquet, libellé)] — du plus ancien au plus récent
        self._apres = []            # idem, pour refaire

    def raz(self):
        """Table rase : on change de point, l'histoire d'avant n'est plus la
        sienne. Annuler d'un point à l'autre n'aurait aucun sens."""
        self._avant.clear()
        self._apres.clear()

    def pousser(self, etat_precedent, libelle=""):
        """Enregistre l'état d'AVANT le changement qui vient d'avoir lieu.

        Un nouveau changement rend le « refaire » caduc : la branche qu'on
        avait annulée n'existe plus."""
        self._avant.append((_gel(etat_precedent), str(libelle or "")))
        del self._avant[:-self.profondeur]
        self._apres.clear()

    # ------------------------------------------------------------- lecture
    @property
    def peut_annuler(self):
        return bool(self._avant)

    @property
    def peut_refaire(self):
        return bool(self._apres)

    @property
    def libelle_annuler(self):
        return self._avant[-1][1] if self._avant else ""

    @property
    def libelle_refaire(self):
        return self._apres[-1][1] if self._apres else ""

    def __len__(self):
        return len(self._avant)

    # -------------------------------------------------------------- gestes
    def annuler(self, etat_courant):
        """(état à restaurer, libellé) et l'état courant passe dans « refaire »."""
        if not self._avant:
            return None, ""
        paquet, libelle = self._avant.pop()
        self._apres.append((_gel(etat_courant), libelle))
        del self._apres[:-self.profondeur]
        return _degel(paquet), libelle

    def refaire(self, etat_courant):
        """L'inverse : (état à restaurer, libellé), le courant repart dans
        « annuler »."""
        if not self._apres:
            return None, ""
        paquet, libelle = self._apres.pop()
        self._avant.append((_gel(etat_courant), libelle))
        del self._avant[:-self.profondeur]
        return _degel(paquet), libelle


# ===================================================== dire ce qu'on annule
def _n_places(etat):
    return sum(len(v) for v in (etat.get("placements") or {}).values())


def _poses(etat):
    """Les colis posés, réduits à ce qui se voit : cale, lot, position, sens,
    niveaux. Deux états qui donnent la même liste montrent le même plan."""
    out = []
    for code, lst in sorted((etat.get("placements") or {}).items()):
        for p in lst:
            out.append((code, p.get("lot_id"), round(float(p.get("x", 0)), 3),
                        round(float(p.get("y", 0)), 3), p.get("rot"),
                        p.get("niveaux")))
    return out


def _compte(n, un, singulier, pluriel_=None):
    """« une charge » / « 3 charges » : au singulier on écrit l'article, pas
    le chiffre — « l'ajout de 1 lot » n'est pas du français."""
    if n <= 1:
        return f"{un} {singulier}"
    return f"de {n} {pluriel_ or singulier + 's'}"


def decrire(avant, apres):
    """Ce qui a changé entre deux états, en français et au singulier près.

    Sert au libellé du menu (« Annuler la pose de 3 charges ») : un Ctrl+Z qui
    dit ce qu'il va défaire se presse sans crainte. On regarde dans l'ordre où
    le bord travaille, et on s'arrête au premier changement trouvé — décrire
    tout ce qui a bougé ferait une phrase que personne ne lit.
    """
    avant = avant or {}
    apres = apres or {}

    # --- les colis : posés, retirés, déplacés
    na, nb = _n_places(avant), _n_places(apres)
    if nb > na:
        return "la pose " + _compte(nb - na, "d'une", "charge")
    if nb < na:
        return "le retrait " + _compte(na - nb, "d'une", "charge")
    if na and _poses(avant) != _poses(apres):
        return "le déplacement des charges"

    # --- le manifeste
    ma = avant.get("manifeste") or []
    mb = apres.get("manifeste") or []
    if len(mb) > len(ma):
        return "l'ajout " + _compte(len(mb) - len(ma), "d'un", "lot")
    if len(mb) < len(ma):
        return "le retrait " + _compte(len(ma) - len(mb), "d'un", "lot")
    if ma != mb:
        return "la modification du manifeste"

    # --- les capacités : c'est le relevé qui change, rarement la liste
    ta = {t.get("capacite"): (t.get("mesure"), t.get("valeur"), t.get("densite"))
          for t in (avant.get("tanks") or [])}
    tb = {t.get("capacite"): (t.get("mesure"), t.get("valeur"), t.get("densite"))
          for t in (apres.get("tanks") or [])}
    if ta != tb:
        changees = [c for c in set(ta) | set(tb) if ta.get(c) != tb.get(c)]
        if len(changees) == 1:
            return f"le relevé de « {changees[0]} »"
        return f"le relevé de {len(changees)} capacités"

    # --- les poids divers, dont le poids fictif des tirants d'eau
    ea = avant.get("extras") or []
    eb = apres.get("extras") or []
    if ea != eb:
        from .tirants_releves import NOM_POIDS
        noms_a = {str(e.get("nom", "")) for e in ea}
        noms_b = {str(e.get("nom", "")) for e in eb}
        nouveaux = noms_b - noms_a
        if any(n.startswith(NOM_POIDS) for n in nouveaux | (noms_a - noms_b)):
            return "la correction par les tirants d'eau"
        if len(eb) > len(ea):
            return "l'ajout " + _compte(len(eb) - len(ea), "d'un", "poids divers", "poids divers")
        if len(eb) < len(ea):
            return "le retrait " + _compte(len(ea) - len(eb), "d'un", "poids divers", "poids divers")
        return "la modification des poids divers"

    # --- le reste, du plus fréquent au plus rare
    if (avant.get("epontilles_en_place") or []) != (apres.get("epontilles_en_place") or []):
        return "les épontilles en place"
    if avant.get("voilure") != apres.get("voilure"):
        return "le changement de voilure"
    if bool(avant.get("inclure_lege", True)) != bool(apres.get("inclure_lege", True)):
        return "la prise en compte du navire lège"
    if (avant.get("tirants_releves") or None) != (apres.get("tirants_releves") or None):
        return "le relevé de tirants d'eau"
    if (avant.get("brouillons") or []) != (apres.get("brouillons") or []):
        return "les brouillons du plan de chargement"
    if avant.get("note") != apres.get("note") or avant.get("nom") != apres.get("nom"):
        return "la note du chargement"
    return "la dernière modification"
