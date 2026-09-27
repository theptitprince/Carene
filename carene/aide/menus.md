# Les menus, un par un

Cette page est la **référence** : chaque menu de la barre du haut, chaque
entrée, ce qu'elle fait et sa touche ; puis les boutons de l'en-tête, les
barres des vues, et les menus du clic droit. Les pages des écrans expliquent
le *pourquoi* ; celle-ci dit *où c'est*.

## La barre de menus

### Chargement — ce qu'on fait au chargement du point

| Entrée | Touche | Ce qu'elle fait |
|---|---|---|
| **Annuler** | `Ctrl+Z` | revient sur le dernier changement du chargement — pose, retrait, déplacement, sonde, poids divers, voilure, poids fictif… L'entrée dit ce qu'elle va défaire (« Annuler la pose de 3 charges »). Quarante gestes en arrière ; changer de point vide la pile |
| **Refaire** | `Ctrl+Shift+Z`, `Ctrl+Y` | rétablit ce qui vient d'être annulé |
| **Brouillons du plan de chargement…** | | plusieurs plans de cargaison pour ce point : les garder côte à côte, en charger un, en valider un — voir [Charger à la main](chargement.md) |
| **Répartir le chargement…** | `F9` | le [répartiteur automatique](repartiteur.md) |
| **Ballastage…** | `F8` | le solutionneur de [ballastage](capacites.md) |
| **Tirants d'eau relevés…** | `F7` | comparer les tirants d'eau lus aux marques au chargement déclaré, et en tirer le poids fictif manquant — voir [La stabilité](stabilite.md) |
| **Quitter** | | ferme Carène ; la question « enregistrer le point ? » est toujours posée |

### Journal — sur quel point on travaille

| Entrée | Touche | Ce qu'elle fait |
|---|---|---|
| **Voir le journal** | `F2` (`Ctrl+J`) | la vue Journal : la fiche du point courant et la chronologie — voir [Le point de chargement](point_de_chargement.md) |
| **Ouvrir le point ▸** | | la liste de tous les points, le courant coché ; en choisir un demande confirmation |
| **Nouveau point (copie du courant)** | `Ctrl+N` | ouvre le point suivant du journal, copie intégrale de celui-ci ; demande confirmation |
| **Enregistrer le point** | `Ctrl+S` | écrit le point courant dans le journal (aussi le bouton *Enregistrer* de l'en-tête) |
| **Figer ce point…** | `Ctrl+Shift+S` | archive l'état du navire à cet instant, verdict compris — définitif |
| **Importer un ancien cas de chargement…** | | un cas enregistré par une version d'avant le journal devient un point |

### Navire — ce qui se définit une fois pour toutes

| Entrée | Touche | Ce qu'elle fait |
|---|---|---|
| **Créer ou modifier le navire…** | | la fenêtre de [création du navire](navire.md) : tables, capacités, plans |
| **Éditeur de plans…** | | décalquer les cales, poser les calques de charge, de hauteur et d'information — voir [Le navire › L'éditeur de plans](navire.md) |
| **Catalogue des charges…** | `Ctrl+K` | les types de colis du bord — voir [Le manifeste](manifeste.md) |
| **Matériel du bord…** | | les engins du navire (chariot, transpalette) : ils pèsent et prennent la place, ils ne sont pas au manifeste |
| **Escales du navire…** | | les ports de la ligne, et la recherche dans les 17 573 ports du monde |
| **Épontilles…** | | mettre en place ou déposer les épontilles amovibles (elles se tracent dans l'éditeur de plans) |
| **Exporter une sauvegarde du navire…** | | un zip du navire entier — tables, plans, journal, brouillons — à mettre sur une clé avant une mise à jour |
| **Importer une sauvegarde…** | | reprendre un navire depuis une sauvegarde ; le navire en place est mis de côté, jamais effacé |
| **Ouvrir un autre dossier de navire…** | | choisir le dossier d'un navire (sur ce poste, une clé, le NAS) et l'ouvrir à la place — rien n'est déplacé |
| **Supprimer le navire…** | | Carène ne gère qu'un navire : le supprimer permet d'en créer un autre |

### Exporter — ce qu'on sort

| Entrée | Touche | Ce qu'elle fait |
|---|---|---|
| **Exporter ou imprimer…** | `Ctrl+E`, `Ctrl+P` | la fenêtre unique des [exports](exports.md) : cocher les documents (rapport, relevés, plans, pointages, planche des dockers, journal), puis les prévisualiser, les imprimer ou les exporter — toujours la sélection entière |

### Affichage

| Entrée | Touche | Ce qu'elle fait |
|---|---|---|
| **Recalculer** | `Ctrl+R` | relance le calcul d'équilibre et de stabilité (il se relance de lui-même à chaque modification) |
| **Capacités** / **Chargement** / **Stabilité** | `F3` / `F4` / `F5` | les trois vues de travail |
| **Recadrer la vue** | `F` | remet le cadrage et le zoom de la vue en cours, sans changer l'angle de l'iso |
| **Calques du plan de chargement ▸** | | les mêmes cases que le bouton *Calques* de la barre du plan : ce qui se dessine, ce qui se signale |
| **Infobulles d'aide** | | rallume les bulles au survol des boutons et des champs (éteintes par défaut ; celles du plan restent) |

### Aide

| Entrée | Touche | Ce qu'elle fait |
|---|---|---|
| **Aide de Carène…** | `F1` | ce mode d'emploi, avec la recherche, le PDF et l'impression |
| **Vérifier les mises à jour…** | | demande au serveur des mises à jour s'il existe une version plus récente, et l'installe d'un clic (téléchargement vérifié, ancienne version gardée, navire jamais touché) — voir [Réglages et dépannage](reglages.md) |
| **Vérifier les mises à jour au lancement** | | coché par défaut : au démarrage, Carène demande au serveur des mises à jour s'il existe une version plus récente — sans réseau, une ligne le dit, rien ne bloque |
| **Serveur des mises à jour…** | | l'adresse du serveur, et l'identifiant et le mot de passe de ce poste si le dossier est protégé — gardés par Windows, jamais dans un fichier |
| **Signaler un problème…** | | trois questions, et Carène joint ce qui tournait et le journal technique ; il se dépose sur GitHub, dans les « Issues » de Carène — voir [Réglages et dépannage](reglages.md) |
| **Journal technique…** | | ce que Carène a noté depuis son lancement — à joindre en cas de problème |
| **À propos…** | | la version, l'avertissement, l'adresse de contact |

## L'en-tête

De gauche à droite : les boutons **Enregistrer**, **Exporter / imprimer**,
**Recalculer**, **Recadrer**, **Aide** ; le **nom du navire** et la **liste des points** (elle finit par
*＋ Nouveau point…*) ; les boutons de vue **Capacités**, **Chargement**,
**Stabilité** ; les six chiffres **DÉPLACEMENT**, **TE ARRIÈRE**, **TE AVANT**,
**ASSIETTE**, **GÎTE**, **GM CORRIGÉ** ; la **voilure** ; le **verdict**, et les
pastilles *POINT FIGÉ* ou *LECTURE SEULE* quand elles s'appliquent. Sur une
fenêtre étroite, l'en-tête passe à la ligne : rien ne se perd.

## La barre de la vue Chargement

Deux rangées de groupes, chacun sous son étiquette grise ; elles passent à la
ligne sur une fenêtre étroite.

| Groupe | Ce qu'il porte |
|---|---|
| **PONT** | un bouton par pont, et *Tout le pont* pour quitter le zoom sur une cale |
| **OUTIL** | *Sélectionner*, *Poser*, *Zone*, *Mesurer* — ce que le clic veut dire |
| **LOT** | le lot en main, *Tourner*, *Retirer* |
| **AFFICHAGE** | *Calques ▾*, et la couleur des colis (par lot, par port, par catégorie) |
| **CHARGEMENT** | *Répartir le chargement…*, *Manifeste…*, *Charges posées…*, *Épontilles…*, *Brouillons…* |
| **NAVIRE** | *Catalogue…*, *Matériel du bord…* |
| **POSE** | la case *Aimanter* et la molette du **jeu d'arrimage** |
| **ÉTAT** | les contrôles éteints, ce qui est posé, la dernière mesure, et le verdict du plan (déroulant : un clic mène au colis en défaut) |

Tout est détaillé dans [Charger à la main](chargement.md).

## La barre de la vue Stabilité

| Groupe | Ce qu'il porte |
|---|---|
| **RELEVÉ** | *Tirants d'eau relevés…*, le poids fictif en place, *Retirer le poids fictif* |
| **CALCUL** | *Navire lège inclus*, *Recalculer*, *Ballastage…* |
| **DOSSIER** | *Exporter ou imprimer…* |
| **ÉTAT** | le compte des critères tenus |

Voir [La stabilité](stabilite.md).

## Les menus du clic droit

| Où | Ce qui s'ouvre |
|---|---|
| **Sur un colis posé** (plan de chargement) | pas de menu : le clic droit **retire** le colis, qui retourne au manifeste — c'est le geste inverse du clic gauche |
| **Dans le vide d'une cale**, rien en main | le **menu de la cale** : zoomer / revenir au pont, *Répartir automatiquement dans cette cale…*, *Plan de cale…*, *Sélectionner les colis*, *Vider la cale* |
| **Dans le vide**, un lot en main | le clic droit **lâche le lot** (comme `Échap`) |
| **Sur une épontille** | la fenêtre *Épontilles…* (le clic gauche bascule celle-là) |

## Les touches, en une table

| Touche | Où | Ce qu'elle fait |
|---|---|---|
| `F1` … `F5` | partout | aide, journal, capacités, chargement, stabilité |
| `F7` / `F8` / `F9` | partout | tirants d'eau relevés / ballastage / répartiteur |
| `F` | vue graphique | recadrer |
| `Ctrl+N` / `Ctrl+S` / `Ctrl+Shift+S` | partout | nouveau point / enregistrer / figer |
| `Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y` | partout | annuler / refaire |
| `Ctrl+E` / `Ctrl+K` / `Ctrl+R` | partout | exporter / catalogue / recalculer |
| `A` / `R` / `P` / `Suppr` / `Maj+Suppr` / `Échap` | plan de chargement | tourner le fantôme / tourner le colis sur place / épingler / retirer un / retirer la sélection / lâcher le lot puis vider la sélection |
| `Alt` pendant un glissement | plan de chargement | s'affranchir de l'aimantation |

## Retour au sommaire

[Sommaire](index.md)
