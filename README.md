# Carène

**Aide au chargement et à la stabilité à l'état intact des navires de charge.**

Carène se tient à côté de l'officier pendant qu'il prépare son chargement :
il pose ses colis sur le plan des cales, relève ses capacités, et lit à tout
moment l'équilibre, la courbe de stabilité et les critères réglementaires que
son navire doit tenir.

> **Carène est une aide, ni certifiée ni réglementaire.** Le dossier de
> stabilité approuvé du navire fait foi. Carène se limite à la stabilité à
> l'état intact et au positionnement des colis : ni stabilité après avarie,
> ni saisissage.

## Ce qu'elle fait

- **Le navire se décrit, il n'est pas programmé.** Tables hydrostatiques,
  pantocarènes, jaugeages, lège, surface au vent, plans des cales : tout
  s'importe à la création du navire (classeur Excel ou CSV), et des **cas de
  référence** du dossier approuvé se rejouent pour prouver que les tables ont
  été bien reprises.
- **Le chargement se pose sur le plan** : colis du catalogue du bord, piles,
  aimantation aux voisins et aux parois, zones interdites, épontilles,
  hauteur libre, charge admissible des ponts, cales IMDG ; un **répartiteur**
  propose une répartition, qu'on garde ou qu'on retouche.
- **La stabilité se lit en continu** : équilibre (tirants d'eau, assiette,
  gîte), GM corrigé des carènes liquides, courbe GZ, critère météo, et les
  critères de chaque réglementation retenue.
- **Les réglementations sont des fichiers de données**
  (`carene/reglements/*.json`) : Code IS 2008 (critères généraux, critère
  météo, navires à passagers, bois en pontée, navires de pêche), BV NR500
  pour les voiliers, ligne de charge. Elles se choisissent selon le profil du
  navire, et se mettent à jour sans reprogrammer.
- **Un journal des points de chargement**, le rapport de stabilité en PDF,
  le plan de chargement pour les dockers, les exports tableur.

## Installer et lancer

Carène est écrite en Python avec PySide6 (développée et testée sous
Windows avec Python 3.14).

```
installer_dependances.bat      (une fois : installe les paquets de requirements.txt)
python main.py
```

Au premier lancement, sans navire, Carène propose son aide, ouverte sur la
création du navire (*Navire › Créer ou modifier le navire…*). Le navire est
écrit dans `navires/<NOM>/`, à côté du programme ; il n'est jamais versé au
dépôt.

Un exécutable Windows se fabrique avec PyInstaller : `pyinstaller carene.spec`.

## L'aide

L'aide complète est dans le logiciel : *Aide › Aide de Carène…* (touche
**F1**), une page par écran, avec la recherche, l'export en PDF et
l'impression. `LISEZMOI.txt` retrace les versions.

## Signaler un problème

*Aide › Signaler un problème…* prépare le rapport (ce que vous faisiez, ce qui
s'est passé, ce qui tournait) et ouvre un nouveau signalement dans les
[Issues](https://github.com/theptitprince/Carene/issues) de ce dépôt. Le
dépôt est public : relisez le rapport avant de l'envoyer ; le nom du navire
et le chemin de son dossier y sont masqués par défaut.

---

ETDEL © 2026 — tous droits réservés.
