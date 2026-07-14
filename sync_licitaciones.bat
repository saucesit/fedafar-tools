@echo off
chcp 65001 > nul
cd /d "C:\Users\FEDAFAR\fedafar-tools"

echo === LICITACIONES %date% %time% === >> sync_licitaciones_log.txt

echo [1/5] Scrapeando licitaciones SaltaCompra... >> sync_licitaciones_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" licitaciones_scraper.py >> sync_licitaciones_log.txt 2>&1

echo [2/5] Scrapeando solicitudes IPS... >> sync_licitaciones_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" ips_scraper.py >> sync_licitaciones_log.txt 2>&1

echo [3/5] Descargando pliegos SaltaCompra y extrayendo items... >> sync_licitaciones_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" sc_pliego_scraper.py >> sync_licitaciones_log.txt 2>&1

echo [4/5] Ingesta de licitaciones por email (15 remitentes)... >> sync_licitaciones_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" email_scraper.py >> sync_licitaciones_log.txt 2>&1

echo [5/5] Limpieza de descartadas viejas (+15 dias)... >> sync_licitaciones_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" limpiar_descartadas.py >> sync_licitaciones_log.txt 2>&1

echo === Fin licitaciones === >> sync_licitaciones_log.txt
echo. >> sync_licitaciones_log.txt
