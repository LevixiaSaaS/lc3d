"""LC3D — catalogue de composants, lot B (n° 16 à 23).
Même style que composants_lc3d.py : chaque composant = une fonction paramétrique qui renvoie les formes CadQuery
+ ses cotes + ses calculs + une note. Statut « calculé » (passe les vérifs LC3D sur son modèle de test
tests/composants/t_cNN.py) → « validé » seulement après une VRAIE impression réussie (photo à l'appui).
Règles suivies (buse 0,4, couche 0,2, PETG) : jeu mobile ≥ 0,5 mm par côté, fentes ≥ 1,2 mm, murs ≥ 1,5 mm,
surplombs ≤ 45°, accroche de clip ≥ 1 mm avec face de retenue + rampe 30°, trous horizontaux en goutte.
"""
import math
import cadquery as cq

MAT = "PETG"


def _mat(materiau=MAT):
    import lc3d
    return lc3d.MATERIAUX[materiau]


def _secteur(r_in, r_out, a0, a1, h, z0=0.0, n=24):
    """Secteur d'anneau (angles en degrés, sens trigo) de r_in à r_out, de z0 à z0 + h."""
    pts = [(r_out * math.cos(math.radians(a0 + (a1 - a0) * k / n)), r_out * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]
    pts += [(r_in * math.cos(math.radians(a1 - (a1 - a0) * k / n)), r_in * math.sin(math.radians(a1 - (a1 - a0) * k / n))) for k in range(n + 1)]
    return cq.Workplane("XY").polyline(pts).close().extrude(h).translate((0, 0, z0))


def _obround(longueur, largeur, h, z0=0.0):
    """Fente arrondie (bouts en demi-cercle), longueur en X, largeur en Y, de z0 à z0 + h."""
    return cq.Workplane("XY").slot2D(longueur, largeur).extrude(h).translate((0, 0, z0))


def _rect_arrondi(L, l, r, h, z0=0.0):
    return cq.Workplane("XY").sketch().rect(L, l).vertices().fillet(r).finalize().extrude(h).translate((0, 0, z0))


# ------------------------------------------------------------------ n° 19 : jonction fixe en queue d'aronde
def assemblage_aronde_19(profondeur=10.0, largeur_col=10.0, angle=15.0, epaisseur=8.0, fond=1.6, jeu=0.3, jeu_fond=0.3,
                         nb=2, pas=30.0, materiau=MAT):
    """Queue d'aronde pour joindre 2 pièces trop grandes pour le plateau (pièce A = queues, pièce B = mortaises).
    Les deux pièces s'impriment À PLAT : le profil en trapèze est dans le plan des couches (aucun surplomb, flancs pleins).
    Repère : joint dans le plan x = 0. A est du côté x ≤ 0 (queues vers +X), B du côté x ≥ jeu. Plaques de z = 0 à z = epaisseur.
    La mortaise de B est borgne (fond de `fond` mm en bas) : A descend par le haut et s'arrête sur ce fond.
    jeu = jeu dessiné par flanc : 0,3 (l'impression referme ~0,13 mm → ≈ 0,17 mm réel : glisse à la main sans forcer;
    colle CA/époxy dans le jeu pour du permanent). 0,15 dessiné = 37 % des impressions coincent (simulation LC3D).
    A imprimer à l'envers (dessus sur le plateau) : la queue part alors du plateau."""
    t = math.tan(math.radians(angle))
    tete = largeur_col + 2 * profondeur * t
    prof_q = [(0, -largeur_col / 2), (profondeur, -tete / 2), (profondeur, tete / 2), (0, largeur_col / 2)]
    z0 = fond + jeu_fond                                  # bas de la queue (au-dessus du fond de la mortaise)
    hq = epaisseur - z0
    ys = [(k - (nb - 1) / 2) * pas for k in range(nb)]
    queue = None; mort = None
    for y in ys:
        q = cq.Workplane("XY").polyline(prof_q).close().extrude(hq).translate((-0.01, y, z0))   # -0,01 : soudée au corps de A
        # mortaise = profil de la queue agrandi de `jeu` partout (flancs + bout), ouverte du côté du joint
        pm = cq.Workplane("XY").polyline([(-1.0, -largeur_col / 2 - 1.0 * t), (profondeur, -tete / 2), (profondeur, tete / 2), (-1.0, largeur_col / 2 + 1.0 * t)]).close()
        m = pm.offset2D(jeu, "intersection").extrude(epaisseur + 1 - fond).translate((0, y, fond))
        queue = q if queue is None else queue.union(q)
        mort = m if mort is None else mort.union(m)
    M = _mat(materiau)
    h_col = hq
    F_col = largeur_col * h_col * M["sigma"]                # traction à la rupture du col (couches dans le plan : pleine résistance)
    # arrachement : les flancs à `angle` poussent la mortaise vers l'extérieur ; la paroi de B à côté de la tête doit tenir
    calc = dict(section_col_mm2=round(largeur_col * h_col, 1), traction_rupture_col_N=round(F_col * nb),
                traction_admissible_N=round(F_col * nb / 3), note_calc="admissible = rupture / 3 (PETG plein, sans colle); "
                "colle CA sur les flancs : environ ×2")
    return dict(queue=queue, mortaise_a_soustraire=mort, calcul=calc, positions_y=ys,
                cotes=dict(profondeur=profondeur, largeur_col=largeur_col, largeur_tete=round(tete, 2), angle=angle, epaisseur=epaisseur,
                           fond=fond, jeu_flanc=jeu, jeu_fond=jeu_fond, nb=nb, pas=pas, hauteur_queue=round(hq, 2)),
                note="Imprimer A et B à plat (A à l'envers). Pousser A dans B par le haut jusqu'au fond. Jeu 0,3 dessiné ≈ 0,17 réel : "
                     "glisse ajusté; une goutte de colle CA sur les flancs pour du permanent. Matière de B à côté d'une tête : ≥ 5 mm.",
                numero=19, nom="jonction en queue d'aronde")


# ------------------------------------------------------------------ n° 21 : trous pour vis directe dans le plastique (+ bossage)
TAILLES_VIS_DIRECTE = ("M2", "M2.5", "M3", "M4", "M5")


def tableau_vis_directe():
    """Tableau des diamètres (mm) pour visser directement dans le PETG imprimé (buse 0,4), M2 à M5.
    pilote = trou à dessiner (le filet taille son chemin); passage = trou de la pièce du dessus;
    bossage = Ø extérieur mini du tube (mur ≥ 2 mm et ≥ 0,5 × trou); prise = filet engagé mini (2,5 × D);
    profondeur = prise + 2,5 (bout de vis + copeaux); lamage d'entrée = Ø D + 0,2 × 0,6 de creux (pas de « volcan » qui soulève le couvercle)."""
    import lc3d
    T = {}
    for t in TAILLES_VIS_DIRECTE:
        D = float(t[1:]); b = lc3d.calc_bossage(t, "auto_taraudage")
        prise = 2.5 * D
        T[t] = dict(pilote=lc3d.TROUS_FDM["auto_taraudage"][t], passage=lc3d.TROUS_FDM["passage"][t], bossage=b["diametre_bossage_min"],
                    bord_min=b["distance_bord_min"], prise_min=round(prise, 2), profondeur=math.ceil((prise + 2.5) * 2) / 2,
                    lamage_entree=round(D + 0.2, 2), interference_rayon=round((D - lc3d.TROUS_FDM["auto_taraudage"][t]) / 2, 2))
    return T


def trou_vis_directe_21(taille="M3", hauteur_bossage=None, horizontal=False, traversee=3.0, longueur_trou=None):
    """Trou pilote pour vis vissée directement dans le plastique (sans insert ni écrou) + bossage autour.
    Repère : ouverture du trou à z = 0 (dessus du bossage), le trou descend vers -Z; le bossage va de -hauteur à 0.
    horizontal=True : trou en goutte le long de X (pointe à 45° vers le haut, imprimable sans support), ouverture à x = 0.
    traversee : épaisseur de la pièce serrée sous la tête (sert à choisir la longueur de vis avec calc_vis).
    Bon pour 5 à 10 montages/démontages; au-delà, prendre un insert (composant n° 2)."""
    import lc3d
    T = tableau_vis_directe()[taille]
    prof = longueur_trou or T["profondeur"]
    hb = hauteur_bossage or prof + 1.2                          # 1,2 mm de fond sous le trou (6 couches)
    if horizontal:
        trou = lc3d.goutte(T["pilote"], 2 * prof).translate((-prof, 0, 0))
        trou = trou.union(cq.Workplane("YZ").circle(T["lamage_entree"] / 2).extrude(-0.6))
        boss = cq.Workplane("YZ").circle(T["bossage"] / 2).extrude(-hb)
    else:
        trou = cq.Workplane("XY").circle(T["pilote"] / 2).extrude(prof).translate((0, 0, -prof))
        trou = trou.union(cq.Workplane("XY").circle(T["lamage_entree"] / 2).extrude(0.6).translate((0, 0, -0.6)))
        boss = cq.Workplane("XY").circle(T["bossage"] / 2).extrude(hb).translate((0, 0, -hb))
    calc = lc3d.calc_vis(taille, traversee=traversee, prof_trou=prof, prise="auto_taraudage", tete="chc")
    return dict(bossage=boss.cut(trou), trou_a_soustraire=trou, tableau=tableau_vis_directe(), calcul=calc,
                cotes=dict(taille=taille, **T, profondeur_trou=prof, hauteur_bossage=hb, horizontal=horizontal),
                note=f"Vis {taille} : pilote Ø{T['pilote']}, passage Ø{T['passage']} dans la pièce du dessus, bossage Ø{T['bossage']}. "
                     "Bossage imprimé avec 3 murs minimum (le filet doit mordre dans du plein, pas dans le remplissage). "
                     "Visser à la main, s'arrêter dès que ça serre. Trou horizontal : goutte pointe en haut.",
                numero=21, nom=f"trou de vis directe {taille}")


# ------------------------------------------------------------------ n° 23 : fixation murale en trou de serrure (keyhole)
def trou_serrure_23(tete_d=8.4, tete_h=3.0, tige_d=4.2, course=10.0, levre=2.0, jeu=0.5, toit=2.0):
    """Trou de serrure pour accrocher une pièce sur une vis plantée dans le mur (vis à bois n° 8 / 4 mm à tête cylindrique
    ou bombée par défaut : tête Ø8,4 × 3, tige Ø4,2 — mesurer la vraie vis).
    Repère : dos de la pièce (contre le mur) à z = 0, la pièce va vers +Z. Grand trou d'entrée centré en (0, 0),
    fente vers +Y (le haut) sur `course` mm. On présente la pièce tête dans le grand trou, puis on la descend :
    la tige monte dans la fente et la tête se cache derrière les lèvres (de z = 0 à `levre`).
    Retourne a_soustraire (à couper dans la pièce, dos à z = 0), cotes, calcul, epaisseur_min.
    Impression : dos sur le plateau → les lèvres sont en bas, le dessus du canal est un pont de (tete_d + 2 × jeu) mm."""
    entree = tete_d + 2 * (jeu + 0.1)                   # +0,1 : trou vertical imprimé un peu petit
    fente = tige_d + 2 * jeu
    canal = tete_d + 2 * jeu
    hc = tete_h + 2 * jeu                               # hauteur du canal derrière les lèvres
    e_min = levre + hc + toit
    trou_entree = cq.Workplane("XY").circle(entree / 2).extrude(levre + hc).translate((0, 0, -0.01))
    s_fente = _obround(course + fente, fente, levre + 0.02).rotate((0, 0, 0), (0, 0, 1), 90).translate((0, course / 2, -0.01))
    s_canal = _obround(course + canal, canal, hc).rotate((0, 0, 0), (0, 0, 1), 90).translate((0, course / 2, levre))
    a_sous = trou_entree.union(s_fente).union(s_canal)
    calc = dict(depassement_vis_mm=round(levre + jeu, 2), pont_canal_mm=round(canal, 2),
                note_calc=f"visser jusqu'à laisser {levre + jeu:.1f} mm entre le mur et le dessous de la tête "
                          f"(cale : une carte de {levre + jeu:.1f} mm ou 2 cartes de crédit + 1 mm)")
    return dict(a_soustraire=a_sous, epaisseur_min=e_min, calcul=calc,
                cotes=dict(entree=round(entree, 2), fente=round(fente, 2), canal=round(canal, 2), hauteur_canal=round(hc, 2), levre=levre,
                           course=course, epaisseur_min=round(e_min, 2), tete_d=tete_d, tete_h=tete_h, tige_d=tige_d),
                note="Imprimer dos sur le plateau (le canal fait un pont ≤ 12 mm). Lèvre ≥ 2 mm, en 100 % / 6 murs si la pièce est lourde. "
                     "Pour 2 trous : même hauteur, entraxe mesuré au mur.",
                numero=23, nom="trou de serrure (fixation murale)")


# ------------------------------------------------------------------ n° 22 : passant pour sangle (fente arrondie) + boucle à 3 barres
SANGLES = {20: dict(largeur_max=21.0, epaisseur=1.8), 25: dict(largeur_max=26.0, epaisseur=2.0), 38: dict(largeur_max=39.0, epaisseur=2.2)}
# largeur_max : sangle nylon/polypro du commerce (tolérance ≈ +1 mm); épaisseur : sangle « moyenne » (mince 1,2 – épaisse 2,5 : mesurer)


def _fente_chanfrein(longueur, largeur, h, ch=0.6):
    """Fente arrondie traversante (X = longueur) de z = 0 à h, avec chanfrein 45° de `ch` en haut et en bas (bords doux pour la sangle)."""
    f = _obround(longueur, largeur, h + 0.02, -0.01)
    bas = cq.Workplane("XY").slot2D(longueur + 2 * ch, largeur + 2 * ch).extrude(ch, taper=45).translate((0, 0, -0.01))
    haut = cq.Workplane("XY").slot2D(longueur, largeur).extrude(ch, taper=-45).translate((0, 0, h - ch + 0.01))
    return f.union(bas).union(haut)


def passant_sangle_22(sangle=25, epaisseur=4.0, barre=5.0, jeu=1.0, cadre=4.0, epaisseur_sangle=None, materiau=MAT):
    """Passants pour sangle 20, 25 ou 38 mm. Tout est en fentes VERTICALES traversantes (pièce imprimée à plat) :
    aucun pont, aucun surplomb (le pont d'un passant « en arche » de 27-40 mm pendrait).
    Retourne :
      fente_a_soustraire   : une fente arrondie (X = largeur de sangle), centrée en (0, 0), de z = 0 à `epaisseur`;
      passant_a_soustraire : 2 fentes séparées par une barre de `barre` mm (la sangle descend, passe sous la barre, remonte) ;
      boucle               : boucle de réglage à 3 barres (tri-glide) autonome, fentes pour 2 épaisseurs de sangle.
    Jeu ≥ 1 mm partout autour de la plus large sangle du commerce (règle « objet logé »)."""
    S = SANGLES[sangle]; es = epaisseur_sangle or S["epaisseur"]
    gf = es + 2 * jeu                                   # ouverture (1 épaisseur)
    gb = 2 * es + 2 * jeu                               # ouverture de la boucle (2 épaisseurs)
    Lf = S["largeur_max"] + gf                          # longueur : la partie droite couvre toute la sangle (les bouts ronds
    Lfb = S["largeur_max"] + gb                         # mangeraient le jeu aux coins de la sangle : 0,59 au lieu de 1,0)
    fente = _fente_chanfrein(Lf, gf, epaisseur)
    yo = (barre + gf) / 2
    passant = _fente_chanfrein(Lf, gf, epaisseur).translate((0, -yo, 0)).union(_fente_chanfrein(Lf, gf, epaisseur).translate((0, yo, 0)))
    yb = (barre + gb) / 2
    Lb, Wb = Lfb + 2 * cadre, 2 * gb + barre + 2 * cadre
    boucle = _rect_arrondi(Lb, Wb, min(3.0, cadre), epaisseur)
    boucle = boucle.cut(_fente_chanfrein(Lfb, gb, epaisseur).translate((0, -yb, 0))).cut(_fente_chanfrein(Lfb, gb, epaisseur).translate((0, yb, 0)))
    # barre centrale : poutre encastrée 2 bouts, charge répartie, flexion DANS le plan des couches (sangle tirée le long de la pièce)
    lim = 25.0                                           # MPa, charge maintenue PETG
    T_adm = 2 * lim * epaisseur * barre ** 2 / Lf        # M = T·L/12 ; σ = 6M/(e·b²) → T = 2·σ·e·b²/L
    calc = dict(traction_admissible_barre_N=round(T_adm), traction_admissible_kg=round(T_adm / 9.81, 1),
                note_calc="barre encastrée aux 2 bouts, charge répartie, σ ≤ 25 MPa (charge maintenue), sangle tirée le long de la pièce. "
                          "Tirée perpendiculairement à la pièce, la barre plie hors plan (section e × b au lieu de b × e) : compter environ e/b × moins.")
    return dict(fente_a_soustraire=fente, passant_a_soustraire=passant, boucle=boucle, calcul=calc, positions_fentes_y=(-yo, yo),
                positions_boucle_y=(-yb, yb), taille_boucle=(Lb, Wb),
                cotes=dict(sangle=sangle, largeur_max_sangle=S["largeur_max"], epaisseur_sangle=es, longueur_fente=round(Lf, 2), ouverture_fente=round(gf, 2),
                           longueur_fente_boucle=round(Lfb, 2), ouverture_boucle=round(gb, 2), barre=barre, epaisseur=epaisseur, boucle=(round(Lb, 1), round(Wb, 1)), chanfrein=0.6),
                note=f"Sangle {sangle} mm : fente {Lf:.0f} × {gf:.1f} mm, bouts arrondis, bords chanfreinés 0,6. Pièce à plat sur le plateau. "
                     "Barre et cadre en 100 % / 6 murs si ça porte du poids. Mesurer l'épaisseur de SA sangle (1,2 à 2,5 mm).",
                numero=22, nom=f"passant de sangle {sangle} mm + boucle")


# ------------------------------------------------------------------ n° 17 : couvercle à emboîter (lèvre + léger serrage)
def couvercle_pression_17(L=60.0, l=40.0, H=30.0, r=6.0, mur=2.0, fond=2.0, plaque=2.0, levre_h=6.0, levre_e=1.6,
                          jeu_levre=0.4, serrage=0.2, cote_l=1.6, bec=4.0, bec_e=2.5, materiau=MAT):
    """Boîte rectangulaire à coins arrondis + couvercle qui s'emboîte avec une lèvre intérieure et un LÉGER serrage.
    Le serrage ne se fait PAS sur toute la lèvre (trop sensible aux variations d'impression) : la lèvre a 0,4 mm de jeu
    par côté et porte 6 petites côtes d'écrasement verticales (1,6 mm de large) qui serrent de `serrage` mm contre le mur
    (dessiné 0,2 → ≈ 0,33 réel avec le grossissement FDM). Les côtes ont une rampe d'entrée à 30°.
    Repère : boîte de z = 0 à H, couvercle posé dessus (plaque de H à H + plaque, lèvre qui descend dans la boîte).
    Couvercle imprimé à l'envers (plaque sur le plateau), boîte debout. Bec de `bec` mm sur un petit côté pour l'ouvrir."""
    import lc3d
    M = _mat(materiau)
    boite = _rect_arrondi(L, l, r, H).cut(_rect_arrondi(L - 2 * mur, l - 2 * mur, max(r - mur, 0.5), H, fond))
    Li, li, ri = L - 2 * mur, l - 2 * mur, max(r - mur, 0.5)               # intérieur de la boîte
    Lo, lo, ro = Li - 2 * jeu_levre, li - 2 * jeu_levre, max(ri - jeu_levre, 0.5)   # extérieur de la lèvre
    couv = _rect_arrondi(L, l, r, plaque, H)
    couv = couv.union(cq.Workplane("XY").box(bec, 12.0, bec_e).translate((L / 2 + bec / 2 - 0.01, 0, H + plaque - bec_e / 2)))
    lev = _rect_arrondi(Lo, lo, ro, levre_h, H - levre_h).cut(_rect_arrondi(Lo - 2 * levre_e, lo - 2 * levre_e, max(ro - levre_e, 0.5), levre_h, H - levre_h))
    couv = couv.union(lev)
    # côtes d'écrasement : saillie = jeu + serrage, rampe 30° en bas (entrée), sur les 2/3 hauts de la lèvre
    s = jeu_levre + serrage
    hr = levre_h - 1.0; ramp = s / math.tan(math.radians(30))
    prof = cq.Workplane("XZ").polyline([(0, 0), (0, hr), (s, hr), (s, ramp)]).close().extrude(cote_l / 2, both=True)   # côte vers +X, bas à z=0
    def cote(x, y, ang):
        return prof.rotate((0, 0, 0), (0, 0, 1), ang).translate((x, y, H - levre_h + 1.0))
    xs = (-Lo / 4, Lo / 4)
    cotes_l = [cote(x, lo / 2 - 0.01, 90) for x in xs] + [cote(x, -lo / 2 + 0.01, -90) for x in xs] + [cote(Lo / 2 - 0.01, 0, 0), cote(-Lo / 2 + 0.01, 0, 180)]
    for c in cotes_l: couv = couv.union(c)
    # estimation de la tenue : le mur de la boîte (porte-à-faux depuis le fond) plie sous chaque côte; largeur efficace ≈ 2/3 de H
    s_reel = serrage + 0.13                                    # +0,05 côte grossie, +0,08 trou (intérieur de boîte) plus petit
    k_mur = M["E"] * (2 * H / 3) * mur ** 3 / (4 * (H - levre_h / 2) ** 3)
    N = k_mur * s_reel; F = M["mu"] * N * len(cotes_l)
    calc = dict(serrage_dessine_mm=serrage, serrage_reel_estime_mm=round(s_reel, 2), raideur_mur_N_mm=round(k_mur, 2), force_normale_par_cote_N=round(N, 2),
                force_retrait_N=round(F, 1), fourchette_N=(round(F / 2, 1), round(F * 2, 1)),
                note_calc="estimation grossière (mur = poutre en porte-à-faux, largeur efficace 2/3 H; côtes qui s'écrasent un peu au 1er montage) : "
                          "le couvercle tient tout seul et s'enlève avec le bec, ce n'est pas un clip")
    return dict(boite=boite, couvercle=couv, calcul=calc,
                cotes=dict(L=L, l=l, H=H, rayon=r, mur=mur, levre_h=levre_h, levre_e=levre_e, jeu_levre=jeu_levre, serrage=serrage, saillie_cote=round(s, 2),
                           nb_cotes=len(cotes_l), bec=bec),
                note="Boîte debout, couvercle à l'envers (plaque sur le plateau). Trop dur : poncer les côtes ou serrage 0,1. Trop lâche : serrage 0,3. "
                     "Pour un vrai « clic » qui retient, prendre le clip annulaire n° 20 ou le clip n° 1.",
                numero=17, nom="couvercle à emboîter (lèvre + côtes de serrage)")


# ------------------------------------------------------------------ n° 20 : clip annulaire (couvercle rond qui clipse tout le tour)
def _revol(pts):
    """Profil (r, z) tourné autour de Z (360°)."""
    return cq.Workplane("XZ").polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0))


def clip_annulaire_20(D=50.0, H=40.0, mur=2.0, fond=2.0, plaque=2.5, accroche=1.0, jeu=0.3, h=1.5, L=14.0, nb_fentes=12, fente=1.5,
                      rampe=30.0, retenue=45.0, bec=4.0, materiau=MAT):
    """Pot rond + couvercle qui clipse TOUT LE TOUR sur un bourrelet. La jupe du couvercle est coupée en `nb_fentes`
    doigts (fentes de `fente` mm, ≥ 1,2) qui s'écartent de `accroche` mm en passant le bourrelet.
    Bourrelet du pot : rampe d'entrée 30° en haut, face de retenue `retenue`° en bas (45° = imprimable sans support
    ET s'enlève en tirant fort avec le bec; 90° = permanent mais surplomb). La lèvre du couvercle a les mêmes angles.
    Repère : pot de z = 0 à H (Ø extérieur D), couvercle posé sur le bord (plaque de H à H + plaque).
    Pot debout; couvercle à l'envers (plaque sur le plateau)."""
    import lc3d
    Rp = D / 2
    a = accroche + jeu                                    # saillie du bourrelet (la lèvre garde `jeu` contre le pot)
    t_ret = math.tan(math.radians(retenue)); t_ram = math.tan(math.radians(rampe))
    Ri = Rp + a + jeu                                     # intérieur de la jupe (jeu au-dessus du bourrelet)
    Re = Ri + h
    zbas = H - L                                          # bas de la jupe = bout des doigts
    ram_l = a / t_ram                                     # hauteur de la rampe d'entrée de la lèvre
    zl = zbas + 0.5 + ram_l + 0.4                         # haut du plat de la lèvre (pointe)
    zb0 = zl + jeu * 1.0                                  # bas du bourrelet : jeu axial au-dessus de la lèvre
    # pot + bourrelet
    pot = _revol([(Rp - mur, fond), (Rp - mur, H), (Rp, H), (Rp, zb0 + a / t_ret + 0.4 + a / t_ram),
                  (Rp + a, zb0 + a / t_ret + 0.4), (Rp + a, zb0 + a / t_ret), (Rp, zb0), (Rp, 0), (0, 0), (0, fond)])
    pot = pot.cut(cq.Workplane("XY").circle(Rp - mur).extrude(H).translate((0, 0, fond)))
    # couvercle : plaque + jupe + lèvre (pointe à Rp + jeu, face haute parallèle à la face de retenue)
    rt = Rp + jeu
    jupe = _revol([(Re, H + 0.01), (Re, zbas), (Ri, zbas), (Ri, zbas + 0.5), (rt, zbas + 0.5 + ram_l), (rt, zl),
                   (Ri, zl + (Ri - rt) / t_ret), (Ri, H + 0.01)])
    couv = cq.Workplane("XY").circle(Re).extrude(plaque).translate((0, 0, H)).union(jupe)
    # bec : son dos commence DANS le disque sur toute sa largeur (12 mm). Avant : dos à Re − 1, hors du disque aux bords du bec
    # quand Re < 18,5 → fente de 0,01-0,1 mm entre bec et plaque (❌ LC3D, petits Ø). Corrigé 2026-10-28 (recettes LC3D).
    xb0 = math.sqrt(max(Re ** 2 - 36.0, 0.0)) - 0.5
    couv = couv.union(cq.Workplane("XY").box(Re + bec - xb0, 12.0, plaque).translate(((xb0 + Re + bec) / 2, 0, H + plaque / 2)))
    for k in range(nb_fentes):                             # fentes de flexion, du bout des doigts jusque sous la plaque
        # fente de zbas − 0,01 jusqu'à H pile (dessous de la plaque). Avant : arrêtée à H − 0,005 → marche de 0,005 mm sous la plaque,
        # vue par LC3D comme « fente 0,01 mm » + « mur 0,16 mm » (❌) sur les petits Ø. Corrigé 2026-10-28 (recettes LC3D).
        f = cq.Workplane("XY").box(2 * h + 2 * a + 4, fente, L + 0.01).translate((Rp + a, 0, zbas + L / 2 - 0.005))
        couv = couv.cut(f.rotate((0, 0, 0), (0, 0, 1), (k + 0.5) * 360 / nb_fentes))
    w = 2 * math.pi * (Ri + h / 2) / nb_fentes - fente
    calc = lc3d.calc_snap(L, h, w, accroche, materiau, rampe, retenue)
    calc["note_calc"] = ("doigt calculé comme une poutre droite; un doigt courbe est un peu plus raide (arc de "
                         f"{360 / nb_fentes:.0f}°) : force réelle un peu plus haute, déformation un peu plus basse")
    return dict(pot=pot, couvercle=couv, calcul=calc,
                cotes=dict(D=D, H=H, accroche=accroche, saillie_bourrelet=round(a, 2), jeu=jeu, jupe_interieur=round(2 * Ri, 2), jupe_exterieur=round(2 * Re, 2),
                           h=h, L=L, w=round(w, 2), nb_fentes=nb_fentes, fente=fente, rampe=rampe, retenue=retenue, bec=bec),
                note=f"{nb_fentes} doigts de {w:.1f} × {L:g} × {h:g} mm. Retenue {retenue:g}° : s'enlève en tirant le bec "
                     f"({calc['force_retrait_N']} N). Retenue 90° = permanent (mais surplomb sous le bourrelet). Couvercle en 6 murs / 100 % (doigts pleins).",
                numero=20, nom="clip annulaire (couvercle rond)")


# ------------------------------------------------------------------ n° 18 : loquet coulissant (verrou) avec crans ouvert / fermé
def _poche_xy(pts, z0, z1, ch):
    """Poche à couper : polygone XY extrudé de z0 à z1, puis plafond à 45° (rétréci de `ch`) : aucun plafond plat."""
    w = cq.Workplane("XY").polyline(pts).close()
    return w.extrude(z1 - z0).translate((0, 0, z0)).union(cq.Workplane("XY").polyline(pts).close().extrude(ch, taper=45).translate((0, 0, z1 - 0.01)))


def loquet_glissiere_18(b=12.0, t=5.0, chanfrein=1.5, jeu=0.5, Lg=50.0, course=15.0, mur=3.5, plancher=3.0, levre=2.0,
                        accroche=1.0, h_doigt=1.8, L_doigt=22.0, fente=1.5, flanc=60.0, x_cran=-5.0, bout_ferme=4.0, gache_e=14.0, gache_ecart=3.0,
                        engagement=8.0, vis="M3", materiau=MAT):
    """Verrou coulissant : guide (vissé sur la porte) + pêne qui glisse en X + gâche (vissée sur le cadre).
    - Section du pêne b × t, arêtes du dessus chanfreinées à 45° : le guide a des lèvres à 45° au-dessus (aucun surplomb plat,
      le pêne ne peut pas sortir par le haut), jeu `jeu` partout.
    - Cran : un doigt flexible DANS le pêne (côté +Y, lame dans le plan des couches) porte une bosse (rampes 30°) qui tombe dans
      2 encoches du mur du guide (flancs à `flanc`° = 60° : clic franc ≈ 7 N pour sortir d'un cran; le flanc est un mur vertical,
      aucun surplomb) : FERMÉ (x_cran) et OUVERT (x_cran + course). Entre les deux, le doigt plie de `accroche`.
    - Butée franche côté fermé : le bouton bute contre le bout fermé du guide (pont de 9-10 mm). Côté ouvert, en tirant fort,
      le pêne sort par le bout +X (démontage), via la rampe d'entrée à 30°.
    Repère (position FERMÉE) : guide de x = -Lg/2 à +Lg/2, dessous à z = 0, pêne centré en y = 0; gâche du côté -X.
    Tout s'imprime à plat, sans support."""
    import lc3d
    c = chanfrein; j = jeu
    z0 = plancher + j                                    # dessous du pêne
    a = accroche + j                                     # saillie de la bosse au-delà du flanc du pêne
    yb = b / 2                                           # flanc +Y du pêne
    ztop = z0 + t + j + levre                            # dessus du guide
    prof_pene = [(-b / 2, z0), (b / 2, z0), (b / 2, z0 + t - c), (b / 2 - c, z0 + t), (-b / 2 + c, z0 + t), (-b / 2, z0 + t - c)]
    def canal(x0, x1):
        return cq.Workplane("YZ").polyline(prof_pene).close().offset2D(j, "intersection").extrude(x1 - x0).translate((x0, 0, 0))
    w_open = b - 2 * c + 2 * j
    Wc = b + 2 * j + 2 * mur
    # ---- guide
    guide = cq.Workplane("XY").box(Lg, Wc, ztop).translate((0, 0, ztop / 2))
    guide = guide.union(cq.Workplane("XY").box(Lg, Wc + 20, plancher).translate((0, 0, plancher / 2)))
    guide = guide.cut(canal(-Lg / 2 - 1, Lg / 2 + 1))
    guide = guide.cut(cq.Workplane("XY").box(Lg + 2 - bout_ferme, w_open, ztop).translate((bout_ferme / 2 + 1, 0, ztop / 2 + z0 + t - 1)))
    # encoches (flancs 45°), profondeur a + jeu depuis le mur (y = b/2 + j), z du plancher au haut du flanc droit du pêne + jeu
    yi = w_open / 2 - 1.5                                 # l'encoche enlève aussi la lèvre au-dessus (pas de lame mince)
    ym = b / 2 + j; yf = yb + a + j; n0 = 2.4                 # n0 : demi-fond d'encoche → 0,5 mm de jeu autour de la bosse au repos
    def encoche(xc):
        d = yf - ym; e = d / math.tan(math.radians(flanc))
        return cq.Workplane("XY").polyline([(xc - n0 - e, yi), (xc - n0 - e, ym), (xc - n0, yf), (xc + n0, yf), (xc + n0 + e, ym),
                                            (xc + n0 + e, yi)]).close().extrude(ztop + 1 - z0 + j).translate((0, 0, z0 - j))
    # encoches ouvertes jusqu'en haut (pas de plafond : rien à faire tenir dans le vide, pas de lame mince sous la lèvre)
    guide = guide.cut(encoche(x_cran)).cut(encoche(x_cran + course))
    ram = (yf - ym) / math.tan(math.radians(30))
    guide = guide.cut(cq.Workplane("XY").polyline([(Lg / 2 + 1, yi), (Lg / 2 + 1, yf), (Lg / 2 - 0.2, yf), (Lg / 2 - 0.2 - ram, ym),
                                                   (Lg / 2 - 0.2 - ram, yi)]).close().extrude(ztop + 1 - z0 + j).translate((0, 0, z0 - j)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            guide = guide.cut(lc3d.trou_vis(vis, "passage", profondeur=plancher + 1, tete="fraisee", x=sx * (Lg / 2 - 7), y=sy * (Wc / 2 + 5), z=plancher))
    # ---- pêne (position fermée) : bout à -Lg/2 - gache_ecart - engagement
    x_bout = -Lg / 2 - gache_ecart - engagement
    hb = a / math.tan(math.radians(30)); f = 1.0          # bosse : rampes 30°, plat de 1 mm
    x_libre = x_cran - f / 2 - hb - 0.3                   # bout libre du doigt
    x_racine = x_libre + L_doigt
    x_arriere = x_racine + 4.0
    pene = cq.Workplane("YZ").polyline(prof_pene).close().extrude(x_arriere - x_bout).translate((x_bout, 0, 0))
    yd = yb - h_doigt                                     # face intérieure du doigt
    pene = pene.cut(cq.Workplane("XY").box(L_doigt, fente, 30).translate((x_libre + L_doigt / 2, yd - fente / 2, 0)))
    pene = pene.cut(cq.Workplane("XY").box(fente, h_doigt + fente + 1, 30).translate((x_libre - fente / 2, yd - fente + (h_doigt + fente + 1) / 2, 0)))
    bosse = cq.Workplane("XY").polyline([(x_cran - f / 2 - hb, yb - 0.01), (x_cran - f / 2, yb + a), (x_cran + f / 2, yb + a), (x_cran + f / 2 + hb, yb - 0.01)]).close() \
        .extrude(t - c).translate((0, 0, z0))
    pene = pene.union(bosse)
    kx, ky, kz = 6.0, 5.0, 8.0
    xk = -Lg / 2 + bout_ferme + j + kx / 2
    pene = pene.union(cq.Workplane("XY").box(kx, ky, kz).translate((xk, 0, z0 + t + kz / 2 - 0.01)).edges("|X and >Z").fillet(1.5))
    # ---- gâche
    xg1 = -Lg / 2 - gache_ecart; xg0 = xg1 - gache_e
    gache = cq.Workplane("XY").box(gache_e, Wc, ztop).translate(((xg0 + xg1) / 2, 0, ztop / 2))
    gache = gache.union(cq.Workplane("XY").box(gache_e, Wc + 20, plancher).translate(((xg0 + xg1) / 2, 0, plancher / 2)))
    gache = gache.cut(canal(xg0 - 1, xg1 + 1))
    for sy in (-1, 1):
        gache = gache.cut(lc3d.trou_vis(vis, "passage", profondeur=plancher + 1, tete="fraisee", x=(xg0 + xg1) / 2, y=sy * (Wc / 2 + 5), z=plancher))
    calc = lc3d.calc_snap(L_doigt - (x_cran - x_libre), h_doigt, t - c, accroche, materiau, 30.0, flanc, usage="fatigue")
    return dict(guide=guide, pene=pene, gache=gache, calcul=calc,
                cotes=dict(pene=(b, t), chanfrein=c, jeu=j, guide=Lg, course=course, accroche=accroche, doigt=(L_doigt, h_doigt), fente=fente, flanc=flanc,
                           x_cran_ferme=x_cran, x_cran_ouvert=x_cran + course, ouverture_dessus=round(w_open, 2), engagement_gache=engagement,
                           L_calcul=round(L_doigt - (x_cran - x_libre), 2), w_calcul=t - c),
                note="Guide, pêne et gâche à plat sur le plateau. Le pêne s'enfile par le bout +X du guide (le doigt plie). "
                     "Vis fraisées " + vis + ". Ouvert/fermé : clic franc dans chaque encoche; le bouton bute en fermé.",
                numero=18, nom="loquet coulissant à crans")


# ------------------------------------------------------------------ n° 16 : fermeture baïonnette (pousser + tourner ~30°) avec cran
def _polaire(pts_sr, r_ref):
    """Polygone donné en (s, r) — s = longueur d'arc au rayon r_ref, r = rayon — converti en XY (arcs échantillonnés)."""
    out = []
    for (s0, r0), (s1, r1) in zip(pts_sr, pts_sr[1:] + pts_sr[:1]):
        n = max(1, int(abs(s1 - s0) / 0.4) + int(abs(r1 - r0) / 0.4))
        for k in range(n):
            s = s0 + (s1 - s0) * k / n; r = r0 + (r1 - r0) * k / n; a = s / r_ref
            out.append((r * math.cos(a), r * math.sin(a)))
    return out


def baionnette_16(Ri=20.0, mur=3.0, H=26.0, fond=2.0, nb=3, angle=30.0, jeu=0.5, accroche=1.0, lug_l=4.0, lug_h=3.0,
                  langue_l=8.0, langue_h=1.6, L=14.0, fente=1.5, collerette=3.0, rampe=30.0, retenue=45.0, materiau=MAT):
    """Baïonnette : on enfonce le bouchon (ergots dans les fentes verticales) puis on tourne de `angle`° : les ergots passent
    sous le rebord (fenêtre horizontale) et franchissent un CRAN qui retient (on entend un clic). Pour ouvrir : tourner fort
    dans l'autre sens (face de retenue `retenue`° = 45°), puis tirer.
    - Douille (femelle) : tube Ø intérieur 2·Ri, mur `mur`, fentes en L traversantes. Le cran est un bloc laissé dans la fenêtre,
      de Ri + accroche jusqu'à l'extérieur : l'ergot (qui dépasse jusqu'à Ri + 2·accroche) doit rentrer de `accroche` pour passer.
    - Bouchon (mâle) : collerette + jupe (jeu `jeu`), chaque ergot au bout d'une LANGUETTE flexible (2 fentes de `fente` mm,
      longueur L du haut des fentes au centre de l'ergot) qui plie vers l'intérieur.
    Repère : douille de z = 0 à H (axe Z), bouchon en position VERROUILLÉE, ergot n° 1 à l'angle 0°, fentes verticales à -angle.
    Douille debout; bouchon à l'envers (collerette sur le plateau). Tourner dans le sens trigo (vu de dessus) pour fermer."""
    import lc3d
    j = jeu; Ro = Ri + mur; Rs = Ri - j                        # Rs : extérieur de la jupe
    r_tip = Ri + 2 * accroche                                   # bout de l'ergot (1 mm dans le mur + 1 mm d'accroche sur le cran)
    r_cran = Ri + accroche
    z_lug0 = fond + 1.5 + j                                     # bas de l'ergot (fenêtre : z_lug0 - j à z_lug0 + lug_h + j)
    z_fen0, z_fen1 = z_lug0 - j, z_lug0 + lug_h + j
    z_col = H + j                                               # dessous de la collerette (jeu axial au repos)
    z_jupe0 = z_lug0 - 0.5                                      # bas de la jupe (sous l'ergot)
    rm = (Ri + r_tip) / 2
    # ---- douille
    douille = cq.Workplane("XY").circle(Ro).extrude(H).cut(cq.Workplane("XY").circle(Ri).extrude(H).translate((0, 0, fond)))
    d_ang = math.degrees(math.atan((lug_l / 2) / Ri) + math.asin(j / math.hypot(Ri, lug_l / 2))) + 0.3   # bout de fenêtre : jeu ≥ j au rayon Ri
    s_l = math.degrees(math.atan((lug_l / 2) / Ri)) * math.pi / 180 * rm   # (conservateur : angle vu au rayon Ri)
    for k in range(nb):
        a0 = k * 360.0 / nb
        fen = _secteur(Ri - 1, Ro + 1, a0 - angle - d_ang, a0 + d_ang, z_fen1 - z_fen0, z_fen0)
        vert = cq.Workplane("XY").box(Ro + 2 - (Ri - 1), lug_l + 2 * j, H + 1 - z_fen0).translate(((Ri - 1 + Ro + 2) / 2, 0, (H + 1 + z_fen0) / 2)) \
            .rotate((0, 0, 0), (0, 0, 1), a0 - angle)
        # cran (en s, r autour de l'ergot verrouillé) : face de retenue 45°, plat 1 mm, rampe d'entrée 30°.
        # Il est RETIRÉ de l'outil de coupe de la fenêtre (pas ajouté après) : aucune face confondue, maillage propre.
        s_e = -(s_l + j)                                        # face de retenue au bout de l'ergot : jeu j au repos
        t_ret = math.tan(math.radians(retenue)); t_ram = math.tan(math.radians(rampe))
        pts = [(s_e, r_tip), (s_e - accroche / t_ret, r_cran), (s_e - accroche / t_ret - 1.0, r_cran),
               (s_e - accroche / t_ret - 1.0 - accroche / t_ram, r_tip), (s_e - accroche / t_ret - 1.0 - accroche / t_ram, Ro + 2), (s_e, Ro + 2)]
        cran = cq.Workplane("XY").polyline(_polaire(pts, rm)).close().extrude(z_fen1 - z_fen0 + 2).translate((0, 0, z_fen0 - 1))
        douille = douille.cut(fen.cut(cran.rotate((0, 0, 0), (0, 0, 1), a0))).cut(vert)
    s_cran_debut = -(s_l + j) - accroche / math.tan(math.radians(retenue)) - 1.0 - accroche / math.tan(math.radians(rampe))
    # ---- bouchon
    bouchon = cq.Workplane("XY").circle(Ro).extrude(collerette).translate((0, 0, z_col))
    bouchon = bouchon.union(cq.Workplane("XY").circle(Rs).circle(Rs - langue_h).extrude(z_col - z_jupe0 + 0.01).translate((0, 0, z_jupe0)))
    z_haut_fente = z_lug0 + lug_h / 2 + L                       # L = du haut des fentes au centre de l'ergot
    if z_haut_fente > z_col - 1.0: raise ValueError("languette trop longue pour la hauteur : augmenter H ou réduire L")
    for k in range(nb):
        a0 = k * 360.0 / nb
        for sg in (-1, 1):
            # fente RADIALE (secteur), ≥ `fente` mm au rayon intérieur de la jupe. Avant : fente à flancs parallèles → coins de 71-74°
            # entre flanc et jupe (petits Ø), vus par LC3D comme murs de 0,15 mm en diagonale (❌ de t_c16). Corrigé 2026-10-28.
            r_in = Rs - langue_h; r_mid = Rs - langue_h / 2
            demi = math.degrees((fente / 2) / r_in)
            ac = sg * (math.degrees((langue_l / 2) / r_mid) + demi)
            f = _secteur(r_in - 1.0, Rs + 1.0, a0 + ac - demi, a0 + ac + demi, z_haut_fente - z_jupe0 + 1, z_jupe0 - 1, n=4)
            bouchon = bouchon.cut(f)
        ergot = cq.Workplane("XY").box(r_tip - (Rs - 0.6), lug_l, lug_h).translate(((r_tip + Rs - 0.6) / 2, 0, z_lug0 + lug_h / 2))
        bouchon = bouchon.union(ergot.rotate((0, 0, 0), (0, 0, 1), a0))
    calc = lc3d.calc_snap(L, langue_h, langue_l, accroche, materiau, rampe, retenue)
    # couple pour franchir le cran ≈ force tangentielle × rayon × nb ergots
    calc["couple_fermeture_Nm"] = round(calc["force_insertion_N"] * rm / 1000 * nb, 2)
    calc["couple_ouverture_Nm"] = None if isinstance(calc["force_retrait_N"], str) else round(calc["force_retrait_N"] * rm / 1000 * nb, 2)
    rot_libre = math.degrees((s_cran_debut - j - s_l) / rm) + angle      # rotation libre depuis la fente avant de toucher la rampe
    return dict(douille=douille, bouchon=bouchon, calcul=calc,
                cotes=dict(Ri=Ri, Ro=Ro, H=H, nb=nb, angle=angle, jeu=j, accroche=accroche, ergot=(lug_l, lug_h, round(r_tip - Rs, 2)),
                           languette=(langue_l, L, langue_h), fente=fente, z_ergot=z_lug0, rotation_libre=round(rot_libre, 1),
                           s_cran_debut=round(s_cran_debut, 2), rayon_moyen=rm),
                note=f"Enfoncer (ergots dans les fentes), tourner de {angle:g}° dans le sens trigo : clic du cran. "
                     "Douille debout, bouchon collerette sur le plateau. Les languettes plient à travers les couches : PETG, bouchon en 100 %.",
                numero=16, nom="fermeture baïonnette à cran")


# ------------------------------------------------------------------ catalogue du lot B
LOT_B = {16: baionnette_16, 17: couvercle_pression_17, 18: loquet_glissiere_18, 19: assemblage_aronde_19,
         20: clip_annulaire_20, 21: trou_vis_directe_21, 22: passant_sangle_22, 23: trou_serrure_23}

FICHES_B = [
    dict(num=16, nom="Baïonnette à cran", type="fermeture",
         description="Bouchon Ø46 à 3 ergots : on enfonce puis on tourne de 30° et un cran fait clic (languettes 8 × 14 × 1,6, accroche 1 mm, jeu 0,5).",
         statut="calcule"),
    dict(num=17, nom="Couvercle à emboîter", type="couvercle",
         description="Boîte 60 × 40 × 30 à coins arrondis et couvercle à lèvre (jeu 0,4) avec 6 côtes qui serrent de 0,2 mm, tient seul (≈ 2 N) et s'ouvre par un bec.",
         statut="calcule"),
    dict(num=18, nom="Loquet coulissant", type="verrou",
         description="Pêne 12 × 5 qui glisse de 15 mm dans un guide à lèvres 45°, clic franc (≈ 7 N) en ouvert et en fermé grâce à un doigt flexible, butée en fermé.",
         statut="calcule"),
    dict(num=19, nom="Queue d'aronde", type="jonction",
         description="Deux queues d'aronde 15° (col 10 mm, profondeur 10) pour joindre 2 grandes pièces imprimées à plat, jeu 0,3 par flanc et fond d'arrêt.",
         statut="calcule"),
    dict(num=20, nom="Clip annulaire", type="clip",
         description="Couvercle rond Ø56 qui clipse tout le tour sur un bourrelet de 1,3 mm (12 doigts 14 × 1,5, fentes 1,5), s'enlève en tirant le bec (≈ 15 N).",
         statut="calcule"),
    dict(num=21, nom="Trou de vis directe", type="visserie",
         description="Trous pilotes pour visser M2 à M5 direct dans le plastique (M3 : pilote Ø2,6, passage Ø3,4, bossage Ø6,6, prise 7,5 mm) avec tableau des diamètres.",
         statut="calcule"),
    dict(num=22, nom="Passant de sangle + boucle", type="sangle",
         description="Fentes arrondies traversantes pour sangle 20/25/38 mm (25 mm : fente 30 × 4, barre 5 mm, tient ≈ 10 kg) et boucle de réglage à 3 barres.",
         statut="calcule"),
    dict(num=23, nom="Trou de serrure mural", type="fixation",
         description="Trou de serrure pour vis à bois n° 8 (tête Ø8,4) : entrée Ø9,6, fente 5,2 sur 10 mm, lèvres de 2 mm, pièce de 8 mm d'épaisseur minimum.",
         statut="calcule"),
]
