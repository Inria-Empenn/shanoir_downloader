import zipfile
import logging
import shutil
from pathlib import Path
import pandas
import dicom2nifti
import SimpleITK as sitk
import shanoir_downloader
from anima_utils import *

parser = shanoir_downloader.create_arg_parser("Convert DICOMs to Niftis")

parser.add_argument('-d', '--dicoms', required=True, help='Path to the folder containing the dicoms (raw/).')
parser.add_argument('-ff', '--from_folders', default=False, action='store_true', help='Convert from folders instead of zip archives.')
parser.add_argument('-of', '--output_folder', required=False, help='Path to the output folder (only used when using --from_folders).')
parser.add_argument('-kd', '--keep_dicom', default=False, action='store_true', help='Keep dicoms after conversion.')
parser.add_argument('-sie', '--skip_if_exists', default=True, action='store_true', help='Skip the conversion if nifti already exists.')

args = parser.parse_args()

dicoms = Path(args.dicoms)

conversion_info = []
conversion_info_path = dicoms / 'conversion_info.tsv'

if conversion_info_path.exists():
    df = pandas.read_csv(conversion_info_path, sep='\t', index_col=False)
    conversion_info = df.to_dict('records')

def save_conversion_tools(conversion_info):
    df = pandas.DataFrame.from_records(conversion_info)
    df.to_csv(conversion_info_path, sep='\t', index=False)
    return

def get_first_nifti(path):
    niftis = list(Path(path).glob('**/*.nii.gz'))
    return niftis[0] if len(niftis) > 0 else None

def image_is_readable(image_path):
    if image_path is None: return False
    try:
        sitk.ReadImage(str(image_path))
        return True
    except:
        return False

def convert_dicom_to_nifti(dicom_directory, output_folder):
    output_folder.mkdir(parents=True, exist_ok=True)

    image_converted = False
    
    dicom2nifti_command = lambda: dicom2nifti.convert_directory(dicom_directory, output_folder, compression=True, reorient=True)
    mricron_dcm2niix_command = lambda: call(['/home/amasson/apps/dcm2nii/mricron/dcm2niix', '-z', 'y', '-w', '1', '-o', output_folder, dicom_directory])
    dcm2niix_command = lambda: call(['dcm2niix', '-z', 'y', '-o', output_folder, dicom_directory])
    mcverter_command = lambda: call(['mcverter', '-o', output_folder, '-f', 'nifti', '-n', dicom_directory])

    commands = [dicom2nifti_command, mricron_dcm2niix_command, dcm2niix_command, mcverter_command]
    # commands = [mcverter_command]
    commandNames = ['dicom2nifti', 'mricronDcm2niix', 'dcm2niix', 'mcverter']

    conversion_tool = None
    reconverted = None
    image_converted = None

    for i, command in enumerate(commands):
        conversion_tool = commandNames[i]
        reconverted = False
        try:
            command()
        except:
            pass
        image_path = get_first_nifti(output_folder)
        if image_path is None: continue
        image_converted = image_is_readable(image_path)
        if image_converted: break
        call([animaConvertImage, '-i', image_path, '-o', image_path])
        reconverted = True
        image_converted = image_is_readable(image_path)
        if image_converted: break

    return conversion_tool, reconverted, image_converted

def convert_dicom_to_nifti_if_needed(dicom_directory, output_folder, keep_dicom, conversion_info):

    if str(output_folder) in [ci['path'] for ci in conversion_info]:
        return output_folder
    
    conversion_tool, reconverted, image_converted = convert_dicom_to_nifti(dicom_directory, output_folder)

    if not keep_dicom:
        if image_converted:
            shutil.rmtree(str(dicom_directory))
        else:
            print('ERROR: dicom could not be converted!', dicom_directory)

    conversion_info.append({'path': str(output_folder), 'conversion_tool': conversion_tool, 'reconverted': reconverted, 'converted': image_converted})
    save_conversion_tools(conversion_info)

    return output_folder

for dicom in sorted(list(dicoms.iterdir())):
    if args.from_folders:
        print('Converting', dicom)
        convert_dicom_to_nifti_if_needed(dicom, Path(args.output_folder) / f'{dicom.name}', args.keep_dicom, conversion_info)
    else:
        # Extract the zip file
        nifti = get_first_nifti(dicom)
        if args.skip_if_exists and nifti is not None: continue
        zip_files = list(dicom.glob('*.zip'))
        for dicom_zip in zip_files:
            print(dicom_zip)
            logging.info(f'    Extracting {dicom_zip}...')
            dicom_folder = dicom_zip.parent / dicom_zip.stem
            dicom_folder.mkdir(exist_ok=True)
            with zipfile.ZipFile(str(dicom_zip), 'r') as zip_ref:
                zip_ref.extractall(str(dicom_folder))
            convert_dicom_to_nifti_if_needed(dicom_folder, dicom_folder.parent, args.keep_dicom, conversion_info)