# 1. Optionally Create a virtual environment with Python 3.12
python3.12 -m venv venv
# Activate the virtual environment:
# Linux/macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# 2. Install dependencies (exact versions locked in requirements.txt)
pip install -r requirements.txt

# 3. Install deps from local wheel files (offline)
pip install --no-index --find-links=wheels -r requirements.txt

# 4. Install as a module for global access

pip install . 

# 5 Install globally as a module offline

pip install --no-index --find-links=wheels .


# 5 Invoke anywhere 

usb