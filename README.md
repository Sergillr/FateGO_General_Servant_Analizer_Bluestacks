# FGO Servant Analyzer (BlueStacks)

Analiza uno a uno los servants de tu cuenta de **Fate/Grand Order** en BlueStacks y
genera un **PDF** con nivel, NP, skills, append skills, bond, Fou, stats y un
diagnostico de lo que te falta por subir.

Funciona **desde el PC**, hablando con el emulador por **ADB**: captura la pantalla,
detecta en que menu esta el juego, lee los datos y navega por los menus. No modifica
el APK, no inyecta codigo y no lee memoria del juego.

---

## Por que PC + ADB y no un APK

| | App de PC + ADB | APK propio |
|---|---|---|
| Root | **No** | Si (o Accesibilidad) |
| FGO en emulador rooteado | Funciona | FGO suele bloquearlo |
| Captura | `adb exec-out screencap` | MediaProjection (permisos) |
| OCR / vision | OpenCV + Tesseract | ML Kit, limitado |
| Depurar | PNG en disco, iterar en segundos | Recompilar e instalar |
| Generar PDF | reportlab | Librerias PDF en Android |
| Superficie de deteccion | Baja (solo toca menus) | Alta (overlay/injection) |

Conclusion: la app de PC es mas rapida de desarrollar, mas fiable y menos invasiva.

---

## Requisitos

- Windows 10/11 y **Python 3.11+** (probado con 3.14)
- **BlueStacks 5** con FGO NA en ingles y resolucion **1920x1080**
- **ADB** activado en BlueStacks (ver abajo)
- **Tesseract** (recomendado): descarga el instalador de
  [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) y anade su carpeta al `PATH`.
  Sin Tesseract la app arranca igual, pero no puede leer numeros ni nombres.

## Instalacion

```powershell
python -m pip install -r requirements.txt
```

## Activar ADB en BlueStacks

1. BlueStacks > **Ajustes** (rueda dentada) > **Avanzado**.
2. Activa **Puente de depuracion Android (ADB)**.
3. Reinicia la instancia si te lo pide.
4. Comprueba:

```powershell
python run.py doctor
```

Deberia detectar `127.0.0.1:5555`, la resolucion 1920x1080 y poder capturar pantalla.
Si usas varias instancias, cambia `port` en `config.toml` (`5555`, `5565`, `5575`...).

---

## Prueba sin emulador

```powershell
python run.py demo --open
```

Genera `output/demo_report.pdf` con cuatro servants de ejemplo y datos reales de
Atlas Academy. Sirve para ver el resultado final antes de calibrar nada.

---

## Flujo real

### 1. Calibrar (solo la primera vez, o si cambia la UI)

Todo se basa en **anclas** (recortes unicos de cada pantalla) y **ROIs**
(zonas donde estan los numeros). La calibracion es visual: se abre una ventana,
arrastras un rectangulo y pulsas Enter.

```powershell
# Deja el juego en la lista de servants (Enhance > Servant)
python tools/calibrate.py anchor servant_list

# Entra en la ficha de cualquier servant
python tools/calibrate.py anchor servant_detail

# Zonas de lectura de la ficha
python tools/calibrate.py roi name
python tools/calibrate.py roi level
python tools/calibrate.py roi max_level
python tools/calibrate.py roi np_level
python tools/calibrate.py roi bond
python tools/calibrate.py roi fou_atk
python tools/calibrate.py roi fou_hp
python tools/calibrate.py roi skill_1
python tools/calibrate.py roi skill_2
python tools/calibrate.py roi skill_3
python tools/calibrate.py roi append_1
python tools/calibrate.py roi append_2
python tools/calibrate.py roi append_3
python tools/calibrate.py roi portrait

# Zona donde estan las tarjetas + numero de columnas/filas
python tools/calibrate.py grid
```

Los ROIs se guardan en `data/rois.json` y tienen prioridad sobre `config.toml`.
Puedes editarlos a mano: son `[x, y, ancho, alto]` en pixeles.

Verifica que las anclas funcionan:

```powershell
python run.py detect
```

### 2. Escanear el roster

**Modo manual (recomendado para empezar):** tu navegas con el raton, la app lee.

```powershell
python run.py scan --mode manual
```

Entra en la ficha de un servant en BlueStacks y pulsa **Enter** en la terminal.
Repite para cada servant. `s` para salir.

**Modo automatico:** requiere anclas y rejilla bien calibradas.

```powershell
python run.py scan --mode auto --limit 5 --dry-run   # simula, no toca nada
python run.py scan --mode auto
```

### 3. Generar el PDF

```powershell
python run.py report --open
```

---

## Comandos

| Comando | Que hace |
|---|---|
| `python run.py doctor` | Diagnostico de entorno, ADB, resolucion, OCR y calibracion |
| `python run.py shot` | Guarda una captura en `output/screenshots/` |
| `python run.py detect` | Dice que pantalla detecta y guarda una imagen anotada |
| `python run.py scan --mode manual` | Captura fichas pulsando Enter |
| `python run.py scan --mode auto` | Recorre la rejilla automaticamente |
| `python run.py report --open` | Genera y abre el PDF |
| `python run.py demo` | PDF de ejemplo sin emulador |
| `python run.py atlas --index` | Cachea el indice de servants de Atlas Academy |
| `python run.py atlas --name mash` | Busca servants por nombre |
| `python tools/calibrate.py ...` | Calibracion visual |

Opciones utiles de `scan`: `--limit N`, `--no-ocr`, `--no-atlas`,
`--keep-screens`, `--name "Nombre"` (si el OCR del nombre falla).

---

## Estructura

```
config.toml            configuracion (ADB, resolucion, rejilla, ROIs)
run.py                 CLI principal
fatego/
  adb.py               conexion, captura y toques por ADB
  capture.py           frames estables + hash perceptual
  vision.py            template matching, recortes, anotacion
  ocr.py               Tesseract (texto y numeros), degrada si falta
  screens.py           deteccion de pantalla por anclas
  models.py            ServantRecord
  store.py             roster persistente (data/roster.json)
  atlas.py             cliente de Atlas Academy con cache
  extract.py           lectura de la ficha de un servant
  navigator.py         modos de escaneo manual y automatico
  report.py            generacion del PDF
tools/calibrate.py     calibracion visual
assets/anchors/        anclas de pantalla (*.png)
data/                  roster, ROIs, rejilla, cache, retratos
output/                capturas y PDFs
```

---

## Como funciona

1. **Captura**: `adb exec-out screencap -p` cada pocos cientos de ms.
2. **Estabilizacion**: se espera a que dos frames consecutivos sean iguales para no
   leer animaciones a medias.
3. **Deteccion de pantalla**: template matching de las anclas.
4. **Lectura**: recortes ROI + Tesseract con whitelist de digitos.
5. **Enriquecido**: el nombre se cruza con el indice de Atlas Academy y se traen
   stats, clase, rareza, NP y nombres de skills.
6. **Persistencia**: `data/roster.json`; si repites el escaneo se actualiza, no se duplica.
7. **PDF**: portada con resumen, tabla por clase, inventario y una pagina por servant
   con barras de progreso y diagnostico.

### El truco para que sea fiable

No se hace OCR de toda la ficha. Solo se leen **8 numeros** (nivel, NP, bond, Fou,
3 skills y 3 append) y el nombre. Todo lo demas viene de Atlas Academy, que es una
API publica y gratuita. Asi el OCR tiene mucho menos margen de error.

---

## Limitaciones y avisos

- **ToS**: automatizar menus es botting segun los terminos de FGO y puede conllevar
  sancion. Este proyecto es de **solo lectura**: no farmea, no gasta AP y no toca
  combate. Usalo con delays humanos y bajo tu responsabilidad.
- **Duplicados**: el roster se indexa por servant, no por copia. Si tienes dos
  copias del mismo servant se conserva la de mayor nivel.
- **Cambios de UI**: un update del juego puede mover botones. Vuelve a calibrar.
- **Resolucion fija**: si cambias la resolucion de BlueStacks, recalibra todo.
- **OCR**: los numeros sobre fondos muy claros u oscuros pueden fallar; revisa
  `data/roster.json` y corrige a mano si hace falta.

## Roadmap

- [ ] Priorizacion automatica de skills (tier lists)
- [ ] Deteccion de CE equipada y command codes
- [ ] Historial de progreso (comparar escaneos)
- [ ] GUI de escritorio
- [ ] Exportar tambien a CSV/Excel
