@echo off
chcp 65001 > nul
cd /d "C:\Users\FEDAFAR\fedafar-tools"

echo === LICITACIONES %date% %time% === >> sync_licitaciones_log.txt

echo [1/4] Scrapeando licitaciones SaltaCompra... >> sync_licitaciones_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" licitaciones_scraper.py >> sync_licitaciones_log.txt 2>&1

echo [2/4] Scrapeando solicitudes IPS... >> sync_licitaciones_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" ips_scraper.py >> sync_licitaciones_log.txt 2>&1

echo [3/4] Descargando pliegos SaltaCompra y extrayendo items... >> sync_licitaciones_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" sc_pliego_scraper.py >> sync_licitaciones_log.txt 2>&1

echo [4/4] Ingesta de licitaciones de Jujuy por email... >> sync_licitaciones_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" jujuy_mail_scraper.py >> sync_licitaciones_log.txt 2>&1

echo === Fin licitaciones === >> sync_licitaciones_log.txt
echo. >> sync_licitaciones_log.txt
