@echo off
title SM MOIDEEN TRADERS Server
echo ========================================================
echo Starting SM MOIDEEN TRADERS Catering Management Server
echo Access the application at: http://127.0.0.1:8000
echo ========================================================
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
pause
