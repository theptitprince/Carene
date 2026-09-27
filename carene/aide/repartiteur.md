# Le répartiteur automatique

Cette page explique comment faire proposer un plan de chargement complet, ce
que veut dire chaque réglage, et comment lire le compte rendu — en particulier
la liste de ce qui n'a pas pu être placé.

## Ouvrir le répartiteur

Bouton **Répartir le chargement…** de la vue [Chargement](chargement.md), ou
*Chargement › Répartir le chargement…* (`F9`), ou le bouton **Répartir…** du
manifeste.

Le bouton **?** de la fenêtre ramène directement à cette page.

## Ce que c'est — et ce que ce n'est pas

Le répartiteur propose un **premier jet**, à ajuster ensuite à la main. Il
essaie une quinzaine de dispositions par cale et garde la meilleure : c'est un
**choix comparé**, pas un optimum démontré. Sur un manifeste très hétérogène,
un arrangement à la main peut encore faire mieux.

Il ne touche jamais aux **colis épinglés** (`P`) ni au **matériel du bord**.

## Les réglages rapides

Trois boutons, en haut, cochent d'un coup une combinaison — qui se relit
ensuite **case par case** : rien n'est caché derrière un bouton.

| Réglage rapide | Ce qu'il coche, et pour quoi faire |
|---|---|
| **Au plus** | tout ce qui entre : on mélange les lots, on empile, on tourne. L'assiette et la gîte départagent les cales, sans jamais coûter un colis |
| **Chargement soigné** | un lot par cale, l'ordre des escales tenu, les ponts bas d'abord : le quai va plus vite et le GM est meilleur, mais il restera de la place inemployée |
| **Assiette tenue** | l'assiette visée prime sur le remplissage : le répartiteur s'arrête de garnir une cale plutôt que de rater la cible |

## Les trois familles de réglages

Elles sont rangées dans l'ordre où l'officier de chargement se pose les
questions.

### Ce qu'on cherche

D'abord la **priorité**, et elle seule :

| Priorité | Ce que fait le répartiteur |
|---|---|
| **Charger au maximum (l'assiette suit)** | il fait entrer le plus de colis possible, en servant à chaque fois la cale la plus libre — en *fraction* de sa surface, pour que la petite cave soit servie aussi. Il ne renonce jamais à un colis pour tenir une assiette : c'est le ballast qui rattrapera |
| **Tenir l'assiette visée (quitte à charger moins)** | il calcule le LCG que la cargaison doit avoir pour tomber sur l'assiette demandée, répartit pour l'approcher, et descend les lourdes. Une cale peut rester à moitié vide |

Puis deux buts, **cochés séparément et indépendants** :

- **Viser une assiette de** … m — positif = sur l'arrière. Décochée,
  l'assiette n'entre dans **aucun** départage, pas même pour choisir entre
  deux cales également libres. C'est le réglage du bord qui dit : « remplis,
  je m'occuperai de l'assiette au ballast ». Le compte rendu annonce quand
  même l'assiette que donne le plan, et dit en toutes lettres si elle sort du
  domaine des tables.
- **Chercher la gîte, TCG visé** … m — c'est le TCG **du navire entier** :
  0 m = navire droit, ce qu'on veut presque toujours. Le répartiteur en déduit
  le TCG que la **cargaison** doit viser, compte tenu de tout ce qui penche
  déjà — le lège du navire de référence est à +0,168 m (bâbord), les caisses sont rarement
  symétriques : un navire qui penche à bâbord reçoit sa cargaison à tribord.
  (Avant la v2.16, il visait un TCG de *cargaison* nul, et chargeait « du
  mauvais côté » sur un navire déjà penché.) Il s'en sert **après** la
  capacité et l'assiette, jamais devant elles : deux cales symétriques ont le
  même LCG et la même surface, c'est le TCG qui dit laquelle redresse le
  navire ; et dans chaque cale, c'est la disposition qui pousse le lot du bon
  bord. Une **zone morte de 5 cm** marque l'objectif atteint. Le compte rendu
  dit le TCG du navire prévu, celui de la cargaison, et ce qui reste à
  rattraper au ballast quand la cargaison ne suffit pas.

> Ce qu'il annonce est un **TCG en mètres, pas une gîte en degrés** : le
> répartiteur n'a pas le GM sous la main. La gîte réelle s'affiche au bandeau
> dès le plan appliqué.

### Ce qu'on s'autorise

| Réglage | Ce qui change quand on le décoche (ou le modifie) |
|---|---|
| **Empiler les colis quand le lot le permet (stack)** | décochée, une **seule couche** est posée, même sur un lot dont le manifeste annonce un stack de 3. Le manifeste n'est pas retouché — c'est le répartiteur qui s'interdit la deuxième couche |
| **Disposition dans la cale** | dans quel sens la cale se **remplit** — pas dans quel sens sont posés les colis. *Transversale — de tribord à bâbord, pour la gîte* : les colis se disposent d'une muraille à l'autre, et c'est la **gîte visée** qui décide du côté de départ (depuis tribord, depuis bâbord, ou depuis l'axe vers les deux bords quand on veut le navire droit). *Longitudinale — d'arrière en avant, pour l'assiette* : d'un bout à l'autre, et c'est l'**assiette visée** qui décide du bout de départ (arrière, avant, ou depuis le milieu). Ça ne change rien tant que le lot remplit la cale ; ça décide de tout dès qu'il ne la remplit qu'à moitié. *Automatique* laisse le calepinage loger le plus de colis possible. Une disposition imposée ne coûte jamais un colis sur une cale donnée ; le compte rendu dit, cale par cale, ce qui a été fait |
| **Tourner les colis de 90°** | le calepinage choisit alors l'orientation de chaque colis pour occuper le plus de place. Décochez pour garder tous les colis dans le sens du manifeste (empilement, fourches, saisines). Un type déclaré *sans rotation* au catalogue n'est jamais tourné, quoi qu'il en soit ici — et le compte rendu le dit |
| **Mélanger les lots dans une même cale** | décochée, un **lot à la fois** : le répartiteur finit un lot dans une cale avant d'y en commencer un autre, et n'ouvre une deuxième cale pour un lot que si la première est pleine. On remplit moins, mais le quai va plus vite |
| **Respecter les cales imposées du manifeste** | la colonne *Cale* du manifeste fait loi : un lot qui la porte n'est essayé que là, et reste à quai si elle est pleine. Décochée, la colonne devient un souhait |
| **Repartir des cales vides** | décochée (par défaut), le répartiteur **complète** ce qui est posé à la main. Cochée, il retire d'abord les colis des lots et cales cochés — sauf les épinglés et le matériel du bord — et **vous le confirme avant de le faire** |

### Ce qu'on respecte

- **Ordre des escales : ne rien empiler sur ce qui se débarque avant.** Le
  répartiteur lit le *port de déchargement* de chaque lot et l'ordre des
  escales du navire (*Navire › Escales du navire…*). Il refuse alors de poser
  un lot au-dessus d'un lot qui sort à une escale **antérieure** — dans une
  pile comme d'un pont à l'autre, une cale dont l'emprise recouvre une cale
  plus basse étant au-dessus d'elle. Deux lots sans port, ou de même port, ne
  se contraignent pas ; sans liste d'escales, la case se tait.
  **Ce n'est pas un plan d'escales** : le répartiteur traite les lots du plus
  lourd au plus léger, et ne cherche pas l'ordre qui les ferait tous tenir.
  Si des colis restent à quai avec cette case cochée, c'est à vous d'organiser
  la répartition — une cale par escale, ou la case décochée (D-80).
- **Marchandises dangereuses** (pas une case : une règle du navire). Un lot
  qui porte une classe IMDG ne va que dans une cale qui l'admet (champ
  *IMDG admises* de l'éditeur de plans). Sans cale qui l'admet — ou avec une
  cale imposée qui ne l'admet pas —, il reste à quai et le compte rendu dit
  « n'admet pas la classe IMDG … » (D-83).
- **Ponts servis d'abord** : *Automatique*, *Ponts bas (meilleur GM)* ou
  *Ponts hauts (débarquement plus facile)*. C'est un **départage**, jamais une
  contrainte : la cale suivante est servie dès que la préférée est pleine, et
  aucun colis n'est perdu pour cela.

> **Carène ne modélise pas l'accès.** Le plan proposé peut demander de déplacer
> un colis pour en sortir un autre qui est derrière. Seul l'empilement est
> tenu : ni le chemin des fourches, ni « ce qui est devant bloque ce qui est
> derrière ». Un demi-modèle d'accès serait pire que pas de modèle.

- **Charge de pont admissible (t/m²) : refuser ce qui la dépasse** et
  **Hauteur libre des cales : refuser ce qui la dépasse** — les deux
  contraintes qu'on peut **débrayer**. Cochées (toujours, à l'ouverture),
  elles refusent une pose comme elles l'ont toujours fait, et le compte rendu
  dit pourquoi un lot reste à quai. **Décochées**, le plan est composé comme si
  elles n'existaient pas, puis **relu** : ce qui les dépasse est dit dans le
  compte rendu, sous le titre orange *Contraintes débrayées — ce que le plan
  dépasse*, cale par cale et chiffres à l'appui (« 1030 : charge de pont
  débrayée — 6 colis au-delà de la charge admissible, jusqu'à 3,10 t/m² pour
  2,50 t/m² admissible »). Une fois le plan appliqué, les mêmes dépassements
  restent **signalés sur le plan de chargement** par les calques des charges
  et des hauteurs, et dans la liste des problèmes. Un rappel orange sous les
  cases reste affiché tant qu'une contrainte est débrayée, et **ces deux cases
  ne se retiennent pas** d'un passage à l'autre : débrayer se décide à chaque
  fois, exprès. À réserver aux chargements qu'on assume — une pièce lourde sur
  un renfort local que le calque des charges ne connaît pas — ou pour mesurer
  ce que la contrainte coûte en colis.

## Ce qui ne se règle pas

Ces contraintes sont **toujours** respectées, quelle que soit la case cochée :

- les **charges épinglées**, jamais déplacées ;
- le **contour de la cale** et les zones interdites ;
- la **hauteur libre** de la cale ;
- la **charge de pont admissible** (t/m²), vérifiée sous chaque charge **et**
  en moyenne sur la cale ;
- le **débord** du lot et le **jeu d'arrimage** de la vue Chargement.

Aucune règle de **ségrégation IMDG** n'est appliquée.

## Lire le compte rendu

Le répartiteur **relit son propre résultat** : il recalcule l'équilibre du plan
proposé et annonce l'assiette obtenue. Si elle sort du domaine des tables, il
le dit en toutes lettres plutôt que de présenter un résultat extrapolé.

Le compte rendu donne :

1. **combien de colis sont posés**, et où ;
2. l'**assiette** et le **TCG** obtenus ;
3. **ce qui n'a pas pu être placé, et pourquoi, cale par cale**.

### Pourquoi des colis ne sont pas placés

C'est le point le plus utile du compte rendu. Quand la raison est un
**réglage**, le répartiteur **nomme le réglage** — et il le met **avant** les
motifs de cale :

| Ce qu'il écrit | Ce qu'on peut faire |
|---|---|
| « l'empilement est interdit par les réglages » | cocher *Empiler les colis quand le lot le permet (stack)* |
| « les lots ne sont pas mélangés » | cocher *Mélanger les lots dans une même cale* |
| « l'ordre des escales interdit d'empiler là » | décocher *Ordre des escales*, ou corriger les ports du manifeste |
| « la cale imposée est pleine » | décocher *Respecter les cales imposées*, ou changer la cale au manifeste |
| « type sans rotation » | c'est une donnée du catalogue, pas un réglage d'ici |
| « plus de place », « hauteur libre », « charge admissible » | c'est la cale qui est pleine ou qui refuse : il n'y a pas de case à décocher |

> **Une case se décoche ; « plus de place » ne se décoche pas.** C'est pour
> cela que les motifs de réglage passent devant.

## Appliquer, puis reprendre à la main

Le plan proposé s'applique d'un bouton. Il n'est **pas définitif** : on revient
à la vue [Chargement](chargement.md) et on déplace ce qu'on veut. Épinglez
(`P`) ce que vous voulez garder avant de relancer le répartiteur.

Les réglages **se retiennent** d'un lancement à l'autre. Ce sont des réglages
de *travail* : ils n'entrent jamais dans le dossier du navire ni dans le point
de chargement, et ils sont aussi ceux que reprennent l'outil **Zone** et
« Remplir depuis le manifeste ».

## Ce qu'il ne sait pas faire

- La **gîte** est un critère de départage, pas une contrainte. Un manifeste
  dissymétrique — une pièce lourde sans contrepartie — ne s'équilibre pas en
  déplaçant des palettes : le rapport dit alors ce qui reste, à corriger au
  [ballast](capacites.md).
- Pas de ségrégation IMDG, pas de réservation d'allées pour les engins.

## Suite

[La stabilité](stabilite.md) — vérifier ce que donne le plan.
