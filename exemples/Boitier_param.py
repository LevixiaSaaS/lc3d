"""Boîtier construit avec les gestes paramétriques (export FreeCAD modifiable)."""
from lc3d import Piece, Assemblage, Atelier

PARAMS = dict(L=60.0, l=40.0, h=30.0, mur=2.0, r=6.0, d_cable=8.0)

def build(p):
    a = Atelier("boitier")
    a.bloc(p["L"], p["l"], p["h"], titre="Tracer le bloc et monter")
    a.arrondir("|Z", p["r"], titre="Arrondir les coins")
    a.bloc(p["L"] - 2 * p["mur"], p["l"] - 2 * p["mur"], p["h"], pos=(0, 0, p["mur"]), op="coupe", titre="Creuser l'intérieur")
    a.trou(p["d_cable"], p["mur"] + 2, pos=(p["L"] / 2 - p["mur"] - 1, 0, p["h"] / 2), axe="X", titre="Percer le trou du câble")
    return {"boitier": Piece("boitier", a.forme)}

def assembly(p, pieces):
    A = Assemblage(); A.place("boitier"); return A
