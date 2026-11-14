"""LC3D — composants du lot A (n° 8 à 15) : charnières, rotule, pivot clipsé, cliquet, glissière, détente.
Même style que composants_lc3d.py : chaque composant = une fonction paramétrique qui renvoie un dict
{formes CadQuery..., cotes, calcul, note, numero, nom}. Impression FDM buse 0,4 / couche 0,2, PETG par défaut.
Statut de départ : « calculé » (passe les vérifs LC3D) — « validé » seulement après une vraie impression (photo à l'appui).
Chaque composant a son modèle de test : tests/composants/t_c<NN>.py.
"""
import math
import cadquery as cq

RAC2 = math.sqrt(2.0)


def _prisme(plan, pts, ep, both=True):
    """Profil 2D fermé (liste de points) dans le plan donné, extrudé de ep (symétrique si both)."""
    return cq.Workplane(plan).polyline(pts).close().extrude(ep / 2 if both else ep, both=both)


def _boite(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))


def _goutte_x(r, x0, x1, y=0.0, z=0.0):
    """Trou horizontal (axe X) en goutte : rond de rayon r + pointe à 45° vers le haut (imprimable sans support)."""
    L = x1 - x0
    rond = cq.Workplane("YZ").circle(r).extrude(L)
    pointe = cq.Workplane("YZ").polyline([(-r * math.sin(math.radians(45)), r * math.cos(math.radians(45))), (0, r * RAC2),
                                          (r * math.sin(math.radians(45)), r * math.cos(math.radians(45)))]).close().extrude(L)
    return rond.union(pointe).translate((x0, y, z))


# ------------------------------------------------------------------ n° 8 : charnière imprimée montée (print-in-place)
def charniere_imprimee_8(longueur=40.0, largeur=20.0, n_noeuds=5, R=5.0, d_axe=3.5, jeu_pip=0.45, ep=2.0, jeu_rot=0.5):
    """Charnière imprimée d'un seul coup, à plat, sans support. Axe le long de X à la hauteur z = R.
    feuille_a (côté -Y) porte les nœuds pairs + l'axe Ø d_axe qui traverse tout (axe captif, ne peut pas sortir);
    feuille_b (côté +Y) porte les nœuds impairs percés en goutte (Ø axe + 2 × jeu_pip). Nœuds en goutte vers le bas
    (pied à plat sur le plateau, flancs à 45°) : aucun surplomb. Ouvre de 0 à 180° (feuille_b se rabat sur feuille_a).
    jeu_pip : jeu radial et axial entre les deux pièces imprimées ensemble (règle print-in-place ≥ 0,4)."""
    if n_noeuds % 2 == 0: raise ValueError("n_noeuds doit être impair (un nœud de feuille_a à chaque bout tient l'axe)")
    wk = (longueur - (n_noeuds - 1) * jeu_pip) / n_noeuds
    rp = d_axe / 2; rh = rp + jeu_pip
    s45 = math.sin(math.radians(45))
    pied = [(-s45 * R, R - s45 * R), (s45 * R, R - s45 * R), ((s45 - (1 - s45)) * R, 0), (-(s45 - (1 - s45)) * R, 0)]
    Rf = math.hypot((2 * s45 - 1) * R, R)          # rayon balayé par le pied du nœud qui tourne (≈ 1,08 R)
    dy = Rf + jeu_rot                               # recul des feuilles devant les nœuds de l'autre pièce
    def noeud(x0):
        c = cq.Workplane("YZ").center(0, R).circle(R).extrude(wk)
        p = cq.Workplane("YZ").polyline(pied).close().extrude(wk)
        return c.union(p).translate((x0, 0, 0))
    A = _boite(-longueur / 2, longueur / 2, -largeur, -dy, 0, ep)
    B = _boite(-longueur / 2, longueur / 2, dy, largeur, 0, ep)
    for i in range(n_noeuds):
        x0 = -longueur / 2 + i * (wk + jeu_pip)
        if i % 2 == 0:
            A = A.union(noeud(x0)).union(_boite(x0, x0 + wk, -dy - 0.01, 0, 0, ep))
        else:
            B = B.union(noeud(x0)).union(_boite(x0, x0 + wk, 0, dy + 0.01, 0, ep))
            B = B.cut(_goutte_x(rh, x0 - 0.5, x0 + wk + 0.5, 0, R))
    axe = cq.Workplane("YZ").center(0, R).circle(rp).extrude(longueur).translate((-longueur / 2, 0, 0))
    axe = axe.cut(_boite(-longueur, longueur, -R, R, -1, R - 0.7 * rp))   # dessous de l'axe aplati (pont de 2,5 mm de large, pas de filet fin)
    A = A.union(axe)
    paroi = R - rh * RAC2
    cotes = dict(longueur=longueur, largeur_feuille=largeur, n_noeuds=n_noeuds, largeur_noeud=round(wk, 2), R_noeud=R, d_axe=d_axe,
                 trou=round(2 * rh, 2), jeu_pip=jeu_pip, epaisseur_feuille=ep, axe_z=R, pivot=(0, 0, R), axe=(1, 0, 0))
    calcul = dict(paroi_sur_goutte_mm=round(paroi, 2), pont_axe_mm=round(wk + 2 * jeu_pip, 2), rayon_balaye_pied_mm=round(Rf, 2),
                  ouverture_deg="0 → 180 (vérifié par le mouvement LC3D)")
    return dict(feuille_a=A, feuille_b=B, cotes=cotes, calcul=calcul, numero=8, nom="charnière imprimée montée",
                note="Imprimer les 2 feuilles ENSEMBLE, à plat, sans support (un seul objet dans le slicer). "
                     "Après l'impression : plier doucement 2-3 fois pour décoller l'axe. Jeu 0,45 : si ta P2S soude, monter à 0,5.")


# ------------------------------------------------------------------ n° 9 : charnière à goupilles clipsées (démontable)
def charniere_clipsee_9(largeur=40.0, profondeur=30.0, ep_couv=4.0, d_goupille=4.0, jeu=0.5, accroche=1.2, L_bras=14.0,
                        h_bras=1.6, fente=1.5, ep_oreille=2.5, larg_oreille=10.0, ep_base=4.0):
    """Couvercle qui pivote sur 2 goupilles Ø d_goupille portées par 2 bras flexibles (dans le plan du couvercle).
    La base a 2 oreilles percées en goutte (Ø goupille + 1,0 : règle pivot) avec une rampe 30° en haut :
    on pousse le couvercle par le haut, les bras plient vers l'intérieur, les goupilles tombent dans les trous.
    Retenue : face carrée (bout de goupille dans le trou) → ne sort jamais toute seule.
    Démontage sans rien briser : pincer les 2 bras vers l'intérieur (accès par les fentes) et soulever.
    Axe le long de X à (y = 0, z = zc). Couvercle fermé à plat sur +Y, ouvre en montant (rotation + autour de X)."""
    import lc3d
    zc = ep_base + jeu + ep_couv / 2
    r = d_goupille / 2; rh = r + 0.7                      # trou = goupille + 1,4 mm (≥ +1,0; le pied plat de la goupille garde 0,5 de jeu)
    W2 = largeur / 2
    couv = _boite(-W2, W2, 0, profondeur, zc - ep_couv / 2, zc + ep_couv / 2)
    couv = couv.union(cq.Workplane("YZ").center(0, zc).circle(ep_couv / 2).extrude(largeur).translate((-W2, 0, 0)))
    xo0 = W2 + jeu; xo1 = xo0 + ep_oreille
    lg = jeu + accroche                                   # longueur de goupille qui dépasse du couvercle
    base = _boite(-xo1, xo1, -larg_oreille / 2, profondeur, 0, ep_base)
    apex = rh * RAC2
    # bas de la rampe 1,6 mm au-dessus de la pointe de la goutte (avant : 0,4 → lame de 0,45 mm en diagonale entre la pointe de la goutte
    # et la rampe, ❌ « mur 0,45 mm » de LC3D depuis la vérif des murs en diagonale; corrigé 2026-10-28, recettes LC3D)
    zt = zc + apex + 1.6 + (accroche + 0.2) / math.tan(math.radians(30))
    dx = accroche + 0.2; dz = dx / math.tan(math.radians(30))
    for s in (1, -1):
        # bras flexible : fente derrière le bras, ouverte au bout (côté axe)
        f = _boite(W2 - h_bras - fente, W2 - h_bras, -ep_couv, L_bras, zc - ep_couv, zc + ep_couv)
        s45 = math.sin(math.radians(45))      # goupille en goutte vers le bas, pied plat de 0,83 r au plateau (pas de surplomb, pas de filet fin)
        g = cq.Workplane("YZ").center(0, zc).circle(r).extrude(lg).union(
            cq.Workplane("YZ").polyline([(-s45 * r, zc - s45 * r), (s45 * r, zc - s45 * r), ((2 * s45 - 1) * r, zc - r), (-(2 * s45 - 1) * r, zc - r)]).close().extrude(lg)
        ).translate((W2 - 0.01, 0, 0))
        o = _boite(xo0, xo1, -larg_oreille / 2, larg_oreille / 2, ep_base - 0.01, zt)
        o = o.cut(_goutte_x(rh, xo0 - 1, xo1 + 1, 0, zc))
        rampe = _prisme("XZ", [(xo0 - 0.2, zt + 0.5), (xo0 + dx, zt + 0.5), (xo0 + dx, zt), (xo0, zt - dz), (xo0 - 0.2, zt - dz)], larg_oreille + 2)
        o = o.cut(rampe)
        if s < 0: f, g, o = f.mirror("YZ"), g.mirror("YZ"), o.mirror("YZ")
        couv = couv.cut(f).union(g)
        base = base.union(o)
    # dessous du bout arrondi (entre les 2 fentes) taillé à 45° (pas de surplomb à plat sur le plateau; reste dans le rond → ne change pas le pivotement)
    rr = ep_couv / 2
    tri_arr = [(-rr, zc), (0, zc - rr), (0, zc - rr - 1), (-rr - 2, zc - rr - 1), (-rr - 2, zc)]
    couv = couv.cut(cq.Workplane("YZ").polyline(tri_arr).close().extrude(2 * W2).translate((-W2, 0, 0)))
    calc = lc3d.calc_snap(L_bras, h_bras, ep_couv, accroche, "PETG", 30.0, 90.0)
    cotes = dict(largeur=largeur, profondeur=profondeur, ep_couvercle=ep_couv, goupille=d_goupille, trou=round(2 * rh, 2), jeu=jeu,
                 accroche=accroche, bras=f"{L_bras} × {h_bras} × {ep_couv}", fente=fente, oreille=f"{ep_oreille} × {larg_oreille} × {round(zt - ep_base, 1)}",
                 axe_z=round(zc, 2), pivot=(0, 0, zc), axe=(1, 0, 0), haut_oreille=round(zt, 2))
    return dict(couvercle=couv, base=base, cotes=cotes, calcul=calc, numero=9, nom="charnière à goupilles clipsées",
                note="Couvercle imprimé à plat (goupilles couchées, bras dans le plan des couches). Base à plat, oreilles debout, trous en goutte. "
                     "Pour l'enlever : pincer les 2 bras vers le centre (≈ 1,2 mm chacun) et soulever.")


# ------------------------------------------------------------------ n° 10 : charnière vivante (lame mince)
MATERIAUX_VIVANTE = {   # allongement utilisable en flexion répétée d'une lame imprimée (estimations, à confirmer par essai)
    "PP":   dict(eps_pratique=0.15, verdict="excellent : des milliers de pliages (le matériau des charnières de bouchons)"),
    "PETG": dict(eps_pratique=0.10, verdict="correct : quelques centaines de pliages; blanchit au 1er pli (normal)"),
    "TPU":  dict(eps_pratique=0.50, verdict="ne casse pas mais ne tient pas la forme (mou)"),
    "PLA":  dict(eps_pratique=0.03, verdict="CASSE : le PLA fend après quelques pliages — ne jamais l'utiliser pour une charnière vivante"),
}


def charniere_vivante_10(largeur=30.0, longueur_lame=8.0, ep_lame=0.84, ep_plaque=3.0, long_plaque=25.0, angle=90.0, materiau="PETG"):
    """Deux plaques reliées par une lame mince (imprimée à plat, collée au plateau, couches dans le plan de la lame).
    ep_lame ≥ 0,84 mm (2 lignes de buse : minimum LC3D). Le pli est réparti sur longueur_lame.
    Déformation en flexion pure : ε = ep × θ / (2 × L). Comparée à ce que chaque matériau encaisse.
    Repère : lame de y = -L/2 à +L/2, z 0 → ep_lame; plaques de chaque côté (z 0 → ep_plaque); pli autour de X."""
    import lc3d
    L = longueur_lame; th = math.radians(angle)
    A = _boite(-largeur / 2, largeur / 2, -L / 2 - long_plaque, -L / 2, 0, ep_plaque)
    B = _boite(-largeur / 2, largeur / 2, L / 2, L / 2 + long_plaque, 0, ep_plaque)
    lame = _boite(-largeur / 2, largeur / 2, -L / 2 - 0.5, L / 2 + 0.5, 0, ep_lame)
    forme = A.union(B).union(lame)
    eps = ep_lame * th / (2 * L)
    angle_elast = math.degrees(2 * L * lc3d.MATERIAUX["PETG"]["eps"] / ep_lame)
    # calc_lame (modèle en porte-à-faux, pire cas : la courbure se concentre à la racine) : flèche équivalente f = 2Lθ/3
    cl = lc3d.calc_lame(L, ep_lame, largeur, 2 * L * th / 3, "PETG", usage="fatigue")
    # dégagement des plaques au pli (chaque moitié tourne de θ/2 autour du milieu de la lame)
    deg = 2 * ((L / 2) * math.cos(th / 2) - (ep_plaque - ep_lame / 2) * math.sin(th / 2))
    angle_geo = math.degrees(2 * math.atan((L / 2) / (ep_plaque - ep_lame / 2)))
    mats = {m: dict(eps_pratique_pct=v["eps_pratique"] * 100, ok=eps <= v["eps_pratique"], verdict=v["verdict"]) for m, v in MATERIAUX_VIVANTE.items()}
    calcul = dict(deformation_pct=round(eps * 100, 1), angle_elastique_PETG_deg=round(angle_elast, 0), calc_lame_porte_a_faux=cl,
                  degagement_plaques_au_pli_mm=round(deg, 2), angle_max_geometrique_deg=round(angle_geo, 0), materiaux=mats,
                  verdict_materiau=("OK " + materiau) if mats.get(materiau, {}).get("ok") else f"{materiau} : déformation {eps*100:.1f} % > {MATERIAUX_VIVANTE.get(materiau, {}).get('eps_pratique', 0)*100:.0f} % pratique")
    cotes = dict(largeur=largeur, longueur_lame=L, ep_lame=ep_lame, ep_plaque=ep_plaque, angle=angle, materiau=materiau)
    return dict(piece=forme, cotes=cotes, calcul=calcul, numero=10, nom="charnière vivante",
                note="Imprimer à plat, lame collée au plateau, 100 % de remplissage, lignes PERPENDICULAIRES au pli. "
                     "PP = idéal; PETG = correct (blanchit au 1er pli, quelques centaines de cycles); PLA = CASSE. "
                     "Plier une 1re fois lentement à fond (le PETG/PP s'oriente et devient plus endurant). Durée de vie = estimation, à confirmer par essai.")


# ------------------------------------------------------------------ n° 11 : rotule imprimée montée, friction réglable
def rotule_11(R_boule=9.5, jeu_pip=0.45, d_tige=8.0, z_centre=12.0, paroi=2.5, vis="M3"):
    """Rotule imprimée d'un seul coup (print-in-place), douille sur le plateau, boule portée par sa tige qui descend au plateau.
    Cavité = sphère (R_boule + jeu) + double cône à 45° (entonnoir en bas jusqu'au plateau, ouverture en haut) :
    aucun surplomb > 45° dans la douille, boule captive (ouvertures Ø ≈ 1,41 × R < Ø boule).
    Friction réglable : vis de blocage M3 radiale + écrou captif (glissé par le haut), la pointe de vis pousse sur la boule.
    Débattement de la tige : α_max = 45° − asin((r_tige + 0,5) / (R + jeu))."""
    import lc3d
    Rg = R_boule + jeu_pip; zc = z_centre
    Rs = zc + paroi                                     # l'entonnoir arrive au plateau au rayon zc
    z_top = zc + Rg * math.sin(math.radians(45))
    douille = cq.Workplane("XY").circle(Rs).extrude(z_top)
    cav = cq.Workplane("XY").sphere(Rg).translate((0, 0, zc))
    cav = cav.union(cq.Workplane("XY").add(cq.Solid.makeCone(0, zc + 2, zc + 2, cq.Vector(0, 0, zc), cq.Vector(0, 0, -1))))
    cav = cav.union(cq.Workplane("XY").add(cq.Solid.makeCone(0, z_top - zc + 2, z_top - zc + 2, cq.Vector(0, 0, zc), cq.Vector(0, 0, 1))))
    # bossage de la vis de blocage (côté +X), du plateau jusqu'au-dessus de l'écrou
    V = lc3d.VIS_ISO[vis]; e = V["ecrou"] + lc3d.JEU_ECROU; hn = V["h_ecrou"] + 0.4
    xb = Rs + 4.5
    boss = _boite(Rs - 2, xb, -5, 5, 0, zc + 5)
    douille = douille.union(boss).cut(cav)
    douille = douille.cut(_goutte_x(lc3d.TROUS_FDM["passage"][vis] / 2, Rg - 1, xb + 1, 0, zc))
    xn0 = xb - 1.6 - hn                                  # poche d'écrou : 1,6 mm de paroi côté extérieur
    rc = e / 2 / math.cos(math.radians(30))
    hexa = [(rc * math.cos(math.radians(90 + 60 * k)), rc * math.sin(math.radians(90 + 60 * k))) for k in range(6)]
    poche = cq.Workplane("YZ").polyline(hexa).close().extrude(hn).translate((xn0, 0, zc))
    poche = poche.union(_boite(xn0, xn0 + hn, -e / 2, e / 2, zc, zc + 6))   # fente ouverte vers le haut
    douille = douille.cut(poche)
    boule = cq.Workplane("XY").sphere(R_boule).translate((0, 0, zc)).union(cq.Workplane("XY").circle(d_tige / 2).extrude(zc))
    alpha = 45 - math.degrees(math.asin((d_tige / 2 + 0.5) / Rg))
    cotes = dict(R_boule=R_boule, jeu_pip=jeu_pip, d_tige=d_tige, centre_z=zc, d_douille=2 * Rs, hauteur_douille=round(z_top, 2),
                 ouverture_haut=round(2 * Rg * math.sin(math.radians(45)), 2), vis=f"{vis} × 10 + écrou", x_tete_vis=round(Rg + 10, 2),
                 x_ecrou=round(xn0, 2), centre=(0, 0, zc))
    calcul = dict(debattement_max_deg=round(alpha, 1), retenue="ouvertures Ø%.1f < Ø boule %.0f" % (2 * Rg * 0.7071, 2 * R_boule),
                  friction="vis de blocage : la pointe touche la boule après %.1f mm de serrage, puis frein progressif" % jeu_pip)
    return dict(douille=douille, boule=boule, cotes=cotes, calcul=calcul, numero=11, nom="rotule à friction réglable",
                note="Imprimer douille + boule ENSEMBLE, debout (tige au plateau, bordure/brim conseillée). Le dessous de la boule "
                     "(autour de la tige) est un surplomb de sphère : il sort un peu rugueux, sans effet sur le fonctionnement. "
                     "Après l'impression : faire tourner la boule pour la décoller, glisser l'écrou M3 par le haut, visser la M3×10.")


# ------------------------------------------------------------------ n° 12 : axe pivot clipsé (goupille fendue)
def pivot_clipse_12(d=6.0, prise=11.0, accroche=1.0, fente=2.6, d_tete=10.0, h_tete=3.0, jeu_axial=0.5, plat=0.7, materiau="PETG"):
    """Goupille fendue qui clipse : on l'enfonce dans des trous Ø d + 1,0 (règle pivot), les 2 branches se serrent,
    les crochets (face carrée + rampe 30°) passent et se rouvrent derrière la dernière pièce. Démontable en pinçant les crochets.
    Repère : axe Z, dessous de la tête à z = 0, tige vers -Z; prise = épaisseur totale serrée (pièces + jeux).
    Deux méplats (|y| ≤ plat × r) : s'imprime couchée sur un méplat, branches pliant dans le plan des couches."""
    import lc3d
    r = d / 2; rh = r + 0.5; rb = rh + accroche
    z0 = -(prise + jeu_axial)                          # face carrée des crochets
    r_bout = r - 0.3
    h_rampe = (rb - r_bout) / math.tan(math.radians(30))
    z_bout = z0 - h_rampe - 0.4
    f = plat * r
    tete = cq.Workplane("XY").circle(d_tete / 2).extrude(h_tete)
    tige = cq.Workplane("XY").circle(r).extrude(-z0).translate((0, 0, z0))
    crochet = _prisme("XZ", [(0, z0), (rb, z0), (r_bout, z0 - h_rampe), (r_bout, z_bout), (0, z_bout)], 2 * f)
    crochets = crochet.union(crochet.mirror("YZ")).intersect(cq.Workplane("XY").circle(rb).extrude(z0 - z_bout + 2).translate((0, 0, z_bout - 1)))   # crochets arrondis au Ø crochet (coins des méplats)
    g = tete.union(tige).union(crochets)
    g = g.intersect(_boite(-d_tete, d_tete, -f, f, z_bout - 1, h_tete + 1))
    haut_fente = h_tete / 2
    g = g.cut(_boite(-fente / 2, fente / 2, -f - 1, f + 1, z_bout - 1, haut_fente))
    h_br = r - fente / 2
    L = haut_fente - z0
    calc = lc3d.calc_snap(L, h_br, 2 * f, accroche, materiau, 30.0, 90.0)
    trou = cq.Workplane("XY").circle(rh).extrude(prise + 20).translate((0, 0, -prise - 10))
    cotes = dict(d=d, trou=2 * rh, prise=prise, accroche=accroche, fente=fente, branche=f"{round(L,1)} × {h_br} × {2*f:.1f}",
                 crochet_d=2 * rb, tete=f"Ø{d_tete} × {h_tete}", longueur_totale=round(h_tete - z_bout, 1), jeu_axial=jeu_axial)
    return dict(goupille=g, trou_a_soustraire=trou, cotes=cotes, calcul=calc, numero=12, nom="axe pivot clipsé",
                note="Goupille couchée sur un méplat, 100 % de remplissage (rôle flexible). Trous des pièces : Ø d + 1,0. "
                     "Pour l'enlever : pincer les 2 crochets ensemble et pousser.")


# ------------------------------------------------------------------ n° 13 : roue à rochet + cliquet à lame-ressort
def cliquet_13(n_dents=20, r_tete=15.0, profondeur=1.5, jeu_fond=0.3, ep_roue=5.0, d_axe=8.0, L_lame=20.0, h_lame=1.5,
               jeu=0.5, ep_base=3.0):
    """Roue à rochet (dents en dents de scie : rampe + face radiale) + cliquet monobloc avec la base : une lame-ressort
    imprimée (dans le plan des couches) qui porte la dent du cliquet. Sens libre = antihoraire (vu de dessus) :
    la rampe soulève la dent, la lame plie. Sens bloqué = horaire : la face radiale bute sur la dent et TIRE la lame
    (traction, pas de flambage). Engagement = profondeur − jeu_fond (≥ 1,0).
    Repère : axe de la roue = Z à l'origine; cliquet en haut (+Y); base sur le plateau (z = 0)."""
    import lc3d
    p = 2 * math.pi / n_dents; r_pied = r_tete - profondeur
    z_r0 = ep_base + jeu; z_r1 = z_r0 + ep_roue
    pts = []
    for k in range(n_dents):
        for j in range(8):
            t = j / 8
            phi = k * p + t * p
            rr = r_tete - profondeur * t
            pts.append((rr * math.cos(phi), rr * math.sin(phi)))
        phi = (k + 1) * p - 1e-4
        pts.append((r_pied * math.cos(phi), r_pied * math.sin(phi)))
    roue = cq.Workplane("XY").polyline(pts).close().extrude(ep_roue).translate((0, 0, z_r0))
    rot0 = math.pi / 2 + math.radians(4.0) - round((math.pi / 2 + math.radians(4.0)) / p) * p   # une face radiale à 94°
    roue = roue.rotate((0, 0, 0), (0, 0, 1), math.degrees(rot0))
    roue = roue.cut(cq.Workplane("XY").circle(d_axe / 2 + 0.5).extrude(50).translate((0, 0, -10)))
    phi_f = round((math.pi / 2 + math.radians(4.0)) / p) * p + rot0       # angle de la face radiale = 94°
    # dent du cliquet : face côté -X parallèle à la face radiale (0,5 mm), dessous parallèle à la rampe (+ jeu_fond)
    y_lame = r_tete + 0.6
    c = 0.5 / r_pied
    dessous = []
    for j in range(13):
        phi = phi_f - c - j * (0.75 * p) / 12
        rr = r_pied + profondeur * (phi_f - phi) / p + jeu_fond
        dessous.append((rr * math.cos(phi), rr * math.sin(phi)))
    x_face = dessous[0][0]
    x_fin = dessous[-1][0] + 1.0
    dent = [(x_face, y_lame + 0.1)] + dessous + [(dessous[-1][0], y_lame + 0.1)]
    H = z_r1
    dent_s = cq.Workplane("XY").polyline(dent).close().extrude(H)
    x_rac = x_fin - L_lame - 2.0                        # racine de la lame (côté -X : la lame travaille en traction au blocage)
    lame = _boite(x_rac, x_fin, y_lame, y_lame + h_lame, 0, H)
    racine = _boite(x_rac - 6, x_rac + 0.01, y_lame - 3, y_lame + h_lame + 4, 0, H)
    X0, X1, Y0, Y1 = x_rac - 6, r_tete + 6, -r_tete - 6, y_lame + h_lame + 4
    base = _boite(X0, X1, Y0, Y1, 0, ep_base)
    # dégagement sous la lame et la dent (la lame repose sur le plateau, libre de plier vers +Y)
    base = base.cut(_boite(x_rac, X1 + 1, r_pied - 1.5, Y1 + 1, -1, ep_base + 1))
    base = base.union(racine).union(lame).union(dent_s)
    base = base.union(cq.Workplane("XY").circle(d_axe / 2).extrude(z_r1 + 1.0))
    eng = profondeur - jeu_fond
    L_eff = (dessous[0][0] + dessous[-1][0]) / 2 - x_rac
    calc = lc3d.calc_snap(L_eff, h_lame, H, eng, "PETG", 30.0, 90.0, usage="fatigue")
    ressort = lc3d.calc_lame(L_eff, h_lame, H, eng, "PETG", frottement_N=0.3, usage="fatigue")
    cotes = dict(n_dents=n_dents, pas_deg=round(360 / n_dents, 2), r_tete=r_tete, profondeur=profondeur, engagement=round(eng, 2),
                 roue_z=(z_r0, z_r1), trou_roue=d_axe + 1.0, axe=d_axe, lame=f"{round(L_eff,1)} × {h_lame} × {H}", jeu=jeu)
    return dict(roue=roue, base=base, cotes=cotes, calcul=dict(clip=calc, lame=ressort), numero=13, nom="cliquet à lame-ressort",
                note="Base imprimée à plat : la lame et la dent sont posées sur le plateau (dégagement dans la plaque), elles plient dans "
                     "le plan des couches. Roue à plat. Retenue axiale de la roue sur l'axe : rondelle + vis, ou goupille clipsée n° 12.")


# ------------------------------------------------------------------ n° 14 : glissière en queue d'aronde + butée
def glissiere_aronde_14(longueur=80.0, larg_rail=24.0, ep_rail=4.0, larg_bas=8.0, h_queue=4.0, angle=60.0, jeu=0.5,
                        long_chariot=20.0, toit=3.0, paroi=3.0, butee=5.0):
    """Rail (queue d'aronde mâle) + chariot (rainure femelle = profil du rail décalé de « jeu » partout).
    angle = angle des flancs avec l'horizontale (60° classique → surplomb de 30° seulement : imprimable sans support).
    Butée fixe au bout +X du rail; le chariot entre par le bout -X. Glisse le long de X.
    jeu réglable : 0,5 = règle LC3D pour pièces mobiles séparées (plus serré = plus précis, mais risque de coincer)."""
    from shapely.geometry import Polygon
    t = larg_bas + 2 * h_queue / math.tan(math.radians(angle))
    queue = [(-larg_bas / 2, ep_rail - 0.01), (larg_bas / 2, ep_rail - 0.01), (t / 2, ep_rail + h_queue), (-t / 2, ep_rail + h_queue)]
    rail = _boite(-longueur / 2, longueur / 2, -larg_rail / 2, larg_rail / 2, 0, ep_rail)
    rail = rail.union(_prisme("YZ", [(y, z) for y, z in queue], longueur))
    xb = longueur / 2 - butee
    rail = rail.union(_boite(xb, longueur / 2, -larg_rail / 2, larg_rail / 2, ep_rail - 0.01, ep_rail + h_queue + 2))
    # rainure : profil (prolongé sous le dessus du rail) décalé de jeu, angles vifs
    rain = Polygon(queue).buffer(jeu, join_style=2)
    larg_ch = t + 2 * jeu + 2 * paroi
    zc0 = ep_rail + jeu; zc1 = ep_rail + h_queue + jeu + toit
    chariot = _boite(-long_chariot / 2, long_chariot / 2, -larg_ch / 2, larg_ch / 2, zc0, zc1)
    ext = list(rain.exterior.coords)[:-1]
    chariot = chariot.cut(_prisme("YZ", ext, long_chariot + 2))
    course = xb - jeu - long_chariot / 2               # chariot posé à x = 0 → bute après « course »
    paroi_min = (larg_ch - (t + 2 * jeu)) / 2
    cotes = dict(longueur=longueur, queue=f"bas {larg_bas} / haut {t:.2f} / h {h_queue} / flancs {angle}°", jeu=jeu, chariot=f"{long_chariot} × {larg_ch:.1f} × {zc1-zc0:.1f}",
                 course=round(course, 2), butee_x=round(xb, 2), paroi_chariot=round(paroi_min, 2))
    return dict(rail=rail, chariot=chariot, cotes=cotes, calcul=dict(surplomb_flancs_deg=round(90 - angle, 0), course_mm=round(course, 2)),
                numero=14, nom="glissière queue d'aronde", note="Rail à plat; chariot à l'envers (toit sur le plateau). Jeu 0,5 partout (flancs, dessus, dessous).")


# ------------------------------------------------------------------ n° 15 : détente / cran (bosse sur lame flexible)
def detente_15(n_crans=3, pas_cran=6.0, larg_curseur=16.0, long_curseur=30.0, h_curseur=6.0, jeu=0.5, accroche=1.0,
               L_lame=20.0, h_lame=1.6, fente=1.5, ep_fond=2.0, mur=2.0, long_base=60.0, flanc=45.0):
    """Curseur qui glisse dans un canal; une lame flexible (paroi +Y du canal, posée sur le plateau) porte une bosse
    trapézoïdale à flancs 45° (pas de bille ronde) qui tombe dans des encoches en V du curseur → positions crantées,
    franchissables dans les 2 sens. Enfoncement de la bosse dans le curseur = accroche (≥ 1,0). Encoche = bosse + 0,2.
    Repère : glissement le long de X; curseur au repos centré en x = 0 (bosse dans l'encoche 0)."""
    import lc3d
    from shapely.geometry import Polygon
    W2 = larg_curseur / 2
    y_lame = W2 + jeu                                   # face intérieure de la lame
    y_ext0 = y_lame + h_lame + fente                    # face intérieure du mur extérieur
    zc0 = ep_fond + jeu; zc1 = zc0 + h_curseur
    Hl = zc1                                            # lame du plateau jusqu'en haut du curseur
    x_rac = -L_lame / 2; x_bout = L_lame / 2
    x_b = x_bout - 3.0                                  # bosse près du bout de la lame
    hb = jeu + accroche; a = 0.5
    tg = 1 / math.tan(math.radians(flanc))
    bosse_xy = [(x_b - a - hb * tg, y_lame + 0.01), (x_b - a, y_lame - hb), (x_b + a, y_lame - hb), (x_b + a + hb * tg, y_lame + 0.01)]
    L2 = long_base / 2
    base = _boite(-L2, L2, -W2 - jeu - mur, y_ext0 + mur, 0, ep_fond)
    base = base.union(_boite(-L2, L2, -W2 - jeu - mur, -W2 - jeu, 0, zc1))                 # mur -Y
    base = base.union(_boite(-L2, L2, y_ext0, y_ext0 + mur, 0, zc1))                      # mur extérieur +Y
    base = base.union(_boite(-L2, x_rac, y_lame, y_ext0 + 0.01, 0, zc1))                  # racine (bloc plein)
    base = base.cut(_boite(x_rac, L2 + 1, y_lame - 1.5, y_ext0, -1, ep_fond + 1))         # dégagement sous la lame
    base = base.union(_boite(x_rac - 0.01, x_bout, y_lame, y_lame + h_lame, 0, Hl))      # lame (sur le plateau)
    bosse = cq.Workplane("XY").polyline(bosse_xy).close().extrude(zc1 - zc0 - 0.5).translate((0, 0, zc0 + 0.5))
    # dessous de la bosse chanfreiné à 45° (pas de surplomb) : on enlève un coin
    coin = _prisme("YZ", [(y_lame - hb - 1, zc0 + 0.5 - 0.01), (y_lame + 0.01, zc0 + 0.5 - 0.01), (y_lame - hb - 1, zc0 + 0.5 + hb + 1)], 20).translate((x_b, 0, 0))
    base = base.union(bosse.cut(coin))
    cur = _boite(-long_curseur / 2, long_curseur / 2, -W2, W2, zc0, zc1)
    enc = Polygon(bosse_xy).buffer(0.2, join_style=2)
    for k in range(n_crans):
        e = cq.Workplane("XY").polyline([(x - k * pas_cran, y) for x, y in list(enc.exterior.coords)[:-1]]).close().extrude(zc1 - zc0 + 2).translate((0, 0, zc0 - 1))
        cur = cur.cut(e)
    calc = lc3d.calc_snap(x_b - x_rac, h_lame, Hl, accroche, "PETG", flanc, flanc, usage="fatigue")
    cotes = dict(n_crans=n_crans, pas_cran=pas_cran, accroche=accroche, flancs_deg=flanc, lame=f"{L_lame} × {h_lame} × {Hl:.1f}", fente=fente, jeu=jeu,
                 curseur=f"{long_curseur} × {larg_curseur} × {h_curseur}", positions_x=[k * pas_cran for k in range(n_crans)])
    return dict(base=base, curseur=cur, cotes=cotes, calcul=calc, numero=15, nom="détente à crans",
                note="Base à plat : la lame est posée sur le plateau (dégagement dans le fond) et plie dans le plan des couches. "
                     "Force pour changer de cran ≈ force_insertion_N du calcul (flancs 45° des 2 côtés : franchissable dans les 2 sens).")


LOT_A = {8: charniere_imprimee_8, 9: charniere_clipsee_9, 10: charniere_vivante_10, 11: rotule_11, 12: pivot_clipse_12,
         13: cliquet_13, 14: glissiere_aronde_14, 15: detente_15}

FICHES_A = [
    dict(num=8, nom="charnière imprimée montée", type="charnière",
         description="Charnière imprimée d'un seul coup à plat sans support : 5 nœuds Ø10, axe captif Ø3,5, jeu 0,45, ouvre 0-180°.", statut="calcule"),
    dict(num=9, nom="charnière à goupilles clipsées", type="charnière",
         description="Couvercle démontable : 2 goupilles Ø4 sur bras flexibles 14 × 1,6 clipsent (1,2 mm, face carrée) dans des trous Ø5,4 en goutte avec rampe 30°, ouvre 0-120°.", statut="calcule"),
    dict(num=10, nom="charnière vivante", type="charnière",
         description="Lame de 0,84 × 8 mm imprimée à plat entre 2 plaques : ~8 % de déformation à 90°, OK en PP/PETG, le PLA casse.", statut="calcule"),
    dict(num=11, nom="rotule à friction réglable", type="articulation",
         description="Boule Ø19 imprimée dans sa douille Ø29 (jeu 0,45, cavité à 45° sans support), ±16° vérifiés (max calculé ≈ 18°), freinée par une vis M3 + écrou captif.", statut="calcule"),
    dict(num=12, nom="axe pivot clipsé", type="fixation",
         description="Goupille fendue Ø6 à 2 méplats pour trous Ø7 : crochets 1 mm à face carrée + rampe 30°, fente 2,6, démontable en pinçant.", statut="calcule"),
    dict(num=13, nom="cliquet à lame-ressort", type="mécanisme",
         description="Roue à rochet 20 dents Ø30 + cliquet sur lame imprimée 1,5 mm (engagement 1,2 mm) : tourne dans un seul sens, la lame tire au blocage.", statut="calcule"),
    dict(num=14, nom="glissière queue d'aronde", type="guidage",
         description="Rail en queue d'aronde à flancs 60° (sans support) + chariot 20 mm à jeu 0,5 réglable, course 24,5 mm jusqu'à la butée fixe.", statut="calcule"),
    dict(num=15, nom="détente à crans", type="mécanisme",
         description="Curseur à 3 crans tous les 6 mm : bosse 45° de 1 mm sur une lame 20 × 1,6 qui tombe dans des encoches en V.", statut="calcule"),
]
