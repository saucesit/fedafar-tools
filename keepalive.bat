@echo off
chcp 65001 > nul
cd /d "C:\Users\FEDAFAR\fedafar-tools"
rem Mantiene despierto el servicio de Render (plan free lo duerme a los 15 min
rem sin uso, y el arranque en frio lo paga el primer cliente que entra).
rem Corre cada 10 minutos en horario comercial via tarea programada.
"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe" keepalive.py >> keepalive_log.txt 2>&1
