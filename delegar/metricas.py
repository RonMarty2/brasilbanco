# -*- coding: utf-8 -*-
"""ENVOLTORIO del motor unico de agy (02-11-2026). El motor vive en _AGENTES_CENTRAL\\motor_agy; aqui solo se dice
QUE proyecto es (la carpeta de su agy.json). Mismo uso y mismos argumentos que antes. NO editar la logica aqui:
se edita el motor (una sola vez para todos los proyectos)."""
import os, sys, runpy

AQUI = os.path.dirname(os.path.abspath(__file__))


def subir_hasta(pred):
    d = AQUI
    while True:
        r = pred(d)
        if r:
            return r
        p = os.path.dirname(d)
        if p == d:
            return None
        d = p


PROYECTO = AQUI if os.path.exists(os.path.join(AQUI, "agy.json")) else None
CENTRAL = subir_hasta(lambda d: next((c for c in (os.path.join(d, "_AGENTES_CENTRAL"), os.path.join(d, "12.NUBES", "_AGENTES_CENTRAL"))
                                      if os.path.isdir(os.path.join(c, "motor_agy"))), None))
if not PROYECTO or not CENTRAL:
    falta = "el proyecto (agy.json)" if not PROYECTO else "_AGENTES_CENTRAL/motor_agy"
    sys.exit("[!] envoltorio de agy: no encontre " + falta + " subiendo desde " + AQUI)
os.environ["AGY_PROYECTO"] = PROYECTO
motor = os.path.join(CENTRAL, "motor_agy", os.path.basename(__file__))
sys.argv[0] = motor
runpy.run_path(motor, run_name="__main__")
