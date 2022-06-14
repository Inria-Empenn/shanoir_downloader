#!/usr/bin/env python3
"""
shanoir2bids.py is a script that allows to download a Shanoir dataset and organise it as a BIDS data structure.
                The script is made to run for every project given some information provided by the user into a ".json"
                configuration file. More information below.

Usage:
shanoir2bids.py -c <json_file> [-d <dl_dir>]

 Options:
    -h, --help         Show this message.
    --version          Print the version.

    -c, --json_file=<json_file>  Path to the .json configuration file specifying parameters for shanoir downloading.
    -d, --dl_dir=<dl_dir>        Path to the download directory. Where files will be saved.

-----------------------------[.json configuration file information]-------------------------------
This file will tell the script what Shanoir datasets should be downloaded and how the data will be organised.
The dictionary in the json file must have four keys :
"shanoir_id"  : str, your Shanoir login
"study_name"  : str, the Shanoir study ID
"subjects"    : list of str, a list of Shanoir subjects
"data_to_bids": list of dict, each dictionary specifies datasets to download and BIDS format with the following keys :
    -> "datasetName": str, Shanoir name for the sequence to search
    -> "bidsDir"    : str, BIDS subdirectory sequence name (eg : "anat", "func" or "dwi", ...)
    -> "bidsName"   : str, BIDS sequence name (eg: "t1w-mprage", "t2-hr", "cusp66-ap-b0", ...)
See example "s2b_example_config.json"
"""
# Script to download and BIDS-like organize data on Shanoir using "shanoir_downloader.py" developed by Arthur Masson
# @Author: Malo Gaubert <malo.gaubert@irisa.fr>, Quentin Duché <quentin.duche@irisa.fr>
# @Date: 14 Juin 2022
# todo : 1. dotenv.loadenv() (my script and shanoir_downloader.py) pour gerer le login shanoir
# todo : 2. Double configuration file (foutre dans le Readme.md)
# todo : 3. Abandonner docopt au profit de choses bcp plus optimales

import docopt
import os
import sys
import zipfile
import json
from pathlib import Path
import shanoir_downloader as sd
from os.path import join as opj, splitext as ops, exists as ope
from glob import glob
from time import time


def banner_msg(msg):
    """
    Print a message framed by a banner of "*" characters
    :param msg:
    """
    banner = '*' * (len(msg) + 6)
    print(banner + '\n* ', msg, ' *\n' + banner)


# Keys for json configuration file
K_JSON_SHANOIR_ID = 'shanoir_id'
K_JSON_STUDY_NAME = "study_name"
K_JSON_L_SUBJECTS = "subjects"
K_JSON_DATA_DICT = "data_to_bids"
LIST_KEYS_JSON = [K_JSON_SHANOIR_ID, K_JSON_STUDY_NAME, K_JSON_L_SUBJECTS, K_JSON_DATA_DICT]

# Define keys for data dictionary
K_BIDS_NAME = 'bidsName'
K_BIDS_DIR = 'bidsDir'
K_DS_NAME = 'datasetName'

# Define Extensions that are dealt so far by
NIFTI = '.nii'
NIIGZ = '.nii.gz'
JSON = '.json'
BVAL = '.bval'
BVEC = '.bvec'


class DownloadShanoirDatasetToBIDS:
    def __init__(self):
        self.subjects = None
        self.data_dict = None
        self.shanoir_id = None
        self.study_id = None
        self.dl_dir = None
        self.parser = None  # Shanoir Downloader Parser
        self.file_type = 'nifti'  # alternative 'dicom'

    def set_json_config_file(self, json_file):
        """
        Sets the configuration for the download through a json file
        :param json_file:
        :return:
        """
        f = open(json_file)
        data = json.load(f)
        # Check keys
        for k in data.keys():
            if not k in LIST_KEYS_JSON:
                print('Unknown key "{}" for data dictionary'.format(k))
        for k in LIST_KEYS_JSON:
            if not k in data.keys():
                sys.exit('Error, missing key "{}" in data dictionary'.format(k))
        # Set the fields for the instance of the class
        self.set_shanoir_id(shanoir_id=data[K_JSON_SHANOIR_ID])
        self.set_study_id(study_id=data[K_JSON_STUDY_NAME])
        self.set_subjects(subjects=data[K_JSON_L_SUBJECTS])
        self.set_data_dict(data_dict=data[K_JSON_DATA_DICT])

    def set_study_id(self, study_id):
        self.study_id = study_id

    def set_shanoir_id(self, shanoir_id):
        self.shanoir_id = shanoir_id

    def set_subjects(self, subjects):
        self.subjects = subjects

    def set_data_dict(self, data_dict):
        self.data_dict = data_dict

    def set_download_directory(self, dl_dir):
        self.dl_dir = dl_dir

    def configure_parser(self):
        """
        Configure the parser and the configuration of the shanoir_downloader
        """
        self.parser = sd.create_arg_parser()
        sd.add_common_arguments(self.parser)
        sd.add_configuration_arguments(self.parser)
        sd.add_search_arguments(self.parser)
        sd.add_ids_arguments(self.parser)

    def download_subject(self, subject_to_search):
        """

        :param subject_to_search:
        :return:
        """
        banner_msg("Downloading subject " + subject_to_search)

        # Loop on each sequence defined in the dictionary
        for seq in range(len(self.data_dict)):
            # Isolate elements that are called many times
            shanoir_seq_name = self.data_dict[seq][K_DS_NAME]  # Shanoir sequence name (OLD)
            bids_seq_subdir = self.data_dict[seq][K_BIDS_DIR]  # Sequence BIDS subdirectory name (NEW)
            bids_seq_name = self.data_dict[seq][K_BIDS_NAME]  # Sequence BIDS nickname (NEW)

            # Print message concerning the sequence that is being downloaded
            print('\t-', bids_seq_name, subject_to_search, '[' + str(seq + 1) + '/' + str(len(self.data_dict)) + ']')

            # Initialize the parser
            args = self.parser.parse_args(
                ['-u', self.shanoir_id,
                 '-d', 'shanoir.irisa.fr',
                 '-of', self.dl_dir,
                 '-em',
                 '-st', 'studyName:' + self.study_id +
                 ' AND datasetName:\"' + shanoir_seq_name +
                 '\" AND subjectName:' + subject_to_search,
                 '-s', '200',
                 '-f', self.file_type,
                 '-so', 'id,ASC',
                 '-t', '500'])  # Increase time out for heavy files

            config = sd.initialize(args)
            response = sd.solr_search(config, args)

            # From response, process the data
            # Print the number of items found and a list of these items
            if response.status_code == 200:
                print('\n SEQUENCE == ' + shanoir_seq_name + '\nnumber of items found: ' +
                      str(len(response.json()['content'])))

                for item in response.json()['content']:
                    print('Subject ID: ' + item['subjectName'] + ' - Dataset Name:' + item["datasetName"])

                # Download all by default (there was a user choice required before here)

                # Invoke shanoir_downloader to download all the data
                sd.download_search_results(config, args, response)

                # Organize in BIDS like specifications and rename files
                for item in response.json()['content']:
                    # ID of the subject (sub-*)
                    subject_id = 'sub-' + item['subjectName']
                    print('Processing ' + subject_id)

                    # Subject BIDS directory
                    subject_dir = opj(self.dl_dir, subject_id)
                    # Prepare BIDS naming
                    bids_data_dir = opj(subject_dir, bids_seq_subdir)
                    bids_data_basename = '_'.join([subject_id, bids_seq_name])

                    # Create temp directory to make sure the directory is empty before
                    tmp_dir = opj(self.dl_dir, 'temp_archive')
                    Path(tmp_dir).mkdir(parents=True, exist_ok=True)

                    # Create the directory of the subject
                    Path(subject_dir).mkdir(parents=True, exist_ok=True)
                    # And create the subdirectories (ignore if exists)
                    Path(bids_data_dir).mkdir(parents=True, exist_ok=True)

                    # Extract the downloaded archive
                    dl_archive = glob(opj(self.dl_dir, item['id'] + '*.zip'))[0]
                    with zipfile.ZipFile(dl_archive, 'r') as zip_ref:
                        zip_ref.extractall(tmp_dir)
                    # Get the list of files in the archive
                    list_unzipped_files = glob(opj(tmp_dir, '*'))

                    def seq_name(extension, run_num=0):
                        """
                        Returns a BIDS filename with appropriate basename and potential suffix
                        ext: extension ('.json' or '.nii.gz' or ...)
                        run_num : int, if 0 no suffix, else adds suffix '_run-1' or '_run-2' etc...
                        """
                        if run_num > 0:
                            basename = bids_data_basename + '_run-{0}{1}'.format(run_num, extension)
                        else:
                            basename = bids_data_basename + extension
                        return opj(bids_data_dir, basename)

                    # Rename every element in the list of files that was in the archive
                    for f in list_unzipped_files:  # Loop over files in the archive
                        filename, ext = ops(f)  # os.path.splitext to get extension
                        if ext == NIFTI:
                            # In special case of a nifti file, gzip it
                            cmd = "gzip " + r'"{}"'.format(f)
                            os.system(cmd)
                            # And update variables
                            f = filename + NIIGZ
                            ext = NIIGZ

                        # Let's process and rename the file
                        # Todo : try to make the difference between multiple sequences and multiple downloads
                        if ext in [NIIGZ, JSON, BVAL, BVEC]:
                            bids_filename = seq_name(extension=ext, run_num=0)
                            list_existing_f_ext = glob(opj(bids_data_dir, bids_data_basename + '*' + ext))
                            nf = len(list_existing_f_ext)
                            if nf == 0:
                                # No previously existing file : perform the renaming
                                os.rename(f, bids_filename)
                            elif nf == 1:
                                # One file already existed : give suffices
                                # the old file gets run-1 suffix
                                os.rename(bids_filename, seq_name(extension=ext, run_num=1))
                                # the new file gets run-2 suffix
                                os.rename(f, seq_name(extension=ext, run_num=2))
                            else:  # nf >= 2
                                # At least two files exist, do not touch previous but add the right suffix to new file
                                os.rename(f, seq_name(extension=ext, run_num=nf + 1))
                        else:
                            print('[BIDS format] The extension', ext,
                                  'is not yet dealt. Ask the authors of the script to make an effort.')

                    # Delete temporary directory
                    os.rmdir(tmp_dir)
                    os.remove(dl_archive)

            elif response.status_code == 204:
                banner_msg('ERROR : No file found!')
            else:
                banner_msg('ERROR : Returned by the request: status of the response = ' + response.status_code)

    def download(self):
        """
        Go download the required datasets
        :return:
        """
        self.configure_parser()  # Configure the shanoir_downloader parser
        for subject_to_search in self.subjects:
            t_start_subject = time()
            self.download_subject(subject_to_search=subject_to_search)
            duration = int((time() - t_start_subject) // 60)
            end_msg = 'Downloaded dataset for subject ' + subject_to_search + ' in ' + str(duration) + ' minutes'
            banner_msg(end_msg)


def main():
    # Read arguments from the command line
    args = docopt.docopt(__doc__)
    config_file = args['--json_file']  # Retrieve configuration filename
    download_dir = args['--dl_dir']  # Get download directory

    if not download_dir:
        from datetime import datetime
        # Set default download directory
        download_dir = "shanoir_2_bids_download_" + datetime.now().strftime("%Y_%m_%d__%Hh%Mm%Ss")
        print('A NEW DEFAULT directory is created as you did not provide a download directory (-d option)')
        print('\t :' + download_dir)
        os.mkdir(download_dir)
    else:
        if not ope(download_dir):
            Path(download_dir).mkdir(parents=True, exist_ok=True)

    stb = DownloadShanoirDatasetToBIDS()
    stb.set_json_config_file(json_file=config_file)
    stb.set_download_directory(dl_dir=download_dir)
    stb.download()


if __name__ == '__main__':
    main()
