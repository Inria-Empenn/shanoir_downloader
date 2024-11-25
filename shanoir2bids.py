#!/usr/bin/env python3
DESCRIPTION = """
shanoir2bids.py is a script that allows to download a Shanoir dataset and organise it as a BIDS data structure.
                The script is made to run for every project given some information provided by the user into a ".json"
                configuration file. More details regarding the configuration file in the Readme.md"""
# Script to download and BIDS-like organize data on Shanoir using "shanoir_downloader.py" developed by Arthur Masson


import os
from os.path import join as opj, splitext as ops, exists as ope, dirname as opd
import re
from glob import glob
import sys
from pathlib import Path
from time import time
import zipfile
import datetime
import tempfile
from dateutil import parser
import json
import logging
import shutil

import shanoir_downloader
from dotenv import load_dotenv
from heudiconv.main import workflow

import bids_validator

# Load environment variables
load_dotenv(dotenv_path=opj(opd(__file__), ".env"))


def banner_msg(msg):
    """
    Print a message framed by a banner of "*" characters
    :param msg:
    """
    banner = "*" * (len(msg) + 6)
    print(banner + "\n* ", msg, " *\n" + banner)


# Keys for json configuration file
K_JSON_STUDY_NAME = "study_name"
K_JSON_L_SUBJECTS = "subjects"
K_JSON_SESSION = "session"
K_JSON_DATA_DICT = "data_to_bids"
K_JSON_FIND_AND_REPLACE = "find_and_replace_subject"
K_DCM2NIIX_PATH = "dcm2niix"
K_DCM2NIIX_OPTS = "dcm2niix_options"
K_FIND = "find"
K_REPLACE = "replace"
K_JSON_DATE_FROM = (
    "date_from"  # examinationDate:[2014-03-21T00:00:00Z TO 2014-03-22T00:00:00Z]
)
K_JSON_DATE_TO = (
    "date_to"  # examinationDate:[2014-03-21T00:00:00Z TO 2014-03-22T00:00:00Z]
)
LIST_MANDATORY_KEYS_JSON = [K_JSON_STUDY_NAME, K_JSON_L_SUBJECTS, K_JSON_DATA_DICT]
LIST_AUTHORIZED_KEYS_JSON = LIST_MANDATORY_KEYS_JSON + [
    K_DCM2NIIX_PATH,
    K_DCM2NIIX_OPTS,
    K_JSON_FIND_AND_REPLACE,
    K_JSON_DATE_FROM,
    K_JSON_DATE_TO,
    K_JSON_SESSION,
]

# Define keys for data dictionary
K_BIDS_NAME = "bidsName"
K_BIDS_DIR = "bidsDir"
K_BIDS_SES = "bidsSession"
K_DS_NAME = "datasetName"

# Define Extensions that are dealt so far by (#todo : think of other possible extensions ?)
NIFTI = ".nii"
NIIGZ = ".nii.gz"
JSON = ".json"
BVAL = ".bval"
BVEC = ".bvec"
DCM = ".dcm"

# Shanoir parameters
SHANOIR_FILE_TYPE_NIFTI = "nifti"
SHANOIR_FILE_TYPE_DICOM = "dicom"
DEFAULT_SHANOIR_FILE_TYPE = SHANOIR_FILE_TYPE_NIFTI

# Define error and warning messages when call to dcm2niix is not well configured in the json file
DCM2NIIX_ERR_MSG = """ERROR !!
Conversion from DICOM to nifti can not be performed.
Please provide path to your favorite dcm2niix version in your Shanoir2BIDS .json configuration file.
Add key "{key}" with the absolute path to dcm2niix version to the following file : """
DCM2NIIX_WARN_MSG = """WARNING. You did not provide any option to the dcm2niix call.
If you want to do so, add key "{key}"  to you Shanoir2BIDS configuration file :"""


def create_tmp_directory(path_temporary_directory):
    tmp_dir = Path(path_temporary_directory)
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    pass


def check_date_format(date_to_format):
    # TRUE FORMAT should be: date_format = 'Y-m-dTH:M:SZ'
    try:
        parser.parse(date_to_format)
    # If the date validation goes wrong
    except ValueError:
        print(
            "Incorrect data format, should be YYYY-MM-DDTHH:MM:SSZ (for example: 2020-02-19T00:00:00Z)"
        )


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
    date_from = "*"
    date_to = "*"
    session_id = "*"

    if K_JSON_FIND_AND_REPLACE in data.keys():
        list_fars = data[K_JSON_FIND_AND_REPLACE]
    if K_DCM2NIIX_PATH in data.keys():
        dcm2niix_path = data[K_DCM2NIIX_PATH]
    if K_DCM2NIIX_OPTS in data.keys():
        dcm2niix_opts = data[K_DCM2NIIX_OPTS]
    if K_JSON_DATE_FROM in data.keys():
        if data[K_JSON_DATE_FROM] == "":
            data_from = "*"
        else:
            date_from = data[K_JSON_DATE_FROM]
            check_date_format(date_from)
    if K_JSON_DATE_TO in data.keys():
        if data[K_JSON_DATE_TO] == "":
            data_to = "*"
        else:
            date_to = data[K_JSON_DATE_TO]
            check_date_format(date_to)
    if K_JSON_SESSION in data.keys():
        session_id = data[K_JSON_SESSION]

    # Close json file and return
    f.close()
    return (
        study_id,
        subjects,
        session_id,
        data_dict,
        list_fars,
        dcm2niix_path,
        dcm2niix_opts,
        date_from,
        date_to,
    )


def generate_bids_heuristic_file(
    shanoir2bids_dict,
    path_heuristic_file,
    output_type='("dicom","nii.gz")',
) -> None:
    """Generate heudiconv heuristic.py file from shanoir2bids mapping dict
    Parameters
    ----------
    shanoir2bids_dict :
    path_heuristic_file : path of the python heuristic file (.py)
    """
    if output_type == "dicom":
        outtype = '("dicom",)'
    elif output_type == "nifti":
        outtype = '("nii.gz",)'
    else:
        outtype = '("dicom","nii.gz")'

    heuristic = f"""from heudiconv.heuristics.reproin import create_key

def create_bids_key(dataset):

    template = create_key(subdir=dataset['bidsDir'],file_suffix="_".join(dataset['bidsName'].split('_')[:-1]) + '_' + r"run-{{item:02d}}_" + dataset['bidsName'].split('_')[-1],outtype={outtype})
    return template

def get_dataset_to_key_mapping(shanoir2bids):
    dataset_to_key = dict()
    for dataset in shanoir2bids:
        template = create_bids_key(dataset)
        dataset_to_key[dataset['datasetName']] = template
    return dataset_to_key

def simplify_runs(info):
    info_final = dict()
    for key in info.keys():
        if len(info[key])==1:
            new_template = key[0].replace('run-{{item:02d}}_','')
            new_key = (new_template, key[1], key[2])
            info_final[new_key] = info[key]
        else:
            info_final[key] = info[key]
    return info_final

def infotodict(seqinfo):

    info = dict()
    shanoir2bids = {shanoir2bids_dict}

    dataset_to_key = get_dataset_to_key_mapping(shanoir2bids)
    for seq in seqinfo:
        if seq.series_description in dataset_to_key.keys():
            key = dataset_to_key[seq.series_description]
            if key in info.keys():
                info[key].append(seq.series_id)
            else:
                info[key] = [seq.series_id]
    # remove run- key if not needed (one run only)
    info_final = simplify_runs(info)      
    return info_final
"""

    with open(path_heuristic_file, "w", encoding="utf-8") as file:
        file.write(heuristic)
    pass


class DownloadShanoirDatasetToBIDS:
    """
    class that handles the downloading of shanoir data set and the reformatting as a BIDS data structure
    """

    def __init__(self):
        """
        Initialize the class instance
        """
        self.shanoir_subjects = None  # List of Shanoir subjects
        self.shanoir2bids_dict = (
            None  # Dictionary specifying how to reformat data into BIDS structure
        )
        self.shanoir_username = None  # Shanoir username
        self.shanoir_study_id = None  # Shanoir study ID
        self.shanoir_session_id = None  # Shanoir study ID
        self.shanoir_file_type = SHANOIR_FILE_TYPE_DICOM  # Download File Type (DICOM)
        self.output_file_type = (
            DEFAULT_SHANOIR_FILE_TYPE  # Default Export File Type (NIFTI)
        )
        self.json_config_file = None
        self.list_fars = []  # List of substrings to edit in subjects names
        self.dl_dir = None  # download directory, where data will be stored
        self.parser = None  # Shanoir Downloader Parser
        self.n_seq = 0  # Number of sequences in the shanoir2bids_dict
        self.log_fn = None
        self.dcm2niix_path = None  # Path to the dcm2niix the user wants to use
        self.actual_dcm2niix_path = shutil.which("dcm2niix")
        self.dcm2niix_opts = None  # Options to add to the dcm2niix call
        self.date_from = None
        self.date_to = None
        self.longitudinal = False
        self.to_automri_format = (
            False  # Special filenames for automri (No longer used ! --> BIDS format)
        )
        self.add_sns = False  # Add series number suffix to filename
        self.debug_mode = False  # No debug mode by default

    def set_json_config_file(self, json_file):
        """
        Sets the configuration for the download through a json file
        :param json_file: str, path to the json_file
        """
        self.json_config_file = json_file
        (
            study_id,
            subjects,
            session_id,
            data_dict,
            list_fars,
            dcm2niix_path,
            dcm2niix_opts,
            date_from,
            date_to,
        ) = read_json_config_file(json_file=json_file)
        self.set_shanoir_study_id(study_id=study_id)
        self.set_shanoir_subjects(subjects=subjects)
        self.set_shanoir_session_id(session_id=session_id)
        self.set_shanoir2bids_dict(data_dict=data_dict)
        self.set_shanoir_list_find_and_replace(list_fars=list_fars)
        self.set_dcm2niix_parameters(
            dcm2niix_path=dcm2niix_path, dcm2niix_opts=dcm2niix_opts
        )
        self.set_date_from(date_from=date_from)
        self.set_date_to(date_to=date_to)

    def set_output_file_type(self, outfile_type):
        if outfile_type in [SHANOIR_FILE_TYPE_DICOM, SHANOIR_FILE_TYPE_NIFTI, "both"]:
            self.output_file_type = outfile_type
        else:
            sys.exit("Unknown output file type {}".format(outfile_type))

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

    def export_dcm2niix_config_options(self, path_dcm2niix_options_file):
        # Serializing json
        json_object = json.dumps(self.dcm2niix_opts, indent=4)
        with open(path_dcm2niix_options_file, "w") as file:
            file.write(json_object)

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
            self.dl_dir = "_".join(
                ["shanoir2bids", "download", self.shanoir_study_id, dt]
            )
            print(
                "A NEW DEFAULT directory is created as you did not provide a download directory (-of option)\n\t"
                + self.dl_dir
            )
        else:
            self.dl_dir = dl_dir
        # Create directory if it does not exist
        if not ope(self.dl_dir):
            Path(self.dl_dir).mkdir(parents=True, exist_ok=True)
        self.set_log_filename()

    def set_log_filename(self):
        curr_time = datetime.datetime.now()
        basename = "shanoir_downloader_{:04}{:02}{:02}_{:02}{:02}{:02}.log".format(
            curr_time.year,
            curr_time.month,
            curr_time.day,
            curr_time.hour,
            curr_time.minute,
            curr_time.second,
        )
        self.log_fn = opj(self.dl_dir, basename)

    def toggle_longitudinal_version(self):
        self.longitudinal = True

    def is_correct_dcm2niix(self):
        current_version = Path(self.actual_dcm2niix_path)
        config_version = Path(self.dcm2niix_path)
        if current_version is not None and config_version is not None:
            return config_version.samefile(current_version)
        else:
            return False

    def configure_parser(self):
        """
        Configure the parser and the configuration of the shanoir_downloader
        """
        self.parser = shanoir_downloader.create_arg_parser()
        shanoir_downloader.add_username_argument(self.parser)
        shanoir_downloader.add_domain_argument(self.parser)
        self.parser.add_argument(
            "-f",
            "--format",
            default="dicom",
            choices=["dicom"],
            help="The format to download.",
        )
        shanoir_downloader.add_output_folder_argument(self.parser)
        shanoir_downloader.add_configuration_arguments(self.parser)
        shanoir_downloader.add_search_arguments(self.parser)
        shanoir_downloader.add_ids_arguments(self.parser)

    def is_mapping_bids(self):
        """Check BIDS compliance of filenames/path used in the configuration file"""
        validator = bids_validator.BIDSValidator()

        subjects = self.shanoir_subjects
        list_find_and_replace = self.list_fars
        if list_find_and_replace:
            # normalise subjects name
            normalised_subjects = []
            for subject in subjects:
                for i, far in enumerate(list_find_and_replace):
                    if i == 0:
                        normalised_subject = subject
                    normalised_subject = normalised_subject.replace(
                        far["find"], far["replace"]
                    )
                normalised_subjects.append(normalised_subject)
        else:
            normalised_subjects = subjects

        sessions = list(
            set(
                [d["bidsSession"] for d in self.shanoir2bids_dict if "bidsSession" in d]
            )
        )
        extension = ".nii.gz"

        if not sessions:
            paths = (
                "/"
                + "sub-"
                + subject
                + "/"
                + map["bidsDir"]
                + "/"
                + "sub-"
                + subject
                + "_"
                + map["bidsName"]
                + extension
                for subject in normalised_subjects
                for map in self.shanoir2bids_dict
            )
        else:
            paths = (
                "/"
                + "sub-"
                + subject
                + "/"
                + "ses-"
                + map["bidsSession"]
                + "/"
                + map["bidsDir"]
                + "/"
                + "sub-"
                + subject
                + "_"
                + "ses-"
                + map["bidsSession"]
                + "_"
                + map["bidsName"]
                + extension
                for subject in normalised_subjects
                for map in self.shanoir2bids_dict
            )

        bids_errors = [p for p in paths if not validator.is_bids(p)]

        if not bids_errors:
            return True, bids_errors
        else:
            return False, bids_errors

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
        fp = open(self.log_fn, "a")

        # Real Shanoir2Bids mapping (handle case when solr search term are included)
        bids_mapping = []

        # Manual temporary directories containing dowloaded DICOM.zip and extracted files
        # (temporary directories that can be kept are not supported by pythn <3.1
        tmp_dicom = Path(self.dl_dir).joinpath("tmp_dicoms", subject_to_search)
        tmp_archive = Path(self.dl_dir).joinpath(
            "tmp_archived_dicoms", subject_to_search
        )
        create_tmp_directory(tmp_archive)
        create_tmp_directory(tmp_dicom)

        # BIDS subject id (search and replace)
        bids_subject_id = subject_to_search
        for far in self.list_fars:
            bids_subject_id = bids_subject_id.replace(far[K_FIND], far[K_REPLACE])

        bids_seq_session = None

        # Loop on each sequence defined in the dictionary
        for seq in range(self.n_seq):
            # Isolate elements that are called many times
            shanoir_seq_name = self.shanoir2bids_dict[seq][
                K_DS_NAME
            ]  # Shanoir sequence name (OLD)
            bids_seq_subdir = self.shanoir2bids_dict[seq][
                K_BIDS_DIR
            ]  # Sequence BIDS subdirectory name (NEW)
            bids_seq_name = self.shanoir2bids_dict[seq][
                K_BIDS_NAME
            ]  # Sequence BIDS nickname (NEW)
            if self.longitudinal:
                bids_seq_session = self.shanoir2bids_dict[seq][
                    K_BIDS_SES
                ]  # Sequence BIDS nickname (NEW)
            else:
                bids_seq_session = None

            # Print message concerning the sequence that is being downloaded
            print(
                "\t-",
                bids_seq_name,
                subject_to_search,
                "[" + str(seq + 1) + "/" + str(self.n_seq) + "]",
            )

            request_terms = [
                self.shanoir_study_id,
                shanoir_seq_name,
                subject_to_search,
                self.shanoir_session_id,
                self.date_from,
                self.date_to,
            ]

            def escape_solr_special_characters(s):
                # List of Solr special characters
                special_characters = r'\+\-\!\(\)\{\}\[\]\^"~\?:\\'
                # remove \* from special characters to be able to use wildcards in solr
                # Add more if needed
                escape_pattern = re.compile(r'([{}])'.format(special_characters))
                return escape_pattern.sub(r'\\\1', s)

            escaped_request_terms = {s: escape_solr_special_characters(s) for s in request_terms}

            # Initialize the parser
            search_txt = (
                "studyName:"
                + escaped_request_terms[self.shanoir_study_id].replace(" ", "?")
                + " AND datasetName:"
                + escaped_request_terms[shanoir_seq_name].replace(" ", "?")
                + " AND subjectName:"
                + escaped_request_terms[subject_to_search].replace(" ", "?")
                + " AND examinationComment:"
                + escaped_request_terms[self.shanoir_session_id].replace(" ", "*")
                + " AND examinationDate:["
                + self.date_from
                + " TO "
                + self.date_to
                + "]"
            )

            print(search_txt)

            args = self.parser.parse_args(
                [
                    "-u",
                    self.shanoir_username,
                    "-d",
                    self.shanoir_domaine,
                    "-of",
                    str(tmp_archive),
                    "-em",
                    "-st",
                    search_txt,
                    "-s",
                    "200",
                    "-f",
                    self.shanoir_file_type,
                    "-so",
                    "id,ASC",
                    "-t",
                    "500",
                ]
            )  # Increase time out for heavy files

            config = shanoir_downloader.initialize(args)
            response = shanoir_downloader.solr_search(config, args)

            # From response, process the data
            # Print the number of items found and a list of these items
            if response.status_code == 200:
                # Invoke shanoir_downloader to download all the data
                shanoir_downloader.download_search_results(config, args, response)

                if len(response.json()["content"]) == 0:
                    warn_msg = """WARNING ! The Shanoir request returned 0 result. Make sure the following search text returns 
a result on the website.
Search Text : "{}" \n""".format(
                        search_txt
                    )
                    print(warn_msg)
                    fp.write(warn_msg)
                else:
                    for item in response.json()["content"]:
                        # Define subject_id
                        # su_id = item["subjectName"]
                        # If the user has defined a list of edits to subject names... then do the find and replace
                        # weird to do it at the dataset level

                        # ID of the subject (sub-*)
                        # read_bids_subject_id = su_id

                        # correct BIDS mapping of the searched dataset
                        bids_seq_mapping = {
                            "datasetName": item["datasetName"],
                            "bidsDir": bids_seq_subdir,
                            "bidsName": bids_seq_name,
                            "bids_subject_id": bids_subject_id,
                        }

                        if not self.longitudinal:
                            bids_seq_session = None

                        bids_seq_mapping["bids_session_id"] = bids_seq_session

                        bids_mapping.append(bids_seq_mapping)

                        # Write the information on the data in the log file
                        fp.write("- datasetId = " + str(item["datasetId"]) + "\n")
                        fp.write("  -- studyName: " + item["studyName"] + "\n")
                        fp.write("  -- subjectName: " + item["subjectName"] + "\n")
                        fp.write("  -- session: " + item["examinationComment"] + "\n")
                        fp.write("  -- datasetName: " + item["datasetName"] + "\n")
                        fp.write(
                            "  -- examinationDate: " + item["examinationDate"] + "\n"
                        )
                        fp.write("  >> Downloading archive OK\n")

                        # Extract the downloaded archive
                        dl_archive = glob(opj(tmp_archive, "*" + item["id"] + "*.zip"))[
                            0
                        ]
                        with zipfile.ZipFile(dl_archive, "r") as zip_ref:
                            extraction_dir = opj(tmp_dicom, item["id"])
                            zip_ref.extractall(extraction_dir)

                        fp.write(
                            "  >> Extraction of all files from archive '"
                            + dl_archive
                            + " into "
                            + extraction_dir
                            + "\n"
                        )

            elif response.status_code == 204:
                banner_msg("ERROR : No file found!")
                fp.write("  >> ERROR : No file found!\n")
            else:
                banner_msg(
                    "ERROR : Returned by the request: status of the response = "
                    + response.status_code
                )
                fp.write(
                    "  >> ERROR : Returned by the request: status of the response = "
                    + str(response.status_code)
                    + "\n"
                )

        # Launch DICOM to BIDS conversion using heudiconv + heuristic file + dcm2niix options
        with tempfile.NamedTemporaryFile(
            mode="r+", encoding="utf-8", dir=self.dl_dir, suffix=".py"
        ) as heuristic_file:
            # Generate Heudiconv heuristic file from configuration.json mapping
            generate_bids_heuristic_file(
                bids_mapping, heuristic_file.name, output_type=self.output_file_type
            )
            with tempfile.NamedTemporaryFile(
                mode="r+", encoding="utf-8", dir=self.dl_dir, suffix=".json"
            ) as dcm2niix_config_file:
                self.export_dcm2niix_config_options(dcm2niix_config_file.name)
                workflow_params = {
                    "files": glob(opj(tmp_dicom, "*", "*.dcm"), recursive=True),
                    "outdir": opj(self.dl_dir, self.shanoir_study_id).replace(" ", ""),
                    "subjs": [bids_subject_id],
                    "converter": "dcm2niix",
                    "heuristic": heuristic_file.name,
                    "bids_options": "--bids",
                    # "with_prov": True,
                    "debug": self.debug_mode,
                    "dcmconfig": dcm2niix_config_file.name,
                    "datalad": True,
                    "minmeta": True,
                    "grouping": "all",  # other options are too restrictive (tested on EMISEP)
                    "overwrite": True,
                }

                if self.longitudinal:
                    workflow_params["session"] = bids_seq_session
                try:
                    workflow(**workflow_params)
                except AssertionError:
                    error = (
                        f" \n >> WARNING : No DICOM file available for conversion for subject {subject_to_search} \n "
                        f"If some datasets are to be downloaded check log file and your configuration file syntax \n "
                    )
                    print(error)
                    fp.write(error)
                finally:
                    if not self.debug_mode:
                        shutil.rmtree(tmp_archive, ignore_errors=True)
                        shutil.rmtree(tmp_dicom, ignore_errors=True)
                        # beware of side effects
                        shutil.rmtree(tmp_archive.parent, ignore_errors=True)
                        shutil.rmtree(tmp_dicom.parent, ignore_errors=True)

                    fp.close()

    def download(self):
        """
        Loop over the Shanoir subjects and go download the required datasets
        :return:
        """
        self.set_log_filename()
        self.configure_parser()  # Configure the shanoir_downloader parser
        fp = open(self.log_fn, "w")
        if self.shanoir_subjects is not None:
            for subject_to_search in self.shanoir_subjects:
                t_start_subject = time()
                self.download_subject(subject_to_search=subject_to_search)
                dur_min = int((time() - t_start_subject) // 60)
                dur_sec = int((time() - t_start_subject) % 60)
                end_msg = (
                    "Downloaded dataset for subject "
                    + subject_to_search
                    + " in {}m{}s".format(dur_min, dur_sec)
                )
                banner_msg(end_msg)
        else:
            print(f"No Shanoir Subjects to Download")


def main():
    # Parse argument for the script
    parser = shanoir_downloader.create_arg_parser(description=DESCRIPTION)
    # Use username and output folder arguments from shanoir_downloader
    shanoir_downloader.add_username_argument(parser)
    parser.add_argument(
        "-d",
        "--domain",
        default="shanoir.irisa.fr",
        help="The shanoir domain to query.",
    )

    parser.add_argument(
        "--outformat",
        default="both",
        choices=["nifti", "dicom", "both"],
        help="The format to download.",
    )

    shanoir_downloader.add_output_folder_argument(parser=parser, required=False)
    # Add the argument for the configuration file
    parser.add_argument(
        "-j",
        "--config_file",
        required=True,
        help="Path to the .json configuration file specifying parameters for shanoir downloading.",
    )
    parser.add_argument(
        "-L",
        "--longitudinal",
        required=False,
        action="store_true",
        help="Toggle longitudinal approach.",
    )
    parser.add_argument(
        "--debug",
        required=False,
        action="store_true",
        help="Toggle debug mode (keep temporary directories)",
    )

    args = parser.parse_args()

    # Start configuring the DownloadShanoirDatasetToBids class instance
    stb = DownloadShanoirDatasetToBIDS()
    stb.set_shanoir_username(args.username)
    stb.set_shanoir_domaine(args.domain)
    stb.set_json_config_file(
        json_file=args.config_file
    )  # path to json configuration file
    stb.set_output_file_type(args.outformat)
    stb.set_download_directory(
        dl_dir=args.output_folder
    )  # output folder (if None a default directory is created)

    if args.debug:
        stb.debug_mode = True

    if args.longitudinal:
        stb.toggle_longitudinal_version()

    if not stb.is_correct_dcm2niix():
        print(
            f"WARNING!: Current dcm2niix path {stb.actual_dcm2niix_path} is different from dcm2niix configured path {stb.dcm2niix_path}"
        )
    else:
        if not stb.is_mapping_bids()[0]:
            print(
                f" WARNING !: Provided BIDS keys {stb.is_mapping_bids()[1]} are not BIDS compliant check syntax in provided configuration file {args.config_file}"
            )
        stb.download()


if __name__ == "__main__":
    main()
