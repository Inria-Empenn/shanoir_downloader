# Shanoir Downloader

Shanoir downloader enables to download datasets, check that the downloaded DICOM content is correct, anonymize, archive and encrypt them.

See `python shanoir_downloader_check.py --help` for usage information.

## Install

It is advised to install the project in [a virtual environment](https://docs.python.org/3/tutorial/venv.html). 

[Install python with pip](https://www.python.org/downloads/) ; then use `pip install -r requirements.txt` to install python dependencies.

Optionally, rename the `.env.example` to `.env` and set the variables (`shanoir_password`, `gpg_recipient`) to your need.

**(Deprecated, now using pydicom)** To anonymize the dicoms, download or clone the latest version of [DicomAnonymizer](https://github.com/KitwareMedical/dicom-anonymizer/) (for example in this repository) and install it :
 - install wheel with `pip install wheel`
 - in the `dicom-anonymizer` folder, package the source files with `python ./setup.py bdist_wheel`
 - install `dicom-anonymizer` with `pip install ./dist/dicom_anonymizer-1.0.9-py2.py3-none-any.whl` (the version number might be higher)

## Example usage

`python shanoir_downloader_check.py -u username -d shanoir-ofsep.irisa.fr -ids path/to/datasets_to_download.csv -of path/to/output/folder/ -se -lf path/to/downloads.log`

## Password management

By default, shanoir_downloader will ask for the shanoir password. You can also set the `shanoir_password` environment variable to avoid entering your password every time. 
You can either use the `.env` file or run `export shanoir_password=XXX` (`set shanoir_password=XXX` on Windows) before executing the scripts.
