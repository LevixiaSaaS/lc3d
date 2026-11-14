"""Génère le catalogue public : fiches.json + pour chaque composant un modèle 3D (GLB, couleurs par pièce)
et une image (rendu photo Blender si --photo, sinon rendu LC3D). Sortie : <dossier>/fiches.json, images/, modeles/."""
import os, sys, json, importlib, importlib.util, math, argparse
import numpy as np, trimesh

ICI = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, ICI)
import lc3d, catalogue_lc3d as K

COUL = [(0.85, 0.36, 0.11), (0.21, 0.24, 0.28), (0.90, 0.88, 0.84), (0.13, 0.36, 0.62), (0.40, 0.50, 0.25)]


def modele_vitrine(num):
    for c in (f"tests/composants/t_c{num:02d}.py", f"tests/vitrine/t_c{num:02d}.py"):
        if os.path.exists(os.path.join(ICI, c)): return os.path.join(ICI, c)
    return {1: os.path.join(ICI, "tests/t_clip.py"), 5: os.path.join(ICI, "tests/t_couvercle.py")}.get(num)


def scene(chemin):
    mod = lc3d._charger_modele(chemin); p = getattr(mod, "PARAMS", {})
    brut = mod.build(p); pieces = {}
    for n, v in (brut.items() if isinstance(brut, dict) else [(x.nom, x) for x in brut]):
        pieces[n] = v if isinstance(v, lc3d.Piece) else lc3d.Piece(n, v)
    A = mod.assembly(p, pieces) if hasattr(mod, "assembly") else None
    places = {}
    for n, pc in pieces.items():
        m = lc3d.vers_mesh(pc.forme, tol=0.03, ang=0.15)
        if A is not None and n in A.poses: m.apply_transform(A.poses[n])
        places[n] = (m, pc)
    return places


def _scalaires(d, garde=12):
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, (int, float, str)) and not isinstance(v, bool) and len(str(v)) < 60:
            out[k] = round(v, 3) if isinstance(v, float) else v
        if len(out) >= garde: break
    return out


def generer(dossier, photo=False):
    os.makedirs(os.path.join(dossier, "images"), exist_ok=True); os.makedirs(os.path.join(dossier, "modeles"), exist_ok=True)
    fiches = []
    for f in K.tout():
        n = f["num"]; fiche = {k: f.get(k) for k in ("num", "nom", "type", "description", "besoins", "fonction", "module", "version", "licence", "cotes_fixes", "cotes_ajustables")}
        fiche["version"] = fiche["version"] or 1
        if fiche.get("nom"): fiche["nom"] = fiche["nom"][0].upper() + fiche["nom"][1:]
        try:
            r = K.utiliser(n)
            if isinstance(r, dict):
                if not fiche.get("cotes_ajustables"): fiche["cotes_ajustables"] = _scalaires(r.get("cotes"))
                fiche["calcul"] = _scalaires(r.get("calcul"))
                if r.get("note") and not fiche.get("description"): fiche["description"] = r["note"]
        except Exception as e:
            fiche["calcul"] = {}
        ch = modele_vitrine(n)
        if ch:
            try:
                pl = scene(ch)
                sc = trimesh.Scene()
                for i, (nom, (m, pc)) in enumerate(pl.items()):
                    c = (0.72, 0.74, 0.77) if pc.role == "achetee" else COUL[i % len(COUL)]
                    m = m.copy(); m.visual = trimesh.visual.ColorVisuals(m, face_colors=np.tile(np.r_[np.array(c) * 255, 255].astype(np.uint8), (len(m.faces), 1)))
                    sc.add_geometry(m, node_name=nom)
                fiche["modele"] = f"modeles/lc{n:03d}.glb"; sc.export(os.path.join(dossier, fiche["modele"]))
                img = os.path.join(dossier, "images", f"lc{n:03d}.png")
                ok = False
                if photo:
                    ph = lc3d.rendu_photo({k: v[0] for k, v in pl.items()}, img, couleurs={k: COUL[i % len(COUL)] for i, k in enumerate(pl)},
                                          taille=(900, 675), echantillons=32, achetees=[k for k, v in pl.items() if v[1].role == "achetee"])
                    ok = bool(ph.get("ok"))
                if not ok:
                    im, _, _ = lc3d.rendre_vue([(m, (0.72, 0.74, 0.77) if pc.role == "achetee" else COUL[i % len(COUL)]) for i, (m, pc) in enumerate(pl.values())], "Iso avant", taille=700)
                    im.save(img)
                fiche["image"] = f"images/lc{n:03d}.png"
            except Exception as e:
                fiche["erreur_vitrine"] = f"{type(e).__name__}: {e}"
        fiches.append(fiche); print(n, fiche.get("nom"), "ok" if fiche.get("image") else fiche.get("erreur_vitrine", "sans vitrine"), flush=True)
    json.dump(fiches, open(os.path.join(dossier, "fiches.json"), "w"), ensure_ascii=False, indent=1)
    return fiches


if __name__ == "__main__":
    a = argparse.ArgumentParser(); a.add_argument("dossier"); a.add_argument("--photo", action="store_true"); x = a.parse_args()
    generer(x.dossier, x.photo)
