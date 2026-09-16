@echo off
chcp 65001 > nul
cd /d "C:\Users\FEDAFAR\fedafar-tools"

REM Chequeo automatico: facturas/remitos de compra que no sumaron stock.
REM Ventana chica (5 dias) para que sea rapido y corra todos los dias sin
REM molestar. Revisa cada nueva factura casi apenas se carga, en vez de
REM enterarnos semanas despues.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo === %date% %time% === >> chequeo_facturas_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" auditoria_facturas_compra.py --dias 5 --quiet >> chequeo_facturas_log.txt 2>&1
echo === Fin chequeo === >> chequeo_facturas_log.txt
echo. >> chequeo_facturas_log.txt
