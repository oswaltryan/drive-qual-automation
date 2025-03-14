import os
from setuptools import setup, find_packages

# Read README for long description if available.
long_description = ''
if os.path.exists('README.md'):
    with open('README.md', encoding='utf-8') as f:
        long_description = f.read()

setup(
    name='win-usb-tool',
    version='0.1.0',
    description='Python tool to detect and display USB device information using libusb on Windows.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Ryan Oswalt',
    author_email='your.email@example.com',
    url='',  # Add a URL if you have a repo (e.g., GitHub)
    packages=find_packages(),
    python_requires='>=3.9',  # libusb requires Python 3.9+
    install_requires=[
        'pywin32==309',       # For WMI functionality
        'libusb==1.0.27.post4',  # For USB device enumeration
        'pygments==2.19.1', #suppress errors in term
    ],
    setup_requires=[
        'setuptools>=75.8.0',  # Build-time dependency for setup.py
    ],
    include_package_data=True,  # Kept in case other data files are added later
    entry_points={
        'console_scripts': [
            # Creates a globally available CLI command 'usb'
            'usb=windows_usb:main',
        ],
    },
    classifiers=[
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Operating System :: Microsoft :: Windows',
        'License :: OSI Approved :: MIT License',
    ],
)