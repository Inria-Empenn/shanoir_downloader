# Shanoir Downloader

Shanoir downloader enables to download datasets, check that the downloaded DICOM content is correct, anonymize, archive and encrypt them.

See `python shanoir_downloader_check.py --help` for usage information.

The scripts `convert_dicoms_to_niftis.py` and `create_previews.py` enable to convert dicoms to niftis and create png previews of the nifti files.

## Install

It is advised to install the project in [a virtual environment](https://docs.python.org/3/tutorial/venv.html). 

[Install python with pip](https://www.python.org/downloads/) ; then use `pip install -r requirements.txt` to install python dependencies.

Optionally, rename the `.env.example` to `.env` and set the variables (`shanoir_password`, `gpg_recipient`) to your needs.

*See the "Installing DicomAnonymizer" section if you want to use DicomAnonymizer for the dicom anonymization instead of PyDicom.*

## How to download Shanoir datasets ?

There are three scripts to download datasets from a Shanoir instance: 

1.`shanoir_downloader.py`:  downloads datasets from a id, a list of ids, or directly from a [shanoir search as on the shanoir solr search page](https://shanoir.irisa.fr/shanoir-ng/solr-search),

2.`shanoir_downloader_check.py`: a more complete tool ; it enables to download datasets (from a csv or excel file containing a list of dataset ids, or directly from a [shanoir search as on the shanoir solr search page](https://shanoir.irisa.fr/shanoir-ng/solr-search)), verify their content, anonymize them and / or encrypt them.

3.`shanoir2bids.py`: Download datasets from Shanoir in DICOM format and convert them into datalad datasets in BIDS format. The conversion is parameterised by a configuration file in `.json` format. 

### `shanoir_downloader_check.py`
 - `shanoir_downloader_check.py` creates two files in the output folder:
   - `downloaded_datasets.csv` records the successfully downloaded datasets,
   - `missing_datasets.csv` records the datasets which could not be downloaded.

With those two files, `shanoir_downloader_check.py` is able to resume a download session (the downloading can be interrupted any time, the tool will not redownload datasets which have already been downloaded).

Note that when downloading from a search text, the tool will only take the 50 first datasets by default (since `--page` is 0 and `--size` is 50 by default). Provide the arguments `--page` and `--size` to download the search results that you want (you can set `--size` to a big number if you want to download all search results).

Note that the timeout is 4 minutes by default (an timout error is thrown when the download takes more than 4 minutes or the server does not answer within 4 minutes). Use the `--timeout` argument to increase (or decrease) this duration (useful for big datasets).

Note that the `--expert_mode` argument enables to create a advanced search (for a specific subject or study with the format `subjectName:JohnDoe AND studyName:Study01`). Without the expert mode, shanoir will return all datasets containing one of the term in one of their field. See section [Search usage](#search-usage) below for more information.

See `python shanoir_downloader_check.py --help` for more information. 

You might want to skip the anonymization process and the encryption process with the `--skip_anonymization` and `--skip_encryption` arguments respectively (or `-sa` and `-se`).

### `shanoir2bids.py`

A `.json` configuration file must be provided to transform a Shanoir dataset into a BIDS dataset.
```
-----------------------------[.json configuration file information]-------------------------------
This file will tell the script what Shanoir datasets should be downloaded and how the data will be organised.
The dictionary in the json file must have four keys :

"study_name"  : str, the Shanoir study ID
"subjects"    : list of str, a list of Shanoir subjects
"data_to_bids": list of dict, each dictionary specifies datasets to download and BIDS format with the following keys :
    -> "datasetName": str, Shanoir name for the sequence to search
    -> "bidsDir"    : str, BIDS subdirectory sequence name (eg : "anat", "func" or "dwi", ...)
    -> "bidsName"   : str, BIDS sequence name (eg: "t1w", "acq-b0_dir-AP", ...)
```
Please refer to the [BIDS starter kit](https://bids-standard.github.io/bids-starter-kit/folders_and_files/files.html) 
for exhaustive templates of filenames. A BIDS compatible example is provided in the file `s2b_example_config.json`.

To download longitudinal data, a key `session` and a new entry `bidsSession` in `data_to_bids` dictionaries should be defined in the JSON configuration files. Of note, only one session can be downloaded at once. Then, the key `session` is just a string, not a list as for subjects.


### Download Examples 
#### Raw download 
To download datasets, verify the content of them, anonymize them and / or encrypt them you can use a command like:

`python shanoir_downloader_check.py -u username -d shanoir.irisa.fr -ids path/to/datasets_to_download.csv -of path/to/output/folder/ -se -lf path/to/downloads.log`

The `example_input_check.csv` file in this repository is an example input file (the format of the `datasets_to_download.csv` file should be the same).

#### Solr search download
You can also download datasets from a [SolR search](https://shanoir.irisa.fr/shanoir-ng/solr-search) as on the website:

`python shanoir_downloader.py -u amasson -d shanoir.irisa.fr -of /data/amasson/test/shanoir_test4 --search_text "FLAIR" -p 1 -s 2 `

where `--search_text` is the string you would use on [the SolR search page](https://shanoir.irisa.fr/shanoir-ng/solr-search) (for example `(subjectName:(CT* OR demo*) AND studyName:etude test) OR datasetName:*flair*`). More information on the info box of the SolR search page.

#### BIDS download
`python shanoir2bids.py -j s2b_example_config.json -of my_download_dir --outformat nifti` will download Shanoir datasets identified in the configuration file  saves them as DICOM and convert them  into a BIDS datalad dataset into `my_download_dir`.

## About Solr Search 

The `--search_text` and `--expert_mode` arguments work as on the [Shanoir search page](https://shanoir.irisa.fr/shanoir-ng/solr-search).

Without expert mode, shanoir will return all datasets containing one of the search term in one of their field.

With expert mode, shanoir will perform a Solr search enabling to retrieve specific datasets.

For example, the query `(subjectName:(CT* OR demo*) AND studyName:etude test) OR datasetName:*flair*` will return all datasets in the study "etude test" with a subject name that either starts with "CT" or starts with "demo", and any dataset which contain "flair" in its name.

Case is insentitive for values.

You can exclude terms with `- .`, for exemple `(*:* -datasetName:*localizer* AND -datasetName:*scout*)` will return all existing datasets except those which have "localizer" or "scout" in their name.

The present field names are : `studyName, datasetName, subjectName, datasetName, datasetStartDate, datasetEndDate, examinationComment, datasetType, datasetNature, sliceThickness, pixelBandwidth, magneticFieldStrength, tags`

For further information, see the [Solr official documentation](https://solr.apache.org/guide/6_6/the-standard-query-parser.html).

## Password management

By default, shanoir_downloader will ask for the shanoir password. You can also set the `shanoir_password` environment variable to avoid entering your password every time. 
You can either use the `.env` file or run `export shanoir_password=XXX` (`set shanoir_password=XXX` on Windows) before executing the scripts.

## Installing DicomAnonymizer

**(Deprecated, now using pydicom)**

To anonymize the dicoms, download or clone the latest version of [DicomAnonymizer](https://github.com/KitwareMedical/dicom-anonymizer/) (for example in this repository) and install it :
 - install wheel with `pip install wheel`
 - in the `dicom-anonymizer` folder, package the source files with `python ./setup.py bdist_wheel`
 - install `dicom-anonymizer` with `pip install ./dist/dicom_anonymizer-1.0.9-py2.py3-none-any.whl` (the version number might be higher)
