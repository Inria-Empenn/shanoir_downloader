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
import shutil
import shanoir_downloader
from dotenv import load_dotenv
from pathlib import Path
from os.path import join as opj, splitext as ops, exists as ope, dirname as opd
from glob import glob
from time import time
import datetime
from dateutil import parser


# TODO list
# 1) Ajouter option pour conserver/supprimer le dicom folder apres conversion dcm2niix

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
K_JSON_SESSION = "session"
K_JSON_DATA_DICT = "data_to_bids"
K_JSON_FIND_AND_REPLACE = "find_and_replace_subject"
K_DCM2NIIX_PATH = "dcm2niix"
K_DCM2NIIX_OPTS = "dcm2niix_options"
K_FIND = 'find'
K_REPLACE = 'replace'
K_JSON_DATE_FROM = 'date_from'  # examinationDate:[2014-03-21T00:00:00Z TO 2014-03-22T00:00:00Z]
K_JSON_DATE_TO = 'date_to'      # examinationDate:[2014-03-21T00:00:00Z TO 2014-03-22T00:00:00Z]
LIST_MANDATORY_KEYS_JSON = [K_JSON_STUDY_NAME, K_JSON_L_SUBJECTS, K_JSON_DATA_DICT]
LIST_AUTHORIZED_KEYS_JSON = LIST_MANDATORY_KEYS_JSON + [K_DCM2NIIX_PATH, K_DCM2NIIX_OPTS, K_JSON_DATE_FROM, K_JSON_DATE_TO, K_JSON_SESSION]

# Define keys for data dictionary
K_BIDS_NAME = 'bidsName'
K_BIDS_DIR = 'bidsDir'
K_BIDS_SES = 'bidsSession'
K_DS_NAME = 'datasetName'

# Define Extensions that are dealt so far by (#todo : think of other possible extensions ?)
NIFTI = '.nii'
NIIGZ = '.nii.gz'
JSON = '.json'
BVAL = '.bval'
BVEC = '.bvec'
DCM = '.dcm'

# Shanoir parameters
SHANOIR_FILE_TYPE_NIFTI = 'nifti'
SHANOIR_FILE_TYPE_DICOM = 'dicom'
DEFAULT_SHANOIR_FILE_TYPE = SHANOIR_FILE_TYPE_NIFTI

# Define error and warning messages when call to dcm2niix is not well configured in the json file
DCM2NIIX_ERR_MSG = """ERROR !!
Conversion from DICOM to nifti can not be performed.
Please provide path to your favorite dcm2niix version in your Shanoir2BIDS .json configuration file.
Add key "{key}" with the absolute path to dcm2niix version to the following file : """
DCM2NIIX_WARN_MSG = """WARNING. You did not provide any option to the dcm2niix call.
If you want to do so, add key "{key}"  to you Shanoir2BIDS configuration file :"""


def check_date_format(date_to_format):
    # TRUE FORMAT should be: date_format = 'Y-m-dTH:M:SZ'
    try:
        parser.parse(date_to_format)
    # If the date validation goes wrong
    except ValueError:
        print("Incorrect data format, should be YYYY-MM-DDTHH:MM:SSZ (for example: 2020-02-19T00:00:00Z)")

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
        if not key in LIST_AUTHORIZED_KEYS_JSON:
            print('Unknown key "{}" for data dictionary'.format(key))
    for key in LIST_MANDATORY_KEYS_JSON:
        if not key in data.keys():
            sys.exit('Error, missing key "{}" in data dictionary'.format(key))

    # Sets the mandatory fields for the instance of the class
    study_id = data[K_JSON_STUDY_NAME]
    subjects = data[K_JSON_L_SUBJECTS]
    data_dict = data[K_JSON_DATA_DICT]

    # Default non-mandatory options
    list_fars = []
    dcm2niix_path = None
    dcm2niix_opts = None
    date_from = '*'
    date_to = '*'
    session_id = '*'

    if K_JSON_FIND_AND_REPLACE in data.keys():
        list_fars = data[K_JSON_FIND_AND_REPLACE]
    if K_DCM2NIIX_PATH in data.keys():
        dcm2niix_path = data[K_DCM2NIIX_PATH]
    if K_DCM2NIIX_OPTS in data.keys():
        dcm2niix_opts = data[K_DCM2NIIX_OPTS]
    if K_JSON_DATE_FROM in data.keys():
        if data[K_JSON_DATE_FROM] == '':
            data_from = '*'
        else:
            date_from = data[K_JSON_DATE_FROM]
            check_date_format(date_from)
    if K_JSON_DATE_TO in data.keys():
        if data[K_JSON_DATE_TO] == '':
            data_to = '*'
        else:
            date_to = data[K_JSON_DATE_TO]
            check_date_format(date_to)
    if K_JSON_SESSION in data.keys():
        session_id = data[K_JSON_SESSION]


    # Close json file and return
    f.close()
    return study_id, subjects, session_id, data_dict, list_fars, dcm2niix_path, dcm2niix_opts, date_from, date_to


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
        self.shanoir_session_id = None  # Shanoir study ID
        self.shanoir_file_type = DEFAULT_SHANOIR_FILE_TYPE  # Default download type (nifti/dicom)
        self.json_config_file = None
        self.list_fars = []  # List of substrings to edit in subjects names
        self.dl_dir = None  # download directory, where data will be stored
        self.parser = None  # Shanoir Downloader Parser
        self.n_seq = 0  # Number of sequences in the shanoir2bids_dict
        self.log_fn = None
        self.dcm2niix_path = None  # Path to the dcm2niix the user wants to use
        self.dcm2niix_opts = None  # Options to add to the dcm2niix call
        self.date_from = None
        self.date_to = None
        self.longitudinal = False
        self.to_automri_format = False # Special filenames for automri (close to BIDS format)
        self.add_sns = False # Add series number suffix to filename

    def set_json_config_file(self, json_file):
        """
        Sets the configuration for the download through a json file
        :param json_file: str, path to the json_file
        """
        self.json_config_file = json_file
        study_id, subjects, session_id, data_dict, list_fars, dcm2niix_path, dcm2niix_opts, date_from, date_to = read_json_config_file(json_file=json_file)
        self.set_shanoir_study_id(study_id=study_id)
        self.set_shanoir_subjects(subjects=subjects)
        self.set_shanoir_session_id(session_id=session_id)
        self.set_shanoir2bids_dict(data_dict=data_dict)
        self.set_shanoir_list_find_and_replace(list_fars=list_fars)
        self.set_dcm2niix_parameters(dcm2niix_path=dcm2niix_path, dcm2niix_opts=dcm2niix_opts)
        self.set_date_from(date_from=date_from)
        self.set_date_to(date_to=date_to)

    def set_shanoir_file_type(self, shanoir_file_type):
        if shanoir_file_type in [SHANOIR_FILE_TYPE_DICOM, SHANOIR_FILE_TYPE_NIFTI]:
            self.shanoir_file_type = shanoir_file_type
        else:
            sys.exit('Unknown shanoir file type {}'.format(shanoir_file_type))

    def set_shanoir_study_id(self, study_id):
        self.shanoir_study_id = study_id

    def set_shanoir_username(self, shanoir_username):
        self.shanoir_username = shanoir_username

    def set_shanoir_domaine(self, shanoir_domaine): 
        self.shanoir_domaine = shanoir_domaine

    def set_shanoir_subjects(self, subjects):
        self.shanoir_subjects = subjects

    def set_shanoir_session_id(self, session_id):
        self.shanoir_session_id = session_id

    def set_shanoir_list_find_and_replace(self, list_fars):
        self.list_fars = list_fars

    def set_dcm2niix_parameters(self, dcm2niix_path, dcm2niix_opts):
        self.dcm2niix_path = dcm2niix_path
        self.dcm2niix_opts = dcm2niix_opts

    def set_date_from(self, date_from):
        self.date_from = date_from

    def set_date_to(self, date_to):
        self.date_to = date_to

    def set_shanoir2bids_dict(self, data_dict):
        self.shanoir2bids_dict = data_dict
        self.n_seq = len(self.shanoir2bids_dict)

    def set_download_directory(self, dl_dir):
        if dl_dir is None:
            # Create a default download directory
            dt = datetime.datetime.now().strftime("%Y_%m_%d_at_%Hh%Mm%Ss")
            self.dl_dir = '_'.join(["shanoir2bids", "download", self.shanoir_study_id, dt])
            print('A NEW DEFAULT directory is created as you did not provide a download directory (-of option)\n\t' + self.dl_dir)
        else:
            self.dl_dir = dl_dir
        # Create directory if it does not exist
        if not ope(self.dl_dir):
            Path(self.dl_dir).mkdir(parents=True, exist_ok=True)
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

    def toggle_longitudinal_version(self):
        self.longitudinal = True

    def switch_to_automri_format(self):
        self.to_automri_format = True

    def add_series_number_suffix(self):
        self.add_sns = True

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
        fp = open(self.log_fn, 'a')

        # Loop on each sequence defined in the dictionary
        for seq in range(self.n_seq):
            # Isolate elements that are called many times
            shanoir_seq_name = self.shanoir2bids_dict[seq][K_DS_NAME]  # Shanoir sequence name (OLD)
            bids_seq_subdir = self.shanoir2bids_dict[seq][K_BIDS_DIR]  # Sequence BIDS subdirectory name (NEW)
            bids_seq_name = self.shanoir2bids_dict[seq][K_BIDS_NAME]  # Sequence BIDS nickname (NEW)
            if self.longitudinal:
                bids_seq_session = self.shanoir2bids_dict[seq][K_BIDS_SES]  # Sequence BIDS nickname (NEW)

            # Print message concerning the sequence that is being downloaded
            print('\t-', bids_seq_name, subject_to_search, '[' + str(seq + 1) + '/' + str(self.n_seq) + ']')

            # Initialize the parser
            search_txt = 'studyName:' + self.shanoir_study_id.replace(" ", "?") + \
                        ' AND datasetName:' + shanoir_seq_name.replace(" ", "?")  + \
                        ' AND subjectName:' + subject_to_search.replace(" ", "?") + \
                        ' AND examinationComment:' + self.shanoir_session_id.replace(" ", "*") + \
                        ' AND examinationDate:[' + self.date_from + ' TO ' + self.date_to + ']'

            args = self.parser.parse_args(
                ['-u', self.shanoir_username,
                 '-d', self.shanoir_domaine,
                 '-of', self.dl_dir,
                 '-em',
                 '-st', search_txt,
                 '-s', '200',
                 '-f', self.shanoir_file_type,
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
Search Text : "{}" \n""".format(search_txt)
                    print(warn_msg)
                    fp.write(warn_msg)
                else:
                    # Organize in BIDS like specifications and rename files
                    for item in response.json()['content']:
                        # Define subject_id
                        su_id = item['subjectName']
                        # If the user has defined a list of edits to subject names... then do the find and replace
                        for far in self.list_fars:
                            su_id = su_id.replace(far[K_FIND], far[K_REPLACE])

                        # ID of the subject (sub-*)
                        subject_id = 'sub-' + su_id

                        # Write the information on the data in the log file
                        fp.write('- datasetId = ' + str(item['datasetId']) + '\n')
                        fp.write('  -- studyName: ' + item['studyName'] + '\n')
                        fp.write('  -- subjectName: ' + item['subjectName'] + '\n')
                        fp.write('  -- session: ' + item['examinationComment'] + '\n')
                        fp.write('  -- datasetName: ' + item['datasetName'] + '\n')
                        fp.write('  -- examinationDate: ' + item['examinationDate'] + '\n')
                        fp.write('  >> Downloading archive OK\n')

                        # Subject BIDS directory
                        if self.to_automri_format:
                            subject_dir = opj(self.dl_dir, 'su_' + su_id)
                        else:
                            subject_dir = opj(self.dl_dir, subject_id)

                        # Prepare BIDS naming
                        if self.longitudinal:
                            # Insert a session sub-directory
                            bids_data_dir = opj(subject_dir, bids_seq_session, bids_seq_subdir)
                            if self.to_automri_format:
                                bids_data_basename = '_'.join([bids_seq_session, bids_seq_name])
                            else:
                                bids_data_basename = '_'.join([subject_id, bids_seq_session, bids_seq_name])
                        else:
                            bids_data_dir = opj(subject_dir, bids_seq_subdir)
                            if self.to_automri_format:
                                bids_data_basename = '_'.join([bids_seq_name, su_id])
                            else:
                                bids_data_basename = '_'.join([subject_id, bids_seq_name])

                        # Create temp directory to make sure the directory is empty before
                        tmp_dir = opj(self.dl_dir, 'temp_archive')
                        Path(tmp_dir).mkdir(parents=True, exist_ok=True)

                        # Create the directory of the subject
                        Path(subject_dir).mkdir(parents=True, exist_ok=True)
                        # And create the subdirectories (ignore if exists)
                        Path(bids_data_dir).mkdir(parents=True, exist_ok=True)

                        # Extract the downloaded archive
                        dl_archive = glob(opj(self.dl_dir, '*' + item['id'] + '*.zip'))[0]
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

                        if self.shanoir_file_type == SHANOIR_FILE_TYPE_DICOM:
                            # Process the DICOM file by calling dcm2niix
                            if not self.dcm2niix_path:
                                err_msg = "msg\n- {file}""".format(msg=DCM2NIIX_ERR_MSG, file=self.json_config_file)
                                sys.exit(err_msg)
                            if not self.dcm2niix_opts:
                                warn_msg = "msg\n- {file}""".format(msg=DCM2NIIX_WARN_MSG, file=self.json_config_file)
                                print(warn_msg)

                            dcm_files = glob(opj(tmp_dir, '*' + DCM))
                            # Define dcm2niix options
                            options = ' {opts} -f {basename} -o {out}'.format(opts=self.dcm2niix_opts, basename=bids_data_basename, out=tmp_dir)
                            cmd = self.dcm2niix_path + options + ' ' + dcm_files[0]

                            # Retrieve dcm2niix output and save it to file
                            info_dcm = os.popen(cmd)
                            info_dcm = info_dcm.read()
                            info_dcm = info_dcm.split('\n')
                            fp.write('[dcm2niix] ' + '\n[dcm2niix] '.join(info_dcm[2:-1]) + '\n')

                            # Remove temporary DICOM files
                            for dcm_file in dcm_files:
                                os.remove(dcm_file)

                            # After the command, the user should have a nifti and json file and extra files
                            list_unzipped_files = glob(opj(tmp_dir, '*'))

                            # Now the DICOM part of the script should be in the same stage as the NIFTI part of the script which is below

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
                                    break

                        # By default, the new data to order is not a duplication
                        duplicated_data = False

                        if self.to_automri_format and self.add_sns:
                                # Update bids_data_basename with Series Number information
                                for filename in list_unzipped_files:
                                    if filename.endswith(JSON):
                                        f_temp = open(filename)
                                        json_dataset = json.load(f_temp)
                                        series_number_suffix = str(json_dataset['SeriesNumber'])
                                        bids_data_basename = '_'.join([bids_seq_name, su_id, series_number_suffix])

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
                                list_unzipped_files = []

                            if ext in [NIIGZ, JSON, BVAL, BVEC]:
                                if not duplicated_data:
                                    bids_filename = seq_name(extension=ext, run_num=0)
                                    if nf == 0:
                                        # No previously existing file : perform the renaming
                                        os.rename(f, bids_filename)
                                        fp.write("    >> Renaming to '" + bids_filename + "'\n")
                                    elif nf == 1:
                                        fp.write('   /!\ One similar filename found ! \n')
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
                                print('[BIDS format] The extension', ext, 'is not yet dealt. Ask the authors of the script to make an effort.')
                                fp.write('    >> [BIDS format] The extension' + ext + 'is not yet dealt. Ask the authors of the script to make an effort.\n')

                        # Delete temporary directory (remove files before if duplicated)
                        if duplicated_data:
                            for f in list_unzipped_files:
                                filename, ext = ops(f)
                                if ext == NIFTI:
                                    if os.path.exists(f + '.gz'): os.remove(f + '.gz')
                                else:
                                    if os.path.exists(f): os.remove(f)
                        shutil.rmtree(tmp_dir)
                        fp.write('  >> Deleting temporary dir ' + tmp_dir + '\n')
                        os.remove(dl_archive)
                        fp.write('  >> Deleting downloaded archive ' + dl_archive + '\n\n\n')
                    # End for item in response.json()
                # End else (cas ou response.json()['content']) != 0)

            elif response.status_code == 204:
                banner_msg('ERROR : No file found!')
                fp.write('  >> ERROR : No file found!\n')
            else:
                banner_msg('ERROR : Returned by the request: status of the response = ' + response.status_code)
                fp.write('  >> ERROR : Returned by the request: status of the response = ' + str(response.status_code) + '\n')

        fp.close()

    def download(self):
        """
        Loop over the Shanoir subjects and go download the required datasets
        :return:
        """
        self.set_log_filename()
        self.configure_parser()  # Configure the shanoir_downloader parser
        fp = open(self.log_fn, 'w')
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
    parser.add_argument('-d', '--domain', default='shanoir.irisa.fr', help='The shanoir domain to query.')
    parser.add_argument('-f', '--format', default='nifti', choices=['nifti', 'dicom'], help='The format to download.')
    shanoir_downloader.add_output_folder_argument(parser=parser, required=False)
    # Add the argument for the configuration file
    parser.add_argument('-j', '--config_file', required=True, help='Path to the .json configuration file specifying parameters for shanoir downloading.')
    parser.add_argument('-L', '--longitudinal', required=False, action='store_true', help='Toggle longitudinal approach.')
    parser.add_argument('-a', '--automri', action='store_true', help='Switch to automri file tree.')
    parser.add_argument('-A', '--add_sns', action='store_true', help='Add series number suffix (compatible with -a)')
    # Parse arguments
    args = parser.parse_args()

    # Start configuring the DownloadShanoirDatasetToBids class instance
    stb = DownloadShanoirDatasetToBIDS()
    stb.set_shanoir_username(args.username)
    stb.set_shanoir_domaine(args.domain)
    stb.set_json_config_file(json_file=args.config_file)  # path to json configuration file
    stb.set_shanoir_file_type(shanoir_file_type=args.format)  # Format (dicom or nifti)
    stb.set_download_directory(dl_dir=args.output_folder)  # output folder (if None a default directory is created)
    if args.longitudinal:
        stb.toggle_longitudinal_version()
    if args.automri:
        stb.switch_to_automri_format()
    if args.add_sns:
        if not args.automri:
            print('Warning : -A option is only compatible with -a option.')
        stb.add_series_number_suffix()
    stb.download()


if __name__ == '__main__':
    main()
