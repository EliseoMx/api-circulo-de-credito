"""
XML del buró (formato <Respuesta><Personas><Persona>...) -> PDF.

Une el parser (parser_xml.py) con la plantilla de layout
(reporte_estructura.py). La plantilla no sabe nada del XML y el parser no
sabe nada de ReportLab: si el buró cambia el esquema, sólo se toca el
parser.

Este módulo viene de Xml2Pdf-Circulo (D:\\CIRCULO_DE_CREDITO\\Xml2Pdf-Circulo),
integrado aquí para que api_circulo.py pueda generar el PDF directo desde la
respuesta del API, sin depender de un .exe aparte.
"""

from reportlab.platypus import Spacer, Paragraph
from reportlab.lib import colors

from parser_xml import cargar
from reporte_estructura import (
    Documento, encabezado_reporte, titulo, caja_datos, caja_texto,
    tabla_simple, tabla_resumen, tabla_pld, tabla_detalle, tabla_consultas,
    escalar, _p, ST_NOTA,
)


def construir(xml: str, salida: str = "reporte.pdf", mascara: bool = False):
    """
    Genera el PDF a partir de la ruta de un XML ya escrito en disco (el
    parser lee con xml.etree, necesita un archivo, no un string en memoria).

    mascara=False (default aquí): usa los datos reales del XML tal cual.
    mascara=True: genera una identidad ficticia legible para demos/pruebas
    (nombre, RFC, CURP, calle y teléfono; los datos financieros/cuentas
    nunca se tocan).
    """
    d = cargar(xml, mascara=mascara)
    doc = Documento(salida)
    story = []

    story.append(encabezado_reporte(d["meta"]))

    if d["mascara"]:
        story.append(Spacer(1, 5))
        story.append(Paragraph(
            "DOCUMENTO GENERADO EN MODO PRUEBA — IDENTIDAD FICTICIA "
            "(nombre, RFC, CURP, calle y teléfono no corresponden al titular real)",
            _p(7, bold=True, alignment=1,
               textColor=colors.HexColor("#B00020"))))

    story += titulo("Datos Generales")
    story.append(caja_datos(d["persona"]))

    # Los <Mensaje> del XML alimentan la tabla PLD Check (Consecutivo /
    # Mensajes). El esquema de ejemplo no distingue un canal aparte para
    # avisos generales, así que esa sección se deja en su estado vacío
    # tal como aparece en el reporte oficial de referencia.
    story += titulo("Mensajes")
    story.append(caja_texto("No hay mensajes..."))

    story += titulo("PLD Check")
    story.append(tabla_pld(d["mensajes"]))

    story += titulo("Domicilios")
    story.append(tabla_simple(
        ["#", "Calle y Número", "Colonia", "Municipio", "Ciudad",
         "Estado", "CP", "Teléfono", "Fecha de Registro"],
        d["domicilios"],
        escalar([16, 132, 80, 62, 62, 36, 34, 60, 73]),
        vacio="No existen Domicilios Registrados"))

    story += titulo("Empleos")
    story.append(tabla_simple(
        ["#", "Compañía", "Puesto", "Salario", "Ciudad",
         "Estado", "Fecha de Registro"],
        d["empleos"],
        escalar([16, 150, 110, 70, 90, 45, 74]),
        vacio="No existen Empleos Registrados"))

    story += titulo("Resumen por Producto")
    story.append(tabla_resumen(d["resumen"], d["totales"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Los pagos requeridos por corte sólo consideran créditos con "
        "periodicidad semanal, quincenal o mensual.", ST_NOTA))

    story += titulo("Indicadores")
    story.append(caja_texto("No existen Indicadores Registrados"))

    story += titulo("Detalle de Cuentas")
    story.append(tabla_detalle(d["cuentas"]))

    story += titulo("Consultas Realizadas")
    story.append(tabla_consultas(d["consultas"]))

    story.append(Spacer(1, 10))
    story.append(Paragraph("FIN DEL REPORTE", _p(6.5, alignment=1)))

    doc.build(story)
    return salida, d
