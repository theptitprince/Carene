# Premiers pas : une escale de bout en bout

Cette page s'adresse à quelqu'un qui **n'a jamais ouvert Carène** et doit
charger le navire aujourd'hui. Elle suit l'ordre d'une escale, avec le geste
exact à chaque étape ; les pages des écrans donnent ensuite le détail.

Le principe tient en une phrase : **on travaille sur un point du journal, on y
relève les capacités, on y pose la cargaison, on lit le verdict, on enregistre
— et à la prochaine escale on ouvre le point suivant, copie de celui-ci.**

## 1. Au lancement

Carène s'ouvre sur **l'unique navire de cette installation**. S'il n'y en a pas
encore, la fenêtre propose *Créer le navire…* et *Lire d'abord l'aide…* — ce
second bouton ouvre cette aide droit sur la page du parcours. Créer le navire
est le travail d'une fois, décrit dans [Le navire](navire.md) et
[Recréer le navire](creation_du_navire.md).

Un avertissement rappelle ce qu'est le logiciel : une **aide**, ni certifiée
ni réglementaire. Il invite aussi à *signaler un problème* — retenez-le.

Puis Carène demande **sur quel point travailler**. La liste montre les points
du journal, le plus récent en tête. Au premier lancement il n'y en a qu'un.

## 2. Se repérer dans la fenêtre

En haut, l'**en-tête** : les boutons *Enregistrer*, *Recalculer*, *Recadrer*,
*Aide* ; le nom du navire et la **liste des points** ; les trois boutons de vue
**Capacités**, **Chargement**, **Stabilité** ; les six chiffres qui décident
(déplacement, tirants d'eau, assiette, gîte, GM) ; la voilure ; le **verdict**.
Sur un petit écran l'en-tête passe à la ligne, rien ne disparaît.

Tout ce que fait Carène est dans les menus, décrits un par un dans [Les menus](menus.md).
Presque tout a une touche : `F2` journal, `F3` capacités, `F4` chargement,
`F5` stabilité, `F1` cette aide.

## 3. Ouvrir le point de l'escale

*Journal › Nouveau point (copie du courant)* (`Ctrl+N`), ou **＋ Nouveau
point…** au bout de la liste des points. Carène demande confirmation, puis
ouvre le point suivant : **mêmes sondes, même cargaison** que le précédent.
Donnez-lui sa date, son lieu (la liste propose les escales du navire), son
libellé (« Arrivée », « Départ »…).

> Pourquoi une copie ? Parce qu'à l'escale on ne repart pas de zéro : les
> soutes ont baissé, une partie de la cargaison est débarquée, le reste est
> encore à bord. On part de l'état réel et on corrige.

Voir [Le point de chargement](point_de_chargement.md).

## 4. Relever les capacités

`F3`. Pour chaque soute, ballast et caisse : la **mesure** relevée (sonde,
volume ou pourcentage) et sa valeur. Carène lit le poids, le centre de gravité
et la carène liquide dans les tables de jaugeage du dossier. La **densité** se
règle par capacité.

Le bouton *Ballastage…* (`F8`) propose une manœuvre de ballast pour tenir une
assiette ou redresser une gîte. Voir [Les capacités](capacites.md).

## 5. Dire ce qu'on embarque : le manifeste

`F4`, puis *Manifeste…* dans la barre. Une **ligne par lot** : type (depuis le
catalogue du bord, `Ctrl+K`), désignation, quantité, poids unitaire, hauteur,
stack, débord, port de déchargement, cale imposée s'il y en a une. Tout se tape
ligne par ligne ; le catalogue ne fait que proposer.

Voir [Le manifeste et le catalogue](manifeste.md).

## 6. Poser la cargaison

Deux chemins, qu'on combine :

- **le répartiteur** (`F9`, ou *Répartir le chargement…*) compose un premier
  jet : on lui dit ce qu'on cherche (remplir au maximum, ou tenir une
  assiette), ce qu'on s'autorise (empiler, tourner, mélanger les lots), ce
  qu'on respecte (l'ordre des escales, la charge de pont, la hauteur libre) ;
  puis on lit son compte rendu et on applique. Un **clic droit dans une cale ›
  Répartir automatiquement dans cette cale…** ne garnit que celle-là ;
- **à la main** : on prend un lot dans la barre, le fantôme suit le pointeur,
  le clic gauche pose, `A` tourne, le clic droit retire. Les colis se collent
  entre eux et aux parois ; la molette **jeu d'arrimage** dit de combien
  chaque colis déborde de ses dimensions. Un double-clic dans une cale
  **zoome** dessus, un autre revient au pont.

Une pose impossible — hors de la cale, sur un autre colis, sur une épontille en
place — est **refusée** et le motif s'affiche. Ce qui dépasse une charge
admissible ou une hauteur libre est **signalé** dans le verdict du plan, en
bas à droite, dont la liste mène au colis en défaut. `Ctrl+Z` défait n'importe
quel geste.

Voir [Charger à la main](chargement.md) et [Le répartiteur](repartiteur.md).

## 7. Lire la stabilité

`F5`. La vue montre le profil avec la flottaison, la coupe au maître, le bilan
des poids, les hydrostatiques, la courbe GZ et le tableau des **critères** pour
la voilure choisie. Le verdict de l'en-tête résume : **CONFORME**, **NON
CONFORME**, **HORS DOMAINE** (les tables ne couvrent pas ce cas — les chiffres
n'ont pas de valeur), **NON ÉVALUABLE**.

Si les tirants d'eau lus à la coque ne sont pas ceux du calcul, **Tirants
d'eau relevés…** (`F7`, ou le bouton de la barre) chiffre l'écart, dit où il
tombe, et pose un poids fictif qui recolle le calcul à la coque — et vous
avertit si le chiffre est étrange.

Voir [La stabilité](stabilite.md).

## 8. Enregistrer, figer, exporter

- **Enregistrer** (`Ctrl+S`) : le point est écrit dans le journal. Il reste
  modifiable.
- **Figer** (`Ctrl+Shift+S`) au départ : l'état du navire à cet instant,
  verdict compris, est archivé pour de bon.
- **Exporter** (`Ctrl+E`) : le rapport de stabilité, les relevés, le plan de
  chargement, les feuilles de pointage — Carène demande où les écrire. La
  planche pour les **dockers** est à part, dans le même menu.

Voir [Les exports](exports.md).

## 9. Quand quelque chose cloche

- Un refus de pose, un verdict orange : le motif est écrit — sur le plan, dans
  la barre d'état, dans la liste des problèmes.
- Un chiffre douteux, une fenêtre qui se ferme : *Aide › Signaler un
  problème…*. Trois questions, et Carène joint tout le reste.
- Le [Dépannage](reglages.md) répond aux ennuis courants : navire illisible,
  verrou d'un autre poste, dossier déplacé.

## Suite

[Les menus, un par un](menus.md), puis [Le point de chargement](point_de_chargement.md).
