# Shanoir Downloader

Shanoir downloader enables to download datasets, check that the downloaded DICOM content is correct, anonymize, archive and encrypt them.

See `python shanoir_downloader_check.py --help` for usage information.

## Install

[Install python with pip](https://www.python.org/downloads/) ; then use `pip install -r requirements.txt` to install all python dependencies.

## Example usage

`python shanoir_downloader_check.py -u username -d shanoir-ofsep.irisa.fr -ids path/to/datasets_to_download.csv -of path/to/output/folder/ -se -lf path/to/downloads.log`

