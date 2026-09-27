# Le serveur des mises à jour de Carène

Ce que Carène attend de lui (3.5.0, D-85), et comment le préparer.

## Ce qu'on y dépose

Dans le dossier du serveur (`http://theptitprince.fr/carene` pour l'instant,
l'adresse de `carene.SERVEUR_MAJ`), deux fichiers et rien d'autre :

- `carene_<version>.zip` — le **programme seul** ;
- `derniere.json` — sa description : version, nom du zip, taille, empreinte
  SHA-256, date, notes.

Les deux se fabriquent ensemble, sur le poste de développement :

    python tools/livraison.py <dossier_de_sortie> --serveur

Rien n'est envoyé d'ici : on dépose les deux fichiers par le FTP ou le
gestionnaire de fichiers de l'hébergeur, **le zip d'abord, `derniere.json`
ensuite** — un poste qui vérifierait entre les deux verrait sinon une version
dont le zip n'est pas encore là.

Le zip ne contient que `carene/`, `main.py`, `installer_dependances.bat`,
`requirements.txt`, `LISEZMOI.txt` et `carene.spec`. Jamais `navires/`, ni
les tests, ni les outils, ni `docs/`, ni les documents du bord.

## Le fichier .htaccess du dossier

À déposer dans le même dossier, sous le nom `.htaccess` :

    # Carène : dossier des mises à jour, protégé par mot de passe
    AuthType Basic
    AuthName "Carene"
    # chemin ABSOLU, et HORS du dossier web : le fichier des mots de passe ne
    # doit pas pouvoir se télécharger
    AuthUserFile /chemin/absolu/hors/du/web/.htpasswd
    Require valid-user
    Options -Indexes
    # derniere.json ne doit pas rester en cache chez un intermédiaire
    <IfModule mod_headers.c>
      <Files "derniere.json">
        Header set Cache-Control "no-cache"
      </Files>
    </IfModule>
    # Quand le certificat HTTPS est installé, décommenter :
    # RewriteEngine On
    # RewriteCond %{HTTPS} off
    # RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]

Le fichier `.htpasswd` se crée avec `htpasswd -c /chemin/.htpasswd bord` (ou
depuis le panneau de l'hébergeur). Son chemin absolu est donné par
l'hébergeur (souvent dans l'espace client, rubrique FTP).

## Côté Carène

*Aide › Serveur des mises à jour…* : l'adresse, l'identifiant, le mot de
passe. Le mot de passe est gardé par le gestionnaire d'identification de
Windows du poste, jamais dans un fichier. Carène ne l'envoie qu'à l'hôte de
l'adresse donnée ; une redirection vers un autre hôte le perd.

## HTTPS

Tant que l'adresse est en `http://`, l'identifiant et le mot de passe
passent en clair, et quelqu'un qui intercepte la connexion pourrait
remplacer à la fois le zip et son empreinte. Carène l'accepte et le dit. Le
jour où l'hébergeur fournit un certificat (Let's Encrypt, gratuit chez la
plupart), il suffit de décommenter les trois lignes ci-dessus et de passer
l'adresse en `https://` dans Carène — ou de changer `SERVEUR_MAJ` dans
`carene/__init__.py` pour tous les postes.
