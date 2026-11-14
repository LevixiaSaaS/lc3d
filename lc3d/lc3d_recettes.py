"""LC3D — RECETTES : une demande courante → un modèle complet fait de composants VALIDÉS du catalogue.
On n'improvise pas : une recette ne contient que des composants qui passent le run complet (0 ❌) dans toute la plage
de paramètres testée (tests/recettes). Usage dans un modèle :

    from lc3d_recettes import etui_visse
    PARAMS, build, assembly, COULEURS = etui_visse(objet_d=20, objet_l=100)

Chaque recette : (PARAMS, build, assembly, COULEURS). Les cotes données sont celles de l'OBJET à ranger (ou de
l'intérieur voulu) ; la recette ajoute les jeux, murs, filets et orientation d'impression d'elle-même.
"""
import math
import numpy as np
import trimesh
import cadquery as cq
import lc3d
from lc3d import Piece, Assemblage, Atelier
from composants_lc3d import couvercle_filete_5
import composants_lc3d as C1
import composants_lot_a as KA
import composants_lot_b as KB
import composants_lot_c as KC
import composants_lot_d as KD

RECETTES = {}


def recette(f):
    RECETTES[f.__name__] = f
    return f


def _plage(nom, v, lo, hi, unite="mm"):
    if not (lo <= v <= hi):
        raise ValueError(f"{nom} = {v:g} {unite} hors de la plage validée de la recette ({lo:g} à {hi:g} {unite}). "
                         f"Hors plage : modèle sur mesure (méthode § 4) + run complet.")


# ------------------------------------------------------------------ étui / tube vissé (cigare, stylo, pinceaux, clés USB…)
@recette
def etui_visse(objet_d=20.0, objet_l=100.0, jeu_d=1.0, jeu_l=2.0, fond=2.0, pas=7.0, materiau="PETG", couleurs=("brun", "doré")):
    """Tube fermé par un bouchon vissé (composant n° 5 v3 : filet 45° pas 7, profondeur 1,2, sommet 0,85, entrée chanfreinée, ≈ 1,5 tour de prise RÉELLE mesurée). Objet Ø objet_d × objet_l.
    Prise radiale 0,9 mm (prof 1,2 − jeu 0,3) : la prise par défaut du n° 5 (0,5 mm) a été jugée trop faible en revue indépendante.
    Tube debout, bouchon retourné : imprimables sans support. Corps au Ø du bouchon (à ras une fois vissé)."""
    _plage("objet_d", objet_d, 6, 80); _plage("objet_l", objet_l, 30, 220)
    d_int = objet_d + 2 * jeu_d
    h_filet = 22.0           # 22 mm à pas 7 : 1,5 tour de prise réelle (18 mm : 0,9 tour seulement, mesuré)
    prof = 1.2
    if 2 * prof + 0.85 > 0.47 * pas: raise ValueError(f"pas {pas:g} trop petit pour un filet de profondeur {prof:g} (base 2·prof + 0,85 ≤ 0,47·pas)")
    P = dict(d_int=d_int, fond=fond, h_filet=h_filet, pas=pas, prof=prof, h_tube=fond + objet_l + jeu_l)

    def _c5(p):
        return couvercle_filete_5(diametre=p["d_int"] + 4.0, pas=p["pas"], hauteur_filet=p["h_filet"], paroi=2.0, plafond=2.0, prof=p["prof"], entree=True, sommet=0.85)

    def build(p):
        C = _c5(p); h, hf = p["h_tube"], p["h_filet"]
        d_corps = round(C["couvercle"].val().BoundingBox().xlen, 1)
        t = Atelier("tube")
        t.cylindre(d_corps, h - hf, pos=(0, 0, 0), titre=f"Corps du tube Ø{d_corps:g}")
        t.ajouter(C["col"].translate((0, 0, h - hf)), titre="Col fileté (composant n° 5)")
        t.trou(p["d_int"], h - p["fond"], pos=(0, 0, p["fond"]), titre=f"Logement Ø{p['d_int']:g}")
        t.chanfreiner("<Z", 0.6, titre="Chanfrein du pied (patte d'éléphant)")
        c = Atelier("bouchon")
        c.ajouter(C["couvercle"], titre="Bouchon fileté (composant n° 5)")
        c.chanfreiner(">Z", 0.8, titre="Chanfrein du dessus")
        return {"tube": Piece("tube", t.forme, materiau=materiau, orientation="telle"),
                "bouchon": Piece("bouchon", c.forme, materiau=materiau, orientation=((1, 0, 0), 180))}

    def assembly(p, pieces):
        A = Assemblage()
        A.place("tube"); A.place("bouchon", z=p["h_tube"] - p["h_filet"])
        A.mouvement("bouchon", "vissage", axe=(0, 0, 1), de=_c5(p)["cotes"]["tours_couvercle"] * 360, a=0, pas_filet=p["pas"])
        return A

    return P, build, assembly, {"tube": couleurs[0], "bouchon": couleurs[1]}


# ------------------------------------------------------------------ pot vissé (épices, vis, bijoux…) = même mécanique, large et bas
@recette
def pot_visse(d_int=50.0, h_int=40.0, materiau="PETG", couleurs=("blanc", "gris")):
    """Pot à couvercle vissé (n° 5). d_int, h_int = intérieur utile."""
    _plage("d_int", d_int, 20, 140); _plage("h_int", h_int, 32, 150)
    return etui_visse(objet_d=d_int - 2.0, objet_l=h_int - 2.0, materiau=materiau, couleurs=couleurs)


# ================================================================== outils communs des recettes
def _b(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))


# n° 17 : la tenue par friction dépend de la hauteur (le mur plie comme un porte-à-faux depuis le fond : raideur ∝ mur³ / H²).
# La recette choisit mur et serrage pour que le couvercle tienne seul et s'ouvre au bec (calcul du composant n° 17, mêmes formules).
_COMBOS_17 = [(2.0, 0.2), (2.0, 0.1), (2.0, 0.3), (2.5, 0.2), (2.5, 0.3), (3.0, 0.2), (3.0, 0.3)]


def _tenue_17(H_ext, mur, serrage, levre_h=6.0, n_cotes=6, materiau="PETG"):
    M = lc3d.MATERIAUX[materiau]
    k = M["E"] * (2 * H_ext / 3) * mur ** 3 / (4 * (H_ext - levre_h / 2) ** 3)
    return M["mu"] * k * (serrage + 0.13) * n_cotes


def _choix_17(H_ext, materiau="PETG"):
    for lo, hi in ((2.0, 12.0), (1.0, 15.0)):
        for mur, s in _COMBOS_17:
            if lo <= _tenue_17(H_ext, mur, s, materiau=materiau) <= hi:
                return mur, s
    raise ValueError(f"hauteur extérieure {H_ext:g} mm : aucun mur (2-3 mm) ni serrage (0,1-0,3) ne donne une tenue de 1 à 15 N "
                     "au couvercle à emboîter (n° 17). Hors plage : modèle sur mesure.")


def _assemblage_17(A, p, F, perdues=0):
    """Couvercle n° 17 : côtes d'écrasement = AJUSTEMENT SERRÉ voulu (A.serrage), pas un clip (un clip doit retomber dans sa fenêtre)."""
    A.serrage("couvercle", "boite", p["serrage"])
    A.inserer("couvercle", depuis=(0, 0, 40))
    A.retenue("couvercle", (1, 0, 0), 2); A.retenue("couvercle", (0, 1, 0), 2)       # la lèvre empêche de glisser de côté
    Fa = F * (6 - perdues) / 6
    A.regle("tenue du couvercle (friction)", lambda q, F=Fa: 1.0 <= F <= 15.0,
            f"force de retrait estimée {Fa:.1f} N (calcul n° 17, mur {p['mur']:g}, serrage {p['serrage']:g}"
            + (f", {perdues} côte(s) en face d'une encoche ne serrent pas" if perdues else "") + ") : tient seul, s'ouvre avec le bec")
    A.regle("jeu de la lèvre hors côtes", "jeu_levre >= 0.3", "seules les côtes serrent, pas toute la lèvre")
    return A


def _penetration_zone(mob, fixe, lo, hi, depuis_z, pas=0.25, n=40000):
    """Pénétration max (mm, même mesure que LC3D : distance à la surface la plus proche) entre `mob` qui descend
    tout droit de depuis_z jusqu'à sa pose et `fixe`, en ne regardant QUE la zone [lo, hi] (repère assemblé).
    Sert à mesurer séparément deux clips d'une même paire de pièces (LC3D, lui, ne donne que le pire des deux)."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    pm, _ = trimesh.sample.sample_surface(mob, n, seed=3); pm = np.vstack([pm, mob.vertices])
    pf, _ = trimesh.sample.sample_surface(fixe, n, seed=5); pf = np.vstack([pf, fixe.vertices])
    dans = lambda q: np.all((q >= lo) & (q <= hi), axis=1)
    pf = pf[dans(pf)]
    best = 0.0
    for k in range(int(round(depuis_z / pas)) + 1):
        dz = np.array([0.0, 0.0, k * pas])
        q = pm + dz; q = q[dans(q)]
        if len(q):
            ins = fixe.contains(q)
            if ins.any(): best = max(best, float(trimesh.proximity.closest_point(fixe, q[ins])[1].max()))
        if len(pf):
            r = pf - dz; ins = mob.contains(r)
            if ins.any(): best = max(best, float(trimesh.proximity.closest_point(mob, r[ins])[1].max()))
    return best


# ------------------------------------------------------------------ boîte + couvercle à emboîter (n° 17)
@recette
def boite_couvercle_pression(L=80.0, l=60.0, H=40.0, materiau="PETG", couleurs=("blanc", "gris")):
    """Boîte rectangulaire + couvercle à emboîter (n° 17 : lèvre, 6 côtes de serrage, bec pour ouvrir).
    L × l × H = intérieur utile (H mesurée sous la lèvre du couvercle, qui descend de 6 mm dans la boîte).
    Mur (2 / 2,5 / 3) et serrage (0,1 / 0,2 / 0,3) choisis par le calcul de tenue du n° 17 (1 à 15 N, viser 2-12 N).
    Boîte debout, couvercle à l'envers (plaque sur le plateau)."""
    _plage("L", L, 20, 200); _plage("l", l, 20, 200); _plage("H", H, 8, 75)
    fond, levre_h = 2.0, 6.0
    He = fond + H + levre_h
    mur, serrage = _choix_17(He, materiau)
    P = dict(L=L + 2 * mur, l=l + 2 * mur, H=He, mur=mur, fond=fond, levre_h=levre_h, serrage=serrage, jeu_levre=0.4)

    def _c17(p):
        return KB.couvercle_pression_17(L=p["L"], l=p["l"], H=p["H"], mur=p["mur"], fond=p["fond"], levre_h=p["levre_h"],
                                        serrage=p["serrage"], jeu_levre=p["jeu_levre"], materiau=materiau)

    def build(p):
        c = _c17(p)
        b = Atelier("boite"); b.ajouter(c["boite"], f"Boîte {p['L']:g} × {p['l']:g} × {p['H']:g}, mur {p['mur']:g} (composant n° 17)")
        k = Atelier("couvercle"); k.ajouter(c["couvercle"], f"Couvercle : lèvre + 6 côtes de serrage {p['serrage']:g} + bec (composant n° 17)")
        return {"boite": Piece("boite", b.forme, materiau=materiau, orientation="telle"),
                "couvercle": Piece("couvercle", k.forme, materiau=materiau, orientation=((1, 0, 0), 180))}

    def assembly(p, pieces):
        A = Assemblage(); A.place("boite"); A.place("couvercle")
        return _assemblage_17(A, p, _c17(p)["calcul"]["force_retrait_N"])

    return P, build, assembly, {"boite": couleurs[0], "couvercle": couleurs[1]}


# ------------------------------------------------------------------ pot rond + couvercle clipsé tout le tour (n° 20)
@recette
def boite_ronde_clips(D=60.0, H=40.0, materiau="PETG", couleurs=("blanc", "gris")):
    """Pot rond + couvercle qui clipse tout le tour (n° 20, retenue 45° : s'enlève en tirant le bec). D, H = intérieur utile.
    Accroche DESSINÉE 1,2 mm : LC3D mesure la pénétration à la surface la plus proche, et les plats de 0,4 mm de la lèvre et du
    bourrelet du n° 20 font lire ≈ 0,92 pour 1,0 dessiné (❌ « accroche < 1 mm ») — 1,2 dessiné se mesure ≈ 1,07.
    Nombre de doigts ajusté au Ø (doigts de ≈ 12 mm de large : même force par doigt que le composant validé)."""
    _plage("D", D, 20, 150); _plage("H", H, 14, 150)
    # doigts de 1,6 (pas 1,5) : à 1,5 pile, les facettes d'un grand Ø les mesurent 1,47 (⚠️ < 1,5)
    mur, fond, acc, jeu, h, Ld, fente = 2.0, 2.0, 1.2, 0.3, 1.6, 14.0, 1.5
    De = D + 2 * mur
    Ri = De / 2 + acc + 2 * jeu
    nb = int(max(8, round(2 * math.pi * (Ri + h / 2) / (12.0 + fente))))
    P = dict(D=De, H=H + fond, mur=mur, fond=fond, accroche=acc, jeu_bourrelet=jeu, h=h, L=Ld, nb_fentes=nb, fente=fente)

    def _c20(p):
        return KB.clip_annulaire_20(D=p["D"], H=p["H"], mur=p["mur"], fond=p["fond"], accroche=p["accroche"], jeu=p["jeu_bourrelet"], h=p["h"],
                                    L=p["L"], nb_fentes=p["nb_fentes"], fente=p["fente"], retenue=45.0, materiau=materiau)

    def build(p):
        c = _c20(p)
        a = Atelier("pot"); a.ajouter(c["pot"], f"Pot Ø{p['D']:g} × {p['H']:g} + bourrelet (composant n° 20)")
        k = Atelier("couvercle"); k.ajouter(c["couvercle"], f"Couvercle à {p['nb_fentes']} doigts clipsés + bec (composant n° 20)")
        return {"pot": Piece("pot", a.forme, materiau=materiau, orientation="telle"),
                "couvercle": Piece("couvercle", k.forme, materiau=materiau, role="structure", orientation=((1, 0, 0), 180))}

    def assembly(p, pieces):
        c = _c20(p); k = c["cotes"]
        A = Assemblage(); A.place("pot"); A.place("couvercle")
        A.clip("couvercle", "pot", accroche=p["accroche"], L=p["L"], h=p["h"], w=k["w"], alpha_in=30, alpha_out=45)
        # plats de la lèvre et du bourrelet alignés (engagement maximal) à dz = jeu + saillie/tan(45°) + 0,4 au-dessus de la pose :
        # le chemin de montage passe exactement par ce point (sinon le pas de 2 mm du mode rapide le saute et sous-mesure l'accroche)
        dz = k["jeu"] + k["saillie_bourrelet"] + 0.4
        A.inserer("couvercle", depuis=(0, 0, 8 * dz), pas=8 if lc3d.RAPIDE["actif"] else 40)
        A.retenue("couvercle", (0, 0, 1), 5)
        A.mouvement("couvercle", "rotation", pivot=(0, 0, 0), axe=(0, 0, 1), de=0, a=40, pas_deg=2, titre="couvercle qui tourne sur le pot")
        return A

    return P, build, assembly, {"pot": couleurs[0], "couvercle": couleurs[1]}


# ------------------------------------------------------------------ boîte à fermeture baïonnette (n° 16)
def _descente_libre(md, mb, angle, hauteur, pas=0.5):
    """Bouchon tourné de -angle (ergots face aux fentes), monté de `hauteur` puis descendu : pire chevauchement (mm³, hauteur)."""
    R = trimesh.transformations.rotation_matrix(math.radians(-angle), (0, 0, 1))
    pire = (0.0, None)
    for k in range(int(hauteur / pas) + 1):
        m = mb.copy(); m.apply_transform(trimesh.transformations.translation_matrix((0, 0, k * pas)) @ R)
        v = lc3d._vol_inter(m, md)[0]
        if not v == v: return (float("nan"), k * pas)
        if v > pire[0]: pire = (v, k * pas)
    return pire


@recette
def boite_baionnette(D=40.0, H=40.0, materiau="PETG", couleurs=("blanc", "gris")):
    """Boîte ronde à fermeture baïonnette (n° 16) : on enfonce le bouchon, on tourne, clic du cran.
    Le bouchon du n° 16 est un manchon qui descend jusqu'au fond (ergots en bas) : D = Ø intérieur utile DANS le manchon,
    H = hauteur intérieure. L'angle de rotation est agrandi pour les petits Ø (sinon le cran mange toute la fenêtre)."""
    _plage("D", D, 24, 140); _plage("H", H, 20, 150)       # D < 24 : la fenêtre dépasse 95° sur 120° (resserré après essais)
    # accroche 1,1 (pas 1,0) : plat du cran de 1 mm → LC3D mesure 0,98 pour 1,0 dessiné (❌ « < 1 mm »).
    # mur : au bout du cran il reste mur − 2·accroche de matière (1,0 mm avec les défauts du n° 16 → ⚠️ mur mince); ici 1,6 mm.
    lh, fond, lug_l, Lg = 1.6, 2.0, 4.0, 14.0
    acc = 1.1 if D <= 70 else 1.25     # grand Ø : la mesure LC3D de l'accroche lit jusqu'à 0,93 pour 1,1 dessiné (facettes) → 1,25
    mur = round(2 * acc + 1.6, 2)      # matière au bout du cran = mur − 2·accroche = 1,6 mm
    jeu = 0.5 if D <= 70 else 0.6       # grand Ø : les facettes du maillage mangent jusqu'à 0,08 mm du jeu (mesuré 0,47 pour 0,5 dessiné)
    Ri = D / 2 + jeu + lh
    rm = Ri + acc
    s_l = math.atan((lug_l / 2) / Ri) * rm
    s_cran = -(s_l + jeu) - acc / math.tan(math.radians(45)) - 1.0 - acc / math.tan(math.radians(30))
    besoin = -math.degrees((s_cran - jeu - s_l) / rm)               # rotation mangée par l'ergot + le cran
    # angle de verrouillage : 2,5 à 6,5 mm de rotation libre avant la rampe du cran (le plafond de la fenêtre entre la fente verticale
    # et le cran ne tient que d'un côté : au-delà de ~12 mm il pend — ❌ « ponts » de 30 mm avec 30° fixes sur un Ø 130),
    # arrondi à un multiple m de θc = position où l'ergot recouvre tout le plat du cran (engagement maximal) : le pas du
    # pivotement de montage tombe alors pile dessus (sinon le pas de 6° du mode rapide le saute → accroche sous-mesurée).
    theta_c = math.degrees((s_l + jeu + 1.5) / rm)
    m_ = max(2, math.ceil((besoin + math.degrees(2.5 / rm)) / theta_c))
    angle = round(m_ * theta_c, 3)
    libre_mm = math.radians(angle - besoin) * rm
    d_ang = math.degrees(math.atan((lug_l / 2) / Ri) + math.asin(jeu / math.hypot(Ri, lug_l / 2))) + 0.3
    if angle + 2 * d_ang > 95 or libre_mm > 6.5:
        raise ValueError(f"D = {D:g} : baïonnette hors plage (fenêtre {angle + 2 * d_ang:.0f}° sur 120°, plafond libre {libre_mm:.1f} mm).")
    P = dict(Ri=round(Ri, 3), mur=mur, H=H + fond, fond=fond, angle=angle, m_cran=m_, jeu=jeu, accroche=acc, L=Lg)

    def _c16(p):
        return KB.baionnette_16(Ri=p["Ri"], mur=p["mur"], H=p["H"], fond=p["fond"], angle=p["angle"], jeu=p["jeu"], accroche=p["accroche"], L=p["L"], materiau=materiau)

    def build(p):
        c = _c16(p)
        a = Atelier("douille"); a.ajouter(c["douille"], f"Boîte (douille Ø{2 * p['Ri']:g}) à fentes en L + crans (composant n° 16)")
        k = Atelier("bouchon"); k.ajouter(c["bouchon"], f"Bouchon à 3 ergots sur languettes, rotation {p['angle']:g}° (composant n° 16)")
        # bout des ergots taillé au rayon r_tip (cylindrique) : les ergots-boîtes du n° 16 ont des coins à r_tip + 0,1 (prise inégale) et
        # un bout plat sans sommet de maillage au milieu → LC3D mesurait l'accroche au hasard (0,34 à 1,18 mm pour 1,1 dessiné).
        kz = c["cotes"]["z_ergot"]; r_tip = p["Ri"] + 2 * p["accroche"]; lug_h = c["cotes"]["ergot"][1]
        k.couper(cq.Workplane("XY").circle(p["Ri"] + p["mur"] + 5).circle(r_tip).extrude(lug_h + 0.2).translate((0, 0, kz - 0.1)),
                 f"Bout des ergots arrondi au rayon {r_tip:g}")
        return {"douille": Piece("douille", a.forme, materiau=materiau, orientation="telle"),
                "bouchon": Piece("bouchon", k.forme, materiau=materiau, role="structure", orientation=((1, 0, 0), 180))}

    def assembly(p, pieces):
        c = _c16(p); k = c["cotes"]
        A = Assemblage(); A.place("douille"); A.place("bouchon")
        A.clip("bouchon", "douille", accroche=p["accroche"], L=p["L"], h=k["languette"][2], w=k["languette"][0], alpha_in=30, alpha_out=45)
        A.pivoter("bouchon", pivot=(0, 0, 0), axe=(0, 0, 1), angle=-p["angle"],                # tourner pour verrouiller : passe le cran
                  pas=p["m_cran"] if lc3d.RAPIDE["actif"] else 10 * p["m_cran"])               # un pas tombe sur θc (engagement max)
        haut = p["H"] + 2.0; pas_d = 0.5 if haut <= 42 else 1.0
        md, mb = lc3d.vers_mesh(pieces["douille"].forme), lc3d.vers_mesh(pieces["bouchon"].forme)
        v, z = _descente_libre(md, mb, p["angle"], haut, pas_d)
        A.regle(f"descente tout droit dans les fentes (déverrouillé, 0 à {haut:g} mm)", lambda q, v=v: v <= 0.02,
                (f"pire chevauchement {v:.3f} mm³ à {z} mm de haut" if z is not None else f"aucun chevauchement (pas de {pas_d:g} mm)")
                + " — doit être ≤ 0,02 mm³ : les ergots glissent dans les fentes sans toucher")
        A.jeu("bouchon", "douille", 0.5)
        A.mouvement("bouchon", "rotation", pivot=(0, 0, 0), axe=(0, 0, 1), de=-p["angle"], a=-p["angle"] + max(k["rotation_libre"] - 0.5, 1.0),
                    pas_deg=1, jeu_min=0.5, titre="rotation libre de la fente jusqu'au cran")
        A.retenue("bouchon", (0, 0, 1), 4)                   # verrouillé, tiré vers le haut : les ergots butent sous le rebord
        return A

    return P, build, assembly, {"douille": couleurs[0], "bouchon": couleurs[1]}


# ------------------------------------------------------------------ boîte à charnière (n° 9) + fermeture clip (n° 1)
@recette
def boite_charniere(L=80.0, l=60.0, H=40.0, materiau="PETG", couleurs=("blanc", "gris")):
    """Boîte à couvercle sur charnière démontable (n° 9 : 2 goupilles sur bras flexibles qui clipsent dans 2 oreilles)
    + fermeture devant par un clip n° 1 (bras sur la boîte, crochet à retenue 45° qui passe par-dessus le couvercle).
    L × l × H = intérieur utile. Charnière n° 9 choisie plutôt que n° 31 (n° 31 : 1 ❌ et mouvement non vérifié au run de référence;
    n° 9 : lame de 0,45 mm corrigée dans le composant le 2026-10-28, oreilles de 3,0 mm ici).
    On ferme en appuyant le couvercle tout droit (goupilles + clip avant clipsent ensemble); on ouvre en tirant le haut du
    clip avant au doigt, puis le couvercle pivote jusqu'à 120°. Boîte et couvercle à plat, tels quels."""
    _plage("L", L, 30, 200); _plage("l", l, 25, 200); _plage("H", H, 15, 150)
    mur, fond = 2.0, 2.0
    W = L + 2 * mur                       # largeur extérieure = largeur du couvercle (à ras sur les côtés)
    Pf = l - 5.0 + 2 * mur                # face avant extérieure (le dos est à y = -5 : plaque des oreilles du n° 9)
    P = dict(L=L, l=l, H=H, mur=mur, fond=fond, W=W, Pf=Pf, Pl=Pf + 1.05, Hb=fond + H, Lc=14.0, hc=1.6, wc=8.0, acc_c=1.2, ep_or=3.0)
    # ep_oreille 3,0 (au lieu de 2,5) : la rampe du n° 9 mange 1,4 mm du haut de l'oreille → crête de 1,6 mm (1,1 mm avant : ⚠️ mur mince)

    def _geo(p):
        c9 = KA.charniere_clipsee_9(largeur=p["W"], profondeur=p["Pl"], ep_oreille=p["ep_or"]); k9 = c9["cotes"]
        eb, j9 = 4.0, k9["jeu"]                                  # ep_base et jeu par défaut du n° 9
        c1 = C1.clip_1(L=p["Lc"], h=p["hc"], w=p["wc"], accroche=p["acc_c"] + 0.15, retenue=45.0)   # +0,15 : bras à 0,15 du couvercle
        a1 = p["acc_c"] + 0.15
        hf = a1 / math.tan(math.radians(30)) + 1.0 + a1 / math.tan(math.radians(45))   # rampe + plat + montée de la face 45°
        s = p["Hb"] - eb
        lid_top = p["Hb"] + j9 + k9["ep_couvercle"]
        zb0 = lid_top - p["Lc"] + hf + 0.3                      # base du bras : dessous du crochet à 0,3 au-dessus du couvercle
        yb = p["Pl"] + 0.15 + p["hc"] / 2
        return dict(c9=c9, c1=c1, s=s, zb0=zb0, yb=yb, zc=k9["axe_z"] + s, lid_top=lid_top, hf=hf, ep_couv=k9["ep_couvercle"])

    def build(p):
        g = _geo(p); W, Pf, s = p["W"], p["Pf"], g["s"]
        b = Atelier("boite")
        b.bloc(W, Pf + 5.0, p["Hb"], pos=(0, (Pf - 5.0) / 2, 0), titre=f"Corps {W:g} × {Pf + 5:g} × {p['Hb']:g}")
        b.chanfreiner("<Z", 0.6, titre="Chanfrein du pied (patte d'éléphant)")
        for sx in (1, -1):
            lg = 0.5 + p["ep_or"] + 0.01
            b.bloc(lg, 10.0, s + 0.01, pos=(sx * (W / 2 - 0.01 + lg / 2), 0, 0), titre="Patte qui porte l'oreille de charnière")
        b.ajouter(g["c9"]["base"].translate((0, 0, s)).intersect(_b(-W, W, -6, 5, s - 1, s + 60)), "Oreilles de charnière percées en goutte (composant n° 9)")
        b.bloc(W - 2 * p["mur"], p["l"], p["Hb"], pos=(0, -5.0 + p["mur"] + p["l"] / 2, p["fond"]), titre="Vider l'intérieur", op="coupe")
        h, w, zb0 = p["hc"], p["wc"], g["zb0"]
        # gousset 45° sous le bras : assez bas pour garder ≥ 1,6 mm (perpendiculaire) sous le fond de la fente de 1,2 du bras
        pied = cq.Workplane("YZ").polyline([(Pf - 0.01, zb0 - 3.8), (g["yb"] + h / 2, zb0 - 3.8 + (g["yb"] + h / 2 - Pf)), (g["yb"] + h / 2, zb0 + 0.01),
                                            (Pf - 0.01, zb0 + 0.01)]).close().extrude(w / 2, both=True)
        b.ajouter(pied, "Pied du clip (gousset 45°, sans support)")
        bras = g["c1"]["bras"].rotate((0, 0, 0), (1, 0, 0), 180).rotate((0, 0, 0), (0, 0, 1), -90).translate((0, g["yb"], zb0))
        b.ajouter(bras, "Clip avant : bras + crochet 45° (composant n° 1)")
        k = Atelier("couvercle")
        k.ajouter(g["c9"]["couvercle"].translate((0, 0, s)), "Couvercle à goupilles sur bras flexibles (composant n° 9)")
        return {"boite": Piece("boite", b.forme, materiau=materiau, orientation="telle"),
                "couvercle": Piece("couvercle", k.forme, materiau=materiau, orientation="telle")}

    def assembly(p, pieces):
        g = _geo(p)
        A = Assemblage(); A.place("boite"); A.place("couvercle")
        A.clip("couvercle", "boite", accroche=1.2, L=14.0, h=1.6, w=g["ep_couv"])          # bras des goupilles (n° 9)
        A.inserer("couvercle", depuis=(0, 0, 15), pas=60)
        A.retenue("couvercle", (0, 0, 1), 5)
        # les 2 clips (goupilles n° 9 + clip avant n° 1) sont sur la MÊME paire : LC3D ne mesure que le pire des deux → chacun mesuré ici
        mc, mbx = lc3d.vers_mesh(pieces["couvercle"].forme), lc3d.vers_mesh(pieces["boite"].forme)
        W, Pf = p["W"], p["Pf"]
        f_av = _penetration_zone(mc, mbx, (-W, Pf - 1.0, -1), (W, Pf + 10, 999), 15.0)
        f_ch = _penetration_zone(mc, mbx, (-W - 10, -10, -1), (W + 10, 15.0, 999), 15.0)
        r1 = lc3d.calc_snap(p["Lc"], p["hc"], p["wc"], max(f_av, p["acc_c"]), "PETG", 30.0, 45.0)
        r9 = lc3d.calc_snap(14.0, 1.6, g["ep_couv"], max(f_ch, 1.2), "PETG", 30.0, 90.0)
        A.regle("clip avant n° 1 : accroche mesurée et calcul", lambda q: f_av >= 1.0 and r1["verdict"] == lc3d.OK,
                f"accroche mesurée {f_av:.2f} mm (dessinée {p['acc_c']:g}) · déformation {r1['deformation_pct']} % · contrainte {r1['contrainte_MPa']} MPa "
                f"(limite {r1['limite_MPa']}) · poussée {r1['force_insertion_N']} N · retrait {r1['force_retrait_N']} N (face 45° : s'ouvre au doigt)")
        A.regle("goupilles de charnière n° 9 : accroche mesurée et calcul", lambda q: f_ch >= 1.0 and r9["verdict"] == lc3d.OK,
                f"accroche mesurée {f_ch:.2f} mm (dessinée 1,2) · déformation {r9['deformation_pct']} % · contrainte {r9['contrainte_MPa']} MPa · poussée {r9['force_insertion_N']} N")
        # ouverture : de 0 à th0 on déclipse l'avant au doigt (le crochet retient : c'est voulu); ensuite le couvercle doit pivoter libre
        th0 = None
        for t10 in range(5, 600, 5):
            t = math.radians(t10 / 10)
            ok = True
            for dzr, haut in ((2.0, g["hf"] + 0.6), (-2.0, g["hf"] + 4.6)):        # coins avant haut / bas du couvercle
                recul = p["Pl"] * (1 - math.cos(t)) + dzr * math.sin(t)
                monte = p["Pl"] * math.sin(t) - dzr * (1 - math.cos(t))
                if not (recul >= p["acc_c"] + 0.8 or monte >= haut): ok = False
            if ok: th0 = t10 / 10; break
        A.mouvement("couvercle", "rotation", pivot=(0, 0, g["zc"]), axe=(1, 0, 0), de=th0, a=120, pas_deg=2,
                    titre=f"ouvrir {th0:g} → 120° (de 0 à {th0:g}° : on déclipse l'avant au doigt)")
        return A

    return P, build, assembly, {"boite": couleurs[0], "couvercle": couleurs[1]}


# ------------------------------------------------------------------ boîtier électronique (n° 17 + n° 2 + n° 33)
# prise montée sur la carte (réceptacle) : largeur, profondeur vers l'intérieur, hauteur au-dessus du circuit (fiches techniques typiques :
# USB-C GCT USB4085 8,94 × 7,35 × 3,26; micro-B 7,5 × 5 × 2,5; USB-A 13,1 × 14 × 5,7; USB-B et jack 5,5 : bibliothèque Arduino de lc3d)
_PRISES = {"usb_c": (8.94, 7.35, 3.26), "micro_usb": (7.5, 5.0, 2.5), "usb_a": (13.1, 14.0, 5.7),
           "usb_b": (12.0, 16.0, 11.0), "barillet_5.5": (9.0, 13.2, 10.9)}


@recette
def boitier_electronique(pcb_L=60.0, pcb_l=40.0, h_composants=10.0, connecteurs=("usb_c",), pcb_e=1.6, vis="M3",
                         materiau="PETG", couleurs=("noir", "gris", "vert")):
    """Boîtier pour une carte électronique pcb_L × pcb_l (trous de fixation à 3,5 mm des coins) : boîte + couvercle à emboîter
    (n° 17), 4 bossages pour inserts M3 à chaud (n° 2) sous les trous de la carte, une encoche ouverte (n° 33) par prise
    sur le bord -Y de la carte (connecteurs = types de fiches : usb_c, micro_usb, usb_a, usb_b, barillet_5.5; 1 à 3).
    Prises supposées à ras du bord de la carte, réparties sur le bord -Y. La vraie fiche de câble (surmoulage) est vérifiée."""
    _plage("pcb_L", pcb_L, 25, 180); _plage("pcb_l", pcb_l, 20, 150); _plage("h_composants", h_composants, 2, 50)
    types = [lc3d._type_fiche(t) for t in connecteurs]
    if not 1 <= len(types) <= 3 or None in types or any(t not in _PRISES for t in types):
        raise ValueError(f"connecteurs {connecteurs} : 1 à 3 parmi {', '.join(_PRISES)}")
    g, fond, h_boss, levre_h, inset = 2.5, 2.0, 8.0, 6.0, 3.5
    # jeu de l'encoche n° 33 : 1,0 par côté (pas 0,5) — LC3D exige le surmoulage + 0,5 par côté LIBRE sur toute la section, et les
    # coins du bas de l'encoche sont arrondis r 1,5 (ils mangent 0,44 mm dans les coins) : avec 0,5 la vraie fiche USB-C touchait (❌).
    J33 = 1.0
    Li, li = pcb_L + 2 * g, pcb_l + 2 * g
    z_pcb = fond + h_boss; z_top = z_pcb + pcb_e
    def fiche(t):
        F = lc3d.FICHES_CABLE[t]
        return (F["profil"][0][1], F["profil"][0][1]) if F.get("rond") else (max(q[1] for q in F["profil"]), max(q[2] for q in F["profil"]))
    He = z_top + max([h_composants] + [_PRISES[t][2] for t in types]) + 1.5 + levre_h
    for t in types:      # la fiche passe sous la lèvre du couvercle (qui descend de levre_h à l'intérieur du mur)
        He = max(He, z_top + _PRISES[t][2] / 2 + fiche(t)[1] / 2 + 0.5 + 0.5 + levre_h)
    He = round(He, 2)
    mur, serrage = _choix_17(He, materiau)
    n = len(types)
    xs = [round(-pcb_L / 2 + (k + 1) * pcb_L / (n + 1), 2) for k in range(n)]
    ri = max(6.0 - mur, 0.5)
    for x, t in zip(xs, types):
        if abs(x) + _PRISES[t][0] / 2 > pcb_L / 2 - inset - 3.0:
            raise ValueError(f"prise {t} trop près d'un trou de fixation : carte trop courte ({pcb_L:g} mm) pour {n} prise(s). Hors plage.")
        if abs(x) + fiche(t)[0] / 2 + J33 > Li / 2 - ri - 1.0:
            raise ValueError(f"encoche {t} dans l'arrondi du coin : carte trop courte. Hors plage.")
    for (x0, t0), (x1, t1) in zip(list(zip(xs, types)), list(zip(xs, types))[1:]):
        if x1 - x0 < (fiche(t0)[0] + fiche(t1)[0]) / 2 + 2 * J33 + 4.0:
            raise ValueError(f"prises {t0} et {t1} trop proches ({x1 - x0:.1f} mm) : moins de 4 mm de mur entre les encoches. Hors plage.")
    Lo = Li - 0.8
    perdues = sum(1 for x, t in zip(xs, types) for xc in (-Lo / 4, Lo / 4) if abs(x - xc) < fiche(t)[0] / 2 + J33 + 0.8 + 0.3)
    P = dict(L=Li + 2 * mur, l=li + 2 * mur, H=He, mur=mur, fond=fond, levre_h=levre_h, serrage=serrage, jeu_levre=0.4,
             pcb_L=pcb_L, pcb_l=pcb_l, pcb_e=pcb_e, h_composants=h_composants, z_pcb=z_pcb, h_boss=h_boss, inset=inset)
    trous = [(sx * (pcb_L / 2 - inset), sy * (pcb_l / 2 - inset)) for sx in (1, -1) for sy in (1, -1)]

    def _c17(p):
        return KB.couvercle_pression_17(L=p["L"], l=p["l"], H=p["H"], mur=p["mur"], fond=p["fond"], levre_h=p["levre_h"],
                                        serrage=p["serrage"], jeu_levre=p["jeu_levre"], materiau=materiau)

    def build(p):
        c = _c17(p)
        b = Atelier("boite"); b.ajouter(c["boite"], f"Boîte {p['L']:g} × {p['l']:g} × {p['H']:g}, mur {p['mur']:g} (composant n° 17)")
        for x, y in trous:
            # chanfrein 0,6 sur le bord EXTÉRIEUR du dessus : le bossage (Ø8,8) dépasse de 0,9 sous le bord de la carte; sans chanfrein,
            # son flanc vient à 0,05 mm du chant de la carte (LC3D : ❌ « jeu achetée » qui ne passera pas)
            bo = C1.bossage_insert_2(vis, hauteur=p["h_boss"] + 0.01)["bossage"]
            bo = bo.faces(">Z").edges(cq.selectors.RadiusNthSelector(1)).chamfer(0.6).translate((x, y, p["fond"] - 0.01))
            b.ajouter(bo, f"Bossage insert {vis} sous le trou ({x:g}, {y:g}) (composant n° 2)")
        for x, t in zip(xs, types):
            e = KD.encoche_ouverte_33(t, z_axe=z_top + _PRISES[t][2] / 2, ep_mur=p["mur"], jeu=J33, hauteur_mur=p["H"])
            b.couper(e["a_soustraire"].translate((x, -p["l"] / 2, 0)), f"Encoche ouverte pour {e['cotes']['fiche']} (composant n° 33)")
        k = Atelier("couvercle"); k.ajouter(c["couvercle"], f"Couvercle : lèvre + 6 côtes de serrage {p['serrage']:g} + bec (composant n° 17)")
        cr = Atelier("carte")
        cr.bloc(p["pcb_L"], p["pcb_l"], p["pcb_e"], pos=(0, 0, p["z_pcb"]), titre="Circuit imprimé")
        for x, y in trous: cr.trou(3.2, p["pcb_e"] + 0.2, pos=(x, y, p["z_pcb"] - 0.1), titre="Trou de fixation Ø3,2")
        for x, t in zip(xs, types):
            w_, d_, h_ = _PRISES[t]
            cr.bloc(w_, d_, h_, pos=(x, -p["pcb_l"] / 2 + d_ / 2, z_top - 0.01), titre=f"Prise {t}")
        dmax = max(_PRISES[t][1] for t in types)
        bx, by0, by1 = p["pcb_L"] / 2 - 7.0, -p["pcb_l"] / 2 + dmax + 1.0, p["pcb_l"] / 2 - 7.0
        if bx > 2 and by1 - by0 > 2:
            cr.bloc(2 * bx, by1 - by0, p["h_composants"], pos=(0, (by0 + by1) / 2, z_top - 0.01), titre="Composants (enveloppe)")
        return {"boite": Piece("boite", b.forme, materiau=materiau, orientation="telle"),
                "couvercle": Piece("couvercle", k.forme, materiau=materiau, orientation=((1, 0, 0), 180)),
                "carte": Piece("carte", cr.forme, role="achetee")}

    def assembly(p, pieces):
        A = Assemblage(); A.place("boite"); A.place("carte"); A.place("couvercle")
        A.inserer("carte", depuis=(0, 0, 40))
        A.assise("carte", "boite", aire_min=100)
        A.aligner("carte", "boite")
        for x, t in zip(xs, types):
            A.connecteur("carte", t, (x, -p["pcb_l"] / 2, z_top + _PRISES[t][2] / 2), (0, -1, 0), nom=f"prise {t}")
        return _assemblage_17(A, p, _c17(p)["calcul"]["force_retrait_N"], perdues)

    return P, build, assembly, {"boite": couleurs[0], "couvercle": couleurs[1], "carte": couleurs[2]}


# ------------------------------------------------------------------ support mural à trous de serrure (n° 23)
def _vis_bois(k, longueur=25.0):
    """Enveloppe de la vis à bois pour laquelle le n° 23 est dessiné (n° 8 : tête Ø8,4 × 3, tige Ø4,2 = Ø extérieur du filet).
    Tête de z = 0 à +tete_h, tige vers -Z (même repère que lc3d.vis). Une vis ISO M4 (tige Ø4,0) donnait 0,6 mm de jeu → ❌ « trop lâche »."""
    return cq.Workplane("XY").circle(k["tete_d"] / 2).extrude(k["tete_h"]).union(
        cq.Workplane("XY").circle(k["tige_d"] / 2).extrude(longueur).translate((0, 0, -longueur)))


@recette
def support_mural(L=100.0, l=60.0, tablette=0.0, materiau="PETG", couleurs=("blanc",)):
    """Plaque murale L (largeur) × l (hauteur) accrochée sur 1 vis (L < 60) ou 2 vis (entraxe L − 30) par trous de serrure
    (n° 23 : vis à bois n° 8, tête Ø8,4 × 3 — mesurer la vraie). tablette > 0 : rebord en bas de `tablette` mm de saillie,
    avec 2 goussets à 45°. Imprimée dos sur le plateau (les lèvres des trous en premières couches)."""
    _plage("L", L, 30, 220); _plage("l", l, 38, 220); _plage("tablette", tablette, 0, 80)
    if tablette > 0 and L < 40: raise ValueError("tablette sur une plaque de moins de 40 mm de large : hors plage")
    c = KB.trou_serrure_23(); k = c["cotes"]
    e = c["epaisseur_min"]
    xs = [0.0] if L < 60 else [-(L / 2 - 15), L / 2 - 15]
    yk = l / 2 - 6.0 - k["course"] - k["canal"] / 2
    P = dict(L=L, l=l, tablette=tablette, e=e, yk=round(yk, 3), course=k["course"], levre=k["levre"], jeu=0.5)

    def build(p):
        t = Atelier("support")
        t.bloc(p["L"], p["l"], p["e"], titre=f"Plaque {p['L']:g} × {p['l']:g} × {p['e']:g}")
        t.arrondir("|Z", 5.0, titre="Coins arrondis R5")
        for x in xs:
            t.couper(KB.trou_serrure_23()["a_soustraire"].translate((x, p["yk"], 0)), "Trou de serrure (composant n° 23)")
        # allègement : poche de 4 mm par l'avant (fond de 4 mm), hors bord de 5 mm, hors îlots autour des trous de serrure (canal + 3 mm)
        # et hors rebord/goussets. Ouverte vers le haut à l'impression : aucun surplomb.
        mx = p["L"] / 2 - (9.0 if p["tablette"] > 0 else 5.0)
        y_bas = -p["l"] / 2 + (8.0 if p["tablette"] > 0 else 5.0); y_haut = p["l"] / 2 - 5.0
        if 2 * mx > 12 and y_haut - y_bas > 12:
            poche = _b(-mx, mx, y_bas, y_haut, p["e"] - 4.0, p["e"] + 1)
            for x in xs:
                poche = poche.cut(_b(x - k["canal"] / 2 - 3, x + k["canal"] / 2 + 3, p["yk"] - k["entree"] / 2 - 3, p["l"], -1, p["e"] + 2))
            poche = poche.edges("|Z").fillet(1.0)
            t.couper(poche, "Poche d'allègement (fond 4 mm)")
        if p["tablette"] > 0:
            tb = p["tablette"]; y0 = -p["l"] / 2
            # rebord et goussets à l'intérieur des coins arrondis R5 (sinon les bouts du rebord dépassent dans le vide : porte-à-faux)
            t.bloc(p["L"] - 10.0, 3.0, tb, pos=(0, y0 + 1.5, p["e"] - 0.01), titre=f"Rebord de {tb:g} mm")
            gs = min(tb, p["l"] - 10.0)
            for x in (-(p["L"] / 2 - 6.5), p["L"] / 2 - 6.5):
                gu = cq.Workplane("YZ").polyline([(y0 + 2.99, p["e"] - 0.01), (y0 + 2.99, p["e"] + gs - 0.01), (y0 + 3.0 + gs, p["e"] - 0.01)]) \
                    .close().extrude(1.5, both=True).translate((x, 0, 0))
                t.ajouter(gu, "Gousset 45° (sans support)")
        mur = _b(-p["L"] / 2 - 15, p["L"] / 2 + 15, -p["l"] / 2 - 15, p["l"] / 2 + 15, -10, 0)
        for x in xs: mur = mur.cut(cq.Workplane("XY").circle(2.2).extrude(30).translate((x, p["yk"] + p["course"], -25)))
        out = {"support": Piece("support", t.forme, materiau=materiau, orientation="telle"),
               "mur": Piece("mur", mur, role="achetee", materiau="acier")}
        for i, _ in enumerate(xs):
            out[f"vis_{i + 1}"] = Piece(f"vis_{i + 1}", _vis_bois(k), role="achetee", materiau="acier")
        return out

    def assembly(p, pieces):
        L_ = p["course"]
        A = Assemblage(); A.place("mur")
        for i, x in enumerate(xs): A.place(f"vis_{i + 1}", x, p["yk"] + L_, p["levre"] + p["jeu"])
        A.place("support")                                              # accroché : les tiges en haut des fentes
        A.inserer("support", depuis=(0, L_, 0), pas=50)                 # présenté têtes dans les grands trous, puis descendu
        for dz in (1.0, 2.5, 4.0, 6.0, 9.0):                            # approche vers le mur, têtes dans les grands trous
            A.etat(f"approche à {dz} mm du mur", {"support": (0, L_, dz)})
        for i, _ in enumerate(xs): A.jeu("support", f"vis_{i + 1}", p["jeu"])
        A.retenue("support", (0, 0, 1), 5)        # tiré du mur : les lèvres butent sous les têtes
        A.retenue("support", (0, -1, 0), 5)       # poids vers le bas : le haut des fentes bute sur les tiges
        return A

    return P, build, assembly, {"support": couleurs[0]}


# ------------------------------------------------------------------ bac de rangement Gridfinity (n° 28)
@recette
def bac_rangement(nx=2, ny=1, hauteur_u=3, cases=(1, 1), aimants=False, couleurs=("gris", "noir")):
    """Bac Gridfinity nx × ny cases de 42 mm, hauteur_u × 7 mm, cloisons cases = (cx, cy), + sa plaque de base (n° 28).
    Murs 0,95 mm = norme Gridfinity (mur_min 0,9 déclaré pour le bac)."""
    _plage("nx", nx, 1, 5, "cases"); _plage("ny", ny, 1, 5, "cases"); _plage("hauteur_u", hauteur_u, 2, 12, "unités")
    _plage("cases x", cases[0], 1, 3 * nx, "compartiments"); _plage("cases y", cases[1], 1, 3 * ny, "compartiments")
    P = dict(nx=int(nx), ny=int(ny), hu=int(hauteur_u), cx=int(cases[0]), cy=int(cases[1]), aimants=bool(aimants))

    def build(p):
        g = KC.gridfinity_28(p["nx"], p["ny"], p["hu"], cases=(p["cx"], p["cy"]), aimants=p["aimants"])
        a = Atelier("plaque"); a.ajouter(g["plaque"], f"Plaque Gridfinity {p['nx']} × {p['ny']} (composant n° 28)")
        # Plaque du n° 28 adaptée à l'impression (la norme a des lames de 0 mm que LC3D refuse : ❌ murs de 0,23-0,25 mm en diagonale) :
        # 1) chaque poche agrandie de 0,15 mm par côté sur toute sa hauteur (jeu bac ↔ plaque 0,40 au lieu de 0,25 : avec 0,25, 14 % des
        #    1 000 impressions simulées P2S coinçaient le bac) et descendue DROITE jusqu'au plateau (plus de lèvre à 45° qui part de 0 mm);
        # 2) crêtes du haut écrêtées à z = 3,0 : plat de 1,5 mm au bord, 3,0 mm entre les cases.
        q0, q1, q2 = lc3d.GF["plaque_profil"]; c_ = lc3d.GF["pas"] - 2 * q2; Hp = q0 + q1 + q2; e_ = 0.15
        for i in range(p["nx"]):
            for j in range(p["ny"]):
                ox = (i - (p["nx"] - 1) / 2) * lc3d.GF["pas"]; oy = (j - (p["ny"] - 1) / 2) * lc3d.GF["pas"]
                droite = cq.Workplane("XY").sketch().rect(c_ + 2 * e_, c_ + 2 * e_).vertices().fillet(4.0 - q2 + e_).finalize() \
                    .extrude(q0 + q1 + 1.0).translate((ox, oy, -1.0))
                pente = cq.Solid.makeLoft([lc3d._wire_rr(cq, q0 + q1 - 0.01, c_ + 2 * e_ + 0.02, c_ + 2 * e_ + 0.02, 4.0 - q2 + e_),
                                           lc3d._wire_rr(cq, Hp + 0.5, c_ + 2 * e_ + 2 * (q2 + 0.51), c_ + 2 * e_ + 2 * (q2 + 0.51), 4.0 + e_ + 0.51)], True)
                a.couper(droite.union(cq.Workplane("XY").add(pente.translate(cq.Vector(ox, oy, 0)))),
                         "Poche +0,15 par côté, droite jusqu'au plateau (plus de lèvre en lame)")
        bb = a.forme.val().BoundingBox()
        a.couper(_b(bb.xmin - 1, bb.xmax + 1, bb.ymin - 1, bb.ymax + 1, 3.0, bb.zmax + 1), "Écrêter les lames du haut à 3,0 mm (plat imprimable)")
        b = Atelier("bac"); b.ajouter(g["bac"], f"Bac {p['nx']} × {p['ny']} × {p['hu']}u, {p['cx']} × {p['cy']} cases (composant n° 28)")
        return {"plaque": Piece("plaque", a.forme, orientation="telle"),
                "bac": Piece("bac", b.forme, mur_min=0.9, orientation="telle")}

    def assembly(p, pieces):
        A = Assemblage()
        A.environnement(temperature=25, ou="intérieur")
        A.place("plaque"); A.place("bac")
        A.inserer("bac", depuis=(0, 0, 30))
        # pas de A.jeu : le bac s'appuie sur les chanfreins à 45° de la plaque (ajustement défini par la norme)
        A.assise("plaque", "sol", aire_min=300); A.assise("bac", "sol", aire_min=300)
        A.jeu("bac", "plaque", minimum=0.05)    # jeu de la norme sur les pentes à 45° (≈ 0,1 mm) : le bac se pose, il ne frotte pas
        A.stabilite()
        return A

    return P, build, assembly, {"plaque": couleurs[1], "bac": couleurs[0]}


def liste():
    return {n: (f.__doc__ or "").strip().split("\n")[0] for n, f in RECETTES.items()}
