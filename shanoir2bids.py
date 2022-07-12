#!/usr/bin/env python3
DESCRIPTION = """
shanoir2bids.py is a script that allows to download a Shanoir dataset and organise it as a BIDS data structure.
                The script is made to run for every project given some information provided by the user into a ".json"
                configuration file. More details regarding the configuration file in the Readme.md"""
# Script to download and BIDS-like organize data on Shanoir using "shanoir_downloader.py" developed by Arthur Masson
# @Author: Malo Gaubert <malo.gaubert@irisa.fr>, Quentin Duché <quentin.duche@irisa.fr>
# @Date: 24 Juin 2022
import os
import sys
import zipfile
import json
import shanoir_downloader
from dotenv import load_dotenv
from pathlib import Path
from os.path import join as opj, splitext as ops, exists as ope, dirname as opd
from glob import glob
from time import time
import datetime


# Load environment variables
load_dotenv(dotenv_path=opj(opd(__file__), '.env'))

def banner_msg(msg):
    """
    Print a message framed by a banner of "*" characters
    :param msg:
    """
    banner = '*' * (len(msg) + 6)
    print(banner + '\n* ', msg, ' *\n' + banner)


# Keys for json configuration file
K_JSON_STUDY_NAME = "study_name"
K_JSON_L_SUBJECTS = "subjects"
K_JSON_DATA_DICT = "data_to_bids"
LIST_KEYS_JSON = [K_JSON_STUDY_NAME, K_JSON_L_SUBJECTS, K_JSON_DATA_DICT]

# Define keys for data dictionary
K_BIDS_NAME = 'bidsName'
K_BIDS_DIR = 'bidsDir'
K_DS_NAME = 'datasetName'

# Define Extensions that are dealt so far by (#todo : think of other possible extensions ?)
NIFTI = '.nii'
NIIGZ = '.nii.gz'
JSON = '.json'
BVAL = '.bval'
BVEC = '.bvec'

# Shanoir parameters
SHANOIR_FILE_TYPE = 'nifti'  # alternative 'dicom'


def read_json_config_file(json_file):
    """
    Reads a json configuration file and checks whether mandatory keys for specifying the transformation from a
    Shanoir dataset to a BIDS dataset is present.
    :param json_file: str, path to a json configuration file
    :return:
    """
    f = open(json_file)
    data = json.load(f)
    # Check keys
    for key in data.keys():
        if not key in LIST_KEYS_JSON:
            print('Unknown key "{}" for data dictionary'.format(key))
    for key in LIST_KEYS_JSON:
        if not key in data.keys():
            sys.exit('Error, missing key "{}" in data dictionary'.format(key))
    # Set the fields for the instance of the class
    study_id = data[K_JSON_STUDY_NAME]
    subjects = data[K_JSON_L_SUBJECTS]
    data_dict = data[K_JSON_DATA_DICT]
    f.close()
    return study_id, subjects, data_dict


class DownloadShanoirDatasetToBIDS:
    """
    class that handles the downloading of shanoir data set and the reformatting as a BIDS data structure
    """
    def __init__(self):
        """
        Initialize the class instance
        """
        self.shanoir_subjects = None  # List of Shanoir subjects
        self.shanoir2bids_dict = None  # Dictionary specifying how to reformat data into BIDS structure
        self.shanoir_username = None  # Shanoir username
        self.shanoir_study_id = None  # Shanoir study ID
        self.dl_dir = None  # download directory, where data will be stored
        self.parser = None  # Shanoir Downloader Parser
        self.n_seq = 0  # Number of sequences in the shanoir2bids_dict
        self.log_fn = None

    def set_json_config_file(self, json_file):
        """
        Sets the configuration for the download through a json file
        :param json_file: str, path to the json_file
        """
        study_id, subjects, data_dict = read_json_config_file(json_file=json_file)
        self.set_shanoir_study_id(study_id=study_id)
        self.set_shanoir_subjects(subjects=subjects)
        self.set_shanoir2bids_dict(data_dict=data_dict)

    def set_shanoir_study_id(self, study_id):
        self.shanoir_study_id = study_id

    def set_shanoir_username(self, shanoir_username):
        self.shanoir_username = shanoir_username

    def set_shanoir_subjects(self, subjects):
        self.shanoir_subjects = subjects

    def set_shanoir2bids_dict(self, data_dict):
        self.shanoir2bids_dict = data_dict
        self.n_seq = len(self.shanoir2bids_dict)

    def set_download_directory(self, dl_dir):
        self.dl_dir = dl_dir
        self.set_log_filename()

    def set_log_filename(self):
        curr_time = datetime.datetime.now()
        basename = 'shanoir_downloader_{:04}{:02}{:02}_{:02}{:02}{:02}.log'.format(curr_time.year,
                                                                                   curr_time.month,
                                                                                   curr_time.day,
                                                                                   curr_time.hour,
                                                                                   curr_time.minute,
                                                                                   curr_time.second)
        self.log_fn = opj(self.dl_dir, basename)

    def configure_parser(self):
        """
        Configure the parser and the configuration of the shanoir_downloader
        """
        self.parser = shanoir_downloader.create_arg_parser()
        shanoir_downloader.add_common_arguments(self.parser)
        shanoir_downloader.add_configuration_arguments(self.parser)
        shanoir_downloader.add_search_arguments(self.parser)
        shanoir_downloader.add_ids_arguments(self.parser)

    def download_subject(self, subject_to_search):
        """
        For a single subject
        1. Downloads the Shanoir datasets
        2. Reorganises the Shanoir dataset as BIDS format as defined in the json configuration file provided by user
        :param subject_to_search:
        :return:
        """
        banner_msg("Downloading subject " + subject_to_search)

        # Open log file to write the steps of processing (downloading, renaming...)
        fp = open(self.log_fn, 'w')

        # Loop on each sequence defined in the dictionary
        for seq in range(self.n_seq):
            # Isolate elements that are called many times
            shanoir_seq_name = self.shanoir2bids_dict[seq][K_DS_NAME]  # Shanoir sequence name (OLD)
            bids_seq_subdir = self.shanoir2bids_dict[seq][K_BIDS_DIR]  # Sequence BIDS subdirectory name (NEW)
            bids_seq_name = self.shanoir2bids_dict[seq][K_BIDS_NAME]  # Sequence BIDS nickname (NEW)

            # Print message concerning the sequence that is being downloaded
            print('\t-', bids_seq_name, subject_to_search, '[' + str(seq + 1) + '/' + str(self.n_seq) + ']')

            # Initialize the parser
            search_txt = 'studyName:' + self.shanoir_study_id + ' AND datasetName:\"' + shanoir_seq_name + \
                         '\" AND subjectName:\"' + subject_to_search + '\"'
            args = self.parser.parse_args(
                ['-u', self.shanoir_username,
                 '-d', 'shanoir.irisa.fr',
                 '-of', self.dl_dir,
                 '-em',
                 '-st', search_txt,
                 '-s', '200',
                 '-f', SHANOIR_FILE_TYPE,
                 '-so', 'id,ASC',
                 '-t', '500'])  # Increase time out for heavy files

            config = shanoir_downloader.initialize(args)
            response = shanoir_downloader.solr_search(config, args)

            # From response, process the data
            # Print the number of items found and a list of these items
            if response.status_code == 200:

                # Invoke shanoir_downloader to download all the data
                shanoir_downloader.download_search_results(config, args, response)

                if len(response.json()['content']) == 0:
                    warn_msg = """WARNING ! The Shanoir request returned 0 result. Make sure the following search text returns 
a result on the website.
Search Text : "{}" """.format(search_txt)
                    print(warn_msg)
                    fp.write(warn_msg)
                else:
                    # Organize in BIDS like specifications and rename files
                    for item in response.json()['content']:
                        # ID of the subject (sub-*)
                        subject_id = 'sub-' + item['subjectName']

                        # Write the information on the data in the log file
                        fp.write('- datasetId = ' + str(item['datasetId']) + '\n')
                        fp.write('  -- studyName: ' + item['studyName'] + '\n')
                        fp.write('  -- subjectName: ' + item['subjectName'] + '\n')
                        fp.write('  -- datasetName: ' + item['datasetName'] + '\n')
                        fp.write('  -- examinationDate: ' + item['examinationDate'] + '\n')
                        fp.write('  >> Downloading archive OK\n')

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

                        fp.write("  >> Extraction of all files from archive '" + dl_archive + " into " + tmp_dir + "\n")

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

                        def check_duplicated_data(list_existing_file_json, file_to_add_json):
                            """
                            For a list of json file, check if a json file already exists meaning.
                            We check the flags AcquisitionTime and SequenceName to derive equality test.
                            :param list_existing_file_json: list of existing json files
                            :param file_to_add_json:
                            :return: True if one correspondance is found, False otherwise
                            """
                            f = open(file_to_add_json)
                            data = json.load(f)

                            for old_json in list_existing_file_json:
                                f_old = open(old_json)
                                data_old = json.load(f_old)

                                if (data['AcquisitionTime'] == data_old['AcquisitionTime']) & (data['SequenceName'] == data_old['SequenceName']):
                                    # If one of the json file has the same AcquisitionTime and SequenceName, then it is a duplicated file
                                    f_old.close()
                                    f.close()
                                    return True

                            f.close()
                            return False

                        # Reorder list_unzipped_files to have json file first; otherwise, nii file will be ordered and then, json will be scanned.
                        # if duplicated, json won't be copied while nii is already ordered
                        tempo_fn, tempo_ext = ops(list_unzipped_files[0])
                        if tempo_ext != JSON:
                            for idx_fn in range(1, len(list_unzipped_files)):
                                tempo_fn, tempo_ext = ops(list_unzipped_files[idx_fn])
                                if tempo_ext == JSON:
                                    temp = list_unzipped_files[0]
                                    list_unzipped_files[0] = list_unzipped_files[idx_fn]
                                    list_unzipped_files[idx_fn] = temp
                                    idx_fn = len(list_unzipped_files) + 10

                        # By default, the new data to order is not a duplication
                        duplicated_data = False

                        # Rename every element in the list of files that was in the archive
                        for f in list_unzipped_files:  # Loop over files in the archive
                            fp.write("  >> Processing file '" + f + "'\n")

                            filename, ext = ops(f)  # os.path.splitext to get extension
                            if ext == NIFTI:
                                # In special case of a nifti file, gzip it
                                cmd = "gzip " + r'"{}"'.format(f)  # todo : use a lib
                                os.system(cmd)
                                # And update variables. Filename as now '.nii.gz' extension
                                f = filename + NIIGZ
                                ext = NIIGZ
                            if ext == '.gz':
                                # os.path.splitext returns (filename.nii, '.gz') instead of (filename, '.nii.gz')
                                ext = NIIGZ

                            # Let's process and rename the file
                            # Compare the contents of the associated json file between previous and new file "AcquisitionTime"
                            list_existing_f_ext = glob(opj(bids_data_dir, bids_data_basename + '*' + ext))
                            nf = len(list_existing_f_ext)

                            # if files with same bids_data_basename are present in subjects directory, check json files
                            if (nf > 0) & (not duplicated_data):
                                for filename_tempo in list_unzipped_files:
                                    fn_tempo, ext_tempo = ops(filename_tempo)
                                    if (ext_tempo == JSON) & (ext == JSON):
                                        list_existing_f_ext_json = glob(opj(bids_data_dir, bids_data_basename + '*json'))
                                        duplicated_data = check_duplicated_data(list_existing_f_ext_json, filename_tempo)

                            if duplicated_data:
                                fp.write(" \n/!\ File already present in the subject's directory. Data will not be used.\n\n")

                            if ext in [NIIGZ, JSON, BVAL, BVEC] and not duplicated_data:
                                bids_filename = seq_name(extension=ext, run_num=0)
                                if nf == 0:
                                    # No previously existing file : perform the renaming
                                    os.rename(f, bids_filename)
                                    fp.write("    >> Renaming to '" + bids_filename + "'\n")
                                elif nf == 1:
                                    fp.write('   /!\ One similar sequence found ! \n')
                                    # One file already existed : give suffices
                                    # the old file gets run-1 suffix
                                    os.rename(bids_filename, seq_name(extension=ext, run_num=1))
                                    fp.write("    >> Renaming '" + bids_filename + "' to '" + seq_name(extension=ext, run_num=1) + "'\n")
                                    # the new file gets run-2 suffix
                                    os.rename(f, seq_name(extension=ext, run_num=2))
                                    fp.write("    >> Renaming to '" + seq_name(extension=ext, run_num=2) + "'\n")
                                else:  # nf >= 2
                                    # At least two files exist, do not touch previous but add the right suffix to new file
                                    os.rename(f, seq_name(extension=ext, run_num=nf + 1))
                                    fp.write("    >> Renaming to '" + seq_name(extension=ext, run_num=nf + 1) + "'\n")
                            else:
                                print('[BIDS format] The extension', ext,
                                      'is not yet dealt. Ask the authors of the script to make an effort.')
                                fp.write('    >> [BIDS format] The extension' + ext + 'is not yet dealt. Ask the authors of the script to make an effort.\n')

                        # Delete temporary directory (remove files before if duplicated)
                        if duplicated_data:
                            for f in list_unzipped_files:
                                filename, ext = ops(f)
                                if ext == '.nii':
                                    if os.path.exists(f + '.gz'): os.remove(f + '.gz')
                                else:
                                    if os.path.exists(f): os.remove(f)
                            # Alternative to clear temporary disk os.remove( tmp_dir + '/*json') (loop on table with all data type)
                        os.rmdir(tmp_dir)
                        fp.write('  >> Deleting temporary dir ' + tmp_dir + '\n')
                        os.remove(dl_archive)
                        fp.write('  >> Deleting downloaded archive ' + dl_archive + '\n\n\n')

            elif response.status_code == 204:
                banner_msg('ERROR : No file found!')
                fp.write('  >> ERROR : No file found!\n')
            else:
                banner_msg('ERROR : Returned by the request: status of the response = ' + response.status_code)
                fp.write('  >> ERROR : Returned by the request: status of the response = ' + str(response.status_code) + '\n')

    def download(self):
        """
        Loop over the Shanoir subjects and go download the required datasets
        :return:
        """
        self.configure_parser()  # Configure the shanoir_downloader parser
        for subject_to_search in self.shanoir_subjects:
            t_start_subject = time()
            self.download_subject(subject_to_search=subject_to_search)
            dur_min = int((time() - t_start_subject) // 60)
            dur_sec = int((time() - t_start_subject) % 60)
            end_msg = 'Downloaded dataset for subject ' + subject_to_search + ' in {}m{}s'.format(dur_min, dur_sec)
            banner_msg(end_msg)


def main():
    # Parse argument for the script
    parser = shanoir_downloader.create_arg_parser(description=DESCRIPTION)
    # Use username and output folder arguments from shanoir_downloader
    shanoir_downloader.add_username_argument(parser)
    shanoir_downloader.add_output_folder_argument(parser, required=False)
    # Add the argument for the configuration file
    parser.add_argument('-j', '--config_file', required=True, help='Path to the .json configuration file specifying parameters for shanoir downloading.')
    # Parse arguments
    args = parser.parse_args()

    # Read and check the content of the configuration file
    shanoir_study_id, shanoir_subjects, shanoir_data2bids_dict = read_json_config_file(args.config_file)

    # Check existence of output folder and create a default output folder otherwise
    if not args.output_folder:
        from datetime import datetime
        # Set default download directory
        dt = datetime.now().strftime("%Y_%m_%d__%Hh%Mm%Ss")
        output_folder = "shanoir2bids_download_" + shanoir_study_id + '_' + dt
        print('A NEW DEFAULT directory is created as you did not provide a download directory (-d option)\n\t' + output_folder)
    else:
        output_folder = args.output_folder

    # Create directory if it does not exist
    if not ope(output_folder):
        Path(output_folder).mkdir(parents=True, exist_ok=True)

    stb = DownloadShanoirDatasetToBIDS()
    stb.set_shanoir_username(args.username)
    stb.set_shanoir_study_id(study_id=shanoir_study_id)
    stb.set_shanoir_subjects(subjects=shanoir_subjects)
    stb.set_shanoir2bids_dict(data_dict=shanoir_data2bids_dict)
    stb.set_download_directory(dl_dir=output_folder)
    stb.set_log_filename()
    stb.download()


if __name__ == '__main__':
    main()
