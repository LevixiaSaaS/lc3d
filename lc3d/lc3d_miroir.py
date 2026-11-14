"""LC3D — boucle miroir : la pièce se compare à la PHOTO de l'objet et dit où elle diffère.

Photo prise de face (ou de dessus), d'assez loin (≥ 50 cm, zoom), objet sur fond uni, avec une carte de crédit
(85,6 × 54 mm) posée à plat dans le même plan que la face photographiée — elle donne l'échelle.
1. Silhouette de l'objet (OpenCV : GrabCut à partir du cadre de l'objet) et de la carte (rectangle 85,6 × 54 le plus probable).
2. Rendu de la silhouette de la pièce LC3D vue du même côté (projection orthographique).
3. Superposition à la même échelle : % de ressemblance (IoU) + écarts mesurés (largeur et hauteur par tranche,
   « en haut, 4,1 mm trop large »).
Claude corrige le paramètre en cause et relance jusqu'à ≥ 95 % ou jusqu'à ce que ça ne s'améliore plus.
Plusieurs photos (face, côté, dessus) = plusieurs vues comparées.
Limite honnête : vue supposée de face (perspective faible); une photo de près ou en biais fausse les cotes de quelques %.
"""
import json, os, math
import numpy as np

CARTE = (85.6, 54.0)
VUES = {"face": (0, 2, 1), "dessus": (0, 1, 2), "cote": (1, 2, 0)}     # (axe horizontal, axe vertical, axe de profondeur) dans le repère pièce


def silhouette_photo(chemin, cadre=None, carte=None):
    """Retourne (masque objet, mm_par_px, infos). cadre = (x, y, l, h) de l'objet en px (sinon : plus gros objet contrasté).
    carte = (x, y, l, h) de la carte en px (sinon : détection du rectangle au bon rapport)."""
    import cv2
    img = cv2.imread(chemin); g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); H, W = g.shape
    bords = cv2.Canny(cv2.GaussianBlur(g, (5, 5), 0), 40, 120)
    bords = cv2.dilate(bords, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(bords, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects = []
    for c in cnts:
        if cv2.contourArea(c) < 0.002 * W * H: continue
        r = cv2.minAreaRect(c); (w, h) = sorted(r[1])
        if w <= 0: continue
        rapport = h / w; plein = cv2.contourArea(c) / (w * h + 1e-9)
        rects.append((abs(rapport - CARTE[0] / CARTE[1]), plein, r, c))
    mm_px = None
    if carte:
        mm_px = CARTE[0] / max(carte[2], carte[3])
    else:
        cands = [x for x in rects if x[0] < 0.08 and x[1] > 0.85]
        if cands:
            r = min(cands, key=lambda x: x[0])[2]; mm_px = CARTE[0] / max(r[1])
    # objet : plus gros contour qui n'est pas la carte
    objets = [x for x in rects if not (x[0] < 0.08 and x[1] > 0.85)]
    if cadre is None and objets:
        c = max(objets, key=lambda x: cv2.contourArea(x[3]))[3]; cadre = cv2.boundingRect(c)
    if cadre is None: raise ValueError("objet introuvable sur la photo : fond uni et bon contraste requis")
    masque = np.zeros((H, W), np.uint8); bg = np.zeros((1, 65), np.float64); fg = np.zeros((1, 65), np.float64)
    x, y, w, h = cadre; m = 8
    cv2.grabCut(img, masque, (max(0, x - m), max(0, y - m), min(W - 1, w + 2 * m), min(H - 1, h + 2 * m)), bg, fg, 5, cv2.GC_INIT_WITH_RECT)
    obj = np.where((masque == 1) | (masque == 3), 1, 0).astype(np.uint8)
    return obj, mm_px, dict(cadre=list(map(int, cadre)), mm_par_px=mm_px)


def silhouette_piece(meshes, vue="face", mm_par_px=0.2):
    """Projection orthographique des pièces (repère pièce) → masque binaire à mm_par_px."""
    import cv2
    ah, av, ap = VUES[vue]
    V = np.vstack([m.vertices for m in meshes]); lo = V[:, [ah, av]].min(0); hi = V[:, [ah, av]].max(0)
    W, H = (np.ceil((hi - lo) / mm_par_px).astype(int) + 4)
    masque = np.zeros((H, W), np.uint8)
    for m in meshes:
        P = (m.vertices[:, [ah, av]] - lo) / mm_par_px + 2
        P[:, 1] = H - P[:, 1]
        for t in np.round(P[m.faces]).astype(np.int32):      # triangle par triangle (fillPoly ferait du pair-impair)
            cv2.fillConvexPoly(masque, t, 1)
    return masque


def _recadrer(m):
    ys, xs = np.nonzero(m); return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def comparer(meshes, photo, vue="face", cadre=None, carte=None, mm_par_px=None, sortie_png=None):
    import cv2
    obj, mmpx, info = silhouette_photo(photo, cadre, carte)
    mmpx = mm_par_px or mmpx
    if not mmpx: raise ValueError("carte de crédit non trouvée : la mettre à plat, bien visible, ou donner mm_par_px")
    A = _recadrer(obj)
    B = _recadrer(silhouette_piece(meshes, vue, mmpx))
    H, W = max(A.shape[0], B.shape[0]), max(A.shape[1], B.shape[1])
    pa = np.zeros((H, W), np.uint8); pb = np.zeros((H, W), np.uint8)
    pa[H - A.shape[0]:, (W - A.shape[1]) // 2:(W - A.shape[1]) // 2 + A.shape[1]] = A   # alignés par le bas, centrés
    pb[H - B.shape[0]:, (W - B.shape[1]) // 2:(W - B.shape[1]) // 2 + B.shape[1]] = B
    inter = (pa & pb).sum(); union = (pa | pb).sum(); iou = inter / max(union, 1)
    ecarts = []
    for nom, (z0, z1) in (("en haut", (0.0, 0.25)), ("au milieu", (0.375, 0.625)), ("en bas", (0.75, 1.0))):
        r0, r1 = int(H * z0), max(int(H * z1), int(H * z0) + 1)
        la = pa[r0:r1].sum(1).mean() * mmpx; lb = pb[r0:r1].sum(1).mean() * mmpx
        if abs(lb - la) > 0.5: ecarts.append(f"{nom} : la pièce est {abs(lb - la):.1f} mm trop {'large' if lb > la else 'étroite'}")
    dh = (B.shape[0] - A.shape[0]) * mmpx; dw = (B.shape[1] - A.shape[1]) * mmpx
    if abs(dh) > 0.5: ecarts.insert(0, f"hauteur : {abs(dh):.1f} mm trop {'haute' if dh > 0 else 'basse'}")
    if abs(dw) > 0.5: ecarts.insert(0, f"largeur totale : {abs(dw):.1f} mm trop {'large' if dw > 0 else 'étroite'}")
    if sortie_png:
        vis = np.full((H, W, 3), 255, np.uint8); vis[pa == 1] = (90, 140, 230); vis[pb == 1] = (60, 120, 230)
        vis[(pa == 1) & (pb == 0)] = (40, 40, 220); vis[(pb == 1) & (pa == 0)] = (30, 140, 245)
        cv2.imwrite(sortie_png, vis)
    return dict(ressemblance_pct=round(100 * iou, 1), objet_mm=[round(A.shape[1] * mmpx, 1), round(A.shape[0] * mmpx, 1)],
                piece_mm=[round(B.shape[1] * mmpx, 1), round(B.shape[0] * mmpx, 1)], ecarts=ecarts, mm_par_px=round(mmpx, 4), image=sortie_png,
                objectif="≥ 95 % ; corriger le paramètre lié au plus gros écart et relancer")
