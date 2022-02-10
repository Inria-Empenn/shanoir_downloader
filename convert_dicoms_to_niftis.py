import logging
import shutil
from pathlib import Path
import pandas
import dicom2nifti
import SimpleITK as sitk
import shanoir_downloader
from anima_utils import *

parser = shanoir_downloader.create_arg_parser("Convert DICOMs to Niftis")

parser.add_argument('-d', '--dicoms', required=True, help='Path to the folder containing the dicoms.')

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

def convert_dicom_to_nifti(dicom_directory, conversion_info):
    dicom_parent = dicom_directory.parent
    if str(dicom_parent) in [ci['path'] for ci in conversion_info]:
        return dicom_parent
    
    image_converted = False
    
    dicom2nifti_command = lambda: dicom2nifti.convert_directory(dicom_directory, dicom_parent, compression=True, reorient=True)
    mricron_dcm2niix_command = lambda: call(['/home/amasson/apps/dcm2nii/mricron/dcm2niix', '-z', 'y', '-w', '1', '-o', dicom_parent, dicom_directory])
    dcm2niix_command = lambda: call(['dcm2niix', '-z', 'y', '-o', dicom_parent, dicom_directory])
    mcverter_command = lambda: call(['mcverter', '-o', dicom_parent, '-f', 'nifti', '-n', dicom_directory])

    commands = [dicom2nifti_command, mricron_dcm2niix_command, dcm2niix_command, mcverter_command]
    commandNames = ['dicom2nifti', 'mricronDcm2niix', 'dcm2niix', 'mcverter']

    for i, command in enumerate(commands):
        conversion_tool = commandNames[i]
        reoriented = False
        try:
            command()
        except:
            pass
        image_path = get_first_nifti(dicom_parent)
        if image_path is None: continue
        image_converted = image_is_readable(image_path)
        if image_converted: break
        call([animaConvertImage, '-i', image_path, '-R', 'AXIAL', '-o', image_path])
        reoriented = True
        image_converted = image_is_readable(image_path)
        if image_converted: break

    if image_converted:
        shutil.rmtree(str(dicom_directory))
    else:
        print('ERROR: dicom could not be converted!', dicom_directory)
    
    conversion_info.append({'path': str(dicom_parent), 'conversion_tool': conversion_tool, 'reoriented': reoriented, 'converted': image_converted})
    save_conversion_tools(conversion_info)
    return dicom_parent

for dicom in sorted(list(dicoms.iterdir())):
    # Extract the zip file
    zip_files = list(dicom.glob('**/*.zip'))
    for dicom_zip in zip_files:
        print(dicom_zip)
        logging.info(f'    Extracting {dicom_zip}...')
        dicom_folder = dicom_zip.parent / dicom_zip.stem
        dicom_folder.mkdir(exist_ok=True)
        shutil.unpack_archive(str(dicom_zip), str(dicom_folder))

        convert_dicom_to_nifti(dicom_folder, conversion_info)