"""LC3D — reconstruire un STL (MakerWorld, Printables…) en VRAIE pièce modifiable (gestes paramétriques).

Méthode (pièces « 2,5D », la majorité des pièces imprimables) : on coupe le maillage en tranches le long de son
axe principal, on regroupe les tranches identiques en ÉTAGES (extrusions), on reconnaît les cercles (trous,
bossages) et les contours. Résultat : un modele.py LC3D écrit avec l'Atelier (« Étage 1 : contour extrudé de 12 mm »,
« Percer Ø5 »…) → modifiable, exportable en FreeCAD / Fusion avec l'histoire.
Fidélité mesurée : écart de volume et distance max entre l'original et la reconstruction.
Limite honnête : formes organiques (figurines, surfaces courbes libres) → non reconstruites en fonctions
(on garde le maillage); pentes/chanfreins inclinés → approximés en marches (avertissement).
"""
import math, os, json
import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union


def _sections(m, axe, n):
    lo, hi = m.bounds[0][axe], m.bounds[1][axe]
    zs = np.linspace(lo, hi, n + 2)[1:-1]
    normal = np.eye(3)[axe]
    out = []
    for z in zs:
        s = m.section(plane_origin=normal * z, plane_normal=normal)
        if s is None: out.append((z, Polygon())); continue
        garde = [i for i in range(3) if i != axe]
        forme = Polygon()
        for boucle in s.discrete:          # remplissage pair-impair : les boucles intérieures font des trous
            if len(boucle) < 4: continue
            P = Polygon(boucle[:, garde]).buffer(0)
            if not P.is_empty: forme = forme.symmetric_difference(P)
        out.append((z, forme.buffer(0)))
    return out, lo, hi


def _repere(axe):
    """Matrice 4×4 qui ramène le plan de coupe en 2D sans rotation inutile."""
    M = np.eye(4)
    if axe == 0: M[:3, :3] = [[0, 1, 0], [0, 0, 1], [1, 0, 0]]
    elif axe == 1: M[:3, :3] = [[1, 0, 0], [0, 0, 1], [0, 1, 0]]
    return np.linalg.inv(M)


def _pareil(a, b, tol):
    if a.is_empty and b.is_empty: return True
    if a.is_empty or b.is_empty: return False
    return a.symmetric_difference(b).area <= tol * max(a.area, b.area, 1e-9)


def _cercle(ring, tol=0.02):
    """Le contour est-il un cercle ? → (cx, cy, d) sinon None."""
    p = np.asarray(ring.coords)[:-1]
    if len(p) < 8: return None
    c = p.mean(0); r = np.linalg.norm(p - c, axis=1)
    if r.std() / r.mean() < tol: return (float(c[0]), float(c[1]), float(2 * r.mean()))
    return None


def reconstruire(stl, sortie_py, nom=None, tranches=120, tol=0.01):
    m = trimesh.load(stl, force="mesh")
    nom = nom or os.path.splitext(os.path.basename(stl))[0]
    # axe : celui où les sections changent le moins (le plus « extrudé »)
    meilleur = None
    for axe in (2, 0, 1):
        secs, lo, hi = _sections(m, axe, 40)
        changements = sum(not _pareil(secs[i][1], secs[i + 1][1], 0.02) for i in range(len(secs) - 1))
        if meilleur is None or changements < meilleur[0]: meilleur = (changements, axe)
    axe = meilleur[1]
    secs, lo, hi = _sections(m, axe, tranches)
    pas = (hi - lo) / (tranches + 1)
    # étages : tranches consécutives identiques
    etages = []
    for z, poly in secs:
        if etages and _pareil(etages[-1]["poly"], poly, tol): etages[-1]["z1"] = z
        else: etages.append(dict(z0=z, z1=z, poly=poly))
    for i, e in enumerate(etages):
        e["bas"] = lo if i == 0 else (etages[i - 1]["z1"] + e["z0"]) / 2
        e["haut"] = hi if i == len(etages) - 1 else (e["z1"] + etages[i + 1]["z0"]) / 2
    etages = [e for e in etages if not e["poly"].is_empty and e["haut"] - e["bas"] > 0.05]
    marches = sum(1 for e in etages if e["haut"] - e["bas"] < 3 * pas + 1e-6)
    # écrire le modèle LC3D (gestes nommés)
    L = [f'"""Reconstruit par LC3D depuis {os.path.basename(stl)} — {len(etages)} étage(s), axe {"XYZ"[axe]}."""',
         "import cadquery as cq", "from lc3d import Piece, Assemblage, Atelier", "",
         "PARAMS = dict(" + ", ".join(f"h{i + 1}={e['haut'] - e['bas']:.3f}" for i, e in enumerate(etages)) + ")", "", "",
         "def build(p):", f'    a = Atelier("{nom}")', "    z = %.3f" % etages[0]["bas"] if etages else "    z = 0"]
    trous_total = 0
    for i, e in enumerate(etages, 1):
        polys = list(e["poly"].geoms) if isinstance(e["poly"], MultiPolygon) else [e["poly"]]
        for j, P in enumerate(polys):
            P = P.simplify(0.02, preserve_topology=True)
            c = _cercle(P.exterior)
            if c:
                L.append(f'    a.ajouter(cq.Workplane("XY").center({c[0]:.3f}, {c[1]:.3f}).circle({c[2] / 2:.3f}).extrude(p["h{i}"]).translate((0, 0, z)), "Étage {i} : cylindre Ø{c[2]:.2f} de {{:.1f}} mm".format(p["h{i}"]))')
            else:
                pts = ", ".join(f"({x:.3f}, {y:.3f})" for x, y in list(P.exterior.coords)[:-1])
                L.append(f'    a.ajouter(cq.Workplane("XY").polyline([{pts}]).close().extrude(p["h{i}"]).translate((0, 0, z)), "Étage {i} : contour extrudé de {{:.1f}} mm".format(p["h{i}"]))')
            for k, ring in enumerate(P.interiors):
                cc = _cercle(ring)
                if cc:
                    L.append(f'    a.trou({cc[2]:.3f}, p["h{i}"] + 0.02, pos=({cc[0]:.3f}, {cc[1]:.3f}, z - 0.01), axe="Z", titre="Percer Ø{cc[2]:.2f}")'); trous_total += 1
                else:
                    pts = ", ".join(f"({x:.3f}, {y:.3f})" for x, y in list(ring.coords)[:-1])
                    L.append(f'    a.couper(cq.Workplane("XY").polyline([{pts}]).close().extrude(p["h{i}"] + 0.02).translate((0, 0, z - 0.01)), "Évider (étage {i})")')
        L.append(f'    z = z + p["h{i}"]')
    rot = {2: "", 0: '.rotate((0, 0, 0), (0, 1, 0), 90).rotate((0, 0, 0), (1, 0, 0), 90)', 1: '.rotate((0, 0, 0), (1, 0, 0), -90)'}[axe]
    L += [f'    return {{"{nom}": Piece("{nom}", a.forme{rot})}}', "", "", "def assembly(p, pieces):", "    A = Assemblage(); A.place(\"%s\"); return A" % nom, ""]
    open(sortie_py, "w").write("\n".join(L))
    # fidélité
    fid = fidelite(sortie_py, m, nom)
    return dict(modele=sortie_py, axe="XYZ"[axe], etages=len(etages), trous=trous_total, marches_suspectes=marches,
                **fid, note=("Pentes ou courbes en hauteur approximées en marches : vérifier." if marches > 2 else "Pièce 2,5D : reconstruction directe."))


def fidelite(modele_py, original, nom):
    import importlib.util, sys
    import lc3d
    spec = importlib.util.spec_from_file_location("reco", modele_py); mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("lc3d", lc3d); spec.loader.exec_module(mod)
    pc = mod.build(mod.PARAMS)[nom]
    r = lc3d.vers_mesh(pc.forme)
    v0, v1 = original.volume, r.volume
    pts = original.sample(4000)
    try:
        d = np.abs(trimesh.proximity.signed_distance(r, pts))
        dmax, d99 = float(d.max()), float(np.percentile(d, 99))
    except Exception:
        dmax = d99 = None
    return dict(volume_original=round(v0, 1), volume_reconstruit=round(v1, 1), ecart_volume_pct=round(100 * abs(v1 - v0) / max(v0, 1e-9), 2),
                distance_max_mm=None if dmax is None else round(dmax, 3), distance_99pct_mm=None if d99 is None else round(d99, 3))


if __name__ == "__main__":
    import sys
    print(json.dumps(reconstruire(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "reconstruit.py"), ensure_ascii=False, indent=1))
