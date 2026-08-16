"""
Cliente Python para el API "Reporte de Crédito Consolidado + FICO® Score y
PLD Check® - Personas Físicas" de Círculo de Crédito.

Flujo:
    1. Corres el script:  python api_circulo.py

    2. El script revisa la carpeta input/:
       - Si NO hay ningún .json ahí, usa la persona de ejemplo del sandbox
         (la de siempre) y consulta en DEV. Sirve para probar que todo
         sigue funcionando sin arriesgar una consulta pagada.
       - Si HAY uno o varios .json, consulta CADA UNO en PRODUCCIÓN y
         genera su propio JSON + XML de salida.

    El ambiente se puede forzar con --env dev / --env prod si quieres
    saltarte la detección automática.

    3. La respuesta de cada persona queda en output/: el JSON crudo del
       API y el XML en el formato clásico del buró
       (<Respuesta><Personas><Persona>...).

--------------------------------------------------------------------------
VARIABLES DE ENTORNO (van en el archivo .env de esta carpeta, nunca en el
código):

  Para AMBOS ambientes:
    CDC_API_KEY          -> tu x-api-key

  Solo para --env prod (además de CDC_API_KEY):
    CDC_PRIVATE_KEY_D     -> valor 'priv' de tu llave ECDSA, en hex, una sola
                             línea (openssl ec -in pri_key.pem -noout -text)
    CDC_USERNAME          -> usuario de Círculo de Crédito
    CDC_PASSWORD          -> contraseña de Círculo de Crédito
    CDC_PUBLIC_KEY_XY     -> (opcional) llave pública de Círculo de Crédito,
                             para verificar la firma que ellos regresan

  Opcionales, para cambiar dónde se leen/escriben los archivos:
    CDC_INPUT_DIR          -> carpeta donde se buscan los .json de entrada
                               (default: input)
    CDC_OUTPUT_DIR         -> carpeta donde se guardan JSON/XML/evidencias
                               (default: output)
                               Los flags --input y --output, si se pasan,
                               tienen prioridad sobre estas variables.

  Opcional, para que la consola no se cierre sola al terminar:
    CDC_PAUSAR_AL_TERMINAR -> "1" espera un ENTER antes de cerrar, "0" no
                               espera. Sin definir: espera solo si es el
                               .exe compilado.

--------------------------------------------------------------------------
Instalación (una sola vez):
    python -m venv venv
    venv\\Scripts\\pip install -r requirements.txt
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from xml.sax.saxutils import escape as _escape_xml

import requests
from ecdsa import SigningKey, VerifyingKey, NIST384p, BadSignatureError
from ecdsa.util import sigencode_der, sigdecode_der

# Carpeta donde vive el .env: la del .exe cuando está compilado con
# PyInstaller (sys.frozen), o la del propio script cuando corres con
# "python api_circulo.py". Así el .exe siempre busca el .env justo al lado
# de sí mismo, sin importar desde dónde lo lances (doble clic, acceso
# directo, cmd en otra carpeta, etc.) — nunca según el directorio de trabajo.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    print(
        "Aviso: no está instalado python-dotenv, así que no se cargó ningún "
        "archivo .env automáticamente. Instálalo con:\n"
        "  pip install python-dotenv\n"
        "o define las variables de entorno manualmente antes de correr el script.\n"
    )

URLS = {
    "dev": "https://services.circulodecredito.com.mx/sandbox/v1/rcc-ficoscore-pld",
    "prod": "https://services.circulodecredito.com.mx/v1/rcc-ficoscore-pld",
}
SECURITY_TEST_URL = "https://services.circulodecredito.com.mx/v1/securitytest"


def _ruta_junto_al_exe(ruta: str) -> str:
    """Resuelve rutas relativas (input, output, etc.) contra BASE_DIR en vez
    del directorio de trabajo actual, para que el .exe funcione igual sin
    importar desde dónde se ejecute."""
    return ruta if os.path.isabs(ruta) else os.path.join(BASE_DIR, ruta)


CARPETA_INPUT = _ruta_junto_al_exe(os.environ.get("CDC_INPUT_DIR") or "input")
CARPETA_OUTPUT = _ruta_junto_al_exe(os.environ.get("CDC_OUTPUT_DIR") or "output")

# Persona de ejemplo del sandbox (apellidoPaterno "SESENTAYDOS" -> Full
# Report, Status 200). Se usa como fallback SOLO cuando input/ está vacía,
# para poder probar que el script sigue funcionando sin gastar una consulta
# real en producción.
PERSONA_EJEMPLO = {
    "apellidoPaterno": "SESENTAYDOS",
    "apellidoMaterno": "PRUEBA",
    "primerNombre": "JUAN",
    "fechaNacimiento": "1965-08-09",
    "RFC": "SEPJ650809JG1",
    "nacionalidad": "MX",
    "domicilio": {
        "direccion": "PASADISO ENCONTRADO 58",
        "coloniaPoblacion": "MONTEVIDEO",
        "delegacionMunicipio": "GUSTAVO A MADERO",
        "ciudad": "CIUDAD DE MÉXICO",
        "estado": "CDMX",
        "CP": "07730",
    },
}


# ---------------------------------------------------------------------------
# Entrada: JSON de la(s) persona(s) a consultar
# ---------------------------------------------------------------------------

def cargar_persona(ruta: str) -> dict:
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def listar_personas(carpeta_input: str):
    """
    Devuelve (lista_de_(nombre, persona_dict), usando_ejemplo).

    - Si carpeta_input no existe o no tiene ningún .json: [("ejemplo",
      PERSONA_EJEMPLO)], True.
    - Si tiene uno o varios .json: uno por archivo (nombre = nombre del
      archivo sin extensión), False.
    """
    archivos = []
    if os.path.isdir(carpeta_input):
        archivos = sorted(
            f for f in os.listdir(carpeta_input) if f.lower().endswith(".json")
        )

    if not archivos:
        return [("ejemplo", PERSONA_EJEMPLO)], True

    personas = []
    for nombre_archivo in archivos:
        ruta = os.path.join(carpeta_input, nombre_archivo)
        nombre = os.path.splitext(nombre_archivo)[0]
        personas.append((nombre, cargar_persona(ruta)))
    return personas, False


# ---------------------------------------------------------------------------
# Evidencia de request/response (para la solicitud de acceso productivo)
# ---------------------------------------------------------------------------

def guardar_evidencia(nombre: str, headers_enviados: dict, body_enviado: str,
                       resp: requests.Response, carpeta_output: str) -> None:
    carpeta = os.path.join(carpeta_output, "evidencias")
    os.makedirs(carpeta, exist_ok=True)

    headers_seguros = dict(headers_enviados)
    for campo_sensible in ("password", "x-api-key"):
        if campo_sensible in headers_seguros:
            valor = headers_seguros[campo_sensible]
            headers_seguros[campo_sensible] = valor[:2] + "…(oculto)"

    contenido = (
        f"=== REQUEST ===\n"
        f"URL: {resp.request.url if resp.request else ''}\n"
        f"Headers: {json.dumps(headers_seguros, indent=2, ensure_ascii=False)}\n"
        f"Body:\n{body_enviado}\n\n"
        f"=== RESPONSE ===\n"
        f"Status: {resp.status_code}\n"
        f"Headers: {json.dumps(dict(resp.headers), indent=2, ensure_ascii=False)}\n"
        f"Body:\n{resp.text}\n"
    )
    ruta = os.path.join(carpeta, f"{nombre}.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(contenido)
    print(f"Evidencia guardada en: {os.path.abspath(ruta)}")


def probar_security_test(carpeta_output: str) -> requests.Response:
    api_key = os.environ.get("CDC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta la variable de entorno CDC_API_KEY.")

    body_str = json.dumps({"attribute": "Hello World!"}, separators=(",", ":"))
    signature = firmar_request(body_str)
    headers = {
        "x-api-key": api_key,
        "x-signature": signature,
        "Content-Type": "application/json",
    }
    resp = requests.post(
        SECURITY_TEST_URL, headers=headers, data=body_str.encode("utf-8"), timeout=30
    )
    guardar_evidencia("securitytest", headers, body_str, resp, carpeta_output)
    return resp


# ---------------------------------------------------------------------------
# Firma ECDSA (solo se usa en producción)
# ---------------------------------------------------------------------------

def _private_key_from_env(var_name: str = "CDC_PRIVATE_KEY_D") -> SigningKey:
    hex_d = os.environ.get(var_name)
    if not hex_d:
        raise RuntimeError(f"Falta la variable de entorno {var_name}.")
    hex_d = hex_d.strip().replace(":", "").replace("\n", "").replace(" ", "")
    return SigningKey.from_string(bytes.fromhex(hex_d), curve=NIST384p)


def firmar_request(body_str: str, private_key_env: str = "CDC_PRIVATE_KEY_D") -> str:
    """Firma el string EXACTO del body con SHA256withECDSA/secp384r1 (hex DER)."""
    sk = _private_key_from_env(private_key_env)
    signature_der = sk.sign(
        body_str.encode("utf-8"), hashfunc=hashlib.sha256, sigencode=sigencode_der
    )
    return signature_der.hex()


def verificar_firma_respuesta(body_str: str, signature_hex: str, public_key_xy_hex: str) -> bool:
    """Verifica el x-signature que regresa Círculo de Crédito en la respuesta."""
    vk = VerifyingKey.from_string(bytes.fromhex(public_key_xy_hex), curve=NIST384p)
    try:
        return vk.verify(
            bytes.fromhex(signature_hex),
            body_str.encode("utf-8"),
            hashfunc=hashlib.sha256,
            sigdecode=sigdecode_der,
        )
    except BadSignatureError:
        return False


# ---------------------------------------------------------------------------
# Llamada al API (dev o prod)
# ---------------------------------------------------------------------------

def consultar_reporte_credito(persona: dict, env: str, carpeta_output: str) -> requests.Response:
    """
    - dev:  solo requiere x-api-key.
    - prod: requiere x-api-key, x-signature (firmado con tu llave privada),
            username y password.
    """
    if env not in URLS:
        raise ValueError("env debe ser 'dev' o 'prod'")

    api_key = os.environ.get("CDC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta la variable de entorno CDC_API_KEY.")

    # Mismo string para firmar y enviar, así nunca hay mismatch.
    body_str = json.dumps(persona, ensure_ascii=False, separators=(",", ":"))

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }

    if env == "prod":
        username = os.environ.get("CDC_USERNAME")
        password = os.environ.get("CDC_PASSWORD")
        faltantes = [
            n for n, v in [("CDC_USERNAME", username), ("CDC_PASSWORD", password)] if not v
        ]
        if faltantes:
            raise RuntimeError(f"Faltan variables de entorno para prod: {', '.join(faltantes)}")

        headers["x-signature"] = firmar_request(body_str)
        headers["username"] = username
        headers["password"] = password

    resp = requests.post(
        URLS[env], headers=headers, data=body_str.encode("utf-8"), timeout=30
    )
    guardar_evidencia(f"reporte_credito_{env}", headers, body_str, resp, carpeta_output)

    if env == "prod":
        public_key_xy = os.environ.get("CDC_PUBLIC_KEY_XY")
        signature_resp = resp.headers.get("x-signature")
        if public_key_xy and signature_resp:
            valida = verificar_firma_respuesta(resp.text, signature_resp, public_key_xy)
            print(f"Firma de la respuesta: {'VÁLIDA' if valida else 'INVÁLIDA (revisa CDC_PUBLIC_KEY_XY)'}")

    return resp


# ---------------------------------------------------------------------------
# Exportación a XML (formato "Respuesta.xsd" del reporte de crédito)
#
# El API regresa JSON, pero el formato con el que se trabaja el reporte de
# crédito es el XML <Respuesta><Personas><Persona>...  Estas funciones
# convierten la respuesta JSON a ese XML sin perder información: los campos
# conocidos salen en el orden del esquema y cualquier campo extra que mande
# Círculo de Crédito se agrega al final de su bloque.
# ---------------------------------------------------------------------------

XML_ORDEN = {
    "Encabezado": [
        "FolioConsultaOtorgante", "ClaveOtorgante", "ExpedienteEncontrado", "FolioConsulta",
    ],
    "Nombre": [
        "ApellidoPaterno", "ApellidoMaterno", "ApellidoAdicional", "Nombres",
        "FechaNacimiento", "RFC", "CURP", "Nacionalidad", "Residencia",
        "EstadoCivil", "Sexo", "ClaveElectorIFE", "NumeroDependientes", "FechaDefuncion",
    ],
    "Domicilio": [
        "Direccion", "ColoniaPoblacion", "DelegacionMunicipio", "Ciudad", "Estado",
        "CP", "FechaResidencia", "NumeroTelefono", "TipoDomicilio",
        "TipoAsentamiento", "FechaRegistroDomicilio",
    ],
    "Empleo": [
        "NombreEmpresa", "Direccion", "ColoniaPoblacion", "DelegacionMunicipio",
        "Ciudad", "Estado", "CP", "NumeroTelefono", "Extension", "Fax", "Puesto",
        "FechaContratacion", "ClaveMoneda", "SalarioMensual", "FechaUltimoDiaEmpleo",
        "FechaVerificacionEmpleo", "OrigenRazonSocial",
    ],
    "Mensaje": ["TipoMensaje", "Leyenda"],
    "Cuenta": [
        "FechaActualizacion", "RegistroImpugnado", "ClaveOtorgante", "NombreOtorgante",
        "CuentaActual", "TipoResponsabilidad", "TipoCuenta", "TipoCredito",
        "ClaveUnidadMonetaria", "ValorActivoValuacion", "NumeroPagos", "FrecuenciaPagos",
        "MontoPagar", "FechaAperturaCuenta", "FechaUltimoPago", "FechaUltimaCompra",
        "FechaCierreCuenta", "FechaReporte", "UltimaFechaSaldoCero", "Garantia",
        "CreditoMaximo", "SaldoActual", "LimiteCredito", "SaldoVencido",
        "NumeroPagosVencidos", "PagoActual", "HistoricoPagos",
        "FechaRecienteHistoricoPagos", "FechaAntiguaHistoricoPagos", "ClavePrevencion",
        "TotalPagosReportados", "PeorAtraso", "FechaPeorAtraso", "SaldoVencidoPeorAtraso",
    ],
    "ConsultaEfectuada": [
        "FechaConsulta", "ClaveOtorgante", "NombreOtorgante", "TipoCredito",
        "ClaveUnidadMonetaria", "ImporteCredito", "TipoResponsabilidad",
    ],
    "Score": ["NombreScore", "Valor"],
}

XML_CLAVES_JSON = {
    "RFC": "RFC",
    "CURP": "CURP",
    "CP": "CP",
    "CAN": "CAN",
}


def _clave_json(tag: str) -> str:
    return XML_CLAVES_JSON.get(tag, tag[0].lower() + tag[1:])


def _tag_xml(clave: str) -> str:
    if clave.isupper():
        return clave
    return clave[0].upper() + clave[1:]


def _texto_xml(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "1" if valor else "0"
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return _escape_xml(str(valor))


XML_SINGULARES = {
    "Domicilios": "Domicilio",
    "Empleos": "Empleo",
    "Mensajes": "Mensaje",
    "Cuentas": "Cuenta",
    "ConsultasEfectuadas": "ConsultaEfectuada",
    "Scores": "Score",
    "Razones": "Razon",
    "DeclaracionesConsumidor": "DeclaracionConsumidor",
}


def _singular(tag: str) -> str:
    if tag in XML_SINGULARES:
        return XML_SINGULARES[tag]
    if tag.endswith("s") and len(tag) > 2:
        return tag[:-1]
    return tag + "Item"


def _emitir(tag: str, valor, nivel: int, lineas: list) -> None:
    sangria = "  " * nivel
    if isinstance(valor, dict):
        _emitir_bloque(tag, valor, XML_ORDEN.get(tag, []), nivel, lineas)
    elif isinstance(valor, list):
        if not valor:
            lineas.append(f"{sangria}<{tag}></{tag}>")
            return
        lineas.append(f"{sangria}<{tag}>")
        hijo = _singular(tag)
        for item in valor:
            if isinstance(item, dict):
                _emitir_bloque(hijo, item, XML_ORDEN.get(hijo, []), nivel + 1, lineas)
            else:
                _emitir(hijo, item, nivel + 1, lineas)
        lineas.append(f"{sangria}</{tag}>")
    else:
        lineas.append(f"{sangria}<{tag}>{_texto_xml(valor)}</{tag}>")


def _emitir_bloque(tag: str, datos: dict, orden: list, nivel: int, lineas: list) -> None:
    datos = datos or {}
    sangria = "  " * nivel
    lineas.append(f"{sangria}<{tag}>")
    usadas = set()
    for etiqueta in orden:
        clave = _clave_json(etiqueta)
        usadas.add(clave)
        _emitir(etiqueta, datos.get(clave, ""), nivel + 1, lineas)
    for clave, valor in datos.items():           # campos extra que mande el API
        if clave not in usadas:
            _emitir(_tag_xml(clave), valor, nivel + 1, lineas)
    lineas.append(f"{sangria}</{tag}>")


def construir_xml(data: dict, indentado: bool = True) -> str:
    """Convierte la respuesta JSON del API al XML <Respuesta> del buró."""
    persona = dict(data.get("persona") or {})

    nombres = persona.pop("nombres", None)
    primero = persona.pop("primerNombre", "")
    segundo = persona.pop("segundoNombre", "")
    if not nombres:
        nombres = " ".join(x for x in (primero, segundo) if x).strip()
    persona["nombres"] = nombres

    encabezado = {
        "folioConsultaOtorgante": data.get("folioConsultaOtorgante", ""),
        "claveOtorgante": data.get("claveOtorgante", ""),
        "expedienteEncontrado": data.get("expedienteEncontrado", "1" if data.get("creditos") else "0"),
        "folioConsulta": data.get("folioConsulta", ""),
    }

    lineas = []
    _emitir_bloque("Encabezado", encabezado, XML_ORDEN["Encabezado"], 3, lineas)
    _emitir_bloque("Nombre", persona, XML_ORDEN["Nombre"], 3, lineas)
    _emitir("Domicilios", data.get("domicilios") or [], 3, lineas)
    _emitir("Empleos", data.get("empleos") or [], 3, lineas)
    _emitir("Mensajes", data.get("mensajes") or [], 3, lineas)

    lineas.append("      <Cuentas>")
    for credito in data.get("creditos") or []:
        _emitir_bloque("Cuenta", credito, XML_ORDEN["Cuenta"], 4, lineas)
    lineas.append("      </Cuentas>")

    lineas.append("      <ConsultasEfectuadas>")
    for consulta in data.get("consultas") or []:
        _emitir_bloque("ConsultaEfectuada", consulta, XML_ORDEN["ConsultaEfectuada"], 4, lineas)
    lineas.append("      </ConsultasEfectuadas>")

    if data.get("scores"):
        _emitir("Scores", data["scores"], 3, lineas)

    declaraciones = data.get("declaracionesConsumidor") or ""
    _emitir("DeclaracionesConsumidor", declaraciones, 3, lineas)

    cuerpo = [
        '<Respuesta xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="/Respuesta.xsd">',
        "  <Personas>",
        "    <Persona>",
        *lineas,
        "    </Persona>",
        "  </Personas>",
        "</Respuesta>",
    ]

    if indentado:
        texto = "\n".join(cuerpo)
    else:
        texto = "".join(linea.strip() for linea in cuerpo)

    return '<?xml version="1.0" encoding="ISO-8859-1"?>' + ("\n" if indentado else "") + texto


def ruta_libre(ruta: str) -> str:
    """Si el archivo está abierto en otro programa (Excel, un lector de XML,
    etc.), Windows lo bloquea y truena con PermissionError. En ese caso
    devuelve una ruta alterna con la hora en el nombre en vez de perder la
    consulta ya pagada."""
    try:
        with open(ruta, "a", encoding="utf-8"):
            pass
        return ruta
    except PermissionError:
        base, ext = os.path.splitext(ruta)
        alterna = f"{base}_{datetime.now():%H%M%S}{ext}"
        print(f"  ! {os.path.basename(ruta)} está abierto en otro programa; "
              f"guardando como {os.path.basename(alterna)}")
        return alterna
    except OSError:
        return ruta


def exportar_a_xml(data: dict, ruta_salida: str, indentado: bool = True,
                    encoding: str = "ISO-8859-1") -> str:
    xml_texto = construir_xml(data, indentado=indentado)
    ruta_salida = ruta_libre(ruta_salida)
    with open(ruta_salida, "w", encoding=encoding, errors="xmlcharrefreplace", newline="\n") as f:
        f.write(xml_texto)
        f.write("\n" if indentado else "")
    ruta = os.path.abspath(ruta_salida)
    print(f"XML generado: {ruta}")
    return ruta


def guardar_json(data: dict, ruta_salida: str) -> str:
    ruta_salida = ruta_libre(ruta_salida)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    ruta = os.path.abspath(ruta_salida)
    print(f"JSON guardado: {ruta}")
    return ruta


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _debe_pausar_al_terminar() -> bool:
    """
    CDC_PAUSAR_AL_TERMINAR en .env controla si la consola espera un ENTER
    antes de cerrarse (para poder leer el resultado cuando corres el .exe
    con doble clic, en vez de que la ventana se cierre sola).

    - "1"/"true" -> siempre pausa.
    - "0"/"false" -> nunca pausa.
    - sin definir -> pausa solo si es el .exe compilado (sys.frozen); si
      corres "python api_circulo.py" desde una terminal, esa terminal ya
      se queda abierta sola, así que no hace falta.
    """
    valor = os.environ.get("CDC_PAUSAR_AL_TERMINAR")
    if valor is not None and valor.strip() != "":
        return valor.strip().lower() not in ("0", "false", "no")
    return getattr(sys, "frozen", False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Consulta al API de Círculo de Crédito.")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        help="Fuerza el ambiente (dev o prod). Si no se pasa, se detecta solo: "
             "sin .json en input/ -> dev con persona de ejemplo; con .json -> prod.",
    )
    parser.add_argument(
        "--endpoint",
        choices=["reporte", "securitytest"],
        default="reporte",
        help="'reporte' consulta rcc-ficoscore-pld (default); 'securitytest' prueba tu firma ECDSA",
    )
    parser.add_argument(
        "--input",
        default=None,
        help=(
            "Ruta a UN JSON puntual a consultar (opcional). Si no se pasa, "
            f"el script revisa todos los .json dentro de {CARPETA_INPUT}/ "
            "y, si no hay ninguno, usa la persona de ejemplo en DEV."
        ),
    )
    parser.add_argument(
        "--output",
        default=CARPETA_OUTPUT,
        help=f"Carpeta donde se guardan el JSON, el XML y las evidencias (default: {CARPETA_OUTPUT})",
    )
    parser.add_argument(
        "--xml-compacto",
        action="store_true",
        help="Además del XML indentado, genera el XML en una sola línea, como lo entrega el buró",
    )
    parser.add_argument(
        "--sin-xml", action="store_true", help="No generar el XML de la respuesta"
    )
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    if args.endpoint == "securitytest":
        try:
            resp = probar_security_test(args.output)
        except RuntimeError as e:
            print(f"Error de configuración: {e}")
            sys.exit(1)
        print(f"Status: {resp.status_code}")
        print(resp.text)
        return

    # Si pasas --input, es un archivo puntual (se trata como "hay JSON real"
    # -> prod, salvo que fuerces --env). Si no, se revisa la carpeta input/.
    if args.input:
        try:
            personas = [(os.path.splitext(os.path.basename(args.input))[0], cargar_persona(args.input))]
        except (RuntimeError, OSError, json.JSONDecodeError) as e:
            print(f"Error: no pude leer {args.input}: {e}")
            sys.exit(1)
        usando_ejemplo = False
    else:
        personas, usando_ejemplo = listar_personas(CARPETA_INPUT)

    env = args.env or ("dev" if usando_ejemplo else "prod")

    if usando_ejemplo:
        print(f"No hay archivos .json en {CARPETA_INPUT}/; uso la persona de ejemplo del sandbox.\n")
    else:
        print(f"Encontré {len(personas)} archivo(s) en {'la ruta indicada' if args.input else CARPETA_INPUT + '/'}.\n")

    print(f">> Usando ambiente: {env.upper()} ({URLS[env]})\n")

    hubo_error = False
    for nombre, persona in personas:
        print(f"--- Consultando: {nombre} ---")
        try:
            resp = consultar_reporte_credito(persona, env, args.output)
        except RuntimeError as e:
            print(f"Error de configuración: {e}")
            sys.exit(1)
        except requests.RequestException as e:
            print(f"Error de red consultando a {nombre}: {e}")
            hubo_error = True
            continue

        print(f"Status: {resp.status_code}")

        try:
            data = resp.json()
        except ValueError:
            print(resp.text)
            hubo_error = True
            continue

        print(json.dumps(data, indent=2, ensure_ascii=False))

        # El folio + el nombre del archivo de origen identifican cada
        # corrida, así no se pisan los archivos entre distintas personas.
        folio = data.get("folioConsulta") or datetime.now().strftime("%Y%m%d_%H%M%S")
        base_nombre = f"reporte_credito_{env}_{nombre}_{folio}"

        guardar_json(data, os.path.join(args.output, f"{base_nombre}.json"))
        if not args.sin_xml:
            exportar_a_xml(data, os.path.join(args.output, f"{base_nombre}.xml"))
            if args.xml_compacto:
                exportar_a_xml(
                    data, os.path.join(args.output, f"{base_nombre}_plano.xml"), indentado=False
                )
        print()

    print(f"Todo quedó en: {os.path.abspath(args.output)}")
    if hubo_error:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    finally:
        # Corre SIEMPRE, incluso si main() truena con un error no manejado
        # o llama sys.exit(), para que la ventana no se cierre antes de que
        # alcances a leer qué pasó.
        if _debe_pausar_al_terminar():
            try:
                input("\nPresiona ENTER para cerrar...")
            except EOFError:
                pass
