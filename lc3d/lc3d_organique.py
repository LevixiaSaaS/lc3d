"""LC3D — formes organiques : (1) sculpture paramétrique douce (SDF), (2) rendre FONCTIONNELLE une forme IA
(TRELLIS.2 / Hunyuan3D / Meshy / scan) : réparer, mettre à la taille, poser, puis ajouter de vraies fonctions
vérifiées — aimants, cavité secrète avec couvercle, passage de LED + fil, anneau de porte-clés, coupe pour le plateau.

Les formes sont des maillages (pas d'historique CAO); les FONCTIONS ajoutées, elles, sont calculées (cotes,
jeux, aimants du commerce) et vérifiées par LC3D comme le reste.
"""
import math, os
import numpy as np
import trimesh


# ------------------------------------------------------------------ (1) sculpture paramétrique (fonctions de distance)
def sculpter(recette, pas=0.6):
    """recette : fonction (sdf) -> forme sdf. Retourne un maillage trimesh. pas = finesse (mm)."""
    import sdf as S
    f = recette(S)
    pts = f.generate(step=pas, verbose=False)
    m = trimesh.Trimesh(*_triangles(pts)); m.merge_vertices(); m.fix_normals()
    return m


def _triangles(pts):
    pts = np.asarray(pts).reshape(-1, 3)
    v, inv = np.unique(np.round(pts, 5), axis=0, return_inverse=True)
    return v, inv.reshape(-1, 3)


def chien_stylise(taille=60.0, oreilles=1.0, museau=1.0, queue=1.0, ventre=1.0):
    """Exemple de sculpture paramétrique : un chien assis stylisé, cotes modifiables (facteurs 0,5-1,5)."""
    k = taille / 60.0

    def r(S):
        corps = S.ellipsoid((14 * k * ventre, 11 * k, 16 * k)).translate((0, 0, 16 * k))
        tete = S.sphere(10 * k).translate((0, 4 * k, 36 * k))
        mus = S.capsule((0, 8 * k, 34 * k), (0, (8 + 8 * museau) * k, 33 * k), 4.5 * k)
        nez = S.sphere(2.2 * k).translate((0, (8 + 8 * museau + 3) * k, 33.5 * k))
        # oreilles tombantes (chien) : partent du haut de la tête et retombent sur les côtés
        o1 = S.ellipsoid((2.2 * k, 4.5 * k, 7 * k * oreilles)).translate((10.5 * k, 2 * k, (40 - 4 * oreilles) * k))
        o2 = S.ellipsoid((2.2 * k, 4.5 * k, 7 * k * oreilles)).translate((-10.5 * k, 2 * k, (40 - 4 * oreilles) * k))
        pattes = [S.capsule((sx * 7 * k, 7 * k, 2 * k), (sx * 6 * k, 6 * k, 14 * k), 3.6 * k) for sx in (-1, 1)]
        cuisses = [S.ellipsoid((5 * k, 8 * k, 6 * k)).translate((sx * 10 * k, -2 * k, 6 * k)) for sx in (-1, 1)]
        q = S.capsule((0, -10 * k, 8 * k), (0, (-10 - 10 * queue) * k, (10 + 6 * queue) * k), 2.4 * k)
        f = corps | tete.k(5 * k) | mus.k(3 * k) | nez.k(1 * k) | o1.k(2 * k) | o2.k(2 * k) | q.k(2 * k)
        for p in pattes + cuisses: f = f | p.k(3 * k)
        sol = S.slab(z0=0)            # base plate pour imprimer sans support
        return f & sol
    return sculpter(r, pas=max(0.35, 0.6 * k))


# ------------------------------------------------------------------ (2) forme IA → produit fonctionnel
def preparer(chemin_ou_mesh, hauteur=None):
    """Charge (STL/GLB/OBJ), garde le plus gros morceau, répare, met à la hauteur voulue, pose à plat (z=0), centre."""
    m = trimesh.load(chemin_ou_mesh, force="mesh") if isinstance(chemin_ou_mesh, str) else chemin_ou_mesh.copy()
    parts = m.split(only_watertight=False)
    if len(parts) > 1: m = max(parts, key=lambda p: p.area)
    trimesh.repair.fill_holes(m); trimesh.repair.fix_normals(m)
    if hauteur: m.apply_scale(hauteur / m.extents[2])
    m.apply_translation([-m.bounds[:, 0].mean(), -m.bounds[:, 1].mean(), -m.bounds[0, 2]])
    return m


def _manifold(m):
    import manifold3d as M
    return M.Manifold(M.Mesh(vert_properties=np.asarray(m.vertices, np.float32), tri_verts=np.asarray(m.faces, np.uint32)))


def _trimesh(M):
    o = M.to_mesh(); return trimesh.Trimesh(np.asarray(o.vert_properties)[:, :3], np.asarray(o.tri_verts))


def _cyl(d, h, x, y, z):
    c = trimesh.creation.cylinder(radius=d / 2, height=h, sections=64); c.apply_translation([x, y, z + h / 2]); return c


def aimants_dessous(m, n=1, d=6.0, e=3.0, jeu=0.15):
    """Poches pour aimants néodyme Ø d × e dans le dessous (posé sur un frigo, une base métal, un socle aimanté)."""
    M = _manifold(m); sec = m.section(plane_origin=[0, 0, 0.3], plane_normal=[0, 0, 1])
    pts = [(0.0, 0.0)] if n == 1 else [(math.cos(2 * math.pi * i / n) * min(m.extents[:2]) * 0.22, math.sin(2 * math.pi * i / n) * min(m.extents[:2]) * 0.22) for i in range(n)]
    for x, y in pts:
        M = M - _manifold(_cyl(d + 2 * jeu, e + 0.2, x, y, -0.01))
    return _trimesh(M), dict(aimants=n, diametre=d, epaisseur=e, jeu=jeu, achat=f"{n} aimant(s) néodyme {d:g} × {e:g} mm (N52)",
                             note="Pause d'impression inutile : poches ouvertes par dessous, aimants collés (cyanoacrylate) ou pressés.")


def cavite_secrete(m, d=None, h=None, mur=2.0, jeu=0.3):
    """Cavité cylindrique dans le corps + bouchon vissé/emboîté par dessous (cachette, LED, poids)."""
    d = d or min(m.extents[:2]) * 0.45; h = h or m.extents[2] * 0.35
    M = _manifold(m) - _manifold(_cyl(d, h, 0, 0, -0.01))
    bouchon = _manifold(_cyl(d - 2 * jeu, 4.0, 0, 0, 0)) + _manifold(_cyl(d + 6, 1.6, 0, 0, -1.6))
    return _trimesh(M), _trimesh(bouchon), dict(diametre=d, profondeur=h, jeu=jeu, mur_min=mur,
                                               note="Bouchon emboîté à 0,3 mm de jeu (serré léger). Vérifier le mur restant avec lc3d check.")


def passage_led(m, d_led=5.5, d_fil=4.0):
    """Logement de LED au centre + canal pour le fil jusqu'au dessous (veilleuse, figurine lumineuse)."""
    zc = m.extents[2] * 0.55
    M = _manifold(m) - _manifold(_cyl(d_fil, zc, 0, 0, -0.01)) - _manifold(_cyl(d_led + 2, 8, 0, 0, zc - 4))
    return _trimesh(M), dict(led=f"LED Ø5 ou ruban COB dans Ø{d_led + 2:g}", canal=f"Ø{d_fil:g} mm jusqu'au dessous", note="Imprimer en blanc ou translucide pour la lueur.")


def anneau_porte_cles(m, d_int=4.0, ep=2.4):
    """Anneau en haut pour porte-clés / collier (orienté pour imprimer sans support)."""
    top = m.bounds[1, 2]
    t = trimesh.creation.torus(major_radius=d_int / 2 + ep / 2, minor_radius=ep / 2, major_sections=48, minor_sections=16)
    t.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
    # point le plus haut de la forme
    i = int(np.argmax(m.vertices[:, 2])); x, y = m.vertices[i, :2]
    t.apply_translation([x, y, top + d_int / 2 - ep * 0.3])
    return _trimesh(_manifold(m) + _manifold(t)), dict(anneau=f"intérieur Ø{d_int:g}, épaisseur {ep:g} mm")


def fonctionnaliser(source, hauteur, fonctions=("aimants",), sortie=None, **opts):
    """source : STL/GLB/OBJ de TRELLIS.2 / Hunyuan3D / Meshy / scan (ou un maillage).
    fonctions : parmi « aimants », « cavite », « led », « anneau », « socle ». Écrit les STL et retourne le rapport."""
    m = preparer(source, hauteur); pieces = {"figurine": m}; rapport = dict(hauteur=hauteur, taille=[round(x, 1) for x in m.extents])
    for f in fonctions:
        if f == "aimants": pieces["figurine"], rapport["aimants"] = aimants_dessous(pieces["figurine"], **opts.get("aimants", {}))
        elif f == "cavite": pieces["figurine"], pieces["bouchon"], rapport["cavite"] = cavite_secrete(pieces["figurine"], **opts.get("cavite", {}))
        elif f == "led": pieces["figurine"], rapport["led"] = passage_led(pieces["figurine"], **opts.get("led", {}))
        elif f == "anneau": pieces["figurine"], rapport["anneau"] = anneau_porte_cles(pieces["figurine"], **opts.get("anneau", {}))
    if sortie:
        os.makedirs(sortie, exist_ok=True)
        rapport["fichiers"] = {}
        for n, p in pieces.items():
            f = os.path.join(sortie, f"{n}.stl"); p.export(f); rapport["fichiers"][n] = f
    rapport["etanche"] = {n: bool(p.is_watertight) for n, p in pieces.items()}
    return pieces, rapport
