"""Démo du Studio : petit boîtier construit geste par geste ."""
import cadquery as cq
from lc3d import Piece, Assemblage, Atelier

PARAMS = dict(L=60.0, l=40.0, h=30.0, mur=2.0, jeu=0.3)


def build(p):
    L, l, h, m = p["L"], p["l"], p["h"], p["mur"]
    a = Atelier("boitier")
    a.ajouter(cq.Workplane("XY").rect(L, l).extrude(h), f"Tracer {L:.0f} × {l:.0f} et monter de {h:.0f} mm")
    a.modifier(lambda f: f.edges("|Z").fillet(6), "Arrondir les coins R6")
    a.couper(cq.Workplane("XY").workplane(offset=m).rect(L - 2 * m, l - 2 * m).extrude(h), f"Creuser l'intérieur (murs {m:.0f} mm)")
    a.couper(cq.Workplane("YZ").workplane(offset=L / 2 - 4).center(0, h / 2).circle(4).extrude(8), "Percer le trou du câble Ø8")
    a.couper(cq.Workplane("XY").rect(L - 20, 3).extrude(1).translate((0, 0, 0)), "Graver la fente d'aération")
    c = Atelier("couvercle")
    c.ajouter(cq.Workplane("XY").rect(L, l).extrude(2.5).translate((0, 0, h)), "Tracer le couvercle et monter de 2,5 mm")
    c.modifier(lambda f: f.edges("|Z").fillet(6), "Arrondir les coins R6")
    c.ajouter(cq.Workplane("XY").rect(L - 2 * m - 2 * p["jeu"], l - 2 * m - 2 * p["jeu"]).extrude(4).translate((0, 0, h - 4))
              .cut(cq.Workplane("XY").rect(L - 2 * m - 2 * p["jeu"] - 3, l - 2 * m - 2 * p["jeu"] - 3).extrude(4).translate((0, 0, h - 4))),
              "Ajouter la lèvre qui entre dans la boîte")
    return {"boitier": Piece("boitier", a.forme), "couvercle": Piece("couvercle", c.forme)}


def assembly(p, pieces):
    A = Assemblage()
    A.place("boitier"); A.place("couvercle")
    A.inserer("couvercle", depuis=(0, 0, 25))
    return A
