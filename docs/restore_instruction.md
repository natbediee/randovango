# Instruction technique : restaurer les bases de Randovango

| | |
| --- | --- |
| **Objet** | Remettre en service les données de Randovango à partir d'une sauvegarde chiffrée |
| **Quand l'utiliser** | La machine est en panne ou remplacée ; ou un passage a abîmé les données |
| **Liée à** | La sauvegarde décrite dans le [guide d'exploitation](exploitation.md#sauvegarde-et-restauration-des-bases) |

## 1. Avant de commencer

Il faut :
- une archive `randovango_AAAAMMJJ_HHMMSS.tar.gz.enc` (dans le dossier des sauvegardes) :
  la date dans le nom est celle de la sauvegarde ;
- son mot de passe, et le fichier `.env` du projet, tous deux gardés hors de la machine ;
- Docker, git et python3 installés, et le projet récupéré avec git.

Sur un ordinateur neuf, remettre d'abord le `.env` à la racine du projet.
Sur la machine habituelle, après un passage raté, faire d'abord une sauvegarde de l'état actuel
(`python3 scripts/backup.py`) : la restauration remplace les données, et cette sauvegarde permet
de revenir en arrière.

Toutes les commandes se lancent depuis le dossier du projet. Dans les commandes, `ARCHIVE` est le
chemin complet de l'archive choisie. Si le trousseau n'a pas le mot de passe, ajouter
`--demander` aux commandes `restore.py` : le mot de passe est alors demandé sans être affiché.

## 2. Vérifier l'archive

Elle est rechargée dans des bases jetables, puis ses comptes de lignes sont comparés à ceux du
jour de la sauvegarde. Les vraies bases ne sont pas touchées.
```bash
python3 scripts/restore.py ARCHIVE --essai
```
*Résultat attendu* : `mysql`, `mongo` et `sqlite` suivis de « identiques à la sauvegarde ».
Sinon, ne pas aller plus loin et essayer l'archive précédente.

## 3. Restaurer

**3.1 Démarrer seulement les deux bases**, puis attendre qu'elles soient `(healthy)` :
```bash
docker compose up -d db_randovango mongo
```
```bash
docker compose ps
```

**3.2 Ouvrir l'archive dans un dossier :**
```bash
python3 scripts/restore.py ARCHIVE --dossier "$HOME/restauration"
```

**3.3 Recharger MySQL.** Le mot de passe de la base est lu dans le conteneur : rien à taper.
```bash
docker exec -i db_randovango sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root "$MYSQL_DATABASE"' < "$HOME/restauration/mysql.sql"
```

**3.4 Recharger Mongo** (`--drop` remplace ce qui est déjà dans la base) :
```bash
docker exec -i mongo_randovango sh -c 'mongorestore --quiet --archive --gzip --drop -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin' < "$HOME/restauration/mongo.archive.gz"
```

**3.5 Remettre la base des comptes et les traces des passages :**
```bash
mkdir -p storage logs && cp "$HOME/restauration/rando_users.sqlite" storage/ && cp -R "$HOME/restauration/logs/." logs/
```

**3.6 Démarrer toute l'application :**
```bash
docker compose up -d
```

## 4. Contrôler, puis nettoyer

**4.1 Comparer quelques comptes** : ceux du jour de la sauvegarde, puis ceux de la base restaurée.
```bash
grep -E '"(spots|restaurants|cities|users)"' "$HOME/restauration/comptes.json"
```
```bash
docker exec db_randovango sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root "$MYSQL_DATABASE" -e "SELECT COUNT(*) AS spots FROM spots; SELECT COUNT(*) AS restaurants FROM restaurants; SELECT COUNT(*) AS cities FROM cities;"'
```
*Résultat attendu* : les mêmes nombres.

**4.2 Essayer l'application** sur http://localhost : une ville connue, ses spots et ses services,
puis la connexion avec un compte existant.

**4.3 Effacer le dossier de restauration**, qui contient les données en clair :
```bash
rm -rf "$HOME/restauration"
```

## 5. En cas de problème

| Ce qu'on voit | Cause probable | Que faire |
| --- | --- | --- |
| « Mot de passe introuvable dans le trousseau » | ordinateur sans le trousseau | ajouter `--demander` |
| « Déchiffrement impossible » | mauvais mot de passe, ou archive pas entièrement téléchargée du drive | vérifier le mot de passe ; attendre la fin du téléchargement de l'archive |
| `No such container` | les bases ne sont pas démarrées | étape 3.1 |
| `Access denied` en 3.3 ou 3.4 | `.env` absent, ou bases créées avant sa mise en place | remettre le `.env` ; sur un ordinateur neuf seulement, `docker compose down -v` efface les bases vides, puis reprendre à 3.1 (**jamais sur la machine habituelle** : la commande efface aussi les vraies données) |
| La vérification signale des différences | archive incomplète ou abîmée | essayer l'archive précédente |
