# Anclas de pantalla

Cada `*.png` de esta carpeta es un recorte unico de una pantalla del juego.
El nombre del archivo es el nombre de la pantalla:

- `servant_list.png` -> pantalla de lista de servants
- `servant_detail.png` -> ficha de un servant

Crealas con:

```powershell
python tools/calibrate.py anchor servant_list
python tools/calibrate.py anchor servant_detail
```

Consejos:

- Elige una zona **fija y con detalle** (un icono, un header, una esquina del marco).
- Evita zonas con texto variable, arte del servant o animaciones.
- Tamano recomendado: entre 60x40 y 300x150 px.
- Si un ancla falla, baja su umbral en `anchors.json`:

```json
{
  "servant_list": { "threshold": 0.75 }
}
```
