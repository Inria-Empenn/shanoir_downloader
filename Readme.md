# Shanoir Downloader

Shanoir downloader enables to download datasets, check that the downloaded DICOM content is correct, anonymize, archive and encrypt them.

See `python shanoir_downloader_check.py --help` for usage information.

Other tool to download and reorganize data as BIDS-like specification: https://gitlab.inria.fr/mgaubert/download-data-on-shanoir

## Install

It is advised to install the project in [a virtual environment](https://docs.python.org/3/tutorial/venv.html). 

[Install python with pip](https://www.python.org/downloads/) ; then use `pip install -r requirements.txt` to install python dependencies.

Optionally, rename the `.env.example` to `.env` and set the variables (`shanoir_password`, `gpg_recipient`) to your needs.

*See the "Installing DicomAnonymizer" section if you want to use DicomAnonymizer for the dicom anonymization instead of PyDicom.*

## Usage

There are two scripts to download datasets:
 - `shanoir_downloader.py` simply downloads datasets from a id, a list of ids, or directly from a [shanoir search as on the shanoir solr search page](https://shanoir.irisa.fr/shanoir-ng/solr-search),
 - `shanoir_downloader_check.py` is a more complete tool ; it enables to download datasets (from a csv or excel file containing a list of dataset ids, or directly from a [shanoir search as on the shanoir solr search page](https://shanoir.irisa.fr/shanoir-ng/solr-search)), verify their content, anonymize them and / or encrypt them.

`shanoir_downloader_check.py` creates two files in the output folder:
 - `downloaded_datasets.csv` records the successfully downloaded datasets,
 - `missing_datasets.csv` records the datasets which could not be downloaded.

With those two files, `shanoir_downloader_check.py` is able to resume a download session (the downloading can be interrupted any time, the tool will not redownload datasets which have already been downloaded).

See `python shanoir_downloader_check.py --help` for more information. 
You might want to skip the anonymization process and the encryption process with the `--skip_anonymization` and `--skip_encryption` arguments respectively (or `-sa` and `-se`).

### Example usage

To download datasets, verify the content of them, anonymize them and / or encrypt them you can use a command like:

`python shanoir_downloader_check.py -u username -d shanoir.irisa.fr -ids path/to/datasets_to_download.csv -of path/to/output/folder/ -se -lf path/to/downloads.log`

The `example_input_check.csv` file in this repository is an example input file (the format of the `datasets_to_download.csv` file should be the same).

You can also download datasets from a [SolR search](https://shanoir.irisa.fr/shanoir-ng/solr-search) as on the website:

`python shanoir_downloader.py -u amasson -d shanoir.irisa.fr -of /data/amasson/test/shanoir_test4 --search_text "FLAIR" -p 1 -s 2 `

where `--search_text` is the string you would use on [the SolR search page](https://shanoir.irisa.fr/shanoir-ng/solr-search) (for example `(subjectName:(CT* OR demo*) AND studyName:etude test) OR datasetName:*flair*`). More information on the info box of the SolR search page.

## Password management

By default, shanoir_downloader will ask for the shanoir password. You can also set the `shanoir_password` environment variable to avoid entering your password every time. 
You can either use the `.env` file or run `export shanoir_password=XXX` (`set shanoir_password=XXX` on Windows) before executing the scripts.

## Installing DicomAnonymizer

**(Deprecated, now using pydicom)**

To anonymize the dicoms, download or clone the latest version of [DicomAnonymizer](https://github.com/KitwareMedical/dicom-anonymizer/) (for example in this repository) and install it :
 - install wheel with `pip install wheel`
 - in the `dicom-anonymizer` folder, package the source files with `python ./setup.py bdist_wheel`
 - install `dicom-anonymizer` with `pip install ./dist/dicom_anonymizer-1.0.9-py2.py3-none-any.whl` (the version number might be higher)