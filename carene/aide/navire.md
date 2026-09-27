# Le navire

Cette page décrit ce qu'on fait **une fois pour toutes** : créer le navire,
importer ses tables, décalquer ses plans — et ce que contient son dossier.

C'est une opération rare dans la vie du logiciel. Elle a donc sa fenêtre
dédiée, séparée de l'interface de travail quotidien.

Pour le parcours **dans l'ordre**, depuis une installation sans navire jusqu'au
navire contrôlé contre son dossier — le classeur à remplir, la table des
couples, le catalogue des plans, le calage sur les perpendiculaires, les cas de
référence — lisez [Recréer le navire depuis un logiciel
vierge](creation_du_navire.md). Cette page-ci décrit chaque fenêtre.

## Une installation, un navire

Carène ne gère **qu'un seul navire par installation**. Pour en changer, on
supprime celui en place (*Navire › Supprimer le navire…*) et on en crée un
autre. Rien n'est perdu au passage : une copie de sauvegarde du dossier est
conservée.

## La fenêtre « Création du navire »

*Navire › Créer ou modifier le navire…*

C'est un programme dans le programme : un **sommaire à gauche**, parcourable
dans l'ordre qu'on veut, et une **fiche détaillée à droite** pour chaque
étape — à quoi ça sert, ce qu'il faut avoir sous la main, la marche à suivre
numérotée, le format attendu (colonne, unité, requis, exemple) et les pièges à
éviter.

Le bandeau du haut affiche en permanence le verdict qui compte : **« Prêt à
calculer »** dès que l'essentiel est complet. Chaque étape porte une pastille
d'état (✓ fait, ! à vérifier, ○ à faire), **déduite des données réellement
présentes** — pas d'un cochage manuel.

### Ce qu'il faut, et dans quel ordre

| Section | Contenu | Nécessaire au calcul |
|---|---|---|
| **Essentiel** | le classeur à remplir, identification, table hydrostatique, pantocarènes, navire lège, critères | **oui** |
| **Compartimentage** | capacités et jaugeages, points d'envahissement, surface au vent | pour les liquides et le critère météo |
| **Plans du navire** | table des couples, profil, ponts, plans de ponts, capacités tracées | non — sert au placement graphique |
| **Vérification** | cas de référence, récapitulatif et enregistrement | — |

Avec l'essentiel seul, Carène calcule déjà l'équilibre, la courbe GZ et les
critères. Les liquides demandent les capacités et leurs jaugeages ; le
placement graphique des colis demande les plans.

### Importer les tables

Le chemin court est la première étape, **Par où commencer : le classeur à
remplir** : un classeur Excel type, une feuille par table, une explication sur
chaque intitulé, et un seul import pour tout — détaillé dans
[Recréer le navire](creation_du_navire.md). Chaque étape garde aussi son import
propre.

Les imports acceptent des **CSV** (délimiteur deviné) et des fichiers **Excel**,
avec **reconnaissance des colonnes par synonymes** : `Tirant d'eau moyen (m)`,
`Draft`, `TE_milieu_m` désignent la même grandeur. Les virgules décimales, les
espaces de milliers et le signe moins Unicode sont acceptés.

- Une colonne obligatoire absente produit un **message explicite**, pas un
  échec muet.
- Ré-importer un fichier corrigé **remplace** les lignes concernées au lieu de
  les cumuler.

### Les réglementations : le profil propose, vous cochez

L'étape **Critères de stabilité** commence par le **profil du navire** :
type (navire de charge, à passagers, de pêche, de servitude, navire-école,
voilier traditionnel), propulsion (moteur, voile, voile et moteur), vitesse
de service, moment dû au regroupement des passagers, cargaisons
particulières (bois en pontée). **Proposer d'après le profil** coche les
réglementations de la bibliothèque qui s'appliquent ; vous cochez ou
décochez ensuite — c'est votre dossier approuvé qui fait foi.

Chaque réglementation est un fichier de la **bibliothèque** de Carène
(`carene\reglements\`), avec son texte de référence, sa version, ses
critères et le paragraphe de chacun. Son **statut** est dit :

- *vérifiée* : rejouée sur un dossier de stabilité approuvé ;
- *relue* : relue ligne à ligne sur le texte officiel, mais pas encore
  rejouée sur un dossier approuvé — Carène le rappelle sous le tableau ;
- *à relire* : seuils écrits sans avoir été rejoués — Carène le dit à chaque
  calcul, et le rapport l'écrit en rouge. Relisez-la sur le texte officiel
  avant de vous y fier.

Certaines réglementations en **remplacent** d'autres, et c'est à vous de
choisir laquelle cocher : un navire qui applique les critères du bois en
pontée (§ 3.3.2) retient *bois en pontée* au lieu du § 2.2, et le *critère
météo, bois en pontée* au lieu du § 2.3 ; un navire de pêche de 24 à 45 m
peut retenir le *critère météo, pêche de 24 à 45 m* (pression du vent selon
la hauteur) au lieu du § 2.3.

Mettre une réglementation à jour, c'est remplacer son fichier : rien à
reprogrammer. Carène se limite à la stabilité **à l'état intact** : elle est
une aide, pas un logiciel certifié. Un navire créé avant la 3.0 garde ses
critères : ils sont relus comme les réglementations correspondantes, seuils
et conventions compris.

Parmi les dimensions, le **tirant d'eau d'été** du certificat de franc-bord
est facultatif, mais c'est lui qui permet de contrôler la ligne de charge à
chaque point (voir [La stabilité](stabilite.md)).

### Les capacités

C'est ici — étape *Capacités et jaugeages* — qu'on déclare, pour chaque
capacité : son code, son **contenu**, sa **densité**, sa case **Ballast**, sa
charge de pont admissible s'il s'agit d'une cale, et sa table de jaugeage.

Le **tri capacité / cale se fait par le nom** : une forme tracée sur un plan
est une capacité liquide si son nom figure dans la liste des capacités du
navire ; sinon c'est une cale. Aucun nom n'est écrit dans le code.

> **Conséquence à connaître** : une soute tracée sous un nom absent de la liste
> sera traitée comme une cale — et n'affichera de toute façon ni volume, ni
> poids, ni FSM, faute de jaugeage. Le remède : la nommer comme le dossier la
> nomme.

## L'éditeur de plans

*Navire › Éditeur de plans…*, ou la section *Plans du navire* de la fenêtre de
création.

Le bouton **?** de l'éditeur ramène directement à cette page.

C'est là qu'on décalque la tôle : les contours de ponts, les cales, les
épontilles, et les calques qui contraignent le chargement.

### Le flux, en six temps

#### 1. Importer le plan

Groupe *Fichier* : **Importer le profil…**, **Importer le plan du pont…**, ou
**Catalogue des plans…** — les PDF du chantier entrés une fois dans le dossier
du navire, d'où l'on affecte une page à chaque vue (voir
[Recréer le navire](creation_du_navire.md)).

**DXF ou PDF vectoriel** de préférence, image au pire. Le PDF est exploité
brut : l'image rendue n'est que le décor, les **sommets** — extrémités des
traits et croisements — sont lus dans le fichier lui-même et rangés avec le
navire, pour que l'accroche marche à bord sans le PDF d'origine.

#### 2. Caler

Outil **Calage**, puis **Appliquer**.

On clique des points connus et on donne leurs coordonnées :

- les **perpendiculaires** — boutons **PPAR** et **PPAV** de la fiche, qui
  lisent les X saisis à l'étape *Identification et dimensions* ;
- la **ligne de base** (Z = 0, sur le profil) et la **ligne de foi** (Y = 0,
  sur un pont) — boutons « Ligne de base » et « Sur l'axe » ;
- des **couples** (la table du navire propose « C.35 »).

Deux points calent l'échelle et l'origine ; un troisième hors axe contrôle.
L'**écart résiduel** de chaque point est affiché : c'est la mesure de
confiance du calage. Un calage se juge sur les cotes du plan, pas à l'œil.

L'**Accroche** fait venir le curseur sur les traits du plan, et surtout sur
leurs croisements. *Édition › Effacer le calage de la vue active* remet tout à
zéro.

#### 3. Décalquer la tôle

Groupe **DÉCALQUER** : **Contour de pont**, **Cale**, **Épontille**,
**Structure** (rectangle bloquant : descente, puits), **Traits de
construction** (ligne de foi, couples, cotes reportées).

Pour une **épontille** : un clic dans une cale, puis sa fiche. La case **fixe**
en fait de la structure, toujours en place ; sinon elle est **amovible** et se
met en place escale par escale depuis la vue [Chargement](chargement.md).

#### 4. Poser les calques contraignants

Groupe **CALQUES** : **Charge t/m²** (polygone dans une cale + valeur
admissible) et **Hauteur libre** (rectangle + hauteur).

Ces deux-là sont **signalés au chargement, non bloquants** : ils dépendent de
l'empilement, pas de l'endroit où l'on lâche une charge.

Une zone de hauteur est un **rectangle aligné sur les axes** — c'est ce que le
moteur sait lire ; une bande en L se pave de plusieurs rectangles.

#### 5. Le calque d'information

Trait, point ou texte : clés de saisissage, descente, remarque. **Rien n'en
dépend** — c'est du décor utile.

#### 6. Enregistrer

Le rapport d'enregistrement liste ce qui a été écrit et ce qui est signalé.

### Retoucher un contour déjà tracé

Cliquez la cale, puis :

| Geste | Effet |
|---|---|
| glisser une **poignée** | déplacer ce sommet |
| **clic droit sur un segment** → *Ajouter un sommet ici* | insérer un sommet sur le segment, à l'endroit visé, accroché comme le reste |
| **double-clic** sur un segment | la même chose |
| **Suppr** sur un sommet | le retirer |
| glisser **l'intérieur** | déplacer toute la cale |
| **Ctrl+Z** | annuler |

La cale sélectionnée passe **au-dessus** des autres : ses sommets restent
saisissables même sous une cale qui la recouvre. Là où plusieurs tracés se
superposent, un clic de plus au même endroit passe au suivant ; l'arbre
*Structure*, lui, les liste tous.

### Les cales IMDG

Dans la fiche d'une cale, le champ **IMDG admises** dit quelles
marchandises dangereuses elle peut recevoir : « 3, 9 », ou « toutes ». Vide
— le cas de presque toutes les cales —, elle n'en reçoit aucune. Une classe
principale admet ses divisions : « 2 » admet 2.1, 2.2 et 2.3. C'est une
donnée du navire : elle part avec ses plans, pour tous les postes.

Ensuite, tout suit : un lot du manifeste qui porte une classe IMDG n'est
envoyé par le répartiteur que dans une cale qui l'admet (et, sinon, reste à
quai avec la raison) ; un colis dangereux posé à la main ailleurs est un
**défaut** sur le plan, au même titre qu'un chevauchement ; le rapport de
stabilité liste les marchandises dangereuses, leur cale, et si elle les
admet.

Par exemple, un document de conformité marchandises dangereuses (SOLAS
II-2/19.4) peut n'autoriser les marchandises dangereuses, en colis seulement,
que dans **une seule cale**, et pour certaines classes : 1.4S, 2, 3, 4, 5.1,
6.1, 8 et 9, soit « 1.4S, 2, 3, 4, 5.1, 6.1, 8, 9 » dans le champ de cette
cale, et rien dans celui des autres. Les restrictions de ce document que
Carène ne contrôle pas — hydrogène interdit, 2.3 à risque subsidiaire 2.1 et
4.3 liquides de point d'éclair inférieur à 23 °C interdits sous pont,
matériel électrique isolé, par exemple — restent à la charge du bord.

### Changer le code d'une cale

Le code d'une cale (1030, 2040…) est ce sous quoi les points du journal
rangent leurs colis. On peut le changer dans l'éditeur de plans, à deux
conditions que Carène tient elle-même :

- **un code, une cale** : un code déjà porté par une autre capacité — ou
  qu'elle a porté — est refusé, et la barre d'état dit pourquoi. Deux cales
  au même code feraient compter deux fois la cargaison rangée sous ce code ;
- **l'éditeur travaille sur une copie** de la géométrie : ce que vous
  retouchez n'entre dans le calcul qu'à l'**enregistrement** des plans ;
- **la cale se souvient de ses anciens codes** : les colis d'un point écrit
  avant le changement restent dans cette cale, à sa hauteur — points figés
  compris, qu'on ne réécrit pas. À l'enregistrement des plans, les colis du
  point ouvert passent sous le nouveau code.

Si un point range des colis sous un code qu'aucune cale ne porte ni n'a
porté (cale supprimée), leur poids reste compté — au **plancher le plus haut
du navire**, faute de savoir où ils sont — et la vue Stabilité le dit en
tête de ses réserves : « Cargaison dans une cale que le plan ne connaît
plus ». Reposez-les dans une cale du plan.

### Verrouiller ce qui ne doit plus bouger

- **Clic droit sur une cale → *Verrouiller la cale*** (ou la case *Verrouillée*
  dans *Propriétés*) : elle ne se déplace plus, ses sommets non plus, on n'en
  ajoute ni n'en retire, et elle ne se supprime pas. Elle se dessine en
  **tirets** avec un 🔒.
- **Clic droit sur une poignée → *Verrouiller ce sommet*** : ce sommet-là
  seulement, dessiné en **carré plein** — de quoi tenir un coin sur un couple
  sans figer le reste du contour.

Un geste refusé par un verrou est toujours annoncé dans la barre d'état. Les
verrous sont une donnée du **navire** : ils partent avec le dossier, et un plan
verrouillé l'est pour tous les postes qui l'ouvrent.

### Cales qui se chevauchent

Deux cales d'un même pont qui se mordent de plus de quelques millimètres sont
**signalées** : barre d'état à la fin d'un tracé, suffixe « ⚠ chevauche … »
dans l'arbre, ligne dans le rapport d'enregistrement.

Se toucher bord à bord reste normal — c'est le décalque d'une cloison. C'est un
**avertissement, jamais un refus** : on enregistre, et on corrige ensuite.

### Changer de vue, et Échap

Le groupe **VUE** en tête de la barre *Décalquer* est une liste déroulante :
*Profil longitudinal*, puis chaque pont par Z croissant. *Affichage › Vue
précédente* (`Ctrl+PgUp`) et *Vue suivante* (`Ctrl+PgDn`), ou `Ctrl+↑` /
`Ctrl+↓`, passent d'une vue à l'autre. **`Échap` annule le tracé en cours,
quitte l'outil et revient à la sélection**, où que soit le focus (sauf dans un
champ de texte en cours de frappe) ; un second `Échap` désélectionne.

### L'assistant guidé

L'éditeur de plans a son propre assistant (`F1` dans cette fenêtre, ou le
bouton *Assistant*) : huit étapes, non modales, dont l'état est déduit du
projet. On peut donc revenir en arrière, corriger, l'assistant se recale seul.

### Reprendre la silhouette schématique

*Fichier › Reprendre la silhouette schématique…* écrit dans la géométrie la
silhouette que Carène reconstitue depuis les tables. Elle cesse alors d'être
signalée comme schématique, puisqu'elle devient votre tracé — et il reste à la
retoucher plutôt qu'à repartir de zéro. **Rien de ce qui est déjà tracé n'est
écrasé.**

*Fichier › Reprendre un ancien fichier .carene.json…* convertit un fichier des
versions où la géométrie était séparée des tables.

## Le dossier du navire

Tout ce qui décrit le navire vit dans **un dossier**, et rien n'est codé dans
le logiciel. Copier ce dossier suffit à transporter le navire sur un autre
poste.

```
navire/
  navire.json              identité, dimensions, navire lège, critères
  hydrostatiques.csv       table multi-assiette
  pantocarenes_kn.csv      KN par assiette, déplacement et gîte
  kgmax_gmmin.csv          courbes KGmax / GMmin réglementaires
  capacites.csv            caractéristiques des capacités
  jauges/*.csv             une table de jaugeage par capacité
  points_envahissement.csv ouvertures non étanches
  profils_vent.csv         surface exposée au vent par voilure et tirant d'eau
  geometrie.json           profil, ponts, capacités tracées, épontilles, calques
  formes.json              le plan des formes décalqué
  couples.csv              la règle des couples
  catalogue_charges.json   les types de colis du bord
  equipements_bord.json    le matériel du bord
  ports.json               les escales du navire
  plans/                   images et sommets des plans du chantier,
                           les PDF du catalogue et catalogue.json
  validation/              les cas de référence (cas_reference.csv)
  journal/                 les points du journal, créés à l'usage
  conditions/              les cas enregistrés
  exports/                 les documents sortis
```

Un navire neuf est écrit dans `navires/<NOM>/` à côté de l'application ; si
l'installation livre un navire d'exemple, il arrive sous
`navires/<NOM>.exemple/` et n'est copié en `navires/<NOM>/` qu'au premier lancement d'une installation
vierge — un navire déjà là n'est jamais écrasé par une mise à jour (voir
[Recréer le navire](creation_du_navire.md)).

*Navire › Emplacement du navire…* dit où il est et permet de le déplacer.

## Sauvegarder et reprendre le navire

Copier le dossier à la main marche, mais on oublie un sous-dossier, on ne
sait plus de quelle version il vient, et une clé USB fatiguée rend un
fichier tronqué sans le dire. D'où deux gestes, dans le menu *Navire* :

- **Exporter une sauvegarde du navire…** écrit **un zip du dossier entier**,
  tel quel — tables, géométrie décalquée, plans et calages, journal des
  points, brouillons, conditions, validation — plus les réglages de
  l'application à part, et un **manifeste** (`sauvegarde.json`) qui dit quelle
  version de Carène l'a écrite, quand, quel navire, et l'empreinte de chaque
  fichier. Le zip va par défaut dans `sauvegardes/` à côté de l'application,
  nommé `sauvegarde_<NAVIRE>_<date>_<heure>.zip`. Un point modifié et non
  enregistré n'y serait pas : Carène propose de l'enregistrer d'abord.
- **Importer une sauvegarde…** relit un tel zip et en fait le navire de
  l'installation. Avant d'écrire quoi que ce soit, Carène **vérifie l'archive
  entière** (manifeste, fichiers annoncés, empreintes) : une archive abîmée
  ou tronquée est refusée, en le disant, et le disque n'a pas bougé. Le
  navire déjà en place est **mis de côté** sous `<NOM>.avant_import-<date>`,
  jamais écrasé — le jeter est votre geste, pas celui du logiciel. Une case
  permet de reprendre aussi les réglages de l'application (répartiteur,
  préférences) ; ce qui désigne le poste (l'emplacement du navire) ne se
  transporte jamais.

> **Une sauvegarde d'une version passée se relit (D-54).** Une sauvegarde
> écrite par n'importe quelle Carène 2.x s'importe dans toute 2.x
> ultérieure et dans la 3.x. Ce n'est pas le zip qui fait cette promesse —
> il est trivial et le restera — mais les fichiers qu'il contient, qui
> portent chacun leur `format` et leur `version`, et dont les lecteurs
> gardent la lecture des versions passées (un point sans date de
> modification, une condition sans brouillon, un réglage sous son ancien
> nom). Si une version future ne savait plus relire un fichier tel quel,
> elle le convertirait à l'import, en le disant — jamais perdu en silence.

**Avant une mise à jour** : exporter une sauvegarde, décompresser la
nouvelle version, ouvrir Carène. Le navire est toujours là (la livraison ne
touche pas à `navires/<NOM>/`) ; la sauvegarde est le filet. **Pour envoyer
le navire** (un autre poste, une vérification à terre) : c'est ce zip-là
qu'on envoie, et *Importer une sauvegarde…* de l'autre côté.

Sans ouvrir la fenêtre, `python main.py --sauvegarde` écrit la même
sauvegarde : une tâche planifiée du poste peut le faire chaque soir.

## Ce que le dossier apporte au logiciel

Le principe est constant : **tout ce qui vient d'un dossier appartient au
dossier**. Le vocabulaire des contenus, la convention de carène liquide, les
seuils réglementaires, les angles tabulés des pantocarènes, les colonnes texte
des tables : rien de tout cela n'est écrit dans le code. Le logiciel n'a le
droit de connaître que la physique et les textes réglementaires.

C'est ce qui permet à Carène de servir n'importe quel cargo, et pas seulement
celui avec lequel il a été mis au point.

## Ce que l'éditeur de plans ne sait pas faire

- Un seul contour par pont ; la vue isométrique est un contrôle visuel, non
  éditable.
- Les **sommets** des zones de charge et de hauteur ne se déplacent pas à la
  souris : on supprime et on retrace (valeur, nom et cotes se corrigent, eux).
- Un plan importé depuis une **image** n'a pas de sommets : pas d'accroche.
  Un PDF ou un DXF, lui, part avec le navire dans `plans/`, sommets compris.
- Le plan propre à une cale sert de fond au placement des colis, mais n'est pas
  utilisé par les vues profil, pont et isométrie.

## Suite

[Réglages et dépannage](reglages.md).
