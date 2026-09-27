# -*- coding: utf-8 -*-
"""Le verrou DU NAVIRE : un seul Carène à la fois sur un dossier de navire,
d'où qu'on l'ouvre.

Le bord (21/09/2026) : « Le programme est stocké sur NAS, il est donc
accessible depuis plusieurs ordinateurs. Vu comme le verrou est codé, il est
possible de lancer Carène depuis plusieurs ordinateurs. Quand Carène est
déjà ouvert, ça serait même chouette de savoir quel ordi l'exploite déjà. »

Le verrou d'instance de `app_paths` (un `QLockFile` à côté de la
configuration, un guichet local) répond à UNE question : « y a-t-il déjà un
Carène sur CE POSTE ? » Il ramène la fenêtre ouverte au premier plan, et
c'est tout ce qu'il sait faire. Il ne voit pas l'autre ordinateur — le
processus qu'il connaît n'existe pas chez lui, le guichet est local — et
surtout il verrouille la mauvaise chose : ce qui est partagé sur le NAS, ce
n'est pas l'installation, c'est LE DOSSIER DU NAVIRE, avec son journal.
Deux Carène qui écrivent dans le même journal s'écrasent l'un l'autre sans
un mot.

D'où ce verrou-ci, qui vit DANS le dossier du navire (`carene.ouvert.json`,
à côté de `navire.json`) et dit qui l'a ouvert : la machine, la session, le
processus, depuis quand — et un BATTEMENT, réécrit toutes les trente
secondes tant que Carène tourne. Le second poste lit tout cela avant
d'ouvrir quoi que ce soit :

- battement récent → le navire est bel et bien ouvert ailleurs, et on peut
  dire où : « Carène est déjà ouvert sur SERVER-PC (session Bridge) depuis
  08:12 ». On ne s'ouvre pas dessus ; on peut regarder en LECTURE SEULE ;
- battement périmé (plus de `PERIME_S` sans battre) → le poste qui le tenait
  a planté, ou son câble est parti : on propose de reprendre le verrou, en
  le disant ;
- même machine → le PID tranche tout de suite, comme pour le verrou local :
  un processus mort n'attend pas trois minutes.

Rien ici ne dépend de Qt ni d'un service : un fichier, écrit de façon
atomique, sur le partage que tout le monde voit. C'est volontairement
rustique — un NAS de bord n'a ni base de données ni serveur de verrous, et
un fichier qui dit « ouvert par X depuis 08:12 » se comprend même à la main
dans l'explorateur.
"""
import getpass
import json
import os
import platform
import socket
import time
from dataclasses import dataclass, field

FICHIER = "carene.ouvert.json"
BATTEMENT_S = 30          # on réécrit le battement toutes les 30 s
PERIME_S = 180            # sans battement depuis 3 min : le détenteur a disparu
FORMAT = "carene-verrou-navire"


def _machine():
    for f in (socket.gethostname, platform.node):
        try:
            n = f()
            if n:
                return n
        except Exception:
            continue
    return "poste inconnu"


def _session():
    for f in (getpass.getuser, lambda: os.environ.get("USERNAME", ""),
              lambda: os.environ.get("USER", "")):
        try:
            n = f()
            if n:
                return n
        except Exception:
            continue
    return ""


def _processus_vivant(pid):
    """Le processus `pid` existe-t-il SUR CETTE MACHINE ? None si on ne sait
    pas dire (droits) — dans le doute on ne déclare pas un poste mort."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                # 87 = paramètre invalide : le PID n'existe pas ; 5 = accès
                # refusé : il existe, mais pas à nous
                return ctypes.GetLastError() == 5
            code = ctypes.c_ulong()
            vivant = True
            if ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
                vivant = code.value == 259          # STILL_ACTIVE
            ctypes.windll.kernel32.CloseHandle(h)
            return vivant
        except Exception:
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _iso(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def _depuis_iso(s):
    try:
        return time.mktime(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError, OverflowError):
        return None


def age_sur_le_disque(chemin):
    """Secondes écoulées depuis la dernière écriture de `chemin`, mesurées
    sur L'HORLOGE DU DISQUE qui le porte — ou None si on ne peut pas.

    Le battement écrit dans le fichier est l'heure du poste qui l'a écrit. Le
    comparer à l'heure de CE poste, c'était comparer deux horloges : un poste
    en retard de plus de trois minutes, ou réglé en temps universel quand
    l'autre est à l'heure du bord, voyait le navire d'un collègue bien vivant
    « sans signe de vie » — et le reprenait (revue du 24/09/2026, P-3). Ici
    on écrit une sonde à côté du verrou et on compare les deux dates de
    modification, toutes deux posées par le même disque (le NAS, sur un
    partage) : aucune horloge de poste n'entre dans le calcul."""
    dossier = os.path.dirname(os.path.abspath(chemin))
    sonde = os.path.join(dossier, ".carene-horloge.%d.tmp" % os.getpid())
    try:
        with open(sonde, "w", encoding="utf-8") as f:
            f.write("sonde")
        maintenant = os.stat(sonde).st_mtime
        return max(0.0, maintenant - os.stat(chemin).st_mtime)
    except OSError:
        return None
    finally:
        try:
            os.remove(sonde)
        except OSError:
            pass


def heure_lisible(iso):
    """« 08:12 » si c'est aujourd'hui, « 19/09 08:12 » sinon."""
    t = _depuis_iso(iso)
    if t is None:
        return "?"
    if time.strftime("%Y-%m-%d", time.localtime(t)) == time.strftime("%Y-%m-%d"):
        return time.strftime("%H:%M", time.localtime(t))
    return time.strftime("%d/%m %H:%M", time.localtime(t))


@dataclass
class Detenteur:
    """Ce que le fichier dit de celui qui tient le navire."""
    machine: str = ""
    session: str = ""
    pid: int = 0
    depuis: str = ""
    battement: str = ""
    version: str = ""
    installation: str = ""
    lisible: bool = True            # False : fichier illisible ou d'un autre format
    # âge du dernier battement mesuré sur l'horloge du disque (voir
    # `age_sur_le_disque`) ; None si la mesure n'a pas pu se faire
    age_disque_s: float = None

    @property
    def age_s(self):
        """Secondes depuis le dernier battement ; None si illisible.

        Sur l'horloge du DISQUE quand on a pu la lire — c'est la seule que
        les deux postes partagent ; sur celle de ce poste sinon."""
        if self.age_disque_s is not None:
            return self.age_disque_s
        t = _depuis_iso(self.battement) or _depuis_iso(self.depuis)
        return None if t is None else max(0.0, time.time() - t)

    def est_ici(self):
        return self.machine == _machine()

    def perime(self):
        """Le détenteur a-t-il disparu ?

        Sans signe de vie depuis plus de `PERIME_S` : périmé, où que ce
        soit. Sur la même machine, un PID mort tranche tout de suite, sans
        attendre. Un fichier illisible est périmé — il ne protège personne."""
        if not self.lisible:
            return True
        age = self.age_s
        if age is not None and age > PERIME_S:
            # plus de signe de vie depuis trop longtemps : mort, où qu'il
            # soit — un Carène vivant bat toutes les 30 s. Même sur cette
            # machine : un PID peut avoir été réattribué à un autre
            # programme après un redémarrage, et lui ne bat pas
            return True
        if self.est_ici():
            vivant = _processus_vivant(self.pid)
            if vivant is False:
                return True
            if vivant is True:
                return False
        return age is None

    def phrase(self):
        """« sur SERVER-PC (session Bridge) depuis 08:12 »."""
        if not self.lisible:
            return "par un poste inconnu (fichier de verrou illisible)"
        ou = "sur ce poste" if self.est_ici() else f"sur {self.machine or 'un autre poste'}"
        if self.session:
            ou += f" (session {self.session})"
        if self.depuis:
            ou += f" depuis {heure_lisible(self.depuis)}"
        if not self.est_ici() and self.battement:
            ou += f" — dernier signe de vie à {heure_lisible(self.battement)}"
        return ou

    @classmethod
    def lire(cls, chemin, avec_age=True):
        try:
            with open(chemin, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return cls(lisible=False)
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            return cls(lisible=False)
        try:
            pid = int(d.get("pid", 0) or 0)
        except (TypeError, ValueError):
            pid = 0
        return cls(machine=str(d.get("machine", "")), session=str(d.get("session", "")),
                   pid=pid, depuis=str(d.get("depuis", "")),
                   battement=str(d.get("battement", "")),
                   version=str(d.get("version", "")),
                   installation=str(d.get("installation", "")),
                   age_disque_s=age_sur_le_disque(chemin) if avec_age else None)


@dataclass
class VerrouNavire:
    """Le verrou d'un dossier de navire. `prendre()` puis `battre()` à
    intervalle ; `liberer()` en partant. `tenu` dit si c'est nous."""
    dossier: str
    version: str = ""
    installation: str = ""
    tenu: bool = False
    detenteur: Detenteur = None
    repris_de: Detenteur = None     # le verrou périmé qu'on a repris, s'il y en avait un
    # le verrou est tenu par une AUTRE machine qui ne donne plus signe de
    # vie : on ne le reprend pas sans le demander (voir `prendre`)
    perime_ailleurs: bool = False
    erreur: str = ""
    depuis: str = ""
    _pid: int = field(default_factory=os.getpid)

    @property
    def chemin(self):
        return os.path.join(self.dossier, FICHIER)

    # ---------------------------------------------------------------- prise
    def prendre(self):
        """Essaie de prendre le verrou. Vrai si c'est nous qui le tenons.

        Création EXCLUSIVE du fichier (`O_EXCL`) : deux postes qui essaient
        dans la même seconde ne peuvent pas croire tous les deux avoir
        gagné — le système de fichiers ne crée le fichier qu'une fois, et
        c'est vrai aussi sur un partage réseau. Quand le fichier existe, on
        lit qui le tient ; un fichier périmé se reprend, jamais un fichier
        vivant. Si le dossier n'est pas inscriptible, on le dit (`erreur`)
        et on laisse passer : un verrou qui empêcherait d'ouvrir un navire
        sur une clé USB en lecture seule serait pire que pas de verrou."""
        self.detenteur = None
        self.repris_de = None
        self.perime_ailleurs = False
        self.erreur = ""
        if not os.path.isdir(self.dossier):
            self.erreur = "dossier du navire introuvable"
            self.tenu = False
            return False
        if self._creer_exclusif():
            return True
        d = Detenteur.lire(self.chemin)
        if d.est_ici() and d.pid == self._pid and d.lisible:
            # c'est déjà nous (le navire est rouvert dans la même session)
            self.tenu = True
            self.depuis = d.depuis
            return True
        if d.perime() and (d.est_ici() or not d.lisible):
            # sur CE poste (processus mort, redémarrage) ou fichier illisible :
            # on reprend sans demander, rien ni personne n'est dépossédé
            self.repris_de = d
            return self.reprendre()
        if d.perime():
            # UNE AUTRE MACHINE, sans signe de vie : peut-être plantée,
            # peut-être seulement en veille ou coupée du réseau le temps d'un
            # grain. On ne la dépossède plus sans le demander (D-77) :
            # l'appelant pose la question, et `reprendre()` fait le geste.
            self.perime_ailleurs = True
        self.detenteur = d
        self.tenu = False
        return False

    def reprendre(self):
        """Prend le verrou de force : celui qui le tenait est mort (ou
        l'utilisateur l'a décidé, en connaissance de cause)."""
        try:
            os.remove(self.chemin)
        except FileNotFoundError:
            pass
        except OSError as e:
            self.erreur = f"le verrou n'a pas pu être repris : {e}"
            self.tenu = False
            return False
        if self._creer_exclusif():
            return True
        self.detenteur = Detenteur.lire(self.chemin)
        self.tenu = False
        return False

    def _creer_exclusif(self):
        try:
            fd = os.open(self.chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return False
        except OSError as e:
            # dossier en lecture seule, partage capricieux : on n'empêche
            # pas d'ouvrir, on le note
            self.erreur = f"le verrou n'a pas pu être écrit : {e}"
            self.tenu = True          # on ouvre quand même, sans protection
            self.depuis = _iso()
            return True
        self.depuis = _iso()
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(self._contenu())
        self.tenu = True
        return True

    def _contenu(self):
        return json.dumps({
            "format": FORMAT,
            "machine": _machine(), "session": _session(), "pid": self._pid,
            "depuis": self.depuis or _iso(), "battement": _iso(),
            "version": self.version, "installation": self.installation,
            "note": "Carène est ouvert sur ce navire. Ce fichier disparaît à la "
                    "fermeture ; s'il reste alors que Carène est fermé partout, "
                    "le poste indiqué a planté : Carène proposera de le reprendre.",
        }, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------ battement
    def battre(self):
        """Réécrit le battement. Vrai si le verrou est toujours le nôtre.

        Écriture dans un fichier provisoire puis renommage : un autre poste
        qui lit pendant l'écriture voit l'ancien ou le nouveau, jamais un
        JSON à moitié écrit. Et on vérifie avant que le fichier est encore
        le nôtre : si un autre poste l'a repris (il nous a cru mort — veille
        prolongée, câble débranché), c'est LUI qui a la main désormais, et
        on ne réécrit pas par-dessus."""
        if not self.tenu:
            return False
        if self.erreur:
            return True               # sans verrou écrit, rien à battre
        d = Detenteur.lire(self.chemin)
        if d.lisible and not (d.est_ici() and d.pid == self._pid):
            self.tenu = False
            self.detenteur = d
            return False
        provisoire = self.chemin + ".%d.tmp" % self._pid
        try:
            with open(provisoire, "w", encoding="utf-8") as f:
                f.write(self._contenu())
            os.replace(provisoire, self.chemin)
        except OSError:
            try:
                os.remove(provisoire)
            except OSError:
                pass
            return True               # un battement raté n'est pas une perte du verrou
        return True

    def encore_a_nous(self):
        """Le fichier de verrou nous désigne-t-il encore ? À demander AVANT
        chaque écriture dans le dossier du navire : le battement ne passe que
        toutes les 30 s, et un autre poste qui a repris le navire entre-temps
        doit gagner tout de suite, pas une demi-minute plus tard (P-11)."""
        if not self.tenu:
            return False
        if self.erreur:
            return True               # ouvert sans verrou écrit : rien à relire
        # sans mesurer l'âge : on veut savoir QUI, pas depuis quand — et
        # sur un NAS, chaque sonde est un aller-retour réseau
        d = Detenteur.lire(self.chemin, avec_age=False)
        if not d.lisible:
            return True               # un fichier en cours de réécriture
        if d.est_ici() and d.pid == self._pid:
            return True
        self.tenu = False
        self.detenteur = d
        return False

    # -------------------------------------------------------------- libérer
    def liberer(self):
        """Efface le fichier — s'il est encore le nôtre."""
        if not self.tenu:
            return
        self.tenu = False
        if self.erreur:
            return
        d = Detenteur.lire(self.chemin)
        if d.lisible and not (d.est_ici() and d.pid == self._pid):
            return                    # repris par un autre : on ne touche pas
        try:
            os.remove(self.chemin)
        except OSError:
            pass


def detenteur_actuel(dossier):
    """Qui tient ce navire, sans rien prendre. None s'il est libre."""
    chemin = os.path.join(dossier, FICHIER)
    if not os.path.exists(chemin):
        return None
    return Detenteur.lire(chemin)
