# Les exports et rapports

Cette page dit quels documents Carène sait sortir, ce que chacun contient, et
où ils sont écrits.

## Une seule fenêtre pour tout

*Exporter › Exporter ou imprimer…* (`Ctrl+E`, ou `Ctrl+P`), le bouton
**Exporter / imprimer** du bandeau, ou celui de la barre de la vue
*Stabilité*.

À l'escale on sort en général tout d'un coup — le rapport pour le dossier, les
feuilles de pointage pour le quai, le plan pour la passerelle — et dans le même
dossier. La fenêtre est donc unique : des cases à cocher (avec **Tout cocher**
et **Tout décocher**), un dossier de sortie, et trois boutons qui portent tous
sur **la sélection entière** :

1. Cochez les documents voulus.
2. **Aperçu** montre tous les documents cochés à la suite, tels qu'ils
   s'imprimeront ; **Imprimer** les envoie en une seule fois à l'imprimante.
   Les deux boutons disent combien de documents ils vont montrer.
3. **Exporter (PDF, CSV)…** les écrit. Carène **demande alors où écrire** — le
   dossier proposé est celui du champ *Dossier* — et vous pouvez en choisir un
   autre. La ligne d'état dit ce qui a été écrit ; un bouton ouvre le dossier.

Le dossier proposé par défaut est `exports/` dans le dossier du navire, dans un
sous-dossier nommé d'après le point du journal.

## Les documents

| Case | Ce que c'est |
|---|---|
| **Rapport de stabilité (PDF)** | le dossier du point, en douze sections (voir ci-dessous) |
| **Relevé des capacités (CSV + PDF)** | le tableau de la vue [Capacités](capacites.md) tel qu'il est à l'écran, mesure relevée comprise |
| **Chargement : manifeste et charges posées (CSV + PDF)** | le manifeste ligne par ligne, et la liste de tous les colis posés avec leurs coordonnées |
| **Plan de chargement, un pont par page (PDF)** | le plan de chaque pont à l'échelle, avec les colis dessinés et légendés — le document du bord, pas celui du quai |
| **Plans cotés des cales, à vérifier à bord (PDF A3)** | une planche par cale : le contour à l'échelle et les demi-largeurs depuis l'axe, couple par couple, en millimètres. C'est **ce que le logiciel croit** de la cale, à confronter au mètre |
| **Feuilles de pointage, chargement et déchargement (PDF)** | les listes à cocher pour le quai, par lot et par escale |
| **Journal des points (CSV)** | la chronologie complète du navire |

## Ce que contient le rapport de stabilité

Le bord le trouvait maigre ; il porte maintenant tout ce que le poste de
travail sait de ce point (D-59), et **rien n'y est recalculé** : ce sont les
chiffres de l'écran, mis en page.

1. **Bilan des poids** — chaque poste avec son poids, ses centres et son FSM,
   sous-totaux par groupe, total.
2. **Capacités liquides, capacité par capacité** — sonde, volume, remplissage,
   poids à la densité du point, centres, FSM. Toutes les capacités du dossier,
   vides comprises : une capacité qu'on a oublié de relever se voit à zéro.
3. **Cargaison, cale par cale** — poses, colis, poids, aire de la cale, charge
   moyenne au mètre carré, charge admissible, **la pile la plus chargée et ce
   que le pont admet sous son emprise** (en rouge si elle dépasse), centres et
   ports de déchargement.
4. **Flottaison, centre de gravité et stabilité initiale** — le détail du
   bandeau.
5. **Hydrostatiques lues à l'équilibre** — la ligne de la table, colonne par
   colonne (volume, LCB, VCB, KMt, LCF, aire de flottaison, TPC, MCT, inerties,
   surface mouillée), et les **bornes des tables** du dossier.
6. **Courbe de stabilité (GZ)** — la courbe, puis **la même en chiffres** :
   tous les 5°, l'angle depuis l'équilibre et depuis la verticale, le GZ,
   l'aire cumulée, et les angles remarquables nommés (30°, 40°, GZmax, θf,
   annulation).
7. **Marge aux courbes limites du dossier (KG max / GM min)** — au déplacement
   et à l'assiette du point, avec le **critère qui limite le KG max** dans
   cette zone de la table, tel que le dossier l'écrit.
8. **Critères réglementaires** — le tableau du verdict, pour la voilure portée.
9. **Le même chargement sous chaque voilure** — cargo, voilure complète,
   intermédiaire, réduite : surface au vent, vent admissible (force et nœuds),
   angle, aire, verdict. C'est ce que l'écran dirait en déroulant le sélecteur.
   **Seule la voilure portée fait le verdict du point** ; les autres disent ce
   qu'il en serait, à chargement inchangé.
10. **Ouvertures et angle d'envahissement** — les ouvertures du dossier
    classées de la première immergée à la dernière, avec franc-bord local et
    gîte d'immersion : on voit non seulement θf, mais de combien la suivante
    est loin.
11. **Réserves et messages du moteur.**
12. **Profil et coupe au maître.**

Une section dont le dossier ne porte pas la matière (pas de capacité liquide,
pas de courbes limites, pas de voilure) le dit en une ligne et n'invente rien.

## Le plan de chargement pour les dockers

La case **Plan de chargement pour les dockers (PDF)** de la fenêtre
*Exporter ou imprimer*. C'est le document
qu'on tend au quai une fois le chargement calé : **qui va où, visuellement**.

Un PDF A3 paysage, à part du lot de l'escale (`plan_chargement_<navire>_point<n>.pdf`) :

- **une page de synthèse** — navire, point, voilure, la liste des planches
  (« page 2 : cale 1040 (Pont inférieur) »), les **cales vides, sans planche**,
  un tableau *lot · cale · pont · colis · tonnage · port de déchargement*, les
  totaux posés et le **reste à quai** ;
- **une page par cale chargée** — *un plan cale par cale* : sur le quai, une
  équipe travaille une cale, et c'est cette feuille-là qu'elle tient. La cale
  seule sur la feuille se dessine au **1/75** pour une cale de 15 à 21 m (la calette
  au 1/40) — un pont entier tenait au 1/125–1/150, la palette fait maintenant
  16 mm au lieu de 8. Autour, en gris : le bordé et les cales voisines en
  pointillé, avec leur code quand il tombe sur la feuille ; les repères de
  couples ; la ligne de foi. Dans la cale : les zones interdites hachurées,
  les épontilles en place en carrés noirs, et chaque colis en rectangle **à la
  couleur de son lot, dans son sens, et rien d'écrit dessus** — une pile se
  reconnaît à son trait doublé, le matériel du bord est hachuré. **La couleur
  est le code.** Sous le plan, le code couleur en tableau, **en français
  sous-titré anglais** : par lot, la pastille, le nom, les colis dans la cale
  et au lot, **Empilés / Stacked** (« non / no », « oui ×2 / yes ×2 »), le
  tonnage, les ports de chargement et de déchargement ; puis le total de la
  cale sur une ligne. À droite, une **vignette de situation** : le pont en
  petit, cette cale en noir. Les flèches d'orientation sont bilingues aussi
  (*AVANT / FORWARD →*, *BÂBORD / PORT SIDE ↑*). Le bas de la feuille reste
  blanc — pour le crayon.

Une cale qui ne porte que du matériel du bord a sa page (le chariot qui y dort
est un obstacle), et la feuille dit qu'il reste à bord.

> **Pourquoi pas de numéro sur les colis ?** La première version numérotait
> chaque colis de son rang dans le lot. Sur un quai, un chiffre sur une caisse
> se lit comme un **ordre de pose** — qui n'est pas du tout celui de la
> planche. Le plan dit *où* va chaque colis ; la couleur dit *lequel*.

Arrière à gauche, bâbord en haut, comme à l'écran. Un chargement vide donne
une page qui le dit.

## Ce que porte chaque document

Tous portent, en tête ou en pied : le **navire**, le **point du journal**, la
**version de Carène** et l'**avertissement**.

> **Ce qui est exporté est ce que l'écran affiche, réserves comprises.** Un cas
> `HORS DOMAINE` sort avec sa mention ; un critère `NON ÉVALUABLE` sort comme
> tel. Rien n'est embelli au passage.

## Aperçu et impression

Les boutons **Aperçu** et **Imprimer** de la fenêtre portent sur **tous les
documents cochés**, à la suite, et disent combien il y en a (« Aperçu
(3 documents)… »). Pour un seul document, ne cochez que lui. Chaque document
garde **sa** mise en page : le rapport en A4 portrait, les relevés et le plan
en A4 paysage, les plans cotés et la planche des dockers en A3. Un document
qui n'est qu'un tableau CSV (le journal des points) ne s'imprime pas : il est
laissé de côté, et l'infobulle des boutons le dit.

L'aperçu et l'impression demandent le module d'impression de Qt. Sur une
installation minimale où il manque, ils sont indisponibles — l'export PDF,
lui, marche toujours.

## Les plans cotés : à quoi ils servent vraiment

Ce ne sont pas des documents d'escale mais un **outil de vérification**. Le
contour d'une cale a été décalqué d'un plan du chantier ; cette planche imprime
la demi-largeur que Carène en tire à chaque couple, en millimètres. On corrige
en rouge toute cote démentie par le mètre, et le décalque suit.

À faire une fois, à l'installation du navire, puis à chaque retouche de
contour.

## Suite

[Le navire](navire.md) — ce qu'il faut avoir saisi pour que tout cela existe.
