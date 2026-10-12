#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Laboratorio 1 - Inventario, estado y configuración segura (Netmiko)
Curso: ITIEL-13 - Redes Programables (base: lab1_plantilla.py del profesor)

Estado: R1, R2, R3, R4 (MikroTik) y R5 completos. R6 pendiente (ver TODO).

USO:
    pip install -r requirements.txt
    export LAB_PASS_MT_LAB='...'
    python lab1_inventario.py
    python lab1_inventario.py --limpiar     # (R6) eliminar sus objetos
"""

import argparse
import getpass
import json
import os
import re
from datetime import datetime

import yaml
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

# R4: comandos por TIPO de equipo (no por equipo).
COMANDOS = {
    "mikrotik_routeros": {
        "nombre": "/system identity print",
        "uptime": "/system resource print",
        "interfaces": "/ip address print terse",
        "gateway": "/ip route print terse where dst-address=0.0.0.0/0",
    },
    # (Extra) "cisco_ios": {"nombre": "...", "uptime": "...", ...},
}


# ------------------------------------------------------------------------------
# R1 / R2
# ------------------------------------------------------------------------------
def cargar_inventario(ruta="inventario.yaml"):
    """R1: devuelve el diccionario del YAML (estudiante + lista de equipos)."""
    with open(ruta, encoding="utf-8") as f:
        inv = yaml.safe_load(f)
    n = inv.get("estudiante")
    if not isinstance(n, int) or n <= 0:
        raise SystemExit("inventario.yaml: 'estudiante' debe ser su número de lista (entero > 0)")
    return inv


def obtener_clave(nombre_equipo):
    """R2: LAB_PASS_<NOMBRE> o getpass. 'mt-lab' -> LAB_PASS_MT_LAB"""
    variable = "LAB_PASS_" + nombre_equipo.upper().replace("-", "_")
    return os.getenv(variable) or getpass.getpass(f"Clave para {nombre_equipo} ({variable}): ")


# ------------------------------------------------------------------------------
# R4: parsers (texto -> estructura)
# ------------------------------------------------------------------------------
def parse_kv(texto):
    """Líneas 'clave: valor' (print normal de RouterOS) -> dict."""
    datos = {}
    for linea in texto.splitlines():
        if ":" in linea:
            k, v = linea.split(":", 1)
            datos[k.strip()] = v.strip()
    return datos


def parse_terse(texto):
    """Salida 'print terse' (clave=valor por línea) -> lista de dicts."""
    registros = []
    for linea in texto.splitlines():
        pares = re.findall(r"([\w-]+)=(\S*)", linea)
        if pares:
            registros.append(dict(pares))
    return registros


# Un parser por (device_type, dato). Agregar fabricante = agregar una entrada.
PARSERS = {
    "mikrotik_routeros": {
        "nombre": lambda s: parse_kv(s).get("name"),
        "uptime": lambda s: parse_kv(s).get("uptime"),
        "interfaces": lambda s: [{"interfaz": r.get("interface"), "ip": r.get("address")}
                                 for r in parse_terse(s)],
        "gateway": lambda s: next((r.get("gateway") for r in parse_terse(s)), None),
    },
}


def parsear(device_type, dato, salida):
    """R4: convierte 'salida' (texto) en un valor estructurado."""
    parser = PARSERS.get(device_type, {}).get(dato)
    return parser(salida) if parser else salida.strip()


# ------------------------------------------------------------------------------
# R6: cambio sin duplicados: consultar antes de crear (solo rol: escritura)
# ------------------------------------------------------------------------------
def asegurar_loopback(conn, n, limpiar=False):
    """TODO R6: lo-ssh-<n> + 10.253.0.<n>/32. Consultar ANTES de crear.
    Debe devolver True si hubo cambios y False si ya estaba todo bien."""
    return False


# ------------------------------------------------------------------------------
# R3: un equipo
# ------------------------------------------------------------------------------
def procesar_equipo(eq, n, limpiar):
    """Conecta a UN equipo, recolecta su estado y (si aplica) aplica R6.
    Siempre devuelve un diccionario: si falla, con estado = mensaje de error."""
    resultado = {"nombre": eq["nombre"], "host": eq["host"],
                 "fecha": datetime.now().isoformat(timespec="seconds")}
    os.makedirs("logs", exist_ok=True)
    dispositivo = {
        "device_type": eq["device_type"],
        "host": eq["host"],
        "username": eq["usuario"],
        "password": obtener_clave(eq["nombre"]),
        "session_log": f"logs/{eq['nombre']}.log",
        "conn_timeout": 20,
    }
    try:
        with ConnectHandler(**dispositivo) as conn:
            datos = {}
            for dato, cmd in COMANDOS.get(eq["device_type"], {}).items():
                datos[dato] = parsear(eq["device_type"], dato, conn.send_command(cmd, read_timeout=20))
            resultado["datos"] = datos

            if eq.get("rol") == "escritura":
                resultado["cambios"] = asegurar_loopback(conn, n, limpiar)
        resultado["estado"] = "ok"
    except NetmikoTimeoutException:
        resultado["estado"] = "error: timeout (IP, SSH apagado, Tailscale)"
    except NetmikoAuthenticationException:
        resultado["estado"] = "error: autenticación"
    except Exception as e:                       # cualquier otro imprevisto
        resultado["estado"] = f"error: {e}"
    return resultado


# ------------------------------------------------------------------------------
# R5: reporte
# ------------------------------------------------------------------------------
def guardar_reporte(resultados, ruta="reporte_estado.json"):
    """R5 (parte 1): JSON con todos los equipos."""
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)


def imprimir_resumen(resultados):
    """R5 (parte 2): tabla equipo | IP | estado | #interfaces | gateway."""
    print(f"\n{'EQUIPO':<14}{'IP':<16}{'ESTADO':<30}{'IFACES':<8}GATEWAY")
    print("-" * 80)
    for r in resultados:
        d = r.get("datos") or {}
        ifaces = d.get("interfaces")
        cant = len(ifaces) if isinstance(ifaces, list) else "-"
        print(f"{r['nombre']:<14}{r['host']:<16}{r['estado'][:28]:<30}"
              f"{cant!s:<8}{d.get('gateway') or '-'}")


def main():
    parser = argparse.ArgumentParser(description="Laboratorio 1 - Netmiko")
    parser.add_argument("--inventario", default="inventario.yaml")
    parser.add_argument("--limpiar", action="store_true", help="R6: eliminar sus objetos")
    args = parser.parse_args()

    inv = cargar_inventario(args.inventario)
    n = inv["estudiante"]
    resultados = [procesar_equipo(eq, n, args.limpiar) for eq in inv["equipos"]]

    guardar_reporte(resultados)
    imprimir_resumen(resultados)


if __name__ == "__main__":
    main()
