# -*- coding: utf-8 -*-
"""Les configurations de voilure d'un navire, et la surface qu'elles exposent
au vent à un tirant d'eau donné.

POURQUOI ce module existe. La surface au vent n'est ni une constante du navire
ni une formule : elle dépend de ce qui est déployé — rien (voiles enroulées),
voilure complète, intermédiaire, réduite — ET du tirant d'eau, puisque chaque
centimètre de tirant d'eau en moins découvre L × 0,01 m² de coque. Jusqu'ici
`carene.core.condition` la recevait toute faite de l'appelant, avec une note
disant que le jour où le dossier la publierait, il faudrait la ranger quelque
part. C'est ce fichier-là.

Deux fichiers du dossier navire le nourrissent, et aucun n'est obligatoire :

- `navire.json` › `profils_vent` : la LISTE des configurations, avec pour
  chacune un identifiant, un nom affichable et une description. C'est elle qui
  donne les libellés du sélecteur à l'écran ;
- `profils_vent.csv` : la TABLE de mesures, une ligne par (configuration,
  tirant d'eau), avec les cinq grandeurs dont vivent les deux critères de vent.
  Ce sont des mesures du dossier de stabilité, jamais un calcul du logiciel.

Entre deux tirants d'eau mesurés d'une même configuration, on interpole
linéairement : c'est bien ainsi que varie l'aire découverte quand le navire
s'allège. **Hors de la plage mesurée**, on ne prolonge pas — on prend la borne
la plus proche ET on le dit : `surface_au_vent` rend alors une note en clair,
que l'appelant doit porter dans ses réserves. Un critère réglementaire nourri
d'une aire extrapolée en silence serait pire que pas de critère du tout.

Aucune valeur numérique propre à un navire n'est écrite ici, et aucun
identifiant de configuration non plus : « CARGO », « FS », « IS », « RS » sont
des identifiants du dossier de référence, lus dans son manifeste.
"""
import csv
import json
import os

# Les cinq grandeurs que lisent les critères de vent — ce sont les intitulés
# de colonne du fichier, et les clés du dict rendu par `surface_au_vent` :
#
# - Windage_area_m2 / Windage_V_m : aire de la surface exposée au vent et
#   hauteur de son centre au-dessus de la ligne de base ;
# - Lateral_plane_area_m2 / Lateral_plane_V_m : idem pour le plan de dérive
#   immergé (la partie sous l'eau, qui reçoit la réaction) ;
# - Z_windage_lateral_m : le bras entre les deux centres. Le dossier le publie
#   à part plutôt que de le faire déduire, et c'est lui qui sert au calcul :
#   sur un dossier où les deux hauteurs sont comptées depuis des références
#   différentes, la soustraction serait fausse sans qu'on le voie.
GRANDEURS = ("Windage_area_m2", "Windage_V_m", "Lateral_plane_area_m2",
             "Lateral_plane_V_m", "Z_windage_lateral_m")

# Les trois sans lesquelles aucun des deux critères ne tient debout : une ligne
# à qui il en manque une est écartée, en le disant, plutôt que complétée d'un
# zéro qui passerait pour une mesure.
GRANDEURS_OBLIGATOIRES = ("Windage_area_m2", "Windage_V_m",
                          "Lateral_plane_V_m")

FICHIER = "profils_vent.csv"

# Quel critère de vent s'applique dans une configuration donnée. Voiles
# enroulées, le navire est un cargo au vent de travers : c'est le critère
# météo IS2008 §2.3. Voiles déployées, c'est le critère NR500 « Sailing
# Yachts », que le dossier de référence applique à ses cas 01d-f / 02d-f.
CRITERE_METEO = "meteo"
CRITERE_NR500_VOILE = "nr500_voile"

# Un dossier peut le DIRE, en portant `"critere": "meteo"` sur la
# configuration concernée de navire.json › profils_vent. Faute de quoi on
# retombe sur la convention du dossier de référence, qui nomme « CARGO » sa
# configuration voiles enroulées — c'est un repli, pas une règle du logiciel.
ID_SANS_VOILE_PAR_DEFAUT = "CARGO"


def _f(v):
    """Lecture numérique tolérante d'une cellule (virgule décimale admise)."""
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


class ProfilsVent:
    """Les configurations de voilure d'un navire et leur table de surfaces.

    Se construit par `ProfilsVent.charger(dossier)`, qui rend **None** si le
    dossier ne porte pas `profils_vent.csv` : un navire sans cette table doit
    continuer de fonctionner exactement comme avant, sans une ligne de critère
    de plus ni un message de moins.
    """

    def __init__(self, profils, points, messages=None):
        # [{"id", "nom", "description"}] dans l'ordre du manifeste
        self.profils = list(profils)
        # id -> [{"TE_milieu_m", "Source", **GRANDEURS}] trié par tirant d'eau
        self.points = {k: sorted(v, key=lambda r: r["TE_milieu_m"])
                       for k, v in points.items()}
        # ce qu'il y a à dire de la lecture du fichier (lignes écartées…)
        self.messages = list(messages or [])

    # ------------------------------------------------------------ lecture
    @classmethod
    def charger(cls, dossier, manifest=None):
        """Lit `profils_vent.csv` et la liste des profils du manifeste.

        `manifest` : le contenu déjà lu de navire.json, si l'appelant l'a sous
        la main (c'est le cas de `Navire.__init__`) — sinon il est relu ici.
        Rend None quand ni le manifeste ni le dossier ne décrivent de
        configuration. Quand le manifeste en DÉCLARE mais que la table
        `profils_vent.csv` manque (le dossier du bord d'avant la v2.15.1 :
        navire.json nomme ses quatre voilures, la table n'existait pas
        encore), on rend les configurations SANS surface au vent : le
        sélecteur les montre, et le critère dit qu'il lui manque la table et
        où la prendre — plutôt qu'un « le dossier n'en décrit pas » qui
        serait faux."""
        chemin = os.path.join(dossier, FICHIER)
        if manifest is None:
            mp = os.path.join(dossier, "navire.json")
            if os.path.exists(mp):
                with open(mp, encoding="utf-8") as f:
                    manifest = json.load(f)
            else:
                manifest = {}
        declares = manifest.get("profils_vent") or []
        profils = [{"id": str(p.get("id") or "").strip(),
                    "nom": str(p.get("nom") or p.get("id") or "").strip(),
                    "description": str(p.get("description") or "").strip(),
                    "critere": str(p.get("critere") or "").strip(),
                    # les limites du gréement, telles quelles (D-58)
                    "plan_reduction_voilure": p.get("plan_reduction_voilure")}
                   for p in declares if p.get("id")]
        connus = {p["id"] for p in profils}
        if not os.path.exists(chemin):
            if not profils:
                return None
            return cls(profils, {}, [
                f"{FICHIER} absent du dossier du navire : les voilures sont "
                "déclarées dans navire.json mais sans surface au vent. "
                "Copiez le fichier depuis navires/<NOM>.exemple/ (ou "
                "importez la table dans « Créer ou modifier le navire… », "
                "étape Surface exposée au vent)."])

        points, messages = {}, []
        with open(chemin, newline="", encoding="utf-8") as f:
            for num, r in enumerate(csv.DictReader(f), start=1):
                pid = str(r.get("Profil") or "").strip()
                te = _f(r.get("TE_milieu_m"))
                if not pid or te is None:
                    messages.append(
                        f"{FICHIER} ligne {num} : configuration ou tirant "
                        "d'eau absent — ligne ignorée.")
                    continue
                ligne = {"TE_milieu_m": te,
                         "Source": str(r.get("Source") or "").strip()}
                manquantes = [g for g in GRANDEURS_OBLIGATOIRES
                              if _f(r.get(g)) is None]
                if manquantes:
                    messages.append(
                        f"{FICHIER} ligne {num} ({pid}, {te:.3f} m) : "
                        + ", ".join(manquantes) + " absente(s) — ligne "
                        "ignorée, une surface au vent incomplète ne se "
                        "complète pas toute seule.")
                    continue
                for g in GRANDEURS:
                    v = _f(r.get(g))
                    if v is not None:
                        ligne[g] = v
                if "Z_windage_lateral_m" not in ligne:
                    # le bras entre les deux centres, quand le dossier ne le
                    # publie pas à part : c'est sa définition même, pas une
                    # estimation. (Le navire de référence le publie, et les deux concordent au
                    # dixième de millimètre.)
                    ligne["Z_windage_lateral_m"] = (ligne["Windage_V_m"]
                                                    - ligne["Lateral_plane_V_m"])
                points.setdefault(pid, []).append(ligne)

        # Une configuration mesurée mais non déclarée n'aurait aucun libellé à
        # l'écran : on l'ajoute à la liste sous son identifiant, plutôt que de
        # laisser une table utilisable invisible.
        for pid in points:
            if pid not in connus:
                profils.append({"id": pid, "nom": pid, "description": "",
                                "critere": ""})
                messages.append(
                    f"{FICHIER} : la configuration « {pid} » n'est pas "
                    "décrite dans navire.json › profils_vent ; elle est "
                    "proposée sous son identifiant.")
        return cls(profils, points, messages)

    # ------------------------------------------------------------ lecture
    def __bool__(self):
        # vrai dès qu'il y a quelque chose à MONTRER : des configurations
        # déclarées suffisent, même sans table — le critère dira alors qu'il
        # n'est pas évaluable, et pourquoi
        return bool(self.points or self.profils)

    @property
    def ids(self):
        return [p["id"] for p in self.profils]

    def profil(self, profil_id):
        """La fiche d'une configuration (id/nom/description), ou None."""
        for p in self.profils:
            if p["id"] == profil_id:
                return p
        return None

    def nom(self, profil_id):
        """Le libellé d'une configuration, son identifiant à défaut."""
        p = self.profil(profil_id)
        return p["nom"] if p else str(profil_id or "")

    def description(self, profil_id):
        p = self.profil(profil_id)
        return p["description"] if p else ""

    def limites_du_plan(self, profil_id):
        """Le plan de réduction de voilure du chantier pour cette configuration
        (`plan_reduction_voilure` sur le profil, dans navire.json) : ce sont
        les limites du GRÉEMENT — vent réel et apparent à ne pas dépasser
        selon l'angle de vent apparent —, pas celles de la stabilité. Les deux
        se lisent côte à côte : la plus basse commande. Rend le dict tel quel,
        ou None si le dossier ne le porte pas."""
        p = self.profil(profil_id) or {}
        plan = p.get("plan_reduction_voilure")
        return plan if isinstance(plan, dict) and plan.get("limites") else None

    def phrase_du_plan(self, profil_id):
        """Une phrase pour le bandeau et le rapport : « Plan de réduction de
        voilure C900-6500-03 rév. B, configuration A : vent réel < 20 nd (AWA
        25–90°), < 25 nd (90–170°) ; vent apparent < 23,5 à 25 nd. » — ou ""."""
        plan = self.limites_du_plan(profil_id)
        if not plan:
            return ""
        morceaux = []
        for lim in plan["limites"]:
            try:
                morceaux.append(f"< {_f(lim['tws_max_kn']):g} nd (AWA "
                                f"{_f(lim['awa_min_deg']):g}–{_f(lim['awa_max_deg']):g}°)")
            except (KeyError, TypeError, ValueError):
                continue
        aws = [_f(lim.get("aws_max_kn")) for lim in plan["limites"] if lim.get("aws_max_kn") is not None]
        source = str(plan.get("source") or "").split("«")[0].strip() or "plan de réduction de voilure"
        cfg = plan.get("configuration")
        txt = (f"Plan de réduction de voilure {source}"
               + (f", configuration {cfg}" if cfg else "")
               + " : vent réel " + ", ".join(morceaux))
        if aws:
            lo, hi = min(aws), max(aws)
            txt += f" ; vent apparent < {lo:g}" + (f" à {hi:g}" if hi != lo else "") + " nd"
        return txt + ". C'est la limite du gréement ; la force admissible ci-dessus est celle de la stabilité — la plus basse commande."

    def critere(self, profil_id):
        """Le critère de vent qui s'applique dans cette configuration :
        CRITERE_METEO (voiles enroulées, navire au vent de travers) ou
        CRITERE_NR500_VOILE (voilure déployée).

        Le dossier peut le déclarer (`"critere"` sur le profil) ; sinon on
        applique la convention du dossier de référence, dont la configuration sans voile
        porte l'identifiant « CARGO »."""
        p = self.profil(profil_id) or {}
        declare = (p.get("critere") or "").strip().lower()
        if declare in (CRITERE_METEO, CRITERE_NR500_VOILE):
            return declare
        return (CRITERE_METEO if str(profil_id).strip().upper()
                == ID_SANS_VOILE_PAR_DEFAUT else CRITERE_NR500_VOILE)

    def resoudre(self, profil_id):
        """L'identifiant à employer réellement pour ce point de chargement.

        Un point enregistré sous une configuration que ce navire ne connaît
        pas (dossier changé, point venu d'un autre bord) ne doit pas faire
        échouer le calcul : on retombe sur la première configuration déclarée.
        Rend None si le navire n'en déclare aucune."""
        if profil_id and self.profil(profil_id) is not None:
            return profil_id
        return self.profils[0]["id"] if self.profils else None

    def tirants_eau(self, profil_id):
        """Les tirants d'eau auxquels le dossier a mesuré cette
        configuration."""
        return [r["TE_milieu_m"] for r in self.points.get(profil_id, [])]

    def surface_au_vent(self, profil_id, te_m):
        """(dict des cinq grandeurs, note) à ce tirant d'eau.

        La note vaut "" quand le tirant d'eau tombe dans la plage mesurée du
        dossier (interpolation linéaire entre les deux cas encadrants, ou
        lecture exacte). Sinon elle dit en clair ce qui a été lu et à quelle
        distance — c'est une valeur approchée, et le critère qui en découle
        n'est qu'indicatif.

        Rend (None, motif) quand le dossier ne mesure pas cette
        configuration : il n'y a alors rien à approcher.
        """
        pts = self.points.get(profil_id) or []
        if not pts:
            if not self.points:
                return None, (f"la table {FICHIER} manque au dossier du "
                              "navire (copiez-la depuis navires/"
                              "<NOM>.exemple/, ou importez-la dans « Créer "
                              "ou modifier le navire… »)")
            return None, ("le dossier ne donne pas la surface au vent de "
                          "cette voilure")
        te = float(te_m)
        if len(pts) == 1:
            r = pts[0]
            return self._grandeurs(r), self._note_hors_plage(r, te)
        if te <= pts[0]["TE_milieu_m"]:
            return self._grandeurs(pts[0]), self._note_hors_plage(pts[0], te)
        if te >= pts[-1]["TE_milieu_m"]:
            return self._grandeurs(pts[-1]), self._note_hors_plage(pts[-1], te)
        for a, b in zip(pts, pts[1:]):
            if a["TE_milieu_m"] <= te <= b["TE_milieu_m"]:
                ecart = b["TE_milieu_m"] - a["TE_milieu_m"]
                t = 0.0 if ecart <= 0 else (te - a["TE_milieu_m"]) / ecart
                # une grandeur facultative absente d'un des deux cas
                # encadrants ne s'interpole pas : elle reste absente
                return ({g: a[g] + t * (b[g] - a[g]) for g in GRANDEURS
                         if g in a and g in b}, "")
        # inatteignable (la table est triée et bornée ci-dessus), mais on ne
        # rend jamais un dict vide sans le dire
        return None, "table de surfaces au vent incohérente"

    @staticmethod
    def _grandeurs(ligne):
        return {g: ligne[g] for g in GRANDEURS if g in ligne}

    @staticmethod
    def _note_hors_plage(ligne, te, tolerance=0.005):
        """La note d'une lecture en bord de table — "" si on y est.

        La tolérance vaut 5 mm de tirant d'eau : au-delà, la lecture est en
        bord de table et doit être signalée ; en deçà, c'est le cas du dossier
        lui-même, à l'arrondi d'impression près."""
        if abs(ligne["TE_milieu_m"] - te) <= tolerance:
            return ""
        return (f"hors des cas du dossier : surface au vent lue à "
                f"{ligne['TE_milieu_m']:.2f} m, tirant d'eau actuel "
                f"{te:.2f} m — critère indicatif")
