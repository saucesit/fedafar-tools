@echo off
chcp 65001 > nul
cd /d "C:\Users\FEDAFAR\fedafar-tools"

REM Impacto de stock de VENTA INF — corre a las 18:00 (cierre del dia).
REM Lee las ventas/consumos no impactados, los agrega por producto y hace el
REM EGRESO en Genexus (FEFO). DRY_RUN=0 => SI confirma y descuenta stock real.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set DRY_RUN=0

echo === %date% %time% === >> impactar_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" ajuste_stock.py --impactar >> impactar_log.txt 2>&1
echo === Fin impacto === >> impactar_log.txt
echo. >> impactar_log.txt
