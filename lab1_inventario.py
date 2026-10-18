#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Laboratorio 1 - Inventario, estado y configuración segura (Netmiko)
Curso: ITIEL-13 - Redes Programables (base: lab1_plantilla.py del profesor)

Estado: R1-R6 completos + extras (Cisco IOS multivendor y REST del MikroTik).

USO:
    pip install -r requirements.txt
    export LAB_PASS_MT_LAB='...'
    export LAB_PASS_CISCO='...'
    python lab1_inventario.py
    python lab1_inventario.py --limpiar     # (R6) eliminar sus objetos
"""

import argparse
import getpass
import json
import os
import re
from datetime import datetime

import requests
import urllib3
import yaml
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

# El MikroTik usa un certificado autofirmado: se desactiva la verificación y su aviso.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ESTUDIANTE = "Kristel Gamboa"

# R4: comandos por TIPO de equipo (no por equipo).
COMANDOS = {
    "mikrotik_routeros": {
        "nombre": "/system identity print",
        "uptime": "/system resource print",
        "interfaces": "/ip address print terse",
        "gateway": "/ip route print terse where dst-address=0.0.0.0/0",
    },
    "cisco_ios": {
        "nombre": "show running-config | include hostname",
        "uptime": "show version | include uptime",
        "interfaces": "show ip interface brief | exclude unassigned",
        "gateway": "show ip route 0.0.0.0",
    },
}

# Extra REST: recursos de la API REST de RouterOS para los mismos 4 datos.
REST_RECURSOS = {
    "nombre": "/system/identity",
    "uptime": "/system/resource",
    "interfaces": "/ip/address",
    "gateway": "/ip/route?dst-address=0.0.0.0/0",
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


def buscar(patron, texto):
    """Primer grupo de 'patron' en 'texto' (multilínea) o None."""
    m = re.search(patron, texto, re.MULTILINE)
    return m.group(1).strip() if m else None


def parse_ip_brief(texto):
    """'show ip interface brief' -> lista de {interfaz, ip} (solo con IP asignada)."""
    interfaces = []
    for linea in texto.splitlines():
        campos = linea.split()
        if len(campos) >= 2 and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", campos[1]):
            interfaces.append({"interfaz": campos[0], "ip": campos[1]})
    return interfaces


# Un parser por (device_type, dato). Agregar fabricante = agregar una entrada.
PARSERS = {
    "mikrotik_routeros": {
        "nombre": lambda s: parse_kv(s).get("name"),
        "uptime": lambda s: parse_kv(s).get("uptime"),
        "interfaces": lambda s: [{"interfaz": r.get("interface"), "ip": r.get("address")}
                                 for r in parse_terse(s)],
        "gateway": lambda s: next((r.get("gateway") for r in parse_terse(s)), None),
    },
    "cisco_ios": {
        "nombre": lambda s: buscar(r"^hostname\s+(\S+)", s),
        "uptime": lambda s: buscar(r"uptime is (.+)$", s),
        "interfaces": parse_ip_brief,
        "gateway": lambda s: buscar(r"^\s*\*\s+(\d+\.\d+\.\d+\.\d+)", s),
    },
}


def parsear(device_type, dato, salida):
    """R4: convierte 'salida' (texto) en un valor estructurado."""
    parser = PARSERS.get(device_type, {}).get(dato)
    return parser(salida) if parser else salida.strip()


# ------------------------------------------------------------------------------
# R6: cambio sin duplicados: consultar antes de crear (solo rol: escritura)
# ------------------------------------------------------------------------------
def contar(conn, ruta, filtro):
    """Cuántos objetos de 'ruta' cumplen 'filtro' (consulta de solo lectura)."""
    salida = conn.send_command(f":put [:len [{ruta} find {filtro}]]")
    return int(buscar(r"^\s*(\d+)\s*$", salida) or 0)


def asegurar_loopback(conn, n, limpiar=False):
    """R6: lo-ssh-<n> + 10.253.0.<n>/32. Consultar ANTES de crear.
    Devuelve True si hubo cambios y False si ya estaba todo bien.
    Solo busca por el nombre/IP exactos del estudiante: nunca toca objetos ajenos."""
    bridge = f"lo-ssh-{n}"
    ip = f"10.253.0.{n}/32"
    comentario = f"{ESTUDIANTE} (N={n})"
    f_bridge = f'name="{bridge}"'
    f_ip = f'address="{ip}" interface="{bridge}"'
    cambios = False

    if limpiar:
        # Primero la IP (depende del bridge) y después el bridge.
        if contar(conn, "/ip address", f_ip):
            conn.send_command(f"/ip address remove [find {f_ip}]")
            cambios = True
        if contar(conn, "/interface bridge", f_bridge):
            conn.send_command(f"/interface bridge remove [find {f_bridge}]")
            cambios = True
        if contar(conn, "/ip address", f_ip) or contar(conn, "/interface bridge", f_bridge):
            raise RuntimeError(f"R6: no se pudo eliminar {bridge}")
        return cambios

    if not contar(conn, "/interface bridge", f_bridge):
        conn.send_command(f'/interface bridge add name="{bridge}" comment="{comentario}"')
        cambios = True
    elif not contar(conn, "/interface bridge", f'{f_bridge} comment="{comentario}"'):
        conn.send_command(f'/interface bridge set [find {f_bridge}] comment="{comentario}"')
        cambios = True

    if not contar(conn, "/ip address", f_ip):
        conn.send_command(f'/ip address add address={ip} interface="{bridge}" comment="{comentario}"')
        cambios = True

    # Verificación con comandos de lectura después del cambio.
    if contar(conn, "/interface bridge", f'{f_bridge} comment="{comentario}"') != 1 \
            or contar(conn, "/ip address", f_ip) != 1:
        raise RuntimeError(f"R6: la verificación de {bridge} / {ip} falló")
    return cambios


# ------------------------------------------------------------------------------
# Extra: estado del MikroTik por la API REST (requests) para comparar con SSH
# ------------------------------------------------------------------------------
def estado_rest(eq, clave):
    """Obtiene los mismos 4 datos por REST. Devuelve {estado, datos}."""
    base = eq["rest"].rstrip("/")
    auth = (eq["usuario"], clave)
    try:
        r = {}
        for dato, recurso in REST_RECURSOS.items():
            resp = requests.get(base + recurso, auth=auth, verify=False, timeout=10)
            resp.raise_for_status()
            r[dato] = resp.json()
        datos = {
            "nombre": r["nombre"].get("name"),
            "uptime": r["uptime"].get("uptime"),
            "interfaces": [{"interfaz": a.get("interface"), "ip": a.get("address")}
                           for a in r["interfaces"]],
            "gateway": next((rt.get("gateway") for rt in r["gateway"]), None),
        }
        return {"estado": "ok", "datos": datos}
    except requests.exceptions.HTTPError as e:
        return {"estado": f"error: HTTP {e.response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"estado": f"error: {type(e).__name__}"}


def comparar(ssh, rest):
    """Dato por dato: True si SSH y REST coinciden. El uptime cambia entre una
    consulta y otra, así que solo se reporta, no se compara."""
    return {dato: ssh.get(dato) == rest.get(dato)
            for dato in REST_RECURSOS if dato != "uptime"}


# ------------------------------------------------------------------------------
# R3: un equipo
# ------------------------------------------------------------------------------
def procesar_equipo(eq, n, limpiar):
    """Conecta a UN equipo, recolecta su estado y (si aplica) aplica R6.
    Siempre devuelve un diccionario: si falla, con estado = mensaje de error."""
    resultado = {"nombre": eq["nombre"], "host": eq["host"],
                 "device_type": eq["device_type"],
                 "fecha": datetime.now().isoformat(timespec="seconds")}
    os.makedirs("logs", exist_ok=True)
    try:
        clave = obtener_clave(eq["nombre"])
        dispositivo = {
            "device_type": eq["device_type"],
            "host": eq["host"],
            "username": eq["usuario"],
            "password": clave,
            "session_log": f"logs/{eq['nombre']}.log",
            "conn_timeout": 20,
        }
        with ConnectHandler(**dispositivo) as conn:
            datos = {}
            for dato, cmd in COMANDOS.get(eq["device_type"], {}).items():
                datos[dato] = parsear(eq["device_type"], dato, conn.send_command(cmd, read_timeout=20))
            resultado["datos"] = datos

            if eq.get("rol") == "escritura":
                cambios = asegurar_loopback(conn, n, limpiar)
                resultado["cambios"] = cambios
                if limpiar:
                    msg = "objetos eliminados" if cambios else "nada que limpiar"
                else:
                    msg = "cambios aplicados" if cambios else "sin cambios"
                print(f"R6 {eq['nombre']}: {msg}")
        resultado["estado"] = "ok"
    except NetmikoTimeoutException:
        resultado["estado"] = "error: timeout (IP, SSH apagado o red caída)"
    except NetmikoAuthenticationException:
        resultado["estado"] = "error: autenticación"
    except Exception as e:                       # cualquier otro imprevisto
        resultado["estado"] = f"error: {e}"

    if resultado["estado"] != "ok":
        print(f"[X] {eq['nombre']} ({eq['host']}): {resultado['estado']} -> se continúa")

    # Extra REST: solo para equipos con 'rest' en el inventario.
    if eq.get("rest") and resultado["estado"] == "ok":
        rest = estado_rest(eq, clave)
        if rest["estado"] == "ok":
            rest["coincide"] = comparar(resultado["datos"], rest["datos"])
        resultado["rest"] = rest
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

    # Extra REST: comparación SSH vs. REST.
    con_rest = [r for r in resultados if "rest" in r]
    if con_rest:
        print(f"\n{'SSH vs. REST':<14}{'ESTADO REST':<30}COINCIDE")
        print("-" * 80)
        for r in con_rest:
            coincide = r["rest"].get("coincide")
            detalle = (", ".join(f"{k}={'sí' if v else 'NO'}" for k, v in coincide.items())
                       if coincide else "-")
            print(f"{r['nombre']:<14}{r['rest']['estado'][:28]:<30}{detalle}")


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
