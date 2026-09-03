from datetime import datetime
import time
import os
import sys
import argparse
from pathlib import Path
import logging
import shutil
from dotenv import load_dotenv
import pydicom
import pandas
import numpy as np

import shanoir_downloader
from py7zr import pack_7zarchive, unpack_7zarchive

# register 7zip file format
shutil.register_archive_format('7zip', pack_7zarchive, description='7zip archive')
shutil.register_unpack_format('7zip', ['.7z'], unpack_7zarchive)

SHANOIR_SHUTDOWN_HOUR = 2
SHANOIR_AVAILABLE_HOUR = 5

Path.ls = lambda x: sorted(list(x.iterdir()))

datasets_dtype = {'sequence_id': str, 'shanoir_name': str, 'series_description': str, 'patient_name_in_dicom': str, 'series_description_in_dicom': str}
missing_datasets_dtype = {'sequence_id': str, 'n_tries': np.int64}

def append_row_from_data(df, row, index):
	new_df = pandas.DataFrame.from_records([row], index=index)
	return pandas.concat([df, new_df])

def append_row(df, row):
	new_df = pandas.DataFrame([row])
	return pandas.concat([df, new_df])

def add_missing_dataset(missing_datasets, sequence_id, reason, message, raw_folder, unrecoverable_errors, missing_datasets_path):
	logging.error(f'For dataset {sequence_id}: {message}')
	if sequence_id in missing_datasets.index:
		missing_datasets.loc[sequence_id, 'n_tries'] += 1
		missing_datasets.loc[sequence_id, 'reason'] = reason
		missing_datasets.loc[sequence_id, 'message'] = message
	else:
		missing_datasets = append_row_from_data(missing_datasets, {'reason': str(reason), 'message': str(message), 'n_tries': 1, 'sequence_id': sequence_id}, 'sequence_id')
	if missing_datasets.index.name is None:
		missing_datasets.index.set_names('sequence_id', inplace=True)
	missing_datasets.to_csv(str(missing_datasets_path), sep='\t')
	if (raw_folder / sequence_id).exists() and reason not in unrecoverable_errors:
		shutil.rmtree(raw_folder / sequence_id)
	return missing_datasets

def add_downloaded_dataset(all_datasets, downloaded_datasets, missing_datasets, sequence_id, patient_name_in_dicom, series_description_in_dicom, verified, downloaded_datasets_path, missing_datasets_path):
	if sequence_id in downloaded_datasets.index: return
	downloaded_datasets = append_row(downloaded_datasets, all_datasets.loc[sequence_id])
	downloaded_datasets.loc[sequence_id, 'patient_name_in_dicom'] = patient_name_in_dicom
	downloaded_datasets.loc[sequence_id, 'series_description_in_dicom'] = series_description_in_dicom
	if 'shanoir_name' in all_datasets.columns:
		downloaded_datasets.loc[sequence_id, 'shanoir_name_match'] = patient_name_in_dicom == downloaded_datasets.at[sequence_id, 'shanoir_name']
	if 'series_description' in all_datasets.columns:
		downloaded_datasets.loc[sequence_id, 'series_description_match'] = series_description_in_dicom.replace(' ', '') == downloaded_datasets.at[sequence_id, 'series_description'].replace(' ', '')
	downloaded_datasets.loc[sequence_id, 'verified'] = verified
	if downloaded_datasets.index.name is None:
		downloaded_datasets.index.set_names('sequence_id', inplace=True)
	downloaded_datasets.to_csv(str(downloaded_datasets_path), sep='\t')
	missing_datasets.drop(sequence_id, inplace=True, errors='ignore')
	missing_datasets.to_csv(str(missing_datasets_path), sep='\t')
	return downloaded_datasets

def rename_path(old_path, new_path):
	new_path.parent.mkdir(exist_ok=True, parents=True)
	old_path.rename(new_path)
	return new_path

def anonymize_fields(anonymization_fields, dicom_files, dicom_output_path, sequence_id, patient_id, shanoir_name):
	for dicom_file in dicom_files:
		ds = pydicom.dcmread(str(dicom_file))
		# [(0x0010, 0x0010)]
		ds.PatientID = patient_id if patient_id is not None else sequence_id
		# [(0x0010, 0x0020)]
		ds.PatientName = patient_id if patient_id is not None else sequence_id
		# Update Other Patient IDs
		ds.OtherPatientIDs = sequence_id
		for index, row in anonymization_fields.iterrows():
			codes = row['Code'][1:-1].split(',')
			codes = [int('0x'+code, base=16) for code in codes]
			try:
				data_element = ds[codes[0], codes[1]]
				# if data_element.name.lower() != row['Field Name'].lower():
				# 	logging.info(f"DICOM field {row['Code']} does not correspond to {row['Field Name']} but {data_element.name}. Overwriting {row['Code']} field anyway.")
				data_element.value = ''
			except KeyError as e:
				pass # If the key is not found: juste ignore anonymization
		file_name = dicom_file.name.replace(shanoir_name, patient_id)
		ds.save_as(dicom_output_path / file_name)
	return

def replace_with_sequence_id(sequence_id, dataset, tag):
	dataset.get(tag).value = sequence_id

def create_arg_parser():
	parser = shanoir_downloader.create_arg_parser()

	parser.add_argument('-u', '--username', required=True, help='Your shanoir username.')
	parser.add_argument('-d', '--domain', default='shanoir.irisa.fr', help='The shanoir domain to query.')
	parser.add_argument('-ids', '--dataset_ids', required=False, help='Path to a csv or tsv file containing the dataset ids to download (with the columns "sequence_id" and possibly "shanoir_name" and "series_description").')
	parser.add_argument('-of', '--output_folder', required=True, help='The destination folder where files will be downloaded.')
	parser.add_argument('-gpgr', '--gpg_recipient', help='The gpg recipient (usually an email address) to encrypt the zip files.')
	parser.add_argument('-sa', '--skip_anonymization', action='store_true', help='Skip the DICOM anonymization.')
	parser.add_argument('-se', '--skip_encryption', action='store_true', help='Skip the zip encryption.')
	parser.add_argument('-kif', '--keep_intermediate_files', action='store_true', help='Keep the intermediate files (prevent deleting every files except the final output).')
	parser.add_argument('-mt', '--max_tries', type=int, default=10, help='The number of times to try a download before giving up.')
	parser.add_argument('-ue', '--unrecoverable_errors', default=['status_code_404', 'anonymization_error', 'zip_compression_error', 'encryption_error'], nargs='*', help='The errors which should not trigger a new download.')
	parser.add_argument('-sc', '--skip_columns', default=['previously_sent:1'], nargs='*', help='The columns and values used to ignore data ; formatted as a list of column_name:value_to_ignore. By default, all datasets with previously_sent == 1 are ignored and not downloaded.')
	parser.add_argument('-dids', '--downloaded_datasets', default=None, help='Path to a tsv file containing the already downloaded datasets (generated by this script). Creates the file "downloaded_datasets.tsv" in the given output_folder by default. If the file already exists, it will be taken into account and updated with the new downloads.')
	parser.add_argument('-mids', '--missing_datasets', default=None, help='Path to a tsv file containing the missing datasets (generated by this script). Creates the file "missings_datasets.tsv" in the given output_folder by default. If the file already exists, it will be taken into account and updated with the new errors.')
	parser.add_argument('-vids', '--verified_datasets', default=None, help='Path to a tsv file containing the verified datasets (the file could be downloaded_datasets.tsv generated by this script). Datasets listed in this file will be marked as verified.')
	parser.add_argument('-af', '--anonymization_fields', default=None, help='Path to a tsv file containing the fields to overwrite. Default is anonymization_fields.tsv beside in shanoir_downloader_check.py.')

	shanoir_downloader.add_configuration_arguments(parser)
	shanoir_downloader.add_search_arguments(parser)
	return parser

def download_datasets_from_dict(arg_dict, config=None, all_datasets=None):
	parser = create_arg_parser()
	args = parser.parse_args(['-u', 'username', '-of', 'output_folder'])
	arg_dict = arg_dict if type(arg_dict) is dict else arg_dict.__dict__
	for key in arg_dict:
		setattr(args, key, arg_dict[key])
	download_datasets(args, config, all_datasets)
	return

def download_datasets(args, csv_file, config=None, all_datasets=None):

	if config is None:
		config = shanoir_downloader.initialize(args)

	if all_datasets is None:

		if args.search_text and not args.dataset_ids:
			response = shanoir_downloader.solr_search(config, args)

			if response.status_code == 200:
				json_content = response.json()['content']
				# convert to pandas dataframe
				all_datasets = pandas.DataFrame(json_content)
				all_datasets.rename(columns={'id': 'sequence_id'}, inplace=True)
				if len(all_datasets) == 0:
					sys.exit(f'No datasets found for the search text "{args.search_text}".')
				all_datasets.to_csv(csv_file)

	return

if __name__ == '__main__':
	parser = create_arg_parser()

	args = parser.parse_args()

	load_dotenv()

	if not args.skip_encryption and not args.gpg_recipient and 'gpg_recipient' not in os.environ:
		sys.exit('Please provide --gpg_recipient to encrypt your archives or use --skip_encryption to skip the encryption.')

	if not args.search_text and not args.dataset_ids:
		sys.exit('Please provide --search_text or --datasets_ids.')

	if args.dataset_ids and args.search_text:
		print('Both --dataset_ids and --search_text arguments were provided. The --search_text argument will be ignored.')

	csv_file = 'shanoir_datasets.csv'
	download_datasets(args, csv_file=csv_file)