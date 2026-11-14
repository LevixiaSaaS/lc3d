"""LC3D — vraies pièces du commerce en 3D (fichiers STEP réels, gratuits).

Sources : FreeCAD-library (~2 600 STEP : moteurs NEMA, servos, Arduino, ESP32, alimentations, quincaillerie…)
+ KiCad 3D (~6 200 STEP : interrupteurs, connecteurs USB/JST/jack, boutons, LED, piles, écrans…)
+ bd_warehouse dans lc3d (vis, écrous, rondelles, roulements ISO à n'importe quelle taille)
+ n'importe quel STEP du fabricant que l'utilisateur télécharge (obtenir("chemin/local.step")). On télécharge seulement l'index (quelques
secondes), puis UNIQUEMENT le fichier choisi.

    chercher("moteur pas à pas nema 17")          -> liste de fichiers
    p = obtenir("Electrical Parts/Motors/Stepper/NEMA/NEMA_17_with_connector.step")
    p["forme"]  (CadQuery)  · p["dimensions"] (mm)  → Piece(nom, p["forme"], role="achetee")
Toujours dire à l'utilisateur que c'est le modèle de la bibliothèque, et lui faire comparer 2-3 cotes avec SA pièce
(fiche du vendeur ou pied à coulisse) avant de dessiner autour.
"""
import os, re, subprocess, unicodedata, json

BASE = os.path.join(os.path.expanduser("~"), ".lc3d")
SOURCES = {   # nom : (dépôt GitHub, dossier local)
    "freecad": ("https://github.com/FreeCAD/FreeCAD-library.git", os.path.join(BASE, "fclib")),          # mécanique, moteurs, cartes…
    "kicad": ("https://github.com/KiCad/kicad-packages3D.git", os.path.join(BASE, "kicad3d")),         # ~6 000 composants électroniques
}

FR_EN = {
    "moteur": "motor", "pas a pas": "stepper nema", "servo": "servo", "vis": "screw bolt", "ecrou": "nut", "rondelle": "washer",
    "roulement": "bearing", "interrupteur": "switch", "bouton": "button switch", "prise": "connector jack plug socket",
    "connecteur": "connector", "usb c": "receptacle", "usb": "usb", "pile": "battery", "batterie": "battery", "alimentation": "power supply",
    "ventilateur": "fan", "carte": "board", "capteur": "sensor", "led": "led", "ecran": "display lcd oled",
    "haut parleur": "speaker", "aimant": "magnet", "ressort": "spring", "engrenage": "gear", "poulie": "pulley",
    "courroie": "belt", "profile": "profile extrusion", "rail": "rail", "tige": "rod shaft", "axe": "shaft rod",
    "douille": "socket lamp", "ampoule": "bulb lamp", "fil": "wire cable", "relais": "relay", "fin de course": "endstop microswitch",
}


def _norm(s):
    return re.sub(r"[^a-z0-9.]+", " ", unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()).strip()


def _index():
    tout = []
    for nom, (depot, dossier) in SOURCES.items():
        try:
            if not os.path.isdir(os.path.join(dossier, ".git")):
                os.makedirs(os.path.dirname(dossier), exist_ok=True)
                subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", depot, dossier], check=True)
            out = subprocess.run(["git", "-C", dossier, "ls-tree", "-r", "HEAD", "--name-only"], capture_output=True, text=True, check=True).stdout
            tout += [f"{nom}:{l}" for l in out.splitlines() if l.lower().endswith((".step", ".stp"))]
        except Exception:
            pass
    return tout


def chercher(texte, n=8):
    q = _norm(texte)
    for fr, en in FR_EN.items():
        if fr in q: q += " " + en
    mots = [w for w in q.split() if (len(w) > 1 or "usb" in q) and w not in {"de", "du", "la", "le", "les", "un", "une", "pour", "avec", "des", "a"}]
    res = []
    for chemin in _index():
        c = _norm(chemin.replace("/", " ").replace("_", " ").replace("-", " ").replace(":", " "))
        nom = _norm(os.path.basename(chemin).replace("_", " ").replace("-", " "))
        sc = sum(3 if w in nom.split() else (2 if w in c.split() else (1 if w in c else 0)) for w in mots)
        if "/old/" in chemin.lower(): sc -= 1
        if sc > 0: res.append((sc, chemin))
    res.sort(key=lambda t: (-t[0], len(t[1])))
    return [dict(fichier=c, pertinence=s) for s, c in res[:n]]


def obtenir(chemin):
    """Télécharge ce seul fichier (« freecad:… » ou « kicad:… ») — ou charge un STEP local (ex. téléchargé du fabricant,
    McMaster, Digi-Key) — le charge dans CadQuery et donne ses dimensions."""
    import cadquery as cq
    if os.path.exists(chemin):
        f = chemin
    else:
        src, rel = chemin.split(":", 1) if ":" in chemin else ("freecad", chemin)
        dossier = SOURCES[src][1]
        subprocess.run(["git", "-C", dossier, "checkout", "HEAD", "--", rel], check=True, capture_output=True)
        f = os.path.join(dossier, rel)
    forme = cq.importers.importStep(f)
    bb = (cq.Compound.makeCompound(forme.vals()) if len(forme.vals()) > 1 else forme.val()).BoundingBox()   # TOUTES les formes du STEP
    return dict(fichier=f, source=f"FreeCAD-library : {chemin}", forme=forme,
                dimensions=dict(x=round(bb.xlen, 2), y=round(bb.ylen, 2), z=round(bb.zlen, 2)),
                boite=[[round(bb.xmin, 2), round(bb.ymin, 2), round(bb.zmin, 2)], [round(bb.xmax, 2), round(bb.ymax, 2), round(bb.zmax, 2)]],
                a_verifier="Comparer 2-3 cotes avec la fiche du vendeur ou un pied à coulisse avant de dessiner autour.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "obtenir":
        r = obtenir(sys.argv[2]); r.pop("forme"); print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(chercher(" ".join(sys.argv[1:])), ensure_ascii=False, indent=1))
