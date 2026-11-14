"""LC3D — lot D (n° 31 à 34) : recettes classiques et éprouvées qui ont fait leurs preuves en essai réel
31 charnière imprimée en place à cônes 45° · 32 berceau qui TIENT une fiche USB-C / USB-B · 33 encoche de câble ouverte
jusqu'au bord (poser une carte avec son câble branché) · 34 engrenages droits à développante + simulation 2D du mouvement.
Chaque fonction renvoie des formes CadQuery + cotes + calcul, comme les autres lots. Tests : tests/composants/t_c31..t_c34."""
import math
import cadquery as cq


def _boite(x0, x1, y0, y1, z0, z1):
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))


def _cyl_x(r, x0, x1, y=0.0, z=0.0):
    return cq.Workplane("YZ").circle(r).extrude(x1 - x0).translate((x0, y, z))


def _cone_x(r0, x0, sens, y=0.0, z=0.0):
    """Cône à 45° d'axe X : base de rayon r0 au plan x0, pointe à x0 + sens·r0."""
    s = cq.Solid.makeCone(r0, 0.0, r0, pnt=cq.Vector(x0, y, z), dir=cq.Vector(sens, 0, 0))
    return cq.Workplane("XY").add(s)


# ------------------------------------------------------------------ n° 31 : charnière imprimée en place à cônes 45°
def charniere_cones_31(longueur=40.0, n_noeuds=5, R=4.0, t=3.0, largeur=20.0, jeu=0.4, r_cone=None):
    """Deux feuilles imprimées à plat d'un seul coup, déjà assemblées, SANS axe séparé ni support.
    Axe le long de X à z = R (noeuds Ø 2R posés sur le plateau). Feuille A vers -Y, feuille B vers +Y, épaisseur t.
    Noeuds alternés A, B, A… (n impair : A a les 2 bouts). Chaque face A→B porte un cône MÂLE à 45° (sur A) qui entre dans
    un creux conique (dans B) décalé de jeu·√2 le long de l'axe → jeu normal = jeu partout. Les surfaces coniques sont à 45° :
    elles s'impriment sans support (dessous du cône mâle et plafond du creux = 45°).
    Pied à 45° sous chaque noeud, côté de l'autre feuille : plus aucun surplomb > 45° sous le noeud.
    B s'ouvre de 0 à 180° (rotation autour de l'axe, +Y qui monte) : à 180° les feuilles sont à 2(R − t) l'une de l'autre."""
    if n_noeuds < 3 or n_noeuds % 2 == 0: raise ValueError("n_noeuds impair ≥ 3 (A a les deux bouts)")
    if t > R - jeu / 2: raise ValueError(f"t ≤ R − jeu/2 = {R - jeu / 2:.2f} (sinon les feuilles se touchent à 180°)")
    rc = r_cone or round(0.55 * R, 2)
    seg = (longueur - (n_noeuds - 1) * jeu) / n_noeuds
    if rc + jeu * math.sqrt(2) > seg - 1.2: raise ValueError(f"noeuds trop courts ({seg:.1f} mm) pour un cône de {rc} mm : moins de noeuds ou plus long")
    zc = R

    def profil_noeud(sens_pied):
        """Section YZ du noeud : cercle R + pied à 45° vers le côté sens_pied (-1 = vers -Y, +1 = vers +Y), jusqu'au plateau."""
        c45 = math.cos(math.radians(45))
        pts = [(sens_pied * R * c45, zc - R * c45), (sens_pied * R, 0.0), (0.0, 0.0)]
        pied = cq.Workplane("YZ").polyline(pts).close()
        return pied

    x = -longueur / 2; A = None; B = None; bornes = []
    for i in range(n_noeuds):
        x0, x1 = x, x + seg; bornes.append((x0, x1, "A" if i % 2 == 0 else "B")); x = x1 + jeu
    feuille_a = _boite(-longueur / 2, longueur / 2, -(largeur + R), -(R + jeu), 0, t)
    feuille_b = _boite(-longueur / 2, longueur / 2, R + jeu, largeur + R, 0, t)
    for x0, x1, qui in bornes:
        n = _cyl_x(R, x0, x1, 0, zc)
        sens = 1 if qui == "A" else -1          # pied du noeud côté de l'AUTRE feuille (là où il n'est pas soudé à la sienne)
        n = n.union(profil_noeud(sens).extrude(x1 - x0).translate((x0, 0, 0)))
        # le noeud se soude à SA feuille : pont plein de l'axe jusqu'à la feuille, sous l'axe
        if qui == "A":
            n = n.union(_boite(x0, x1, -(R + jeu) - 0.01, 0, 0, t))
            A = n if A is None else A.union(n)
        else:
            n = n.union(_boite(x0, x1, 0, R + jeu + 0.01, 0, t))
            B = n if B is None else B.union(n)
    # dégagements : la feuille de l'un est creusée autour des noeuds de l'autre (cylindre R + jeu, + rayon du pied tournant)
    r_deg = R * math.sqrt(2) + jeu       # le coin du pied (à R√2 de l'axe) tourne avec la feuille B
    for x0, x1, qui in bornes:
        d = _cyl_x(r_deg if qui == "B" else R + jeu, x0 - jeu, x1 + jeu, 0, zc)
        if qui == "B": feuille_a = feuille_a.cut(d)
        else: feuille_b = feuille_b.cut(d)
    A = feuille_a.union(A); B = feuille_b.union(B)
    # cônes : sur chaque face A | B
    for (xa0, xa1, qa), (xb0, xb1, qb) in zip(bornes, bornes[1:]):
        if qa == "A":   # A à gauche, B à droite : cône mâle sur la face xa1 vers +X, creux dans B depuis xa1
            A = A.union(_cone_x(rc, xa1 - 0.01, +1, 0, zc))
            B = B.cut(_cone_x(rc + jeu * math.sqrt(2), xa1, +1, 0, zc))   # surface décalée de jeu·√2 en rayon = jeu normal (45°)
        else:           # B à gauche, A à droite : cône mâle sur la face xb0 de A vers -X
            A = A.union(_cone_x(rc, xb0 + 0.01, -1, 0, zc))
            B = B.cut(_cone_x(rc + jeu * math.sqrt(2), xb0, -1, 0, zc))
    prof_creux = rc + jeu * math.sqrt(2) - jeu
    return dict(feuille_a=A, feuille_b=B, pivot=(0.0, 0.0, zc), axe=(1, 0, 0), numero=31, nom="charnière à cônes 45° imprimée en place",
                cotes=dict(longueur=longueur, noeuds=n_noeuds, longueur_noeud=round(seg, 2), R=R, epaisseur_feuille=t, jeu=jeu,
                           cone=f"Ø{2 * rc:.1f} × {rc:.1f} à 45°", entree_cone=round(rc, 2), profondeur_creux_dans_B=round(prof_creux, 2),
                           ecart_feuilles_180=round(2 * (R - t), 2)),
                calcul=dict(verdict="✅" if jeu >= 0.3 else "❌",
                            notes=[] if jeu >= 0.3 else ["jeu < 0,3 mm : les cônes se soudent à l'impression (0,4 conseillé en PLA/PETG)"]),
                note="Imprimer à plat, feuilles sur le plateau, telle quelle. Après impression : plier une fois à fond pour casser les fils. "
                     "Jeu réglable : 0,3 (serré, PLA bien calibré) à 0,5 (lâche). Retenue : B est capturée entre les cônes de A (ne sort pas en tirant).")


# ------------------------------------------------------------------ n° 32 : berceau qui TIENT une fiche USB-C / USB-B
def berceau_fiche_32(type="usb_c", jeu=0.2, nervure=0.3, n_nervures=2, paroi=2.4, fond=2.0, longueur=None, sortie_cable=True):
    """Poche verticale où on POSE la fiche (prise vers le haut) : elle y reste, on pose ensuite l'appareil dessus.
    Surmoulage réel de lc3d.FICHES_CABLE (pire câble réel). Poche = surmoulage + jeu par côté, avec n_nervures nervures
    d'écrasement (demi-cylindres) sur chaque grande face qui avancent de `nervure` dans la poche : serrage = nervure − jeu
    (0,1 mm par défaut, à déclarer A.serrage). Fente de câble au fond, ouverte sur le devant (le câble entre par le côté).
    Repère : poche centrée en (0, 0), fond de la poche à z = fond, haut du berceau à z = fond + longueur.
    Renvoie aussi `fiche` (le surmoulage, pour l'assemblage de vérification) posée au fond de la poche."""
    import lc3d
    k = lc3d._type_fiche(type) if hasattr(lc3d, "_type_fiche") else type
    F = lc3d.FICHES_CABLE[k]
    if F.get("rond"): raise ValueError("fiche ronde : utiliser une poche cylindrique (logement de roulement n° 4 en libre)")
    larg = max(p[1] for p in F["profil"]); haut = max(p[2] for p in F["profil"])
    Lr = longueur or round(min(F["rigide"], 22.0), 1)        # hauteur tenue du surmoulage (le reste dépasse vers le haut)
    px, py = larg / 2 + jeu, haut / 2 + jeu
    ext_x, ext_y = px + paroi, py + paroi
    H = fond + Lr
    corps = _boite(-ext_x, ext_x, -ext_y, ext_y, 0, H)
    poche = _boite(-px, px, -py, py, fond, H + 1)
    # entrée chanfreinée 45° de 0,8 mm (la fiche se pose sans accrocher; s'imprime sans support)
    ch = 0.8
    entree = (cq.Workplane("XY").workplane(offset=H - ch).rect(2 * px, 2 * py).workplane(offset=ch + 0.01).rect(2 * (px + ch), 2 * (py + ch)).loft())
    corps = corps.cut(poche).cut(entree)
    # nervures d'écrasement verticales sur les grandes faces (y = ±py), de fond + 1 à H − ch − 0,5
    r_n = 0.6
    z0n, z1n = fond + 1.0, H - ch - 0.5
    for i in range(n_nervures):
        xn = -px + (i + 1) * (2 * px) / (n_nervures + 1)
        for s in (1, -1):
            yc = s * (py + r_n - nervure)
            n = cq.Workplane("XY").circle(r_n).extrude(z1n - z0n).translate((xn, yc, z0n))
            corps = corps.union(n.intersect(_boite(-px, px, -py - r_n, py + r_n, z0n, z1n)))
    if sortie_cable:      # fente dans le fond, du centre jusqu'au devant (-Y) : le câble (Ø ≤ 4,5) y glisse par le côté et sort par-dessous
        lc = 4.5 + 2 * jeu
        corps = corps.cut(_boite(-lc / 2, lc / 2, -ext_y - 1, 0, -1, fond + 0.01))
    fiche = _boite(-larg / 2, larg / 2, -haut / 2, haut / 2, fond, fond + F["rigide"])
    serr = round(nervure - jeu, 2)
    return dict(berceau=corps, fiche=fiche, numero=32, nom=f"berceau qui tient une {F['nom']}",
                cotes=dict(fiche=F["nom"], surmoulage=f"{larg} × {haut}", poche=f"{2 * px:.2f} × {2 * py:.2f} × {Lr}", jeu_par_cote=jeu,
                           nervures=f"{n_nervures} par grande face, avancent de {nervure}", serrage_nervures=serr,
                           exterieur=f"{2 * ext_x:.1f} × {2 * ext_y:.1f} × {H:.1f}", sortie_cable=sortie_cable),
                serrage=serr,
                calcul=dict(verdict="✅" if 0.05 <= serr <= 0.2 else "❌",
                            notes=[] if 0.05 <= serr <= 0.2 else ["serrage des nervures hors 0,05–0,2 mm : soit la fiche ballotte, soit elle ne rentre pas"]),
                note="Imprimer debout (poche vers le haut). La fiche se pousse à la main et tient par les nervures (elles s'écrasent un peu au 1er essai). "
                     "Câble réel plus gros que la norme : mesurer le surmoulage et passer type=… avec jeu/nervure ajustés.")


# ------------------------------------------------------------------ n° 33 : encoche de câble ouverte jusqu'au bord
def encoche_ouverte_33(type="usb_b", z_axe=10.0, ep_mur=2.5, jeu=0.5, hauteur_mur=None, rayon_bas=True):
    """Découpe à soustraire d'un mur (mur dans le plan XZ, épaisseur selon Y, de y = 0 à y = ep_mur) : passage de la VRAIE fiche
    (surmoulage de lc3d.FICHES_CABLE + jeu par côté) centré à x = 0, z = z_axe, OUVERT vers le haut jusqu'au bord du mur.
    On pose la carte avec le câble déjà branché, et on l'enlève sans débrancher. Les coins du bas sont arrondis
    (rayon_bas, r 1,5) : pas de coin vif qui fissure, et s'imprime sans support (aucun plafond).
    hauteur_mur : haut du mur (défaut z_axe + 30) — l'encoche va jusque-là (+1)."""
    import lc3d
    k = lc3d._type_fiche(type) if hasattr(lc3d, "_type_fiche") else type
    F = lc3d.FICHES_CABLE[k]
    larg = max(p[1] for p in F["profil"]); haut = max(p[2] for p in F["profil"])
    if F.get("rond"): larg = haut = F["profil"][0][1]
    w = larg + 2 * jeu
    zb = z_axe - haut / 2 - jeu                 # bas du passage
    Hm = hauteur_mur if hauteur_mur is not None else z_axe + 30.0
    dec = _boite(-w / 2, w / 2, -1, ep_mur + 1, zb, Hm + 1)
    if rayon_bas:          # coins du bas arrondis (r 1,5) : pas de coin vif qui fissure; le fond reste à zb (la fiche passe)
        dec = dec.edges("|Y and <Z").fillet(min(1.5, w / 2 - 0.1))
    return dict(a_soustraire=dec, numero=33, nom=f"encoche ouverte pour {F['nom']}",
                cotes=dict(fiche=F["nom"], surmoulage=f"{larg} × {haut}", largeur_encoche=round(w, 2), bas_encoche=round(zb, 2),
                           z_axe=z_axe, ouverte_jusqu_a=Hm, jeu_par_cote=jeu),
                calcul=dict(verdict="✅" if jeu >= 0.3 else "❌", notes=[] if jeu >= 0.3 else ["jeu < 0,3 : la fiche frotte sur les bords imprimés"]),
                note="Le couvercle ferme le haut de l'encoche (prévoir une languette ou laisser l'encoche ouverte dans le couvercle aussi). "
                     "Vérifier dans l'assemblage : A.connecteur(...) + A.inserer(carte, depuis=(0, 0, +40)) avec la fiche branchée.")


# ------------------------------------------------------------------ n° 34 : engrenages droits à développante + simulation 2D
def _profil_developpante(m, z, alpha=20.0, jeu_cible=0.2, pts_flanc=14, pts_arc=4):
    """Polygone shapely d'une roue droite à développante (sans trou). Dent amincie de jeu_cible/2 au primitif
    (deux roues → jeu entre dents = jeu_cible). Pied radial sous le cercle de base (petites roues)."""
    from shapely.geometry import Polygon
    a = math.radians(alpha); rp = m * z / 2; rb = rp * math.cos(a); ra = rp + m; rf = rp - 1.25 * m
    inv = lambda x: math.tan(x) - x
    s = math.pi * m / 2 - jeu_cible / 2
    psi = s / (2 * rp)                                         # demi-épaisseur angulaire au primitif
    def theta(r):
        if r <= rb: return psi + inv(a)
        return psi + inv(a) - inv(math.acos(rb / r))
    r0 = max(rf, rb)
    rs = [r0 + (ra - r0) * i / pts_flanc for i in range(pts_flanc + 1)]
    pts = []
    pas = 2 * math.pi / z
    for k in range(z):
        c = k * pas
        # pied (rayon rf) → flanc gauche (−θ) → tête → flanc droit (+θ)
        if rf < rb: pts.append((rf * math.cos(c - theta(rb)), rf * math.sin(c - theta(rb))))
        for r in rs: pts.append((r * math.cos(c - theta(r)), r * math.sin(c - theta(r))))
        tt = theta(ra)
        for i in range(1, pts_arc): u = -tt + 2 * tt * i / pts_arc; pts.append((ra * math.cos(c + u), ra * math.sin(c + u)))
        for r in reversed(rs): pts.append((r * math.cos(c + theta(r)), r * math.sin(c + theta(r))))
        if rf < rb: pts.append((rf * math.cos(c + theta(rb)), rf * math.sin(c + theta(rb))))
        # arc de pied jusqu'à la dent suivante
        t0 = c + theta(r0 if rf >= rb else rb); t1 = c + pas - theta(r0 if rf >= rb else rb)
        for i in range(1, pts_arc): u = t0 + (t1 - t0) * i / pts_arc; pts.append((rf * math.cos(u), rf * math.sin(u)))
    P = Polygon(pts)
    if not P.is_valid: P = P.buffer(0)
    return P, dict(rp=rp, rb=rb, ra=ra, rf=rf, epaisseur_dent_primitif=round(s, 3))


def simuler_engrenages_2d(Pa, Pb, za, zb, entraxe, tours=2.0, pas_par_dent=12, rp_b=None, mesures_jeu=12):
    """Simulation 2D du mouvement : la roue A fait `tours` tours, B suit au rapport exact (−za/zb), en section.
    À chaque position : aire commune A∩B (> 1e-4 mm² = interférence) et distance mini. Puis le VRAI jeu entre dents :
    à `mesures_jeu` positions d'une période de dent, on tourne B dans les deux sens jusqu'au contact (dichotomie) →
    jeu angulaire × rayon primitif de B = jeu au primitif (mm). Quelques secondes."""
    import time
    from shapely import affinity
    t0 = time.time()
    phase_b = 180.0 + 180.0 / zb                               # un creux de B face à la dent 0 de A
    def poser_b(phi_a, d=0.0):
        ang = phase_b - phi_a * za / zb + d
        return affinity.translate(affinity.rotate(Pb, ang, origin=(0, 0)), entraxe, 0)
    n = max(1, int(round(tours * za * pas_par_dent)))
    pire_aire = 0.0; dmin = 1e9; lieu = None
    for i in range(n + 1):
        phi = 360.0 * tours * i / n
        A_ = affinity.rotate(Pa, phi, origin=(0, 0)); B_ = poser_b(phi)
        ar = A_.intersection(B_).area
        if ar > pire_aire: pire_aire, lieu = ar, round(phi, 2)
        dmin = min(dmin, A_.distance(B_))
    jeux = []
    rp_b = rp_b or 0.0
    for j in range(mesures_jeu):
        phi = (360.0 / za) * j / mesures_jeu
        A_ = affinity.rotate(Pa, phi, origin=(0, 0))
        def libre(d): return A_.intersection(poser_b(phi, d)).area < 1e-6
        cotes = []
        for s in (1, -1):
            lo, hi = 0.0, s * 360.0 / zb
            if not libre(0.0): cotes.append(0.0); continue
            for _ in range(30):
                mid = (lo + hi) / 2
                if libre(mid): lo = mid
                else: hi = mid
            cotes.append(abs(lo))
        jeux.append(math.radians(sum(cotes)) * rp_b)
    return dict(positions=n + 1, tours_A=tours, interference_max_mm2=round(pire_aire, 5), a_l_angle=lieu,
                distance_min_mm=round(dmin, 3), jeu_mesure_mm=(round(min(jeux), 3), round(max(jeux), 3)) if jeux else None,
                duree_s=round(time.time() - t0, 2), ok=pire_aire < 1e-4)


def engrenages_droits_34(module=1.5, za=18, zb=36, epaisseur=6.0, jeu_cible=0.2, ecart_entraxe=None, alpha=20.0,
                         d_axe=5.0, jeu_axe=0.2, tours=2.0, simuler=True, jeu_par="entraxe"):
    """Paire de roues droites à développante (profil 2D calculé ici : shapely, puis extrudé), entraxe = théorique + ecart_entraxe.
    jeu_cible = jeu entre dents au primitif. jeu_par="entraxe" (défaut, comme LC3D A.engrenage l'attend) : dents pleines et
    entraxe écarté de jeu_cible / (2·tan α) (0,275 mm pour 0,2); jeu_par="dents" : entraxe théorique, chaque dent amincie de
    jeu_cible/2 (garde l'entraxe exact, ex. boîtier imposé). La simulation 2D fait tourner A de `tours`
    tours, vérifie qu'aucune dent ne se chevauche, et MESURE le vrai jeu (dichotomie) : il doit être jeu_cible ± 0,05.
    Repère : A en (0, 0), B en (entraxe, 0), de z = 0 à z = épaisseur; B déjà tournée de sa phase (prête pour l'assemblage)."""
    al = math.radians(alpha)
    if jeu_par not in ("entraxe", "dents"): raise ValueError("jeu_par = 'entraxe' (dents pleines, entraxe écarté) ou 'dents' (dents amincies)")
    if ecart_entraxe is None: ecart_entraxe = jeu_cible / (2 * math.tan(al)) if jeu_par == "entraxe" else 0.0
    j_dents = jeu_cible if jeu_par == "dents" else 0.0
    Pa, ia = _profil_developpante(module, za, alpha, j_dents)
    Pb, ib = _profil_developpante(module, zb, alpha, j_dents)
    a_th = module * (za + zb) / 2; ent = a_th + ecart_entraxe
    # rapport de conduite (doit être ≥ 1,2 : toujours au moins une dent en prise)
    def rc(ra, rb): return math.sqrt(ra ** 2 - rb ** 2)
    alpha_w = math.acos(a_th * math.cos(al) / ent)
    eps = (rc(ia["ra"], ia["rb"]) + rc(ib["ra"], ib["rb"]) - ent * math.sin(alpha_w)) / (math.pi * module * math.cos(al))
    sim = simuler_engrenages_2d(Pa, Pb, za, zb, ent, tours=tours, rp_b=ib["rp"]) if simuler else None
    # jeu attendu : jeu_cible + effet de l'écart d'entraxe (≈ 2·Δa·tan α)
    attendu = j_dents + 2 * ecart_entraxe * math.tan(al)
    notes = []
    if eps < 1.2: notes.append(f"rapport de conduite {eps:.2f} < 1,2 : chocs, plus de dents ou angle 20°")
    info = [f"{za} dents < 17 : pied radial sous le cercle de base (pas de taillage réel) — la simulation 2D tranche"] if za < 17 else []
    if sim and not sim["ok"]: notes.append(f"interférence {sim['interference_max_mm2']} mm² à {sim['a_l_angle']}° de A")
    if sim and sim["jeu_mesure_mm"] and not (attendu - 0.05 <= sim["jeu_mesure_mm"][0] and sim["jeu_mesure_mm"][1] <= attendu + 0.05):
        notes.append(f"jeu mesuré {sim['jeu_mesure_mm']} hors {attendu:.2f} ± 0,05")
    phase_b = 180.0 + 180.0 / zb
    def solide(P):
        pts = list(P.exterior.coords)[:-1]
        s = cq.Workplane("XY").polyline(pts).close().extrude(epaisseur)
        return s.cut(cq.Workplane("XY").circle(d_axe / 2 + jeu_axe).extrude(epaisseur + 2).translate((0, 0, -1)))
    roue_a = solide(Pa)
    roue_b = solide(Pb).rotate((0, 0, 0), (0, 0, 1), phase_b).translate((ent, 0, 0))
    return dict(roue_a=roue_a, roue_b=roue_b, profil_a=Pa, profil_b=Pb, entraxe=round(ent, 4), phase_b_deg=phase_b,
                numero=34, nom="engrenages droits à développante (simulés en 2D)",
                cotes=dict(module=module, dents=f"{za}/{zb}", rapport=round(zb / za, 4), angle_pression=alpha, entraxe_theorique=a_th,
                           entraxe=round(ent, 4), ecart_entraxe=round(ecart_entraxe, 3), jeu_par=jeu_par, jeu_cible=jeu_cible, jeu_attendu=round(attendu, 3),
                           d_tete=f"{2 * ia['ra']:.2f} / {2 * ib['ra']:.2f}", d_pied=f"{2 * ia['rf']:.2f} / {2 * ib['rf']:.2f}",
                           epaisseur=epaisseur, trou=f"Ø{d_axe + 2 * jeu_axe}"),
                calcul=dict(rapport_conduite=round(eps, 2), simulation=sim, verdict="✅" if not notes else "❌", notes=notes, info=info),
                note="Imprimer les roues à plat. Jeu 0,15-0,25 en FDM 0,4 (0,2 conseillé); trou d'axe à 0,2/côté (un trou lâche change l'entraxe). "
                     "Engrenages fonctionnels : PETG/PA, 100 % de remplissage dans les dents (4 murs).")


LOT_D = {31: charniere_cones_31, 32: berceau_fiche_32, 33: encoche_ouverte_33, 34: engrenages_droits_34}

FICHES_D = [
    dict(num=31, nom="charnière à cônes 45° imprimée en place", type="charniere", fonction="charniere_cones_31",
         besoins="charniere couvercle boite ouvrir pivot imprime en place sans support sans axe print in place",
         description="Deux feuilles imprimées à plat déjà assemblées, noeuds alternés, cônes mâles 45° dans des creux décalés de jeu·√2 : "
                     "s'imprime sans support, aucun axe à ajouter, jeu réglable (0,3-0,5), s'ouvre de 0 à 180°.",
         cotes_fixes=dict(angle_cones="45°", pied_noeud="45°"), cotes_ajustables=dict(longueur="40 mm", n_noeuds="5", R="4 mm", t="3 mm", jeu="0,4 mm"),
         statut="calcule"),
    dict(num=32, nom="berceau qui tient une fiche USB-C / USB-B", type="cable", fonction="berceau_fiche_32",
         besoins="usb fiche cable tenir support telephone chargeur poser appareil station recharge connecteur",
         description="Poche au surmoulage réel (+0,2/côté) avec nervures d'écrasement (serrage 0,1) : la fiche reste dans le support, "
                     "on pose l'appareil dessus. Entrée chanfreinée, fente de câble ouverte sur le devant.",
         cotes_fixes=dict(serrage_nervures="0,1 mm"), cotes_ajustables=dict(type="usb_c / usb_b / usb_a / micro_usb", jeu="0,2", nervure="0,3"),
         statut="calcule"),
    dict(num=33, nom="encoche de câble ouverte jusqu'au bord", type="cable", fonction="encoche_ouverte_33",
         besoins="boite arduino carte cable usb brancher passage trou encoche enlever sans debrancher boitier",
         description="Passage de la vraie fiche (surmoulage + 0,5/côté) ouvert jusqu'au haut du mur, coins du bas arrondis : "
                     "on pose la carte câble branché et on l'enlève sans débrancher. Aucun plafond : sans support.",
         cotes_fixes=dict(coins_bas="r 1,5"), cotes_ajustables=dict(type="usb_b", z_axe="10 mm", ep_mur="2,5", jeu="0,5"), statut="calcule"),
    dict(num=34, nom="engrenages droits à développante simulés", type="engrenage", fonction="engrenages_droits_34",
         besoins="engrenage roue dentee reducteur pignon rapport transmission tourner developpante",
         description="Profil à développante calculé (module, dents, angle 20°), entraxe théorique + écart, jeu cible entre dents; "
                     "simulation 2D de N tours (interférence) et jeu MESURÉ par dichotomie, en quelques secondes.",
         cotes_fixes=dict(angle_pression="20°"), cotes_ajustables=dict(module="1,5", za="18", zb="36", jeu_cible="0,2 mm", jeu_par="entraxe (+0,275) ou dents"),
         statut="calcule"),
]
