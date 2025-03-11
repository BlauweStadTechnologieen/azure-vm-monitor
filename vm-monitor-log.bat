@echo

REM Activate the virtual environment
call "C:\Users\toddg\OneDrive\Documents\Utilities\azure-vm-monitor\.venv\Scripts\activate.bat"

REM Run the Python script
python "C:\Users\toddg\OneDrive\Documents\Utilities\azure-vm-monitor\vm-monitor-log.py"

REM Deactivate the virtual environment
deactivate
