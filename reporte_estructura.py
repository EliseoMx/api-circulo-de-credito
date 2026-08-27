"""
Plantilla de reporte tabular denso estilo "reporte de crédito consolidado".

Demuestra las técnicas de layout:
  - Cabeceras multinivel con SPAN
  - repeatRows: la cabecera se redibuja en cada página
  - Bloques de N filas que no se parten entre páginas (KeepTogether por bloque)
  - Texto vertical (rotado 90°) en celdas
  - Pie de página fijo vía callback de canvas
  - Tablas largas que fluyen automáticamente a varias páginas

Datos 100% ficticios. Marca genérica.
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer,
    Table, TableStyle, Flowable, KeepTogether,
)

# ---------------------------------------------------------------- constantes

PAGE_W, PAGE_H = A4
MARGIN = 20
USABLE_W = PAGE_W - 2 * MARGIN          # 555 pt

# =====================================================================
# TEMA — único lugar que hay que tocar para cambiar la apariencia.
# Cambia MARCA_COLOR por el color de tu institución y toda la plantilla
# (títulos, filetes, recuadro de marca) se recolorea sola.
# =====================================================================

THEME = {
    # --- identidad
    "color":        "#1F5C99",   # <-- tu color de marca aquí
    "color_suave":  "#E8EEF5",   # fondo de cabeceras de tabla
    "linea":        "#7F7F7F",   # bordes de tabla
    "linea_fina":   "#BFBFBF",   # separadores internos

    # --- tipografía: una sola familia, dos pesos
    "font":         "Helvetica",
    "font_bold":    "Helvetica-Bold",

    # --- escala tipográfica (pt). Todo el documento sale de aquí.
    "t_titulo":     15,    # título del reporte
    "t_seccion":    11,    # encabezados de sección
    "t_campo":      7.5,   # etiqueta/valor en cajas de datos
    "t_meta":       6.5,   # folios, notas al pie de tabla
    "t_hdr":        5.2,   # cabeceras de tabla densa
    "t_dato":       5.0,   # celdas de tabla densa
    "t_micro":      4.4,   # historial de pago, "+ Reciente"

    # --- ritmo vertical: separación antes/después de cada sección
    "gap_antes":    9,
    "gap_despues":  3,
}

AZUL = colors.HexColor(THEME["color"])
GRIS_HDR = colors.HexColor(THEME["color_suave"])
LINEA = colors.HexColor(THEME["linea"])
LINEA_FINA = colors.HexColor(THEME["linea_fina"])

EMPRESA = "FINANCIERA EJEMPLO"
SITIO = "www.ejemplo-financiera.mx"
TELEFONO = "Call Center (55) 0000-0000"


def _p(size, **kw):
    """Crea un estilo de párrafo tomando la familia tipográfica del tema."""
    bold = kw.pop("bold", False)
    font = kw.pop("font", THEME["font_bold"] if bold else THEME["font"])
    return ParagraphStyle(
        f"s{size}{kw}{font}", fontName=font,
        fontSize=size, leading=size + 1.2, **kw
    )


T = THEME
ST_TITULO = _p(T["t_titulo"], bold=True, alignment=1, textColor=colors.black)
ST_SECCION = _p(T["t_seccion"], bold=True, textColor=AZUL)
ST_META = _p(T["t_meta"], alignment=2)
ST_LBL = _p(T["t_campo"], bold=True, alignment=2)
ST_VAL = _p(T["t_campo"])
ST_CELDA = _p(T["t_dato"], alignment=1)
ST_CELDA_L = _p(T["t_dato"])
ST_HDR = _p(T["t_hdr"], bold=True, alignment=1)
ST_NOTA = _p(T["t_meta"])
ST_MICRO = _p(T["t_micro"])
ST_MICRO_C = _p(T["t_micro"], alignment=1)
ST_MICRO_R = _p(T["t_micro"], alignment=2)


# ------------------------------------------------- flowable de texto vertical

class TextoVertical(Flowable):
    """Dibuja texto girado 90° dentro de una celda. Útil para etiquetas
    de fila muy angostas (MENSUAL, ANUAL, QUINCENAL...)."""

    def __init__(self, texto, size=4.2, alto=28):
        super().__init__()
        self.texto = texto
        self.size = size
        self.alto = alto

    def wrap(self, avail_w, avail_h):
        # El ancho ocupado es la altura de la fuente; el alto es el largo del texto
        return (self.size + 1, self.alto)

    def draw(self):
        c = self.canv
        c.saveState()
        c.rotate(90)
        c.setFont("Helvetica", self.size)
        c.drawCentredString(self.alto / 2.0, -self.size + 1, self.texto)
        c.restoreState()


# ------------------------------------------------------- pie de página global

def _pie(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 5.5)
    canvas.drawRightString(PAGE_W - MARGIN, 22, TELEFONO)
    canvas.drawRightString(PAGE_W - MARGIN, 15, "Interior 01800-000-0000")
    canvas.setFont("Helvetica", 5.5)
    canvas.drawString(MARGIN, 15, SITIO)
    canvas.setFont("Helvetica", 5)
    canvas.drawCentredString(PAGE_W / 2.0, 15, f"Página {doc.page}")
    canvas.restoreState()


class Documento(BaseDocTemplate):
    def __init__(self, filename, **kw):
        super().__init__(filename, pagesize=A4,
                         leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=MARGIN, bottomMargin=32, **kw)
        frame = Frame(MARGIN, 32, USABLE_W, PAGE_H - MARGIN - 32, id="cuerpo",
                      leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="normal", frames=[frame], onPage=_pie)
        ])


# ------------------------------------------------------------ bloque de marca

def encabezado_reporte(meta):
    """Título centrado + metadatos a la derecha (sin logo/marca)."""
    meta_txt = "<br/>".join(
        f"<b>{k}:</b> {v}" for k, v in meta.items()
    )
    fila = Table(
        [["",
          Paragraph("Reporte de Crédito<br/>Consolidado", ST_TITULO),
          Paragraph(meta_txt, ST_META)]],
        colWidths=[110, 265, 180],
    )
    fila.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return fila


class Filete(Flowable):
    """Línea horizontal del ancho útil completo. Garantiza que todas las
    secciones compartan el mismo riel izquierdo y derecho."""

    def __init__(self, ancho=USABLE_W, grosor=1.1, color=None):
        super().__init__()
        self.ancho, self.grosor = ancho, grosor
        self.color = color or AZUL

    def wrap(self, *a):
        return (self.ancho, self.grosor + 1)

    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.grosor)
        self.canv.line(0, 0, self.ancho, 0)


def titulo(texto):
    """Encabezado de sección: mismo color, mismo tamaño, mismo riel."""
    return [Spacer(1, THEME["gap_antes"]),
            Paragraph(texto, ST_SECCION),
            Spacer(1, 1.5),
            Filete(),
            Spacer(1, THEME["gap_despues"])]


def caja_texto(texto, ancho=USABLE_W):
    """Recuadro de una sola línea para secciones sin datos (Mensajes,
    Indicadores...). Mismo trazo que las demás cajas de la plantilla."""
    t = Table([[Paragraph(texto, _p(6.5, bold=True))]], colWidths=[ancho],
               hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINEA),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


# ------------------------------------------------ 1. caja de datos generales

def caja_datos(pares, ancho=290):
    filas = [[Paragraph(f"{k}:", ST_LBL), Paragraph(v, ST_VAL)] for k, v in pares]
    t = Table(filas, colWidths=[ancho * 0.45, ancho * 0.55], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINEA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


# -------------------------------------------- 2. tabla simple con encabezado

def tabla_simple(cabeceras, filas, anchos, vacio=None):
    """Tabla de una sola fila de encabezado. Si `filas` viene vacía se pinta
    una única fila que abarca todo el ancho con el mensaje `vacio`."""
    head = [[Paragraph(h, ST_HDR) for h in cabeceras]]
    estilo = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINEA),
        ("BACKGROUND", (0, 0), (-1, 0), GRIS_HDR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]
    if not filas:
        cuerpo = [[Paragraph(vacio or "No existen registros",
                             _p(6.5, font="Helvetica-Bold", alignment=1))]
                  + [""] * (len(cabeceras) - 1)]
        estilo.append(("SPAN", (0, 1), (-1, 1)))
    else:
        cuerpo = [[Paragraph(str(c), ST_CELDA) for c in f] for f in filas]

    t = Table(head + cuerpo, colWidths=anchos, repeatRows=1)
    t.setStyle(TableStyle(estilo))
    return t


# ------------------------------- 3. resumen con cabecera agrupada + totales

def tabla_resumen(filas, totales):
    """`filas` / `totales`: [icono, color_hex, producto, cuentas, limite,
    aprobado, actual, vencido, semanal, quincenal, mensual]. `icono`/`color`
    vienen vacíos en la fila de totales. El icono marca el estatus de ese
    grupo de cuentas: al corriente / con atraso vigente / cerradas — un
    mismo tipo de crédito puede tener una fila por cada estatus, igual que
    el reporte oficial."""
    anchos = escalar([26, 124, 40, 62, 62, 62, 55, 41, 41, 42])
    head = [
        [Paragraph("Descripción", ST_HDR), "", "",
         Paragraph("Montos [Pesos]", ST_HDR), "", "", "",
         Paragraph("Pagos Requeridos por corte [Pesos]", ST_HDR), "", ""],
        ["", Paragraph("Producto", ST_HDR), Paragraph("Cuentas", ST_HDR),
         Paragraph("Límite", ST_HDR), Paragraph("Aprobado", ST_HDR),
         Paragraph("Actual", ST_HDR), Paragraph("Vencido", ST_HDR),
         Paragraph("Semanal", ST_HDR), Paragraph("Quincenal", ST_HDR),
         Paragraph("Mensual", ST_HDR)],
    ]

    def _fila(f, negrita=False):
        icono, color, *resto = f
        cel_icono = Paragraph(
            f"<b>{icono}</b>" if icono else "",
            _p(T["t_hdr"], bold=True, alignment=1,
               textColor=colors.HexColor(color) if color else colors.black))
        celdas = [cel_icono]
        for i, c in enumerate(resto):
            txt = f"<b>{c}</b>" if negrita else str(c)
            celdas.append(Paragraph(txt, ST_CELDA_L if i == 0 else ST_CELDA))
        return celdas

    cuerpo = [_fila(f) for f in filas]
    tot = [_fila(totales, negrita=True)]

    t = Table(head + cuerpo + tot, colWidths=anchos, repeatRows=2)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, LINEA),
        ("BACKGROUND", (0, 0), (-1, 1), GRIS_HDR),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F2F2F2")),
        ("SPAN", (0, 0), (2, 0)),       # Descripción abarca icono+Producto+Cuentas
        ("SPAN", (3, 0), (6, 0)),       # Montos abarca 4
        ("SPAN", (7, 0), (9, 0)),       # Pagos requeridos abarca 3
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return t


def tabla_pld(filas):
    """PLD Check: Consecutivo (TipoMensaje) / Mensajes (Leyenda), tal cual
    los reporta el buró. Reusa el estilo de tabla_simple."""
    return tabla_simple(
        ["Consecutivo", "Mensajes"], filas, escalar([90, 465]),
        vacio="No hay mensajes de PLD")


# ---------------------------- 4. detalle de cuentas: el bloque multi-fila

def escalar(pesos, total=USABLE_W):
    """Convierte una lista de anchos relativos en puntos que suman exactamente
    el ancho útil. Evita depender de que A4 mida un número entero."""
    s = float(sum(pesos))
    return [p * total / s for p in pesos]


DET_ANCHOS = escalar(
    [12, 12, 48, 34, 34, 22, 34, 36, 34, 32, 32, 36, 36, 34, 34, 22, 28, 35])

DET_HEAD = [
    [Paragraph("Descripción", ST_HDR), "", "", "", "", "",
     Paragraph("Montos", ST_HDR), "", "", "", "",
     Paragraph("Fechas", ST_HDR), "", "", "",
     Paragraph("Peor Atraso", ST_HDR), "", ""],
    ["", "", "", "", "", "",
     Paragraph("[Pesos]", ST_HDR), "", "", "", "",
     Paragraph("[dd/mmm/aa]", ST_HDR), "", "", "",
     Paragraph("Atraso", ST_HDR), Paragraph("Monto", ST_HDR),
     Paragraph("Fecha", ST_HDR)],
    ["", "", Paragraph("Producto<br/>Responsabilidad", ST_HDR),
     Paragraph("Crédito", ST_HDR), Paragraph("Otorgante", ST_HDR),
     Paragraph("Plazo", ST_HDR), Paragraph("Límite", ST_HDR),
     Paragraph("Aprobado", ST_HDR), Paragraph("Actual", ST_HDR),
     Paragraph("Vencido", ST_HDR), Paragraph("a Pagar", ST_HDR),
     Paragraph("Reporte", ST_HDR), Paragraph("Apertura", ST_HDR),
     Paragraph("Cierre", ST_HDR), Paragraph("Pago", ST_HDR),
     Paragraph("Situación", ST_HDR), "", ""],
]

DET_HEAD_STYLE = [
    ("SPAN", (0, 0), (5, 0)), ("SPAN", (6, 0), (10, 0)),
    ("SPAN", (11, 0), (14, 0)), ("SPAN", (15, 0), (17, 0)),
    ("SPAN", (0, 1), (5, 1)), ("SPAN", (6, 1), (10, 1)),
    ("SPAN", (11, 1), (14, 1)),
    ("SPAN", (0, 2), (1, 2)), ("SPAN", (15, 2), (17, 2)),
    ("BACKGROUND", (0, 0), (-1, 2), GRIS_HDR),
    ("GRID", (0, 0), (-1, 2), 0.4, LINEA),
]


def bloque_cuenta(cta, base_row):
    """Devuelve (filas, comandos_de_estilo) para UNA cuenta = 3 filas.

    base_row es el índice de la primera fila del bloque dentro de la tabla
    completa; los SPAN se calculan relativos a él.
    """
    r = base_row
    marca = "\u2713" if cta["activa"] else "\u00d7"  # x latina: existe en Helvetica

    filas = [
        # ---- fila de datos
        [TextoVertical(cta["periodicidad"]),
         Paragraph(marca, _p(T["t_hdr"], alignment=1)),
         Paragraph(cta["responsabilidad"], ST_CELDA),
         Paragraph(cta["credito"], ST_CELDA),
         Paragraph(cta["otorgante"], ST_CELDA),
         Paragraph(cta["plazo"], ST_CELDA)]
        + [Paragraph(v, ST_CELDA) for v in cta["montos"]]
        + [Paragraph(v, ST_CELDA) for v in cta["fechas"]]
        + [Paragraph(cta["atraso"], ST_CELDA),
           Paragraph(cta["monto_atraso"], ST_CELDA),
           Paragraph(cta["fecha_atraso"], ST_CELDA)],
        # ---- fila etiqueta del historial
        ["", "", Paragraph("Historial de Pago (Periodos)<br/>"
                           "Últimos 24 (de izquierda a derecha)",
                           ST_MICRO_C)]
        + [""] * 12
        + [Paragraph(cta.get("situacion", ""), ST_MICRO_C), "", ""],
        # ---- fila con la cadena del historial
        ["", "", Paragraph("+ Reciente", ST_MICRO),
         Paragraph(cta["historial"], ST_MICRO_C)]
        + [""] * 11
        + [Paragraph("+ Antiguo", ST_MICRO_R), "", ""],
    ]

    estilo = [
        ("SPAN", (0, r), (0, r + 2)),          # periodicidad vertical
        ("SPAN", (1, r), (1, r + 2)),          # icono
        ("SPAN", (2, r + 1), (14, r + 1)),     # etiqueta historial
        ("SPAN", (15, r + 1), (17, r + 1)),    # situación
        ("SPAN", (3, r + 2), (14, r + 2)),     # cadena del historial
        ("SPAN", (15, r + 2), (17, r + 2)),    # + Antiguo
        ("BOX", (0, r), (-1, r + 2), 0.4, LINEA),
        ("LINEBELOW", (2, r), (-1, r), 0.3, LINEA_FINA),
        ("INNERGRID", (2, r), (17, r), 0.3, LINEA),
    ]
    return filas, estilo


def tabla_detalle(cuentas):
    filas = list(DET_HEAD)
    estilo = list(DET_HEAD_STYLE)
    for cta in cuentas:
        f, e = bloque_cuenta(cta, len(filas))
        filas.extend(f)
        estilo.extend(e)

    t = Table(filas, colWidths=DET_ANCHOS, repeatRows=3)
    estilo += [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
    ]
    # Nota: no hace falta forzar "no partir" el bloque. Los SPAN verticales
    # de las columnas 0 y 1 abarcan las 3 filas, y ReportLab nunca corta
    # una tabla en medio de un SPAN vertical.
    t.setStyle(TableStyle(estilo))
    return t


# ------------------------------------------------------ 5. tabla larga final

def tabla_consultas(filas):
    anchos = escalar([110, 150, 145, 80, 70])
    return tabla_simple(
        ["Fecha de Consulta", "Otorgante", "Tipo de Crédito", "Monto", "Moneda"],
        filas, anchos
    )


# ----------------------------------------------------------- datos de ejemplo

def datos_demo():
    cuentas = []
    plantillas = [
        ("MENSUAL", True, "PAGOS FIJOS /<br/>AVAL", "PRESTAMO<br/>PERSONAL",
         "COOPERATIVA A", "240", "V V V V V V V V V V V V V V V V V V V V V V V V", ""),
        ("MENSUAL", False, "PAGOS FIJOS /<br/>INDIVIDUAL (TITULAR)",
         "PRESTAMO<br/>PERSONAL", "COOPERATIVA B", "48",
         "V V V V V V V V V01 V V V V V", "CC - CUENTA<br/>CANCELADA O CERRADA"),
        ("ANUAL", False, "PAGOS FIJOS /<br/>INDIVIDUAL (TITULAR)",
         "LINEA DE<br/>CREDITO", "ENTIDAD C", "1",
         "V V V V V V", "CC - CUENTA<br/>CANCELADA O CERRADA"),
        ("QUINCENAL", True, "REVOLVENTE /<br/>INDIVIDUAL (TITULAR)",
         "TARJETA DE<br/>CREDITO", "BANCO D", "",
         "V V V V V V V V V V V V V V V V V V", ""),
        ("TRIMESTRAL", False, "PAGOS FIJOS /<br/>INDIVIDUAL (TITULAR)",
         "APARATOS<br/>/MUEBLES", "TIENDA E", "12",
         "V V V V V-- V V", "CC - CUENTA<br/>CANCELADA O CERRADA"),
    ]
    for i in range(24):  # se repiten para forzar varias páginas
        p = plantillas[i % len(plantillas)]
        cuentas.append({
            "periodicidad": p[0], "activa": p[1], "responsabilidad": p[2],
            "credito": p[3], "otorgante": p[4], "plazo": p[5],
            "montos": ["0", f"{(i + 1) * 5000:,}", f"{(i + 1) * 1200:,}",
                       "0", f"{(i + 1) * 100:,}"],
            "fechas": ["30 JUN 2026", "20 OCT 2022", "", "22 JUN 2026"],
            "atraso": "0", "monto_atraso": "0", "fecha_atraso": "",
            "historial": p[6], "situacion": p[7],
        })

    consultas = [
        [f"{d:02d} JUL 2026", "ENTIDAD EJEMPLO", "PAGOS FIJOS",
         f"{(d * 1000):,}", "MX"]
        for d in range(1, 46)
    ]
    return cuentas, consultas


# -------------------------------------------------------------------- armado

def construir(salida="reporte_estructura.pdf"):
    cuentas, consultas = datos_demo()
    doc = Documento(salida)
    story = []

    story.append(encabezado_reporte({
        "Fecha de Consulta": "11:19 - 17 JUL 2026",
        "Folio Consulta": "0,000,000,000",
        "Folio Referencia": "00000_0000000000000000-0",
    }))

    story += titulo("Datos Generales")
    story.append(caja_datos([
        ("Nombre (s)", "NOMBRE DEMO"),
        ("Apellido Paterno", "APELLIDO UNO"),
        ("Apellido Materno", "APELLIDO DOS"),
        ("Fecha de Nacimiento", "01 ENE 1990"),
        ("Identificador Fiscal", "XXXX000000"),
        ("Identificador Único", "XXXX000000XXXXXX00"),
    ]))

    story += titulo("Mensajes")
    story.append(caja_texto("No hay mensajes..."))

    story += titulo("PLD Check")
    story.append(tabla_pld([["2", "1"]]))

    story += titulo("Domicilios")
    story.append(tabla_simple(
        ["#", "Calle y Número", "Colonia", "Municipio", "Ciudad",
         "Estado", "CP", "Teléfono", "Fecha de Registro"],
        [["1", "CALLE DEMO 100", "CENTRO", "MUNICIPIO", "CIUDAD",
          "XX", "00000", "0000000000", "17 JUL 2026"],
         ["2", "AVENIDA EJEMPLO 250", "REFORMA", "MUNICIPIO", "CIUDAD",
          "XX", "00000", "", "18 OCT 2022"]],
        escalar([16, 132, 80, 62, 62, 36, 34, 60, 73])))

    story += titulo("Empleos")
    story.append(tabla_simple(
        ["#", "Compañía", "Puesto", "Salario", "Ciudad",
         "Estado", "Fecha de Registro"],
        [], escalar([16, 150, 110, 70, 90, 45, 74]),
        vacio="No existen Empleos Registrados"))

    story += titulo("Resumen por Producto")
    story.append(tabla_resumen(
        [["OK", "#1E8449", "PRESTAMO PERSONAL", "5", "888,600", "1,038,600",
          "566,434", "0", "0", "0", "625"],
         ["OK", "#1E8449", "TARJETA DE CREDITO", "3", "394,400", "414,528",
          "183,358", "0", "0", "0", "7,030"],
         ["CE", "#7F7F7F", "LINEA DE CREDITO", "5", "13,688", "6,201",
          "228", "0", "0", "0", "228"],
         ["CE", "#7F7F7F", "APARATOS/MUEBLES", "2", "30,600", "30,600",
          "0", "0", "0", "0", "0"]],
        ["", "", "Totales", "15", "1,327,288", "1,489,929", "750,020",
         "0", "0", "0", "7,883"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Nota al pie de la tabla: se excluyen los créditos cuya periodicidad "
        "de pago no es mensual, quincenal o semanal.", ST_NOTA))

    story += titulo("Indicadores")
    story.append(caja_texto("No existen Indicadores Registrados"))

    story += titulo("Detalle de Cuentas")
    story.append(tabla_detalle(cuentas))

    story += titulo("Consultas Realizadas")
    story.append(tabla_consultas(consultas))

    story.append(Spacer(1, 12))
    story.append(Paragraph("DOCUMENTO DE MUESTRA — DATOS FICTICIOS",
                           _p(7, font="Helvetica-Bold", alignment=1)))
    story.append(Paragraph("FIN DEL REPORTE", _p(6.5, alignment=1)))

    doc.build(story)
    return salida


if __name__ == "__main__":
    print("Generado:", construir())