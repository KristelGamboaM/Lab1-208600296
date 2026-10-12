# Laboratorio 1: Inventario, estado y configuración segura con Python + SSH (Netmiko)
 
**Curso:** ITIEL-13 - Redes Programables (Grupo 01) · **Profesor:** Randall Zamora Rojas
**Estudiante:** Kristel Gamboa · **Carnet:** 208600296 · **Número de lista (N):** 12
 
Script en Python que lee un inventario YAML, se conecta por SSH con Netmiko a los equipos
del laboratorio GNS3, recolecta su estado como datos estructurados (JSON) y asegura en el
MikroTik un cambio de configuración **sin duplicados** (idempotente).
 
## Estructura del repositorio
 
```
lab1-208600296/
├── README.md
├── requirements.txt        # netmiko, pyyaml
├── .gitignore              # venv/, __pycache__/, logs con datos sensibles
├── inventario.yaml         # inventario SIN contraseñas
├── lab1_inventario.py      # script principal
├── reporte_estado.json     # salida de una ejecución real
└── logs/                   # session_log de cada equipo
```
 
## Instalación
 
Requiere Python 3.10+ en Linux (probado en Linux Mint, Python 3.12).
 
```bash
git clone https://github.com/KristelGamboaM/Lab1-208600296.git
cd Lab1-208600296
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
 
## Configuración
 
### 1. Inventario (`inventario.yaml`)
 
```yaml
estudiante: 12                   # su número de lista N
 
equipos:
  - nombre: mt-lab
    host: 10.60.30.202
    device_type: mikrotik_routeros
    usuario: lab-ssh
    rol: escritura        # "lectura" = solo consulta, "escritura" = además aplica R6
```
 
El archivo **no contiene contraseñas**.
 
### 2. Credenciales (variables de entorno)
 
La clave de cada equipo se lee de `LAB_PASS_<NOMBRE>` (nombre en mayúsculas y guiones
como `_`). Si la variable no existe, el script la pide con `getpass`.
 
| Equipo en el YAML | Variable de entorno |
|---|---|
| `mt-lab` | `LAB_PASS_MT_LAB` |
| `cisco-gns3` | `LAB_PASS_CISCO_GNS3` |
 
```bash
export LAB_PASS_MT_LAB='su_clave'
```
 
## Ejecución
 
```bash
python3 lab1_inventario.py              # consulta el estado y asegura lo-ssh-N en el MikroTik
python3 lab1_inventario.py --limpiar    # elimina solo sus objetos (lo-ssh-N y su IP)
python3 lab1_inventario.py --inventario otro.yaml
```
 
Salida: tabla en consola (equipo, IP, estado, cantidad de interfaces, gateway por defecto),
`reporte_estado.json` y un `logs/<equipo>.log` por cada equipo.
 
## Cómo cumple cada requerimiento
 
| Req. | Implementación |
|---|---|
| **R1** Inventario externo | `inventario.yaml`, leído con `yaml.safe_load` en `cargar_inventario()`. Valida que `estudiante` sea un entero positivo. |
| **R2** Credenciales seguras | `obtener_clave()`: variable `LAB_PASS_<NOMBRE>` y, si no existe, `getpass`. Ninguna clave en código, YAML ni repo. |
| **R3** Conexión robusta | `ConnectHandler` dentro de `with`; se manejan `NetmikoTimeoutException`, `NetmikoAuthenticationException` y `Exception` **por equipo**: si uno falla se registra el error y se continúa con los demás. `session_log` por equipo en `logs/`. |
| **R4** Estado estructurado | Diccionario `COMANDOS` por `device_type` y diccionario `PARSERS` con una función por dato. Se obtienen `nombre`, `uptime`, `interfaces` (lista de `{interfaz, ip}`) y `gateway`. Agregar otro fabricante es agregar una entrada en cada diccionario. |
| **R5** Reporte | `reporte_estado.json` (equipos, fecha/hora, estado `ok` o mensaje de error, datos) y tabla resumen en consola. |
| **R6** Cambio sin duplicados | `asegurar_loopback()`: consulta con `:put [:len [... find ...]]`, crea solo lo que falta, verifica con un comando de lectura y devuelve `True` (hubo cambios) o `False` ("sin cambios"). Con `--limpiar` elimina solo `lo-ssh-N` y `10.253.0.N/32`. Busca únicamente por su nombre e IP exactos, nunca toca objetos de otros estudiantes. |
 
### Detalle de R6
 
Objetos que se aseguran en el MikroTik (con `N` = su número de lista):
 
- Bridge sin puertos `lo-ssh-N`, con comentario con su nombre.
- IP `10.253.0.N/32` sobre ese bridge, con el mismo comentario.
Comportamiento esperado:
 
1. Primera ejecución → `R6 mt-lab: cambios aplicados`
2. Segunda ejecución → `R6 mt-lab: sin cambios`
3. `--limpiar` → `R6 mt-lab: objetos eliminados`; si se repite → `nada que limpiar`
Verificación manual en el MikroTik:
 
```routeros
/interface bridge print
/ip address print
```
 
## Pruebas del manejo de errores
 
- Clave incorrecta: `export LAB_PASS_MT_LAB=mala` → el equipo aparece con `error: autenticación` y el script no se detiene.
- Sin conectividad (equipo apagado, IP incorrecta o VPN caída) → `error: timeout`.

## Declaración de uso de IA
 
Se utilizó **Claude (Anthropic)** como asistente de apoyo únicamente para:
 
- **Guía para montar el laboratorio:** configuración inicial del MikroTik en GNS3 (IP, usuario SSH y servicio SSH).
- **Elaboración de `lab1_inventario.py`:** parsers de R4, tabla de resumen de R5 y función `asegurar_loopback()` de R6, partiendo de la plantilla del profesor.
El código fue ejecutado y probado contra el MikroTik del laboratorio.
