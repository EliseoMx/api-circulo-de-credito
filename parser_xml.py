"""
Parser: respuesta XML del buró  ->  estructuras de datos de la plantilla PDF.

Uso:
    from parser_xml import cargar
    datos = cargar("respuesta.xml", mascara=True)

`mascara=True` (por defecto) NO oculta los datos con XXXX: genera una
identidad ficticia legible (nombre, RFC, CURP, calle y teléfono) para poder
validar visualmente el layout sin exponer al titular real. Es determinista
por persona (misma semilla -> mismo alias en corridas repetidas del mismo
XML) pero cambia de un titular a otro. Los datos financieros (cuentas,
montos, historial de pago, otorgantes, consultas) NUNCA se tocan: son los
que dan complejidad real al layout y no son identificadores personales.

Apaga `mascara` sólo en el entorno donde estés autorizado a tratar el dato
completo en claro.
"""

import hashlib
import random
import xml.etree.ElementTree as ET
from datetime import datetime

# --------------------------------------------------------------- catálogos

MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
         "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]

TIPO_RESPONSABILIDAD = {
    "I": "INDIVIDUAL (TITULAR)", "A": "AVAL", "M": "MANCOMUNADO",
    "O": "OBLIGADO SOLIDARIO", "T": "TITULAR",
}

TIPO_CUENTA = {
    "F": "PAGOS FIJOS", "R": "REVOLVENTE",
    "L": "SIN LIMITE PREESTABLECIDO", "H": "HIPOTECARIO",
}

TIPO_CREDITO = {
    "PP": "PRESTAMO PERSONAL", "TC": "TARJETA DE CREDITO",
    "LC": "LINEA DE CREDITO", "PN": "PRESTAMO DE NOMINA",
    "AE": "FISICA ACTIVIDAD EMPRESARIAL", "AM": "APARATOS/MUEBLES",
    "CA": "COMPRA DE AUTOMOVIL", "MC": "MEJORAS A LA CASA",
    "OT": "OTROS", "F": "PAGOS FIJOS", "NC": "DESCONOCIDO",
}

FRECUENCIA = {
    "S": "SEMANAL", "C": "CATORCENAL", "Q": "QUINCENAL", "M": "MENSUAL",
    "B": "BIMESTRAL", "T": "TRIMESTRAL", "E": "SEMESTRAL", "A": "ANUAL",
    "R": "PAGO MINIMO REVOLVENTE", "P": "PAGO UNICO", "D": "DEDUCCION",
}

PREVENCION = {
    "CC": "CC - CUENTA<br/>CANCELADA O CERRADA",
    "CO": "CO - CUENTA<br/>EN COBRANZA",
    "FN": "FN - FRAUDE",
}

# Estatus de cuenta para "Resumen por Producto": el icono/color con el que
# se pinta cada fila. Orden de severidad usado para clasificar: cerrada >
# con atraso vigente > al corriente.
ESTATUS = {
    "cerrada":  {"icono": "CE", "color": "#7F7F7F", "orden": 2},
    "atraso":   {"icono": "AT", "color": "#C0392B", "orden": 1},
    "corriente": {"icono": "OK", "color": "#1E8449", "orden": 0},
}


# ------------------------------------------------------------- utilidades

def _t(nodo, tag, default=""):
    """Texto de un hijo, limpio y tolerante a nodos ausentes o vacíos."""
    if nodo is None:
        return default
    v = nodo.findtext(tag)
    return (v or "").strip() or default


def fecha(iso):
    """'2026-06-30' -> '30 JUN 2026'. Cadena vacía si no hay dato."""
    if not iso or len(iso) < 10:
        return ""
    try:
        a, m, d = iso[:4], int(iso[5:7]), iso[8:10]
        return f"{d} {MESES[m - 1]} {a}"
    except (ValueError, IndexError):
        return ""


def num(v, vacio="0"):
    """'32612' -> '32,612'. Los montos vienen como enteros sin separador."""
    if v is None or str(v).strip() == "":
        return vacio
    try:
        return f"{int(float(v)):,}"
    except ValueError:
        return str(v)


def _entero(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------- identidad ficticia

_NOMBRES_H = ["JOSE", "JUAN", "LUIS", "CARLOS", "MIGUEL", "FRANCISCO",
              "ALEJANDRO", "RICARDO", "FERNANDO", "SERGIO", "JORGE", "DANIEL"]
_NOMBRES_M = ["MARIA", "ANA", "LAURA", "PATRICIA", "DANIELA", "GABRIELA",
              "MONICA", "ROSA", "ELENA", "CLAUDIA", "VERONICA", "ADRIANA"]
_APELLIDOS = ["HERNANDEZ", "GARCIA", "MARTINEZ", "LOPEZ", "GONZALEZ",
              "RODRIGUEZ", "PEREZ", "SANCHEZ", "RAMIREZ", "TORRES", "FLORES",
              "VAZQUEZ", "REYES", "GUTIERREZ", "ORTIZ", "MORALES", "CASTRO",
              "JIMENEZ", "RUIZ", "MENDOZA"]
_CALLES = ["AVENIDA REVOLUCION", "CALLE JUAREZ", "CALLE HIDALGO",
           "AVENIDA INDEPENDENCIA", "CALLE MORELOS", "CALLE ALLENDE",
           "AVENIDA DE LAS FLORES", "CALLE NIÑOS HEROES", "CALLE 5 DE MAYO",
           "AVENIDA REFORMA", "CALLE ZARAGOZA", "CALLE MATAMOROS"]
_VOCALES = "AEIOU"
_CONSONANTES = "BCDFGHJKLMNPQRSTVWXYZ"

# Código de entidad usado por el CURP para el estado de nacimiento. Sólo
# cubre los que aparecen típicamente en domicilios de ejemplo; el resto cae
# en "NE" (no especificado) sin romper el formato.
_CURP_ESTADO = {
    "JAL": "JC", "CDMX": "DF", "CMX": "DF", "NL": "NL", "GTO": "GT",
    "PUE": "PL", "MEX": "MC", "VER": "VZ", "MICH": "MN", "QRO": "QO",
    "SON": "SR", "COAH": "CL", "CHIH": "CH", "SIN": "SL", "OAX": "OC",
}


def _rng_persona(semilla):
    """RNG determinista: mismo XML -> mismo alias en corridas repetidas."""
    h = hashlib.sha256((semilla or "circulo-credito-demo").encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def _primer_interno(texto, juego):
    """Primera letra de `juego` (vocal o consonante) dentro de texto[1:]."""
    for ch in texto[1:]:
        if ch in juego:
            return ch
    return "X"


def _rfc_ficticio(rng, nombres, paterno, materno, fecha_nac_iso):
    letras = (
        (paterno[:1] if paterno else "X")
        + _primer_interno(paterno or "X", _VOCALES)
        + (materno[:1] if materno else "X")
        + (nombres[:1] if nombres else "X")
    )
    aammdd = (fecha_nac_iso or "000101")[2:4] + (fecha_nac_iso or "000101")[5:7] + (fecha_nac_iso or "000101")[8:10]
    homoclave = "".join(rng.choice("0123456789ABCDEFGHIJKLMNPQRSTUVWXYZ") for _ in range(3))
    return f"{letras}{aammdd}{homoclave}"


def _curp_ficticio(rng, nombres, paterno, materno, fecha_nac_iso, sexo, estado):
    letras = (
        (paterno[:1] if paterno else "X")
        + _primer_interno(paterno or "X", _VOCALES)
        + (materno[:1] if materno else "X")
        + (nombres[:1] if nombres else "X")
    )
    aammdd = (fecha_nac_iso or "000101")[2:4] + (fecha_nac_iso or "000101")[5:7] + (fecha_nac_iso or "000101")[8:10]
    sexo_c = "H" if (sexo or "H").upper().startswith("H") else "M"
    edo = _CURP_ESTADO.get((estado or "").upper(), "NE")
    consonantes = (
        _primer_interno(paterno or "X", _CONSONANTES)
        + _primer_interno(materno or "X", _CONSONANTES)
        + _primer_interno(nombres or "X", _CONSONANTES)
    )
    homoclave = "".join(rng.choice("0123456789") for _ in range(2))
    return f"{letras}{aammdd}{sexo_c}{edo}{consonantes}{homoclave}"


def _identidad_ficticia(rng, fecha_nac_iso, sexo, estado):
    """Genera nombre + RFC + CURP ficticios pero formalmente consistentes
    entre sí (el RFC/CURP se derivan del nombre falso, como en la vida real).
    """
    pool_nombres = _NOMBRES_H if (sexo or "H").upper().startswith("H") else _NOMBRES_M
    nombres = rng.choice(pool_nombres)
    if rng.random() < 0.4:
        nombres += " " + rng.choice(pool_nombres)
    paterno = rng.choice(_APELLIDOS)
    materno = rng.choice([a for a in _APELLIDOS if a != paterno])
    rfc = _rfc_ficticio(rng, nombres, paterno, materno, fecha_nac_iso)
    curp = _curp_ficticio(rng, nombres, paterno, materno, fecha_nac_iso, sexo, estado)
    return nombres, paterno, materno, rfc, curp


def _calle_ficticia(rng):
    return f"{rng.choice(_CALLES)} {rng.randint(10, 999)}"


def _telefono_ficticio(rng):
    return f"33{rng.randint(10000000, 99999999)}"


def _digitos_ficticios(rng, n):
    return "".join(rng.choice("0123456789") for _ in range(n))


# ------------------------------------------------------------ extractores

def _persona(p, mascara, rng):
    n = p.find("Nombre")
    nombres = _t(n, "Nombres")
    paterno = _t(n, "ApellidoPaterno")
    materno = _t(n, "ApellidoMaterno")
    fecha_nac_iso = _t(n, "FechaNacimiento")
    rfc, curp = _t(n, "RFC"), _t(n, "CURP")

    if mascara:
        nombres, paterno, materno, rfc, curp = _identidad_ficticia(
            rng, fecha_nac_iso, _t(n, "Sexo"), _t(p.find("Domicilios/Domicilio"), "Estado"))

    return [
        ("Nombre (s)", nombres),
        ("Apellido Paterno", paterno),
        ("Apellido Materno", materno),
        ("Fecha de Nacimiento", fecha(fecha_nac_iso)),
        ("RFC", rfc),
        ("CURP", curp),
    ]


def _domicilios(p, mascara, rng):
    filas = []
    for i, d in enumerate(p.iter("Domicilio"), 1):
        calle = _t(d, "Direccion")
        tel = _t(d, "NumeroTelefono")
        if mascara:
            calle = _calle_ficticia(rng)
            if tel:
                tel = _telefono_ficticio(rng)
        filas.append([
            str(i), calle, _t(d, "ColoniaPoblacion"),
            _t(d, "DelegacionMunicipio"), _t(d, "Ciudad"),
            _t(d, "Estado"), _t(d, "CP"), tel,
            fecha(_t(d, "FechaRegistroDomicilio")),
        ])
    return filas


def _empleos(p, mascara):
    filas = []
    for e in p.iter("Empleo"):
        filas.append([
            "", _t(e, "NombreEmpresa"), _t(e, "Puesto"),
            num(_t(e, "SalarioMensual"), ""), _t(e, "Ciudad"),
            _t(e, "Estado"), fecha(_t(e, "FechaRegistro")),
        ])
    for i, f in enumerate(filas, 1):
        f[0] = str(i)
    return filas


def _estatus_cuenta(c):
    """Clasifica la cuenta para el Resumen por Producto: cerrada > con
    atraso vigente (el periodo más reciente del historial no es "V") >
    al corriente. El campo NumeroPagosVencidos es un acumulado histórico
    y no basta para esto: sólo el token más reciente refleja el atraso
    vigente al corte."""
    prevencion = _t(c, "ClavePrevencion")
    cerrada = bool(prevencion) or bool(_t(c, "FechaCierreCuenta"))
    if cerrada:
        return "cerrada"
    hist = _t(c, "HistoricoPagos").split()
    mas_reciente = hist[0] if hist else ""
    if mas_reciente and mas_reciente != "V":
        return "atraso"
    return "corriente"


def _cuenta(c):
    """Traduce un <Cuenta> al dict que consume tabla_detalle()."""
    prevencion = _t(c, "ClavePrevencion")
    cerrada = bool(prevencion) or bool(_t(c, "FechaCierreCuenta"))

    resp = TIPO_RESPONSABILIDAD.get(_t(c, "TipoResponsabilidad"), "")
    cta = TIPO_CUENTA.get(_t(c, "TipoCuenta"), "")

    # El historial viene como cadena de marcas separadas por espacio
    hist = _t(c, "HistoricoPagos").strip()

    return {
        "periodicidad": FRECUENCIA.get(_t(c, "FrecuenciaPagos"), ""),
        "activa": not cerrada,
        "responsabilidad": f"{cta} /<br/>{resp}",
        "credito": TIPO_CREDITO.get(_t(c, "TipoCredito"), _t(c, "TipoCredito")),
        "otorgante": _t(c, "NombreOtorgante"),
        "plazo": _t(c, "NumeroPagos"),
        "montos": [
            num(_t(c, "LimiteCredito")),
            num(_t(c, "CreditoMaximo")),
            num(_t(c, "SaldoActual")),
            num(_t(c, "SaldoVencido")),
            num(_t(c, "MontoPagar")),
        ],
        "fechas": [
            fecha(_t(c, "FechaReporte")),
            fecha(_t(c, "FechaAperturaCuenta")),
            fecha(_t(c, "FechaCierreCuenta")),
            fecha(_t(c, "FechaUltimoPago")),
        ],
        "atraso": _t(c, "PeorAtraso", "0"),
        "monto_atraso": num(_t(c, "SaldoVencidoPeorAtraso")),
        "fecha_atraso": fecha(_t(c, "FechaPeorAtraso")),
        "historial": hist or "&nbsp;",
        "situacion": PREVENCION.get(prevencion, ""),
        # crudos, para el resumen agregado
        "_tipo": _t(c, "TipoCredito"),
        "_frec": _t(c, "FrecuenciaPagos"),
        "_estatus": _estatus_cuenta(c),
        "_lim": _entero(_t(c, "LimiteCredito")),
        "_apr": _entero(_t(c, "CreditoMaximo")),
        "_act": _entero(_t(c, "SaldoActual")),
        "_ven": _entero(_t(c, "SaldoVencido")),
        "_pago": _entero(_t(c, "MontoPagar")),
    }


def _resumen(cuentas):
    """Agrupa por (tipo de crédito, estatus) y reparte el pago según su
    periodicidad — igual que el reporte oficial: cada tipo de crédito puede
    aparecer en más de una fila si tiene cuentas al corriente, con atraso
    vigente y cerradas. El orden de las filas es el de primera aparición
    de cada combinación en el XML (no alfabético ni por conteo)."""
    grupos = {}
    orden = []
    for c in cuentas:
        clave = (c["_tipo"], c["_estatus"])
        if clave not in grupos:
            grupos[clave] = dict(n=0, lim=0, apr=0, act=0, ven=0, sem=0, qna=0, men=0)
            orden.append(clave)
        g = grupos[clave]
        g["n"] += 1
        g["lim"] += c["_lim"]
        g["apr"] += c["_apr"]
        g["act"] += c["_act"]
        g["ven"] += c["_ven"]
        destino = {"S": "sem", "Q": "qna", "M": "men"}.get(c["_frec"])
        if destino:
            g[destino] += c["_pago"]

    filas, tot = [], dict(n=0, lim=0, apr=0, act=0, ven=0, sem=0, qna=0, men=0)
    for tipo, estatus in orden:
        g = grupos[(tipo, estatus)]
        filas.append([
            ESTATUS[estatus]["icono"], ESTATUS[estatus]["color"],
            TIPO_CREDITO.get(tipo, tipo), str(g["n"]),
            num(g["lim"]), num(g["apr"]), num(g["act"]), num(g["ven"]),
            num(g["sem"]), num(g["qna"]), num(g["men"]),
        ])
        for k in tot:
            tot[k] += g[k]

    totales = ["", "", "Totales", str(tot["n"]), num(tot["lim"]), num(tot["apr"]),
               num(tot["act"]), num(tot["ven"]), num(tot["sem"]),
               num(tot["qna"]), num(tot["men"])]
    return filas, totales


def _consultas(p):
    filas = []
    for q in p.iter("ConsultaEfectuada"):
        filas.append([
            fecha(_t(q, "FechaConsulta")),
            _t(q, "NombreOtorgante"),
            TIPO_CREDITO.get(_t(q, "TipoCredito"), _t(q, "TipoCredito")),
            num(_t(q, "ImporteCredito")),
            _t(q, "ClaveUnidadMonetaria"),
        ])
    return filas


def _mensajes(p):
    """<Mensajes><Mensaje><TipoMensaje>/<Leyenda> alimenta la tabla PLD
    Check (Consecutivo=TipoMensaje, Mensajes=Leyenda). No se conoce, a
    partir de este único esquema de ejemplo, un canal separado para la
    sección "Mensajes" genérica del reporte oficial, así que se deja
    siempre en su estado vacío ("No hay mensajes..."); si el buró usa
    algún TipoMensaje para alertas no-PLD, ese filtro se agrega aquí."""
    filas = []
    for m in p.iter("Mensaje"):
        tipo = _t(m, "TipoMensaje")
        leyenda = _t(m, "Leyenda")
        if tipo or leyenda:
            filas.append([tipo, leyenda])
    return filas


# ------------------------------------------------------------------ pública

def cargar(ruta, mascara=True):
    """Lee el XML y devuelve un dict con todo lo que necesita el PDF."""
    # El archivo declara ISO-8859-1; ElementTree respeta la declaración.
    raiz = ET.parse(ruta).getroot()
    p = raiz.find(".//Persona")
    if p is None:
        raise ValueError("No se encontró <Persona> en la respuesta.")

    enc = p.find("Encabezado")
    if _t(enc, "ExpedienteEncontrado") != "1":
        raise ValueError("La respuesta indica que no se encontró expediente.")

    n = p.find("Nombre")
    rng = _rng_persona(_t(n, "CURP") or _t(n, "RFC") or _t(enc, "FolioConsulta"))

    cuentas = [_cuenta(c) for c in p.iter("Cuenta")]
    resumen, totales = _resumen(cuentas)

    folio = _t(enc, "FolioConsulta")
    folio_otg = _t(enc, "FolioConsultaOtorgante")
    if mascara:
        if folio:
            folio = _digitos_ficticios(rng, len(folio))
        if folio_otg:
            prefijo, _, resto = folio_otg.partition("_")
            folio_otg = f"{_digitos_ficticios(rng, len(prefijo))}_{_digitos_ficticios(rng, len(resto))}" \
                if resto else _digitos_ficticios(rng, len(folio_otg))

    # El XML de este esquema no trae la hora de consulta (viene del momento
    # de la llamada a la API, fuera de este payload); se usa el instante de
    # generación del PDF, con el mismo formato que el reporte oficial.
    ahora = datetime.now()
    fecha_consulta = f"{ahora:%H:%M} - {ahora.day:02d} {MESES[ahora.month - 1]} {ahora.year}"

    return {
        "meta": {
            "Fecha de Consulta": fecha_consulta,
            "Folio Consulta": folio,
            "Folio Consulta otra SIC": folio_otg,
        },
        "persona": _persona(p, mascara, rng),
        "domicilios": _domicilios(p, mascara, rng),
        "empleos": _empleos(p, mascara),
        "mensajes": _mensajes(p),
        "resumen": resumen,
        "totales": totales,
        "cuentas": cuentas,
        "consultas": _consultas(p),
        "mascara": mascara,
    }


if __name__ == "__main__":
    import sys
    d = cargar(sys.argv[1] if len(sys.argv) > 1 else "respuesta.xml")
    print(f"cuentas={len(d['cuentas'])} consultas={len(d['consultas'])} "
          f"domicilios={len(d['domicilios'])} grupos={len(d['resumen'])}")
    print("totales:", d["totales"])
