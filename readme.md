
# EDT Unicaen — Serveur MCP (Model Context Protocol)

Ce dépôt contient un serveur Model Context Protocol (MCP) minimal exposant des outils pour interroger des emplois du temps (EDT) de l'Université de Caen (Unicaen).

Le serveur est implémenté en Python et fournit des outils MCP (via `mcp.server.fastmcp`) pour récupérer le prochain cours d'un professeur, d'une salle ou d'un étudiant, et pour vérifier la disponibilité d'une salle.

## Points clés

- Nom : EDT Unicaen MCP Server
- Fichiers principaux : `index.py`, `utils.py`
- Outils MCP exposés : `prochain_cours`, `disponibilite_salle`
- Endpoint de santé : `/health`

## Fonctionnalités

- Construction d'URL de mise à jour ADE (endpoint tiers) à partir des métadonnées d'entrée.
- Récupération via HTTP des mises à jour (JSON ou ICS) et parsing pour retrouver les événements (prochains cours, disponibilités).
- Support d'une limite temporelle optionnelle lors des requêtes de disponibilité (paramètres `start` et `end`).

## Prérequis

- Python 3.10+ recommandé
- Dépendances listées dans `requirements.txt` (utiliser un environnement virtuel)

## Installation rapide

1. Créez et activez un environnement virtuel (Windows PowerShell) :

```powershell
python -m venv devenv
.\devenv\Scripts\Activate.ps1
```

2. Installez les dépendances :

```powershell
pip install -r requirements.txt
```

## Configuration

Le comportement du serveur peut être configuré via variables d'environnement :

- `MCP_HOST` — adresse d'écoute (par défaut `127.0.0.1`)
- `MCP_PORT` — port HTTP (par défaut `8000`)
- `MCP_MOUNT` — chemin de montage MCP (par défaut `/mcp`)
- `MCP_SSE_PATH` — chemin SSE (par défaut `/sse`)
- `MCP_MESSAGE_PATH` — chemin messages (par défaut `/messages/`)
- `MY_EDT` — nom par défaut à utiliser quand l'appelant ne fournit pas de nom (format attendu : `PRENOM NOM`)

Exemple (PowerShell) :

```powershell
$env:MCP_PORT = '8000'
$env:MY_EDT = 'Jean Dupont'
```

## Usage

Lancer le serveur en mode standard (stdio) :

```powershell
python index.py
```

Le serveur démarre un serveur MCP et expose les outils déclarés dans `index.py`.

### Endpoints utiles

- `/health` (GET) — renvoie un JSON simple pour vérifier que le serveur est actif.

Les outils MCP sont accessibles via la couche MCP (middleware) — voir le dispatch et le client MCP utilisé par vos agents/EDT.

## Outils MCP fournis

- `prochain_cours(nom: Optional[str]) -> dict` :
	- Retourne le prochain événement (date/heure ISO, résumé) pour le nom fourni (professeur / salle / étudiant / université).
	- Si `nom` absent ou égal à `me`/`moi`/`self`, le serveur utilise `MY_EDT` si configuré.
	- Recherche dans les fichiers `assets/*.json`, construit l'URL ADE, récupère la ressource, et tente de parser JSON ou ICS pour extraire le prochain événement.

- `disponibilite_salle(nom: Optional[str], start: Optional[str], end: Optional[str]) -> dict` :
	- Indique si la salle est libre maintenant, et si non jusqu'à quelle heure elle est occupée.
	- Paramètres `start`/`end` peuvent être des heures `HH:MM` ou des datetimes ISO pour limiter la fenêtre de recherche.

Les retours incluent des dates/horaires au format ISO complet (ex: `2025-10-25T08:00:00`).

## Données / Assets

Le dossier `assets/` contient plusieurs fichiers JSON d'exemple :

- `prof.json` — métadonnées des enseignants
- `salle.json` — métadonnées des salles
- `student.json` — métadonnées des étudiants
- `univ.json` — métadonnées générales / timetable

Ces fichiers servent de source locale pour résoudre un nom d'EDT et construire les URLs ADE.

## Développement

- Code principal : `index.py`
- Fonctions utilitaires de parsing/résolution : `utils.py`

Conseils pour développement :

1. Activez l'environnement de développement.
2. Installez les dépendances de développement si nécessaire.
3. Lancez `index.py` et testez les outils via un client MCP ou en simulant des appels.

## Tests

Il n'y a pas (encore) de suite de tests incluse dans ce dépôt. Pour ajouter des tests :

1. Ajouter `pytest` à `requirements.txt` ou `requirements-dev.txt`.
2. Écrire des tests unitaires pour `utils.py` (parsing ICS/JSON, construction d'URL, recherche d'entrées).

## Exemple d'utilisation (client MCP)

Un client MCP peut invoquer l'outil `prochain_cours` en passant un nom. La réponse est un objet JSON contenant `ok`, `source`, et `next` (ou `error`).

## Contribuer

Contributions bienvenues : issues, PRs pour ajouter des tests, améliorer la robustesse du parsing ICS/JSON, ou ajouter des outils MCP supplémentaires.

## Licence

Ce dépôt n'inclut pas de fichier `LICENSE`. Ajoutez-en un si vous souhaitez déclarer une licence explicite.

---

Si vous voulez, je peux :

- compléter le `readme.md` avec des exemples concrets d'appels (payloads et réponses),
- ajouter une suite de tests minimaliste pour `utils.py`,
- ou créer un `requirements-dev.txt` et des scripts make/shell pour développement.
