@echo off
chcp 65001 > nul
cd /d "C:\Users\FEDAFAR\fedafar-tools"

echo === %date% %time% === >> sync_log.txt

echo [1/5] Sincronizando stock... >> sync_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" sync_stock.py >> sync_log.txt 2>&1

echo [2/5] Sincronizando lista de precios... >> sync_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" sync_precios.py >> sync_log.txt 2>&1

echo [3/5] Sincronizando cuentas corrientes... >> sync_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" sync_cta_cte.py --todos >> sync_log.txt 2>&1

echo [4/5] Sincronizando items de facturas... >> sync_log.txt
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" sync_items.py >> sync_log.txt 2>&1

echo [5/5] Pusheando stock y precios actualizados a Render... >> sync_log.txt
git -C "C:\Users\FEDAFAR\fedafar-tools" add stock_data.json price_list.xlsx >> sync_log.txt 2>&1
git -C "C:\Users\FEDAFAR\fedafar-tools" diff --cached --quiet || git -C "C:\Users\FEDAFAR\fedafar-tools" commit -m "sync: stock y precios actualizados %date%" >> sync_log.txt 2>&1
git -C "C:\Users\FEDAFAR\fedafar-tools" push >> sync_log.txt 2>&1

echo === Fin sync === >> sync_log.txt
echo. >> sync_log.txt
