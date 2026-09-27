# Réglages et dépannage

Cette page rassemble les réglages d'affichage, l'endroit où sont les fichiers,
et quoi faire quand quelque chose ne va pas.

## Les réglages d'affichage

### Infobulles d'aide

*Affichage › Infobulles d'aide*

Elles sont **éteintes par défaut** : une fois le logiciel connu, une bulle qui
s'ouvre sous chaque bouton gêne plus qu'elle n'aide. Rallumez-les pour
découvrir le logiciel, ou pour former quelqu'un : chaque bouton, chaque champ
et chaque case dit alors ce qu'il fait au survol.

Les bulles du plan de pose et de la vue navire — celles qui disent ce qui est
**sous la souris** — restent toujours affichées : elles ne commentent pas un
bouton, elles lisent le dessin.

### Une seule palette

Carène n'a qu'un thème, le clair : un poste de passerelle se lit de jour, et
toutes les paires texte / fond tiennent le contraste réglementaire, y compris
dans les vues graphiques. Le thème sombre des versions précédentes a été
retiré à la demande du bord (2.19.0).

### Calques du plan de chargement

*Affichage › Calques du plan de chargement* coche les mêmes cases que le menu
**Calques** de la barre du plan — voir [Charger à la main](chargement.md).

### Recadrer la vue

*Affichage › Recadrer la vue* (`F`) remet le cadrage et le zoom de la vue
graphique en cours — isométrie des capacités, plan de chargement — **sans**
changer l'angle de la vue isométrique.

## Les raccourcis

### Fenêtre principale

| Touche | Ce qu'elle fait |
|---|---|
| `F1` | ouvrir cette aide |
| `F2` | vue Journal |
| `F3` | vue Capacités |
| `F4` | vue Chargement |
| `F5` | vue Stabilité |
| `F` | recadrer la vue en cours |
| `Ctrl+R` | recalculer |
| `F8` | ballastage |
| `F9` | répartir le chargement |
| `Ctrl+N` | nouveau point (copie du courant) |
| `Ctrl+S` | enregistrer le point |
| `Ctrl+Shift+S` | figer le point |
| `Ctrl+J` | journal |
| `Ctrl+K` | catalogue des charges |
| `Ctrl+E` | exporter |

### Sur un plan

molette : zoom · bouton du milieu : déplacement · `G` : grille · `F` : zoom
ajusté · `Échap` : annuler le tracé · `Suppr` : supprimer la sélection ·
`Entrée` : terminer le polygone.

### Sur une charge

glisser : déplacer · `R` : tourner sur place · `P` : épingler · `Suppr` (ou
clic droit) : retirer · `Alt` : ni magnétisme ni aimantation.

### Un lot en main

`A` : tourner le fantôme · clic gauche : poser · clic sur une épontille : la
mettre en place ou la déposer · `Échap` (retour à l'outil *Sélectionner*, où
que soit le focus), clic droit dans le vide, ou « — aucun lot — » : quitter
la pose · second `Échap` : vider la sélection.

## Où sont les fichiers

Trois endroits, à ne pas confondre.

| Quoi | Où |
|---|---|
| **Le dossier du navire** | à côté de l'application, ou là où *Navire › Emplacement du navire…* l'a mis. Il contient tout ce qui décrit le navire, plus le journal des points et les exports |
| **La configuration** | `carene.config.json`, à côté de l'application — ou dans le profil utilisateur si l'application est installée dans un dossier en lecture seule |
| **Le journal technique** | `journaux/carene-AAAA-MM-JJ.log`, à côté de la configuration |
| **Le navire d'exemple** | `navires/<NOM>.exemple/`, quand l'installation en livre un : copié en `navires/<NOM>/` au premier lancement d'une installation vierge, jamais ouvert tel quel, jamais recopié ensuite |

Ces trois premiers endroits sont **les vôtres** : une mise à jour de Carène ne
les contient pas et ne les touche pas. Voir [Recréer le navire depuis un
logiciel vierge](creation_du_navire.md), dernier paragraphe.

Lancé en ligne de commande avec `--chemins`, Carène imprime le dossier de
l'application, celui des données, le fichier de configuration et le navire
trouvé. C'est la réponse la plus rapide à « quelle copie du logiciel est-ce que
je suis en train de lancer ? ».

## Le journal technique

*Aide › Journal technique…*

Le bord n'a pas de console sous les yeux. Cette fenêtre montre donc, à l'écran :

- le **chemin** du fichier ;
- la **fin du journal** ;
- un bouton **Copier tout** et un bouton **Ouvrir le dossier**.

Le journal note, en continu et sans qu'on le demande :

- l'**identité de la version au lancement** — numéro, dossier d'où le code est
  réellement chargé, Python, Qt, système, dossier du navire. Deux copies du
  logiciel coexistent souvent sur un bureau : la première ligne du journal
  tranche la question ;
- **toute erreur** et toute exception non rattrapée ;
- les messages de Qt.

**Il ne note aucune donnée de chargement** : ni poids, ni port, ni position.
Un fichier par jour, les dix derniers gardés.

> **Quand quelque chose se passe mal**, ouvrez cette fenêtre, cliquez *Copier
> tout*, et joignez le texte à votre message. C'est ce qui permet de comprendre
> à distance.

## Signaler un problème

*Aide › Signaler un problème…*

Un bogue, un chiffre douteux, une fenêtre qui se ferme : dites-le. Les
signalements se font sur **GitHub**, dans les « Issues » de Carène
(https://github.com/theptitprince/Carene/issues) — il faut un compte GitHub, gratuit —, et
l'avertissement du lancement le rappelle. La fenêtre pose **trois questions** — *ce que je faisais*, *ce qui
s'est passé*, *ce que j'attendais* — et joint d'elle-même **ce qui tournait** :
version, système, Python et Qt, navire et point ouverts, verdict affiché, vue
ouverte, et les dernières lignes du journal technique (la case *Joindre le
journal technique* s'enlève, mais sans lui un problème rare est presque
impossible à retrouver). L'aperçu montre le rapport **entier** avant l'envoi :
on n'envoie rien qu'on n'ait pu lire, et il ne contient ni chargement ni
donnée du navire. **Le dépôt est public** : la case *Masquer le nom du
navire* (cochée) remplace le nom du navire et le chemin de son dossier
partout dans le rapport, journal compris.

Trois façons de l'envoyer :

- **Signaler sur GitHub…** — la page d'un nouveau signalement s'ouvre dans le
  navigateur, titre et corps remplis ; le rapport complet est aussi copié, et
  un rapport trop long pour le lien s'y colle à la place du texte tronqué ;
- **Copier le rapport** — pour le coller dans un signalement ouvert depuis un
  autre poste ;
- **Enregistrer…** — un fichier `carene_<version>_signalement_<date>.txt`, à
  côté du journal technique par défaut.

## Les mises à jour

*Aide › Vérifier les mises à jour…*, et *Affichage › Vérifier les mises à
jour au lancement* (coché par défaut).

Carène demande au **serveur des mises à jour** s'il existe une version plus
récente qu'elle. Le serveur publie deux fichiers : `derniere.json` (le
numéro de la version, le nom du zip, sa taille, son empreinte SHA-256 et ses
notes) et le zip du **programme seul** — jamais le navire. Au lancement, la
vérification se fait en arrière-plan, après les questions du démarrage, et
ne bloque jamais :

- **sans connexion à Internet**, la barre d'état dit « la vérification de
  mise à jour n'a pas pu avoir lieu : pas de connexion » — et c'est tout ;
- **rien de publié** sur le serveur, ou **identifiant refusé** : une ligne le
  dit, avec la raison ;
- **à jour**, une ligne le dit ;
- **une version plus récente existe** : une fenêtre s'ouvre, non modale (elle
  attend qu'on ait fini), avec le numéro, ce qu'il y a de neuf, et le bouton
  **Télécharger et installer…**.

### Le serveur, l'identifiant et le mot de passe

*Aide › Serveur des mises à jour…* donne l'adresse du serveur (par défaut
celle du logiciel) et, si son dossier est protégé par `.htaccess`,
l'**identifiant** et le **mot de passe**. Ils ne sont écrits dans **aucun
fichier** : Windows les garde dans son gestionnaire d'identification, pour
cet utilisateur de ce poste. Un autre poste les demandera une fois. *Oublier
le mot de passe* les efface. L'adresse, elle, va dans `carene.config.json`.

> **http:// ou https://** — avec une adresse en `http://`, l'identifiant et
> le mot de passe circulent en clair, et l'empreinte ne protège que d'un
> téléchargement abîmé, pas d'un zip remplacé. Carène l'accepte et le dit en
> orange. Dès que le serveur a son certificat, passez l'adresse en
> `https://`.

### Ce qui se passe à l'installation

Le zip est téléchargé dans un dossier temporaire et **vérifié** — sa taille
contre celle annoncée, son empreinte SHA-256 contre celle de
`derniere.json`. **Sans empreinte publiée, rien ne s'installe**, et un zip
qui ne correspond pas non plus. Carène propose ensuite d'enregistrer le
point, se ferme, et un petit script (`mise_a_jour_carene.bat`) attend sa
fermeture, **garde l'ancienne version de côté** dans `_ancienne_<version>\`,
déplie le zip par-dessus le programme, et relance Carène. Le journal de
l'opération est dans `journaux\mise_a_jour.log`.

> **Le dossier du navire n'est jamais touché** — ni `navires\<NOM>\`, ni le
> journal des points, ni `carene.config.json`, ni les journaux techniques.
> Le zip du serveur ne porte que le programme. Pour revenir en arrière,
> `_ancienne_<version>\` contient le programme d'avant.

Un poste qui aurait un dépôt GitHub de mises à jour peut encore le donner par
la clé `"depot_github": "proprietaire/depot"` de `carene.config.json` ; une
adresse de serveur donnée sur le poste passe avant.

## L'aide en PDF, ou imprimée

Dans la fenêtre d'aide, **PDF…** enregistre la page affichée ou **tout le
manuel** (sommaire en tête, une page par chapitre), et **Imprimer…** fait de
même vers une imprimante. Le nom proposé porte la version :
`Carene_<version>_aide_complete.pdf`.

## À propos

*Aide › À propos…* donne la version de Carène, le rappel de ce qu'est le
logiciel, l'avertissement, et l'adresse où signaler un problème.

## Dépannage

### « Le dossier du navire n'existe plus »

Le dossier a été déplacé, renommé, ou il était sur une clé qui n'est plus là.

1. *Navire › Emplacement du navire…* et désignez le bon dossier.
2. S'il a vraiment disparu, recopiez-le depuis la livraison ou depuis une
   sauvegarde : c'est un simple dossier, il se copie.
3. Si Carène trouve **le même navire à côté de l'application**, il le propose
   au démarrage plutôt que de s'ouvrir vide.

Rien n'est effacé au passage : l'ancien dossier, s'il existe encore, reste où
il est.

### « Carène est déjà ouvert sur ce poste »

Un second lancement ramène la fenêtre déjà ouverte au premier plan et se
retire : deux Carène écriraient dans le même journal. Si aucune fenêtre
n'apparaît, c'est qu'un Carène tourne sans fenêtre visible (autre bureau,
session verrouillée) : fermez-le par le gestionnaire des tâches ; le verrou
`carene.verrou` tombe avec le processus.

### « Carène est déjà ouvert sur ce navire » — plusieurs postes, un NAS

Quand le dossier du navire est sur un partage (NAS, dossier réseau) que
plusieurs ordinateurs voient, le verrou du poste ci-dessus ne suffit pas :
il ne voit pas l'autre ordinateur. Carène pose donc aussi un **verrou dans
le dossier du navire** — `carene.ouvert.json`, à côté de `navire.json` —
qui dit **qui l'a ouvert** : la machine, la session Windows, depuis quand,
et un signe de vie réécrit toutes les trente secondes tant que Carène
tourne (D-55).

Un second poste qui ouvre le même navire lit ce fichier et le dit en
clair : *« Ce navire est déjà ouvert sur SERVER-PC (session Bridge) depuis
08:12 »*. Il propose alors de **quitter**, ou de **consulter en lecture
seule** : tout se lit, le bandeau porte la pastille rouge *LECTURE SEULE ·
SERVER-PC*, et rien ne s'enregistre — ni point, ni éditeur de plans, ni
catalogue, ni import de sauvegarde — tant que l'autre poste n'a pas fermé.
Fermez Carène là-bas, rouvrez ici.

Si le poste qui tenait le navire a **planté** (ou son câble est parti), le
signe de vie s'arrête. Au bout de **trois minutes** — comptées sur
l'horloge du **disque partagé**, pas sur celle des postes, pour qu'une
horloge fausse ou réglée en temps universel ne fasse passer personne pour
mort —, le lancement suivant ne reprend plus le navire tout seul : il
**demande**. La boîte dit depuis combien de temps l'autre poste se tait et
propose un troisième bouton, **Reprendre le navire**, à n'employer que si
vous êtes sûr que personne n'y travaille : l'autre poste passera en lecture
seule, et ce qu'il n'avait pas enregistré sera perdu. Sur la même machine,
un processus mort ne fait pas attendre : le verrou se reprend tout de suite.

Chaque enregistrement relit le verrou : si un autre poste a repris le
navire entre deux signes de vie, ce poste-ci passe en lecture seule avant
d'écrire — jamais deux Carène n'écrivent le même journal.

Le fichier disparaît à la fermeture normale. Il ne part ni dans une
sauvegarde ni dans une livraison.

### « Le dossier du navire ne répond pas »

Le navire est sur un disque ou un partage réseau (NAS) qui ne répond pas :
lecteur pas encore monté au démarrage du poste, réseau coupé. Carène
**n'ouvre rien à sa place** — jusqu'à la 2.20, elle ouvrait sans un mot la
copie posée à côté de l'application et la retenait comme navire du poste —
et ne change rien à sa configuration. L'écran d'accueil le dit, avec le
chemin attendu, et propose **Réessayer** : rétablissez l'accès au partage,
puis cliquez.

### Aucun navire n'est défini sur ce poste

L'écran d'accueil le dit et propose **Créer le navire…** ; son bouton **Lire
d'abord l'aide…** ouvre directement
[Recréer le navire depuis un logiciel vierge](creation_du_navire.md), le
parcours complet depuis une installation sans navire.

### Une soute n'apparaît pas dans la vue Capacités

Elle est probablement tracée sous un nom absent de la liste des capacités du
navire, et Carène la traite alors comme une cale. Le remède : la nommer comme
le dossier la nomme. Voir [Le navire](navire.md).

### Le verdict reste HORS DOMAINE

L'équilibre trouvé sort des tables du dossier. Ce n'est pas un défaut du
logiciel mais l'état du navire tel qu'il est saisi : vérifiez le relevé des
capacités, la cargaison posée, et les poids divers. Voir
[La stabilité](stabilite.md).

### Le champ « Escale » ne propose plus que les ports du navire

La liste mondiale UN/LOCODE n'a pas été trouvée à côté du logiciel. C'est une
donnée du **logiciel**, pas du navire : elle est réinstallée avec lui.

### Les plans ne s'ouvrent plus (DXF, PDF)

La lecture des DXF et des PDF demande des bibliothèques qui sont embarquées
dans la livraison. Si elles manquent, le journal technique le dit à
l'ouverture du fichier — c'est la première chose à regarder.

### « Il manque à ce poste, pour lancer Carène : … »

Au lancement, Carène vérifie ses dépendances (celles de `requirements.txt` :
PySide6, numpy, pymupdf, ezdxf, openpyxl) **avant** d'ouvrir quoi que ce
soit. S'il en manque une, ou si elle est trop ancienne, une boîte le dit en
une phrase avec la commande à lancer — pas de traceback. Pour tout
installer d'un coup sur un poste : double-cliquez **`installer_dependances.bat`**
(il vérifie Python, appelle `pip install -r requirements.txt`, puis refait
le contrôle). En console, `python main.py --dependances` donne l'état paquet
par paquet.

### Windows avertit au premier lancement

L'exécutable n'est pas signé. *Informations complémentaires*, puis *Exécuter
quand même*. Le poste de destination n'a besoin de rien d'autre : ni Python, ni
bibliothèque à installer.

## Quitter

*Chargement › Quitter*. Si le point courant a changé depuis le dernier
enregistrement, Carène le demande avant de fermer.

## Retour au sommaire

[Sommaire de l'aide](index.md)
