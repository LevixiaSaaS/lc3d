---
name: lc3d
description: Conçoit des pièces imprimées en 3D qui marchent du premier coup — construites en code, vérifiées avant l'impression (montage, clips, ressorts, couches, résistance) et livrées en 3MF prêt à imprimer pour l'imprimante de la personne, avec la pièce affichée en direct dans LC3D Studio. À utiliser dès qu'on demande une pièce, un objet ou un mécanisme à imprimer en 3D.
---

# LC3D — pièces imprimées en 3D, vérifiées avant l'impression

Tu es l'IA de la personne. Elle te demande une pièce (« fais-moi une boîte avec un couvercle qui clipse pour ma P1S »). Tu fais **tout**, d'un seul coup : installation, Studio, questions, plan de l'objet, construction, vérifications, livraison. Elle n'a rien d'autre à faire que répondre à tes questions et regarder son Studio.

**Chaque commande Python passe par `~/cadenv/bin/python`** (l'environnement de LC3D) : ton terminal ne garde pas l'activation d'une commande à l'autre.

## 0. Récupérer LC3D

Si tu n'es pas déjà dans le dépôt LC3D (le dossier qui contient ce fichier) :

```bash
git clone https://github.com/LevixiaSaaS/lc3d.git && cd lc3d
```

Toutes les commandes suivantes se lancent depuis ce dossier.

## 1. Installer (une seule fois par machine)

```bash
~/cadenv/bin/python -c "import cadquery, trimesh, manifold3d" 2>/dev/null || bash install.sh
```

`install.sh` installe tout, gratuitement, sur Linux, macOS ou Windows avec WSL. Il demande Python 3.12 (`PY=python3.12`) : s'il manque, installe-le d'abord. Si une étape échoue, lis l'erreur et règle-la toi-même avant de continuer.

## 2. Ouvrir le Studio de la personne

```bash
~/cadenv/bin/python lc3d/lc3d.py studio-ouvrir
```

La première fois, ça crée son Studio (gratuit) et le garde sur sa machine ; les fois suivantes, ça rouvre le même (« rouvre mon Studio »). Donne-lui tout de suite le lien `studio` : c'est là qu'elle voit sa pièce se construire en 3D, et qu'elle peut toucher la pièce pour te montrer un endroit. Le lien est privé.

## 3. Poser seulement les questions qui manquent

- **L'imprimante** : si la personne l'a déjà nommée, ne la redemande pas. Trouve son nom exact : `~/cadenv/bin/python lc3d/lc3d.py imprimante "P1S"` (~1 150 machines). Sans `--imprimante`, LC3D prend la Bambu Lab P2S : passe donc toujours `--imprimante` à `apercu` et à `run`.
- Ensuite seulement ce qui change la pièce : taille, matériau, pièce achetée à loger (vis, aimant, ampoule…). Une valeur par défaut proposée à chaque question.

Affiche les questions dans le Studio aussi :

```bash
~/cadenv/bin/python lc3d/lc3d.py studio-ecrire studio/courant '{"projet":"Boîte","version":"v1","etape":"questions","message":"Avant de bâtir","questions":[{"q":"Quelle taille intérieure?","defaut":"80 × 60 × 40 mm"}]}'
```

## 4. Comprendre l'objet avant de dessiner

Cherche comment le vrai objet est fait (produits vendus, modèles populaires, vraies dimensions, comment on s'en sert), puis écris `projets/<Nom>/plan.json` :

```json
{"objet": "Bol de camping pliable", "usage": "manger dehors, se range dans un sac",
 "dimensions": "Ø 140 × 60 mm, paroi 2 mm", "references": ["Sea to Summit X-Bowl", "bol nomade populaire MakerWorld"],
 "design": "bord arrondi R1, fond plat stable, formes douces, rien de carré brut"}
```

Sans ce plan, LC3D refuse de livrer. Dessine une pièce **belle et logique** : arêtes extérieures arrondies ou chanfreinées, épaisseurs régulières, proportions du vrai produit. Une pièce brute (tout en arêtes vives) reçoit un ❌. Une arête qui doit rester vive (joint, face d'appui) : `"aretes_vives": "raison"` dans le plan.

## 5. Écrire le modèle (CAO par code)

Crée `projets/<Nom>/modele.py` en partant de l'exemple le plus proche :

- boîte, couvercle, boîtier : `exemples/Boite_couvercle.py`
- boîtier réglable : `exemples/Boitier_param.py`
- construction geste par geste pour le Studio : `exemples/Demo_gestes.py`

Le fichier contient `PARAMS`, `build(p)` → `{nom: Piece}` et, dès 2 pièces, `assembly(p, pieces)` → `Assemblage`. Construis chaque pièce avec `Atelier` (`a.ajouter(...)`, `a.couper(...)`, `a.modifier(...)`, chaque geste avec un titre simple) : le Studio rejoue chaque geste. Composants réutilisables (clips, charnières, filets, ressorts, engrenages…) : `lc3d/composants_lc3d.py` et `catalogue/`. Pour une pièce achetée (vis, douille, aimant, roulement…), utilise la vraie pièce standard (`vis()`, `roulement()`, `piece_achetee()`) et dessine autour d'elle.

## 6. Construire en direct dans le Studio

À chaque étape (le mécanisme, puis les clips, puis le reste) :

```bash
~/cadenv/bin/python lc3d/lc3d.py apercu projets/<Nom>/modele.py --out projets/<Nom>/ap --imprimante p1s
~/cadenv/bin/python lc3d/lc3d.py studio-pousser projets/<Nom>/ap --projet "<Nom>" --version v1 --etape construction --message "J'ajoute …" --imprimante "Bambu Lab P1S · PETG"
```

(`--imprimante` d'`apercu` et `run` = le nom de la machine ; celui de `studio-pousser` = le texte affiché dans le Studio.)

Si la personne dit « ici » ou « là », lis l'endroit qu'elle a touché : `~/cadenv/bin/python lc3d/lc3d.py studio-lire studio/ici`. Si elle a changé une cote dans le Studio : `studio-lire studio/demande`.

## 7. Vérifier, corriger, livrer

```bash
~/cadenv/bin/python lc3d/lc3d.py run projets/<Nom>/modele.py --out projets/<Nom>/sortie --imprimante p1s --studio --zip <Nom>_v1
```

Avec `--zip`, LC3D envoie tout seul la pièce et le rapport au Studio : **donne tout de suite à la personne le lien `studio_lien`** du résultat. Corrige le modèle jusqu'à **0 ❌** dans `projets/<Nom>/sortie/rapport.md` (entre les essais, pousse un aperçu avec `--etape correction`).

**Coup d'œil final :** regarde les images du résultat (`images`). Est-ce que ça ressemble au vrai objet ? Est-ce beau et logique ? Si non, corrige. Si oui, écris ta réponse dans `plan.json` (`"coup_oeil": "…"`). Ensuite :

```bash
~/cadenv/bin/python lc3d/lc3d.py studio-pousser projets/<Nom>/sortie --projet "<Nom>" --version v1 --etape pret --message "Prêt à imprimer" --imprimante "Bambu Lab P1S · PETG"
```

Le Studio affiche la pièce finale, le rapport des vérifications et le bouton de téléchargement. Donne aussi le zip à la personne : **un 3MF par pièce, réglages d'impression dedans**, rien d'autre. Dis l'orientation d'impression de chaque pièce.

## Règles

- La première impression doit marcher : ne propose jamais d'imprimer « pour tester ».
- Ne dis jamais « parfait » ou « aucune erreur » : dis ce qui a été vérifié et ce qui ne l'a pas été (le rapport le liste).
- Montre la pièce dans le Studio avant de livrer le zip : sans le coup d'œil final dans `plan.json`, l'étape « pret » est refusée.
- Modifie seulement ce que la personne demande ; demande avant de changer autre chose.
- Réponds dans la langue de la personne, simplement.
