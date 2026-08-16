# API Círculo de Crédito

Cliente para el API "Reporte de Crédito Consolidado + FICO® Score y PLD Check® -
Personas Físicas" de Círculo de Crédito. Lee la(s) persona(s) a consultar desde
JSON en `input/`, llama al API (sandbox o producción) y guarda la respuesta como
JSON crudo y como XML (formato clásico del buró) en `output/`.

## 1. Instalación (con Python)

Requiere Python 3.10+.

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

Copia tu `.env` (o créalo a partir de las variables de abajo) en esta misma
carpeta, junto a `api_circulo.py`. **Nunca lo subas a git** — ya está listado
en `.gitignore`.

### Variables de entorno (`.env`)

```
# Requerido para dev y prod
CDC_API_KEY=...

# Requerido solo para producción
CDC_PRIVATE_KEY_D=...
CDC_USERNAME=...
CDC_PASSWORD=...

# Opcional: verifica la firma que regresa Círculo de Crédito
CDC_PUBLIC_KEY_XY=...

# Opcional: dónde buscar el input y guardar el output.
# Relativas (a la carpeta del script/.exe) o absolutas.
CDC_INPUT_DIR=input
CDC_OUTPUT_DIR=output

# Opcional: 1 = la consola espera un ENTER antes de cerrarse (recomendado
# para el .exe con doble clic, así ves el resultado antes de que se cierre
# la ventana). 0 = no espera. Sin definir: el .exe espera solo, el script
# de Python no (la terminal ya se queda abierta).
CDC_PAUSAR_AL_TERMINAR=1
```

## 2. Uso

```bash
venv\Scripts\python.exe api_circulo.py
```

El script decide el ambiente solo, según lo que encuentre en `input/`:

- **`input/` vacía** → usa una persona de ejemplo del sandbox y consulta en
  **DEV**. Sirve para confirmar que todo sigue funcionando sin gastar una
  consulta real.
- **`input/` con uno o varios `.json`** → consulta CADA UNO en
  **PRODUCCIÓN**, y genera su propio `reporte_credito_prod_<archivo>_<folio>.json`
  y `.xml` en `output/`.

Para forzar el ambiente sin depender de lo que haya en `input/`:

```bash
venv\Scripts\python.exe api_circulo.py --env dev
venv\Scripts\python.exe api_circulo.py --env prod
```

Otras opciones útiles: `--input <archivo>` (consulta un solo JSON puntual),
`--output <carpeta>`, `--sin-xml`, `--xml-compacto`, `--endpoint securitytest`
(prueba tu firma ECDSA contra `/v1/securitytest`).

## 3. Generar el .exe

El `.exe` es standalone (no necesita Python instalado en la máquina destino);
solo necesita su propio `.env` al lado para saber con qué credenciales correr.

```bash
venv\Scripts\pip install pyinstaller
build_exe.bat
```

`build_exe.bat` corre PyInstaller con los flags correctos y deja el
ejecutable en `dist\ApiCirculo.exe`.

### Para distribuir el .exe a otra máquina

Copia junto al `.exe`:

- `.env` (con las credenciales de esa máquina/ambiente)
- opcionalmente `input\` y `output\` — si no existen, el .exe las crea solo

```
ApiCirculo.exe
.env
input\
output\
```

El `.exe` siempre busca su `.env` y sus carpetas `input`/`output` **junto a
sí mismo**, sin importar desde dónde lo ejecutes (doble clic, acceso directo,
cmd en otra carpeta) — nunca según el directorio de trabajo actual.

Corre igual que el script:

```bash
ApiCirculo.exe
ApiCirculo.exe --env dev
```

### Reconstruir el .exe después de cambios

Vuelve a correr `build_exe.bat`. Se sobrescribe `dist\ApiCirculo.exe`.
