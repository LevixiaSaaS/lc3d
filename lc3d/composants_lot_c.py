"""LC3D — composants du lot C (n° 24 à 30) : ressort imprimé, bouton à ressort de stylo, paire d'engrenages,
came + suiveur, Gridfinity, serre-câble, pieds antidérapants.

Même style que composants_lc3d.py : chaque composant = une fonction `nom_N(...)` qui renvoie un dict avec
les formes CadQuery (dans SON repère, expliqué dans la docstring), `cotes`, `calcul`, `note`, `numero`, `nom`.
Statut : « calcule » (passe les vérifs LC3D) → « imprime » seulement après une VRAIE impression réussie (photo à l'appui).
Les numéros ne changent jamais. Tests : tests/composants/t_c24.py … t_c30.py.
"""
import math
import cadquery as cq


def _boite(x0, x1, y0, y1, z0, z1):
    """Boîte alignée sur les axes, donnée par ses bornes (mm)."""
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))


# ------------------------------------------------------------------ n° 24 : ressort de compression imprimé (zigzag symétrique)
def ressort_imprime_24(L=40.0, h=1.2, w=7.0, n_lames=6, course=3.0, plaque=3.0, poteau=3.0, materiau="PETG",
                       frottement_N=0.5, jeu=0.5, precharge=1.0):
    """Ressort plat en « échelle » : n lames de longueur L reliées tour à tour par un poteau au CENTRE puis par deux poteaux
    aux BOUTS (symétrique : il ne penche pas en s'écrasant). Plaque d'appui rigide en bas et en haut.
    Repère : écrasement le long de Y (plaque du bas à y = 0, plaque du haut vers +Y), largeur L en X centrée sur x = 0,
    épaisseur w en Z (z = 0 → w). S'IMPRIME À PLAT tel quel (lames dans le plan des couches, axe_flexion = (1, 0, 0)).
    Calcul : chaque demi-lame (entre 2 poteaux, portée Ls) est encastrée-guidée = 2 lames de Ls/2 en série (calc_lame);
    2 demi-lames en parallèle par lame; n lames en série. Fente entre lames = max(1,2 ; 2·δ + 0,4) où δ = course / n."""
    import lc3d
    # précharge : le logement est plus court que le ressort libre, donc il pousse déjà au repos (sinon la force tombe à 0
    # en fin de retour et la pièce ne revient pas jusqu'au bout). Écrasement total = précharge + course.
    d = (course + precharge) / n_lames                     # écrasement max par lame
    g = max(lc3d.REGLES["fente_min"], 2 * d + 0.4)         # fente au repos (se ferme de 2·δ au plus)
    Ls = (L - 3 * poteau) / 2                              # portée libre d'une demi-lame
    if Ls <= 4 * h: raise ValueError("lames trop courtes pour leur épaisseur : allonger L")
    cl = lc3d.calc_lame(Ls / 2, h, w, d / 2, materiau, frottement_N=0.0, usage="fatigue")
    F_lame = 2 * cl["force_N"]                             # 2 demi-lames en parallèle
    k = 0.8 * F_lame / (course + precharge)                # n lames en série ; ×0,8 : les éléments finis montrent ~20 % plus souple
    F_repos = k * precharge; F_lame = k * (course + precharge)
    marge = F_repos / frottement_N if frottement_N > 0 else None   # la règle ≥ 3× se juge au repos (le pire cas)
    # --- géométrie
    y = 0.0
    s = _boite(-L / 2, L / 2, 0, plaque, 0, w); y = plaque
    for i in range(n_lames + 1):
        centre = (i % 2 == 0)
        if centre:
            s = s.union(_boite(-poteau / 2, poteau / 2, y - 0.01, y + g + 0.01, 0, w))
        else:
            s = s.union(_boite(-L / 2, -L / 2 + poteau, y - 0.01, y + g + 0.01, 0, w)).union(_boite(L / 2 - poteau, L / 2, y - 0.01, y + g + 0.01, 0, w))
        y += g
        if i < n_lames:
            s = s.union(_boite(-L / 2, L / 2, y, y + h, 0, w)); y += h
    s = s.union(_boite(-L / 2, L / 2, y, y + plaque, 0, w)); H = y + plaque
    logement = _boite(-L / 2 - jeu, L / 2 + jeu, -0.01, H - precharge + 0.01, -jeu, w + jeu)
    notes = list(cl["notes"])
    if marge is not None and marge < 3: notes.append(f"force au repos {F_repos:.2f} N = {marge:.1f}× les frottements < 3× : plus de précharge, lames plus épaisses/larges ou ressort de métal")
    verdict = "✅" if not notes else "❌"
    return dict(ressort=s, logement_a_soustraire=logement, numero=24, nom="ressort de compression imprimé (zigzag)",
                cotes=dict(L=L, h_lame=h, epaisseur=w, n_lames=n_lames, fente=round(g, 2), hauteur_libre=round(H, 2),
                           hauteur_logement=round(H - precharge, 2), hauteur_ecrasee=round(H - precharge - course, 2), course=course,
                           precharge=precharge, portee_demi_lame=round(Ls, 2)),
                calcul=dict(raideur_N_mm=round(k, 3), force_repos_N=round(F_repos, 2), force_course_N=round(F_lame, 2), contrainte_MPa=cl["contrainte_MPa"],
                            limite_MPa=cl["limite_MPa"], marge_vs_frottement=None if marge is None else round(marge, 1),
                            verdict=verdict, notes=notes),
                note="Vérifié aux éléments finis (défauts) : 3,6 mm sous 5,6 N, donc raideur réelle ≈ 1,55 N/mm, le calcul simple est ~20 % trop raide. "
                     "Imprimer à plat, role='flexible', axe_flexion=(1,0,0), 100 % (6 murs). Fluage : le PETG perd de la force "
                     "s'il reste écrasé longtemps — pour un retour garanti à long terme, préférer le ressort de métal (n° 25).")


# ------------------------------------------------------------------ n° 25 : bouton-poussoir + ressort de stylo + clips anti-sortie
def bouton_ressort_25(p=10.0, T=10.0, course=4.0, jeu=0.5, mur=2.0, L_bras=14.0, h_bras=1.6, accroche=1.0, rampe=30.0,
                      retenue=90.0, ep_chapeau=3.0, guide=12.0, d_ressort=4.5, L_libre=22.0, precharge=3.0,
                      d_fil=0.5, D_moyen=4.0, spires=18, frottement_N=0.3, materiau="PETG"):
    """Bouton guidé (plongeur carré p × T dans un alésage +2·jeu), ramené par un RESSORT DE STYLO en métal posé dans un puits
    du fond (appui fixe), retenu par 2 bras clips (clip n° 1) qui glissent à l'extérieur du boîtier et s'accrochent dans
    2 fenêtres : le haut de la fenêtre est la butée anti-sortie, le dessous du chapeau sur le boîtier est la butée de fin de course.
    Repère : axe Z, boîtier posé à z = 0, bouton déjà à sa place au repos (pas besoin de le déplacer).
    Le bouton est un profil extrudé en Y (épaisseur T) : il s'imprime COUCHÉ sur sa face avant (bras dans le plan des couches).
    Le boîtier s'imprime debout (ouverture en haut, ponts des fenêtres ≤ 12 mm)."""
    import lc3d
    import composants_lc3d as C
    d_puits = d_ressort + 2 * 1.0                         # jeu 1 mm autour du ressort (règle pièce achetée)
    L_rep = L_libre - precharge                            # longueur du ressort au repos (déjà précomprimé)
    L_ecr = L_rep - course                                 # longueur bouton enfoncé
    L_bloc = (spires + 2) * d_fil                          # spires jointives (estimation)
    prof_puits = L_ecr - 1.0                               # le plongeur reste 1 mm au-dessus du fond enfoncé
    z_fond = prof_puits + 2.0                              # dessus du fond (fond plein de 2 mm sous le puits)
    z_pb = z_fond - prof_puits + L_rep                     # dessous du plongeur au repos
    z_haut = z_pb + guide                                  # dessus du boîtier
    z_ch = z_haut + course                                 # dessous du chapeau au repos (butée à fin de course)
    xi = p / 2 + jeu                                       # face intérieure des murs X
    xo = xi + mur                                          # face extérieure des murs X
    yo = T / 2 + jeu + mur
    xb = xo + jeu                                          # face intérieure des bras
    xc = xb + h_bras                                       # face extérieure des bras = bord du chapeau
    hc = (jeu + accroche) / math.tan(math.radians(rampe))  # hauteur de la rampe du crochet (crochet dépasse de jeu + accroche)
    z_bras_bas = z_ch - L_bras
    z_crochet = z_bras_bas + hc + 1.0                      # face carrée du crochet = haut de la fenêtre au repos
    z_fen_bas = z_bras_bas - course - jeu
    # --- boîtier
    boitier = _boite(-xo, xo, -yo, yo, 0, z_haut)
    boitier = boitier.cut(_boite(-xi, xi, -(T / 2 + jeu), T / 2 + jeu, z_fond, z_haut + 1))
    boitier = boitier.cut(cq.Workplane("XY").circle(d_puits / 2).extrude(prof_puits + 0.01).translate((0, 0, z_fond - prof_puits)))
    for sx in (-1, 1):
        boitier = boitier.cut(_boite(min(sx * (xi - 0.2), sx * (xo + 0.2)), max(sx * (xi - 0.2), sx * (xo + 0.2)),
                                     -(T / 2 + jeu), T / 2 + jeu, z_fen_bas, z_crochet))
    # --- bouton : chapeau + plongeur + 2 bras du clip n° 1
    bouton = _boite(-xc, xc, -T / 2, T / 2, z_ch, z_ch + ep_chapeau).union(_boite(-p / 2, p / 2, -T / 2, T / 2, z_pb, z_ch + 0.01))
    c1 = C.clip_1(L=L_bras, h=h_bras, w=T, accroche=jeu + accroche, rampe=rampe, retenue=retenue, jeu=0.3, mur=mur, materiau=materiau)
    bras_g = c1["bras"].translate((-(xb + h_bras / 2), 0, z_ch))                       # crochet vers +X (vers le boîtier)
    bras_d = c1["bras"].rotate((0, 0, 0), (0, 0, 1), 180).translate((xb + h_bras / 2, 0, z_ch))
    bouton = bouton.union(bras_g).union(bras_d)
    ressort_ecrase = cq.Workplane("XY").circle(d_ressort / 2).extrude(L_ecr - 0.05).translate((0, 0, z_fond - prof_puits))
    # --- calculs
    snap = lc3d.calc_snap(L_bras, h_bras, T, accroche, materiau, rampe, retenue)
    rs = lc3d.calc_ressort(d_fil, D_moyen, spires, L_libre - L_ecr)
    k = rs["raideur_N_mm"]; F_repos = k * precharge; F_fond = k * (precharge + course)
    marge = F_repos / frottement_N
    notes = list(snap["notes"]) + list(rs["notes"])
    if marge < 3: notes.append(f"force au repos {F_repos:.2f} N < 3× frottements")
    if L_ecr < L_bloc + 1: notes.append(f"ressort trop écrasé : {L_ecr:.1f} mm pour ~{L_bloc:.1f} mm à spires jointives")
    return dict(boitier=boitier, bouton=bouton, ressort_ecrase=ressort_ecrase, numero=25, nom="bouton-poussoir à ressort de stylo",
                cotes=dict(plongeur=f"{p} × {T}", alesage=f"{p + 2 * jeu} × {T + 2 * jeu}", course=course, puits_ressort=f"Ø{d_puits} × {prof_puits:.1f}",
                           ressort=f"Ø{d_ressort} × {L_libre} libre, {L_rep} au repos, {L_ecr} enfoncé", bras=f"L {L_bras} × h {h_bras} × w {T}",
                           crochet=f"accroche {accroche} (+{jeu} de jeu), rampe {rampe}°, retenue {retenue}°",
                           boitier=f"{2 * xo:.1f} × {2 * yo:.1f} × {z_haut:.1f}", hauteur_totale=round(z_ch + ep_chapeau, 2),
                           z_fond=round(z_fond, 2), z_haut=round(z_haut, 2), z_chapeau=round(z_ch, 2), z_crochet=round(z_crochet, 2)),
                calcul=dict(raideur_ressort_N_mm=k, force_repos_N=round(F_repos, 2), force_enfonce_N=round(F_fond, 2),
                            contrainte_ressort_MPa=rs["contrainte_MPa"], marge_vs_frottement=round(marge, 1),
                            clip=dict(deformation_pct=snap["deformation_pct"], contrainte_MPa=snap["contrainte_MPa"],
                                      poussee_N=snap["force_insertion_N"], retrait=snap["retrait_lecture"]),
                            verdict="✅" if not notes else "❌", notes=notes),
                note="Ressort de stylo typique (Ø4,5 × 22, fil 0,5) : MESURER le vrai ressort (Ø ext., longueur libre) et refaire "
                     "le calcul. Frottements estimés à 0,3 N. Les bras sont dehors : on peut les écarter à la main pour démonter.")


# ------------------------------------------------------------------ n° 26 : paire d'engrenages droits sur axes + support
def paire_engrenages_26(module=1.5, za=20, zb=40, epaisseur=6.0, d_axe=5.0, jeu_axe=0.25, jeu_entraxe=0.35,
                        ep_support=4.0, collerette=1.0, depasse=1.5, bord=4.0):
    """Pignon + roue (bd_warehouse SpurGear, angle de pression 20°) sur 2 axes fixes d'un support plat.
    Repère : pignon centré en (0, 0), roue en (entraxe, 0); les roues vont de z = 0 à z = épaisseur (posées sur une
    collerette Ø axe+4 qui les éloigne du support); dessus du support à z = -collerette.
    Entraxe = théorique + jeu_entraxe (0,35 → jeu entre dents ≈ 2·0,35·tan 20° ≈ 0,25 mm).
    Jeu sur l'axe : 0,25/côté (EXCEPTION à la règle 0,5 : un trou trop lâche change l'entraxe et les dents sautent)."""
    import lc3d
    from bd_warehouse.gear import SpurGear
    c = lc3d.calc_engrenage(module, za, zb, jeu_entraxe=jeu_entraxe)
    ent = c["entraxe_conseille_FDM"]
    def roue(z):
        g = SpurGear(module=module, tooth_count=z, pressure_angle=20, thickness=epaisseur)
        g = cq.Workplane("XY").add(cq.Shape.cast(g.wrapped)).translate((0, 0, epaisseur / 2))
        return g.cut(cq.Workplane("XY").circle(d_axe / 2 + jeu_axe).extrude(epaisseur + 2).translate((0, 0, -1)))
    ra, rb = c["diam_tete_a"] / 2, c["diam_tete_b"] / 2
    x0, x1 = -ra - bord, ent + rb + bord; ymax = max(ra, rb) + bord
    support = _boite(x0, x1, -ymax, ymax, -collerette - ep_support, -collerette)
    for cx in (0.0, ent):
        support = support.union(cq.Workplane("XY").circle(d_axe / 2 + 2).extrude(collerette + 0.01).translate((cx, 0, -collerette - 0.01)))
        support = support.union(cq.Workplane("XY").circle(d_axe / 2).extrude(collerette + epaisseur + depasse + 0.01).translate((cx, 0, -collerette - 0.01)))
    jeu_dents = 2 * jeu_entraxe * math.tan(math.radians(20))
    return dict(pignon=roue(za), roue=roue(zb), support=support, entraxe=ent, numero=26, nom="paire d'engrenages droits sur axes",
                phase_roue_deg=180.0 / zb,
                cotes=dict(module=module, dents=f"{za}/{zb}", rapport=c["rapport_b_sur_a"], entraxe_theorique=c["entraxe_theorique"],
                           entraxe=ent, jeu_entre_dents=round(jeu_dents, 2), d_tete=f"{c['diam_tete_a']} / {c['diam_tete_b']}",
                           epaisseur=epaisseur, axe=f"Ø{d_axe}", trou=f"Ø{d_axe + 2 * jeu_axe}", support=f"{x1 - x0:.1f} × {2 * ymax:.1f}"),
                calcul=dict(verdict=c["verdict"], notes=c["notes"]),
                note="Imprimer les roues à plat. Mettre la roue menée tournée de phase_roue_deg pour que les dents s'emboîtent. "
                     "Retenue en hauteur à prévoir dans le produit (couvercle à 0,5 mm au-dessus des axes) ; graisse sèche ou PTFE conseillée.")


# ------------------------------------------------------------------ n° 27 : came excentrique + suiveur guidé
def came_suiveur_27(course=6.0, R_came=12.0, ep_came=8.0, d_axe=8.0, jeu=0.5, mur=2.0, ep_paroi=3.0, levre=3.0,
                    hex_plats=8.0, d_ressort=4.5, L_libre=22.0, precharge=2.0, d_fil=0.5, D_moyen=4.0, spires=18,
                    hauteur_guide=16.0, materiau="PETG"):
    """Came = disque Ø 2·R_came décentré de e = course/2 sur un axe fixe Ø d_axe (trou +1,0), entraînée par un moyeu hexagonal;
    suiveur = barre à fond plat qui monte/descend dans un guide (jeu 0,5/côté). Levée = e·(1 − cos φ) : sinusoïde exacte
    (fond plat sur cercle décentré). Une lèvre au bas du suiveur, devant la came, l'empêche de sortir de son axe.
    Retour : 2 ressorts de stylo (poches carrées 6,5 dans le guide et dans la tête du suiveur).
    Repère : axe de la came = Y passant par l'origine; paroi du support dans le plan XZ (y = -ep_paroi → 0);
    au repos la came est en BAS (centre à z = -e) et le suiveur est en bas (fond à z = R_came - e).
    Impression : support couché sur le dos (axe debout), came sur sa face arrière, suiveur sur sa face avant (lèvre au plateau)."""
    import lc3d
    e = course / 2
    yc0, yc1 = jeu, jeu + ep_came                          # came entre la paroi et la lèvre
    b = max(2 * e + 4.0, 10.0)                             # largeur du suiveur (le point de contact se promène de ±e)
    yb0, yb1 = jeu, yc1 + jeu + 2.5                         # profondeur du suiveur (lèvre de 2,5 devant la came)
    z_f = R_came - e                                       # fond du suiveur au repos
    z_g0 = R_came + e + 1.0                                # dessous du guide (au-dessus du sommet de la came)
    z_g1 = z_g0 + hauteur_guide
    poche = d_ressort + 2.0; prof_g = 6.0; prof_t = 5.0
    xs = b / 2 + jeu + mur + poche / 2                     # position des ressorts
    xg = xs + poche / 2 + 1.5                              # demi-largeur du guide
    L_rep = L_libre - precharge
    z_t = z_g1 - prof_g + L_rep - prof_t                   # dessous de la tête au repos
    ep_tete = prof_t + 2.0
    # --- support : paroi + axe + guide avec poches de ressort
    zmin = -(R_came + e) - 3.0; zmax = z_g1 + 2.0
    support = _boite(-xg - 3, xg + 3, -ep_paroi, 0, zmin, zmax)
    prof_trou = ep_came - 1.5                              # trou borgne : 1,5 mm de matière devant (le moyeu hexagonal repose dessus)
    y_axe = yc0 + prof_trou - jeu                          # bout de l'axe à 0,5 mm du fond du trou
    support = support.union(cq.Workplane("XZ").circle(d_axe / 2).extrude(-(y_axe + 0.01)).translate((0, -0.01, 0)))    # axe le long de +Y
    gx = b / 2 + jeu; gy = yb1 + jeu
    guide = _boite(-xg, xg, -0.01, gy + mur, z_g0, z_g1).cut(_boite(-gx, gx, -1, gy, z_g0 - 1, z_g1 + 1))
    yp = (yb0 + yb1) / 2                                   # axe des ressorts : milieu de la tête du suiveur
    for sx in (-1, 1):
        guide = guide.cut(_boite(sx * xs - poche / 2, sx * xs + poche / 2, yp - poche / 2, yp + poche / 2, z_g1 - prof_g, z_g1 + 1))
    support = support.union(guide)
    for sx in (-1, 1):   # 2 trous de fixation Ø3,4 dans la paroi, sous la came
        support = support.cut(cq.Workplane("XZ").center(sx * (xg - 1), zmin + 5).circle(1.7).extrude(-(ep_paroi + 2)).translate((0, -ep_paroi - 1, 0)))
    # --- came : disque décentré + moyeu hexagonal sur l'axe (trou borgne Ø d_axe + 1 côté paroi)
    came = cq.Workplane("XZ").center(0, -e).circle(R_came).extrude(-ep_came).translate((0, yc0, 0))
    came = came.union(cq.Workplane("XZ").polygon(6, hex_plats / math.cos(math.radians(30))).extrude(-(6.0 + 0.01)).translate((0, yc1 - 0.01, 0)))
    came = came.cut(cq.Workplane("XZ").circle((d_axe + 1.0) / 2).extrude(-(prof_trou + 0.01)).translate((0, yc0 - 0.01, 0)))
    # --- suiveur : barre + lèvre + tête avec poches
    tete_x = xg
    suiveur = _boite(-b / 2, b / 2, yb0, yb1, z_f, z_t + 0.01)
    suiveur = suiveur.union(_boite(-b / 2, b / 2, yc1 + jeu, yb1, z_f - levre, z_f + 0.01))
    tete = _boite(-tete_x, tete_x, yb0, yb1, z_t, z_t + ep_tete)
    for sx in (-1, 1):
        tete = tete.cut(_boite(sx * xs - poche / 2, sx * xs + poche / 2, yp - poche / 2, yp + poche / 2, z_t - 1, z_t + prof_t))
    suiveur = suiveur.union(tete)
    # --- calculs
    rs = lc3d.calc_ressort(d_fil, D_moyen, spires, precharge + course)
    k2 = 2 * rs["raideur_N_mm"]; L_haut = L_rep - course; L_bloc = (spires + 2) * d_fil
    notes = list(rs["notes"])
    if L_haut < L_bloc + 1: notes.append(f"ressorts trop écrasés en haut : {L_haut:.1f} mm pour ~{L_bloc:.1f} jointif")
    hex_r = hex_plats / 2 / math.cos(math.radians(30))
    if z_f - levre < hex_r + jeu: notes.append("la lèvre touche le moyeu hexagonal : réduire la lèvre ou le moyeu")
    return dict(support=support, came=came, suiveur=suiveur, numero=27, nom="came excentrique + suiveur guidé",
                excentricite=e, fond_suiveur_repos=z_f,
                cotes=dict(course=course, excentricite=e, came=f"Ø{2 * R_came} × {ep_came}", axe=f"Ø{d_axe} × {y_axe:.1f}", trou_came=f"Ø{d_axe + 1.0} borgne {prof_trou}",
                           suiveur=f"{b} × {yb1 - yb0:.1f}", guide=f"{2 * gx:.1f} × {gy:.1f} sur {hauteur_guide}", hex=f"{hex_plats} sur plats",
                           levee="e·(1 − cos φ)", poches_ressort=f"{poche} carré, prof. {prof_g} (guide) / {prof_t} (tête)"),
                calcul=dict(ressorts=f"2 ressorts de stylo, k total {k2:.2f} N/mm", force_bas_N=round(k2 * precharge, 2),
                            force_haut_N=round(k2 * (precharge + course), 2), longueur_ressort_haut=L_haut,
                            contrainte_ressort_MPa=rs["contrainte_MPa"], verdict="✅" if not notes else "❌", notes=notes),
                note="Rotation libre dans les 2 sens. Le suiveur s'enlève par le haut quand on le tire (les ressorts le poussent vers la came). "
                     "Course réglable : changer `course` (le guide et les ressorts suivent).")


# ------------------------------------------------------------------ n° 28 : Gridfinity (bac + plaque)
def gridfinity_28(nx=1, ny=1, hauteur_u=3, cases=(1, 1), aimants=False, etiquette=False, levre=True, plaque_nx=None, plaque_ny=None):
    """Enveloppe simple des fonctions Gridfinity de lc3d : un bac nx × ny cases de 42 mm, hauteur_u × 7 mm, cloisons `cases`,
    aimants 6 × 2 optionnels, et la plaque de base (par défaut de la même taille que le bac).
    Repère : bac et plaque centrés sur (0, 0), dessous à z = 0 (le bac se pose dans la plaque, tous deux sur la table)."""
    import lc3d
    bac = lc3d.gridfinity_bac(nx, ny, hauteur_u, cases[0], cases[1], aimants=aimants, levre=levre, etiquette=etiquette)
    px, py = plaque_nx or nx, plaque_ny or ny
    plaque = lc3d.gridfinity_plaque(px, py)
    bb = bac.val().BoundingBox(); bp = plaque.val().BoundingBox()
    return dict(bac=bac, plaque=plaque, numero=28, nom="Gridfinity (bac + plaque)",
                cotes=dict(bac=f"{bb.xlen:.1f} × {bb.ylen:.1f} × {bb.zlen:.1f}", plaque=f"{bp.xlen:.1f} × {bp.ylen:.1f} × {bp.zlen:.2f}",
                           pas=lc3d.GF["pas"], unite_h=lc3d.GF["unite_h"], cases=f"{cases[0]} × {cases[1]}", aimants=aimants),
                calcul=dict(verdict="✅", notes=[]),
                note="Norme Gridfinity (Zack Freedman) : 42 mm par case, 7 mm par unité de hauteur, base à 45°. Bac à plat, plaque à plat.")


# ------------------------------------------------------------------ n° 29 : passe-câble + serre-câble anti-arrachement
def serre_cable_29(d_min=3.0, d_max=8.0, longueur=20.0, ep_bride=5.0, vis="M3", serrage_min=0.5, jeu_vis_cable=1.0,
                   prof_trou=16.0, nervures=3, mu=0.3, effort_vis_N=50.0):
    """Base avec gorge en V à 90° + bride avec gorge en V à 90°, serrées par 2 vis M3 dans des inserts à chaud.
    Les deux V forment un losange : il serre tout câble de d_min à d_max (le jeu entre base et bride s'ajuste).
    Nervures transversales dans la gorge de la base pour mordre la gaine (anti-arrachement).
    Repère : câble le long de X; dessus de la base à z = 0 (gorge vers le bas), bride posée au-dessus, gorge vers le bas.
    `bride_a(d)` donne la hauteur du dessous de la bride pour un câble Ø d, `centre_cable(d)` la hauteur de son axe."""
    import lc3d
    Vd = (d_min - serrage_min) / math.sqrt(2)              # profondeur de chaque V : à jeu 0, losange de Ø d_min − serrage
    def jeu_pour(d): return max(0.0, d * math.sqrt(2) - 2 * Vd)
    g_max = jeu_pour(d_max)
    rv = lc3d.TROUS_FDM["passage"][vis] / 2
    s = d_max / 2 + jeu_vis_cable + rv                     # entraxe des vis par rapport au câble
    ins = lc3d.TROUS_FDM["insert"][vis]; ins_p = lc3d.TROUS_FDM["insert_prof"][vis]
    Y = s + ins / 2 + 2.2                                  # demi-largeur
    Hb = prof_trou + 2.0
    def v_prisme(prof, z0, sens):
        """Prisme triangulaire le long de X, ouverture sur le plan z0, pointe à z0 + sens·prof (sens -1 = vers le bas)."""
        return (cq.Workplane("YZ").polyline([(-prof - 0.3, z0 - sens * 0.3), (prof + 0.3, z0 - sens * 0.3), (0, z0 + sens * prof)]).close()
                .extrude(longueur + 2).translate((-longueur / 2 - 1, 0, 0)))
    base = _boite(-longueur / 2, longueur / 2, -Y, Y, -Hb, 0)
    base = base.union(_boite(-longueur / 2 - 10, longueur / 2 + 10, -Y, Y, -Hb, -Hb + 4))       # pattes de fixation
    base = base.cut(v_prisme(Vd, 0, -1))
    for i in range(nervures):   # nervures : trapèze 2,4 → 0,9, hauteur 0,75, au fond du V
        x = (i - (nervures - 1) / 2) * (longueur / (nervures + 0.5))
        nerv = cq.Workplane("XZ").polyline([(x - 1.2, -Vd - 0.01), (x + 1.2, -Vd - 0.01), (x + 0.45, -Vd + 0.75), (x - 0.45, -Vd + 0.75)]).close().extrude(Vd * 2, both=True)
        base = base.union(nerv.intersect(_boite(-longueur / 2, longueur / 2, -Y, Y, -Hb, 0.0)).intersect(v_prisme(Vd, 0, -1)))
    for sy in (-1, 1):
        base = base.cut(cq.Workplane("XY").circle(ins / 2).extrude(ins_p + 1.0).translate((0, sy * s, -(ins_p + 1.0))))
        base = base.cut(cq.Workplane("XY").circle(rv).extrude(prof_trou).translate((0, sy * s, -prof_trou)))
    for sx in (-1, 1):
        base = base.cut(cq.Workplane("XY").circle(rv).extrude(10).translate((sx * (longueur / 2 + 5), 0, -Hb - 1)))
    bride = _boite(-longueur / 2, longueur / 2, -Y, Y, 0, ep_bride).cut(v_prisme(Vd, 0, 1))
    for sy in (-1, 1):
        bride = bride.cut(cq.Workplane("XY").circle(rv).extrude(ep_bride + 2).translate((0, sy * s, -1)))
    P = 2 * effort_vis_N
    F = 2 * math.sqrt(2) * mu * P                          # 2 V, 2 lignes de contact chacun, N = P/√2
    L_vis = math.ceil(ep_bride + g_max + ins_p)            # vis assez longue pour le plus gros câble
    L_vis = min([l for l in (12, 16, 20, 25, 30) if l >= L_vis] or [30])
    notes = []
    if ep_bride + jeu_pour(d_min) + prof_trou < L_vis: notes.append("vis trop longue pour le petit câble : approfondir le trou")
    return dict(base=base, bride=bride, numero=29, nom="passe-câble + serre-câble anti-arrachement",
                bride_a=jeu_pour, centre_cable=lambda d: jeu_pour(d) / 2, entraxe_vis=s,
                cotes=dict(cables=f"Ø{d_min} à Ø{d_max}", gorges="2 V à 90°", profondeur_V=round(Vd, 2), jeu_bride_dmin=round(jeu_pour(d_min), 2),
                           jeu_bride_dmax=round(g_max, 2), vis=f"2 × {vis} × {L_vis} + 2 inserts à chaud", entraxe_vis=round(2 * s, 2),
                           base=f"{longueur + 20} × {2 * Y:.1f} × {Hb}", bride=f"{longueur} × {2 * Y:.1f} × {ep_bride}"),
                calcul=dict(tenue_N=round(F, 0), hypothese=f"{effort_vis_N:.0f} N par vis (serré à la main), μ = {mu} gaine/PETG, sans compter les nervures",
                            verdict="✅" if not notes else "❌", notes=notes),
                note="Base et bride s'impriment gorge vers le haut (V à 45°, sans support). La tenue réelle dépend de la gaine : "
                     "serrer jusqu'à ce que la gaine soit pincée, pas écrasée.")


# ------------------------------------------------------------------ n° 30 : pieds antidérapants (caoutchouc autocollant ou TPU clipsé)
def pied_antiderapant_30(d_caoutchouc=12.7, h_caoutchouc=3.5, saillie=2.5, ep_fond=3.0, d_tige=8.0, jeu_tige=0.25,
                         fente=2.4, accroche=1.0, rampe=30.0, retenue=45.0, d_patin=18.0, jeu_logement=1.0):
    """Deux façons de faire tenir un pied sous un boîtier (fond d'épaisseur ep_fond, dessous du fond à z = 0, fond vers +Z) :
    (a) `logement_a_soustraire` : poche pour pied de caoutchouc autocollant Ø d × h (jeu 1 mm autour) qui dépasse de `saillie`;
    (b) `pied_tpu` + `trou_a_soustraire` : pied imprimé en TPU, patin Ø d_patin × saillie, tige fendue Ø d_tige à 2 crochets
        qui clipse dans un trou Ø d_tige + 2·jeu (rampe 30° pour entrer, face de retenue 45° : s'enlève en tirant fort, imprimable).
    Les deux dépassent de la même hauteur (`saillie`) : on peut les mélanger sur un même boîtier."""
    import lc3d
    prof = h_caoutchouc - saillie
    logement = cq.Workplane("XY").circle(d_caoutchouc / 2 + jeu_logement).extrude(prof + 0.01).translate((0, 0, -0.01))
    rt = d_tige / 2 + jeu_tige                              # rayon du trou
    rc = rt + accroche                                      # rayon du crochet
    trou = cq.Workplane("XY").circle(rt).extrude(ep_fond + 2).translate((0, 0, -1))
    h_ret = (rc - rt) / math.tan(math.radians(retenue))     # hauteur de la face de retenue (45° : = accroche)
    h_ramp = (rc - d_tige / 2 + 0.5) / math.tan(math.radians(rampe))
    z1 = ep_fond + h_ret; z2 = z1 + 0.6; z3 = z2 + h_ramp
    r_bout = d_tige / 2 - 0.5
    prof_tige = [(0, -0.01), (d_tige / 2, -0.01), (d_tige / 2, ep_fond), (rc, z1), (rc, z2), (r_bout, z3), (0, z3)]
    tige = cq.Workplane("XZ").polyline(prof_tige).close().revolve(360, (0, 0, 0), (0, 1, 0))
    patin = cq.Workplane("XY").circle(d_patin / 2).extrude(saillie).translate((0, 0, -saillie)).edges("<Z").chamfer(0.6)
    pied = patin.union(tige)
    L_fente = z3 + 0.5
    pied = pied.cut(_boite(-fente / 2, fente / 2, -rc - 0.5, rc + 0.5, -0.5, z3 + 1))   # fente limitée à la tige
    h_bras = d_tige / 2 - fente / 2
    w_bras = 2 * math.sqrt(max((d_tige / 2) ** 2 - (fente / 2) ** 2, 0.1))
    snap = lc3d.calc_snap(L_fente, h_bras, w_bras, accroche, "TPU", rampe, retenue)
    notes = list(snap["notes"])
    if fente < 2 * accroche + 0.2: notes.append("fente trop étroite : les 2 crochets ne peuvent pas rentrer de l'accroche")
    if prof < 0.6: notes.append("poche presque nulle : le caoutchouc n'est pas tenu sur le côté")
    return dict(logement_a_soustraire=logement, pied_tpu=pied, trou_a_soustraire=trou, numero=30, nom="pied antidérapant (caoutchouc ou TPU clipsé)",
                L_bras=L_fente, h_bras=h_bras, w_bras=w_bras,
                cotes=dict(caoutchouc=f"Ø{d_caoutchouc} × {h_caoutchouc} (à mesurer)", poche=f"Ø{d_caoutchouc + 2 * jeu_logement} × {prof:.1f}",
                           saillie=saillie, trou_tpu=f"Ø{2 * rt}", tige=f"Ø{d_tige} fendue {fente}", crochet=f"Ø{2 * rc} (accroche {accroche})",
                           patin=f"Ø{d_patin} × {saillie}", fond=ep_fond),
                calcul=dict(clip_tpu=dict(deformation_pct=snap["deformation_pct"], poussee_par_bras_N=snap["force_insertion_N"],
                                          poussee_totale_N=round(2 * snap["force_insertion_N"], 1),
                                          retrait_total_N=(round(2 * snap["force_retrait_N"], 1) if not isinstance(snap["force_retrait_N"], str) else snap["force_retrait_N"])),
                            verdict="✅" if not notes else "❌", notes=notes),
                note="Pied TPU 95A imprimé patin au plateau, 100 % (6 murs). Les 2 bras plient à travers les couches : acceptable en TPU "
                     "(couches très bien soudées), PAS en PETG. Fond du boîtier imprimé poches vers le haut (sinon pont de Ø14,7).")


LOT_C = {24: ressort_imprime_24, 25: bouton_ressort_25, 26: paire_engrenages_26, 27: came_suiveur_27,
         28: gridfinity_28, 29: serre_cable_29, 30: pied_antiderapant_30}

FICHES_C = [
    dict(num=24, nom="ressort imprimé zigzag", type="ressort",
         description="Ressort plat en échelle 40 × 25 × 7 mm, 6 lames de 1,2 mm, précharge 1 mm + course 3 mm : ≈ 1,7 N au repos → ≈ 6,9 N enfoncé (raideur corrigée −20 % selon les éléments finis), imprimé à plat.", statut="calcule"),
    dict(num=25, nom="bouton à ressort de stylo", type="bouton",
         description="Bouton 10 × 10 mm guidé (jeu 0,5), course 4 mm, ressort de stylo Ø4,5 dans un puits Ø6,5, 2 clips anti-sortie.", statut="calcule"),
    dict(num=26, nom="paire d'engrenages sur axes", type="engrenage",
         description="Pignon 20 dents et roue 40 dents module 1,5 sur axes Ø5 (trou Ø5,5), entraxe théorique + 0,35 mm, support plat.", statut="calcule"),
    dict(num=27, nom="came + suiveur", type="mecanisme",
         description="Came Ø24 × 8 décentrée de 3 mm sur axe Ø8 (trou Ø9, course 6 mm réglable), suiveur à fond plat guidé à 0,5 mm, 2 ressorts de stylo.", statut="calcule"),
    dict(num=28, nom="Gridfinity bac + plaque", type="rangement",
         description="Bac et plaque Gridfinity standard (cases de 42 mm, hauteur 7 mm par unité) avec cloisons et aimants en option.", statut="calcule"),
    dict(num=29, nom="serre-câble anti-arrachement", type="cable",
         description="Base et bride à gorges en V à 90° serrées par 2 vis M3 + inserts, pour câbles Ø3 à Ø8, nervures dans la gorge.", statut="calcule"),
    dict(num=30, nom="pied antidérapant", type="pied",
         description="Poche Ø14,7 pour pied caoutchouc Ø12,7 ou pied TPU Ø18 à tige fendue Ø8 clipsée dans un trou Ø8,5, les deux dépassent de 2,5 mm.", statut="calcule"),
]
