@echo off
cd /d "C:\Users\FEDAFAR\fedafar-tools"
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" sync_cta_cte.py --todos >> "C:\Users\FEDAFAR\fedafar-tools\sync_log.txt" 2>&1
