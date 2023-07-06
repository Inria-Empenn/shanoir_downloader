from datetime import datetime
import time
import os
import sys
import argparse
from pathlib import Path
import logging
import shutil
import subprocess
import requests
import zipfile
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

def anonymize_fields(anonymization_fields, dicom_files, dicom_output_path, sequence_id):
	for dicom_file in dicom_files:
		ds = pydicom.dcmread(str(dicom_file))
		ds.PatientID = sequence_id				# [(0x0010, 0x0010)]
		ds.PatientName = sequence_id 			# [(0x0010, 0x0020)]
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
		ds.save_as(dicom_output_path / dicom_file.name)
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

def download_datasets(args, config=None, all_datasets=None):

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
		elif args.dataset_ids:
			if args.dataset_ids.endswith('.csv') or args.dataset_ids.endswith('.tsv') or args.dataset_ids.endswith('.txt'):
				all_datasets = pandas.read_csv(args.dataset_ids, sep=',' if args.dataset_ids.endswith('.csv') else '\t', dtype=datasets_dtype)
			else:
				all_datasets = pandas.read_excel(args.dataset_ids, dtype=datasets_dtype)
	
	gpg_recipient = args.gpg_recipient or (os.environ['gpg_recipient'] if 'gpg_recipient' in os.environ else None)
	
	if gpg_recipient is None and not args.skip_encryption:
		logging.info('Warning: skipping encryption since gpg_recipient is None (even though skip_encryption is False).')

	output_folder = Path(config['output_folder'])
	
	all_datasets.set_index('sequence_id', inplace=True)
	# Drop duplicates
	all_datasets = all_datasets[~all_datasets.index.duplicated(keep='first')]
	# Drop datasets to ignore from skip_columns
	if args.skip_columns and len(args.skip_columns) > 0:
		for skip_column in args.skip_columns:
			try:
				column_name, value = skip_column.split(':')
				if column_name in all_datasets.columns:
					all_datasets = all_datasets[all_datasets[column_name] != value]
			except Exception as e:
				sys.exit(f'Error while parsing skip_columns argument: {skip_column}\n {e}')

	# Create missing_datasets and downloaded_datasets tsv files
	missing_datasets_path = output_folder / f'missing_datasets.tsv' if args.missing_datasets is None else Path(args.missing_datasets)
	downloaded_datasets_path = output_folder / f'downloaded_datasets.tsv' if args.downloaded_datasets is None else Path(args.downloaded_datasets)

	verified_datasets = pandas.read_csv(args.verified_datasets, index_col='sequence_id', sep=',' if args.verified_datasets.endswith('.csv') else '\t', dtype=datasets_dtype) if args.verified_datasets else None

	missing_datasets = pandas.DataFrame(columns=['sequence_id', 'reason', 'message', 'n_tries']) if not missing_datasets_path.exists() else pandas.read_csv(str(missing_datasets_path), sep='\t', dtype=missing_datasets_dtype)
	missing_datasets.set_index('sequence_id', inplace=True)

	downloaded_datasets = pandas.DataFrame(columns=['sequence_id']) if not downloaded_datasets_path.exists() else pandas.read_csv(str(downloaded_datasets_path), sep='\t', dtype=datasets_dtype)
	downloaded_datasets.set_index('sequence_id', inplace=True)

	anonymization_fields_path = Path(args.anonymization_fields) if args.anonymization_fields else Path(__file__).parent / 'anonymization_fields.tsv'

	if not anonymization_fields_path.exists():
		sys.exit(f'The file {anonymization_fields_path} does not exist. Please provide a valid anonymization_fields file.')

	anonymization_fields = pandas.read_csv(str(anonymization_fields_path), sep='\t')

	datasets_to_download = all_datasets

	raw_folder = output_folder / 'raw'
	processed_folder = output_folder / 'processed'

	# Download and process datasets until there are no more datasets to process 
	# (all the missing datasets are unrecoverable or tried more than args.max_tries times)
	while len(datasets_to_download) > 0:
		
		# datasets_to_download is all_datasets except those already downloaded and those missing which are unrecoverable
		datasets_to_download = all_datasets[~all_datasets.index.isin(downloaded_datasets.index)]
		datasets_max_tries = missing_datasets[missing_datasets['n_tries'] >= args.max_tries].index
		datasets_unrecoverable = missing_datasets[missing_datasets['reason'].isin(args.unrecoverable_errors)].index
		datasets_to_download = datasets_to_download.drop(datasets_max_tries.union(datasets_unrecoverable))

		logging.info(f'There are {len(datasets_to_download)} remaining datasets to download.')

		if len(downloaded_datasets) > 0:
			logging.info(f'{len(downloaded_datasets)} datasets have been downloaded already, over {len(all_datasets)} datasets.')

		n = 1
		for index, row in datasets_to_download.iterrows():

			# Shanoir server reboot every nigth ; between 3 and 4 AM: sleep until shanoir server is awake 
			now = datetime.now()
			if now.hour >= SHANOIR_SHUTDOWN_HOUR and now.hour < SHANOIR_AVAILABLE_HOUR:
				future = datetime(now.year, now.month, now.day, SHANOIR_AVAILABLE_HOUR, 0)
				time.sleep((future-now).total_seconds())
			
			sequence_id = index
			shanoir_name = row['shanoir_name'] if 'shanoir_name' in row else None
			series_description = row['series_description'] if 'series_description' in row else None

			logging.info(f'Downloading dataset {sequence_id} ({n}/{len(datasets_to_download)}), shanoir name: {shanoir_name}, series description: {series_description}')
			n += 1

			# Create the destination folder for this dataset
			destination_folder = raw_folder / sequence_id / 'downloaded_archive'
			destination_folder.mkdir(exist_ok=True, parents=True)
			config['output_folder'] = destination_folder

			# Download the dataset
			try:
				shanoir_downloader.download_dataset(config, sequence_id, 'dicom', True)
			except requests.HTTPError as e:
				message = f'Response status code: {e.response.status_code}, reason: {e.response.reason}'
				if hasattr(e.response, 'error') and e.response.error:
					message += f', response error: {e.response.error}'
				message += str(e)
				missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'status_code_' + str(e.response.status_code), message, raw_folder, args.unrecoverable_errors, missing_datasets_path)
				continue
			except Exception as e:
				missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'unknown_http_error', str(e), raw_folder, args.unrecoverable_errors, missing_datasets_path)
				continue
			
			# List the downloaded zip files
			zip_files = list(destination_folder.glob('*.zip'))

			if len(zip_files) != 1:
				message = f'No zip file was found' if len(zip_files) == 0 else f'{len(zip_files)} zip files were found'
				message += f' in the output directory {destination_folder}.'
				message += f' Downloaded files: { destination_folder.ls() }'
				missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'zip', message, raw_folder, args.unrecoverable_errors, missing_datasets_path)
				continue

			# Extract the zip file
			dicom_zip = zip_files[0]
			
			logging.info(f'    Extracting {dicom_zip}...')
			dicom_folder = destination_folder.parent / f'{sequence_id}' # dicom_zip.stem
			dicom_folder.mkdir(exist_ok=True)
			# shutil.unpack_archive(str(dicom_zip), str(dicom_folder))

			with zipfile.ZipFile(str(dicom_zip), 'r') as zip_ref:
				zip_ref.extractall(str(dicom_folder))
				
			dicom_files = list(dicom_folder.glob('*.dcm'))

			# Error if there are no dicom file found
			if len(dicom_files) == 0:
				missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'nodicom', f'No DICOM file was found in the dicom directory {dicom_folder}.', raw_folder, args.unrecoverable_errors, missing_datasets_path)
				continue
			
			patient_name_in_dicom = None
			series_description_in_dicom = None
			verified = None

			if shanoir_name is not None and series_description is not None:
				# Read the PatientName from the first file, make sure it corresponds to the shanoir_name
				dicom_file = dicom_files[0]
				logging.info(f'    Verifying file {dicom_file}...')
				ds = None
				try:
					ds = pydicom.dcmread(str(dicom_file))
					patient_name_in_dicom = str(ds.PatientName)
					series_description_in_dicom = str(ds.SeriesDescription)

					if patient_name_in_dicom != shanoir_name:
						message = f'Shanoir name {shanoir_name} differs in dicom: {patient_name_in_dicom}'
						logging.error(f'For dataset {sequence_id}: {message}')
						verified = verified_datasets is not None and len(verified_datasets[(verified_datasets.shanoir_name == shanoir_name) & (verified_datasets.patient_name_in_dicom == patient_name_in_dicom)]) > 0
						# missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'content_patient_name', f'Shanoir name {patient_name} differs in dicom: {ds.PatientName}', raw_folder, args.unrecoverable_errors, missing_datasets_path)
						# continue

					if series_description_in_dicom.replace(' ', '') != series_description.replace(' ', ''): 	# or if ds[0x0008, 0x103E].value != series_description:
						message = f'Series description {series_description} differs in dicom: {series_description_in_dicom}'
						logging.error(f'For dataset {sequence_id}: {message}')
						verified = verified_datasets is not None and verified is not False and len(verified_datasets[(verified_datasets.index == sequence_id) & (verified_datasets.series_description == series_description) & (verified_datasets.series_description_in_dicom == series_description_in_dicom)]) > 0
						# missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'content_series_description', f'Series description {series_description} differs in dicom: {ds.SeriesDescription}', raw_folder, args.unrecoverable_errors, missing_datasets_path)
						# continue
				except Exception as e:
					missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'content_read', f'Error while reading DICOM: {e}', raw_folder, args.unrecoverable_errors, missing_datasets_path)
					continue
			
			dicom_zip_to_encrypt = dicom_zip
			anonymized_dicom_folder = None
			final_output = dicom_zip

			if not args.skip_anonymization:

				# Anonymize
				anonymized_dicom_folder = dicom_folder.parent / f'{dicom_folder.name}_anonymized'
				logging.info(f'    Anonymizing dataset to {anonymized_dicom_folder}...')
				
				# extraAnonymizationRules = {}
				# extraAnonymizationRules[(0x0010, 0x0020)] = functools.partial(replace_with_sequence_id, sequence_id) 	# Patient ID
				# extraAnonymizationRules[(0x0010, 0x0010)] = functools.partial(replace_with_sequence_id, sequence_id) 	# Patient's Name
				
				try:
					anonymized_dicom_folder.mkdir(exist_ok=True)
					# import dicomanonymizer
					# dicomanonymizer.anonymize(str(dicom_folder), str(anonymized_dicom_folder), extraAnonymizationRules, True)
					anonymize_fields(anonymization_fields, dicom_files, anonymized_dicom_folder, sequence_id)
				except Exception as e:
					missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'anonymization_error', str(e), raw_folder, args.unrecoverable_errors, missing_datasets_path)
					continue
				
				# Zip the anonymized dicom file
				dicom_zip_to_encrypt = anonymized_dicom_folder.parent / f'{anonymized_dicom_folder.name}.7z'
				logging.info(f'    Compressing dataset to {dicom_zip_to_encrypt}...')
				try:
					shutil.make_archive(str(anonymized_dicom_folder), '7zip', str(anonymized_dicom_folder))
				except Exception as e:
					missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'zip_compression_error', str(e), raw_folder, args.unrecoverable_errors, missing_datasets_path)
					continue
				
				final_output = dicom_zip_to_encrypt

			if not args.skip_encryption and gpg_recipient is not None:

				# Encrypt the zip archive
				encrypted_dicom_zip = dicom_zip_to_encrypt.parent / f'{dicom_zip_to_encrypt.name}.gpg'
				logging.info(f'    Encrypting dataset to {encrypted_dicom_zip}...')
				command = ['gpg', '--output', str(encrypted_dicom_zip), '--encrypt', '--recipient', gpg_recipient, '--trust-model', 'always', str(dicom_zip)]
				try:
					return_code = subprocess.call(command)
				except Exception as e:
					missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'encryption_error', str(e), raw_folder, args.unrecoverable_errors, missing_datasets_path)
					continue
				if return_code != 0:
					missing_datasets = add_missing_dataset(missing_datasets, sequence_id, 'encryption_error', str(e), raw_folder, args.unrecoverable_errors, missing_datasets_path)
				
				final_output = encrypted_dicom_zip

			# Remove and rename files
			
			# Remove zip
			# if not args.keep_intermediate_files:
			# 	shutil.rmtree(dicom_zip)

			# Move "output_folder / raw / sequence_id / downloaded_archive / sequence_name.zip" to "output_folder / raw / sequence_id_sequence_name.zip"
			rename_path(dicom_zip, raw_folder / sequence_id / f'{sequence_id}_{dicom_zip.name}')
			if final_output != dicom_zip:
				rename_path(final_output, processed_folder / sequence_id / final_output.name)

			# If user anonymized and do not keep intermediate files: remove unzipped anonymized dicom, and if user also encrypted: also remove the intermediate zip
			if not args.skip_anonymization:
				if not args.keep_intermediate_files:
					shutil.rmtree(anonymized_dicom_folder)

					if not args.skip_encryption:
						dicom_zip_to_encrypt.unlink()
				else:
					rename_path(anonymized_dicom_folder, processed_folder / sequence_id / anonymized_dicom_folder.name)
					if not args.skip_encryption:
						rename_path(dicom_zip_to_encrypt, processed_folder / sequence_id / dicom_zip_to_encrypt.name)
			
			# Remove dicom
			if not args.keep_intermediate_files:
				shutil.rmtree(dicom_folder)
			
			# Remove downloaded_archive (which should be empty)
			shutil.rmtree(destination_folder)

			# Add to downloaded datastes
			downloaded_datasets = add_downloaded_dataset(all_datasets, downloaded_datasets, missing_datasets, sequence_id, patient_name_in_dicom, series_description_in_dicom, verified, downloaded_datasets_path, missing_datasets_path)
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

	download_datasets(args)
