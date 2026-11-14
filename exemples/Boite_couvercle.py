"""Boîte + couvercle à lèvre (jeu 0,5) + trou Ø8 dans le couvercle : le couvercle doit FITTER, et le trou doit
arriver dans FreeCAD / OpenSCAD / Fusion avec les mêmes cotes."""
from lc3d import Piece, Assemblage, Atelier

PARAMS = dict(L=70.0, l=50.0, h=35.0, mur=2.0, r=5.0, fond=2.0, ep_c=2.5, levre=6.0, jeu=0.5, d_trou=8.0)


def build(p):
    b = Atelier("boite")
    b.bloc(p["L"], p["l"], p["h"], titre="Bloc de la boîte")
    b.bloc(p["L"] - 2 * p["mur"], p["l"] - 2 * p["mur"], p["h"], pos=(0, 0, p["fond"]), op="coupe", titre="Creuser la boîte")
    b.arrondir("|Z", p["r"], titre="Coins arrondis dehors et dedans")
    c = Atelier("couvercle")
    c.bloc(p["L"], p["l"], p["ep_c"], titre="Plaque du couvercle")
    c.bloc(p["L"] - 2 * p["mur"] - 2 * p["jeu"], p["l"] - 2 * p["mur"] - 2 * p["jeu"], p["levre"], pos=(0, 0, -p["levre"]), titre="Lèvre qui entre dans la boîte")
    c.bloc(p["L"] - 4 * p["mur"] - 2 * p["jeu"], p["l"] - 4 * p["mur"] - 2 * p["jeu"], p["levre"], pos=(0, 0, -p["levre"]), op="coupe", titre="Évider la lèvre")
    c.arrondir("|Z", p["r"], titre="Coins arrondis (plaque et lèvre)")
    c.trou(p["d_trou"], p["ep_c"] + p["levre"] + 2, pos=(p["L"] / 4, 0, -p["levre"] - 1), titre="Trou Ø du couvercle")
    return {"boite": Piece("boite", b.forme), "couvercle": Piece("couvercle", c.forme)}


def assembly(p, pieces):
    A = Assemblage(); A.place("boite"); A.place("couvercle", z=p["h"])
    A.assise("couvercle", "boite", aire_min=100)       # le couvercle POSE à plat sur le rebord de la boîte
    A.jeu("couvercle", "boite", minimum=0.5)          # jeu mesuré entre la lèvre et le mur intérieur
    A.inserer("couvercle", depuis=(0, 0, 30), pas=60)  # le couvercle descend dans la boîte sans accrocher
    return A
