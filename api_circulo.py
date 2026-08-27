"""
Cliente para el API "Reporte de Crédito Consolidado + FICO® Score y PLD
Check® - Personas Físicas" de Círculo de Crédito.

Se controla por flags de línea de comandos estilo /CLAVE_WS="valor" (igual
que BURO_DE_CREDITO.exe), para poder llamarlo desde un .bat exactamente como
ya se hace con otras integraciones. NO usa .env ni escanea ninguna carpeta
de entrada solo: cada flag tiene un default en este archivo, y se sobreescribe
solo si lo pasas al ejecutar.

--------------------------------------------------------------------------
FLAGS DISPONIBLES (todos opcionales; sin ellos, se usan los defaults de
DEFAULTS_FLAGS más abajo):

  Conexión / credenciales:
    /AMBIENTE_WS="dev|prod"      Ambiente a consultar. Default: dev.
    /API_KEY_WS="..."            Tu x-api-key. Requerido en dev y prod.
    /USUARIO_WS="..."            Usuario Círculo de Crédito. Requerido en prod.
    /PASS_WS="..."               Contraseña. Requerido en prod.
    /LLAVE_PRIVADA_WS="..."      Valor 'priv' de tu llave ECDSA en hex.
                                  Requerido en prod (firma el request).
    /LLAVE_PUBLICA_WS="..."      Llave pública de Círculo de Crédito, en hex
                                  (opcional; si la pasas, se valida la firma
                                  x-signature que ellos regresan en prod).

  Persona a consultar (si no pasas INPUT_WS, arma la persona con estos):
    /Nombre_primerNombre_WS="..."
    /Nombre_segundoNombre_WS="..."
    /Nombre_apellidoPaterno_WS="..."
    /Nombre_apellidoMaterno_WS="..."
    /Nombre_RFC_WS="..."
    /Nombre_fechaNacimiento_WS="AAAA-MM-DD"
    /Nombre_nacionalidad_WS="MX"          Default: MX.
    /Domicilio_direccion1_WS="..."
    /Domicilio_colonia_WS="..."
    /Domicilio_municipio_WS="..."
    /Domicilio_ciudad_WS="..."
    /Domicilio_estado_WS="..."
    /Domicilio_CP_WS="..."

  Entrada por archivo (alternativa a los flags de arriba):
    /INPUT_WS="persona.json"     Un solo JSON con la persona.
    /INPUT_WS="input\\*.json"     Con "*", procesa TODOS los que hagan match,
                                  uno por uno, cada quien con su propio
                                  reporte de salida.
                                  Si no pasas ni INPUT_WS ni ningún flag de
                                  persona, se usa una persona de ejemplo del
                                  sandbox (y se fuerza AMBIENTE_WS=dev, para
                                  no gastar una consulta real sin querer).

  Salida:
    /OUTPUT_WS="output"          Carpeta donde se guardan JSON/XML/PDF/evidencias.
    /ArchivoSalida_WS="ALL"      Qué generar: JSON | XML | PDF | ALL (default).
                                  ALL genera los tres. El PDF siempre se arma
                                  a partir del XML (si no pides XML como
                                  salida, se usa uno temporal que se borra
                                  al terminar).
    /XML_COMPACTO_WS="NO"        SI genera además el XML en una sola línea.
    /PDF_MASCARA_WS="NO"         SI genera el PDF con identidad ficticia
                                  legible (para demos), en vez de los datos
                                  reales de la persona. Los datos financieros
                                  (cuentas, montos, otorgantes) nunca se
                                  enmascaran.

  Otros:
    /ENDPOINT_WS="reporte"       reporte (default) | securitytest.
    /PAUSAR_WS=""                SI/NO. Sin definir: pausa solo si es el .exe
                                  compilado, para que no se cierre la
                                  consola antes de leer el resultado.

Todas las rutas relativas (INPUT_WS, OUTPUT_WS) se resuelven contra la
carpeta del .exe/script, nunca contra el directorio de trabajo actual.

Ejemplo (ver también ApiCirculo.bat.template):
    ApiCirculo.exe /AMBIENTE_WS="prod" /API_KEY_WS="..." /USUARIO_WS="..." ^
        /PASS_WS="..." /LLAVE_PRIVADA_WS="..." /INPUT_WS="input\\*.json"

--------------------------------------------------------------------------
Instalación (una sola vez, para correr como script de Python):
    python -m venv venv
    venv\\Scripts\\pip install -r requirements.txt
"""

import glob
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from xml.sax.saxutils import escape as _escape_xml

import requests
from ecdsa import SigningKey, VerifyingKey, NIST384p, BadSignatureError
from ecdsa.util import sigencode_der, sigdecode_der

import xml_a_pdf

# Carpeta donde vive el .exe cuando está compilado con PyInstaller
# (sys.frozen), o la del propio script cuando corres "python api_circulo.py".
# Así siempre resuelve rutas relativas (INPUT_WS, OUTPUT_WS) contra su propia
# ubicación, sin importar desde dónde lo lances (doble clic, acceso directo,
# cmd en otra carpeta) — nunca según el directorio de trabajo actual.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

URLS = {
    "dev": "https://services.circulodecredito.com.mx/sandbox/v1/rcc-ficoscore-pld",
    "prod": "https://services.circulodecredito.com.mx/v1/rcc-ficoscore-pld",
}
SECURITY_TEST_URL = "https://services.circulodecredito.com.mx/v1/securitytest"


def _ruta_junto_al_exe(ruta: str) -> str:
    """Resuelve rutas relativas contra BASE_DIR en vez del directorio de
    trabajo actual, para que el .exe funcione igual sin importar desde
    dónde se ejecute."""
    return ruta if os.path.isabs(ruta) else os.path.join(BASE_DIR, ruta)


# Persona de ejemplo del sandbox (apellidoPaterno "SESENTAYDOS" -> Full
# Report, Status 200). Se usa SOLO cuando no se pasa ni INPUT_WS ni ningún
# flag de persona, para poder probar que el .exe sigue funcionando sin
# arriesgar una consulta real.
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

# Defaults de cada flag. Deliberadamente en blanco para credenciales: este
# archivo se sube a GitHub, así que nunca debe llevar API keys/usuarios/
# contraseñas reales. Los valores reales van en tu copia local del .bat
# (dist\ApiCirculo.bat), que está excluida del repo por .gitignore.
DEFAULTS_FLAGS = {
    "AMBIENTE_WS": "dev",
    "API_KEY_WS": "",
    "USUARIO_WS": "",
    "PASS_WS": "",
    "LLAVE_PRIVADA_WS": "",
    "LLAVE_PUBLICA_WS": "",
    "NOMBRE_PRIMERNOMBRE_WS": "",
    "NOMBRE_SEGUNDONOMBRE_WS": "",
    "NOMBRE_APELLIDOPATERNO_WS": "",
    "NOMBRE_APELLIDOMATERNO_WS": "",
    "NOMBRE_RFC_WS": "",
    "NOMBRE_FECHANACIMIENTO_WS": "",
    "NOMBRE_NACIONALIDAD_WS": "MX",
    "DOMICILIO_DIRECCION1_WS": "",
    "DOMICILIO_COLONIA_WS": "",
    "DOMICILIO_MUNICIPIO_WS": "",
    "DOMICILIO_CIUDAD_WS": "",
    "DOMICILIO_ESTADO_WS": "",
    "DOMICILIO_CP_WS": "",
    "INPUT_WS": "",
    "OUTPUT_WS": "output",
    "ARCHIVOSALIDA_WS": "ALL",
    "XML_COMPACTO_WS": "NO",
    "PDF_MASCARA_WS": "NO",
    "ENDPOINT_WS": "reporte",
    "PAUSAR_WS": "",
}

# Flags que identifican que SÍ se quiere armar una persona a mano (no cuenta
# NOMBRE_NACIONALIDAD_WS porque siempre trae un default no vacío).
_FLAGS_DE_PERSONA = [
    "NOMBRE_PRIMERNOMBRE_WS", "NOMBRE_SEGUNDONOMBRE_WS", "NOMBRE_APELLIDOPATERNO_WS",
    "NOMBRE_APELLIDOMATERNO_WS", "NOMBRE_RFC_WS", "NOMBRE_FECHANACIMIENTO_WS",
    "DOMICILIO_DIRECCION1_WS", "DOMICILIO_COLONIA_WS", "DOMICILIO_MUNICIPIO_WS",
    "DOMICILIO_CIUDAD_WS", "DOMICILIO_ESTADO_WS", "DOMICILIO_CP_WS",
]


# ---------------------------------------------------------------------------
# Parser de flags estilo /CLAVE_WS="valor" (como BURO_DE_CREDITO.exe)
# ---------------------------------------------------------------------------

def _parsear_flags_estilo_ws(argv: list) -> dict:
    """
    Convierte ["/AMBIENTE_WS=prod", '/USUARIO_WS="mi usuario"', ...] en
    {"AMBIENTE_WS": "prod", "USUARIO_WS": "mi usuario", ...}.
    Ignora cualquier token que no empiece con "/" o no tenga "=".
    Las claves se guardan en MAYÚSCULAS (case-insensitive al escribirlas).
    """
    flags = {}
    for token in argv:
        if not token.startswith("/") or "=" not in token:
            continue
        clave, _, valor = token[1:].partition("=")
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] == '"':
            valor = valor[1:-1]
        flags[clave.strip().upper()] = valor
    return flags


def _obtener(flags: dict, clave: str) -> str:
    return flags.get(clave, DEFAULTS_FLAGS[clave])


# ---------------------------------------------------------------------------
# Entrada: JSON de la(s) persona(s) a consultar
# ---------------------------------------------------------------------------

def cargar_persona(ruta: str) -> dict:
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _hay_datos_de_persona_en_flags(flags: dict) -> bool:
    return any(flags.get(clave) for clave in _FLAGS_DE_PERSONA)


def _persona_desde_flags(flags: dict) -> dict:
    persona = {
        "primerNombre": _obtener(flags, "NOMBRE_PRIMERNOMBRE_WS"),
        "segundoNombre": _obtener(flags, "NOMBRE_SEGUNDONOMBRE_WS"),
        "apellidoPaterno": _obtener(flags, "NOMBRE_APELLIDOPATERNO_WS"),
        "apellidoMaterno": _obtener(flags, "NOMBRE_APELLIDOMATERNO_WS"),
        "RFC": _obtener(flags, "NOMBRE_RFC_WS"),
        "fechaNacimiento": _obtener(flags, "NOMBRE_FECHANACIMIENTO_WS"),
        "nacionalidad": _obtener(flags, "NOMBRE_NACIONALIDAD_WS"),
        "domicilio": {
            "direccion": _obtener(flags, "DOMICILIO_DIRECCION1_WS"),
            "coloniaPoblacion": _obtener(flags, "DOMICILIO_COLONIA_WS"),
            "delegacionMunicipio": _obtener(flags, "DOMICILIO_MUNICIPIO_WS"),
            "ciudad": _obtener(flags, "DOMICILIO_CIUDAD_WS"),
            "estado": _obtener(flags, "DOMICILIO_ESTADO_WS"),
            "CP": _obtener(flags, "DOMICILIO_CP_WS"),
        },
    }
    # No mandar al API campos vacíos que no se llenaron.
    persona = {k: v for k, v in persona.items() if v not in ("", None)}
    domicilio = {k: v for k, v in persona.get("domicilio", {}).items() if v not in ("", None)}
    if domicilio:
        persona["domicilio"] = domicilio
    else:
        persona.pop("domicilio", None)
    return persona


def _resolver_personas(flags: dict):
    """
    Devuelve (lista_de_(nombre, persona_dict), usando_ejemplo).

    - INPUT_WS con "*" -> uno por cada archivo que haga match.
    - INPUT_WS sin "*"  -> ese único archivo.
    - Sin INPUT_WS pero con flags Nombre_*/Domicilio_* -> una persona armada
      con esos flags.
    - Sin nada de lo anterior -> persona de ejemplo del sandbox.
    """
    input_ws = _obtener(flags, "INPUT_WS").strip()
    if input_ws:
        patron = _ruta_junto_al_exe(input_ws)
        es_patron = any(c in input_ws for c in "*?[")
        rutas = sorted(glob.glob(patron)) if es_patron else [patron]
        if not rutas:
            raise RuntimeError(f'No encontré ningún archivo con INPUT_WS="{input_ws}".')

        personas = []
        for ruta in rutas:
            nombre = os.path.splitext(os.path.basename(ruta))[0]
            try:
                personas.append((nombre, cargar_persona(ruta)))
            except (OSError, json.JSONDecodeError) as e:
                print(f"  ! No pude leer {ruta}: {e}")
        if not personas:
            raise RuntimeError("Ningún archivo de INPUT_WS se pudo leer correctamente.")
        return personas, False

    if _hay_datos_de_persona_en_flags(flags):
        return [("persona", _persona_desde_flags(flags))], False

    return [("ejemplo", PERSONA_EJEMPLO)], True


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


def probar_security_test(carpeta_output: str, api_key: str, private_key_hex: str) -> requests.Response:
    if not api_key:
        raise RuntimeError("Falta API_KEY_WS.")
    if not private_key_hex:
        raise RuntimeError("Falta LLAVE_PRIVADA_WS.")

    body_str = json.dumps({"attribute": "Hello World!"}, separators=(",", ":"))
    signature = firmar_request(body_str, private_key_hex)
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

def _signing_key_from_hex(hex_d: str) -> SigningKey:
    if not hex_d:
        raise RuntimeError("Falta LLAVE_PRIVADA_WS.")
    hex_d = hex_d.strip().replace(":", "").replace("\n", "").replace(" ", "")
    return SigningKey.from_string(bytes.fromhex(hex_d), curve=NIST384p)


def firmar_request(body_str: str, private_key_hex: str) -> str:
    """Firma el string EXACTO del body con SHA256withECDSA/secp384r1 (hex DER)."""
    sk = _signing_key_from_hex(private_key_hex)
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

def consultar_reporte_credito(persona: dict, env: str, carpeta_output: str, *,
                               api_key: str, username: str = "", password: str = "",
                               private_key_hex: str = "", public_key_hex: str = "") -> requests.Response:
    """
    - dev:  solo requiere x-api-key.
    - prod: requiere x-api-key, x-signature (firmado con tu llave privada),
            username y password.
    """
    if env not in URLS:
        raise ValueError("env debe ser 'dev' o 'prod'")
    if not api_key:
        raise RuntimeError("Falta API_KEY_WS.")

    # Mismo string para firmar y enviar, así nunca hay mismatch.
    body_str = json.dumps(persona, ensure_ascii=False, separators=(",", ":"))

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }

    if env == "prod":
        faltantes = [
            n for n, v in [
                ("USUARIO_WS", username), ("PASS_WS", password),
                ("LLAVE_PRIVADA_WS", private_key_hex),
            ] if not v
        ]
        if faltantes:
            raise RuntimeError(f"Faltan flags para prod: {', '.join(faltantes)}")

        headers["x-signature"] = firmar_request(body_str, private_key_hex)
        headers["username"] = username
        headers["password"] = password

    resp = requests.post(
        URLS[env], headers=headers, data=body_str.encode("utf-8"), timeout=30
    )
    guardar_evidencia(f"reporte_credito_{env}", headers, body_str, resp, carpeta_output)

    if env == "prod" and public_key_hex:
        signature_resp = resp.headers.get("x-signature")
        if signature_resp:
            valida = verificar_firma_respuesta(resp.text, signature_resp, public_key_hex)
            print(f"Firma de la respuesta: {'VÁLIDA' if valida else 'INVÁLIDA (revisa LLAVE_PUBLICA_WS)'}")

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
# XML -> PDF (integra xml_a_pdf.py / parser_xml.py / reporte_estructura.py,
# adaptados de Xml2Pdf-Circulo)
# ---------------------------------------------------------------------------

def generar_pdf(data: dict, ruta_pdf: str, mascara: bool = False,
                 ruta_xml_existente: str = None) -> str:
    """
    Genera el PDF del reporte a partir de la respuesta JSON del API.

    Si ya escribiste el XML a disco (porque también pediste XML como
    salida), pásalo en `ruta_xml_existente` para no rehacer trabajo. Si no,
    se arma un XML temporal solo para alimentar al generador de PDF, y se
    borra al terminar.
    """
    ruta_pdf = ruta_libre(ruta_pdf)

    if ruta_xml_existente:
        xml_a_pdf.construir(ruta_xml_existente, ruta_pdf, mascara=mascara)
        ruta = os.path.abspath(ruta_pdf)
        print(f"PDF generado: {ruta}")
        return ruta

    xml_texto = construir_xml(data, indentado=True)
    fd, ruta_tmp = tempfile.mkstemp(suffix=".xml", prefix="cdc_tmp_")
    os.close(fd)
    try:
        with open(ruta_tmp, "w", encoding="ISO-8859-1", errors="xmlcharrefreplace") as f:
            f.write(xml_texto)
        xml_a_pdf.construir(ruta_tmp, ruta_pdf, mascara=mascara)
    finally:
        try:
            os.remove(ruta_tmp)
        except OSError:
            pass
    ruta = os.path.abspath(ruta_pdf)
    print(f"PDF generado: {ruta}")
    return ruta


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _debe_pausar_al_terminar(flags: dict) -> bool:
    """
    PAUSAR_WS controla si la consola espera un ENTER antes de cerrarse (para
    poder leer el resultado cuando corres el .exe con doble clic).

    - "SI"/"1" -> siempre pausa. "NO"/"0" -> nunca pausa.
    - sin definir -> pausa solo si es el .exe compilado (sys.frozen); si
      corres "python api_circulo.py" desde una terminal, esa terminal ya
      se queda abierta sola.
    """
    valor = flags.get("PAUSAR_WS", "").strip().upper()
    if valor in ("SI", "S", "1", "TRUE"):
        return True
    if valor in ("NO", "N", "0", "FALSE"):
        return False
    return getattr(sys, "frozen", False)


def main(flags: dict) -> None:
    output_dir = _ruta_junto_al_exe(_obtener(flags, "OUTPUT_WS"))
    os.makedirs(output_dir, exist_ok=True)

    api_key = _obtener(flags, "API_KEY_WS")
    username = _obtener(flags, "USUARIO_WS")
    password = _obtener(flags, "PASS_WS")
    private_key_hex = _obtener(flags, "LLAVE_PRIVADA_WS")
    public_key_hex = _obtener(flags, "LLAVE_PUBLICA_WS")

    endpoint = _obtener(flags, "ENDPOINT_WS").strip().lower()
    if endpoint == "securitytest":
        try:
            resp = probar_security_test(output_dir, api_key, private_key_hex)
        except RuntimeError as e:
            print(f"Error de configuración: {e}")
            sys.exit(1)
        print(f"Status: {resp.status_code}")
        print(resp.text)
        return

    try:
        personas, usando_ejemplo = _resolver_personas(flags)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    ambiente = _obtener(flags, "AMBIENTE_WS").strip().lower()
    if ambiente not in URLS:
        print(f"Error: AMBIENTE_WS debe ser 'dev' o 'prod' (llegó {ambiente!r}).")
        sys.exit(1)

    if usando_ejemplo:
        ambiente = "dev"
        print("No se pasó INPUT_WS ni datos de persona (Nombre_*/Domicilio_*); "
              "uso la persona de ejemplo del sandbox en DEV.\n")
    else:
        print(f"Voy a consultar {len(personas)} persona(s).\n")

    print(f">> Usando ambiente: {ambiente.upper()} ({URLS[ambiente]})\n")

    formato_salida = _obtener(flags, "ARCHIVOSALIDA_WS").strip().upper()
    if formato_salida not in ("XML", "JSON", "PDF", "ALL"):
        print(f"Error: ArchivoSalida_WS debe ser JSON, XML, PDF o ALL (llegó {formato_salida!r}).")
        sys.exit(1)
    generar_json = formato_salida in ("JSON", "ALL")
    generar_xml = formato_salida in ("XML", "ALL")
    generar_pdf_flag = formato_salida in ("PDF", "ALL")
    xml_compacto = _obtener(flags, "XML_COMPACTO_WS").strip().upper() in ("SI", "S", "1", "TRUE")
    pdf_mascara = _obtener(flags, "PDF_MASCARA_WS").strip().upper() in ("SI", "S", "1", "TRUE")

    hubo_error = False
    for nombre, persona in personas:
        print(f"--- Consultando: {nombre} ---")
        try:
            resp = consultar_reporte_credito(
                persona, ambiente, output_dir,
                api_key=api_key, username=username, password=password,
                private_key_hex=private_key_hex, public_key_hex=public_key_hex,
            )
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

        # El folio + el nombre de origen identifican cada corrida, así no se
        # pisan los archivos entre distintas personas.
        folio = data.get("folioConsulta") or datetime.now().strftime("%Y%m%d_%H%M%S")
        base_nombre = f"reporte_credito_{ambiente}_{nombre}_{folio}"

        if generar_json:
            guardar_json(data, os.path.join(output_dir, f"{base_nombre}.json"))

        ruta_xml_generada = None
        if generar_xml:
            ruta_xml_generada = exportar_a_xml(data, os.path.join(output_dir, f"{base_nombre}.xml"))
            if xml_compacto:
                exportar_a_xml(
                    data, os.path.join(output_dir, f"{base_nombre}_plano.xml"), indentado=False
                )

        if generar_pdf_flag:
            try:
                generar_pdf(
                    data, os.path.join(output_dir, f"{base_nombre}.pdf"),
                    mascara=pdf_mascara, ruta_xml_existente=ruta_xml_generada,
                )
            except ValueError as e:
                print(f"  ! No se pudo generar el PDF de {nombre}: {e}")
                hubo_error = True
        print()

    print(f"Todo quedó en: {os.path.abspath(output_dir)}")
    if hubo_error:
        sys.exit(1)


if __name__ == "__main__":
    flags = _parsear_flags_estilo_ws(sys.argv[1:])
    try:
        main(flags)
    finally:
        # Corre SIEMPRE, incluso si main() truena con un error no manejado
        # o llama sys.exit(), para que la ventana no se cierre antes de que
        # alcances a leer qué pasó.
        if _debe_pausar_al_terminar(flags):
            try:
                input("\nPresiona ENTER para cerrar...")
            except EOFError:
                pass
