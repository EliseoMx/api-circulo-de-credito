# API Círculo de Crédito

Cliente para el API "Reporte de Crédito Consolidado + FICO® Score y PLD Check® -
Personas Físicas" de Círculo de Crédito. Consulta el API, y genera el **JSON**
crudo, el **XML** en el formato clásico del buró y/o el **PDF** del reporte
—tú eliges cuál o cuáles con un flag. Se controla con flags de línea de
comandos estilo `/CLAVE_WS="valor"` (igual que `BURO_DE_CREDITO.exe`), para
poder llamarlo desde un `.bat` igual que otras integraciones internas.

La generación de PDF viene integrada de `Xml2Pdf-Circulo`
(`D:\CIRCULO_DE_CREDITO\Xml2Pdf-Circulo`): `xml_a_pdf.py`, `parser_xml.py` y
`reporte_estructura.py` — mismo layout y lógica, ahora en un solo flujo.

No usa `.env` ni escanea ninguna carpeta de entrada solo: cada flag tiene un
default en el código, y se sobreescribe solo si lo pasas al ejecutar.

## 1. Instalación (con Python)

Requiere Python 3.10+.

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

## 2. Uso — flags disponibles

Todos son opcionales.

**Conexión / credenciales:**

| Flag | Default | Descripción |
|---|---|---|
| `/AMBIENTE_WS` | `dev` | `dev` o `prod` |
| `/API_KEY_WS` | (vacío) | tu `x-api-key`. Requerido en dev y prod |
| `/USUARIO_WS` | (vacío) | usuario Círculo de Crédito. Requerido en prod |
| `/PASS_WS` | (vacío) | contraseña. Requerido en prod |
| `/LLAVE_PRIVADA_WS` | (vacío) | valor `priv` de tu llave ECDSA en hex. Requerido en prod |
| `/LLAVE_PUBLICA_WS` | (vacío) | llave pública de Círculo de Crédito, en hex (opcional, valida la firma de la respuesta) |

**Persona a consultar** (si no usas `/INPUT_WS`, se arma con estos flags):

`/Nombre_primerNombre_WS`, `/Nombre_segundoNombre_WS`, `/Nombre_apellidoPaterno_WS`,
`/Nombre_apellidoMaterno_WS`, `/Nombre_RFC_WS`, `/Nombre_fechaNacimiento_WS` (AAAA-MM-DD),
`/Nombre_nacionalidad_WS` (default `MX`), `/Domicilio_direccion1_WS`, `/Domicilio_colonia_WS`,
`/Domicilio_municipio_WS`, `/Domicilio_ciudad_WS`, `/Domicilio_estado_WS`, `/Domicilio_CP_WS`

**Entrada por archivo** (alternativa a los flags de arriba):

| Flag | Descripción |
|---|---|
| `/INPUT_WS="persona.json"` | un solo JSON con la persona |
| `/INPUT_WS="input\*.json"` | con `*`, procesa TODOS los que hagan match, uno por uno |

Si no pasas ni `/INPUT_WS` ni ningún flag de persona, usa una persona de
ejemplo del sandbox y **fuerza `AMBIENTE_WS=dev`**, para no gastar una
consulta real por accidente.

**Salida:**

| Flag | Default | Descripción |
|---|---|---|
| `/OUTPUT_WS` | `output` | carpeta donde se guardan JSON/XML/PDF/evidencias |
| `/ArchivoSalida_WS` | `ALL` | `JSON`, `XML`, `PDF` o `ALL` — qué generar |
| `/XML_COMPACTO_WS` | `NO` | `SI` genera además el XML en una sola línea |
| `/PDF_MASCARA_WS` | `NO` | `SI` genera el PDF con identidad ficticia legible (para demos) en vez de los datos reales. Los datos financieros (cuentas, montos, otorgantes) nunca se enmascaran |

`PDF` siempre se arma a partir del XML: si también pediste XML como salida
(`ALL`), usa ese mismo archivo; si pediste solo `PDF`, arma uno temporal en
memoria y lo borra al terminar — no te deja un XML suelto que no pediste.

**Otros:**

| Flag | Default | Descripción |
|---|---|---|
| `/ENDPOINT_WS` | `reporte` | `reporte` o `securitytest` |
| `/PAUSAR_WS` | (auto) | `SI`/`NO`. Sin definir: pausa solo si es el `.exe` |

Todas las rutas relativas (`INPUT_WS`, `OUTPUT_WS`) se resuelven contra la
carpeta del `.exe`/script, nunca contra el directorio de trabajo actual.

### Ejemplos

```bash
REM Sandbox, persona de ejemplo (sin flags) -> genera JSON+XML+PDF (default ALL)
venv\Scripts\python.exe api_circulo.py

REM Producción, un archivo, solo el PDF
venv\Scripts\python.exe api_circulo.py /AMBIENTE_WS="prod" /API_KEY_WS="..." ^
    /USUARIO_WS="..." /PASS_WS="..." /LLAVE_PRIVADA_WS="..." ^
    /INPUT_WS="input\persona.json" /ArchivoSalida_WS="PDF"

REM Producción, varios archivos de un jalón, solo el XML
venv\Scripts\python.exe api_circulo.py /AMBIENTE_WS="prod" /API_KEY_WS="..." ^
    /USUARIO_WS="..." /PASS_WS="..." /LLAVE_PRIVADA_WS="..." ^
    /INPUT_WS="input\*.json" /ArchivoSalida_WS="XML"

REM Producción, solo la respuesta JSON cruda
venv\Scripts\python.exe api_circulo.py /AMBIENTE_WS="prod" /API_KEY_WS="..." ^
    /USUARIO_WS="..." /PASS_WS="..." /LLAVE_PRIVADA_WS="..." ^
    /INPUT_WS="input\persona.json" /ArchivoSalida_WS="JSON"

REM Producción, los tres archivos (JSON + XML + PDF)
venv\Scripts\python.exe api_circulo.py /AMBIENTE_WS="prod" /API_KEY_WS="..." ^
    /USUARIO_WS="..." /PASS_WS="..." /LLAVE_PRIVADA_WS="..." ^
    /INPUT_WS="input\persona.json" /ArchivoSalida_WS="ALL"
```

Prueba de firma ECDSA: `/ENDPOINT_WS="securitytest"` (requiere `API_KEY_WS` y `LLAVE_PRIVADA_WS`).

## 3. Generar el .exe

El `.exe` es standalone (no necesita Python instalado en la máquina destino).

```bash
venv\Scripts\pip install pyinstaller
build_exe.bat
```

Esto deja en `dist\`:

- **`ApiCirculo.exe`** — el ejecutable
- **`ApiCirculo.bat`** — copia de `ApiCirculo.bat.template` con ejemplos de
  invocación, lista para que rellenes tus credenciales y datos reales

`build_exe.bat` NO sobreescribe `dist\ApiCirculo.bat` si ya existe, para no
borrarte una copia que ya editaste con tus credenciales.

### Para distribuir a otra máquina

Copia junto al `.exe`:

```
ApiCirculo.exe
ApiCirculo.bat      (con tus credenciales y datos ya editados)
input\              (opcional, si usas /INPUT_WS)
```

El `.exe` siempre busca `input`/`output` **junto a sí mismo**, sin importar
desde dónde lo ejecutes (doble clic, acceso directo, cmd en otra carpeta) —
nunca según el directorio de trabajo actual.

### Importante sobre credenciales y git

`api_circulo.py` (el código fuente, versionado) trae los defaults de
credenciales **en blanco a propósito** — nunca debe llevar tu API key,
usuario, password o llave privada reales, porque ese archivo está en GitHub.

Los valores reales van **solo** en tu copia de `dist\ApiCirculo.bat`, que
está excluida del repo por `.gitignore` (junto con toda la carpeta `dist/`).
Nunca edites `ApiCirculo.bat.template` (la plantilla versionada) con datos
reales, y nunca subas manualmente una copia de `ApiCirculo.bat` con
credenciales a git.

### Reconstruir el .exe después de cambios

Vuelve a correr `build_exe.bat`. Se sobrescribe `dist\ApiCirculo.exe`
(tu `dist\ApiCirculo.bat` con credenciales reales queda intacto).
