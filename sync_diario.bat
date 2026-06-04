@echo off
chcp 65001 > nul
cd /d "C:\Users\FEDAFAR\fedafar-tools"

echo === %date% %time% === >> sync_log.txt

echo [1/3] Sincronizando stock... >> sync_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" sync_stock.py >> sync_log.txt 2>&1

echo [2/3] Sincronizando lista de precios... >> sync_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" sync_precios.py >> sync_log.txt 2>&1

echo [3/3] Sincronizando cuentas corrientes... >> sync_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" sync_cta_cte.py --todos >> sync_log.txt 2>&1

echo === Fin sync === >> sync_log.txt
echo. >> sync_log.txt
