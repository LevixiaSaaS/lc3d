"""LC3D — résistance d'une pièce sous charge (éléments finis, gratuit : gmsh + scikit-fem).

r = resistance(forme, fixe=((x0,y0,z0),(x1,y1,z1)), charge=((...),(...)), force=(0, 0, -50), materiau="PETG")
- fixe   : boîte (mm) — les faces de la pièce dont le centre est dans cette boîte sont bloquées (vissées, collées, tenues).
- charge : boîte — les faces où la force est appliquée (répartie).
- force  : newtons (vecteur). 10 N ≈ 1 kg.
- axe_couches : direction d'empilement des couches à l'impression (dans le repère de la pièce). L'impression est
  ~2 fois plus faible ENTRE les couches : on vérifie aussi la traction dans cette direction.
Retourne : contrainte max, traction entre couches, déformation max, facteur de sécurité, verdict, image colorée.
Limites honnêtes : matériau linéaire élastique, remplissage supposé plein (role structure); une pièce à 20 % de
remplissage est plus faible que le calcul. Les coins vifs sur les appuis donnent des pics : on prend le 99e centile.
"""
import os, tempfile, math
import numpy as np

# E (MPa), nu, limite (MPa) du filament en bloc ; facteurs FDM (dans le plan / entre couches)
MATERIAUX_FEM = {
    "PLA":  dict(E=3500, nu=0.36, sigma=50, plan=0.80, couches=0.55),
    "PETG": dict(E=2000, nu=0.38, sigma=50, plan=0.80, couches=0.50),
    "ABS":  dict(E=2200, nu=0.35, sigma=40, plan=0.80, couches=0.45),
    "ASA":  dict(E=2200, nu=0.35, sigma=45, plan=0.80, couches=0.45),
    "PA":   dict(E=1800, nu=0.39, sigma=55, plan=0.80, couches=0.55),
    "PC":   dict(E=2300, nu=0.37, sigma=60, plan=0.80, couches=0.50),
    "TPU":  dict(E=26,   nu=0.45, sigma=35, plan=0.90, couches=0.70),
}
SECURITE_VISEE = 2.0


def _vers_step(forme):
    import cadquery as cq
    if isinstance(forme, cq.Workplane):
        forme = forme.val() if len(forme.vals()) == 1 else cq.Compound.makeCompound(forme.vals())
    f = tempfile.NamedTemporaryFile(suffix=".step", delete=False).name
    cq.exporters.export(forme, f)
    return f


def _mailler(step, taille):
    import gmsh
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.model.add("p"); gmsh.merge(step)
        gmsh.option.setNumber("Mesh.MeshSizeMax", taille); gmsh.option.setNumber("Mesh.MeshSizeMin", taille * 0.3)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.model.mesh.generate(3)
        tags, xyz, _ = gmsh.model.mesh.getNodes()
        p = xyz.reshape(-1, 3); idx = {t: i for i, t in enumerate(tags)}
        et, _, en = gmsh.model.mesh.getElements(3)
        t = None
        for typ, nodes in zip(et, en):
            if typ == 4:   # tétraèdre linéaire
                t = np.vectorize(idx.get)(nodes.reshape(-1, 4))
        if t is None: raise RuntimeError("maillage 3D impossible")
        utilises = np.unique(t); ren = -np.ones(len(p), int); ren[utilises] = np.arange(len(utilises))
        return p[utilises], ren[t]
    finally:
        gmsh.finalize()


def _dans(c, boite, marge=0.05):
    lo, hi = np.asarray(boite[0], float) - marge, np.asarray(boite[1], float) + marge
    return np.all((c >= lo) & (c <= hi), axis=1)


def resistance(forme, fixe, charge, force, materiau="PETG", axe_couches=(0, 0, 1), taille=None, image=None, titre="Résistance"):
    from skfem import MeshTet, ElementTetP2, ElementVector, Basis, FacetBasis, asm, condense, solve, LinearForm
    from skfem.models.elasticity import linear_elasticity, lame_parameters
    from skfem.helpers import sym_grad, trace, eye
    M = MATERIAUX_FEM.get(materiau.split()[0].upper() if materiau.split()[0].upper() in MATERIAUX_FEM else "PETG")
    step = _vers_step(forme)
    try:
        import cadquery as cq
        bb = cq.importers.importStep(step).val().BoundingBox()
        diag = math.sqrt(bb.xlen ** 2 + bb.ylen ** 2 + bb.zlen ** 2)
        h = taille or max(0.8, min(4.0, diag / 30))
        p, t = _mailler(step, h)
    finally:
        os.unlink(step)
    m = MeshTet(p.T.copy(), t.T.copy())
    e = ElementVector(ElementTetP2()); ib = Basis(m, e)
    lam, mu = lame_parameters(M["E"], M["nu"])
    K = asm(linear_elasticity(lam, mu), ib)
    bf = m.boundary_facets(); cf = m.p[:, m.facets[:, bf]].mean(axis=1).T
    f_fixe = bf[_dans(cf, fixe)]; f_charge = bf[_dans(cf, charge)]
    if not len(f_fixe): raise ValueError("aucune face dans la boîte « fixe »")
    if not len(f_charge): raise ValueError("aucune face dans la boîte « charge »")
    fb = FacetBasis(m, e, facets=f_charge)
    P0, P1, P2 = (m.p[:, m.facets[k, f_charge]].T for k in range(3))
    aire = float(0.5 * np.linalg.norm(np.cross(P1 - P0, P2 - P0), axis=1).sum())
    tr = np.asarray(force, float) / aire

    @LinearForm
    def charge_f(v, w):
        return tr[0] * v[0] + tr[1] * v[1] + tr[2] * v[2]
    F = asm(charge_f, fb)
    D = ib.get_dofs(facets=f_fixe).all()
    u = solve(*condense(K, F, D=D))
    # contraintes aux points d'intégration
    U = ib.interpolate(u); E_ = sym_grad(U)
    S = 2 * mu * E_ + lam * eye(trace(E_), 3)
    sxx, syy, szz = S[0, 0], S[1, 1], S[2, 2]; sxy, syz, sxz = S[0, 1], S[1, 2], S[0, 2]
    vm = np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * (sxy ** 2 + syz ** 2 + sxz ** 2))
    n = np.asarray(axe_couches, float); n /= np.linalg.norm(n)
    sn = sum(n[i] * n[j] * S[i, j] for i in range(3) for j in range(3))       # traction perpendiculaire aux couches
    vm_el = vm.max(axis=1); sn_el = np.clip(sn, 0, None).max(axis=1)
    # les éléments collés aux appuis ont des pics artificiels (encastrement parfait) : on les écarte du maximum
    noeuds_fixes = np.unique(m.facets[:, f_fixe]); touche = np.isin(m.t, noeuds_fixes).any(axis=0)
    garde = np.ones_like(touche)   # (garder tout : écarter les appuis sous-estime la contrainte réelle à l'encastrement)
    vm99 = float(np.percentile(vm_el[garde], 99.5)); sn99 = float(np.percentile(sn_el[garde], 99.5))
    dep = u[ib.nodal_dofs].T; dep_max = float(np.linalg.norm(dep, axis=1).max())
    lim_plan, lim_couches = M["sigma"] * M["plan"], M["sigma"] * M["couches"]
    fs = min(lim_plan / max(vm99, 1e-9), lim_couches / max(sn99, 1e-9))
    pire = "entre les couches" if lim_couches / max(sn99, 1e-9) < lim_plan / max(vm99, 1e-9) else "dans la matière"
    statut = "✅" if fs >= SECURITE_VISEE else ("⚠️" if fs >= 1.2 else "❌")
    ratio_el = np.where(garde, np.maximum(vm_el / lim_plan, sn_el / lim_couches), 0); el_pire = int(np.argmax(ratio_el))
    lieu = m.p[:, m.t[:, el_pire]].mean(axis=1).round(1).tolist()
    R = dict(statut=statut, facteur_securite=round(fs, 2), contrainte_max_MPa=round(vm99, 2), traction_couches_MPa=round(sn99, 2),
             deformation_max_mm=round(dep_max, 3), limite_plan_MPa=round(lim_plan, 1), limite_couches_MPa=round(lim_couches, 1),
             point_faible=lieu, casse_d_abord=pire, force_N=list(map(float, force)), materiau=materiau,
             elements=int(m.t.shape[1]), taille_maille_mm=round(h, 2),
             note="matériau plein (role structure); à 20 % de remplissage la pièce est plus faible que ce calcul")
    if image:
        R["image"] = _image(m, vm_el, sn_el, lim_plan, lim_couches, image, titre, R)
    return R


def _image(m, vm_el, sn_el, lp, lc, chemin, titre, R):
    import trimesh
    from PIL import Image, ImageDraw
    from lc3d import rendre_vue, _fnt
    bf = m.boundary_facets()
    tri = m.facets[:, bf].T
    el = m.f2t[0, bf]
    ratio = np.maximum(vm_el[el] / lp, sn_el[el] / lc)       # 1 = à la limite de rupture
    mesh = trimesh.Trimesh(m.p.T, tri, process=False); mesh.fix_normals()
    # bleu (0) → vert → jaune (0,5 = facteur 2) → rouge (≥ 1)
    x = np.clip(ratio, 0, 1)
    col = np.stack([np.clip(2 * x, 0, 1), np.clip(1.6 - 1.6 * abs(x - 0.45) * 2, 0, 1) * 0.9, np.clip(1 - 2.2 * x, 0, 1)], 1)
    col[x >= 0.999] = (0.85, 0.05, 0.05)
    vues = []
    for v in ("Iso avant", "Iso dessous"):
        im, _, _ = rendre_vue([(mesh, col)], v, taille=520)
        vues.append(im)
    W = 1040; c = Image.new("RGB", (W, 640), "white"); c.paste(vues[0], (0, 70)); c.paste(vues[1], (520, 70))
    d = ImageDraw.Draw(c)
    d.text((16, 12), f"{titre} — {dict(zip('✅⚠❌', ('SOLIDE', 'LIMITE', 'VA CASSER'))).get(R['statut'][0], '')} · facteur de sécurité {R['facteur_securite']} (visé ≥ {SECURITE_VISEE})", fill=(20, 20, 20), font=_fnt(22))
    d.text((16, 42), f"Force {R['force_N']} N · contrainte {R['contrainte_max_MPa']} MPa · entre couches {R['traction_couches_MPa']} MPa · déformation {R['deformation_max_mm']} mm · {R['materiau']}",
           fill=(70, 70, 70), font=_fnt(15))
    for i in range(300):
        x = i / 299; cc = (int(255 * min(1, 2 * x)), int(255 * max(0, 1.6 - 3.2 * abs(x - 0.45)) * 0.9), int(255 * max(0, 1 - 2.2 * x)))
        d.line([(370 + i, 604), (370 + i, 620)], fill=cc)
    d.text((300, 600), "solide", fill=(60, 60, 60), font=_fnt(14)); d.text((680, 600), "casse", fill=(60, 60, 60), font=_fnt(14))
    c.save(chemin)
    return chemin


if __name__ == "__main__":
    # essai : poutre 60 × 10 × 6 mm encastrée à gauche, 20 N vers le bas au bout
    import cadquery as cq
    poutre = cq.Workplane("XY").box(60, 10, 6).translate((30, 0, 3))
    r = resistance(poutre, fixe=((-1, -6, -1), (0.2, 6, 7)), charge=((59.8, -6, -1), (61, 6, 7)), force=(0, 0, -20), image="essai_resistance.png")
    print(r)
    # théorie (poutre encastrée) : sigma = 6 F L / (b h²) = 6·20·60/(10·36) = 20 MPa ; flèche = 4 F L³ / (E b h³) = 4·20·216000/(2000·10·216) = 4,0 mm
    print("théorie : 20 MPa, flèche 4,0 mm")
